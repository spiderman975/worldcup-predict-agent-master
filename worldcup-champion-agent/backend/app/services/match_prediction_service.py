"""Single-match prediction orchestration and persistence."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from app.agent.match_pipeline import MatchPredictionPipeline
from app.services.team_analysis_service import get_team_ratings_and_odds, search_teams


PREDICTION_STORE = Path(__file__).resolve().parents[3] / "data" / "snapshots" / "match_predictions.json"
BASE_MATCH_TIME = datetime(2026, 6, 11, 20, 0, 0)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")

TEAM_ALIASES: dict[str, list[str]] = {
    "FRANCE": ["france", "法国", "法兰西", "法"],
    "SPAIN": ["spain", "西班牙", "西"],
    "BRAZIL": ["brazil", "巴西"],
    "ARGENTINA": ["argentina", "阿根廷"],
    "GERMANY": ["germany", "德国"],
    "ENGLAND": ["england", "英格兰", "英国", "英"],
    "ITALY": ["italy", "意大利"],
    "PORTUGAL": ["portugal", "葡萄牙"],
    "NETHERLANDS": ["netherlands", "holland", "荷兰"],
    "BELGIUM": ["belgium", "比利时"],
    "MEXICO": ["mexico", "墨西哥"],
    "URUGUAY": ["uruguay", "乌拉圭"],
    "CROATIA": ["croatia", "克罗地亚"],
    "NORWAY": ["norway", "挪威"],
    "USA": ["usa", "united states", "美国"],
}

SPECIAL_MATCH_ALIASES: dict[str, tuple[str, str]] = {
    "法西大战": ("FRANCE", "SPAIN"),
    "西法大战": ("FRANCE", "SPAIN"),
    "英法大战": ("ENGLAND", "FRANCE"),
    "法英大战": ("ENGLAND", "FRANCE"),
    "巴阿大战": ("BRAZIL", "ARGENTINA"),
    "阿巴大战": ("BRAZIL", "ARGENTINA"),
    "德意大战": ("GERMANY", "ITALY"),
    "意德大战": ("GERMANY", "ITALY"),
}


def _team_name_map() -> dict[str, str]:
    from app.services.data_scout_service import data_scout_service

    return {team["team_id"]: team["name"] for team in data_scout_service.list_teams()}


def _team_id_by_name() -> dict[str, str]:
    from app.services.data_scout_service import data_scout_service

    return {team["name"].casefold(): team["team_id"] for team in data_scout_service.list_teams()}


def _parse_match_time(value: str | None, index: int | None = None) -> datetime:
    if value:
        raw = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is not None:
                return parsed.astimezone(BEIJING_TZ).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    return BASE_MATCH_TIME + timedelta(days=index or 0)


GROUP_STAGE_MATCH_COUNT = 72
UNKNOWN_TEAM = "TBD"


def _db_stage_name(stage: int, stage_one_index: int | None = None) -> str:
    if stage == 1:
        if stage_one_index is not None and stage_one_index > GROUP_STAGE_MATCH_COUNT:
            return "round_of_32"
        return "group"
    return {
        2: "round_of_16",
        3: "quarter",
        4: "semi",
        5: "third_place",
        6: "final",
    }.get(stage, str(stage))


def _list_database_schedule() -> list[dict[str, Any]]:
    from app.services.data_scout_service import data_scout_service
    from data.database import get_active_season

    data_scout_service.ensure_database()
    active_season = get_active_season()
    with data_scout_service._connection() as connection:
        _ensure_terminal_fixtures(connection, active_season)
        rows = connection.execute(
            """
            SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status, season
            FROM matches
            WHERE season = ?
            ORDER BY played_at IS NULL, played_at, id
            """,
            (active_season,),
        ).fetchall()

    ids = _team_id_by_name()
    schedule: list[dict[str, Any]] = []
    stage_one_seen = 0
    for index, row in enumerate(rows):
        stage_number = int(row["stage"])
        if stage_number == 1:
            stage_one_seen += 1
        played_at = _parse_match_time(row["played_at"], index)
        home_score = int(row["home_score"])
        away_score = int(row["away_score"])
        finished = bool(row["is_real"]) and home_score >= 0 and away_score >= 0
        home_name = str(row["home_team"])
        away_name = str(row["away_team"])
        external_status = str(row["status"] or "").strip().lower()
        base_status = "finished" if finished else _display_status(external_status, played_at)
        match_id = str(row["match_id"])
        schedule.append(
            {
                "match_id": match_id,
                "stage": _db_stage_name(stage_number, stage_one_seen if stage_number == 1 else None),
                "stage_number": stage_number,
                "group": None,
                "home_team_id": ids.get(home_name.casefold(), home_name),
                "away_team_id": ids.get(away_name.casefold(), away_name),
                "home_team_name": home_name,
                "away_team_name": away_name,
                "match_time_raw": row["played_at"],
                "match_time": played_at.isoformat(),
                "match_date": played_at.date().isoformat(),
                "venue": "TBD",
                "status": base_status,
                "source_status": external_status or None,
                "actual_home_score": home_score if home_score >= 0 else None,
                "actual_away_score": away_score if away_score >= 0 else None,
                "is_database_match": True,
                "saved_prediction": _saved_prediction_summary(match_id),
                "season": int(row["season"] or active_season),
            }
        )
    return schedule


def _ensure_terminal_fixtures(connection: Any, season: int) -> None:
    """Keep fixed late-knockout slots visible even before both teams are known."""
    if int(season) != 2026:
        return

    rows = connection.execute(
        """
        SELECT match_id, home_team, away_team, home_score, away_score, is_real
        FROM matches
        WHERE match_id IN ('s4_france_spain', 's4_england_argentina')
        """
    ).fetchall()
    semis = {row["match_id"]: row for row in rows}

    def winner(match_id: str) -> str:
        row = semis.get(match_id)
        if not row or not row["is_real"] or row["home_score"] == row["away_score"]:
            return UNKNOWN_TEAM
        return row["home_team"] if row["home_score"] > row["away_score"] else row["away_team"]

    def loser(match_id: str) -> str:
        row = semis.get(match_id)
        if not row or not row["is_real"] or row["home_score"] == row["away_score"]:
            return UNKNOWN_TEAM
        return row["away_team"] if row["home_score"] > row["away_score"] else row["home_team"]

    _upsert_terminal_fixture(
        connection,
        match_id="s5_third_place",
        stage=5,
        home_team=loser("s4_france_spain"),
        away_team=loser("s4_england_argentina"),
        played_at="2026-07-18T21:00:00Z",
    )
    _upsert_terminal_fixture(
        connection,
        match_id="s6_final",
        stage=6,
        home_team=winner("s4_france_spain"),
        away_team=winner("s4_england_argentina"),
        played_at="2026-07-19T19:00:00Z",
    )


def _upsert_terminal_fixture(
    connection: Any,
    *,
    match_id: str,
    stage: int,
    home_team: str,
    away_team: str,
    played_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO matches (match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status, season, competition_code)
        VALUES (?, ?, ?, ?, -1, -1, 0, ?, 'scheduled', 2026, 'WC')
        ON CONFLICT(match_id) DO UPDATE SET
            stage = excluded.stage,
            home_team = CASE
                WHEN matches.is_real = 0 AND matches.home_team = ? THEN excluded.home_team
                WHEN matches.is_real = 0 AND excluded.home_team <> ? THEN excluded.home_team
                ELSE matches.home_team
            END,
            away_team = CASE
                WHEN matches.is_real = 0 AND matches.away_team = ? THEN excluded.away_team
                WHEN matches.is_real = 0 AND excluded.away_team <> ? THEN excluded.away_team
                ELSE matches.away_team
            END,
            played_at = excluded.played_at,
            status = CASE WHEN matches.is_real = 0 THEN excluded.status ELSE matches.status END
        """,
        (match_id, stage, home_team, away_team, played_at, UNKNOWN_TEAM, UNKNOWN_TEAM, UNKNOWN_TEAM, UNKNOWN_TEAM),
    )


