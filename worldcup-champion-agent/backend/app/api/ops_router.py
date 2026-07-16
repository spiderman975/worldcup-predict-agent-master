from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from app.core.redis_client import redis_client
from app.services.cache_service import cache_service
from app.services.checkpoint_service import checkpoint_service
from app.services.database_explorer import database_explorer
from app.services.db_maintenance_service import db_maintenance_service
from app.services.live_score_sync_service import live_score_sync_service
from app.services.match_prediction_service import get_match
from app.services.match_result_service import match_result_service
from app.services.scheduler_service import scheduler_service
from app.services.text2sql_service import text2sql_service
from app.services.worldcup_initialization_service import WorldCupInitializeOptions, worldcup_initialization_service
from data.database import get_active_season, get_connection, init_db

router = APIRouter(prefix="/api/ops", tags=["ops"])


class WorldCupInitializeRequest(BaseModel):
    season: int = Field(..., ge=1930, le=2100)
    activate: bool = True
    sync_football_data: bool = True
    bootstrap_teams: bool = True
    init_knockout_placeholders: bool = True


@router.get("/redis/health")
def redis_health() -> dict:
    return redis_client.health()


@router.get("/cache/status")
def cache_status() -> dict:
    return cache_service.status()


@router.delete("/cache")
def clear_cache(prefix: str | None = Query(default=None)) -> dict:
    if prefix:
        deleted = cache_service.delete_prefix(prefix)
        return {"success": True, "prefix": prefix, "deleted": deleted, "backend": cache_service.backend()}
    deleted = (
        cache_service.delete_prefix("teams:")
        + cache_service.delete_prefix("matches:")
        + cache_service.delete_prefix("match:")
        + cache_service.delete_prefix("postmatch:")
    )
    return {"success": True, "deleted": deleted, "backend": cache_service.backend()}


@router.get("/scheduler/status")
def scheduler_status() -> dict:
    return scheduler_service.status()


@router.post("/scheduler/scan")
async def scheduler_scan(force: bool = Query(default=False)) -> dict:
    return await scheduler_service.scan_once(force=force)


@router.get("/live-sync/status")
def live_sync_status() -> dict:
    return live_score_sync_service.status()


@router.post("/live-sync")
async def trigger_live_sync() -> dict:
    return await live_score_sync_service.sync_once(force=True)


@router.get("/worldcup/seasons")
def list_worldcup_seasons() -> dict:
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT season, competition_code, competition_name, status, is_active, data_source,
                   initialized_at, updated_at, notes
            FROM worldcup_seasons
            ORDER BY season DESC
            """
        ).fetchall()
    return {"active_season": get_active_season(), "seasons": [dict(row) for row in rows]}


@router.post("/worldcup/initialize")
def initialize_worldcup(payload: WorldCupInitializeRequest) -> dict:
    return worldcup_initialization_service.initialize(
        WorldCupInitializeOptions(
            season=payload.season,
            activate=payload.activate,
            sync_football_data=payload.sync_football_data,
            bootstrap_teams=payload.bootstrap_teams,
            init_knockout_placeholders=payload.init_knockout_placeholders,
        )
    )


@router.post("/matches/{match_id}/result-refresh")
async def refresh_match_result(match_id: str, force: bool = Query(default=True)) -> dict:
    match = get_match(match_id)
    if not match:
        return {"success": False, "error": "比赛不存在", "match_id": match_id}
    return await match_result_service.refresh_result(match, force=force)


@router.get("/checkpoints")
def list_checkpoints(status: str | None = Query(default=None), limit: int = Query(default=100)) -> list[dict]:
    return checkpoint_service.list(status=status, limit=limit)


@router.post("/checkpoints/recover-stale")
def recover_stale_checkpoints() -> dict:
    return checkpoint_service.recover_stale()


@router.delete("/checkpoints/{name}")
def delete_checkpoint(name: str) -> dict:
    return {"success": checkpoint_service.delete(name), "name": name}


@router.get("/database/schema")
def database_schema() -> dict:
    return database_explorer.get_schema()


@router.get("/database/performance")
def database_performance() -> dict:
    return db_maintenance_service.performance_report()


@router.post("/database/backup")
def database_backup(label: str = Query(default="manual")) -> dict:
    return db_maintenance_service.backup(label=label)


@router.get("/database/backups")
def database_backups() -> list[dict]:
    return db_maintenance_service.list_backups()


@router.post("/database/restore")
def database_restore(backup_name: str = Query(...)) -> dict:
    return db_maintenance_service.restore(backup_name)


@router.post("/database/optimize")
def database_optimize() -> dict:
    return db_maintenance_service.optimize()


@router.get("/database/integrity")
def database_integrity() -> dict:
    return db_maintenance_service.integrity_check()


@router.post("/text2sql/query")
async def text2sql_query(payload: dict = Body(...)) -> dict:
    question = str(payload.get("question", "")).strip()
    limit = int(payload.get("limit", 100))
    return await text2sql_service.query(question, limit=limit)
