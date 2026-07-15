from fastapi import APIRouter, HTTPException, Query

from app.services.cache_service import cache_service
from app.services.match_prediction_service import (
    get_match,
    get_saved_match_prediction,
    list_schedule,
    predict_single_match,
)

router = APIRouter(prefix="/api/matches", tags=["matches"])


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


@router.get("/{match_id}/prediction")
def get_match_prediction(match_id: str) -> dict:
    match = get_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="比赛不存在")
    saved = get_saved_match_prediction(match["match_id"])
    if not saved:
        raise HTTPException(status_code=404, detail="这场比赛还没有保存的预测结果")
    return saved
