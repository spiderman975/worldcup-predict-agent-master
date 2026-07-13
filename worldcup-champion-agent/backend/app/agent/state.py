from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RunStatus = Literal["pending", "running", "completed", "failed", "canceled"]


class PredictionState(BaseModel):
    """一次预测任务的全量状态，既用于内存运行，也用于 snapshot 落盘。"""

    run_id: str
    status: RunStatus = "pending"
    current_phase: str = "PENDING"
    teams: list[dict[str, Any]] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)
    team_features: dict[str, Any] = Field(default_factory=dict)
    team_ratings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    team_odds: list[dict[str, Any]] = Field(default_factory=list)
    group_results: dict[str, Any] = Field(default_factory=dict)
    group_third_ranking: list[dict[str, Any]] = Field(default_factory=list)
    knockout_results: dict[str, Any] = Field(default_factory=dict)
    predicted_matches: list[dict[str, Any]] = Field(default_factory=list)
    match_explanations: list[dict[str, Any]] = Field(default_factory=list)
    champion_probabilities: list[dict[str, Any]] = Field(default_factory=list)
    round_reach_probabilities: dict[str, Any] = Field(default_factory=dict)
    reasoning_steps: list[dict[str, Any]] = Field(default_factory=list)
    final_champion: str | None = None
    final_reasoning: str | None = None
    verifier_result: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def touch(self, phase: str | None = None) -> None:
        """更新阶段和时间戳，保证前端状态展示及时。"""

        if phase:
            self.current_phase = phase
        self.updated_at = datetime.utcnow()
