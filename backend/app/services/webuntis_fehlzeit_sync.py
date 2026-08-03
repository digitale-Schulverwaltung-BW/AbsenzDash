from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler

logger = logging.getLogger(__name__)


def _to_webuntis_date(value: date) -> int:
    return int(value.strftime("%Y%m%d"))


def _from_webuntis_date(value: int) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


def _zaehlt_als_entschuldigt(excuse_status_id: int | None, zaehlt_als_entschuldigt_by_id: dict[int, bool]) -> bool:
    if excuse_status_id is None:
        return False
    return zaehlt_als_entschuldigt_by_id.get(excuse_status_id, False)


def _merge_tag_gruppe(
    rows: list[dict],
    excuse_status_id_by_name: dict[str, int],
    zaehlt_als_entschuldigt_by_id: dict[int, bool],
) -> tuple[int | None, str | None]:
    """Fasst mehrere WebUntis-Perioden-Zeilen desselben Schuelers/Tages zu den Feldern
    einer einzigen Tages-Zeile zusammen (siehe
    docs/superpowers/specs/2026-07-28-fehltag-merge-fix-design.md).

    excuse_status_id: "unentschuldigt gewinnt" - zaehlt mindestens eine Zeile nicht als
    entschuldigt (aufgeloester Status mit zaehlt_als_entschuldigt=False, oder ein nicht
    aufloesbarer Status), wird deren excuse_status_id uebernommen (bzw. None, falls diese
    Zeile selbst keinen aufgeloesten Status hatte). Nur wenn alle Zeilen entschuldigt sind,
    bleibt ein entschuldigter Status erhalten (die erste in Eintragsreihenfolge).

    grund_text: verschiedene, nicht-leere Freitexte werden mit "; " zusammengefuegt
    (Dopplungen entfernt, Reihenfolge des ersten Vorkommens).
    """
    excused_ids: list[int | None] = []
    unexcused_ids: list[int | None] = []
    gruende: list[str] = []

    for row in rows:
        excuse_status_id = excuse_status_id_by_name.get(row.get("excuseStatus"))
        if _zaehlt_als_entschuldigt(excuse_status_id, zaehlt_als_entschuldigt_by_id):
            excused_ids.append(excuse_status_id)
        else:
            unexcused_ids.append(excuse_status_id)

        grund = row.get("absenceReason") or None
        if grund and grund not in gruende:
            gruende.append(grund)

    if unexcused_ids:
        merged_excuse_status_id = unexcused_ids[0]
    elif excused_ids:
        merged_excuse_status_id = excused_ids[0]
    else:
        merged_excuse_status_id = None

    merged_grund_text = "; ".join(gruende) if gruende else None
    # Sicherheitsnetz: Fehlzeit.grund_text ist String(500); bei vielen Perioden mit
    # unterschiedlichen Freitexten kann der zusammengefuegte String die Spaltenlaenge
    # ueberschreiten und wuerde auf PostgreSQL StringDataRightTruncation ausloesen
    # (bricht den gesamten Sync-Commit ab). SQLite prueft die Laenge nicht, daher hier
    # explizit kappen statt sich auf die DB zu verlassen.
    if merged_grund_text is not None:
        merged_grund_text = merged_grund_text[:500]

    return merged_excuse_status_id, merged_grund_text


