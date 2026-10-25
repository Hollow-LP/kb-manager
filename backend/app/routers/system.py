from fastapi import APIRouter

from app.db import ping_db
from app.redis import ping_redis

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    """健康检查：同时探测数据库与 Redis。"""
    checks: dict[str, str] = {}
    try:
        await ping_db()
        checks["database"] = "ok"
    except Exception as exc:  # 健康检查需返回细节而非 500
        checks["database"] = f"error: {exc}"
    try:
        await ping_redis()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
