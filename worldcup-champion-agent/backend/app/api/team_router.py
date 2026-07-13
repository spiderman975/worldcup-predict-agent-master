from fastapi import APIRouter, HTTPException

from app.services.data_scout_service import data_scout_service

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("")
def list_teams() -> list[dict]:
    """获取 SQLite 球队列表。"""

    return data_scout_service.list_teams()


@router.get("/{team_id}")
def get_team(team_id: str) -> dict:
    """获取单支球队详情。"""

    team = next((item for item in data_scout_service.list_teams() if item["team_id"] == team_id), None)
    if not team:
        raise HTTPException(status_code=404, detail="球队不存在")
    return team
