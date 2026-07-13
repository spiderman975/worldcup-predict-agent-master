from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TeamModel(Base):
    """球队表，保存 demo 或后续采集到的球队特征。"""

    __tablename__ = "teams"

    team_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    group: Mapped[str] = mapped_column(String, nullable=False)
    fifa_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_rating: Mapped[float] = mapped_column(Float, nullable=False)


class MatchModel(Base):
    """赛程表，MVP 中用于记录 demo 小组赛。"""

    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    group: Mapped[str | None] = mapped_column(String, nullable=True)
    home_team_id: Mapped[str] = mapped_column(String, nullable=False)
    away_team_id: Mapped[str] = mapped_column(String, nullable=False)


class PredictionRunModel(Base):
    """预测任务元数据，完整结果仍以 JSON snapshot 为主。"""

    __tablename__ = "prediction_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    final_champion: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PredictedMatchModel(Base):
    """预测比赛表，后续可用于查询和审计。"""

    __tablename__ = "predicted_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("prediction_runs.run_id"))
    match_id: Mapped[str] = mapped_column(String, nullable=False)
    winner: Mapped[str | None] = mapped_column(String, nullable=True)


class ChampionProbabilityModel(Base):
    """冠军概率表。"""

    __tablename__ = "champion_probabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("prediction_runs.run_id"))
    team_id: Mapped[str] = mapped_column(String, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)


class AgentMessageModel(Base):
    """Agent 推理消息表。"""

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("prediction_runs.run_id"))
    event: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
