from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_agent.team_aliases import canonicalize_team_name, load_team_aliases


@dataclass
class CheckResult:
    name: str
    passed: bool
    failures: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate World Cup seed CSV files before ingestion.")
    parser.add_argument("--teams", required=True)
    parser.add_argument("--squads", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--rankings", required=True)
    parser.add_argument("--lineups", default=None)
    parser.add_argument("--injuries", default=None)
    parser.add_argument("--aliases", default="datasets/team_aliases.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    teams = _read_csv(args.teams)
    squads = _read_csv(args.squads)
    schedule = _read_csv(args.schedule)
    rankings = _read_csv(args.rankings)
    lineups = _read_csv(args.lineups) if args.lineups else []
    injuries = _read_csv(args.injuries) if args.injuries else []
    aliases = load_team_aliases(args.aliases)
    _canonicalize_rows(teams, aliases, "name")
    _canonicalize_rows(squads, aliases, "team_name")
    _canonicalize_rows(schedule, aliases, "home_team", "away_team")
    _canonicalize_rows(rankings, aliases, "team_name")
    _canonicalize_rows(lineups, aliases, "team_name")
    _canonicalize_rows(injuries, aliases, "team_name")

    print(f"teams_count={len(teams)}")
    print(f"members_count={len(squads)}")
    print(f"matches_count={len(schedule)}")
    member_counts = _member_counts(teams, squads)
    print(
        "team_member_counts="
        + ",".join(f"{team}:{member_counts[team]}" for team in sorted(member_counts))
    )
    scaffold_teams = _scaffold_fallback_teams(teams, squads)
    print("scaffold_fallback_teams=" + ",".join(scaffold_teams))

    checks = [
        _check_team_names_unique(teams),
        _check_squad_teams_exist(teams, squads),
        _check_team_member_counts(teams, squads),
        _check_member_ranges(squads),
        _check_member_injured(squads),
        _check_schedule_teams_exist(teams, schedule),
        _check_match_id_unique(schedule),
        _check_stage(schedule),
        _check_unplayed_scores(schedule),
        _check_ranking_teams_exist(teams, rankings),
        _check_rankings_positive(rankings),
        _check_lineups_exist(squads, lineups),
        _check_injuries_exist(squads, injuries),
    ]

    failed = False
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{status} {check.name}")
        for failure in check.failures:
            print(f"  - {failure}")
        failed = failed or not check.passed
    return 1 if failed else 0


def _read_csv(path: str | None) -> list[dict[str, str]]:
    if not path:
        return []
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def _canonicalize_rows(rows: list[dict[str, str]], aliases: dict[str, str], *columns: str) -> None:
    for row in rows:
        for column in columns:
            if row.get(column):
                row[column] = canonicalize_team_name(row[column], aliases)


def _result(name: str, failures: list[str]) -> CheckResult:
    return CheckResult(name=name, passed=not failures, failures=failures)


def _team_names(teams: list[dict[str, str]]) -> set[str]:
    return {row["name"] for row in teams}


def _squad_keys(squads: list[dict[str, str]]) -> set[tuple[str, str]]:
    return {(row["team_name"], row["name"]) for row in squads}


def _member_counts(teams: list[dict[str, str]], squads: list[dict[str, str]]) -> dict[str, int]:
    counts = {team["name"]: 0 for team in teams}
    for row in squads:
        if row["team_name"] in counts:
            counts[row["team_name"]] += 1
    return counts


def _scaffold_fallback_teams(teams: list[dict[str, str]], squads: list[dict[str, str]]) -> list[str]:
    by_team: dict[str, list[str]] = {team["name"]: [] for team in teams}
    for row in squads:
        if row["team_name"] in by_team:
            by_team[row["team_name"]].append(row["name"])
    return [
        team
        for team, players in sorted(by_team.items())
        if players and all(_looks_like_scaffold_player(team, player) for player in players)
    ]


def _looks_like_scaffold_player(team_name: str, player_name: str) -> bool:
    escaped = re.escape(team_name)
    return bool(
        re.fullmatch(rf"{escaped} Player \d{{2}}", player_name)
        or re.fullmatch(rf"{escaped} (GK|DF\d+|MF\d+|FW\d+)", player_name)
    )


def _check_team_names_unique(teams: list[dict[str, str]]) -> CheckResult:
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in teams:
        name = row["name"]
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    return _result("team name is unique", duplicates)


def _check_squad_teams_exist(teams: list[dict[str, str]], squads: list[dict[str, str]]) -> CheckResult:
    names = _team_names(teams)
    failures = [f"{row['team_name']} / {row['name']}" for row in squads if row["team_name"] not in names]
    return _result("squads.team_name exists in teams", failures)


def _check_team_member_counts(teams: list[dict[str, str]], squads: list[dict[str, str]]) -> CheckResult:
    counts = {team["name"]: 0 for team in teams}
    for row in squads:
        if row["team_name"] in counts:
            counts[row["team_name"]] += 1
    failures = [f"{team} has {count} members" for team, count in sorted(counts.items()) if count < 11]
    return _result("each team has at least 11 members", failures)


def _check_member_ranges(squads: list[dict[str, str]]) -> CheckResult:
    failures: list[str] = []
    for row in squads:
        attack = _to_float(row["attack"])
        defensive = _to_float(row["defensive"])
        if attack is None or defensive is None or not 0 <= attack <= 100 or not 0 <= defensive <= 100:
            failures.append(f"{row['team_name']} / {row['name']} attack={row['attack']} defensive={row['defensive']}")
    return _result("attack/defensive are in 0~100", failures)


def _check_member_injured(squads: list[dict[str, str]]) -> CheckResult:
    failures = [
        f"{row['team_name']} / {row['name']} injured={row['injured']}"
        for row in squads
        if row["injured"] not in {"0", "1"}
    ]
    return _result("injured is 0 or 1", failures)


def _check_schedule_teams_exist(teams: list[dict[str, str]], schedule: list[dict[str, str]]) -> CheckResult:
    names = _team_names(teams)
    failures = [
        f"{row['match_id']} home_team={row['home_team']} away_team={row['away_team']}"
        for row in schedule
        if row["home_team"] not in names or row["away_team"] not in names
    ]
    return _result("schedule teams exist", failures)


def _check_match_id_unique(schedule: list[dict[str, str]]) -> CheckResult:
    seen: set[str] = set()
    failures: list[str] = []
    for row in schedule:
        match_id = row["match_id"]
        if match_id in seen:
            failures.append(match_id)
        seen.add(match_id)
    return _result("match_id is unique", failures)


def _check_stage(schedule: list[dict[str, str]]) -> CheckResult:
    failures: list[str] = []
    for row in schedule:
        stage = _to_int(row["stage"])
        if stage is None or not 1 <= stage <= 8:
            failures.append(f"{row['match_id']} stage={row['stage']}")
    return _result("stage is in 1~8", failures)


def _check_unplayed_scores(schedule: list[dict[str, str]]) -> CheckResult:
    failures: list[str] = []
    for row in schedule:
        is_real = row["is_real"].lower() in {"1", "true", "yes", "y"}
        if not is_real and (row["home_score"] != "-1" or row["away_score"] != "-1"):
            failures.append(f"{row['match_id']} home_score={row['home_score']} away_score={row['away_score']}")
    return _result("unplayed matches use -1/-1", failures)


def _check_ranking_teams_exist(teams: list[dict[str, str]], rankings: list[dict[str, str]]) -> CheckResult:
    names = _team_names(teams)
    failures = [row["team_name"] for row in rankings if row["team_name"] not in names]
    return _result("ranking team_name exists in teams", failures)


def _check_rankings_positive(rankings: list[dict[str, str]]) -> CheckResult:
    failures: list[str] = []
    for row in rankings:
        ranking = _to_int(row["fifa_ranking"])
        if ranking is None or ranking <= 0:
            failures.append(f"{row['team_name']} fifa_ranking={row['fifa_ranking']}")
    return _result("fifa_ranking is positive integer", failures)


def _check_lineups_exist(squads: list[dict[str, str]], lineups: list[dict[str, str]]) -> CheckResult:
    keys = _squad_keys(squads)
    failures = [
        f"{row['team_name']} / {row['player_name']}"
        for row in lineups
        if (row["team_name"], row["player_name"]) not in keys
    ]
    return _result("lineup players exist in squads", failures)


def _check_injuries_exist(squads: list[dict[str, str]], injuries: list[dict[str, str]]) -> CheckResult:
    keys = _squad_keys(squads)
    failures = [
        f"{row['team_name']} / {row['player_name']}"
        for row in injuries
        if (row["team_name"], row["player_name"]) not in keys
    ]
    return _result("injury players exist in squads", failures)


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
