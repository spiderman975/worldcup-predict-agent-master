from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update live World Cup data through data.database.")
    parser.add_argument("--scores", action="store_true", help="Update schedule and real scores from football-data.org.")
    parser.add_argument("--injuries", action="store_true", help="Update injuries from CSV.")
    parser.add_argument("--lineups", action="store_true", help="Update starting lineups from CSV.")
    parser.add_argument("--rankings", action="store_true", help="Update FIFA rankings from CSV or JSON API.")
    parser.add_argument("--year", type=int, default=2026, help="World Cup season year for football-data.org.")
    parser.add_argument("--injuries-csv", default="datasets/injuries_2026.csv", help="Path to injuries CSV.")
    parser.add_argument("--lineups-csv", default="datasets/lineups_2026.csv", help="Path to lineups CSV.")
    parser.add_argument("--rankings-csv", default="datasets/fifa_rankings.csv", help="Path to rankings CSV.")
    parser.add_argument("--rankings-api", action="store_true", help="Load rankings from FIFA_RANKING_URL instead of CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not any([args.scores, args.injuries, args.lineups, args.rankings]):
        print("No update selected. Use --scores, --injuries, --lineups, or --rankings.", file=sys.stderr)
        return 1

    from data_agent.updater import DataLayerUpdater, MissingDataLayerError

    try:
        updater = DataLayerUpdater()
        if args.scores:
            from data_agent.sources.football_data_source import FootballDataSource

            matches = FootballDataSource().load_matches(args.year)
            updater.update_matches(matches)
            print(f"scores_matches_seen={len(matches)}")
        if args.injuries:
            from data_agent.sources.injury_source import load_injuries_from_csv

            injuries = load_injuries_from_csv(args.injuries_csv)
            updater.update_injuries(injuries)
            print(f"injuries_updated={len(injuries)}")
        if args.lineups:
            from data_agent.sources.lineup_source import load_lineups_from_csv

            lineups = load_lineups_from_csv(args.lineups_csv)
            updater.update_lineups(lineups)
            print(f"lineups_updated={len(lineups)}")
        if args.rankings:
            from data_agent.sources.ranking_source import load_rankings_from_api, load_rankings_from_csv

            rankings = load_rankings_from_api() if args.rankings_api else load_rankings_from_csv(args.rankings_csv)
            updater.update_rankings(rankings)
            print(f"rankings_updated={len(rankings)}")
    except MissingDataLayerError as exc:
        print(f"data_layer_error={exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"live_update_error={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
