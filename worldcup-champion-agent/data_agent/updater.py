from __future__ import annotations

import importlib
from dataclasses import asdict
from types import ModuleType
from typing import Any

from data_agent.normalizer import (
    NormalizedDataset,
    NormalizedInjury,
    NormalizedLineup,
    NormalizedMatch,
    NormalizedMember,
    NormalizedRanking,
    NormalizedTeam,
)


class MissingDataLayerError(RuntimeError):
    """Raised when the documented data layer is not present or lacks write interfaces."""


class DataLayerUpdater:
    """Adapter that writes through data.database instead of reimplementing SQLite writes."""

    def __init__(self, database_module: str = "data.database", models_module: str = "data.models") -> None:
        self.database = self._import_module(database_module)
        self.models = self._import_module(models_module)
        self._validate_core_models()

    def write_dataset(self, dataset: NormalizedDataset) -> list[str]:
        warnings: list[str] = []
        self._write_teams(dataset.teams)
        self._replace_matches(dataset.matches)
        warnings.extend(self._apply_updates(dataset))
        return warnings

    def update_matches(self, matches: list[NormalizedMatch]) -> None:
        scheduled_matches = [match for match in matches if not match.is_real]
        real_matches = [match for match in matches if match.is_real]
        if scheduled_matches:
            self._write_matches(scheduled_matches)
        for match in real_matches:
            self.save_real_score(match)

    def save_real_score(self, match: NormalizedMatch) -> None:
        if not hasattr(self.database, "save_real_score"):
            raise MissingDataLayerError("data.database is missing save_real_score().")
        self.database.save_real_score(match.match_id, match.home_score, match.away_score)

    def update_injuries(self, injuries: list[NormalizedInjury]) -> None:
        if not hasattr(self.database, "update_injury"):
            raise MissingDataLayerError("data.database is missing update_injury().")
        for injury in injuries:
            self.database.update_injury(
                injury.team_name,
                injury.player_name,
                injury.injured,
                injury.injury_description,
            )

    def update_lineups(self, lineups: list[NormalizedLineup]) -> None:
        if not hasattr(self.database, "update_starting_lineup"):
            raise MissingDataLayerError("data.database is missing update_starting_lineup().")
        for lineup in lineups:
            self.database.update_starting_lineup(lineup.team_name, lineup.player_names)

    def update_rankings(self, rankings: list[NormalizedRanking]) -> None:
        if hasattr(self.database, "update_fifa_ranking"):
            for ranking in rankings:
                self.database.update_fifa_ranking(ranking.team_name, ranking.fifa_ranking)
            return
        if hasattr(self.database, "update_team_ranking"):
            for ranking in rankings:
                self.database.update_team_ranking(ranking.team_name, ranking.fifa_ranking)
            return
        raise MissingDataLayerError(
            "data.database is missing update_fifa_ranking() or update_team_ranking(); "
            "ranking updates were not applied."
        )

    def _write_teams(self, teams: list[NormalizedTeam]) -> None:
        team_models = [self._to_team_model(team) for team in teams]
        if hasattr(self.database, "save_teams"):
            self.database.save_teams(team_models)
            return
        if hasattr(self.database, "save_team"):
            for team in team_models:
                self.database.save_team(team)
            return
        raise MissingDataLayerError(
            "data.database is missing save_teams() or save_team(); cannot persist Team/Member data through the data layer."
        )

    def _write_matches(self, matches: list[NormalizedMatch]) -> None:
        match_models = [self._to_match_model(match) for match in matches]
        if hasattr(self.database, "save_matches"):
            self.database.save_matches(match_models)
            return
        if hasattr(self.database, "save_match"):
            for match in match_models:
                self.database.save_match(match)
            return
        raise MissingDataLayerError("data.database is missing save_matches() or save_match().")

    def _replace_matches(self, matches: list[NormalizedMatch]) -> None:
        match_models = [self._to_match_model(match) for match in matches]
        if hasattr(self.database, "replace_matches"):
            self.database.replace_matches(match_models)
            return
        self._write_matches(matches)

    def _apply_updates(self, dataset: NormalizedDataset) -> list[str]:
        warnings: list[str] = []
        if hasattr(self.database, "update_starting_lineup"):
            for team in dataset.teams:
                self.database.update_starting_lineup(team.name, team.starting_lineup)
        else:
            warnings.append("data.database is missing update_starting_lineup(); lineup updates were skipped.")

        if hasattr(self.database, "update_streak"):
            for team in dataset.teams:
                self.database.update_streak(team.name, team.streak)
        else:
            warnings.append("data.database is missing update_streak(); streak updates were skipped.")

        if hasattr(self.database, "update_injury"):
            for member in dataset.members:
                self.database.update_injury(
                    member.team_name,
                    member.name,
                    member.injured,
                    member.injury_description,
                )
        else:
            warnings.append("data.database is missing update_injury(); injury updates were skipped.")
        return warnings

    def _to_team_model(self, team: NormalizedTeam) -> Any:
        member_models = [self._to_member_model(member) for member in team.members]
        payload = asdict(team)
        payload["members"] = member_models
        return _construct_model(
            self.models.Team,
            [
                payload,
                {
                    "name": team.name,
                    "group": team.group,
                    "members": member_models,
                    "attack_team": team.attack_team,
                    "defensive_team": team.defensive_team,
                    "starting_lineup": team.starting_lineup,
                    "streak": team.streak,
                    "fifa_ranking": team.fifa_ranking,
                },
            ],
        )

    def _to_member_model(self, member: NormalizedMember) -> Any:
        return _construct_model(
            self.models.Member,
            [
                {
                    "name": member.name,
                    "team_name": member.team_name,
                    "attack": member.attack,
                    "defensive": member.defensive,
                    "attack_member": member.attack,
                    "defensive_member": member.defensive,
                    "injured": member.injured,
                    "injury_description": member.injury_description,
                },
                {
                    "name": member.name,
                    "attack_member": member.attack,
                    "defensive_member": member.defensive,
                    "injured": member.injured,
                    "injury_description": member.injury_description,
                },
            ],
        )

    def _to_match_model(self, match: NormalizedMatch) -> Any:
        return _construct_model(
            self.models.Match,
            [
                asdict(match),
                {
                    "home_team": match.home_team,
                    "away_team": match.away_team,
                    "home_score": match.home_score,
                    "away_score": match.away_score,
                    "stage": match.stage,
                    "match_id": match.match_id,
                    "status": match.status,
                },
            ],
        )

    def _validate_core_models(self) -> None:
        missing = [name for name in ("Member", "Team", "Match") if not hasattr(self.models, name)]
        if missing:
            raise MissingDataLayerError(f"data.models is missing required model(s): {', '.join(missing)}")

    @staticmethod
    def _import_module(module_name: str) -> ModuleType:
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise MissingDataLayerError(f"Required data layer module not found: {module_name}") from exc


def _construct_model(model_cls: Any, payloads: list[dict[str, Any]]) -> Any:
    last_error: Exception | None = None
    for payload in payloads:
        try:
            return model_cls(**payload)
        except Exception as exc:  # Different model implementations may reject extra fields.
            last_error = exc
    raise MissingDataLayerError(f"Could not construct {model_cls.__name__}: {last_error}") from last_error
