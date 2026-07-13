"""SQLite backup, restore, and performance maintenance helpers."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.data_scout_service import data_scout_service

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"


class DatabaseMaintenanceService:
    def backup(self, label: str = "manual") -> dict[str, Any]:
        from data.database import get_connection, init_db

        init_db()
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in label)[:40] or "manual"
        target = BACKUP_DIR / f"worldcup_{safe_label}_{stamp}.db"
        with get_connection() as source:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        result = {"path": str(target), "size_bytes": target.stat().st_size, "created_at": stamp}
        self._log("backup", "completed", result)
        return result

    def list_backups(self) -> list[dict[str, Any]]:
        if not BACKUP_DIR.exists():
            return []
        return [
            {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size, "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat()}
            for path in sorted(BACKUP_DIR.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
        ]

    def restore(self, backup_name: str) -> dict[str, Any]:
        from data.database import DB_PATH, init_db

        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists() or backup_path.suffix.lower() != ".db":
            raise ValueError("备份文件不存在")
        safety = self.backup(label="before_restore")
        shutil.copy2(backup_path, DB_PATH)
        init_db()
        result = {"restored_from": str(backup_path), "safety_backup": safety["path"]}
        self._log("restore", "completed", result)
        return result

    def optimize(self) -> dict[str, Any]:
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            connection.execute("ANALYZE")
            connection.execute("PRAGMA optimize")
            connection.execute("VACUUM")
            page_count = connection.execute("PRAGMA page_count").fetchone()[0]
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        result = {"page_count": int(page_count), "page_size": int(page_size), "db_size_bytes": int(page_count) * int(page_size)}
        self._log("optimize", "completed", result)
        return result

    def integrity_check(self) -> dict[str, Any]:
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            status = connection.execute("PRAGMA integrity_check").fetchone()[0]
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
        result = {"integrity_check": status, "quick_check": quick, "ok": status == "ok" and quick == "ok"}
        self._log("integrity_check", "completed" if result["ok"] else "failed", result)
        return result

    def performance_report(self) -> dict[str, Any]:
        from app.services.database_explorer import database_explorer
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            indexes = [
                dict(row)
                for row in connection.execute(
                    "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY tbl_name, name"
                ).fetchall()
            ]
        return {"db_path": str(data_scout_service.db_path), "tables": database_explorer.get_tables(), "indexes": indexes}

    def _log(self, action: str, status: str, detail: dict[str, Any]) -> None:
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO db_maintenance_log (action, status, detail_json) VALUES (?, ?, ?)",
                (action, status, json.dumps(detail, ensure_ascii=False, default=str)),
            )


db_maintenance_service = DatabaseMaintenanceService()
