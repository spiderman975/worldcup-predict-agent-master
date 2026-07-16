import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.services.cache_service import cache_service
from app.services.match_prediction_service import (
    get_match,
    get_saved_match_prediction,
    list_schedule,
    predict_single_match,
)
from app.services.stream_service import stream_service

router = APIRouter(prefix="/api/matches", tags=["matches"])

TERMINAL_EVENTS = {"prediction_complete", "prediction_error", "prediction_canceled"}


async def _run_match_prediction_stream(run_id: str, match_id: str, realtime: bool) -> None:
    try:
        await stream_service.publish(run_id, "prediction_start", "开始单场比赛预测", "MATCH_WORKFLOW", {"match_id": match_id})

        async def emit(event: str, message: str, phase: str | None = None, data: dict | None = None) -> None:
            payload = data or {}
            await stream_service.publish(run_id, event, message, phase, payload)
            if event in {"agent_node", "data_scout_update"}:
                await stream_service.publish(
                    run_id,
                    "agent_progress",
                    message,
                    phase,
                    {
                        "stage": payload.get("agent") or event,
                        "status": "completed",
                        "detail": payload,
                    },
                )

        record = await predict_single_match(match_id, realtime=realtime, progress_emit=emit)
        await stream_service.publish(
            run_id,
            "prediction_complete",
            "单场预测完成",
            "MATCH_WORKFLOW",
            {"match_id": match_id, "record": record},
        )
    except Exception as exc:
        await stream_service.publish(
            run_id,
            "prediction_error",
            f"单场预测失败：{exc}",
            "MATCH_WORKFLOW",
            {"match_id": match_id, "error": str(exc)},
        )


@router.get("")
def list_matches(stage: str | None = None, fresh: bool = Query(default=False)) -> list[dict]:
    """List matches with frontend-safe schedule fields."""

    matches = list_schedule() if fresh else cache_service.remember(
            cache_service.key("matches", "list"),
            cache_service.settings.cache_matches_ttl_seconds,
            list_schedule,
        )
    if stage:
        return [match for match in matches if match.get("stage") == stage]
    return matches


@router.get("/schedule")
def get_schedule(fresh: bool = Query(default=False)) -> dict:
    def load_schedule() -> dict:
        matches = list_schedule()
        dates: dict[str, list[dict]] = {}
        for match in matches:
            dates.setdefault(match["match_date"], []).append(match)
        return {"dates": [{"date": date, "matches": items} for date, items in sorted(dates.items())]}

    if fresh:
        return load_schedule()
    return cache_service.remember(
        cache_service.key("matches", "schedule"),
        cache_service.settings.cache_matches_ttl_seconds,
        load_schedule,
    )


@router.get("/{match_id}")
def get_match_detail(match_id: str) -> dict:
    normalized_id = match_id.lower()

    def load_detail() -> dict:
        match = get_match(normalized_id)
        if not match:
            raise HTTPException(status_code=404, detail="比赛不存在")
        return {"match": match, "saved_prediction": get_saved_match_prediction(match["match_id"])}

    return cache_service.remember(
        cache_service.key("match", "detail", normalized_id),
        cache_service.settings.cache_match_detail_ttl_seconds,
        load_detail,
    )


@router.post("/{match_id}/predict")
async def predict_match(match_id: str, realtime: bool = False) -> dict:
    try:
        result = await predict_single_match(match_id, realtime=realtime)
        cache_service.invalidate_matches(match_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{match_id}/predict/start")
async def start_predict_match(match_id: str, realtime: bool = False) -> dict:
    if not get_match(match_id):
        raise HTTPException(status_code=404, detail="比赛不存在")
    run_id = f"match_{uuid.uuid4().hex}"
    asyncio.create_task(_run_match_prediction_stream(run_id, match_id, realtime))
    return {"run_id": run_id, "match_id": match_id, "status": "started"}


@router.get("/predict-runs/{run_id}/stream")
async def stream_match_prediction(run_id: str) -> EventSourceResponse:
    return EventSourceResponse(stream_service.stream(run_id))


@router.get("/{match_id}/prediction")
def get_match_prediction(match_id: str) -> dict:
    match = get_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="比赛不存在")
    saved = get_saved_match_prediction(match["match_id"])
    if not saved:
        raise HTTPException(status_code=404, detail="这场比赛还没有保存的预测结果")
    return saved
