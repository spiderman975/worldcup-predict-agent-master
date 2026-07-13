from __future__ import annotations

from pathlib import Path

from data_agent.sources.csv_source import load_csv_rows


def load_schedule_rows(path: str | Path) -> list[dict[str, str]]:
    return load_csv_rows(
        path,
        required_fields=[
            "match_id",
            "stage",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "is_real",
            "played_at",
        ],
    )

