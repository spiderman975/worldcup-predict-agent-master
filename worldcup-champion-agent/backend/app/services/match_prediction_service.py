"""Single-match prediction orchestration and persistence."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
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


def _db_stage_name(stage: int) -> str:
    if stage <= 3:
        return "group"
    return {
        4: "round_of_32",
        5: "round_of_16",
        6: "quarter",
        7: "semi",
        8: "final",
    }.get(stage, str(stage))


def _list_database_schedule() -> list[dict[str, Any]]:
    from app.services.data_scout_service import data_scout_service

    data_scout_service.ensure_database()
    with data_scout_service._connection() as connection:
        rows = connection.execute(
            """
            SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at
            FROM matches
            ORDER BY played_at IS NULL, played_at, id
            """
        ).fetchall()

    ids = _team_id_by_name()
    schedule: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        played_at = _parse_match_time(row["played_at"], index)
        home_score = int(row["home_score"])
        away_score = int(row["away_score"])
        finished = bool(row["is_real"]) and home_score >= 0 and away_score >= 0
        home_name = str(row["home_team"])
        away_name = str(row["away_team"])
        schedule.append(
            {
                "match_id": str(row["match_id"]),
                "stage": _db_stage_name(int(row["stage"])),
                "stage_number": int(row["stage"]),
                "group": None,
                "home_team_id": ids.get(home_name.casefold(), home_name),
                "away_team_id": ids.get(away_name.casefold(), away_name),
                "home_team_name": home_name,
                "away_team_name": away_name,
                "match_time_raw": row["played_at"],
                "match_time": played_at.isoformat(),
                "match_date": played_at.date().isoformat(),
                "venue": "TBD",
                "status": "finished" if finished else "scheduled",
                "actual_home_score": home_score if home_score >= 0 else None,
                "actual_away_score": away_score if away_score >= 0 else None,
                "is_database_match": True,
            }
        )
    return schedule


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


async def predict_single_match(match_id: str, *, realtime: bool = False, allow_draw: bool | None = None) -> dict[str, Any]:
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

    pipeline = MatchPredictionPipeline(emit)
    prediction, explanation = await pipeline.predict(match, teams, ratings, allow_draw=draw_allowed, phase="MATCH_WORKFLOW")
    record = {
        "match_id": match["match_id"],
        "match": match,
        "prediction": prediction,
        "explanation": explanation,
        "agent_events": events,
        "agent_trace": prediction.get("agent_trace", []),
        "mode": "realtime" if realtime else "historical",
        "created_at": datetime.utcnow().isoformat(),
        "supersedes_previous": realtime,
    }
    store = _load_store()
    store[match["match_id"].upper()] = record
    _save_store(store)
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
