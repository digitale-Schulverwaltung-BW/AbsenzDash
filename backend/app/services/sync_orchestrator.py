from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.einstellung import Einstellung
from app.services.asv_csv_import import import_schueler
from app.services.webuntis_fehlzeit_sync import sync_fehlzeiten
from app.services.webuntis_kategorie_sync import sync_kategorien
from app.services.webuntis_klassen_sync import sync_klassen
from app.services.webuntis_klassenbuch_sync import sync_klassenbuch

logger = logging.getLogger(__name__)


async def _get_or_create_einstellung(db: AsyncSession) -> Einstellung:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None:
        einstellung = Einstellung()
        db.add(einstellung)
        await db.flush()
    return einstellung


def _fehlzeiten_zeitraum(einstellung: Einstellung, heute: date) -> tuple[date, date]:
    if einstellung.letzter_sync_am is not None:
        von = einstellung.letzter_sync_am.date() - timedelta(days=1)
    elif einstellung.schuljahr_start_cache is not None:
        von = einstellung.schuljahr_start_cache
    else:
        von = heute
    return von, heute


async def _run_once(db: AsyncSession) -> None:
    async with WebUntisClient(settings) as client:
        await sync_klassen(client, db)
        await sync_kategorien(client, db)
        await import_schueler(db)

        einstellung = await _get_or_create_einstellung(db)

        schuljahr = await client.call("getCurrentSchoolyear", {})
        schuljahr_start = datetime.strptime(str(schuljahr["startDate"]), "%Y%m%d").date()
        if schuljahr_start != einstellung.schuljahr_start_cache:
            einstellung.schuljahr_start_cache = schuljahr_start

        heute = datetime.now(timezone.utc).date()
        von, bis = _fehlzeiten_zeitraum(einstellung, heute)
        await sync_fehlzeiten(client, db, von, bis)
        await sync_klassenbuch(client, db, von, bis)

        einstellung.letzter_sync_am = datetime.now(timezone.utc)
        if not einstellung.initialer_import_abgeschlossen:
            einstellung.initialer_import_abgeschlossen = True
        await db.commit()


async def run_full_sync(db: AsyncSession) -> None:
    """Orchestriert einen vollstaendigen WebUntis-Sync-Lauf mit Retry (TECH-SPEC.md Abschnitt 1.3b)."""
    max_attempts = settings.webuntis_sync_retry_max_attempts
    delay_seconds = settings.webuntis_sync_retry_delay_minutes * 60

    for attempt in range(1, max_attempts + 1):
        try:
            await _run_once(db)
            return
        except (WebUntisError, OSError) as exc:
            await db.rollback()
            logger.warning("Sync-Lauf fehlgeschlagen (Versuch %d/%d): %s", attempt, max_attempts, exc)
            if attempt == max_attempts:
                logger.error("Sync-Lauf endgueltig abgebrochen nach %d Versuchen", max_attempts)
                return
            await asyncio.sleep(delay_seconds)
