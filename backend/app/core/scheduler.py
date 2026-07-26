from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.einstellung import Einstellung
from app.services.sync_orchestrator import run_full_sync

logger = logging.getLogger(__name__)

MAIN_SYNC_JOB_ID = "webuntis_main_sync"

# Haelt starke Referenzen auf laufende Sync-Hintergrund-Tasks, damit sie waehrend
# ihrer (bis zu ~2h dauernden) Laufzeit nicht vom Event-Loop, der selbst nur eine
# schwache Referenz haelt, vorzeitig eingesammelt werden koennen.
_background_sync_tasks: set[asyncio.Task[None]] = set()


async def _read_sync_interval_cron() -> str:
    async with async_session_factory() as db:
        result = await db.execute(select(Einstellung))
        einstellung = result.scalars().first()
        return einstellung.sync_interval_cron if einstellung else "*/30 * * * *"


async def _run_sync_task() -> None:
    try:
        await run_full_sync(async_session_factory)
    except Exception:
        logger.exception("Unerwarteter Fehler im Sync-Hintergrund-Task")


async def _run_main_sync_job(scheduler: AsyncIOScheduler) -> asyncio.Task[None]:
    """Stoesst den Sync-Lauf (inkl. seiner eigenen Retry-Logik) als
    Hintergrund-Task an und plant den naechsten regulaeren Cron-Termin sofort
    neu — unabhaengig davon, wie lange der Sync-Lauf (mit Retries bis zu ~2h)
    noch braucht (TECH-SPEC.md Abschnitt 1.3b)."""
    task = asyncio.create_task(_run_sync_task())
    _background_sync_tasks.add(task)
    task.add_done_callback(_background_sync_tasks.discard)
    cron_expr = await _read_sync_interval_cron()
    scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=CronTrigger.from_crontab(cron_expr))
    return task


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
