"""Read-only SQLite database explorer for the World Cup data layer."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.services.data_scout_service import data_scout_service


class DatabaseExplorer:
    def _connect(self) -> sqlite3.Connection:
        data_scout_service.ensure_database()
        connection = sqlite3.connect(data_scout_service.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def get_tables(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            tables = []
            for row in rows:
                name = row["name"]
                count = connection.execute(f'SELECT COUNT(*) AS c FROM "{name}"').fetchone()["c"]
                columns = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
                tables.append({"name": name, "row_count": int(count), "column_count": len(columns)})
            return tables

    def get_schema(self) -> dict[str, Any]:
        return {"tables": [self.get_table_schema(table["name"]) for table in self.get_tables()]}

    def get_schema_text(self) -> str:
        lines: list[str] = []
        for table in self.get_schema()["tables"]:
            columns = ", ".join(f"{col['name']} {col['type']}" for col in table["columns"])
            lines.append(f"- {table['name']}({columns})")
        return "\n".join(lines)

    def get_table_schema(self, table_name: str) -> dict[str, Any]:
        self._validate_identifier(table_name)
        with self._connect() as connection:
            columns = [
                {
                    "name": row["name"],
                    "type": row["type"],
                    "nullable": not bool(row["notnull"]),
                    "primary_key": bool(row["pk"]),
                }
                for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
            ]
        return {"table_name": table_name, "columns": columns}

    def execute_readonly(self, sql: str, limit: int = 100) -> dict[str, Any]:
        cleaned = self.validate_sql(sql, limit=limit)
        with self._connect() as connection:
            cursor = connection.execute(cleaned)
            columns = [item[0] for item in cursor.description or []]
            rows = [dict(row) for row in cursor.fetchall()]
        return {"sql": cleaned, "columns": columns, "rows": rows, "row_count": len(rows)}

    def validate_sql(self, sql: str, limit: int = 100) -> str:
        if not sql or not sql.strip():
            raise ValueError("SQL 不能为空")
        cleaned = sql.strip().rstrip(";")
        upper = cleaned.upper()
        if not upper.startswith("SELECT"):
            raise ValueError("只允许 SELECT 查询")
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA"]
        for word in forbidden:
            if re.search(rf"\b{word}\b", upper):
                raise ValueError(f"SQL 包含禁止关键字：{word}")
        if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
            raise ValueError("SQL 不允许包含注释")
        if not re.search(r"\bLIMIT\b", upper):
            cleaned = f"{cleaned} LIMIT {max(1, min(limit, 500))}"
        return cleaned

    @staticmethod
    def _validate_identifier(name: str) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
            raise ValueError("非法表名")


database_explorer = DatabaseExplorer()
