from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.einstellung import Einstellung
from app.services.sync_orchestrator import run_full_sync

logger = logging.getLogger(__name__)

MAIN_SYNC_JOB_ID = "webuntis_main_sync"


async def _read_sync_interval_cron() -> str:
    async with async_session_factory() as db:
        result = await db.execute(select(Einstellung))
        einstellung = result.scalars().first()
        return einstellung.sync_interval_cron if einstellung else "*/30 * * * *"


async def _run_main_sync_job(scheduler: AsyncIOScheduler) -> None:
    try:
        async with async_session_factory() as db:
            await run_full_sync(db)
    finally:
        cron_expr = await _read_sync_interval_cron()
        scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=CronTrigger.from_crontab(cron_expr))


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    cron_expr = await _read_sync_interval_cron()
    logger.info(f"Registering {MAIN_SYNC_JOB_ID} job with cron expression: {cron_expr}")
    scheduler.add_job(
        _run_main_sync_job,
        trigger=CronTrigger.from_crontab(cron_expr),
        id=MAIN_SYNC_JOB_ID,
        args=[scheduler],
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started with {MAIN_SYNC_JOB_ID} job registered")
