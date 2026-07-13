from pydantic import BaseModel


class Match(BaseModel):
    """赛程数据。MVP 中主要包含 16 队 demo 小组赛。"""

    match_id: str
    stage: str
    group: str | None = None
    home_team_id: str
    away_team_id: str
    match_time: str
    venue: str


class ScoreProbability(BaseModel):
    """一个具体比分及其概率。"""

    home_score: int
    away_score: int
    probability: float


class MatchPrediction(BaseModel):
    """单场比赛预测输出，包含胜平负概率和比分矩阵。"""

    match_id: str
    stage: str
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    predicted_home_score: int
    predicted_away_score: int
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    score_matrix: list[list[float]]
    top_scores: list[ScoreProbability]
    winner: str | None
    winner_name: str | None
    confidence: float
    key_factors: list[str]
