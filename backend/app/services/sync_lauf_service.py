"""Verlauf der Sync-Laeufe (Tabelle sync_lauf).

Alle Schreibzugriffe laufen in EIGENEN kurzen Sessions und committen sofort, damit Fortschritt und
Fehler unabhaengig vom Commit/Rollback des Sync-Laufs selbst sichtbar sind."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import database
from app.models.sync_lauf import SyncLauf
from app.schemas.admin import SyncAktuellerLaufOut, SyncLetzterLaufOut, SyncStatusOut

logger = logging.getLogger(__name__)

MAX_VERLAUF = 200
VERALTET_NACH = timedelta(hours=6)
FEHLER_KURZ_MAX = 300

_GEHEIMNIS_PAIR = re.compile(
    r"(?i)\b([\w-]*(?:token|secret|session|sid|cookie|csrf|passw\w*|pwd|auth\w*|api[_-]?key|key))"
    r"(\s*[=:]\s*)(?:bearer\s+|basic\s+)?[^\s;,&\"']+"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_URL = re.compile(r"(https?://[^\s?#\"']+)(?:[?#][^\s\"']*)?")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LANGE_KETTE = re.compile(r"\b[A-Za-z0-9_\-+/=.]{20,}\b")


def bereinige_meldung(meldung: str) -> str:
    """Entfernt erkennbare Geheimnisse (Token/Cookie/CSRF/Passwort-Paare, Bearer-Header, URL-Query,
    E-Mail-Adressen, lange Zufallsketten) und beschraenkt auf die erste Zeile. Namen von Personen
    lassen sich nicht zuverlaessig erkennen -- daher werden Datenbankfehler (siehe fehler_kurz_aus)
    gar nicht mit Meldung gespeichert."""
    erste_zeile = meldung.strip().splitlines()[0] if meldung.strip() else ""
    text = _URL.sub(lambda m: m.group(1), erste_zeile)
    text = _GEHEIMNIS_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}[entfernt]", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} [entfernt]", text)
    text = _EMAIL.sub("[E-Mail]", text)
    text = _LANGE_KETTE.sub("[entfernt]", text)
    return text


def fehler_kurz_aus(exc: BaseException) -> str:
    """'Klasse: bereinigte Meldung', hoechstens 300 Zeichen. SQLAlchemy-Fehler tragen SQL-Parameter
    (potenziell Schuelerdaten) in der Meldung und werden deshalb nur mit Klassennamen gespeichert."""
    name = type(exc).__name__
    if isinstance(exc, SQLAlchemyError):
        orig = getattr(exc, "orig", None)
        return f"{name} ({type(orig).__name__})"[:FEHLER_KURZ_MAX] if orig is not None else name
    meldung = bereinige_meldung(str(exc))
    text = f"{name}: {meldung}" if meldung else name
    return text[:FEHLER_KURZ_MAX]


async def lauf_anlegen(ausgeloest_von: str, nutzer_id: int | None) -> int:
    async with database.async_session_factory() as db:
        lauf = SyncLauf(
            gestartet_am=datetime.now(timezone.utc),
            status="laufend",
            ausgeloest_von=ausgeloest_von,
            nutzer_id=nutzer_id,
        )
        db.add(lauf)
        await db.flush()
        lauf_id = lauf.id
        # Verlauf auf die letzten MAX_VERLAUF Zeilen kuerzen
        behalten = select(SyncLauf.id).order_by(SyncLauf.id.desc()).limit(MAX_VERLAUF)
        await db.execute(delete(SyncLauf).where(SyncLauf.id.not_in(behalten)))
        await db.commit()
        return lauf_id


async def phase_setzen(lauf_id: int, phase: str) -> None:
    async with database.async_session_factory() as db:
        await db.execute(update(SyncLauf).where(SyncLauf.id == lauf_id).values(phase=phase[:50]))
        await db.commit()


async def lauf_abschliessen(lauf_id: int, status: str, fehler_kurz: str | None = None) -> None:
    async with database.async_session_factory() as db:
        await db.execute(
            update(SyncLauf)
            .where(SyncLauf.id == lauf_id)
            .values(
                status=status,
                beendet_am=datetime.now(timezone.utc),
                fehler_kurz=fehler_kurz[:FEHLER_KURZ_MAX] if fehler_kurz else None,
            )
        )
        await db.commit()


async def verwaiste_laeufe_abbrechen() -> int:
    """Beim Start des Backends: Laeufe, die noch 'laufend' sind, gehoerten einem beendeten Prozess."""
    async with database.async_session_factory() as db:
        result = await db.execute(
            update(SyncLauf)
            .where(SyncLauf.status == "laufend")
            .values(status="abgebrochen", beendet_am=datetime.now(timezone.utc))
        )
        await db.commit()
        return result.rowcount or 0


async def get_sync_status(db: AsyncSession) -> SyncStatusOut:
    grenze = datetime.now(timezone.utc) - VERALTET_NACH
    zeilen = (await db.execute(select(SyncLauf).order_by(SyncLauf.id.desc()).limit(50))).scalars().all()

    def aktiv(z: SyncLauf) -> bool:
        return z.status == "laufend" and z.gestartet_am >= grenze

    aktueller = next((z for z in zeilen if aktiv(z)), None)
    letzter = next((z for z in zeilen if not aktiv(z)), None)
    return SyncStatusOut(
        laeuft=aktueller is not None,
        aktueller_lauf=(
            SyncAktuellerLaufOut(
                id=aktueller.id,
                gestartet_am=aktueller.gestartet_am,
                phase=aktueller.phase,
                ausgeloest_von=aktueller.ausgeloest_von,
            )
            if aktueller
            else None
        ),
        letzter_lauf=(
            SyncLetzterLaufOut(
                id=letzter.id,
                status="abgebrochen" if letzter.status == "laufend" else letzter.status,
                gestartet_am=letzter.gestartet_am,
                beendet_am=letzter.beendet_am,
                ausgeloest_von=letzter.ausgeloest_von,
                fehler_kurz=letzter.fehler_kurz,
            )
            if letzter
            else None
        ),
    )
