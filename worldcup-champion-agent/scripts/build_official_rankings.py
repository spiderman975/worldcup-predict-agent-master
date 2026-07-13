from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_agent.team_aliases import canonicalize_team_name, load_team_aliases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FIFA rankings CSV from a traceable official raw file.")
    parser.add_argument("--raw-csv", default=None, help="Downloaded FIFA ranking CSV with team/rank columns.")
    parser.add_argument("--raw-html", default=None, help="Downloaded FIFA ranking HTML page.")
    parser.add_argument("--url", default=None, help="Official ranking page URL to download and preserve as raw HTML.")
    parser.add_argument("--raw-dir", default="datasets/raw")
    parser.add_argument("--output", default="datasets/fifa_rankings.csv")
    parser.add_argument("--teams", default="datasets/teams_2026.csv", help="Teams CSV used for canonical filtering.")
    parser.add_argument("--aliases", default="datasets/team_aliases.csv", help="CSV mapping source team names to canonical names.")
    parser.add_argument("--ranking-date", default="2026-04-01")
    parser.add_argument("--write", action="store_true", help="Write normalized rankings CSV. Retained for compatibility; write is now the default.")
    parser.add_argument("--no-write", action="store_true", help="Validate and print counts without writing the output CSV.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    aliases = load_team_aliases(args.aliases)
    try:
        if args.raw_csv:
            raw_path = Path(args.raw_csv)
            rows = normalize_ranking_csv(raw_path)
        elif args.raw_html:
            raw_path = Path(args.raw_html)
            rows = normalize_ranking_html(raw_path.read_text(encoding="utf-8", errors="ignore"))
        elif args.url:
            raw_path = raw_dir / "fifa_rankings_2026_raw.html"
            html = _download_text(args.url)
            raw_path.write_text(html, encoding="utf-8")
            rows = normalize_ranking_html(html)
        else:
            raw_path = find_default_ranking_raw(raw_dir, args.ranking_date)
            if raw_path is None:
                print(
                    "missing_input=provide --raw-csv, --raw-html, or --url; "
                    "expected datasets/raw/fifa_rankings_2026_20260401_raw.csv, "
                    "fifa_rankings_2026_20260401_full.html, or fifa_rankings_2026_20260401.html",
                    file=sys.stderr,
                )
                return 2
            rows = (
                normalize_ranking_csv(raw_path)
                if raw_path.suffix.lower() == ".csv"
                else normalize_ranking_html(raw_path.read_text(encoding="utf-8", errors="ignore"))
            )

        rows = filter_rankings_for_teams(rows, Path(args.teams), args.ranking_date, aliases)
        print(f"rankings_count={len(rows)}")
        print(f"raw_rankings={raw_path}")
        if not args.no_write:
            _write_csv(Path(args.output), rows)
    except (FileNotFoundError, HTTPError, URLError, ValueError) as exc:
        print(f"ranking_build_error={exc}", file=sys.stderr)
        return 1
    return 0


def normalize_ranking_csv(path: Path) -> list[dict[str, str | int]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    normalized: list[dict[str, str | int]] = []
    for row in rows:
        lowered = {key.lower().strip(): value for key, value in row.items() if key}
        team = lowered.get("team_name") or lowered.get("team") or lowered.get("country") or lowered.get("name")
        ranking = lowered.get("fifa_ranking") or lowered.get("rank") or lowered.get("ranking") or lowered.get("position")
        if team and ranking:
            normalized.append({"team_name": team.strip(), "fifa_ranking": int(str(ranking).strip())})
    if not normalized:
        raise ValueError("No rankings could be parsed from raw CSV")
    return normalized


def find_default_ranking_raw(raw_dir: Path, ranking_date: str) -> Path | None:
    compact_date = ranking_date.replace("-", "")
    preferred = [
        raw_dir / f"fifa_rankings_2026_{compact_date}_raw.csv",
        raw_dir / f"fifa_rankings_2026_{compact_date}_full.html",
        raw_dir / f"fifa_rankings_2026_{compact_date}.html",
    ]
    for path in preferred:
        if path.exists():
            return path
    matches = sorted(raw_dir.glob(f"*fifa_rankings*{compact_date}*"))
    return matches[0] if matches else None


def normalize_ranking_html(html: str) -> list[dict[str, str | int]]:
    rows = _normalize_ranking_html_with_pandas(html)
    if rows:
        return rows
    rows = _normalize_ranking_html_tables(html)
    if rows:
        return rows
    rows = _normalize_ranking_embedded_json(html)
    if rows:
        return rows
    raise ValueError(
        "No rankings could be parsed from raw HTML. Try saving the full official table as CSV and pass --raw-csv."
    )


def filter_rankings_for_teams(
    rows: list[dict[str, str | int]],
    teams_path: Path,
    ranking_date: str,
    aliases: dict[str, str],
) -> list[dict[str, str | int]]:
    teams = _read_team_names(teams_path)
    ranking_by_team = {
        canonicalize_team_name(str(row["team_name"]), aliases): int(row["fifa_ranking"])
        for row in rows
        if row.get("team_name")
    }
    missing = sorted(team for team in teams if canonicalize_team_name(team, aliases) not in ranking_by_team)
    if len(ranking_by_team) < len(teams):
        raise ValueError(
            f"FIFA ranking raw file parsed only {len(ranking_by_team)} unique teams; "
            f"need at least {len(teams)} for the official World Cup team universe; missing={missing}"
        )
    if missing:
        raise ValueError(f"FIFA ranking raw file is missing project teams: {missing}")
    return [
        {
            "team_name": team,
            "fifa_ranking": ranking_by_team[canonicalize_team_name(team, aliases)],
            "ranking_date": ranking_date,
        }
        for team in sorted(teams)
    ]


def _normalize_ranking_html_with_pandas(html: str) -> list[dict[str, str | int]]:
    try:
        import pandas as pd
    except ImportError:
        return []
    try:
        tables = pd.read_html(html)
    except ValueError:
        return []
    rows: list[dict[str, str | int]] = []
    for table in tables:
        columns = {str(column).lower(): column for column in table.columns}
        rank_column = columns.get("rank") or columns.get("ranking") or columns.get("position")
        team_column = columns.get("team") or columns.get("team_name") or columns.get("country")
        if rank_column is None or team_column is None:
            continue
        for _, row in table.iterrows():
            try:
                rank = int(str(row[rank_column]).strip())
            except ValueError:
                continue
            team = str(row[team_column]).strip()
            if team:
                rows.append({"team_name": team, "fifa_ranking": rank})
    if rows:
        ranks = sorted({int(row["fifa_ranking"]) for row in rows})
        if not ranks or ranks[0] != 1:
            return []
    return rows


def _normalize_ranking_html_tables(html: str) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        rank_match = re.search(r"custom-rank-cell_rankNumber[^>]*>\s*(\d+)\s*</h3>", row_html, flags=re.S | re.I)
        team_match = re.search(r"custom-team-cell_teamName[^>]*>\s*(.*?)\s*</a>", row_html, flags=re.S | re.I)
        if not rank_match or not team_match:
            continue
        team_name = re.sub(r"<.*?>", "", team_match.group(1)).strip()
        rows.append({"team_name": team_name, "fifa_ranking": int(rank_match.group(1))})
    return rows


def _normalize_ranking_embedded_json(html: str) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    next_data_match = re.search(r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>", html, flags=re.S | re.I)
    if next_data_match:
        try:
            parsed = json.loads(next_data_match.group(1))
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            rows.extend(_extract_ranking_rows_from_json(parsed))
    for script_match in re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I):
        for item in re.findall(r"\{[^{}]*(?:team_name|fifa_ranking|ranking|rank|country|name)[^{}]*\}", script_match):
            try:
                parsed = json.loads(item)
            except json.JSONDecodeError:
                continue
            team = parsed.get("team_name") or parsed.get("team") or parsed.get("country") or parsed.get("name")
            ranking = parsed.get("fifa_ranking") or parsed.get("ranking") or parsed.get("rank") or parsed.get("position")
            if team and ranking:
                try:
                    rows.append({"team_name": str(team), "fifa_ranking": int(ranking)})
                except ValueError:
                    continue
    return rows


def _extract_ranking_rows_from_json(value: object) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            lowered = {str(key).lower(): key for key in node}
            team_key = (
                lowered.get("team_name")
                or lowered.get("teamname")
                or lowered.get("countryname")
                or lowered.get("country")
                or lowered.get("name")
            )
            rank_key = (
                lowered.get("fifa_ranking")
                or lowered.get("ranking")
                or lowered.get("rank")
                or lowered.get("ranknumber")
                or lowered.get("position")
            )
            if team_key and rank_key:
                team = str(node.get(team_key) or "").strip()
                try:
                    rank = int(str(node.get(rank_key)).strip())
                except ValueError:
                    rank = 0
                if team and rank:
                    rows.append({"team_name": team, "fifa_ranking": rank})
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return rows


def _legacy_normalize_ranking_html(html: str) -> list[dict[str, str | int]]:
    parser = _TableTextParser()
    parser.feed(html)
    text = " ".join(parser.text_parts)
    pairs = re.findall(r"\\b(\\d{1,3})\\s+([A-Z][A-Za-z .'-]{2,40}?)(?=\\s+\\d{1,4}(?:\\.\\d+)?\\b)", text)
    rows = [{"team_name": team.strip(), "fifa_ranking": int(rank)} for rank, team in pairs]
    if not rows:
        raise ValueError("No rankings could be parsed from raw HTML; use --raw-csv if the official page is dynamic")
    return rows


def _download_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "worldcup-data-seed/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def _write_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["team_name", "fifa_ranking", "ranking_date"])
        writer.writeheader()
        writer.writerows(rows)


def _read_team_names(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["name"] for row in csv.DictReader(handle) if row.get("name")}


def _canonical_name(value: str) -> str:
    aliases = {
        "usa": "united states",
        "united states of america": "united states",
        "ir iran": "iran",
        "korea republic": "south korea",
        "cote d'ivoire": "ivory coast",
        "côte d’ivoire": "ivory coast",
        "cape verde islands": "cabo verde",
    }
    cleaned = " ".join(value.lower().replace("’", "'").split())
    return aliases.get(cleaned, cleaned)


class _TableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.text_parts.append(cleaned)


if __name__ == "__main__":
    raise SystemExit(main())
