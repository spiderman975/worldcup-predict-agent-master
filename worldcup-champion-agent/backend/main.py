from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat_router import router as chat_router
from app.api.data_router import router as data_router
from app.api.match_router import router as match_router
from app.api.ops_router import router as ops_router
from app.api.prediction_router import router as prediction_router
from app.api.team_router import router as team_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.init_db import init_db
from app.services.scheduler_service import scheduler_service

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prediction_router)
app.include_router(team_router)
app.include_router(match_router)
app.include_router(chat_router)
app.include_router(data_router)
app.include_router(ops_router)


@app.on_event("startup")
async def on_startup() -> None:
    """应用启动时创建数据库表，并确保 demo 数据已生成。"""

    init_db()
    scheduler_service.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await scheduler_service.stop()


@app.get("/api/health")
def health() -> dict[str, str]:
    """健康检查接口。"""

    return {"status": "ok", "service": settings.app_name}
