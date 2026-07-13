from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import static World Cup CSV data through data.database.")
    parser.add_argument("--teams", required=True, help="Path to teams CSV.")
    parser.add_argument("--squads", required=True, help="Path to squads CSV.")
    parser.add_argument("--schedule", required=True, help="Path to schedule CSV.")
    parser.add_argument("--rankings", required=True, help="Path to FIFA rankings CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from data_agent.pipeline import StaticWorldCupPipeline
    from data_agent.updater import MissingDataLayerError

    try:
        result = StaticWorldCupPipeline().run(
            teams_path=args.teams,
            squads_path=args.squads,
            schedule_path=args.schedule,
            rankings_path=args.rankings,
        )
    except MissingDataLayerError as exc:
        print(f"data_layer_error={exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"validation_error={exc}", file=sys.stderr)
        return 1
    print(f"teams_count={result.teams_count}")
    print(f"members_count={result.members_count}")
    print(f"matches_count={result.matches_count}")
    for warning in result.warnings:
        print(f"warning={warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