def normalize_match(match: dict[str, Any], index: int | None = None) -> dict[str, Any]:
    """Return a UI-safe match record with valid display time and team names."""

    names = _team_name_map()
    item = dict(match)
    raw_time = str(item.get("match_time") or "")
    display_time = _parse_match_time(raw_time, index)
    item["match_time_raw"] = raw_time
    item["match_time"] = display_time.isoformat()
    item["match_date"] = display_time.date().isoformat()
    item["home_team_name"] = names.get(item["home_team_id"], item["home_team_id"])
    item["away_team_name"] = names.get(item["away_team_id"], item["away_team_id"])
    item.setdefault("status", "scheduled")
    item.setdefault("actual_home_score", None)
    item.setdefault("actual_away_score", None)
    return item


def list_schedule() -> list[dict[str, Any]]:
    return _list_database_schedule()


def get_match(match_id: str) -> dict[str, Any] | None:
    for match in list_schedule():
        if match["match_id"].lower() == match_id.lower():
            return match
    return None


def _load_store() -> dict[str, Any]:
    if not PREDICTION_STORE.exists():
        return {}
    return json.loads(PREDICTION_STORE.read_text(encoding="utf-8"))


def _save_store(store: dict[str, Any]) -> None:
    PREDICTION_STORE.parent.mkdir(parents=True, exist_ok=True)
    PREDICTION_STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def get_saved_match_prediction(match_id: str) -> dict[str, Any] | None:
    return _load_store().get(match_id.upper())


