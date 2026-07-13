from fastapi import APIRouter, HTTPException

from app.services.match_prediction_service import (
    get_match,
    get_saved_match_prediction,
    list_schedule,
    predict_single_match,
)

router = APIRouter(prefix="/api/matches", tags=["matches"])


@router.get("")
def list_matches(stage: str | None = None) -> list[dict]:
    """List matches with frontend-safe schedule fields."""

    matches = list_schedule()
    if stage:
        return [match for match in matches if match.get("stage") == stage]
    return matches


@router.get("/schedule")
def get_schedule() -> dict:
    matches = list_schedule()
    dates: dict[str, list[dict]] = {}
    for match in matches:
        dates.setdefault(match["match_date"], []).append(match)
    return {"dates": [{"date": date, "matches": items} for date, items in sorted(dates.items())]}


@router.get("/{match_id}")
def get_match_detail(match_id: str) -> dict:
    match = get_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="比赛不存在")
    return {"match": match, "saved_prediction": get_saved_match_prediction(match["match_id"])}


@router.post("/{match_id}/predict")
async def predict_match(match_id: str, realtime: bool = False) -> dict:
    try:
        return await predict_single_match(match_id, realtime=realtime)
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
