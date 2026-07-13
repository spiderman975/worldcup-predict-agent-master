from pydantic import BaseModel, Field


class Team(BaseModel):
    """球队基础信息和模型特征。"""

    team_id: str
    name: str
    group: str
    fifa_rank: int = Field(gt=0)
    elo_rating: float
    attack_score: float
    defense_score: float
    recent_form: float
    worldcup_history_score: float
    squad_availability_score: float = 0.8


class TeamRating(BaseModel):
    """球队综合评分结果。"""

    team_id: str
    name: str
    group: str
    overall_rating: float
    attack_strength: float
    defense_strength: float
    form_score: float
    explanation_factors: list[str]
