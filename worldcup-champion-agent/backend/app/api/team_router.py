from fastapi import APIRouter, HTTPException

from app.services.cache_service import cache_service
from app.services.data_scout_service import data_scout_service
from app.services.team_analysis_service import get_team_ratings_and_odds

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("")
def list_teams() -> list[dict]:
    """Get SQLite-backed team list."""

    return cache_service.remember(
        cache_service.key("teams", "list"),
        cache_service.settings.cache_teams_ttl_seconds,
        data_scout_service.list_teams,
    )


@router.get("/{team_id}")
def get_team(team_id: str) -> dict:
    """Get one team detail from cache or SQLite."""

    normalized_id = team_id.upper()
    team = cache_service.remember(
        cache_service.key("teams", "detail", normalized_id),
        cache_service.settings.cache_teams_ttl_seconds,
        lambda: data_scout_service.team_detail_by_id(normalized_id),
    )
    if not team:
        raise HTTPException(status_code=404, detail="球队不存在")

    ratings = cache_service.remember(
        cache_service.key("teams", "ratings"),
        cache_service.settings.cache_ratings_ttl_seconds,
        get_team_ratings_and_odds,
    )
    return {**team, "rating": (ratings.get("team_ratings") or {}).get(normalized_id)}
