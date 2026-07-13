from typing import Literal

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    """创建预测任务的请求参数。mode 用于分阶段触发不同预测流程。"""

    monte_carlo_runs: int = Field(default=1000, ge=100, le=10000)
    enable_realtime_search: bool = False
    mode: Literal["full", "ratings", "group", "group_round", "knockout", "champion"] = "full"
    knockout_round: Literal["quarter", "semi", "final"] | None = None
    group_round: Literal[1, 2, 3] | None = None


class RunCreateResponse(BaseModel):
    run_id: str
    status: str


class ChampionProbability(BaseModel):
    team_id: str
    team_name: str
    probability: float


class VerifierResult(BaseModel):
    passed: bool
    warnings: list[str]
    errors: list[str]


class TeamSearchResponse(BaseModel):
    """球队数据检索响应。"""

    query: str
    results: list[dict]


class MatchExplanationSearchResponse(BaseModel):
    """比赛解释向量检索响应。"""

    query: str
    results: list[dict]
