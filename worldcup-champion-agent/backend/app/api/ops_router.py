from fastapi import APIRouter, Body, Query

from app.core.redis_client import redis_client
from app.services.checkpoint_service import checkpoint_service
from app.services.database_explorer import database_explorer
from app.services.db_maintenance_service import db_maintenance_service
from app.services.match_prediction_service import get_match
from app.services.match_result_service import match_result_service
from app.services.scheduler_service import scheduler_service
from app.services.text2sql_service import text2sql_service

router = APIRouter(prefix="/api/ops", tags=["ops"])


@router.get("/redis/health")
def redis_health() -> dict:
    return redis_client.health()


@router.get("/scheduler/status")
def scheduler_status() -> dict:
    return scheduler_service.status()


@router.post("/scheduler/scan")
async def scheduler_scan(force: bool = Query(default=False)) -> dict:
    return await scheduler_service.scan_once(force=force)


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
