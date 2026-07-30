from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import MAIN_SYNC_JOB_ID
from app.models.audit_log import AuditLog
from app.models.einstellung import Einstellung
from app.models.schuljahr import Schuljahr
from app.schemas.admin import SyncSchuljahrOut, SyncSettingsOut
from app.services.sync_orchestrator import get_or_create_einstellung


async def _settings_out(db: AsyncSession, einstellung: Einstellung) -> SyncSettingsOut:
    aktuelles_schuljahr = None
    if einstellung.aktuelles_schuljahr_id is not None:
        schuljahr = await db.get(Schuljahr, einstellung.aktuelles_schuljahr_id)
        if schuljahr is not None:
            aktuelles_schuljahr = SyncSchuljahrOut(id=schuljahr.id, name=schuljahr.name)
    return SyncSettingsOut(
        sync_interval_cron=einstellung.sync_interval_cron,
        schuljahr_start_cache=einstellung.schuljahr_start_cache,
        letzter_sync_am=einstellung.letzter_sync_am,
        aktuelles_schuljahr=aktuelles_schuljahr,
    )


async def get_sync_settings(db: AsyncSession) -> SyncSettingsOut:
    einstellung = await get_or_create_einstellung(db)
    await db.commit()
    return await _settings_out(db, einstellung)


async def update_sync_settings(
    db: AsyncSession, scheduler: AsyncIOScheduler, cron_expr: str, nutzer_id: int
) -> SyncSettingsOut:
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid cron expression: {exc}")

    einstellung = await get_or_create_einstellung(db)
    einstellung.sync_interval_cron = cron_expr
    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="admin_sync_settings_updated",
            resource_typ="einstellung",
            details={"sync_interval_cron": cron_expr},
        )
    )
    await db.commit()

    scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=trigger)

    return await _settings_out(db, einstellung)
