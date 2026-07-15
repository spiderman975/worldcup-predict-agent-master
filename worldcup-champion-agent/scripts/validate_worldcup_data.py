from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "worldcup.db"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.stages import STAGE_NUMBER_TO_KEY


@dataclass
class CheckResult:
    name: str
    passed: bool
    failures: list[str]


def main() -> int:
    if not DB_PATH.exists():
        print(f"database_missing={DB_PATH}", file=sys.stderr)
        return 2

    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        teams_count = _count(connection, "teams")
        members_count = _count(connection, "members")
        matches_count = _count(connection, "matches")
        print(f"teams_count={teams_count}")
        print(f"members_count={members_count}")
        print(f"matches_count={matches_count}")

        checks = [
            _check_non_empty(connection, "teams"),
            _check_non_empty(connection, "members"),
            _check_non_empty(connection, "matches"),
            _check_team_member_counts(connection),
            _check_member_ranges(connection),
            _check_member_injured(connection),
            _check_starting_lineup_json(connection),
            _check_starting_lineup_members(connection),
            _check_match_stage(connection),
            _check_unplayed_scores(connection),
            _check_real_scores(connection),
            _check_match_teams(connection),
            _check_match_id_unique(connection),
            _check_fifa_ranking(connection),
        ]

    has_failures = False
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{status} {check.name}")
        for failure in check.failures:
            print(f"  - {failure}")
        has_failures = has_failures or not check.passed
    return 1 if has_failures else 0


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _result(name: str, failures: list[str]) -> CheckResult:
    return CheckResult(name=name, passed=not failures, failures=failures)


def _check_non_empty(connection: sqlite3.Connection, table: str) -> CheckResult:
    count = _count(connection, table)
    return _result(f"{table} table is non-empty", [] if count > 0 else [f"{table} is empty"])


def _check_team_member_counts(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT teams.name, COUNT(members.id) AS member_count
        FROM teams
        LEFT JOIN members ON members.team_name = teams.name
        GROUP BY teams.name
        HAVING COUNT(members.id) < 11
        ORDER BY teams.name
        """
    ).fetchall()
    return _result(
        "each team has at least 11 members",
        [f"{row['name']} has {row['member_count']} members" for row in rows],
    )


def _check_member_ranges(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT team_name, name, attack, defensive
        FROM members
        WHERE attack < 0 OR attack > 100 OR defensive < 0 OR defensive > 100
        ORDER BY team_name, name
        """
    ).fetchall()
    return _result(
        "member attack/defensive are in 0~100",
        [f"{row['team_name']} / {row['name']} attack={row['attack']} defensive={row['defensive']}" for row in rows],
    )


def _check_member_injured(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT team_name, name, injured
        FROM members
        WHERE injured NOT IN (0, 1)
        ORDER BY team_name, name
        """
    ).fetchall()
    return _result(
        "member injured is 0 or 1",
        [f"{row['team_name']} / {row['name']} injured={row['injured']}" for row in rows],
    )


def _check_starting_lineup_json(connection: sqlite3.Connection) -> CheckResult:
    failures: list[str] = []
    rows = connection.execute("SELECT name, starting_lineup FROM teams ORDER BY name").fetchall()
    for row in rows:
        try:
            parsed = json.loads(row["starting_lineup"] or "[]")
        except json.JSONDecodeError as exc:
            failures.append(f"{row['name']} invalid JSON: {exc}")
            continue
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            failures.append(f"{row['name']} starting_lineup must be a JSON string array")
    return _result("teams.starting_lineup is valid JSON array", failures)


def _check_starting_lineup_members(connection: sqlite3.Connection) -> CheckResult:
    failures: list[str] = []
    rows = connection.execute("SELECT name, starting_lineup FROM teams ORDER BY name").fetchall()
    for row in rows:
        lineup = json.loads(row["starting_lineup"] or "[]")
        if not lineup:
            continue
        member_names = {
            member_row["name"]
            for member_row in connection.execute("SELECT name FROM members WHERE team_name = ?", (row["name"],)).fetchall()
        }
        for player in lineup:
            if player not in member_names:
                failures.append(f"{row['name']} lineup player is not in members: {player}")
    return _result("starting_lineup players belong to team members", failures)


def _check_match_stage(connection: sqlite3.Connection) -> CheckResult:
    valid_stages = tuple(sorted(STAGE_NUMBER_TO_KEY))
    placeholders = ",".join("?" for _ in valid_stages)
    rows = connection.execute(
        f"SELECT match_id, stage FROM matches WHERE stage NOT IN ({placeholders}) ORDER BY match_id",
        valid_stages,
    ).fetchall()
    return _result(f"matches.stage is one of {list(valid_stages)}", [f"{row['match_id']} stage={row['stage']}" for row in rows])


def _check_unplayed_scores(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT match_id, home_score, away_score, is_real
        FROM matches
        WHERE is_real = 0 AND (home_score != -1 OR away_score != -1)
        ORDER BY match_id
        """
    ).fetchall()
    return _result(
        "unplayed matches use -1/-1 scores",
        [
            f"{row['match_id']} home_score={row['home_score']} away_score={row['away_score']} is_real={row['is_real']}"
            for row in rows
        ],
    )


def _check_real_scores(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT match_id, home_score, away_score
        FROM matches
        WHERE is_real = 1 AND (home_score < 0 OR away_score < 0)
        ORDER BY match_id
        """
    ).fetchall()
    return _result(
        "real matches have non-negative scores",
        [f"{row['match_id']} home_score={row['home_score']} away_score={row['away_score']}" for row in rows],
    )


def _check_match_teams(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT match_id, home_team, away_team
        FROM matches
        WHERE home_team NOT IN (SELECT name FROM teams)
           OR away_team NOT IN (SELECT name FROM teams)
        ORDER BY match_id
        """
    ).fetchall()
    return _result(
        "match home_team and away_team exist in teams",
        [f"{row['match_id']} home_team={row['home_team']} away_team={row['away_team']}" for row in rows],
    )


def _check_match_id_unique(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT match_id, COUNT(*) AS count
        FROM matches
        GROUP BY match_id
        HAVING COUNT(*) > 1
        ORDER BY match_id
        """
    ).fetchall()
    return _result("match_id is unique", [f"{row['match_id']} count={row['count']}" for row in rows])


def _check_fifa_ranking(connection: sqlite3.Connection) -> CheckResult:
    rows = connection.execute(
        """
        SELECT name, fifa_ranking
        FROM teams
        WHERE fifa_ranking IS NOT NULL AND fifa_ranking <= 0
        ORDER BY name
        """
    ).fetchall()
    return _result(
        "fifa_ranking is positive when present",
        [f"{row['name']} fifa_ranking={row['fifa_ranking']}" for row in rows],
    )


if __name__ == "__main__":
    raise SystemExit(main())

