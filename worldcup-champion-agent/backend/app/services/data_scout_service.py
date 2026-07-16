"""Database and optional web search support for the World Cup data scout."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)
DEFAULT_WEB_RESULT_COUNT = 20

TEAM_QUERY_ALIASES = {
    "阿根廷": "Argentina",
    "英格兰": "England",
    "法国": "France",
    "西班牙": "Spain",
    "巴西": "Brazil",
    "德国": "Germany",
    "葡萄牙": "Portugal",
    "荷兰": "Netherlands",
    "比利时": "Belgium",
    "瑞士": "Switzerland",
    "挪威": "Norway",
    "摩洛哥": "Morocco",
    "埃及": "Egypt",
    "墨西哥": "Mexico",
    "美国": "United States",
}

CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

ENGLISH_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


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

    TRUSTED_FOOTBALL_DOMAINS = [
        "fifa.com",
        "reuters.com",
        "apnews.com",
        "bbc.com/sport",
        "espn.com",
        "skysports.com",
        "theguardian.com/football",
        "theathletic.com",
        "transfermarkt.com",
        "sofascore.com",
        "fotmob.com",
        "whoscored.com",
        "soccerway.com",
        "worldfootball.net",
    ]

    HISTORICAL_FOOTBALL_DOMAINS = [
        "fifa.com",
        "worldfootball.net",
        "rsssf.org",
        "transfermarkt.com",
        "soccerway.com",
    ]

    def __init__(self) -> None:
        self.project_root = PROJECT_ROOT
        self.search_cache: dict[str, list[dict[str, Any]]] = {}
        self._warned_missing_key = False

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

    def team_detail_by_id(self, team_id: str) -> dict[str, Any] | None:
        normalized_id = team_id.upper()
        team = next((item for item in self.list_teams() if item["team_id"] == normalized_id), None)
        if not team:
            return None

        report = team.get("database") or self.team_report(team["name"]) or {}
        players = [
            {
                "name": row["name"],
                "attack": int(row["attack"] or 0),
                "defense": int(row["defensive"] or 0),
                "overall": round((float(row["attack"] or 0) + float(row["defensive"] or 0)) / 2, 1),
                "injured": bool(row["injured"]),
                "injury_description": row.get("injury_description") or "",
                "is_starter": row["name"] in set(report.get("starting_lineup") or []),
            }
            for row in self._all_member_rows()
            if self._team_id(row["team_name"]) == normalized_id
        ]
        players.sort(key=lambda item: (not item["is_starter"], item["injured"], -item["overall"], item["name"]))

        return {
            **team,
            "database": report,
            "starting_lineup": report.get("starting_lineup") or [item["name"] for item in players[:11]],
            "injured_players": report.get("injured_players") or [item for item in players if item["injured"]],
            "players": players,
        }

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

    def _query_terms(self, query: str) -> list[str]:
        terms = [part.casefold() for part in query.split() if part.strip()]
        lowered = query.casefold()
        for alias, canonical in TEAM_QUERY_ALIASES.items():
            if alias in query:
                terms.extend([alias.casefold(), canonical.casefold()])
        for row in self._all_team_rows():
            name = str(row["name"])
            if name.casefold() in lowered:
                terms.append(name.casefold())
        return list(dict.fromkeys(term for term in terms if term))

    def _team_names_from_query(self, query: str) -> list[str]:
        lowered = query.casefold()
        matches: list[str] = []
        for alias, canonical in TEAM_QUERY_ALIASES.items():
            if alias in query:
                matches.append(canonical)
        for row in self._all_team_rows():
            name = str(row["name"])
            if name.casefold() in lowered:
                matches.append(name)
        return list(dict.fromkeys(matches))

    @staticmethod
    def _recent_match_limit(query: str) -> int | None:
        patterns = [
            r"(?:近|最近)\s*(\d+)\s*场",
            r"(?:近|最近)\s*([一二两三四五六七八九十])\s*场",
            r"last\s+(\d+)\s+matches?",
            r"recent\s+(\d+)\s+matches?",
            r"last\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s+matches?",
            r"recent\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s+matches?",
        ]
        lowered = query.casefold()
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if not match:
                continue
            raw = match.group(1)
            value = int(raw) if raw.isdigit() else CHINESE_NUMBERS.get(raw) or ENGLISH_NUMBERS.get(raw)
            if value:
                return max(1, min(value, 10))
        if any(term in lowered for term in ("近况", "最近比赛", "recent matches", "last matches")):
            return 5
        return None

    def _recent_match_results(self, query: str) -> list[ScoutSearchResult]:
        limit = self._recent_match_limit(query)
        team_names = self._team_names_from_query(query)
        if not limit or not team_names:
            return []

        include_future = self._query_asks_future_matches(query)
        rows = self._all_match_rows()
        results: list[ScoutSearchResult] = []
        for team_name in team_names:
            team_rows = [
                row for row in rows
                if str(row["home_team"]).casefold() == team_name.casefold()
                or str(row["away_team"]).casefold() == team_name.casefold()
            ]
            if not include_future:
                completed_rows = [
                    row for row in team_rows
                    if bool(row["is_real"]) and int(row["home_score"]) >= 0 and int(row["away_score"]) >= 0
                ]
                if completed_rows:
                    team_rows = completed_rows
            team_rows.sort(key=lambda row: str(row.get("played_at") or ""), reverse=True)
            for index, row in enumerate(team_rows[:limit], start=1):
                is_real = bool(row["is_real"])
                home_score = row["home_score"]
                away_score = row["away_score"]
                status = "已完赛" if is_real else "未完赛/待赛"
                score = f"{home_score}-{away_score}" if is_real and home_score >= 0 and away_score >= 0 else "暂无比分"
                results.append(
                    ScoutSearchResult(
                        title=f"{team_name} 最近比赛 {index}：{row['home_team']} vs {row['away_team']}",
                        summary=(
                            f"{row['played_at']}，阶段 {row['stage']}，{row['home_team']} vs {row['away_team']}，"
                            f"状态：{status}，比分：{score}。"
                        ),
                        source="SQLite matches",
                        url=f"local://matches/{row['match_id']}",
                        score=100 - index,
                    )
                )
        return results

    @staticmethod
    def _query_asks_future_matches(query: str) -> bool:
        lowered = query.casefold()
        future_terms = ("下一场", "未来", "即将", "未赛", "赛程", "安排", "next", "upcoming", "future", "scheduled")
        return any(term in lowered for term in future_terms)

    def search_database(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        self.ensure_database()
        terms = self._query_terms(query)
        if not terms:
            return []

        results: list[ScoutSearchResult] = self._recent_match_results(query)
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

    async def search_web(self, query: str, count: int = DEFAULT_WEB_RESULT_COUNT) -> list[dict[str, Any]]:
        settings = get_settings()
        api_key = getattr(settings, "bocha_api_key", None)
        if not api_key:
            if not self._warned_missing_key:
                logger.warning("未配置 BOCHA_API_KEY，已跳过联网搜索功能，仅使用本地数据库检索。")
                self._warned_missing_key = True
            return []

        freshness = self._web_freshness(query)
        target_count = max(DEFAULT_WEB_RESULT_COUNT, min(count, 30))
        cache_key = hashlib.md5(f"{query}|{target_count}|{freshness}|trusted-first".encode("utf-8")).hexdigest()
        if cache_key in self.search_cache:
            return self.search_cache[cache_key]

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        raw_results: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                for trusted_query in self._trusted_site_queries(query):
                    try:
                        raw_results.extend(
                            await self._fetch_web_search(client, headers, trusted_query, count=4, freshness=freshness, preferred=True)
                        )
                    except Exception as exc:
                        logger.debug("高可信站点定向搜索失败，继续其他来源：%s", exc)
                try:
                    raw_results.extend(
                        await self._fetch_web_search(client, headers, query, count=target_count, freshness=freshness, preferred=False)
                    )
                except Exception as exc:
                    logger.warning("普通联网搜索调用失败：%s", exc)
        except Exception as exc:
            logger.warning("联网搜索调用失败，已跳过本次联网搜索：%s", exc)
            return []

        results = self._enrich_web_results(query, raw_results)[:target_count]
        self.search_cache[cache_key] = results
        return results

    async def _fetch_web_search(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        query: str,
        *,
        count: int,
        freshness: str,
        preferred: bool,
    ) -> list[dict[str, Any]]:
        payload = {"query": query, "summary": True, "count": count, "freshness": freshness}
        response = await client.post("https://api.bocha.cn/v1/web-search", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        webpages = data.get("data", {}).get("webPages", {}).get("value", [])
        return [
            {
                "title": item.get("name", "N/A"),
                "summary": item.get("summary") or item.get("snippet", ""),
                "source": item.get("siteName", "Web"),
                "url": item.get("url", ""),
                "date": item.get("datePublished") or item.get("dateLastCrawled", ""),
                "kind": "web",
                "preferred_search": preferred,
                "search_query": query,
            }
            for item in webpages
            if item.get("url") and (item.get("summary") or item.get("snippet"))
        ]

    def _trusted_site_queries(self, query: str) -> list[str]:
        domains = self.HISTORICAL_FOOTBALL_DOMAINS if self._web_freshness(query) == "noLimit" else self.TRUSTED_FOOTBALL_DOMAINS
        return [f"{query} site:{domain}" for domain in domains[:5]]

    async def search(self, query: str, *, include_web: bool = False, top_k: int = DEFAULT_WEB_RESULT_COUNT) -> dict[str, Any]:
        database_results = self.search_database(query, top_k=top_k)
        web_results = await self.search_web(query, count=top_k) if include_web else []
        return {
            "query": query,
            "database": database_results,
            "web": web_results,
            "source_trace": self.build_source_trace(query, web_results),
        }

    @staticmethod
    def _web_freshness(query: str) -> str:
        historical_terms = (
            "历史",
            "以前",
            "过去",
            "往届",
            "历届",
            "previous",
            "history",
            "historical",
            "all time",
            "archive",
        )
        lowered = query.casefold()
        if any(term in lowered for term in historical_terms):
            return "noLimit"
        recent_terms = (
            "今天",
            "今日",
            "现在",
            "刚刚",
            "最新",
            "近期",
            "实时",
            "赛前",
            "赛后",
            "比赛安排",
            "预测",
            "阵容",
            "伤停",
            "首发",
            "today",
            "latest",
            "recent",
            "current",
            "live",
            "preview",
            "lineup",
            "injury",
            "injuries",
            "prediction",
        )
        if any(term in lowered for term in recent_terms):
            return "oneWeek"
        if ("2026" in lowered or "world cup" in lowered or "世界杯" in lowered) and not any(term in lowered for term in historical_terms):
            return "oneWeek"
        return "oneMonth"

    def build_source_trace(self, query: str, web_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Build lightweight source rating, cross-check and trace metadata for UI display."""

        sources = [
            {
                "title": item.get("title", ""),
                "source": item.get("source", "Web"),
                "url": item.get("url", ""),
                "date": item.get("date", ""),
                "source_type": item.get("source_type", "news"),
                "credibility_score": item.get("credibility_score", 0.5),
                "credibility_label": item.get("credibility_label", "一般"),
                "cross_check_count": item.get("cross_check_count", 1),
                "trace_note": item.get("trace_note", ""),
                "timeliness_bucket": item.get("timeliness_bucket", "unknown"),
                "summary": item.get("summary", ""),
            }
            for item in web_results
            if item.get("url")
        ]
        source_count = len(sources)
        avg_score = round(sum(float(item["credibility_score"]) for item in sources) / source_count, 3) if source_count else 0
        cross_validated = [item for item in sources if int(item.get("cross_check_count") or 0) >= 2]
        high_quality = [item for item in sources if float(item.get("credibility_score") or 0) >= 0.75]
        tracing_queries = self._source_tracing_queries(query, sources)
        timeliness = self._timeliness_analysis(query, sources)
        if not sources:
            assessment = "本轮没有拿到可追溯网页来源。"
        elif len(cross_validated) >= 2:
            assessment = "本轮搜索包含多个相互印证的网页来源，可作为回答参考。"
        elif high_quality:
            assessment = "本轮搜索包含较高可信来源，但交叉验证数量有限。"
        else:
            assessment = "本轮搜索来源可信度一般，建议谨慎解读并继续核验。"
        return {
            "query": query,
            "source_count": source_count,
            "average_credibility": avg_score,
            "cross_validated_count": len(cross_validated),
            "high_quality_count": len(high_quality),
            "source_tracing_queries": tracing_queries,
            "assessment": assessment,
            "timeliness": timeliness,
            "sources": sources,
        }

    def _enrich_web_results(self, query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        fingerprints: set[str] = set()
        for item in results:
            fingerprint = hashlib.md5(f"{item.get('title', '')}|{item.get('url', '')}".encode("utf-8")).hexdigest()
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            source_type, credibility_score = self._rate_source(item.get("source", ""), item.get("url", ""))
            enriched.append(
                {
                    **item,
                    "source_type": source_type,
                    "credibility_score": credibility_score,
                    "credibility_label": self._credibility_label(credibility_score),
                    "source_priority": self._source_priority(item.get("url", ""), bool(item.get("preferred_search"))),
                    "fact_fingerprint": fingerprint,
                    "timeliness_bucket": self._timeliness_bucket(item.get("date", "")),
                }
            )

        tokens_by_result = [self._verification_tokens(f"{item.get('title', '')} {item.get('summary', '')}") for item in enriched]
        for index, item in enumerate(enriched):
            tokens = tokens_by_result[index]
            cross_count = 1
            for other_index, other_tokens in enumerate(tokens_by_result):
                if index == other_index or not tokens or not other_tokens:
                    continue
                overlap = len(tokens & other_tokens) / max(len(tokens | other_tokens), 1)
                if overlap >= 0.16:
                    cross_count += 1
            item["cross_check_count"] = cross_count
            item["trace_note"] = self._trace_note(item, cross_count)

        return sorted(
            enriched,
            key=lambda item: (
                item["source_priority"],
                self._timeliness_rank(item.get("timeliness_bucket", "")),
                item["credibility_score"],
                item["cross_check_count"],
            ),
            reverse=True,
        )

    @classmethod
    def _timeliness_analysis(cls, query: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        requires_recent = cls._query_requires_recent(query)
        parsed_dates = [cls._parse_source_datetime(str(item.get("date") or "")) for item in sources]
        parsed_dates = [item for item in parsed_dates if item is not None]
        now = datetime.now(timezone.utc)
        within_24h = sum(1 for item in parsed_dates if now - item <= timedelta(days=1))
        within_7d = sum(1 for item in parsed_dates if now - item <= timedelta(days=7))
        within_30d = sum(1 for item in parsed_dates if now - item <= timedelta(days=30))
        newest = max(parsed_dates).isoformat() if parsed_dates else None
        if not sources:
            status = "no_sources"
            passed = not requires_recent
        elif not parsed_dates:
            status = "unknown_dates"
            passed = not requires_recent
        elif requires_recent and within_7d == 0:
            status = "stale_for_recent_query"
            passed = False
        elif requires_recent and within_7d < max(2, min(5, len(sources) // 4)):
            status = "limited_recent_sources"
            passed = False
        else:
            status = "ok"
            passed = True
        return {
            "requires_recent": requires_recent,
            "passed": passed,
            "status": status,
            "dated_source_count": len(parsed_dates),
            "within_24h_count": within_24h,
            "within_7d_count": within_7d,
            "within_30d_count": within_30d,
            "newest_source_at": newest,
            "freshness_filter": cls._web_freshness(query),
        }

    @staticmethod
    def _parse_source_datetime(value: str) -> datetime | None:
        if not value:
            return None
        text = value.strip()
        for candidate in (text, text.replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                continue
        match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    @classmethod
    def _timeliness_bucket(cls, value: str) -> str:
        parsed = cls._parse_source_datetime(str(value or ""))
        if not parsed:
            return "unknown"
        age = datetime.now(timezone.utc) - parsed
        if age <= timedelta(days=1):
            return "24h"
        if age <= timedelta(days=7):
            return "7d"
        if age <= timedelta(days=30):
            return "30d"
        return "old"

    @staticmethod
    def _timeliness_rank(bucket: str) -> int:
        return {"24h": 4, "7d": 3, "30d": 2, "old": 1, "unknown": 0}.get(bucket, 0)

    @staticmethod
    def _query_requires_recent(query: str) -> bool:
        lowered = query.casefold()
        historical_terms = ("历史", "以前", "过去", "往届", "历届", "previous", "history", "historical", "archive")
        if any(term in lowered for term in historical_terms):
            return False
        recent_terms = (
            "今天",
            "今日",
            "现在",
            "刚刚",
            "最新",
            "近期",
            "实时",
            "赛前",
            "赛后",
            "比赛安排",
            "预测",
            "阵容",
            "伤停",
            "首发",
            "today",
            "latest",
            "recent",
            "current",
            "live",
            "preview",
            "lineup",
            "injury",
            "injuries",
            "prediction",
        )
        return any(term in lowered for term in recent_terms) or (
            ("2026" in lowered or "world cup" in lowered or "世界杯" in lowered)
            and not any(term in lowered for term in historical_terms)
        )

    @staticmethod
    def _rate_source(source_name: str, url: str) -> tuple[str, float]:
        host = urlparse(url).netloc.lower()
        label = f"{source_name} {host}".lower()
        official_terms = ["fifa.com", "uefa.com", "the-afc.com", "conmebol", "concacaf", "thefa.com", "afa.com.ar"]
        academic_terms = [".edu", "scholar", "researchgate", "arxiv", "doi.org"]
        authority_media = ["reuters", "apnews", "bbc", "espn", "skysports", "theguardian", "nytimes", "theathletic", "goal.com"]
        sports_data = [
            "transfermarkt",
            "sofascore",
            "fotmob",
            "whoscored",
            "worldfootball",
            "soccerway",
            "flashscore",
            "theanalyst.com",
            "rsssf.org",
        ]
        social_terms = ["twitter", "x.com", "facebook", "instagram", "reddit", "tiktok", "weibo", "youtube", "blog"]
        if any(term in label for term in official_terms):
            return "official", 0.95
        if any(term in label for term in academic_terms):
            return "academic", 0.86
        if any(term in label for term in authority_media):
            return "authoritative_media", 0.78
        if any(term in label for term in sports_data):
            return "sports_database", 0.74
        if any(term in label for term in social_terms):
            return "self_media", 0.38
        return "news", 0.62

    @classmethod
    def _source_priority(cls, url: str, preferred_search: bool) -> int:
        host = urlparse(url).netloc.lower()
        domain_hit = any(domain.replace("/sport", "").replace("/football", "") in host for domain in cls.TRUSTED_FOOTBALL_DOMAINS)
        historical_hit = any(domain in host for domain in cls.HISTORICAL_FOOTBALL_DOMAINS)
        if preferred_search and (domain_hit or historical_hit):
            return 3
        if domain_hit or historical_hit:
            return 2
        if preferred_search:
            return 1
        return 0

    @staticmethod
    def _credibility_label(score: float) -> str:
        if score >= 0.9:
            return "官方/极高"
        if score >= 0.75:
            return "较高"
        if score >= 0.55:
            return "一般"
        return "待核验"

    @staticmethod
    def _verification_tokens(text: str) -> set[str]:
        lowered = text.casefold()
        words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}|\d{1,4}", lowered))
        stopwords = {"the", "and", "for", "with", "from", "world", "cup", "football", "soccer", "match", "news"}
        return {word for word in words if word not in stopwords}

    @staticmethod
    def _trace_note(item: dict[str, Any], cross_count: int) -> str:
        if cross_count >= 2:
            return f"与 {cross_count - 1} 个来源存在关键词交叉，可作为相互印证线索。"
        if float(item.get("credibility_score") or 0) >= 0.75:
            return "来源评级较高，但当前搜索结果中缺少直接交叉印证。"
        return "单一来源信息，建议结合更多网页或官方来源核验。"

    @staticmethod
    def _source_tracing_queries(query: str, sources: list[dict[str, Any]]) -> list[str]:
        domains = []
        for item in sources[:4]:
            host = urlparse(str(item.get("url", ""))).netloc.replace("www.", "")
            if host:
                domains.append(host)
        queries = [f"{query} official source", f"{query} final score official", f"{query} team news official"]
        queries.extend(f"{query} site:{domain}" for domain in domains[:3])
        return list(dict.fromkeys(queries))[:6]

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
