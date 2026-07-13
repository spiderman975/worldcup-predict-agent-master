from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_agent.team_aliases import canonicalize_team_name, load_team_aliases


OUTPUT_FIELDS = ["team_name", "name", "attack", "defensive", "injured", "injury_description"]
POSITION_DEFAULTS = {
    "GK": (28, 85),
    "DF": (48, 80),
    "MF": (70, 68),
    "FW": (84, 42),
    "UNKNOWN": (65, 65),
}
ALLOWED_SOURCE_NOTES = {
    "official_fifa_squad",
    "team_website",
    "trusted_media",
    "wikipedia_cross_check",
    "manual_curated_candidate",
    "scaffold_fallback",
}
ALLOWED_ABILITY_SOURCES = {
    "rating_source",
    "position_fallback",
    "ranking_position_fallback",
    "neutral_fallback",
    "manual_rule",
}
RATING_MODES = {"position_fallback", "ranking_position_fallback"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build data-layer squads_2026.csv from traceable raw squad input.")
    parser.add_argument("--teams", default="datasets/teams_2026.csv")
    parser.add_argument("--raw-squads", default="datasets/raw/squads_2026_manual.csv")
    parser.add_argument("--output", default="datasets/squads_2026.csv")
    parser.add_argument("--rankings", default=None, help="FIFA rankings CSV used by ranking_position_fallback mode.")
    parser.add_argument("--rating-mode", default="position_fallback", choices=sorted(RATING_MODES))
    parser.add_argument("--aliases", default="datasets/team_aliases.csv")
    parser.add_argument(
        "--allow-scaffold-fill",
        action="store_true",
        help="Fill teams with fewer than 11 raw players using deterministic neutral placeholder players.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_path = Path(args.raw_squads)
    if not raw_path.exists():
        print(f"squad_build_error=raw squad file not found: {raw_path}; output was not modified", file=sys.stderr)
        return 2

    try:
        aliases = load_team_aliases(args.aliases)
        teams = read_team_names(Path(args.teams), aliases)
        rankings = read_rankings(Path(args.rankings), aliases) if args.rankings else {}
        if args.rating_mode == "ranking_position_fallback" and not rankings:
            raise ValueError("--rankings is required when --rating-mode ranking_position_fallback is used")
        raw_rows = read_raw_squads(raw_path, aliases)
        output_rows, source_counts, scaffold_teams = build_squads(
            raw_rows,
            teams,
            allow_scaffold_fill=args.allow_scaffold_fill,
            rankings=rankings,
            rating_mode=args.rating_mode,
        )
        write_csv(Path(args.output), output_rows)
        member_counts = Counter(row["team_name"] for row in output_rows)
        print(f"teams_count={len(teams)}")
        print(f"members_count={len(output_rows)}")
        print(f"min_members_per_team={min(member_counts.values()) if member_counts else 0}")
        print(f"rating_mode={args.rating_mode}")
        print("source_counts=" + ",".join(f"{key}:{source_counts[key]}" for key in sorted(source_counts)))
        print(
            "position_counts="
            + ",".join(f"{key}:{value}" for key, value in sorted(Counter(row["position"] for row in raw_rows).items()))
        )
        print("scaffold_fallback_teams=" + ",".join(scaffold_teams))
    except ValueError as exc:
        print(f"squad_build_error={exc}", file=sys.stderr)
        return 1
    return 0


def read_team_names(path: Path, aliases: dict[str, str]) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {canonicalize_team_name(row["name"], aliases) for row in csv.DictReader(handle) if row.get("name")}


def read_rankings(path: Path, aliases: dict[str, str]) -> dict[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            canonicalize_team_name(row["team_name"], aliases): int(row["fifa_ranking"])
            for row in csv.DictReader(handle)
            if row.get("team_name") and row.get("fifa_ranking")
        }


def read_raw_squads(path: Path, aliases: dict[str, str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    required = {"team_name", "player_name", "position"}
    missing = sorted(required - set(rows[0].keys())) if rows else []
    if missing:
        raise ValueError(f"raw squad file is missing required columns: {missing}")
    for row in rows:
        row["team_name"] = canonicalize_team_name(row.get("team_name", ""), aliases)
        row["position"] = normalize_position(row.get("position", ""))
        validate_source_fields(row)
    return rows


def build_squads(
    raw_rows: list[dict[str, str]],
    teams: set[str],
    allow_scaffold_fill: bool,
    rankings: dict[str, int],
    rating_mode: str,
) -> tuple[list[dict[str, str]], Counter[str], list[str]]:
    rows_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    seen_players: set[tuple[str, str]] = set()
    errors: list[str] = []

    for row in raw_rows:
        team_name = row.get("team_name", "")
        player_name = row.get("player_name", "")
        if team_name not in teams:
            errors.append(f"unknown team_name={team_name} player={player_name}")
            continue
        if not player_name:
            errors.append(f"missing player_name for team={team_name}")
            continue
        key = (team_name, player_name)
        if key in seen_players:
            errors.append(f"duplicate player={team_name} / {player_name}")
            continue
        seen_players.add(key)
        rows_by_team[team_name].append(row)
        source_counts[row.get("source_note") or "unspecified"] += 1

    missing_teams = sorted(teams - set(rows_by_team))
    if missing_teams and not allow_scaffold_fill:
        errors.append(f"teams missing raw squad rows: {missing_teams}")

    too_short = sorted(team for team in teams if 0 < len(rows_by_team.get(team, [])) < 11)
    if too_short and not allow_scaffold_fill:
        errors.append(f"teams with fewer than 11 raw players: {too_short}")

    if errors:
        raise ValueError("; ".join(errors))

    if rating_mode == "ranking_position_fallback":
        missing_rankings = sorted(team for team in teams if team not in rankings)
        if missing_rankings:
            raise ValueError(f"rankings missing teams required by ranking_position_fallback: {missing_rankings}")

    output_rows: list[dict[str, str]] = []
    scaffold_teams: list[str] = []
    for team_name in sorted(teams):
        team_rows = rows_by_team.get(team_name, [])
        while len(team_rows) < 11 and allow_scaffold_fill:
            scaffold_teams.append(team_name)
            index = len(team_rows) + 1
            team_rows.append(
                {
                    "team_name": team_name,
                    "player_name": f"{team_name} Player {index:02d}",
                    "position": "UNKNOWN",
                    "source_note": "scaffold_fallback",
                    "attack_source": "neutral_fallback",
                    "defensive_source": "neutral_fallback",
                    "attack_raw": "",
                    "defensive_raw": "",
                    "injured": "0",
                    "injury_description": "",
                }
            )
            source_counts["scaffold_fallback"] += 1
        for row in team_rows:
            attack, defensive = map_abilities(row, rankings.get(team_name), rating_mode)
            injured = normalize_injured(row.get("injured", ""))
            output_rows.append(
                {
                    "team_name": team_name,
                    "name": row["player_name"],
                    "attack": format_number(attack),
                    "defensive": format_number(defensive),
                    "injured": str(injured),
                    "injury_description": row.get("injury_description", ""),
                }
            )

    scaffold_teams.extend(
        team
        for team, team_rows in rows_by_team.items()
        if team_rows and all(row.get("source_note") == "scaffold_fallback" for row in team_rows)
    )
    return output_rows, source_counts, sorted(set(scaffold_teams))


def map_abilities(row: dict[str, str], fifa_ranking: int | None, rating_mode: str) -> tuple[float, float]:
    position_attack, position_defensive = POSITION_DEFAULTS[row.get("position") or "UNKNOWN"]
    modifier = ranking_modifier(fifa_ranking) if rating_mode == "ranking_position_fallback" else 0
    attack = parse_number(row.get("attack_raw")) if row.get("attack_raw") else position_attack + modifier
    defensive = parse_number(row.get("defensive_raw")) if row.get("defensive_raw") else position_defensive + modifier
    return clamp(attack), clamp(defensive)


def ranking_modifier(fifa_ranking: int | None) -> int:
    if fifa_ranking is None:
        return 0
    if 1 <= fifa_ranking <= 10:
        return 8
    if 11 <= fifa_ranking <= 20:
        return 5
    if 21 <= fifa_ranking <= 30:
        return 3
    if 31 <= fifa_ranking <= 50:
        return 0
    if 51 <= fifa_ranking <= 75:
        return -3
    return -6


def normalize_position(value: str) -> str:
    position = (value or "UNKNOWN").strip().upper()
    return position if position in POSITION_DEFAULTS else "UNKNOWN"


def validate_source_fields(row: dict[str, str]) -> None:
    source_note = row.get("source_note") or ""
    attack_source = row.get("attack_source") or ""
    defensive_source = row.get("defensive_source") or ""
    if source_note not in ALLOWED_SOURCE_NOTES:
        raise ValueError(f"source_note must be one of {sorted(ALLOWED_SOURCE_NOTES)}, got {source_note}")
    if attack_source not in ALLOWED_ABILITY_SOURCES:
        raise ValueError(f"attack_source must be one of {sorted(ALLOWED_ABILITY_SOURCES)}, got {attack_source}")
    if defensive_source not in ALLOWED_ABILITY_SOURCES:
        raise ValueError(f"defensive_source must be one of {sorted(ALLOWED_ABILITY_SOURCES)}, got {defensive_source}")


def normalize_injured(value: str) -> int:
    if value == "":
        return 0
    if value not in {"0", "1"}:
        raise ValueError(f"injured must be 0 or 1, got {value}")
    return int(value)


def parse_number(value: str | None) -> float:
    try:
        return float(value or "")
    except ValueError as exc:
        raise ValueError(f"ability value must be numeric, got {value}") from exc


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def looks_like_scaffold_player(team_name: str, player_name: str) -> bool:
    escaped = re.escape(team_name)
    return bool(
        re.fullmatch(rf"{escaped} Player \d{{2}}", player_name)
        or re.fullmatch(rf"{escaped} (GK|DF\d+|MF\d+|FW\d+)", player_name)
    )


if __name__ == "__main__":
    raise SystemExit(main())
