from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_agent.team_aliases import canonicalize_team_name, load_team_aliases
from data.stages import football_data_stage_to_number


FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
COMPETITION_CODE = "WC"
FINISHED_STATUSES = {"FINISHED", "AWARDED"}
SQUAD_FIELDNAMES = ["team_name", "name", "attack", "defensive", "injured", "injury_description"]
LINEUP_FIELDNAMES = ["team_name", "player_name"]
INJURY_FIELDNAMES = ["team_name", "player_name", "injured", "injury_description"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build official teams and schedule CSVs from football-data.org raw data.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--raw-dir", default="datasets/raw")
    parser.add_argument("--output-dir", default="datasets")
    parser.add_argument("--from-raw", action="store_true", help="Use existing raw JSON files instead of fetching.")
    parser.add_argument("--teams-raw", default=None, help="Path to a downloaded football-data.org teams JSON file.")
    parser.add_argument("--matches-raw", default=None, help="Path to a downloaded football-data.org matches JSON file.")
    parser.add_argument("--squads", default="datasets/squads_2026.csv", help="Existing squads CSV used for canonical team-name checks.")
    parser.add_argument("--aliases", default="datasets/team_aliases.csv", help="CSV mapping source team names to canonical names.")
    parser.add_argument(
        "--rebuild-dependent-scaffolds",
        action="store_true",
        help="Also rebuild squads, lineups, and injuries so they align with the official canonical team universe.",
    )
    parser.add_argument("--write", action="store_true", help="Write datasets/teams_2026.csv and schedule_2026.csv.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    output_dir = Path(args.output_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    teams_raw_path = Path(args.teams_raw) if args.teams_raw else raw_dir / f"football_data_teams_{args.year}.json"
    matches_raw_path = Path(args.matches_raw) if args.matches_raw else raw_dir / f"football_data_matches_{args.year}.json"
    metadata_path = raw_dir / f"football_data_build_{args.year}_metadata.json"
    aliases = load_team_aliases(args.aliases)

    try:
        raw_mode = bool(args.teams_raw and args.matches_raw) or args.from_raw
        if raw_mode:
            teams_payload = _read_json(teams_raw_path)
            matches_payload = _read_json(matches_raw_path)
            source_mode = "raw-file"
        else:
            _load_dotenv()
            api_key = os.getenv("FOOTBALL_DATA_API_KEY")
            if not api_key:
                print(
                    "missing_input=provide FOOTBALL_DATA_API_KEY in .env/environment or pass --teams-raw and --matches-raw",
                    file=sys.stderr,
                )
                return 2
            teams_payload = _fetch_football_data(api_key, f"/competitions/{COMPETITION_CODE}/teams", {"season": args.year})
            matches_payload = _fetch_football_data(api_key, f"/competitions/{COMPETITION_CODE}/matches", {"season": args.year})
            teams_raw_path.write_text(json.dumps(teams_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            matches_raw_path.write_text(json.dumps(matches_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            source_mode = "api"

        teams_rows = build_team_rows(teams_payload, matches_payload, output_dir / "fifa_rankings.csv", aliases)
        schedule_rows, skipped_matches = build_schedule_rows(matches_payload, aliases)
        scaffold_rows: tuple[list[dict], list[dict], list[dict]] | None = None
        if args.rebuild_dependent_scaffolds:
            teams_rows, squad_rows, lineup_rows, injury_rows = rebuild_dependent_scaffolds(
                teams_rows,
                Path(args.squads),
                aliases,
            )
            scaffold_rows = (squad_rows, lineup_rows, injury_rows)
        validation_errors = validate_rows_for_project(
            teams_rows,
            schedule_rows,
            Path(args.squads),
            output_dir / "fifa_rankings.csv",
            skip_squad_mismatch=args.rebuild_dependent_scaffolds,
            skip_ranking_mismatch=args.rebuild_dependent_scaffolds,
        )
        should_write = args.write or args.rebuild_dependent_scaffolds
        _write_metadata(
            metadata_path,
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_mode": source_mode,
                "teams_raw": str(teams_raw_path),
                "matches_raw": str(matches_raw_path),
                "output_teams": str(output_dir / f"teams_{args.year}.csv"),
                "output_schedule": str(output_dir / f"schedule_{args.year}.csv"),
                "aliases": str(args.aliases),
                "rebuild_dependent_scaffolds": bool(args.rebuild_dependent_scaffolds),
                "skipped_matches_missing_teams": skipped_matches,
                "wrote_csv": bool(should_write and not validation_errors),
                "validation_errors": validation_errors,
            },
        )
        if validation_errors:
            raise ValueError("official rows are not compatible with current project CSVs:\n" + "\n".join(validation_errors))
        print(f"official_teams_count={len(teams_rows)}")
        print(f"official_matches_count={len(schedule_rows)}")
        print(f"skipped_matches_missing_teams={skipped_matches}")
        print(f"raw_teams={teams_raw_path}")
        print(f"raw_matches={matches_raw_path}")
        print(f"metadata={metadata_path}")

        if should_write:
            _write_csv(
                output_dir / f"teams_{args.year}.csv",
                ["name", "group", "attack_team", "defensive_team", "streak", "starting_lineup", "fifa_ranking"],
                teams_rows,
            )
            _write_csv(
                output_dir / f"schedule_{args.year}.csv",
                ["match_id", "stage", "home_team", "away_team", "home_score", "away_score", "is_real", "played_at"],
                schedule_rows,
            )
            if scaffold_rows:
                squad_rows, lineup_rows, injury_rows = scaffold_rows
                _write_csv(output_dir / f"squads_{args.year}.csv", SQUAD_FIELDNAMES, squad_rows)
                _write_csv(output_dir / f"lineups_{args.year}.csv", LINEUP_FIELDNAMES, lineup_rows)
                _write_csv(output_dir / f"injuries_{args.year}.csv", INJURY_FIELDNAMES, injury_rows)
    except (FileNotFoundError, HTTPError, URLError, ValueError) as exc:
        print(f"official_build_error={exc}", file=sys.stderr)
        return 1
    return 0


def build_team_rows(
    teams_payload: dict,
    matches_payload: dict,
    rankings_path: Path,
    aliases: dict[str, str],
) -> list[dict[str, str | int | float]]:
    rankings = _read_rankings(rankings_path, aliases)
    group_by_team = _group_by_team(matches_payload, aliases)
    rows: list[dict[str, str | int | float]] = []
    for team in teams_payload.get("teams", []):
        name = canonicalize_team_name(_team_name(team), aliases)
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "group": group_by_team.get(name, "TBD"),
                "attack_team": 1.0,
                "defensive_team": 1.0,
                "streak": 0,
                "starting_lineup": "",
                "fifa_ranking": rankings.get(name, ""),
            }
        )
    return sorted(rows, key=lambda row: (str(row["group"]), str(row["name"])))


def build_schedule_rows(matches_payload: dict, aliases: dict[str, str]) -> tuple[list[dict[str, str | int]], int]:
    rows: list[dict[str, str | int]] = []
    seen_ids: set[str] = set()
    skipped = 0
    for match in matches_payload.get("matches", []):
        home_team = canonicalize_team_name(_team_name(match.get("homeTeam") or {}), aliases)
        away_team = canonicalize_team_name(_team_name(match.get("awayTeam") or {}), aliases)
        if not home_team or not away_team:
            skipped += 1
            continue
        status = str(match.get("status") or "").upper()
        score = match.get("score") or {}
        full_time = score.get("fullTime") or {}
        is_real = status in FINISHED_STATUSES and full_time.get("home") is not None and full_time.get("away") is not None
        stage = _stage_number(match)
        rows.append(
            {
                "match_id": _stable_match_id(stage, home_team, away_team, match.get("id"), seen_ids),
                "stage": stage,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": int(full_time["home"]) if is_real else -1,
                "away_score": int(full_time["away"]) if is_real else -1,
                "is_real": "true" if is_real else "false",
                "played_at": match.get("utcDate") or "",
            }
        )
    return rows, skipped


def validate_rows_for_project(
    teams_rows: list[dict[str, str | int | float]],
    schedule_rows: list[dict[str, str | int]],
    squads_path: Path,
    rankings_path: Path,
    skip_squad_mismatch: bool = False,
    skip_ranking_mismatch: bool = False,
) -> list[str]:
    errors: list[str] = []
    team_names = {str(row["name"]) for row in teams_rows}
    if len(team_names) != len(teams_rows):
        errors.append("duplicate team names in official teams payload")
    if len(team_names) != 48:
        errors.append(f"expected 48 World Cup teams, got {len(team_names)}")
    if not schedule_rows:
        errors.append("official matches payload produced no schedule rows")

    schedule_teams = {str(row["home_team"]) for row in schedule_rows if row["home_team"]} | {
        str(row["away_team"]) for row in schedule_rows if row["away_team"]
    }
    missing_schedule_teams = sorted(schedule_teams - team_names)
    if missing_schedule_teams:
        errors.append(f"schedule references teams missing from teams payload: {missing_schedule_teams}")

    if squads_path.exists() and not skip_squad_mismatch:
        squads_teams = _read_csv_names(squads_path, "team_name")
        official_only = sorted(team_names - squads_teams)
        squads_only = sorted(squads_teams - team_names)
        if official_only or squads_only:
            errors.append(
                "official team names do not match current squads_2026.csv; "
                f"official_only={official_only}; squads_only={squads_only}"
            )

    if rankings_path.exists() and not skip_ranking_mismatch:
        ranking_teams = _read_csv_names(rankings_path, "team_name")
        missing_rankings = sorted(team_names - ranking_teams)
        if missing_rankings:
            errors.append(f"official teams missing from fifa_rankings.csv: {missing_rankings}")
    return errors


def rebuild_dependent_scaffolds(
    teams_rows: list[dict[str, str | int | float]],
    squads_path: Path,
    aliases: dict[str, str],
) -> tuple[list[dict[str, str | int | float]], list[dict], list[dict], list[dict]]:
    old_by_team = _read_squads_by_team(squads_path, aliases)
    squad_rows: list[dict] = []
    lineup_rows: list[dict] = []
    injury_rows: list[dict] = []
    updated_teams: list[dict[str, str | int | float]] = []
    for team_row in teams_rows:
        team_name = str(team_row["name"])
        members = list(old_by_team.get(team_name, []))
        while len(members) < 11:
            index = len(members) + 1
            members.append(
                {
                    "team_name": team_name,
                    "name": f"{team_name} Player {index:02d}",
                    "attack": "65",
                    "defensive": "65",
                    "injured": "0",
                    "injury_description": "",
                }
            )
        normalized_members = []
        for member in members:
            normalized_members.append(
                {
                    "team_name": team_name,
                    "name": member.get("name", ""),
                    "attack": member.get("attack", "65") or "65",
                    "defensive": member.get("defensive", "65") or "65",
                    "injured": member.get("injured", "0") or "0",
                    "injury_description": member.get("injury_description", ""),
                }
            )
        squad_rows.extend(normalized_members)
        starters = [member["name"] for member in normalized_members[:11]]
        lineup_rows.extend({"team_name": team_name, "player_name": player} for player in starters)
        injury_rows.extend(
            {
                "team_name": team_name,
                "player_name": member["name"],
                "injured": member["injured"],
                "injury_description": member["injury_description"],
            }
            for member in normalized_members
        )
        copied = dict(team_row)
        copied["starting_lineup"] = "|".join(starters)
        updated_teams.append(copied)
    return updated_teams, squad_rows, lineup_rows, injury_rows


def _fetch_football_data(api_key: str, path: str, params: dict[str, int]) -> dict:
    url = f"{FOOTBALL_DATA_BASE_URL}{path}?{urlencode(params)}"
    request = Request(url, headers={"X-Auth-Token": api_key, "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_metadata(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _read_rankings(path: Path, aliases: dict[str, str]) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            canonicalize_team_name(row["team_name"], aliases): int(row["fifa_ranking"])
            for row in csv.DictReader(handle)
            if row.get("fifa_ranking")
        }


def _read_squads_by_team(path: Path, aliases: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    squads: dict[str, list[dict[str, str]]] = {}
    if not path.exists():
        return squads
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            team_name = canonicalize_team_name(row.get("team_name", ""), aliases)
            if team_name:
                copied = {key: (value or "").strip() for key, value in row.items()}
                copied["team_name"] = team_name
                squads.setdefault(team_name, []).append(copied)
    return squads


def _read_csv_names(path: Path, column: str) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row[column] for row in csv.DictReader(handle) if row.get(column)}


def _group_by_team(matches_payload: dict, aliases: dict[str, str]) -> dict[str, str]:
    groups: dict[str, str] = {}
    for match in matches_payload.get("matches", []):
        group = _normalize_group(match.get("group"))
        if not group:
            continue
        for side in ("homeTeam", "awayTeam"):
            name = canonicalize_team_name(_team_name(match.get(side) or {}), aliases)
            if name:
                groups.setdefault(name, group)
    return groups


def _team_name(team: dict) -> str:
    return " ".join(str(team.get("name") or team.get("shortName") or "").split())


def _normalize_group(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("GROUP_", "").replace("Group ", "").strip().upper()


def _stage_number(match: dict) -> int:
    return football_data_stage_to_number(match.get("stage"))


def _stable_match_id(stage: int, home_team: str, away_team: str, api_id: object, seen_ids: set[str]) -> str:
    base = f"s{stage}_{_slug(home_team)}_{_slug(away_team)}"
    match_id = base
    if match_id in seen_ids:
        match_id = f"{base}_{api_id}"
    seen_ids.add(match_id)
    return match_id


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
