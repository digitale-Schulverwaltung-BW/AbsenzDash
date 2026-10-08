from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import ist_unique_violation
from app.integrations.webuntis_client import WebUntisClient
from app.integrations.webuntis_duty_client import StudentDutyClient
from app.models.audit_log import AuditLog
from app.models.klassendienst_typ import KlassendienstTyp
from app.schemas.admin import (
    KlassendienstTypIn,
    KlassendienstTypOut,
    WebUntisDienstOptionenOut,
    WebUntisDienstOptionOut,
)

logger = logging.getLogger(__name__)

MAX_BEZEICHNUNG = 100
MAX_KUERZEL = 10
MAX_BESCHREIBUNG = 300

HINWEIS_OPTIONEN_NICHT_VERFUEGBAR = (
    "Die Dienst-Liste konnte nicht aus WebUntis geladen werden. Dienst-ID und Bezeichnung bitte von Hand eintragen."
)
HINWEIS_OPTIONEN_LEER = (
    "WebUntis lieferte keine erkennbare Dienst-Liste. Dienst-ID und Bezeichnung bitte von Hand eintragen."
)


def _typ_out(typ: KlassendienstTyp) -> KlassendienstTypOut:
    return KlassendienstTypOut(
        id=typ.id,
        webuntis_dienst_id=typ.webuntis_dienst_id,
        bezeichnung=typ.bezeichnung,
        kuerzel=typ.kuerzel,
        beschreibung=typ.beschreibung,
        aktiv=typ.aktiv,
    )


async def list_klassendienst_typen(db: AsyncSession) -> list[KlassendienstTypOut]:
    result = await db.execute(select(KlassendienstTyp).order_by(KlassendienstTyp.webuntis_dienst_id, KlassendienstTyp.id))
    return [_typ_out(t) for t in result.scalars().all()]


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def _validate_payload(payload: list[KlassendienstTypIn]) -> None:
    seen_ids: set[int] = set()
    seen_dienst_ids: set[int] = set()
    for typ in payload:
        if typ.id is not None:
            if typ.id in seen_ids:
                raise _unprocessable(f"Duplicate id in payload: {typ.id}")
            seen_ids.add(typ.id)
        if typ.webuntis_dienst_id in seen_dienst_ids:
            raise _unprocessable(f"Duplicate webuntis_dienst_id: {typ.webuntis_dienst_id}")
        seen_dienst_ids.add(typ.webuntis_dienst_id)
        if typ.webuntis_dienst_id < 1:
            raise _unprocessable("webuntis_dienst_id must be a positive number")
        if not typ.bezeichnung.strip():
            raise _unprocessable("bezeichnung must not be empty")
        if len(typ.bezeichnung.strip()) > MAX_BEZEICHNUNG:
            raise _unprocessable(f"bezeichnung must not be longer than {MAX_BEZEICHNUNG} characters")
        if not typ.kuerzel.strip():
            raise _unprocessable("kuerzel must not be empty")
        if len(typ.kuerzel.strip()) > MAX_KUERZEL:
            raise _unprocessable(f"kuerzel must not be longer than {MAX_KUERZEL} characters")
        if typ.beschreibung is not None and len(typ.beschreibung.strip()) > MAX_BESCHREIBUNG:
            raise _unprocessable(f"beschreibung must not be longer than {MAX_BESCHREIBUNG} characters")


def _normalisierte_beschreibung(beschreibung: str | None) -> str | None:
    if beschreibung is None:
        return None
    text = beschreibung.strip()
    return text or None


async def replace_klassendienst_typen(
    db: AsyncSession, payload: list[KlassendienstTypIn], nutzer_id: int
) -> list[KlassendienstTypOut]:
    """Ersetzt die Liste im Stil von measure-types: Eintraege mit id werden aktualisiert, ohne id neu
    angelegt, im Payload fehlende werden GELOESCHT. Anders als bei Massnahmen-Typen haengt an einem
    Klassendienst-Typ keine manuell erfasste Arbeit, nur importierte Anzeigedaten: die zugehoerigen
    schueler_klassendienst-Zeilen verschwinden per ON DELETE CASCADE. Zum voruebergehenden Ausblenden
    ohne Datenverlust dient aktiv=false."""
    _validate_payload(payload)

    existing_by_id = {t.id: t for t in (await db.execute(select(KlassendienstTyp))).scalars().all()}
    for typ_in in payload:
        if typ_in.id is not None and typ_in.id not in existing_by_id:
            raise _unprocessable(f"Unknown klassendienst type id: {typ_in.id}")

    payload_ids = {t.id for t in payload if t.id is not None}
    removed_ids = [tid for tid in existing_by_id if tid not in payload_ids]
    removed_dienst_ids = sorted(existing_by_id[tid].webuntis_dienst_id for tid in removed_ids)

    try:
        for typ_id in removed_ids:
            await db.delete(existing_by_id[typ_id])
        await db.flush()  # Loeschungen vor Inserts, damit eine wiederverwendete webuntis_dienst_id nicht kollidiert

        for typ_in in payload:
            werte = {
                "webuntis_dienst_id": typ_in.webuntis_dienst_id,
                "bezeichnung": typ_in.bezeichnung.strip(),
                "kuerzel": typ_in.kuerzel.strip(),
                "beschreibung": _normalisierte_beschreibung(typ_in.beschreibung),
                "aktiv": typ_in.aktiv,
            }
            if typ_in.id is not None:
                typ = existing_by_id[typ_in.id]
                for feld, wert in werte.items():
                    setattr(typ, feld, wert)
            else:
                db.add(KlassendienstTyp(**werte))

        db.add(
            AuditLog(
                user_id=nutzer_id,
                aktion="admin_klassendienst_typen_updated",
                resource_typ="klassendienst_typ",
                details={"anzahl_typen": len(payload), "entfernte_dienst_ids": removed_dienst_ids},
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ist_unique_violation(exc):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Dienst-ID bereits vergeben — jede WebUntis-Dienst-ID darf nur einmal konfiguriert werden.",
            )
        raise

    return await list_klassendienst_typen(db)


async def load_webuntis_optionen() -> WebUntisDienstOptionenOut:
    """Vorschlagsliste aus `getStudentDutyOptions`. Wirft nie: bei jedem Fehler (Login, 403, Netzwerk,
    unbekannte Antwortform) kommt eine leere Liste mit Hinweistext zurueck."""
    try:
        async with WebUntisClient(settings) as client:
            options = await StudentDutyClient(client, settings).get_duty_options()
    except Exception as exc:  # noqa: BLE001 - Vorschlagsliste ist optional, nie ein 500
        logger.warning("getStudentDutyOptions fehlgeschlagen (%s)", type(exc).__name__)
        return WebUntisDienstOptionenOut(optionen=[], hinweis=HINWEIS_OPTIONEN_NICHT_VERFUEGBAR)
    if not options:
        return WebUntisDienstOptionenOut(optionen=[], hinweis=HINWEIS_OPTIONEN_LEER)
    return WebUntisDienstOptionenOut(
        optionen=[WebUntisDienstOptionOut(id=o.id, bezeichnung=o.bezeichnung) for o in options], hinweis=None
    )
