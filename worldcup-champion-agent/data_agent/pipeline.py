from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_agent.normalizer import NormalizedDataset, normalize_static_dataset
from data_agent.sources.csv_source import load_team_rows
from data_agent.sources.ranking_source import load_ranking_rows
from data_agent.sources.roster_source import load_roster_rows
from data_agent.sources.schedule_source import load_schedule_rows
from data_agent.updater import DataLayerUpdater
from data_agent.validators import validate_dataset


@dataclass(frozen=True)
class StaticIngestionResult:
    teams_count: int
    members_count: int
    matches_count: int
    warnings: list[str]


def load_static_dataset(
    teams_path: str | Path,
    squads_path: str | Path,
    schedule_path: str | Path,
    rankings_path: str | Path,
) -> NormalizedDataset:
    return normalize_static_dataset(
        team_rows=load_team_rows(teams_path),
        roster_rows=load_roster_rows(squads_path),
        schedule_rows=load_schedule_rows(schedule_path),
        ranking_rows=load_ranking_rows(rankings_path),
    )


class StaticWorldCupPipeline:
    def __init__(self, updater: DataLayerUpdater | None = None) -> None:
        self.updater = updater

    def run(
        self,
        teams_path: str | Path,
        squads_path: str | Path,
        schedule_path: str | Path,
        rankings_path: str | Path,
    ) -> StaticIngestionResult:
        dataset = load_static_dataset(teams_path, squads_path, schedule_path, rankings_path)
        report = validate_dataset(dataset)
        if not report.is_valid:
            raise ValueError("Static ingestion validation failed:\n" + "\n".join(report.errors))
        updater = self.updater or DataLayerUpdater()
        update_warnings = updater.write_dataset(dataset)
        return StaticIngestionResult(
            teams_count=len(dataset.teams),
            members_count=len(dataset.members),
            matches_count=len(dataset.matches),
            warnings=[*report.warnings, *update_warnings],
        )
