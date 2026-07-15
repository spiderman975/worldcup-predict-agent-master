from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv

from data_agent.normalizer import NormalizedMatch
from data.stages import football_data_stage_to_number


FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"
WORLD_CUP_COMPETITION_CODE = "WC"
STATUS_FINISHED = {"FINISHED", "AWARDED"}
STATUS_SCHEDULED = {"SCHEDULED", "TIMED", "POSTPONED", "SUSPENDED", "CANCELED", "CANCELLED"}


class FootballDataSource:
    """football-data.org adapter for World Cup schedule and real scores."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout_seconds: float = 30.0) -> None:
        load_dotenv()
        self.api_key = api_key or os.getenv("FOOTBALL_DATA_API_KEY")
        self.base_url = (base_url or os.getenv("FOOTBALL_DATA_BASE_URL") or FOOTBALL_DATA_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("FOOTBALL_DATA_API_KEY is required for football-data.org live updates")

    def load_matches(self, year: int) -> list[NormalizedMatch]:
        payload = self._get(f"/competitions/{WORLD_CUP_COMPETITION_CODE}/matches", {"season": year})
        return normalize_football_data_matches(payload)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-Auth-Token": self.api_key, "Accept": "application/json"}
        with httpx.Client(timeout=self.timeout_seconds, headers=headers) as client:
            response = client.get(f"{self.base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()


def normalize_football_data_matches(payload: dict[str, Any]) -> list[NormalizedMatch]:
    matches: list[NormalizedMatch] = []
    for item in payload.get("matches", []):
        status = str(item.get("status") or "").upper()
        score = item.get("score") or {}
        full_time = score.get("fullTime") or {}
        is_finished = status in STATUS_FINISHED
        home_score = _safe_int(full_time.get("home"))
        away_score = _safe_int(full_time.get("away"))
        if not is_finished or home_score is None or away_score is None:
            home_score = -1
            away_score = -1
            is_real = False
        else:
            is_real = True
        matches.append(
            NormalizedMatch(
                match_id=str(item.get("id") or ""),
                stage=_stage_number(item),
                home_team=_team_name(item.get("homeTeam") or {}),
                away_team=_team_name(item.get("awayTeam") or {}),
                home_score=home_score,
                away_score=away_score,
                is_real=is_real,
                played_at=item.get("utcDate"),
                status=status,
            )
        )
    return matches


def _team_name(team: dict[str, Any]) -> str:
    return " ".join(str(team.get("name") or team.get("shortName") or "").split())


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stage_number(item: dict[str, Any]) -> int:
    return football_data_stage_to_number(item.get("stage"))

