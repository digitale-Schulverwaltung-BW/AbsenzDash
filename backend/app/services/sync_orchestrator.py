from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.einstellung import Einstellung
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
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
        # Liegt der letzte erfolgreiche Sync noch im vorherigen Schuljahr (Schuljahreswechsel seitdem),
        # faellt von sonst ins ALTE Schuljahr, waehrend bis (s.u.) bereits im neuen liegt -- getTimetable-
        # WithAbsences lehnt mit "startDate and endDate are not within a single school year" ab (WebUntis
        # -8507, Live-Fund 2026-09-18). schuljahr_start_cache ist zu diesem Zeitpunkt bereits auf den
        # Start des aktuellen Schuljahres aktualisiert (siehe _run_sync_once_impl), daher als Untergrenze
        # geeignet.
        if einstellung.schuljahr_start_cache is not None:
            von = max(von, einstellung.schuljahr_start_cache)
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


async def _snapshot_klassenzugehoerigkeit_bei_rollover(db: AsyncSession, neues_schuljahr_id: int) -> None:
    """Bei einem echten Schuljahreswechsel wird fuer ALLE Schueler (auch inaktive/ausgeschiedene)
    einmalig ein Snapshot ihrer zu diesem Zeitpunkt noch aktuellen schueler.klasse_id (i.d.R. noch
    die Klasse des alten Schuljahres, da import_schueler in diesem Sync-Lauf erst DANACH laeuft)
    fuers neue Schuljahr geschrieben, siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md. Ohne diesen Snapshot
    wuerden Schueler, die ausscheiden BEVOR sie je ein ASV-CSV-Update unter dem neuen Schuljahr
    bekommen (import_schueler deckt nur noch in der CSV gelistete Schueler ab), permanent ohne
    Historie-Eintrag fuer das neue Schuljahr bleiben. Bereits vorhandene Zeilen werden nicht
    ueberschrieben - der regulaere ASV-CSV-Import-Pfad, der im selben Sync-Lauf direkt danach
    laeuft, uebernimmt ab dann die laufende Pflege dieser Zeile fuer aktuell eingeschriebene
    Schueler."""
    bereits_erfasst = set(
        (
            await db.execute(
                select(SchuelerKlasseHistorie.schueler_id).where(
                    SchuelerKlasseHistorie.schuljahr_id == neues_schuljahr_id
                )
            )
        ).scalars().all()
    )
    alle_schueler = (await db.execute(select(Schueler.id, Schueler.klasse_id))).all()
    for schueler_id, klasse_id in alle_schueler:
        if schueler_id in bereits_erfasst:
            continue
        db.add(SchuelerKlasseHistorie(schueler_id=schueler_id, schuljahr_id=neues_schuljahr_id, klasse_id=klasse_id))
    await db.flush()


async def resolve_aktuelles_schuljahr(client: WebUntisClient, db: AsyncSession) -> Schuljahr:
    """Aktualisiert den schuljahr-Cache aus getSchoolyears und liefert das aktuell gueltige
    Schuljahr zurueck - datumsbasiert bevorzugt: die zuerst gepruefte Quelle ist eine gecachte
    Schuljahr-Zeile, deren [start_datum, end_datum] das heutige Kalenderdatum abdeckt. Das ist
    noetig, weil WebUntis' eigenes 'aktuelles Schuljahr' (getCurrentSchoolyear) waehrend der
    Uebergangsluecke zwischen zwei Schuljahren zeitweise dem Kalenderdatum hinterherhinkt (Live-
    Fund 2026-09-18, siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md)
    - ohne diesen Vorrang wuerde einstellung.aktuelles_schuljahr_id/schuljahr_start_cache zu spaet
    umkippen und das Eskalations-Zaehlfenster faelschlich noch Fehlzeiten des Vorjahres mitzaehlen.
    Nur wenn KEINE gecachte Zeile das heutige Datum abdeckt (echte Luecke: WebUntis hat das neue
    Schuljahr noch gar nicht angelegt), wird wie bisher auf getCurrentSchoolyear zurueckgegriffen,
    und bei dessen Fehlschlag/einer im Cache unbekannten ID auf das juengste bereits gestartete
    Schuljahr (siehe _juengstes_bereits_gestartetes_schuljahr)."""
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

    heute = datetime.now(timezone.utc).date()
    datumstreffer = await db.execute(
        select(Schuljahr)
        .where(Schuljahr.start_datum <= heute, Schuljahr.end_datum >= heute)
        .order_by(Schuljahr.end_datum.desc())
        .limit(1)
    )
    passendes_schuljahr = datumstreffer.scalar_one_or_none()
    if passendes_schuljahr is not None:
        return passendes_schuljahr

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
    einstellung = await get_or_create_einstellung(db)
    heute = datetime.now(timezone.utc).date()

    aktuelles_schuljahr: Schuljahr | None = None
    webuntis_fehler: Exception | None = None
    try:
        async with WebUntisClient(settings) as client:
            aktuelles_schuljahr = await resolve_aktuelles_schuljahr(client, db)
            vorheriges_schuljahr_id = einstellung.aktuelles_schuljahr_id
            einstellung.aktuelles_schuljahr_id = aktuelles_schuljahr.id
            if aktuelles_schuljahr.start_datum != einstellung.schuljahr_start_cache:
                einstellung.schuljahr_start_cache = aktuelles_schuljahr.start_datum

            ist_rollover = vorheriges_schuljahr_id is not None and vorheriges_schuljahr_id != aktuelles_schuljahr.id
            if ist_rollover:
                await _snapshot_klassenzugehoerigkeit_bei_rollover(db, aktuelles_schuljahr.id)

            await sync_abteilungen(client, db)
            await sync_klassen(client, db, schoolyear_id=aktuelles_schuljahr.id)
            await sync_bereiche(db, schuljahr_id=aktuelles_schuljahr.id)
            await sync_kategorien(client, db)
            await sync_stundenraster(client, db)
    except (WebUntisError, OSError, ValueError) as exc:
        # import_schueler haengt ausschliesslich an der lokalen ASV-CSV, nicht an WebUntis. Faellt ein
        # WebUntis-Schritt aus (Auth/Verbindung, sync_klassen, ...), muss schueler.aktiv trotzdem
        # aktualisiert werden, sonst bleiben Abgaenger waehrend eines WebUntis-Ausfalls im aktuellen
        # Schuljahr sichtbar (Live-Fund 2026-09-28). Fehler wird nach dem Import erneut geworfen,
        # damit Retry-Logik in run_full_sync unveraendert greift.
        logger.warning(
            "WebUntis-Teil des Sync-Laufs fehlgeschlagen (%s) -- ASV-CSV-Import laeuft trotzdem weiter, "
            "da er unabhaengig von WebUntis ist",
            exc,
        )
        webuntis_fehler = exc

    await import_schueler(db)

    if webuntis_fehler is not None:
        raise webuntis_fehler

    von, bis = _fehlzeiten_zeitraum(einstellung, heute, aktuelles_schuljahr.end_datum)
    async with WebUntisClient(settings) as client:
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
