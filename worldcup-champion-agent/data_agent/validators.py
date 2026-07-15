from __future__ import annotations

from dataclasses import dataclass

from data_agent.normalizer import NormalizedDataset
from data.stages import STAGE_NUMBER_TO_KEY


@dataclass(frozen=True)
class ValidationReport:
    errors: list[str]
    warnings: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_dataset(dataset: NormalizedDataset) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    team_names = {team.name for team in dataset.teams}
    if len(team_names) != len(dataset.teams):
        errors.append("Duplicate team name found in teams CSV")

    members_by_team: dict[str, set[str]] = {team.name: set() for team in dataset.teams}
    for member in dataset.members:
        if member.team_name not in team_names:
            errors.append(f"Member {member.name} references unknown team_name: {member.team_name}")
            continue
        members_by_team.setdefault(member.team_name, set()).add(member.name)
        if not 0 <= member.attack <= 100:
            errors.append(f"Member {member.name} attack must be in 0~100")
        if not 0 <= member.defensive <= 100:
            errors.append(f"Member {member.name} defensive must be in 0~100")
        if member.injured not in {0, 1}:
            errors.append(f"Member {member.name} injured must be 0 or 1")

    for team in dataset.teams:
        if not team.members:
            warnings.append(f"Team {team.name} has no squad members")
        for player_name in team.starting_lineup:
            if player_name not in members_by_team.get(team.name, set()):
                errors.append(f"Starting lineup player {player_name} does not exist in team {team.name}")

    seen_match_ids: set[str] = set()
    for match in dataset.matches:
        if match.match_id in seen_match_ids:
            errors.append(f"Duplicate match_id found: {match.match_id}")
        seen_match_ids.add(match.match_id)
        if match.stage not in STAGE_NUMBER_TO_KEY:
            errors.append(f"Match {match.match_id} stage must be one of {sorted(STAGE_NUMBER_TO_KEY)}")
        if match.home_team not in team_names:
            errors.append(f"Match {match.match_id} home_team is unknown: {match.home_team}")
        if match.away_team not in team_names:
            errors.append(f"Match {match.match_id} away_team is unknown: {match.away_team}")
        if (match.home_score == -1) != (match.away_score == -1):
            errors.append(f"Match {match.match_id} must use -1/-1 for unplayed score")
        if match.home_score == -1 and match.away_score == -1 and match.is_real:
            errors.append(f"Match {match.match_id} cannot be real when score is -1/-1")
        if match.is_real and (match.home_score < 0 or match.away_score < 0):
            errors.append(f"Real match {match.match_id} must have non-negative scores")

    return ValidationReport(errors=errors, warnings=warnings)

