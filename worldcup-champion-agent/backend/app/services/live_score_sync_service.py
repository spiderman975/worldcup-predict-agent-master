"""Official football-data.org score sync without replacing local match IDs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.services.cache_service import cache_service
from data_agent.sources.football_data_source import FootballDataSource

logger = logging.getLogger(__name__)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ExternalMatch:
    match_id: str
    stage_number: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    is_real: bool
    played_at: str | None
    status: str


class LiveScoreSyncService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.running = False
        self.last_result: dict[str, Any] = {
            "enabled": self.settings.live_score_sync_enabled,
            "running": False,
            "configured": bool(self.settings.football_data_api_key),
            "status": "never_run",
            "last_sync_at": None,
            "last_success_at": None,
            "updated_matches": 0,
            "matched_matches": 0,
            "unmatched_matches": [],
            "ambiguous_matches": [],
            "error": None,
        }

    def status(self) -> dict[str, Any]:
        return {
            **self.last_result,
            "enabled": self.settings.live_score_sync_enabled,
            "running": self.running,
            "configured": bool(self.settings.football_data_api_key),
        }

    async def sync_once(self, *, force: bool = False) -> dict[str, Any]:
        if not self.settings.live_score_sync_enabled and not force:
            return self._record(status="disabled", success=False, message="实时比分同步已关闭。")
        if not self.settings.football_data_api_key:
            return self._record(
                status="missing_api_key",
                success=False,
                message="未配置 FOOTBALL_DATA_API_KEY，无法同步官方实时比分。",
            )

        with redis_client.lock("live_score_sync", ttl_seconds=max(30, self.settings.live_score_sync_interval_seconds)) as acquired:
            if not acquired:
                return {**self.status(), "success": True, "skipped": True, "reason": "lock_busy"}
            self.running = True
            try:
                source = FootballDataSource(api_key=self.settings.football_data_api_key)
                external = [
                    ExternalMatch(
                        match_id=item.match_id,
                        stage_number=int(item.stage),
                        home_team=item.home_team,
                        away_team=item.away_team,
                        home_score=item.home_score,
                        away_score=item.away_score,
                        is_real=bool(item.is_real),
                        played_at=item.played_at,
                        status="finished" if item.is_real else "scheduled",
                    )
                    for item in source.load_matches(int(self.settings.football_data_season))
                    if item.home_team and item.away_team
                ]
                result = self._apply_external_matches(external)
                self.running = False
                return self._record(status="success", success=True, **result)
            except Exception as exc:
                logger.exception("Official live score sync failed: %s", exc)
                self.running = False
                return self._record(status="failed", success=False, error=str(exc))
            finally:
                self.running = False

    def _apply_external_matches(self, external_matches: list[ExternalMatch]) -> dict[str, Any]:
        from data.database import get_connection, init_db

        init_db()
        matched = 0
        updated = 0
        unmatched: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status
                FROM matches
                """
            ).fetchall()
            local_matches = [dict(row) for row in rows]
            for external in external_matches:
                match_result = self._match_local(external, local_matches)
                if match_result["status"] == "ambiguous":
                    ambiguous.append({"external_match_id": external.match_id, "candidates": match_result["candidate_ids"]})
                    continue
                local = match_result.get("match")
                if not local:
                    unmatched.append({"external_match_id": external.match_id, "home": external.home_team, "away": external.away_team})
                    continue
                matched += 1
                swapped = bool(match_result["swapped"])
                home_score = external.away_score if swapped and external.is_real else external.home_score
                away_score = external.home_score if swapped and external.is_real else external.away_score
                if not external.is_real:
                    home_score = int(local["home_score"])
                    away_score = int(local["away_score"])
                cursor = connection.execute(
                    """
                    UPDATE matches
                    SET home_score = ?, away_score = ?, is_real = ?, played_at = ?, status = ?
                    WHERE match_id = ?
                    """,
                    (
                        home_score,
                        away_score,
                        int(external.is_real or bool(local["is_real"])),
                        external.played_at or local["played_at"],
                        external.status,
                        local["match_id"],
                    ),
                )
                updated += cursor.rowcount
        if updated:
            cache_service.invalidate_matches()
        return {
            "updated_matches": updated,
            "matched_matches": matched,
            "unmatched_matches": unmatched,
            "ambiguous_matches": ambiguous,
        }

    def _match_local(self, external: ExternalMatch, local_matches: list[dict[str, Any]]) -> dict[str, Any]:
        candidates: list[tuple[dict[str, Any], bool]] = []
        for local in local_matches:
            if not _stage_compatible(int(local["stage"]), external.stage_number):
                continue
            normal = _same_team(local["home_team"], external.home_team) and _same_team(local["away_team"], external.away_team)
            swapped = _same_team(local["home_team"], external.away_team) and _same_team(local["away_team"], external.home_team)
            if not normal and not swapped:
                continue
            if not _within_time_window(local.get("played_at"), external.played_at):
                continue
            candidates.append((local, swapped))
        if len(candidates) == 1:
            local, swapped = candidates[0]
            return {"status": "matched", "match": local, "swapped": swapped}
        if len(candidates) > 1:
            return {"status": "ambiguous", "candidate_ids": [item[0]["match_id"] for item in candidates]}
        return {"status": "unmatched"}

    def _record(self, *, status: str, success: bool, **extra: Any) -> dict[str, Any]:
        now = datetime.now(BEIJING_TZ).isoformat()
        result = {
            "success": success,
            "enabled": self.settings.live_score_sync_enabled,
            "running": self.running,
            "configured": bool(self.settings.football_data_api_key),
            "last_sync_at": now,
            "last_success_at": now if success and status == "success" else self.last_result.get("last_success_at"),
            "updated_matches": int(extra.get("updated_matches", 0)),
            "matched_matches": int(extra.get("matched_matches", 0)),
            "unmatched_matches": extra.get("unmatched_matches", []),
            "ambiguous_matches": extra.get("ambiguous_matches", []),
            "status": status,
            "error": extra.get("error"),
            "message": extra.get("message"),
        }
        self.last_result = result
        return result


def _normalize_team(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _same_team(left: str, right: str) -> bool:
    return _normalize_team(left) == _normalize_team(right)


def _stage_compatible(local_stage: int, external_stage: int) -> bool:
    if local_stage == external_stage:
        return True
    # Existing local data used stage=1 for both group and early knockout rows.
    return local_stage == 1 and external_stage in {1, 2}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(BEIJING_TZ).replace(tzinfo=None)
    return parsed


def _within_time_window(left: str | None, right: str | None) -> bool:
    left_time = _parse_time(left)
    right_time = _parse_time(right)
    if left_time is None or right_time is None:
        return True
    return abs((left_time - right_time).total_seconds()) <= 12 * 60 * 60


live_score_sync_service = LiveScoreSyncService()
