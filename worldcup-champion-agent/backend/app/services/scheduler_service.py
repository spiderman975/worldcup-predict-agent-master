"""In-process scheduler for pre-match data refresh jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.services.checkpoint_service import checkpoint_service
from app.services.live_score_sync_service import live_score_sync_service
from app.services.match_result_service import match_result_service
from app.services.match_prediction_service import list_schedule, predict_single_match
from app.services.news_collection_service import news_collection_service

logger = logging.getLogger(__name__)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class SchedulerService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: asyncio.Task[None] | None = None
        self.last_scan_at: str | None = None
        self.last_result: dict[str, Any] | None = None
        self.running = False

    def start(self) -> None:
        if not self.settings.scheduler_enabled or self._task and not self._task.done():
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="worldcup-prematch-scheduler")
        logger.info("WorldCup pre-match scheduler started")

    async def stop(self) -> None:
        self.running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self.running:
            try:
                self.last_result = await self.scan_once()
            except Exception as exc:
                logger.exception("Pre-match scheduler scan failed: %s", exc)
                self.last_result = {"success": False, "error": str(exc)}
            await asyncio.sleep(max(10, self.settings.scheduler_poll_seconds))

    async def scan_once(self, *, force: bool = False) -> dict[str, Any]:
        now = datetime.now(BEIJING_TZ).replace(tzinfo=None)
        self.last_scan_at = now.isoformat()
        pre_match_updated: list[dict[str, Any]] = []
        pre_match_candidates: list[str] = []
        pre_match_predictions: list[dict[str, Any]] = []
        post_match_updated: list[dict[str, Any]] = []
        post_match_candidates: list[str] = []
        pre_window = timedelta(minutes=self.settings.pre_match_update_minutes)
        post_offset = timedelta(hours=self.settings.post_match_result_hours)
        live_sync_result: dict[str, Any] | None = None

        with redis_client.lock("prematch_scheduler_scan", ttl_seconds=max(30, self.settings.scheduler_poll_seconds)) as acquired:
            if not acquired:
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "lock_busy",
                    "now_beijing": now.isoformat(),
                    "pre_match_candidates": [],
                    "pre_match_updated": [],
                    "pre_match_predictions": [],
                    "post_match_candidates": [],
                    "post_match_updated": [],
                }
            try:
                live_sync_result = await live_score_sync_service.sync_once(force=force)
            except Exception as exc:
                logger.exception("Live score sync failed inside scheduler: %s", exc)
                live_sync_result = {"success": False, "status": "failed", "error": str(exc)}
            for match in list_schedule():
                match_time = datetime.fromisoformat(match["match_time"])
                if match.get("status") != "finished":
                    should_prematch_update = force or match_time - pre_window <= now <= match_time
                    if should_prematch_update:
                        pre_match_candidates.append(match["match_id"])
                        pre_match_updated.append(await news_collection_service.refresh_match(match, force=force))
                        prediction_result = await self._auto_predict_match(match, force=force)
                        if prediction_result:
                            pre_match_predictions.append(prediction_result)

                    post_result_time = match_time + post_offset
                    has_score = match.get("actual_home_score") is not None and match.get("actual_away_score") is not None
                    should_result_update = force or (post_result_time <= now and not has_score)
                    if should_result_update:
                        post_match_candidates.append(match["match_id"])
                        post_match_updated.append(await match_result_service.refresh_result(match, force=force))

        return {
            "success": True,
            "now_beijing": now.isoformat(),
            "pre_match_window_minutes": self.settings.pre_match_update_minutes,
            "post_match_result_hours": self.settings.post_match_result_hours,
            "live_score_sync": live_sync_result,
            "pre_match_candidates": pre_match_candidates,
            "pre_match_updated": pre_match_updated,
            "pre_match_predictions": pre_match_predictions,
            "post_match_candidates": post_match_candidates,
            "post_match_updated": post_match_updated,
        }

    async def _auto_predict_match(self, match: dict[str, Any], *, force: bool = False) -> dict[str, Any] | None:
        if not self.settings.pre_match_auto_predict and not force:
            return {"success": True, "skipped": True, "reason": "disabled", "match_id": match["match_id"]}
        if match.get("status") == "finished":
            return {"success": True, "skipped": True, "reason": "finished", "match_id": match["match_id"]}
        if self._has_unknown_team(match):
            return {"success": True, "skipped": True, "reason": "unknown_team", "match_id": match["match_id"]}

        checkpoint_name = f"prematch_auto_predict:{match['match_id']}"
        if not force:
            can_start, reason = checkpoint_service.can_start(checkpoint_name)
            if not can_start:
                return {"success": True, "skipped": True, "reason": reason, "match_id": match["match_id"]}

        checkpoint_service.begin(
            checkpoint_name,
            {"match_id": match["match_id"], "match_time": match.get("match_time")},
            phase="prematch_auto_predict",
        )
        try:
            record = await predict_single_match(match["match_id"], realtime=True)
        except Exception as exc:
            logger.exception("Pre-match auto prediction failed for %s: %s", match["match_id"], exc)
            checkpoint_service.fail(
                checkpoint_name,
                {"match_id": match["match_id"], "match_time": match.get("match_time")},
                phase="prematch_auto_predict",
                error_message=str(exc),
            )
            return {"success": False, "match_id": match["match_id"], "status": "failed", "error": str(exc)}

        prediction = record.get("prediction") or {}
        checkpoint_service.complete(
            checkpoint_name,
            {
                "match_id": match["match_id"],
                "created_at": record.get("created_at"),
                "mode": record.get("mode"),
                "predicted_home_score": prediction.get("predicted_home_score"),
                "predicted_away_score": prediction.get("predicted_away_score"),
                "analysis_source": record.get("analysis_source"),
            },
            phase="prematch_auto_predict",
        )
        return {
            "success": True,
            "skipped": False,
            "match_id": match["match_id"],
            "mode": record.get("mode"),
            "created_at": record.get("created_at"),
            "predicted_home_score": prediction.get("predicted_home_score"),
            "predicted_away_score": prediction.get("predicted_away_score"),
            "analysis_source": record.get("analysis_source"),
            "supersedes_previous": record.get("supersedes_previous"),
        }

    @staticmethod
    def _has_unknown_team(match: dict[str, Any]) -> bool:
        values = [
            str(match.get("home_team_name") or match.get("home_team_id") or ""),
            str(match.get("away_team_name") or match.get("away_team_id") or ""),
        ]
        return any(value.strip().lower() in {"", "tbd", "unknown", "待定"} for value in values)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.scheduler_enabled,
            "running": self.running,
            "poll_seconds": self.settings.scheduler_poll_seconds,
            "pre_match_update_minutes": self.settings.pre_match_update_minutes,
            "pre_match_auto_predict": self.settings.pre_match_auto_predict,
            "post_match_result_hours": self.settings.post_match_result_hours,
            "last_scan_at": self.last_scan_at,
            "last_result": self.last_result,
        }


scheduler_service = SchedulerService()
