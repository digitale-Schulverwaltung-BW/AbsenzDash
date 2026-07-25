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


async def sync_fehlzeiten(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None:
    """getTimetableWithAbsences -> fehlzeit (TECH-SPEC.md Abschnitt 1.2, 1.3).

    schueler_id wird über Schueler.externe_id aufgelöst (identisch mit studentId-UUID) -
    kein Namensabgleich noetig, siehe TECH-SPEC.md Abschnitt 1.3.
    """
    result = await client.call(
        "getTimetableWithAbsences",
        {"options": {"startDate": _to_webuntis_date(von), "endDate": _to_webuntis_date(bis)}},
    )
    entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result

    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())

    existing = (await db.execute(select(Fehlzeit))).scalars().all()
    by_key = {(f.schueler_id, f.datum, f.start_zeit, f.end_zeit, f.typ): f for f in existing}

    for row in entries or []:
        if row.get("invalid"):
            continue

        schueler_id = schueler_id_by_externe_id.get(row["studentId"])
        if schueler_id is None:
            logger.warning("Fehlzeiten-Sync: unbekannte externe_id=%s, uebersprungen", row["studentId"])
            continue

        typ = "stunde" if row.get("subjectId") else "tag"
        datum = _from_webuntis_date(row["date"])
        start_zeit = row["startTime"]
        end_zeit = row["endTime"]

        key = (schueler_id, datum, start_zeit, end_zeit, typ)
        fehlzeit = by_key.get(key)
        if fehlzeit is None:
            fehlzeit = Fehlzeit(
                schueler_id=schueler_id, datum=datum, start_zeit=start_zeit, end_zeit=end_zeit, typ=typ
            )
            db.add(fehlzeit)
            by_key[key] = fehlzeit

        fehlzeit.fach = row.get("subjectId") or None
        fehlzeit.grund_text = row.get("absenceReason") or None
        fehlzeit.excuse_status_id = excuse_status_id_by_name.get(row.get("excuseStatus"))
        fehlzeit.invalid = False

    await db.commit()
