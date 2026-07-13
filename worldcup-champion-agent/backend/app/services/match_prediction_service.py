"""Single-match prediction orchestration and persistence."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.agent.match_pipeline import MatchPredictionPipeline
from app.services.team_analysis_service import get_team_ratings_and_odds, search_teams


PREDICTION_STORE = Path(__file__).resolve().parents[3] / "data" / "snapshots" / "match_predictions.json"
BASE_MATCH_TIME = datetime(2026, 6, 11, 20, 0, 0)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


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