def _saved_prediction_summary(match_id: str) -> dict[str, Any] | None:
    record = get_saved_match_prediction(match_id)
    if not record:
        return None
    prediction = record.get("prediction") or {}
    return {
        "predicted_home_score": prediction.get("predicted_home_score"),
        "predicted_away_score": prediction.get("predicted_away_score"),
        "home_win_prob": prediction.get("home_win_prob"),
        "draw_prob": prediction.get("draw_prob"),
        "away_win_prob": prediction.get("away_win_prob"),
        "mode": record.get("mode"),
        "created_at": record.get("created_at"),
        "explanation": record.get("analysis") or prediction.get("explanation") or (record.get("explanation") or {}).get("text"),
    }


def _display_status(source_status: str, match_time: datetime) -> str:
    if source_status in {"postponed", "suspended"}:
        return "postponed"
    if source_status in {"cancelled", "canceled"}:
        return "cancelled"
    now = datetime.now(BEIJING_TZ).replace(tzinfo=None)
    if match_time <= now < match_time + timedelta(hours=3):
        return "live"
    if now >= match_time + timedelta(hours=3):
        return "result_pending"
    return "scheduled"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _alias_team_hits(text: str) -> list[str]:
    lowered = _normalize_text(text)
    hits: list[str] = []
    for team_id, aliases in TEAM_ALIASES.items():
        for alias in aliases:
            if alias.casefold() in lowered or alias in text:
                hits.append(team_id)
                break
    for phrase, pair in SPECIAL_MATCH_ALIASES.items():
        if phrase in text:
            hits.extend(pair)
    deduped: list[str] = []
    for team_id in hits:
        if team_id not in deduped:
            deduped.append(team_id)
    return deduped


def _computed_status(match: dict[str, Any], now: datetime | None = None) -> str:
    if match.get("actual_home_score") is not None and match.get("actual_away_score") is not None:
        return "finished"
    now = now or datetime.now(BEIJING_TZ).replace(tzinfo=None)
    match_time = _parse_match_time(str(match.get("match_time") or match.get("match_time_raw") or ""))
    if now >= match_time + timedelta(hours=3):
        return "finished_unverified"
    if match_time <= now < match_time + timedelta(hours=3):
        return "live_or_recent"
    return "scheduled"


def resolve_match_query(query: str, date_hint: str | None = None) -> dict[str, Any]:
    """Resolve natural language like '法西大战' into one or more schedule matches."""

    schedule = list_schedule()
    lowered = query.lower()
    candidates: list[tuple[float, dict[str, Any], list[str]]] = []

    for match in schedule:
        reasons: list[str] = []
        score = 0.0
        if match["match_id"].lower() in lowered:
            score += 100
            reasons.append("命中比赛 ID")
        if date_hint and match.get("match_date") == date_hint:
            score += 10
            reasons.append("命中日期")
        haystack = " ".join(
            [
                match["home_team_id"],
                match["away_team_id"],
                match["home_team_name"],
                match["away_team_name"],
                match["match_date"],
            ]
        ).casefold()
        for term in [part for part in re.split(r"[\s,，。:：/\\-]+", lowered) if part]:
            if term and term in haystack:
                score += 3
                reasons.append(f"命中关键词 {term}")

        alias_hits = _alias_team_hits(query)
        if alias_hits:
            pair = {match["home_team_id"].upper(), match["away_team_id"].upper()}
            hit_set = set(alias_hits)
            if len(hit_set & pair) == 2:
                score += 80
                reasons.append("命中双方球队别名")
            elif len(hit_set & pair) == 1:
                score += 15
                reasons.append("命中单方球队别名")

        if score > 0:
            enriched = dict(match)
            enriched["computed_status"] = _computed_status(match)
            candidates.append((score, enriched, reasons))

    candidates.sort(key=lambda item: item[0], reverse=True)
    top = [
        {
            "confidence": min(0.99, round(score / 100, 2)),
            "match": match,
            "reasons": reasons,
        }
        for score, match, reasons in candidates[:5]
    ]
    if not top:
        return {"resolved": False, "query": query, "candidates": [], "message": "未能从赛程中解析出明确比赛"}

    best = top[0]
    second_confidence = top[1]["confidence"] if len(top) > 1 else 0
    resolved = best["confidence"] >= 0.5 and best["confidence"] - second_confidence >= 0.15
    return {
        "resolved": resolved,
        "query": query,
        "match_id": best["match"]["match_id"] if resolved else None,
        "match": best["match"] if resolved else None,
        "candidates": top,
        "message": "已解析出唯一比赛" if resolved else "找到多个候选比赛，需要用户确认",
    }


