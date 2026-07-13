from __future__ import annotations

from pathlib import Path

from data_agent.normalizer import NormalizedLineup
from data_agent.sources.csv_source import load_csv_rows


def load_lineup_rows(path: str | Path) -> list[dict[str, str]]:
    return load_csv_rows(path, required_fields=["team_name", "player_name"])


def load_lineups_from_csv(path: str | Path) -> list[NormalizedLineup]:
    grouped: dict[str, list[str]] = {}
    for row in load_lineup_rows(path):
        team_name = row["team_name"]
        player_name = row["player_name"]
        if not team_name or not player_name:
            continue
        grouped.setdefault(team_name, []).append(player_name)
    return [NormalizedLineup(team_name=team_name, player_names=players) for team_name, players in grouped.items()]
