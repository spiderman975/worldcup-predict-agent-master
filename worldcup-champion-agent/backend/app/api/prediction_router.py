from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.schemas.prediction import RunCreateRequest, RunCreateResponse
from app.services.cache_service import cache_service
from app.services.llm_service import llm_service
from app.services.match_reasoning_service import search_match_explanations
from app.services.stream_service import stream_service
from app.services.team_analysis_service import get_team_ratings_and_odds, search_teams

router = APIRouter(prefix="/api", tags=["prediction"])


def _sqlite_only_not_migrated(feature: str) -> None:
    raise HTTPException(
        status_code=501,
        detail=f"{feature} 仍依赖旧 demo 赛制规则，已停用。请先迁移为 SQLite 新数据流程后再启用。",
    )


@router.post("/runs", response_model=RunCreateResponse)
async def create_run(payload: RunCreateRequest) -> RunCreateResponse:
    _sqlite_only_not_migrated("整届赛事预测")


@router.post("/runs/ratings", response_model=RunCreateResponse)
async def create_ratings_run(payload: RunCreateRequest) -> RunCreateResponse:
    _sqlite_only_not_migrated("球队评分任务")


@router.post("/runs/group", response_model=RunCreateResponse)
async def create_group_run(payload: RunCreateRequest) -> RunCreateResponse:
    _sqlite_only_not_migrated("小组赛推演")


@router.post("/runs/group-round/{round_number}", response_model=RunCreateResponse)
async def create_group_round_run(round_number: int, payload: RunCreateRequest) -> RunCreateResponse:
    _sqlite_only_not_migrated("逐轮小组赛预测")


@router.post("/runs/knockout/{round_name}", response_model=RunCreateResponse)
async def create_knockout_run(round_name: str, payload: RunCreateRequest) -> RunCreateResponse:
    _sqlite_only_not_migrated("淘汰赛推演")


@router.post("/runs/champion", response_model=RunCreateResponse)
async def create_champion_run(payload: RunCreateRequest) -> RunCreateResponse:
    _sqlite_only_not_migrated("冠军概率预测")


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    raise HTTPException(status_code=404, detail="旧 demo 预测任务读取已停用；当前只保留 SQLite 单场预测结果。")


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    return EventSourceResponse(stream_service.stream(run_id))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    raise HTTPException(status_code=404, detail="旧 demo 预测任务取消已停用。")


@router.get("/ratings")
def get_ratings() -> dict:
    return cache_service.remember(
        cache_service.key("teams", "ratings"),
        cache_service.settings.cache_ratings_ttl_seconds,
        get_team_ratings_and_odds,
    )


@router.get("/llm/status")
def get_llm_status() -> dict:
    settings = llm_service.settings
    return {
        "llm_enabled": settings.llm_enabled,
        "has_api_key": bool(settings.llm_api_key),
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "agent_names": settings.llm_agent_names,
        "ready": llm_service.enabled,
    }


@router.get("/stages/group")
def get_group_stage() -> dict:
    _sqlite_only_not_migrated("小组赛阶段")


@router.get("/stages/knockout/{round_name}")
def get_knockout_stage(round_name: str) -> dict:
    _sqlite_only_not_migrated("淘汰赛阶段")


@router.get("/predictions/champion")
def get_champion_prediction(runs: int = Query(default=1000, ge=100, le=10000)) -> dict:
    _sqlite_only_not_migrated("冠军概率预测")


@router.get("/search/teams")
def search_team_database(q: str = "") -> dict:
    return {"query": q, "results": search_teams(q)}


@router.get("/search/match-explanations")
def search_explanations(q: str, top_k: int = Query(default=8, ge=1, le=20)) -> dict:
    return {"query": q, "results": search_match_explanations(q, top_k)}
