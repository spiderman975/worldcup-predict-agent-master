"""Database and optional web search support for the World Cup data scout."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings


class WorldCupDataError(RuntimeError):
    """Raised when the SQLite data layer is unavailable or incomplete."""


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class ScoutSearchResult:
    title: str
    summary: str
    source: str
    url: str = ""
    score: float = 0.0
    kind: str = "database"

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "url": self.url,
            "score": self.score,
            "kind": self.kind,
        }


class WorldCupDataScoutService:
    """Read the collaborator SQLite data layer and expose scout-friendly queries."""

    def __init__(self) -> None:
        self.project_root = PROJECT_ROOT
        self.search_cache: dict[str, list[dict[str, Any]]] = {}

    @property
    def db_path(self) -> Path:
        try:
            from data.database import DB_PATH

            return Path(DB_PATH)
        except Exception:
            return self.project_root / "data" / "worldcup.db"

    def ensure_database(self) -> None:
        from data.database import init_db

        init_db()
        required = {"teams", "members", "matches"}
        existing = set(self._table_names())
        missing = sorted(required - existing)
        if missing:
            raise WorldCupDataError(f"SQLite 数据库缺少表：{', '.join(missing)}")
        empty_tables = [table for table in sorted(required) if self._table_count(table) == 0]
        if empty_tables:
            raise WorldCupDataError(f"SQLite 数据库为空表：{', '.join(empty_tables)}。请先导入协作者的新数据。")

    def list_teams(self) -> list[dict[str, Any]]:
        self.ensure_database()
        reports = [self.team_report(row["name"]) for row in self._all_team_rows()]
        return [self._frontend_team(report) for report in reports if report]

    def team_id_for_name(self, name: str) -> str:
        return self._team_id(name)

    def team_report(self, team_name: str) -> dict[str, Any] | None:
        self.ensure_database()
        try:
            from data.database import get_team, get_injured_players
        except Exception:
            return None

        try:
            team = get_team(team_name)
        except KeyError:
            team = self._find_team_by_alias(team_name)
            if team is None:
                return None

        injured = get_injured_players(team.name)
        active_lineup = team.starting_lineup or [member.name for member in team.members[:11]]
        return {
            "name": team.name,
            "group": team.group,
            "fifa_ranking": team.fifa_ranking,
            "attack_team": team.attack_team,
            "defensive_team": team.defensive_team,
            "computed_attack": round(team.get_attack(), 4),
            "computed_defensive": round(team.get_defensive(), 4),
            "streak": team.streak,
            "starting_lineup": active_lineup,
            "injured_players": [
                {
                    "name": member.name,
                    "attack": member.attack_member,
                    "defensive": member.defensive_member,
                    "description": member.injury_description,
                }
                for member in injured
            ],
            "members_count": len(team.members),
        }

    def match_context(self, match: dict[str, Any], teams: list[dict[str, Any]]) -> dict[str, Any]:
        names = {team["team_id"]: team["name"] for team in teams}
        home_name = names.get(match["home_team_id"], match["home_team_id"])
        away_name = names.get(match["away_team_id"], match["away_team_id"])
        return {
            "home": self.team_report(home_name),
            "away": self.team_report(away_name),
            "database_match": self._find_match(home_name, away_name, str(match.get("match_id", ""))),
        }

    def search_database(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        self.ensure_database()
        terms = [part.casefold() for part in query.split() if part.strip()]
        if not terms:
            return []

        results: list[ScoutSearchResult] = []
        for row in self._all_team_rows():
            haystack = " ".join(str(value or "") for value in row.values()).casefold()
            score = self._score(haystack, terms)
            if score:
                results.append(
                    ScoutSearchResult(
                        title=f"球队：{row['name']}",
                        summary=(
                            f"{row['name']} 位于 {row['group']} 组，FIFA 排名 {row.get('fifa_ranking') or '未知'}，"
                            f"团队进攻系数 {row['attack_team']}，防守系数 {row['defensive_team']}，近期势头 {row['streak']}。"
                        ),
                        source="SQLite teams",
                        url=f"local://teams/{row['name']}",
                        score=score,
                    )
                )

        for row in self._all_member_rows():
            haystack = " ".join(str(value or "") for value in row.values()).casefold()
            score = self._score(haystack, terms)
            if score:
                injury = "，伤病：" + row["injury_description"] if row["injured"] else ""
                results.append(
                    ScoutSearchResult(
                        title=f"球员：{row['name']}",
                        summary=(
                            f"{row['name']} 属于 {row['team_name']}，进攻 {row['attack']}，防守 {row['defensive']}"
                            f"{injury}。"
                        ),
                        source="SQLite members",
                        url=f"local://members/{row['team_name']}/{row['name']}",
                        score=score,
                    )
                )

        for row in self._all_match_rows():
            haystack = " ".join(str(value or "") for value in row.values()).casefold()
            score = self._score(haystack, terms)
            if score:
                status = "已赛" if row["is_real"] else "未赛"
                results.append(
                    ScoutSearchResult(
                        title=f"比赛：{row['match_id']}",
                        summary=(
                            f"{row['home_team']} vs {row['away_team']}，阶段 {row['stage']}，{status}，"
                            f"比分 {row['home_score']}-{row['away_score']}。"
                        ),
                        source="SQLite matches",
                        url=f"local://matches/{row['match_id']}",
                        score=score,
                    )
                )

        return [item.as_dict() for item in sorted(results, key=lambda item: item.score, reverse=True)[:top_k]]

    async def search_web(self, query: str, count: int = 5) -> list[dict[str, Any]]:
        settings = get_settings()
        api_key = getattr(settings, "bocha_api_key", None)
        if not api_key:
            return []

        cache_key = hashlib.md5(query.encode("utf-8")).hexdigest()
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]

        payload = {"query": query, "summary": True, "count": count, "freshness": "noLimit"}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                response = await client.post("https://api.bocha.cn/v1/web-search", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception:
            return []

        webpages = data.get("data", {}).get("webPages", {}).get("value", [])
        results = [
            {
                "title": item.get("name", "N/A"),
                "summary": item.get("summary") or item.get("snippet", ""),
                "source": item.get("siteName", "Web"),
                "url": item.get("url", ""),
                "date": item.get("datePublished") or item.get("dateLastCrawled", ""),
                "kind": "web",
            }
            for item in webpages
            if item.get("url") and (item.get("summary") or item.get("snippet"))
        ]
        self.search_cache[cache_key] = results
        return results

    async def search(self, query: str, *, include_web: bool = False, top_k: int = 8) -> dict[str, Any]:
        database_results = self.search_database(query, top_k=top_k)
        web_results = await self.search_web(query, count=top_k) if include_web else []
        return {"query": query, "database": database_results, "web": web_results}

    def _table_count(self, table: str) -> int:
        with self._connection() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _table_names(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return [str(row["name"]) for row in rows]

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _find_team_by_alias(self, name: str):
        from data.database import get_all_teams
        from data_agent.team_aliases import canonicalize_team_name, load_team_aliases

        aliases = load_team_aliases(self.project_root / "datasets" / "team_aliases.csv")
        target = canonicalize_team_name(name, aliases).casefold()
        for team in get_all_teams():
            if canonicalize_team_name(team.name, aliases).casefold() == target or team.name.casefold() == name.casefold():
                return team
        return None

    def _find_match(self, home_name: str, away_name: str, match_id: str) -> dict[str, Any] | None:
        self.ensure_database()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at
                FROM matches
                WHERE match_id = ?
                   OR ((home_team = ? AND away_team = ?) OR (home_team = ? AND away_team = ?))
                LIMIT 1
                """,
                (match_id, home_name, away_name, away_name, home_name),
            ).fetchone()
        return dict(row) if row else None

    def _all_team_rows(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                'SELECT name, "group", attack_team, defensive_team, streak, starting_lineup, fifa_ranking FROM teams'
            ).fetchall()
        return [dict(row) for row in rows]

    def _all_member_rows(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT name, team_name, attack, defensive, injured, injury_description FROM members"
            ).fetchall()
        return [dict(row) for row in rows]

    def _all_match_rows(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at FROM matches"
            ).fetchall()
        return [dict(row) for row in rows]

    def _frontend_team(self, report: dict[str, Any]) -> dict[str, Any]:
        attack_score = self._score_0_1(report["computed_attack"])
        defense_score = self._score_0_1(report["computed_defensive"])
        fifa_rank = int(report["fifa_ranking"] or 999)
        form_score = max(0.0, min(1.0, 0.5 + float(report["streak"]) / 6))
        availability = max(0.5, 1 - len(report["injured_players"]) / max(report["members_count"], 1))
        return {
            "team_id": self._team_id(report["name"]),
            "name": report["name"],
            "group": report["group"],
            "fifa_rank": fifa_rank,
            "elo_rating": int(2400 - min(fifa_rank, 200) * 5),
            "attack_score": attack_score,
            "defense_score": defense_score,
            "recent_form": round(form_score, 4),
            "worldcup_history_score": round(max(0.2, 1 - min(fifa_rank, 120) / 150), 4),
            "squad_availability_score": round(availability, 4),
            "database": report,
        }

    @staticmethod
    def _score_0_1(value: float) -> float:
        return round(max(0.0, min(1.0, float(value) / 100)), 4)

    @staticmethod
    def _team_id(name: str) -> str:
        return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")

    @staticmethod
    def _score(haystack: str, terms: list[str]) -> float:
        return float(sum(1 for term in terms if term in haystack))


data_scout_service = WorldCupDataScoutService()
