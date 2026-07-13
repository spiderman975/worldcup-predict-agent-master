from __future__ import annotations

from pydantic import BaseModel, Field


STREAK_MODIFIER_TABLE = {
    -3: 0.80,
    -2: 0.85,
    -1: 0.92,
    0: 1.00,
    1: 1.08,
    2: 1.15,
    3: 1.20,
}


class Member(BaseModel):
    name: str
    attack_member: float = Field(ge=0, le=100)
    defensive_member: float = Field(ge=0, le=100)
    injured: int = Field(default=0, ge=0, le=1)
    injury_description: str = ""

    def get_attack(self) -> float:
        return self.attack_member * (0.9 if self.injured else 1.0)

    def get_defensive(self) -> float:
        return self.defensive_member * (0.9 if self.injured else 1.0)


class Team(BaseModel):
    name: str
    group: str
    members: list[Member] = Field(default_factory=list)
    attack_team: float = 1.0
    defensive_team: float = 1.0
    starting_lineup: list[str] = Field(default_factory=list)
    streak: int = 0
    fifa_ranking: int | None = None

    @property
    def streak_modifier(self) -> float:
        clamped = max(-3, min(3, self.streak))
        return STREAK_MODIFIER_TABLE[clamped]

    def get_attack(self) -> float:
        lineup = self._active_members()
        if not lineup:
            return 0.0
        avg = sum(member.get_attack() for member in lineup) / len(lineup)
        return avg * self.attack_team * self.streak_modifier

    def get_defensive(self) -> float:
        lineup = self._active_members()
        if not lineup:
            return 0.0
        avg = sum(member.get_defensive() for member in lineup) / len(lineup)
        return avg * self.defensive_team * self.streak_modifier

    def _active_members(self) -> list[Member]:
        if self.starting_lineup:
            name_set = set(self.starting_lineup)
            return [member for member in self.members if member.name in name_set]
        return self.members


class Match(BaseModel):
    home_team: str
    away_team: str
    home_score: int = -1
    away_score: int = -1
    stage: int = Field(ge=1, le=8)
    match_id: str
    is_real: bool = False
    played_at: str | None = None