def get_match_context(match_id: str) -> dict[str, Any]:
    from app.services.data_scout_service import data_scout_service

    match = get_match(match_id)
    if not match:
        return {"found": False, "match_id": match_id, "message": "未找到比赛"}

    teams = data_scout_service.list_teams()
    now = datetime.now(BEIJING_TZ).replace(tzinfo=None)
    computed_status = _computed_status(match, now)
    database_status = str(match.get("status") or "")
    warnings: list[str] = []
    has_score = match.get("actual_home_score") is not None and match.get("actual_away_score") is not None
    if computed_status.startswith("finished") and not has_score:
        warnings.append("按北京时间推算比赛应已结束，但数据库尚无真实比分")
    if database_status == "scheduled" and computed_status.startswith("finished"):
        warnings.append("数据库状态仍为 scheduled，但当前时间已超过比赛开赛 3 小时")
    if database_status == "finished" and not has_score:
        warnings.append("数据库标记已完赛，但真实比分字段为空")

    return {
        "found": True,
        "current_time_beijing": now.isoformat(),
        "match": match,
        "computed_status": computed_status,
        "database_status": database_status,
        "actual_score": {
            "home": match.get("actual_home_score"),
            "away": match.get("actual_away_score"),
            "has_score": has_score,
        },
        "teams": data_scout_service.match_context(match, teams),
        "saved_prediction": get_saved_match_prediction(match_id),
        "data_quality": {
            "has_score": has_score,
            "status_consistent": not warnings,
            "warnings": warnings,
        },
    }


ProgressEmit = Callable[[str, str, str | None, dict[str, Any] | None], Awaitable[None]]


def _trace_item(trace: list[dict[str, Any]], agent: str) -> dict[str, Any]:
    return next((item for item in trace if item.get("agent") == agent), {})


