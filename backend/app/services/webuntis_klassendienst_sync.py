"""Import der WebUntis-Klassendienste (Entschuldigungspflicht, Attestpflicht, ...) als
schreibgeschuetzte Anzeige, siehe docs/superpowers/plans/2026-10-08-klassendienste-anzeige.md.

Datenschutz: Schueler-Namen aus getStudents/studentDTO werden weder gespeichert noch geloggt.
Zuordnung nur ueber studentDTO.id -> getStudents[].key -> Schueler.externe_id (kein Namens-Fallback).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_duty_client import DutyServiceError
from app.models.klasse import Klasse
from app.models.klassendienst_typ import KlassendienstTyp
from app.models.schueler import Schueler
from app.models.schueler_klassendienst import SchuelerKlassendienst

logger = logging.getLogger(__name__)

# Nach so vielen Klassenfehlern in Folge (ohne zwischenzeitlichen Erfolg) wird der Lauf abgebrochen:
# vermutlich ist der interne Dienst grundsaetzlich nicht erreichbar/geaendert.
MAX_AUFEINANDERFOLGENDE_FEHLER = 5


class DutyClientProtocol(Protocol):
    async def get_students(self) -> list[dict[str, Any]]: ...

    async def get_scheduler_data(self, webuntis_klassen_id: int, dienst_id: int) -> dict[str, Any]: ...


@dataclass
class KlassendienstSyncErgebnis:
    uebersprungen: bool = False  # keine aktiven Typen -> Feature aus
    klassen_ok: int = 0
    klassen_fehler: int = 0
    nicht_zuordenbar: int = 0
    zeilen: int = 0


def _parse_wochen_id(value: Any) -> date | None:
    try:
        return datetime.strptime(str(int(value)), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def wochen_zu_zeitraeume(week_ids: list[Any], end_by_week_id: dict[int, Any] | None = None) -> list[tuple[date, date]]:
    """Wochen (Montag als YYYYMMDD) -> zusammenhaengende Zeitraeume (von = Montag der ersten Woche,
    bis = endDate der letzten Woche des Blocks, sonst Montag + 6 Tage). Aufeinanderfolgende Montage
    (7 Tage Abstand) werden verschmolzen, eine Luecke beginnt einen neuen Zeitraum. Eingabe darf
    unsortiert sein und Duplikate/ungueltige Werte enthalten."""
    end_by_week_id = end_by_week_id or {}
    wochen: dict[date, date] = {}
    for raw in week_ids:
        montag = _parse_wochen_id(raw)
        if montag is None:
            continue
        ende = _parse_wochen_id(end_by_week_id.get(int(raw))) if end_by_week_id.get(int(raw)) is not None else None
        wochen[montag] = ende if ende is not None and ende >= montag else montag + timedelta(days=6)

    zeitraeume: list[tuple[date, date]] = []
    block_von: date | None = None
    block_bis: date | None = None
    letzter_montag: date | None = None
    for montag in sorted(wochen):
        if letzter_montag is not None and montag - letzter_montag == timedelta(days=7):
            block_bis = wochen[montag]
        else:
            if block_von is not None and block_bis is not None:
                zeitraeume.append((block_von, block_bis))
            block_von, block_bis = montag, wochen[montag]
        letzter_montag = montag
    if block_von is not None and block_bis is not None:
        zeitraeume.append((block_von, block_bis))
    return zeitraeume


def _end_by_week_id(matrix: dict[str, Any]) -> dict[int, Any]:
    result: dict[int, Any] = {}
    for column in matrix.get("columns") or []:
        if isinstance(column, dict):
            try:
                result[int(column["id"])] = column.get("endDate")
            except (KeyError, TypeError, ValueError):
                continue
    return result


async def _schueler_key_by_webuntis_id(client: DutyClientProtocol) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for student in await client.get_students():
        if not isinstance(student, dict):
            continue
        key = student.get("key")
        try:
            student_id = int(student["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(key, str) and key.strip():
            mapping[student_id] = key.strip()
    return mapping


async def _sync_klasse_typ(
    db: AsyncSession,
    klasse: Klasse,
    typ: KlassendienstTyp,
    matrix: dict[str, Any],
    key_by_wu_id: dict[int, str],
    schueler_id_by_extern: dict[str, int],
) -> tuple[int, int]:
    """Schreibt die Zeitraeume einer (Klasse, Typ) neu. Rueckgabe: (nicht zuordenbare Schueler,
    geschriebene Zeilen). Der Aufrufer kapselt den Aufruf in einer Savepoint-Transaktion."""
    end_by_week = _end_by_week_id(matrix)
    neue_zeilen: list[SchuelerKlassendienst] = []
    nicht_zuordenbar = 0
    zugeordnet: set[int] = set()
    for row in matrix.get("rows") or []:
        if not isinstance(row, dict):
            continue
        relations = row.get("relations") or []
        dto = row.get("studentDTO")
        if not relations or not isinstance(dto, dict):
            continue
        try:
            wu_id = int(dto["id"])
        except (KeyError, TypeError, ValueError):
            nicht_zuordenbar += 1
            continue
        schueler_id = None
        key = key_by_wu_id.get(wu_id)
        if key is not None:
            schueler_id = schueler_id_by_extern.get(key)
        if schueler_id is None:
            nicht_zuordenbar += 1
            continue
        if schueler_id in zugeordnet:
            continue
        zugeordnet.add(schueler_id)
        for von, bis in wochen_zu_zeitraeume(list(relations), end_by_week):
            neue_zeilen.append(
                SchuelerKlassendienst(schueler_id=schueler_id, klassendienst_typ_id=typ.id, von=von, bis=bis)
            )

    # Alte Zeilen aller Schueler der Klasse (laut DB) und aller neu zugeordneten ersetzen.
    klassen_schueler = set(
        (await db.execute(select(Schueler.id).where(Schueler.klasse_id == klasse.id))).scalars().all()
    )
    await db.execute(
        delete(SchuelerKlassendienst).where(
            SchuelerKlassendienst.klassendienst_typ_id == typ.id,
            SchuelerKlassendienst.schueler_id.in_(klassen_schueler | zugeordnet),
        )
    )
    db.add_all(neue_zeilen)
    await db.flush()
    return nicht_zuordenbar, len(neue_zeilen)


async def sync_klassendienste(
    client: DutyClientProtocol, db: AsyncSession, heute: date, schuljahr_id: int | None = None
) -> KlassendienstSyncErgebnis:
    """Importiert alle aktiven Klassendienst-Typen fuer alle Klassen des Schuljahres (Default: das
    juengste Schuljahr mit Klassen). Ohne aktive Typen passiert nichts. Fehler einer einzelnen
    Klasse werden isoliert (alte Zeilen bleiben, Warnung am Ende). Fehler, die den ganzen Lauf
    betreffen (getStudents, MAX_AUFEINANDERFOLGENDE_FEHLER Klassenfehler in Folge), werden geworfen."""
    ergebnis = KlassendienstSyncErgebnis()
    typen = (
        await db.execute(select(KlassendienstTyp).where(KlassendienstTyp.aktiv.is_(True)).order_by(KlassendienstTyp.id))
    ).scalars().all()
    if not typen:
        ergebnis.uebersprungen = True
        return ergebnis

    klassen_query = select(Klasse).order_by(Klasse.id)
    if schuljahr_id is not None:
        klassen_query = klassen_query.where(Klasse.schuljahr_id == schuljahr_id)
    klassen = (await db.execute(klassen_query)).scalars().all()

    key_by_wu_id = await _schueler_key_by_webuntis_id(client)
    schueler_id_by_extern = {
        externe_id: sid for sid, externe_id in (await db.execute(select(Schueler.id, Schueler.externe_id))).all()
    }

    fehler_in_folge = 0
    for klasse in klassen:
        for typ in typen:
            try:
                data = await client.get_scheduler_data(klasse.webuntis_id, typ.webuntis_dienst_id)
                matrix = data["matrix"]
                async with db.begin_nested():
                    nicht_zuordenbar, zeilen = await _sync_klasse_typ(
                        db, klasse, typ, matrix, key_by_wu_id, schueler_id_by_extern
                    )
            except (DutyServiceError, KeyError, TypeError, ValueError) as exc:
                ergebnis.klassen_fehler += 1
                fehler_in_folge += 1
                logger.warning(
                    "Klassendienst-Import fuer Klasse %s, Dienst %s uebersprungen (%s); alte Daten bleiben",
                    klasse.name,
                    typ.webuntis_dienst_id,
                    exc if isinstance(exc, DutyServiceError) else type(exc).__name__,
                )
                if fehler_in_folge >= MAX_AUFEINANDERFOLGENDE_FEHLER:
                    raise DutyServiceError(
                        "aborted", f"{fehler_in_folge} Klassenfehler in Folge, Klassendienst-Import abgebrochen"
                    ) from None
                continue
            fehler_in_folge = 0
            ergebnis.klassen_ok += 1
            ergebnis.zeilen += zeilen
            ergebnis.nicht_zuordenbar += nicht_zuordenbar
            if nicht_zuordenbar:
                logger.warning(
                    "Klassendienst-Import: %d Schueler in Klasse %s (Dienst %s) nicht zuordenbar und uebersprungen",
                    nicht_zuordenbar,
                    klasse.name,
                    typ.webuntis_dienst_id,
                )
    if ergebnis.klassen_fehler:
        logger.warning(
            "Klassendienst-Import: %d von %d Klasse/Dienst-Kombinationen fehlgeschlagen",
            ergebnis.klassen_fehler,
            ergebnis.klassen_fehler + ergebnis.klassen_ok,
        )
    return ergebnis
