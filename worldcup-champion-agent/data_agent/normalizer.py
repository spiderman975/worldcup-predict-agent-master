from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedMember:
    name: str
    team_name: str
    attack: float
    defensive: float
    injured: int
    injury_description: str


@dataclass(frozen=True)
class NormalizedTeam:
    name: str
    group: str
    attack_team: float
    defensive_team: float
    streak: int
    starting_lineup: list[str]
    fifa_ranking: int | None
    members: list[NormalizedMember]


@dataclass(frozen=True)
class NormalizedMatch:
    match_id: str
    stage: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    is_real: bool
    played_at: str | None
    status: str = ""


@dataclass(frozen=True)
class NormalizedRanking:
    team_name: str
    fifa_ranking: int


@dataclass(frozen=True)
class NormalizedInjury:
    team_name: str
    player_name: str
    injured: int
    injury_description: str


@dataclass(frozen=True)
class NormalizedLineup:
    team_name: str
    player_names: list[str]


@dataclass(frozen=True)
class NormalizedDataset:
    teams: list[NormalizedTeam]
    members: list[NormalizedMember]
    matches: list[NormalizedMatch]


def normalize_static_dataset(
    team_rows: list[dict[str, str]],
    roster_rows: list[dict[str, str]],
    schedule_rows: list[dict[str, str]],
    ranking_rows: list[dict[str, str]],
) -> NormalizedDataset:
    ranking_by_team = _ranking_by_team(ranking_rows)
    members = [_normalize_member(row) for row in roster_rows]
    members_by_team: dict[str, list[NormalizedMember]] = {}
    for member in members:
        members_by_team.setdefault(member.team_name, []).append(member)

    teams = [
        _normalize_team(row, ranking_by_team.get(_clean(row["name"])), members_by_team.get(_clean(row["name"]), []))
        for row in team_rows
    ]
    matches = [_normalize_match(row) for row in schedule_rows]
    return NormalizedDataset(teams=teams, members=members, matches=matches)


def _normalize_team(row: dict[str, str], ranking: int | None, members: list[NormalizedMember]) -> NormalizedTeam:
    inline_ranking = _optional_int(row.get("fifa_ranking"))
    return NormalizedTeam(
        name=_clean(row["name"]),
        group=_clean(row["group"]).upper(),
        attack_team=_float(row["attack_team"], default=1.0),
        defensive_team=_float(row["defensive_team"], default=1.0),
        streak=_int(row["streak"], default=0),
        starting_lineup=_parse_name_list(row.get("starting_lineup", "")),
        fifa_ranking=inline_ranking if inline_ranking is not None else ranking,
        members=members,
    )


def _normalize_member(row: dict[str, str]) -> NormalizedMember:
    return NormalizedMember(
        name=_clean(row["name"]),
        team_name=_clean(row["team_name"]),
        attack=_float(row["attack"]),
        defensive=_float(row["defensive"]),
        injured=_int(row["injured"], default=0),
        injury_description=_clean(row.get("injury_description", "")),
    )


def _normalize_match(row: dict[str, str]) -> NormalizedMatch:
    is_real = _bool(row.get("is_real", "false"))
    home_score = _score(row.get("home_score"))
    away_score = _score(row.get("away_score"))
    return NormalizedMatch(
        match_id=_clean(row["match_id"]),
        stage=_int(row["stage"]),
        home_team=_clean(row["home_team"]),
        away_team=_clean(row["away_team"]),
        home_score=home_score,
        away_score=away_score,
        is_real=is_real,
        played_at=_clean(row.get("played_at", "")) or None,
        status=_clean(row.get("status", "")),
    )


def _ranking_by_team(rows: list[dict[str, str]]) -> dict[str, int]:
    rankings: dict[str, int] = {}
    for row in rows:
        name = _clean(row["team_name"])
        if name:
            rankings[name] = _int(row["fifa_ranking"])
    return rankings


def _parse_name_list(value: str) -> list[str]:
    text = _clean(value)
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("starting_lineup JSON must be a list")
        return [_clean(str(item)) for item in parsed if _clean(str(item))]
    separator = "|" if "|" in text else ";"
    return [_clean(item) for item in text.split(separator) if _clean(item)]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _int(value: Any, default: int | None = None) -> int:
    text = _clean(value)
    if not text:
        if default is None:
            raise ValueError("Expected integer value, got empty string")
        return default
    return int(text)


def _optional_int(value: Any) -> int | None:
    text = _clean(value)
    return int(text) if text else None


def _float(value: Any, default: float | None = None) -> float:
    text = _clean(value)
    if not text:
        if default is None:
            raise ValueError("Expected float value, got empty string")
        return default
    return float(text)


def _bool(value: Any) -> bool:
    text = _clean(value).lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", ""}:
        return False
    raise ValueError(f"Expected boolean value, got: {value}")


def _score(value: Any) -> int:
    text = _clean(value)
    return -1 if not text else int(text)
