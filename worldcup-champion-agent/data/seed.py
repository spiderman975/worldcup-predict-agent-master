from __future__ import annotations

import argparse
from pathlib import Path

from data.database import DB_PATH, init_db
from data_agent.pipeline import StaticWorldCupPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEAMS = PROJECT_ROOT / "datasets" / "teams_2026.csv"
DEFAULT_SQUADS = PROJECT_ROOT / "datasets" / "squads_2026.csv"
DEFAULT_SCHEDULE = PROJECT_ROOT / "datasets" / "schedule_2026.csv"
DEFAULT_RANKINGS = PROJECT_ROOT / "datasets" / "fifa_rankings.csv"


def seed_example_data(
    teams_path: str | Path = DEFAULT_TEAMS,
    squads_path: str | Path = DEFAULT_SQUADS,
    schedule_path: str | Path = DEFAULT_SCHEDULE,
    rankings_path: str | Path = DEFAULT_RANKINGS,
    reset: bool = False,
) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    StaticWorldCupPipeline().run(
        teams_path=teams_path,
        squads_path=squads_path,
        schedule_path=schedule_path,
        rankings_path=rankings_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize data/worldcup.db from example CSV files.")
    parser.add_argument("--teams", default=str(DEFAULT_TEAMS), help="Path to teams CSV.")
    parser.add_argument("--squads", default=str(DEFAULT_SQUADS), help="Path to squads CSV.")
    parser.add_argument("--schedule", default=str(DEFAULT_SCHEDULE), help="Path to schedule CSV.")
    parser.add_argument("--rankings", default=str(DEFAULT_RANKINGS), help="Path to FIFA rankings CSV.")
    parser.add_argument("--reset", action="store_true", help="Delete data/worldcup.db before seeding.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed_example_data(
        teams_path=args.teams,
        squads_path=args.squads,
        schedule_path=args.schedule,
        rankings_path=args.rankings,
        reset=args.reset,
    )
    print(f"seeded_db={DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
