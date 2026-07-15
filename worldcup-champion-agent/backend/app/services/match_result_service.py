"""Post-match result search, parsing, persistence, and score updates."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.redis_client import redis_client
from app.services.cache_service import cache_service
from app.services.checkpoint_service import checkpoint_service
from app.services.data_scout_service import data_scout_service

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


class MatchResultService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def refresh_result(self, match: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        checkpoint_name = self._checkpoint_name(match["match_id"])
        if not force:
            can_start, reason = checkpoint_service.can_start(checkpoint_name)
            if not can_start:
                return {"success": True, "skipped": True, "reason": reason, "match_id": match["match_id"]}

        query = (
            f"{match['home_team_name']} vs {match['away_team_name']} "
            f"final score result {match['match_date']} FIFA World Cup"
        )
        checkpoint_service.begin(checkpoint_name, {"match_id": match["match_id"], "query": query}, phase="post_match_result")
        web_results = await data_scout_service.search_web(query, count=10) if self.settings.post_match_include_web else []
        raw_record = {
            "match_id": match["match_id"],
            "match": match,
            "query": query,
            "searched_at": datetime.now(BEIJING_TZ).isoformat(),
            "include_web": bool(self.settings.post_match_include_web),
            "web": web_results,
        }
        parsed = self.parse_score(match, web_results)
        if not web_results:
            self._save_result_record(match["match_id"], query, raw_record, status="no_web_results", error="没有网页搜索结果，可能未配置 BOCHA_API_KEY")
            checkpoint_service.fail(
                checkpoint_name,
                {"match_id": match["match_id"], "searched_at": raw_record["searched_at"], "parsed": None},
                phase="post_match_result",
                error_message="no_web_results",
            )
            return {"success": False, "match_id": match["match_id"], "status": "no_web_results", "parsed": None}
        if not parsed:
            self._save_result_record(match["match_id"], query, raw_record, status="parse_failed", error="未能从网页结果中可靠解析比分")
            checkpoint_service.fail(
                checkpoint_name,
                {"match_id": match["match_id"], "searched_at": raw_record["searched_at"], "parsed": None},
                phase="post_match_result",
                error_message="parse_failed",
            )
            return {"success": False, "match_id": match["match_id"], "status": "parse_failed", "parsed": None}

        applied_at = self.apply_score(match["match_id"], parsed["home_score"], parsed["away_score"])
        cache_service.invalidate_matches(match["match_id"])
        record = {**raw_record, "parsed": parsed, "applied_at": applied_at}
        self._save_result_record(
            match["match_id"],
            query,
            record,
            status="applied",
            parsed_home_score=parsed["home_score"],
            parsed_away_score=parsed["away_score"],
            confidence=parsed["confidence"],
            applied_at=applied_at,
        )
        redis_client.set(redis_client.key("postmatch", match["match_id"]), record, ttl_seconds=24 * 60 * 60)
        checkpoint_service.complete(
            checkpoint_name,
            {"match_id": match["match_id"], "searched_at": raw_record["searched_at"], "parsed": parsed, "applied_at": applied_at},
            phase="post_match_result",
        )
        return {"success": True, "match_id": match["match_id"], "status": "applied", "parsed": parsed, "applied_at": applied_at}

    def parse_score(self, match: dict[str, Any], web_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        home = str(match["home_team_name"])
        away = str(match["away_team_name"])
        home_re = re.escape(home)
        away_re = re.escape(away)
        patterns = [
            re.compile(rf"{home_re}.{{0,80}}?(\d{{1,2}})\s*[-:]\s*(\d{{1,2}}).{{0,80}}?{away_re}", re.I | re.S),
            re.compile(rf"{away_re}.{{0,80}}?(\d{{1,2}})\s*[-:]\s*(\d{{1,2}}).{{0,80}}?{home_re}", re.I | re.S),
        ]
        for result in web_results:
            haystack = " ".join(str(result.get(key) or "") for key in ("title", "summary", "source"))
            if home.casefold() not in haystack.casefold() or away.casefold() not in haystack.casefold():
                continue
            for index, pattern in enumerate(patterns):
                match_obj = pattern.search(haystack)
                if not match_obj:
                    continue
                first, second = int(match_obj.group(1)), int(match_obj.group(2))
                home_score, away_score = (first, second) if index == 0 else (second, first)
                if home_score > 15 or away_score > 15:
                    continue
                return {
                    "home_score": home_score,
                    "away_score": away_score,
                    "confidence": 0.85 if "final" in haystack.lower() or "result" in haystack.lower() else 0.65,
                    "source": result,
                    "evidence": haystack[:500],
                }
        return None

    @staticmethod
    def apply_score(match_id: str, home_score: int, away_score: int) -> str:
        from data.database import get_connection, init_db

        init_db()
        applied_at = datetime.now(BEIJING_TZ).isoformat()
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE matches
                SET home_score = ?, away_score = ?, is_real = 1, status = 'FINISHED'
                WHERE match_id = ?
                """,
                (home_score, away_score, match_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"比赛不存在：{match_id}")
            MatchResultService._advance_knockout_matches(connection)
        return applied_at

    @staticmethod
    def _advance_knockout_matches(connection: Any) -> None:
        """Fill known knockout fixtures once prerequisite real scores exist."""

        rows = connection.execute(
            """
            SELECT match_id, home_team, away_team, home_score, away_score, is_real
            FROM matches
            WHERE match_id IN (
                's3_france_morocco',
                's3_spain_belgium',
                's3_norway_england',
                's3_argentina_switzerland',
                's5_france_spain',
                's5_england_argentina'
            )
            """
        ).fetchall()
        matches = {row["match_id"]: row for row in rows}

        def winner(match_id: str) -> str | None:
            row = matches.get(match_id)
            if not row or not row["is_real"] or row["home_score"] == row["away_score"]:
                return None
            return row["home_team"] if row["home_score"] > row["away_score"] else row["away_team"]

        def loser(match_id: str) -> str | None:
            row = matches.get(match_id)
            if not row or not row["is_real"] or row["home_score"] == row["away_score"]:
                return None
            return row["away_team"] if row["home_score"] > row["away_score"] else row["home_team"]

        semi_home = winner("s3_norway_england")
        semi_away = winner("s3_argentina_switzerland")
        if semi_home and semi_away:
            MatchResultService._upsert_future_match(
                connection,
                match_id=f"s4_{MatchResultService._slug(semi_home)}_{MatchResultService._slug(semi_away)}",
                stage=4,
                home_team=semi_home,
                away_team=semi_away,
                played_at="2026-07-15T19:00:00Z",
            )

        final_home = winner("s5_france_spain")
        final_away = winner("s5_england_argentina")
        third_home = loser("s5_france_spain")
        third_away = loser("s5_england_argentina")
        if third_home and third_away:
            MatchResultService._upsert_future_match(
                connection,
                match_id=f"s5_{MatchResultService._slug(third_home)}_{MatchResultService._slug(third_away)}",
                stage=6,
                home_team=third_home,
                away_team=third_away,
                played_at="2026-07-18T21:00:00Z",
            )
        if final_home and final_away:
            MatchResultService._upsert_future_match(
                connection,
                match_id=f"s6_{MatchResultService._slug(final_home)}_{MatchResultService._slug(final_away)}",
                stage=7,
                home_team=final_home,
                away_team=final_away,
                played_at="2026-07-19T19:00:00Z",
            )

    @staticmethod
    def _upsert_future_match(
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
            INSERT INTO matches (match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status)
            VALUES (?, ?, ?, ?, -1, -1, 0, ?, '')
            ON CONFLICT(match_id) DO UPDATE SET
                stage = excluded.stage,
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                played_at = excluded.played_at
            """,
            (match_id, stage, home_team, away_team, played_at),
        )

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")

    def _save_result_record(
        self,
        match_id: str,
        query: str,
        record: dict[str, Any],
        *,
        status: str,
        error: str | None = None,
        parsed_home_score: int | None = None,
        parsed_away_score: int | None = None,
        confidence: float = 0.0,
        applied_at: str | None = None,
    ) -> None:
        from data.database import get_connection, init_db

        init_db()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO post_match_results (
                    match_id, query, result_json, parsed_home_score, parsed_away_score,
                    confidence, status, error_message, searched_at, applied_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    query,
                    json.dumps(record, ensure_ascii=False, default=str),
                    parsed_home_score,
                    parsed_away_score,
                    confidence,
                    status,
                    error,
                    record.get("searched_at"),
                    applied_at,
                ),
            )

    @staticmethod
    def _checkpoint_name(match_id: str) -> str:
        return f"postmatch_result:{match_id}"


match_result_service = MatchResultService()
