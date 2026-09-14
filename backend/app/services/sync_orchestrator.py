from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.einstellung import Einstellung
from app.models.schuljahr import Schuljahr
from app.services.asv_csv_import import import_schueler
from app.services.eskalations_pruefung import pruefe_schwellwerte
from app.services.webuntis_abteilung_sync import sync_abteilungen
from app.services.webuntis_bereich_sync import sync_bereiche
from app.services.webuntis_fehlzeit_sync import sync_fehlzeiten
from app.services.webuntis_kategorie_sync import sync_kategorien
from app.services.webuntis_klassen_sync import sync_klassen
from app.services.webuntis_klassenbuch_sync import sync_klassenbuch
from app.services.webuntis_stundenraster_sync import sync_stundenraster

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()


class SyncAlreadyRunningError(RuntimeError):
    """Wird geworfen, wenn ein Sync-Lauf angestossen wird, waehrend bereits einer laeuft."""


async def get_or_create_einstellung(db: AsyncSession) -> Einstellung:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None:
        einstellung = Einstellung()
        db.add(einstellung)
        await db.flush()
    return einstellung


def _fehlzeiten_zeitraum(einstellung: Einstellung, heute: date, schuljahr_ende: date) -> tuple[date, date]:
    if einstellung.letzter_sync_am is not None:
        von = einstellung.letzter_sync_am.date() - timedelta(days=1)
    elif einstellung.schuljahr_start_cache is not None:
        von = einstellung.schuljahr_start_cache
    else:
        von = heute
    bis = min(heute, schuljahr_ende)
    return von, bis


async def _juengstes_bereits_gestartetes_schuljahr(db: AsyncSession) -> Schuljahr:
    """Fallback-Auswahl: das juengste Schuljahr, das bereits begonnen hat (start_datum
    <= heute), damit ein bereits im Cache angelegtes aber noch nicht begonnenes
    zukuenftiges Schuljahr nicht faelschlich als 'aktuell' gilt (siehe Live-Fund
    2026-07-30: sonst wuerde schuljahr_start_cache auf ein Datum in der Zukunft
    gesetzt und jedes Eskalations-Zaehlfenster leer laufen). Falls aus irgendeinem
    Grund kein Schuljahr diese Bedingung erfuellt, wird ersatzweise das insgesamt
    juengste bekannte Schuljahr zurueckgegeben, damit die Funktion immer ein
    Ergebnis liefert."""
    heute = datetime.now(timezone.utc).date()
    result = await db.execute(
        select(Schuljahr)
        .where(Schuljahr.start_datum <= heute)
        .order_by(Schuljahr.end_datum.desc())
        .limit(1)
    )
    schuljahr = result.scalar_one_or_none()
    if schuljahr is not None:
        return schuljahr

    result = await db.execute(select(Schuljahr).order_by(Schuljahr.end_datum.desc()).limit(1))
    return result.scalar_one()


