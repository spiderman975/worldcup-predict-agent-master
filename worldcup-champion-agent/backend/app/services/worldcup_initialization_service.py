"""Initialize a new World Cup season without overwriting older seasons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.cache_service import cache_service

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.database import get_connection, init_db, set_active_season
from data_agent.sources.football_data_source import FootballDataSource

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
UNKNOWN_TEAM = "TBD"

EXPECTED_STAGE_COUNTS = {
    1: 72,
    2: 16,
    3: 4,
    4: 2,
    5: 1,
    6: 1,
}


@dataclass(frozen=True)
class WorldCupInitializeOptions:
    season: int
    activate: bool = True
    sync_football_data: bool = True
    bootstrap_teams: bool = True
    init_knockout_placeholders: bool = True


class WorldCupInitializationService:
    def initialize(self, options: WorldCupInitializeOptions) -> dict[str, Any]:
        init_db()
        warnings: list[str] = []
        matches_imported = 0
        placeholders_created = 0
        teams_created = 0
        teams_updated = 0

        with get_connection() as connection:
            self._upsert_season(connection, options)

        if options.sync_football_data:
            if not get_settings().football_data_api_key:
                warnings.append("未配置 FOOTBALL_DATA_API_KEY，已只创建赛季记录，未抓取官方赛程。")
            else:
                source = FootballDataSource(api_key=get_settings().football_data_api_key)
                imported = source.load_matches(options.season)
                with get_connection() as connection:
                    for index, match in enumerate(imported, start=1):
                        if not match.home_team and not match.away_team:
                            continue
                        match_id = self._local_match_id(options.season, match.match_id or f"import_{index}")
                        status = "finished" if match.is_real else "scheduled"
                        connection.execute(
                            """
                            INSERT INTO matches (
                                match_id, stage, home_team, away_team, home_score, away_score,
                                is_real, played_at, status, season, competition_code, source_match_id
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WC', ?)
                            ON CONFLICT(match_id) DO UPDATE SET
                                stage = excluded.stage,
                                home_team = excluded.home_team,
                                away_team = excluded.away_team,
                                home_score = excluded.home_score,
                                away_score = excluded.away_score,
                                is_real = excluded.is_real,
                                played_at = excluded.played_at,
                                status = excluded.status,
                                season = excluded.season,
                                competition_code = excluded.competition_code,
                                source_match_id = excluded.source_match_id
                            """,
                            (
                                match_id,
                                int(match.stage),
                                match.home_team or UNKNOWN_TEAM,
                                match.away_team or UNKNOWN_TEAM,
                                int(match.home_score),
                                int(match.away_score),
                                int(match.is_real),
                                match.played_at,
                                status,
                                int(options.season),
                                str(match.match_id),
                            ),
                        )
                        matches_imported += 1
                    if options.bootstrap_teams:
                        created, updated = self._bootstrap_teams(connection, options.season)
                        teams_created += created
                        teams_updated += updated
                    if options.init_knockout_placeholders:
                        placeholders_created = self._ensure_knockout_placeholders(connection, options.season)
                    warnings.extend(self._validate_mapping(connection, options.season))

        if options.activate:
            set_active_season(options.season)
        with get_connection() as connection:
            connection.execute(
                "UPDATE worldcup_seasons SET status = 'initialized', updated_at = CURRENT_TIMESTAMP WHERE season = ?",
                (options.season,),
            )

        cache_service.invalidate_matches()
        cache_service.invalidate_teams()
        result = {
            "success": True,
            "season": options.season,
            "activated": options.activate,
            "matches_imported": matches_imported,
            "placeholders_created": placeholders_created,
            "teams_created": teams_created,
            "teams_updated": teams_updated,
            "warnings": warnings,
            "message": "新一届世界杯初始化完成" if options.activate else "新一届世界杯初始化完成，尚未切换为当前届次",
        }
        self._save_maintenance_log("worldcup_initialize", "success", result)
        return result

    @staticmethod
    def _upsert_season(connection: Any, options: WorldCupInitializeOptions) -> None:
        connection.execute(
            """
            INSERT INTO worldcup_seasons (
                season, competition_code, competition_name, status, is_active, data_source, notes
            )
            VALUES (?, 'WC', 'World Cup', 'initializing', 0, 'football-data.org', ?)
            ON CONFLICT(season) DO UPDATE SET
                status = 'initializing',
                data_source = excluded.data_source,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (options.season, "Initialized from frontend ops flow"),
        )

    @staticmethod
    def _local_match_id(season: int, source_match_id: str) -> str:
        clean = "".join(ch if ch.isalnum() else "_" for ch in str(source_match_id)).strip("_").lower()
        return f"wc{season}_{clean or 'match'}"

    @staticmethod
    def _bootstrap_teams(connection: Any, season: int) -> tuple[int, int]:
        rows = connection.execute(
            """
            SELECT DISTINCT name FROM (
                SELECT home_team AS name FROM matches WHERE season = ?
                UNION
                SELECT away_team AS name FROM matches WHERE season = ?
            )
            WHERE name IS NOT NULL AND name <> '' AND upper(name) <> 'TBD'
            """,
            (season, season),
        ).fetchall()
        created = 0
        updated = 0
        for index, row in enumerate(rows, start=1):
            name = str(row["name"])
            cursor = connection.execute(
                """
                INSERT INTO teams (name, "group", attack_team, defensive_team, streak, starting_lineup, fifa_ranking)
                VALUES (?, 'TBD', 1.0, 1.0, 0, '[]', ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (name, 80 + index),
            )
            created += cursor.rowcount
            connection.execute(
                """
                INSERT OR IGNORE INTO team_season_profiles (
                    season, team_name, "group", attack_team, defensive_team, streak, fifa_ranking, source
                )
                SELECT ?, name, "group", attack_team, defensive_team, streak, fifa_ranking, 'football-data.org'
                FROM teams
                WHERE name = ?
                """,
                (season, name),
            )
            connection.execute(
                """
                UPDATE team_season_profiles
                SET updated_at = CURRENT_TIMESTAMP
                WHERE season = ? AND team_name = ?
                """,
                (season, name),
            )
            updated += 1
        return created, updated

    @staticmethod
    def _ensure_knockout_placeholders(connection: Any, season: int) -> int:
        row = connection.execute(
            "SELECT MAX(played_at) AS max_time FROM matches WHERE season = ? AND played_at IS NOT NULL",
            (season,),
        ).fetchone()
        start = _parse_time(row["max_time"]) or datetime(season, 7, 1, 20, 0)
        created = 0
        for stage, expected in EXPECTED_STAGE_COUNTS.items():
            if stage == 1:
                continue
            existing = int(connection.execute("SELECT COUNT(*) FROM matches WHERE season = ? AND stage = ?", (season, stage)).fetchone()[0])
            for slot in range(existing + 1, expected + 1):
                match_time = (start + timedelta(days=stage * 2 + slot, hours=slot % 4)).isoformat()
                cursor = connection.execute(
                    """
                    INSERT INTO matches (
                        match_id, stage, home_team, away_team, home_score, away_score,
                        is_real, played_at, status, season, competition_code, source_match_id
                    )
                    VALUES (?, ?, ?, ?, -1, -1, 0, ?, 'scheduled', ?, 'WC', ?)
                    ON CONFLICT(match_id) DO NOTHING
                    """,
                    (
                        f"wc{season}_placeholder_s{stage}_{slot}",
                        stage,
                        UNKNOWN_TEAM,
                        UNKNOWN_TEAM,
                        match_time,
                        season,
                        f"placeholder_s{stage}_{slot}",
                    ),
                )
                created += cursor.rowcount
        return created

    @staticmethod
    def _validate_mapping(connection: Any, season: int) -> list[str]:
        warnings: list[str] = []
        rows = connection.execute(
            "SELECT stage, COUNT(*) AS count FROM matches WHERE season = ? GROUP BY stage ORDER BY stage",
            (season,),
        ).fetchall()
        counts = {int(row["stage"]): int(row["count"]) for row in rows}
        for stage, expected in EXPECTED_STAGE_COUNTS.items():
            if counts.get(stage, 0) < expected:
                warnings.append(f"阶段 {stage} 当前只有 {counts.get(stage, 0)} 场，少于预期 {expected} 场。")
        group_count = int(connection.execute("SELECT COUNT(*) FROM matches WHERE season = ? AND stage = 1", (season,)).fetchone()[0])
        if group_count and group_count < EXPECTED_STAGE_COUNTS[1]:
            warnings.append("小组赛场次数不足，可能是数据源尚未公布完整赛程。")
        profile_groups = connection.execute(
            "SELECT COUNT(*) FROM team_season_profiles WHERE season = ? AND (\"group\" = '' OR upper(\"group\") = 'TBD')",
            (season,),
        ).fetchone()[0]
        if int(profile_groups):
            warnings.append("部分球队缺少明确小组分组，已暂存为 TBD，待数据源补齐后可再次初始化更新。")
        return warnings

    @staticmethod
    def _save_maintenance_log(action: str, status: str, detail: dict[str, Any]) -> None:
        import json

        init_db()
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO db_maintenance_log (action, status, detail_json) VALUES (?, ?, ?)",
                (action, status, json.dumps(detail, ensure_ascii=False)),
            )


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(BEIJING_TZ).replace(tzinfo=None)
    return parsed


worldcup_initialization_service = WorldCupInitializationService()