def _analysis_context(
    match: dict[str, Any],
    prediction: dict[str, Any],
    explanation: dict[str, Any],
    ratings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    home = ratings[match["home_team_id"]]
    away = ratings[match["away_team_id"]]
    trace = prediction.get("agent_trace") or []
    return {
        "match": {
            "match_id": match["match_id"],
            "stage": match.get("stage"),
            "home_team_name": match["home_team_name"],
            "away_team_name": match["away_team_name"],
            "match_time": match.get("match_time"),
            "status": match.get("status"),
        },
        "prediction": {
            "score": f"{prediction['predicted_home_score']}-{prediction['predicted_away_score']}",
            "winner_name": prediction.get("winner_name") or "平局",
            "home_win_prob": prediction.get("home_win_prob"),
            "draw_prob": prediction.get("draw_prob"),
            "away_win_prob": prediction.get("away_win_prob"),
            "confidence": prediction.get("confidence"),
            "top_scores": prediction.get("top_scores", []),
        },
        "home_metrics": {
            "name": home["name"],
            "overall_rating": home.get("overall_rating"),
            "attack_strength": home.get("attack_strength"),
            "defense_strength": home.get("defense_strength"),
            "recent_form": home.get("recent_form"),
        },
        "away_metrics": {
            "name": away["name"],
            "overall_rating": away.get("overall_rating"),
            "attack_strength": away.get("attack_strength"),
            "defense_strength": away.get("defense_strength"),
            "recent_form": away.get("recent_form"),
        },
        "metric_gaps": {
            "overall_gap_home_minus_away": round(float(home.get("overall_rating", 0)) - float(away.get("overall_rating", 0)), 4),
            "attack_gap_home_minus_away": round(float(home.get("attack_strength", 0)) - float(away.get("attack_strength", 0)), 4),
            "defense_gap_home_minus_away": round(float(home.get("defense_strength", 0)) - float(away.get("defense_strength", 0)), 4),
            "form_gap_home_minus_away": round(float(home.get("recent_form", 0)) - float(away.get("recent_form", 0)), 4),
        },
        "agent_trace": trace,
        "narration_text": prediction.get("explanation") or explanation.get("text"),
    }


def _build_rule_match_analysis(
    match: dict[str, Any],
    prediction: dict[str, Any],
    explanation: dict[str, Any],
    ratings: dict[str, dict[str, Any]],
) -> str:
    home = match["home_team_name"]
    away = match["away_team_name"]
    home_rating = ratings[match["home_team_id"]]
    away_rating = ratings[match["away_team_id"]]
    winner = prediction.get("winner_name") or "平局"
    score = f"{prediction['predicted_home_score']}-{prediction['predicted_away_score']}"
    home_prob = float(prediction.get("home_win_prob") or 0)
    draw_prob = float(prediction.get("draw_prob") or 0)
    away_prob = float(prediction.get("away_win_prob") or 0)
    overall_gap = float(home_rating.get("overall_rating", 0)) - float(away_rating.get("overall_rating", 0))
    attack_gap = float(home_rating.get("attack_strength", 0)) - float(away_rating.get("attack_strength", 0))
    defense_gap = float(home_rating.get("defense_strength", 0)) - float(away_rating.get("defense_strength", 0))
    probs = sorted(
        [("主胜", home_prob), ("平局", draw_prob), ("客胜", away_prob)],
        key=lambda item: item[1],
        reverse=True,
    )
    confidence_gap = probs[0][1] - probs[1][1] if len(probs) > 1 else probs[0][1]
    confidence = "较高" if confidence_gap >= 0.18 else "中等" if confidence_gap >= 0.08 else "接近"

    trace = prediction.get("agent_trace") or []
    scout = _trace_item(trace, "DataScoutAgent")
    analyst = _trace_item(trace, "FootballAnalystAgent")
    simulation = _trace_item(trace, "SimulationAgent")
    critic = _trace_item(trace, "CriticAgent")
    factors = [str(item) for item in analyst.get("factors", []) if item]
    factor_lines = factors[:4] or [prediction.get("explanation") or explanation.get("text") or "当前模型主要依据球队评分、攻防强度和固定比分模拟结果。"]
    warnings = [str(item) for item in critic.get("warnings", []) if item]
    warning_text = "；".join(warnings[:2]) if warnings else "未发现比分与胜者字段冲突，但单场比赛仍存在临场阵容、红黄牌和战术调整等不确定性。"

    return "\n".join(
        [
            "结论",
            f"本场预测为 {home} {score} {away}，结果倾向 {winner}。模型给出的最高概率方向是{probs[0][0]}（{probs[0][1]:.1%}），与第二选择的差距为 {confidence_gap:.1%}，因此信心等级为{confidence}。",
            "",
            "实力与数据依据",
            f"1. 数据侦察：{scout.get('summary') or '已读取双方本地数据库资料。'}",
            f"2. 攻防对比：{home} 进攻 {home_rating.get('attack_strength', 0):.2f}、防守 {home_rating.get('defense_strength', 0):.2f}；{away} 进攻 {away_rating.get('attack_strength', 0):.2f}、防守 {away_rating.get('defense_strength', 0):.2f}。进攻差值 {attack_gap:+.2f}，防守差值 {defense_gap:+.2f}。",
            f"3. 综合强弱：{home} 综合 {home_rating.get('overall_rating', 0):.2f}，{away} 综合 {away_rating.get('overall_rating', 0):.2f}，差值 {overall_gap:+.2f}。{factor_lines[0] if factor_lines else analyst.get('summary', '双方综合评分差距有限，需要结合比分模型判断。')}",
            "",
            "比分形成逻辑",
            f"固定模拟器给出的核心结果是：{simulation.get('summary') or f'{home} {score} {away}。'}",
            f"从概率分布看，主胜 {home_prob:.1%}、平局 {draw_prob:.1%}、客胜 {away_prob:.1%}。预测比分不是单看胜负概率，而是把双方进攻、防守、近期状态和阵容可用性压缩到进球期望后得到的最可能比分。",
            "",
            "风险提示",
            f"{warning_text} 所以该结果应理解为模型赛前预测，不是真实赛果。若临场首发或伤病信息变化，比分和胜负倾向都可能被重新修正。",
        ]
    )


async def _build_match_analysis(
    match: dict[str, Any],
    prediction: dict[str, Any],
    explanation: dict[str, Any],
    ratings: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    fallback = _build_rule_match_analysis(match, prediction, explanation, ratings)
    context = _analysis_context(match, prediction, explanation, ratings)
    try:
        from app.harness.runtime import my_claude_runtime

        if not my_claude_runtime.enabled:
            return fallback, "rule"
        system_prompt = (
            "你是 worldcup-predict-agent 的赛后解释撰稿节点，运行在 my-claude-code harness 中。"
            "你只能整合用户提供的结构化指标，不得改动比分、概率、胜者或编造新闻。"
            "输出中文，语气清晰克制，面向普通用户。"
            "必须按以下小节输出，每个小节标题独占一行：结论、实力指标、攻防对比、比分逻辑、风险提示。"
            "不要使用 Markdown 标题、星号、反引号或项目符号。"
        )
        user_prompt = (
            "请根据下面 JSON 为可视化页面生成一段更具体、更有逻辑的单场比赛预测原因分析。"
            "要求：1）明确说明双方关键指标差异；2）解释为什么这个比分合理；"
            "3）如果指标非常接近，不要强行说某队明显占优；4）总长度约 350-650 字。\n"
            f"{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        text = (await my_claude_runtime.complete_direct(system_prompt=system_prompt, user_prompt=user_prompt)).strip()
        if len(text) >= 80 and "结论" in text:
            return text, "harness"
    except Exception:
        pass
    return fallback, "rule"


async def predict_single_match(
    match_id: str,
    *,
    realtime: bool = False,
    allow_draw: bool | None = None,
    progress_emit: ProgressEmit | None = None,
) -> dict[str, Any]:
    match = get_match(match_id)
    if not match:
        raise ValueError(f"未找到比赛 {match_id}")

    from app.services.data_scout_service import data_scout_service

    teams = data_scout_service.list_teams()
    ratings = get_team_ratings_and_odds()["team_ratings"]
    draw_allowed = allow_draw if allow_draw is not None else match.get("stage") == "group"
    events: list[dict[str, Any]] = []

    async def emit(event: str, message: str, phase: str | None = None, data: dict[str, Any] | None = None) -> None:
        events.append({"event": event, "message": message, "phase": phase, "data": data or {}})
        if progress_emit:
            await progress_emit(event, message, phase, data or {})

    pipeline = MatchPredictionPipeline(emit)
    prediction, explanation = await pipeline.predict(match, teams, ratings, allow_draw=draw_allowed, phase="MATCH_WORKFLOW")
    analysis, analysis_source = await _build_match_analysis(match, prediction, explanation, ratings)
    record = {
        "match_id": match["match_id"],
        "match": match,
        "prediction": prediction,
        "explanation": explanation,
        "analysis": analysis,
        "analysis_source": analysis_source,
        "agent_events": events,
        "agent_trace": prediction.get("agent_trace", []),
        "mode": "realtime" if realtime else "historical",
        "created_at": datetime.utcnow().isoformat(),
        "supersedes_previous": realtime,
    }
    store = _load_store()
    store[match["match_id"].upper()] = record
    _save_store(store)
    from app.services.cache_service import cache_service

    cache_service.invalidate_matches(match["match_id"])
    return record


def find_match_from_text(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    for match in list_schedule():
        if match["match_id"].lower() in lowered:
            return match

    resolved = resolve_match_query(text)
    if resolved.get("resolved") and resolved.get("match"):
        return resolved["match"]

    team_hits = search_teams(text)
    ids = [str(item.get("team_id", "")).upper() for item in team_hits if item.get("team_id")]
    if len(ids) >= 2:
        pair = set(ids[:2])
        for match in list_schedule():
            if {match["home_team_id"], match["away_team_id"]} == pair:
                return match
    if len(ids) == 1:
        for match in list_schedule():
            if ids[0] in {match["home_team_id"], match["away_team_id"]}:
                return match
    return None


def run_prediction_sync(match_id: str, *, realtime: bool = False) -> dict[str, Any]:
    return asyncio.run(predict_single_match(match_id, realtime=realtime))