async def resolve_aktuelles_schuljahr(client: WebUntisClient, db: AsyncSession) -> Schuljahr:
    """Aktualisiert den schuljahr-Cache aus getSchoolyears und liefert das aktuell
    gueltige Schuljahr zurueck. Wenn WebUntis kein aktuelles Schuljahr kennt (z.B.
    Uebergangszeitraum zwischen zwei Schuljahren, siehe Live-Fund 2026-07-30), oder
    das von getCurrentSchoolyear gemeldete Schuljahr entgegen Erwartung nicht im
    gerade aktualisierten Cache steht, wird ersatzweise das juengste bereits
    gestartete Schuljahr im Cache zurueckgegeben - so bekommen nachfolgende
    schuljahresgebundene WebUntis-Aufrufe (z.B. getKlassen) immer eine gueltige
    schoolyearId, auch waehrend der Luecke, und es wird nie ein noch nicht
    begonnenes zukuenftiges Schuljahr faelschlich als 'aktuell' behandelt."""
    rows = await client.call("getSchoolyears", {})
    for row in rows:
        start = datetime.strptime(str(row["startDate"]), "%Y%m%d").date()
        end = datetime.strptime(str(row["endDate"]), "%Y%m%d").date()
        bestehend = await db.get(Schuljahr, row["id"])
        if bestehend is None:
            db.add(Schuljahr(id=row["id"], name=row["name"], start_datum=start, end_datum=end))
        else:
            bestehend.name = row["name"]
            bestehend.start_datum = start
            bestehend.end_datum = end
    await db.flush()

    try:
        aktuell = await client.call("getCurrentSchoolyear", {})
    except WebUntisError as exc:
        logger.warning(
            "getCurrentSchoolyear fehlgeschlagen, kein aktives Schuljahr in WebUntis "
            "konfiguriert; verwende juengstes bereits gestartetes Schuljahr als Fallback: %s",
            exc,
        )
        return await _juengstes_bereits_gestartetes_schuljahr(db)

    schuljahr = await db.get(Schuljahr, aktuell["id"])
    if schuljahr is None:
        logger.warning(
            "getCurrentSchoolyear lieferte schoolyearId %s, die nicht im gerade "
            "aktualisierten Schuljahr-Cache enthalten ist; verwende juengstes "
            "bereits gestartetes Schuljahr als Fallback",
            aktuell.get("id"),
        )
        return await _juengstes_bereits_gestartetes_schuljahr(db)
    return schuljahr


async def run_sync_once(db: AsyncSession) -> None:
    if _sync_lock.locked():
        raise SyncAlreadyRunningError("Ein Sync-Lauf ist bereits aktiv.")
    async with _sync_lock:
        await _run_sync_once_impl(db)


async def _run_sync_once_impl(db: AsyncSession) -> None:
    async with WebUntisClient(settings) as client:
        einstellung = await get_or_create_einstellung(db)

        aktuelles_schuljahr = await resolve_aktuelles_schuljahr(client, db)
        einstellung.aktuelles_schuljahr_id = aktuelles_schuljahr.id
        if aktuelles_schuljahr.start_datum != einstellung.schuljahr_start_cache:
            einstellung.schuljahr_start_cache = aktuelles_schuljahr.start_datum

        await sync_abteilungen(client, db)
        await sync_klassen(client, db, schoolyear_id=aktuelles_schuljahr.id)
        await sync_bereiche(db)
        await sync_kategorien(client, db)
        await sync_stundenraster(client, db)
        await import_schueler(db)

        heute = datetime.now(timezone.utc).date()
        von, bis = _fehlzeiten_zeitraum(einstellung, heute, aktuelles_schuljahr.end_datum)
        await sync_fehlzeiten(client, db, von, bis)
        await sync_klassenbuch(client, db, von, bis)

        await pruefe_schwellwerte(db, heute, einstellung, settings)

        einstellung.letzter_sync_am = datetime.now(timezone.utc)
        if not einstellung.initialer_import_abgeschlossen:
            einstellung.initialer_import_abgeschlossen = True
        await db.commit()


async def run_full_sync(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Orchestriert einen vollstaendigen WebUntis-Sync-Lauf mit Retry (TECH-SPEC.md Abschnitt 1.3b).

    Oeffnet pro Versuch eine frische DB-Session statt eine einzige Session ueber
    die komplette Retry-Wartezeit (bis zu ~2h bei Default-Settings) offenzuhalten.
    """
    max_attempts = settings.webuntis_sync_retry_max_attempts
    delay_seconds = settings.webuntis_sync_retry_delay_minutes * 60

    for attempt in range(1, max_attempts + 1):
        try:
            async with session_factory() as db:
                await run_sync_once(db)
            return
        except (WebUntisError, OSError, ValueError) as exc:
            logger.warning("Sync-Lauf fehlgeschlagen (Versuch %d/%d): %s", attempt, max_attempts, exc)
            if attempt == max_attempts:
                logger.error("Sync-Lauf endgueltig abgebrochen nach %d Versuchen", max_attempts)
                return
            await asyncio.sleep(delay_seconds)
