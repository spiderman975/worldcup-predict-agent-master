"""Checkpoint storage with Redis hot cache and SQLite persistence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.core.redis_client import redis_client


class CheckpointService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def key(self, name: str) -> str:
        return redis_client.key("checkpoint", name)

    def get(self, name: str) -> dict[str, Any] | None:
        cached = redis_client.get(self.key(name))
        if isinstance(cached, dict):
            return cached

        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT name, status, phase, payload_json, error_message, expires_at, created_at, updated_at
                FROM app_checkpoints
                WHERE name = ?
                  AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                """,
                (name,),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json") or "{}")
        redis_client.set(self.key(name), value, ttl_seconds=self.settings.checkpoint_ttl_seconds)
        return value

    def exists(self, name: str) -> bool:
        return self.get(name) is not None

    def is_completed(self, name: str) -> bool:
        checkpoint = self.get(name)
        return bool(checkpoint and checkpoint.get("status") == "completed")

    def can_start(self, name: str) -> tuple[bool, str]:
        checkpoint = self.get(name)
        if not checkpoint:
            return True, "missing"
        status = str(checkpoint.get("status") or "")
        if status == "completed":
            return False, "completed"
        if status == "failed":
            return True, "retry_failed"
        if status == "running" and self._is_stale(checkpoint):
            self.fail(name, checkpoint.get("payload") or {}, phase=checkpoint.get("phase"), error_message="stale_running_checkpoint")
            return True, "retry_stale"
        if status == "running":
            return False, "running"
        return True, f"retry_{status or 'unknown'}"

    def begin(self, name: str, value: dict[str, Any] | None = None, *, phase: str | None = None) -> None:
        payload = dict(value or {})
        payload.setdefault("started_at", datetime.utcnow().isoformat())
        self.set(name, payload, status="running", phase=phase)

    def complete(self, name: str, value: dict[str, Any] | None = None, *, phase: str | None = None) -> None:
        payload = dict(value or {})
        payload.setdefault("completed_at", datetime.utcnow().isoformat())
        self.set(name, payload, status="completed", phase=phase)

    def fail(
        self,
        name: str,
        value: dict[str, Any] | None = None,
        *,
        phase: str | None = None,
        error_message: str | None = None,
    ) -> None:
        payload = dict(value or {})
        payload.setdefault("failed_at", datetime.utcnow().isoformat())
        self.set(name, payload, status="failed", phase=phase, error_message=error_message)

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        from data.database import get_connection, init_db

        init_db()
        sql = """
            SELECT name, status, phase, payload_json, error_message, expires_at, created_at, updated_at
            FROM app_checkpoints
            WHERE (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        """
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with get_connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            item["stale"] = item.get("status") == "running" and self._is_stale(item)
            items.append(item)
        return items

    def recover_stale(self) -> dict[str, Any]:
        recovered: list[str] = []
        for checkpoint in self.list(status="running", limit=500):
            if not checkpoint.get("stale"):
                continue
            self.fail(
                checkpoint["name"],
                checkpoint.get("payload") or {},
                phase=checkpoint.get("phase"),
                error_message="stale_running_checkpoint",
            )
            recovered.append(checkpoint["name"])
        return {"success": True, "recovered": recovered, "count": len(recovered)}

    def delete(self, name: str) -> bool:
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            cursor = connection.execute("DELETE FROM app_checkpoints WHERE name = ?", (name,))
        redis_client.delete(self.key(name))
        return cursor.rowcount > 0

    def set(
        self,
        name: str,
        value: dict[str, Any],
        *,
        status: str = "completed",
        phase: str | None = None,
        error_message: str | None = None,
    ) -> None:
        from data.database import get_connection, init_db

        init_db()
        expires_at = (datetime.utcnow() + timedelta(seconds=self.settings.checkpoint_ttl_seconds)).isoformat()
        payload_json = json.dumps(value, ensure_ascii=False, default=str)
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO app_checkpoints (name, status, phase, payload_json, error_message, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    status = excluded.status,
                    phase = excluded.phase,
                    payload_json = excluded.payload_json,
                    error_message = excluded.error_message,
                    expires_at = excluded.expires_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (name, status, phase, payload_json, error_message, expires_at),
            )
        redis_client.set(
            self.key(name),
            {"name": name, "status": status, "phase": phase, "payload": value, "error_message": error_message, "expires_at": expires_at},
            ttl_seconds=self.settings.checkpoint_ttl_seconds,
        )

    def _is_stale(self, checkpoint: dict[str, Any]) -> bool:
        updated_at = str(checkpoint.get("updated_at") or "")
        started_at = str((checkpoint.get("payload") or {}).get("started_at") or "")
        candidate = started_at or updated_at
        if not candidate:
            return True
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            try:
                parsed = datetime.strptime(candidate, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return True
        return datetime.utcnow() - parsed > timedelta(seconds=self.settings.checkpoint_running_timeout_seconds)


checkpoint_service = CheckpointService()
