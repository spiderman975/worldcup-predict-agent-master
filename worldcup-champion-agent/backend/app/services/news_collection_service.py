"""Pre-match information refresh for scheduled matches."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.services.checkpoint_service import checkpoint_service
from app.services.data_scout_service import data_scout_service

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "pre_match_updates"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class NewsCollectionService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def refresh_match(self, match: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        checkpoint_name = self._checkpoint_name(match["match_id"])
        if not force:
            can_start, reason = checkpoint_service.can_start(checkpoint_name)
            if not can_start:
                return {"success": True, "skipped": True, "reason": reason, "match_id": match["match_id"]}

        query = (
            f"{match['home_team_name']} {match['away_team_name']} "
            f"lineup injuries news {match['match_date']}"
        )
        checkpoint_service.begin(checkpoint_name, {"match_id": match["match_id"], "query": query}, phase="pre_match_refresh")
        try:
            result = await data_scout_service.search(
                query,
                include_web=bool(self.settings.pre_match_include_web),
                top_k=10,
            )
            record = {
                "match_id": match["match_id"],
                "match": match,
                "query": query,
                "refreshed_at": datetime.now(BEIJING_TZ).isoformat(),
                "include_web": bool(self.settings.pre_match_include_web),
                "result": result,
            }
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SNAPSHOT_DIR / f"{match['match_id']}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            self._save_update_record(match["match_id"], query, record, status="completed")
        except Exception as exc:
            checkpoint_service.fail(
                checkpoint_name,
                {"match_id": match["match_id"], "query": query},
                phase="pre_match_refresh",
                error_message=str(exc),
            )
            self._save_update_record(
                match["match_id"],
                query,
                {"match_id": match["match_id"], "query": query, "refreshed_at": datetime.now(BEIJING_TZ).isoformat()},
                status="failed",
                error=str(exc),
            )
            raise

        redis_client.set(redis_client.key("prematch", match["match_id"]), record, ttl_seconds=15 * 60)
        checkpoint_service.complete(checkpoint_name, {"match_id": match["match_id"], "refreshed_at": record["refreshed_at"]}, phase="pre_match_refresh")
        return {"success": True, "skipped": False, "match_id": match["match_id"], "snapshot": str(path)}

    @staticmethod
    def _checkpoint_name(match_id: str) -> str:
        return f"prematch_refresh:{match_id}"

    def _save_update_record(self, match_id: str, query: str, record: dict[str, Any], *, status: str, error: str | None = None) -> None:
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO pre_match_updates (match_id, query, result_json, include_web, status, error_message, refreshed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    query,
                    json.dumps(record, ensure_ascii=False, default=str),
                    int(bool(record.get("include_web"))),
                    status,
                    error,
                    record.get("refreshed_at"),
                ),
            )


news_collection_service = NewsCollectionService()
