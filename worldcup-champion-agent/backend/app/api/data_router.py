from fastapi import APIRouter, HTTPException, Query

from app.services.data_scout_service import data_scout_service

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/search")
async def search_data(
    q: str,
    include_web: bool = Query(default=False),
    top_k: int = Query(default=8, ge=1, le=20),
) -> dict:
    return await data_scout_service.search(q, include_web=include_web, top_k=top_k)


@router.get("/teams/{team_name}")
def get_team_database_report(team_name: str) -> dict:
    report = data_scout_service.team_report(team_name)
    if not report:
        raise HTTPException(status_code=404, detail="数据库中没有找到该球队")
    return report
