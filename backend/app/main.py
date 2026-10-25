from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import logging

from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.db import engine
from app.redis import close_redis
from app.routers import ai, auth, dashboard, knowledge, org, settlement, system
from app.services.knowledge import import_queue, recover_pending_jobs
from app.tasks import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动阶段：导入 worker（并把上次未完成的导入任务重新入队）
    await import_queue.start()
    recovered = await recover_pending_jobs()
    if recovered:
        log.info("re-queued %s unfinished import jobs", recovered)
    scheduler.start()
    yield
    # 关闭阶段：停止 worker 与定时任务，释放连接池与缓存连接
    await scheduler.stop()
    await import_queue.stop()
    await close_redis()
    await engine.dispose()


log = logging.getLogger("kb.app")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Knowledge Base Manager API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(system.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(org.router, prefix="/api")
    app.include_router(knowledge.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(settlement.router, prefix="/api")
    return app


app = create_app()