async def sync_fehlzeiten(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None:
    """getTimetableWithAbsences -> fehlzeit (TECH-SPEC.md Abschnitt 1.2, 1.3).

    schueler_id wird ueber Schueler.externe_id aufgeloest (identisch mit studentId-UUID) -
    kein Namensabgleich noetig, siehe TECH-SPEC.md Abschnitt 1.3.

    WebUntis liefert fuer ganztaegige Absenzen an dieser Schule mehrere Perioden-Zeilen
    ohne subjectId statt einer einzigen Ganztages-Zeile (siehe TECH-SPEC.md Abschnitt 1.2) -
    diese werden pro Schueler/Tag zu einer einzigen typ='tag'-Zeile zusammengefuehrt, bevor
    sie geschrieben werden (siehe
    docs/superpowers/specs/2026-07-28-fehltag-merge-fix-design.md). Zeilen mit subjectId
    (typ='stunde') bleiben unveraendert, eine Zeile pro Absenz.
    """
    result = await client.call(
        "getTimetableWithAbsences",
        {"options": {"startDate": _to_webuntis_date(von), "endDate": _to_webuntis_date(bis)}},
    )
    entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result

    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())

    # excuse_status wird nicht manuell vorgepflegt (siehe TECH-SPEC.md Abschnitt 1.2/5) - unbekannte
    # WebUntis-excuseStatus-Namen automatisch anlegen statt sie dauerhaft als NULL zu importieren.
    # zaehlt_als_entschuldigt=False als sicherer Default: das Flag ist ueber keine WebUntis-JSON-RPC-
    # Methode abrufbar, ein Mensch muss es im Admin-Bereich bestaetigen.
    unbekannte_namen = {
        row.get("excuseStatus")
        for row in entries or []
        if row.get("excuseStatus") and row.get("excuseStatus") not in excuse_status_id_by_name
    }
    for name in unbekannte_namen:
        db.add(ExcuseStatus(name=name, zaehlt_als_entschuldigt=False))
        logger.info(
            "Fehlzeiten-Sync: unbekannter excuseStatus '%s' automatisch angelegt (zaehlt_als_entschuldigt=False)",
            name,
        )
    if unbekannte_namen:
        await db.flush()
        excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())

    zaehlt_als_entschuldigt_by_id = dict(
        (await db.execute(select(ExcuseStatus.id, ExcuseStatus.zaehlt_als_entschuldigt))).all()
    )

    existing = (await db.execute(select(Fehlzeit))).scalars().all()
    by_key = {(f.schueler_id, f.datum, f.start_zeit, f.end_zeit, f.typ): f for f in existing}

    def _upsert(schueler_id: int, datum: date, start_zeit: int, end_zeit: int, typ: str) -> Fehlzeit:
        key = (schueler_id, datum, start_zeit, end_zeit, typ)
        fehlzeit = by_key.get(key)
        if fehlzeit is None:
            fehlzeit = Fehlzeit(
                schueler_id=schueler_id, datum=datum, start_zeit=start_zeit, end_zeit=end_zeit, typ=typ
            )
            db.add(fehlzeit)
            by_key[key] = fehlzeit
        return fehlzeit

    tag_gruppen: dict[tuple[int, date], list[dict]] = {}

    for row in entries or []:
        if row.get("invalid"):
            continue

        # WebUntis liefert fuer einmal "gepruefte" Tage die komplette Perioden-Liste des
        # Schuelers zurueck (Timetable + Absence-Check-Ergebnis in einem), nicht nur echte
        # Abwesenheiten -- unabhaengig von subjectId. Zeilen ohne jegliches Abwesenheits-Signal
        # sind normal besuchter Unterricht bzw. reine Zeitplan-Metadaten (z.B. "status:
        # irregular"), siehe TECH-SPEC.md Abschnitt 1.2 (Nachtrag 2026-08-03, live gegen die
        # reale Instanz verifiziert: nur ~5% aller Zeilen im Testzeitraum trugen ein Signal).
        if not (row.get("excuseStatus") or row.get("absenceReason") or row.get("absentTime")):
            continue

        schueler_id = schueler_id_by_externe_id.get(row["studentId"])
        if schueler_id is None:
            logger.warning("Fehlzeiten-Sync: unbekannte externe_id=%s, uebersprungen", row["studentId"])
            continue

        if row.get("subjectId"):
            fehlzeit = _upsert(
                schueler_id, _from_webuntis_date(row["date"]), row["startTime"], row["endTime"], "stunde"
            )
            fehlzeit.fach = row.get("subjectId") or None
            fehlzeit.grund_text = row.get("absenceReason") or None
            fehlzeit.excuse_status_id = excuse_status_id_by_name.get(row.get("excuseStatus"))
            fehlzeit.invalid = False
        else:
            datum = _from_webuntis_date(row["date"])
            tag_gruppen.setdefault((schueler_id, datum), []).append(row)

    for (schueler_id, datum), gruppe in tag_gruppen.items():
        merged_excuse_status_id, merged_grund_text = _merge_tag_gruppe(
            gruppe, excuse_status_id_by_name, zaehlt_als_entschuldigt_by_id
        )
        fehlzeit = _upsert(schueler_id, datum, 0, 2359, "tag")
        fehlzeit.fach = None
        fehlzeit.grund_text = merged_grund_text
        fehlzeit.excuse_status_id = merged_excuse_status_id
        fehlzeit.invalid = False

    await db.commit()
