"""Text2SQL service for safe read-only questions over the World Cup SQLite DB."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.database_explorer import database_explorer
from app.services.llm_service import llm_service


class Text2SQLService:
    SYSTEM_PROMPT = """
你是世界杯 SQLite 数据库的 Text2SQL 助手。
只能生成 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE 等写操作。
必须使用给定 schema 中存在的表和字段。返回 JSON：{"sql": "...", "explanation": "...", "visualization_hint": "table"}。
""".strip()

    async def query(self, question: str, limit: int = 100) -> dict[str, Any]:
        generation = await self.generate_sql(question, limit=limit)
        sql = generation.get("sql", "")
        if not sql:
            return {"success": False, "error": generation.get("explanation", "无法生成 SQL"), "sql": "", "data": [], "columns": []}
        try:
            result = database_explorer.execute_readonly(sql, limit=limit)
        except Exception as exc:
            return {"success": False, "error": str(exc), "sql": sql, "data": [], "columns": []}
        return {
            "success": True,
            "sql": result["sql"],
            "explanation": generation.get("explanation", ""),
            "columns": result["columns"],
            "data": result["rows"],
            "row_count": result["row_count"],
            "visualization_hint": generation.get("visualization_hint", "table"),
        }

    async def generate_sql(self, question: str, limit: int = 100) -> dict[str, Any]:
        if llm_service.enabled:
            schema = database_explorer.get_schema_text()
            prompt = f"Schema:\n{schema}\n\n问题：{question}\n默认 LIMIT：{limit}"
            try:
                text = await llm_service.complete(system_prompt=self.SYSTEM_PROMPT, user_prompt=prompt)
                parsed = self._parse_json(text)
                sql = database_explorer.validate_sql(str(parsed.get("sql", "")), limit=limit)
                return {
                    "sql": sql,
                    "explanation": parsed.get("explanation", ""),
                    "visualization_hint": parsed.get("visualization_hint", "table"),
                }
            except Exception as exc:
                return {"sql": "", "explanation": f"LLM 生成 SQL 失败：{exc}", "visualization_hint": "none"}
        return self._rule_based_sql(question, limit=limit)

    def _rule_based_sql(self, question: str, limit: int) -> dict[str, Any]:
        text = question.lower()
        if any(word in text for word in ["球队", "team", "排名", "fifa"]):
            sql = 'SELECT name, "group", fifa_ranking, attack_team, defensive_team FROM teams ORDER BY fifa_ranking LIMIT {limit}'
            return {"sql": sql.format(limit=limit), "explanation": "按 FIFA 排名查询球队列表。", "visualization_hint": "table"}
        if any(word in text for word in ["伤病", "injury", "injured"]):
            sql = "SELECT team_name, name, injury_description FROM members WHERE injured = 1 LIMIT {limit}"
            return {"sql": sql.format(limit=limit), "explanation": "查询标记为伤病的球员。", "visualization_hint": "table"}
        if any(word in text for word in ["赛程", "比赛", "match", "schedule"]):
            sql = "SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at FROM matches ORDER BY played_at LIMIT {limit}"
            return {"sql": sql.format(limit=limit), "explanation": "查询比赛赛程。", "visualization_hint": "table"}
        return {
            "sql": "SELECT name, team_name, attack, defensive, injured FROM members LIMIT {limit}".format(limit=limit),
            "explanation": "未识别到更具体意图，返回球员样例数据。",
            "visualization_hint": "table",
        }

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip().strip("`").strip()
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}


text2sql_service = Text2SQLService()
