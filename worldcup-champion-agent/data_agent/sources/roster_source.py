from __future__ import annotations

from pathlib import Path

from data_agent.sources.csv_source import load_csv_rows


def load_roster_rows(path: str | Path) -> list[dict[str, str]]:
    return load_csv_rows(
        path,
        required_fields=[
            "name",
            "team_name",
            "attack",
            "defensive",
            "injured",
            "injury_description",
        ],
    )

