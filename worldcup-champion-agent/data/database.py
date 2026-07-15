from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from data.models import Match, Member, Team


DB_PATH = Path(__file__).resolve().with_name("worldcup.db")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                "group" TEXT NOT NULL,
                attack_team REAL DEFAULT 1.0,
                defensive_team REAL DEFAULT 1.0,
                streak INTEGER DEFAULT 0,
                starting_lineup TEXT DEFAULT '[]',
                fifa_ranking INTEGER
            );

            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                team_name TEXT NOT NULL,
                attack REAL NOT NULL,
                defensive REAL NOT NULL,
                injured INTEGER DEFAULT 0,
                injury_description TEXT DEFAULT '',
                FOREIGN KEY (team_name) REFERENCES teams(name),
                UNIQUE (team_name, name)
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL UNIQUE,
                stage INTEGER NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_score INTEGER DEFAULT -1,
                away_score INTEGER DEFAULT -1,
                is_real BOOLEAN DEFAULT FALSE,
                played_at TEXT,
                status TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS app_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'completed',
                phase TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                error_message TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pre_match_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                query TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                include_web INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'completed',
                error_message TEXT,
                refreshed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            );

            CREATE TABLE IF NOT EXISTS post_match_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                query TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                parsed_home_score INTEGER,
                parsed_away_score INTEGER,
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                searched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at TEXT,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            );

            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source TEXT,
                source_url TEXT,
                category TEXT NOT NULL DEFAULT 'general',
                match_id TEXT,
                team_name TEXT,
                content TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(match_id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_documents_fts
            USING fts5(title, content, source, content='knowledge_documents', content_rowid='id');

            CREATE TRIGGER IF NOT EXISTS knowledge_documents_ai AFTER INSERT ON knowledge_documents BEGIN
                INSERT INTO knowledge_documents_fts(rowid, title, content, source)
                VALUES (new.id, new.title, new.content, new.source);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_documents_ad AFTER DELETE ON knowledge_documents BEGIN
                INSERT INTO knowledge_documents_fts(knowledge_documents_fts, rowid, title, content, source)
                VALUES ('delete', old.id, old.title, old.content, old.source);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_documents_au AFTER UPDATE ON knowledge_documents BEGIN
                INSERT INTO knowledge_documents_fts(knowledge_documents_fts, rowid, title, content, source)
                VALUES ('delete', old.id, old.title, old.content, old.source);
                INSERT INTO knowledge_documents_fts(rowid, title, content, source)
                VALUES (new.id, new.title, new.content, new.source);
            END;

            CREATE TABLE IF NOT EXISTS db_maintenance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_matches_stage ON matches(stage);
            CREATE INDEX IF NOT EXISTS idx_matches_played_at ON matches(played_at);
            CREATE INDEX IF NOT EXISTS idx_matches_home_away ON matches(home_team, away_team);
            CREATE INDEX IF NOT EXISTS idx_matches_status_time ON matches(is_real, played_at);
            CREATE INDEX IF NOT EXISTS idx_teams_group_rank ON teams("group", fifa_ranking);
            CREATE INDEX IF NOT EXISTS idx_teams_fifa_ranking ON teams(fifa_ranking);
            CREATE INDEX IF NOT EXISTS idx_members_team ON members(team_name);
            CREATE INDEX IF NOT EXISTS idx_members_injured ON members(team_name, injured);
            CREATE INDEX IF NOT EXISTS idx_members_name ON members(name);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_name ON app_checkpoints(name);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_status_updated ON app_checkpoints(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_pre_match_updates_match_time ON pre_match_updates(match_id, refreshed_at);
            CREATE INDEX IF NOT EXISTS idx_post_match_results_match_time ON post_match_results(match_id, searched_at);
            CREATE INDEX IF NOT EXISTS idx_post_match_results_status ON post_match_results(status, searched_at);
            CREATE INDEX IF NOT EXISTS idx_knowledge_match ON knowledge_documents(match_id);
            CREATE INDEX IF NOT EXISTS idx_knowledge_team ON knowledge_documents(team_name);
            CREATE INDEX IF NOT EXISTS idx_knowledge_category_status ON knowledge_documents(category, status);
            CREATE INDEX IF NOT EXISTS idx_maintenance_action_time ON db_maintenance_log(action, created_at);
            """
        )
        _ensure_column(connection, "matches", "status", "TEXT DEFAULT ''")


def get_all_teams() -> list[Team]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT name, "group", attack_team, defensive_team, streak, starting_lineup, fifa_ranking
            FROM teams
            ORDER BY name
            """
        ).fetchall()
        return [_team_from_row(connection, row) for row in rows]


def get_team(name: str) -> Team:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT name, "group", attack_team, defensive_team, streak, starting_lineup, fifa_ranking
            FROM teams
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Team not found: {name}")
        return _team_from_row(connection, row)


def get_matches(stage: int) -> list[Match]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status
            FROM matches
            WHERE stage = ?
            ORDER BY id
            """,
            (stage,),
        ).fetchall()
        return [_match_from_row(row) for row in rows]


def save_team(team: Team) -> None:
    save_teams([team])


def save_teams(teams: Iterable[Team]) -> None:
    init_db()
    with get_connection() as connection:
        for team in teams:
            connection.execute(
                """
                INSERT INTO teams (name, "group", attack_team, defensive_team, streak, starting_lineup, fifa_ranking)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    "group" = excluded."group",
                    attack_team = excluded.attack_team,
                    defensive_team = excluded.defensive_team,
                    streak = excluded.streak,
                    starting_lineup = excluded.starting_lineup,
                    fifa_ranking = excluded.fifa_ranking
                """,
                (
                    team.name,
                    team.group,
                    team.attack_team,
                    team.defensive_team,
                    team.streak,
                    json.dumps(team.starting_lineup, ensure_ascii=False),
                    team.fifa_ranking,
                ),
            )
            for member in team.members:
                connection.execute(
                    """
                    INSERT INTO members (name, team_name, attack, defensive, injured, injury_description)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(team_name, name) DO UPDATE SET
                        attack = excluded.attack,
                        defensive = excluded.defensive,
                        injured = excluded.injured,
                        injury_description = excluded.injury_description
                    """,
                    (
                        member.name,
                        team.name,
                        member.attack_member,
                        member.defensive_member,
                        member.injured,
                        member.injury_description,
                    ),
                )


def save_match(match: Match) -> None:
    save_matches([match])


def save_matches(matches: list[Match]) -> None:
    init_db()
    with get_connection() as connection:
        _upsert_matches(connection, matches)


def replace_matches(matches: list[Match]) -> None:
    init_db()
    with get_connection() as connection:
        _upsert_matches(connection, matches)
        _migrate_match_references(connection, matches)
        incoming_ids = [match.match_id for match in matches]
        if incoming_ids:
            placeholders = ",".join("?" for _ in incoming_ids)
            connection.execute(
                f"""
                DELETE FROM matches
                WHERE match_id NOT IN ({placeholders})
                  AND match_id NOT IN (SELECT DISTINCT match_id FROM pre_match_updates)
                  AND match_id NOT IN (SELECT DISTINCT match_id FROM post_match_results)
                  AND match_id NOT IN (
                      SELECT DISTINCT match_id FROM knowledge_documents WHERE match_id IS NOT NULL
                  )
                """,
                incoming_ids,
            )
        else:
            connection.execute(
                """
                DELETE FROM matches
                WHERE match_id NOT IN (SELECT DISTINCT match_id FROM pre_match_updates)
                  AND match_id NOT IN (SELECT DISTINCT match_id FROM post_match_results)
                  AND match_id NOT IN (
                      SELECT DISTINCT match_id FROM knowledge_documents WHERE match_id IS NOT NULL
                  )
                """
            )


def save_real_score(match_id: str, home: int, away: int) -> None:
    if home < 0 or away < 0:
        raise ValueError("Real scores must be non-negative")
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE matches
            SET home_score = ?, away_score = ?, is_real = 1, status = 'FINISHED'
            WHERE match_id = ?
            """,
            (home, away, match_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Match not found: {match_id}")


def update_injury(team: str, player: str, injured: int, desc: str) -> None:
    if injured not in {0, 1}:
        raise ValueError("injured must be 0 or 1")
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE members
            SET injured = ?, injury_description = ?
            WHERE team_name = ? AND name = ?
            """,
            (injured, desc, team, player),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Member not found: {team} / {player}")


def update_starting_lineup(team: str, lineup: list[str]) -> None:
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE teams
            SET starting_lineup = ?
            WHERE name = ?
            """,
            (json.dumps(lineup, ensure_ascii=False), team),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Team not found: {team}")


def update_streak(team: str, streak: int) -> None:
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE teams
            SET streak = ?
            WHERE name = ?
            """,
            (streak, team),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Team not found: {team}")


def update_fifa_ranking(team: str, fifa_ranking: int) -> None:
    init_db()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE teams
            SET fifa_ranking = ?
            WHERE name = ?
            """,
            (fifa_ranking, team),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Team not found: {team}")


def get_injured_players(team: str) -> list[Member]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT name, attack, defensive, injured, injury_description
            FROM members
            WHERE team_name = ? AND injured = 1
            ORDER BY name
            """,
            (team,),
        ).fetchall()
        return [_member_from_row(row) for row in rows]


def _team_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> Team:
    member_rows = connection.execute(
        """
        SELECT name, attack, defensive, injured, injury_description
        FROM members
        WHERE team_name = ?
        ORDER BY id
        """,
        (row["name"],),
    ).fetchall()
    return Team(
        name=row["name"],
        group=row["group"],
        members=[_member_from_row(member_row) for member_row in member_rows],
        attack_team=float(row["attack_team"]),
        defensive_team=float(row["defensive_team"]),
        starting_lineup=_load_lineup(row["starting_lineup"]),
        streak=int(row["streak"]),
        fifa_ranking=row["fifa_ranking"],
    )


def _member_from_row(row: sqlite3.Row) -> Member:
    return Member(
        name=row["name"],
        attack_member=float(row["attack"]),
        defensive_member=float(row["defensive"]),
        injured=int(row["injured"]),
        injury_description=row["injury_description"] or "",
    )


def _match_from_row(row: sqlite3.Row) -> Match:
    return Match(
        match_id=row["match_id"],
        stage=int(row["stage"]),
        home_team=row["home_team"],
        away_team=row["away_team"],
        home_score=int(row["home_score"]),
        away_score=int(row["away_score"]),
        is_real=bool(row["is_real"]),
        played_at=row["played_at"],
        status=row["status"] if "status" in row.keys() else "",
    )


def _load_lineup(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _normalize_match_score(match: Match) -> tuple[int, int, bool]:
    if match.home_score == -1 and match.away_score == -1:
        return -1, -1, False
    if match.home_score < 0 or match.away_score < 0:
        raise ValueError(f"Match {match.match_id} must use -1/-1 for unplayed scores")
    return match.home_score, match.away_score, bool(match.is_real)


def _upsert_matches(connection: sqlite3.Connection, matches: list[Match]) -> None:
    for match in matches:
        home_score, away_score, is_real = _normalize_match_score(match)
        connection.execute(
            """
            INSERT INTO matches (
                match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                stage = excluded.stage,
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                home_score = excluded.home_score,
                away_score = excluded.away_score,
                is_real = excluded.is_real,
                played_at = excluded.played_at,
                status = excluded.status
            """,
            (
                match.match_id,
                match.stage,
                match.home_team,
                match.away_team,
                home_score,
                away_score,
                int(is_real),
                match.played_at,
                match.status,
            ),
        )


def _migrate_match_references(connection: sqlite3.Connection, matches: list[Match]) -> None:
    for match in matches:
        legacy_rows = connection.execute(
            """
            SELECT match_id
            FROM matches
            WHERE match_id != ?
              AND home_team = ?
              AND away_team = ?
              AND played_at IS ?
            """,
            (match.match_id, match.home_team, match.away_team, match.played_at),
        ).fetchall()
        for row in legacy_rows:
            old_match_id = row["match_id"]
            for table in ("pre_match_updates", "post_match_results", "knowledge_documents"):
                connection.execute(
                    f"UPDATE {table} SET match_id = ? WHERE match_id = ?",
                    (match.match_id, old_match_id),
                )


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
