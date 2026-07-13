from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_agent.team_aliases import canonicalize_team_name, load_team_aliases


@dataclass(frozen=True)
class TeamStrength:
    team_name: str
    fifa_ranking: int | None
    avg_attack: float
    avg_defensive: float
    starting_attack: float | None
    starting_defensive: float | None
    member_count: int

    @property
    def overall(self) -> float:
        return (self.avg_attack + self.avg_defensive) / 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze squad attack/defensive strength from CSV files.")
    parser.add_argument("--teams", default="datasets/teams_2026.csv")
    parser.add_argument("--squads", default="datasets/squads_2026.csv")
    parser.add_argument("--rankings", default="datasets/fifa_rankings.csv")
    parser.add_argument("--aliases", default="datasets/team_aliases.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    aliases = load_team_aliases(args.aliases)
    teams = read_csv(Path(args.teams))
    squads = read_csv(Path(args.squads))
    ranking_by_team = read_rankings(Path(args.rankings), aliases)
    strengths = analyze_strengths(teams, squads, ranking_by_team, aliases)

    print(f"teams_count={len(strengths)}")
    print("top_10_avg_attack")
    print_rows(sorted(strengths, key=lambda row: (-row.avg_attack, row.team_name))[:10])
    print("top_10_avg_defensive")
    print_rows(sorted(strengths, key=lambda row: (-row.avg_defensive, row.team_name))[:10])
    print("bottom_10_overall")
    print_rows(sorted(strengths, key=lambda row: (row.overall, row.team_name))[:10])

    attack_values = {round(row.avg_attack, 6) for row in strengths}
    defensive_values = {round(row.avg_defensive, 6) for row in strengths}
    overall_values = {round(row.overall, 6) for row in strengths}
    if len(attack_values) == 1 and len(defensive_values) == 1 and len(overall_values) == 1:
        print("warning=all team squad averages are identical")
    else:
        print("warning=none")
    return 0


def analyze_strengths(
    teams: list[dict[str, str]],
    squads: list[dict[str, str]],
    ranking_by_team: dict[str, int],
    aliases: dict[str, str],
) -> list[TeamStrength]:
    members_by_team: dict[str, list[dict[str, str]]] = {}
    for row in squads:
        team_name = canonicalize_team_name(row["team_name"], aliases)
        members_by_team.setdefault(team_name, []).append(row)

    strengths: list[TeamStrength] = []
    for team in teams:
        team_name = canonicalize_team_name(team["name"], aliases)
        members = members_by_team.get(team_name, [])
        avg_attack = average(float(member["attack"]) for member in members)
        avg_defensive = average(float(member["defensive"]) for member in members)
        starters = set(parse_name_list(team.get("starting_lineup", "")))
        starting_members = [member for member in members if member["name"] in starters]
        starting_attack = average(float(member["attack"]) for member in starting_members) if starting_members else None
        starting_defensive = average(float(member["defensive"]) for member in starting_members) if starting_members else None
        strengths.append(
            TeamStrength(
                team_name=team_name,
                fifa_ranking=ranking_by_team.get(team_name),
                avg_attack=avg_attack,
                avg_defensive=avg_defensive,
                starting_attack=starting_attack,
                starting_defensive=starting_defensive,
                member_count=len(members),
            )
        )
    return strengths


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def read_rankings(path: Path, aliases: dict[str, str]) -> dict[str, int]:
    return {
        canonicalize_team_name(row["team_name"], aliases): int(row["fifa_ranking"])
        for row in read_csv(path)
        if row.get("team_name") and row.get("fifa_ranking")
    }


def parse_name_list(value: str) -> list[str]:
    text = " ".join(str(value or "").split())
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        return [str(item).strip() for item in parsed if str(item).strip()]
    separator = "|" if "|" in text else ";"
    return [item.strip() for item in text.split(separator) if item.strip()]


def average(values: object) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def print_rows(rows: list[TeamStrength]) -> None:
    for row in rows:
        starting_attack = format_optional(row.starting_attack)
        starting_defensive = format_optional(row.starting_defensive)
        print(
            f"{row.team_name},"
            f"fifa_ranking={row.fifa_ranking},"
            f"avg_attack={row.avg_attack:.2f},"
            f"avg_defensive={row.avg_defensive:.2f},"
            f"starting_attack={starting_attack},"
            f"starting_defensive={starting_defensive},"
            f"member_count={row.member_count}"
        )


def format_optional(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    raise SystemExit(main())
