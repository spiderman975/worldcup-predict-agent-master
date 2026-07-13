from __future__ import annotations

from pathlib import Path

from data_agent.normalizer import NormalizedInjury
from data_agent.sources.csv_source import load_csv_rows


def load_injury_rows(path: str | Path) -> list[dict[str, str]]:
    return load_csv_rows(
        path,
        required_fields=["team_name", "player_name", "injured", "injury_description"],
    )


def load_injuries_from_csv(path: str | Path) -> list[NormalizedInjury]:
    injuries: list[NormalizedInjury] = []
    for row in load_injury_rows(path):
        injured = int(row["injured"])
        if injured not in {0, 1}:
            raise ValueError(f"injured must be 0 or 1 for {row['team_name']} / {row['player_name']}")
        injuries.append(
            NormalizedInjury(
                team_name=row["team_name"],
                player_name=row["player_name"],
                injured=injured,
                injury_description=row.get("injury_description", ""),
            )
        )
    return injuries

