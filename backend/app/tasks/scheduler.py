"""定时任务：知识沉淀挖掘（MINING_CRON）。APScheduler 的 CronTrigger 使用系统本地时区。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.services import mining

log = logging.getLogger("kb.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def _job() -> None:
    try:
        result = await mining.run_all()
        log.info("定时挖掘完成：%s", result)
    except Exception:  # noqa: BLE001
        log.exception("定时挖掘失败")


def start() -> AsyncIOScheduler | None:
    global _scheduler
    settings = get_settings()
    if not settings.mining_enabled or _scheduler is not None:
        return _scheduler
    try:
        trigger = CronTrigger.from_crontab(settings.mining_cron)
    except ValueError as exc:
        log.warning("MINING_CRON 配置无效（%s）：%s，使用默认 02:00", settings.mining_cron, exc)
        trigger = CronTrigger(hour=2, minute=0)
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_job, trigger, id="kb-mining", replace_existing=True, misfire_grace_time=3600)
    _scheduler.start()
    log.info("沉淀挖掘定时任务已启动：%s", settings.mining_cron)
    return _scheduler


async def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def status() -> dict:
    job = _scheduler.get_job("kb-mining") if _scheduler else None
    return {"running": bool(_scheduler), "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None}
