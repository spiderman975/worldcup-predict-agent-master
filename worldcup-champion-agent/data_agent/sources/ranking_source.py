from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from data_agent.normalizer import NormalizedRanking
from data_agent.sources.csv_source import load_csv_rows


def load_ranking_rows(path: str | Path) -> list[dict[str, str]]:
    return load_csv_rows(path, required_fields=["team_name", "fifa_ranking"])


def load_ranking_map(path: str | Path) -> dict[str, int]:
    rankings: dict[str, int] = {}
    for row in load_ranking_rows(path):
        team_name = row["team_name"]
        if not team_name:
            continue
        rankings[team_name] = int(row["fifa_ranking"])
    return rankings


def load_rankings_from_csv(path: str | Path) -> list[NormalizedRanking]:
    return [
        NormalizedRanking(team_name=row["team_name"], fifa_ranking=int(row["fifa_ranking"]))
        for row in load_ranking_rows(path)
        if row["team_name"]
    ]


def load_rankings_from_api(url: str | None = None, api_key: str | None = None) -> list[NormalizedRanking]:
    """Load rankings from a JSON endpoint.

    The endpoint may return a list directly or an object with a `rankings` list.
    Each row should contain `team_name`/`name` and `fifa_ranking`/`rank`.
    """

    import httpx
    from dotenv import load_dotenv

    load_dotenv()
    ranking_url = url or os.getenv("FIFA_RANKING_URL")
    if not ranking_url:
        raise ValueError("FIFA_RANKING_URL is required for API ranking updates")
    token = api_key or os.getenv("FIFA_RANKING_API_KEY")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30.0, headers=headers) as client:
        response = client.get(ranking_url)
    response.raise_for_status()
    return normalize_ranking_payload(response.json())


def normalize_ranking_payload(payload: Any) -> list[NormalizedRanking]:
    rows = payload.get("rankings", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Ranking payload must be a list or an object with a rankings list")
    rankings: list[NormalizedRanking] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        team_name = row.get("team_name") or row.get("name") or row.get("team")
        ranking = row.get("fifa_ranking") or row.get("rank") or row.get("ranking")
        if team_name and ranking:
            rankings.append(NormalizedRanking(team_name=str(team_name), fifa_ranking=int(ranking)))
    return rankings
