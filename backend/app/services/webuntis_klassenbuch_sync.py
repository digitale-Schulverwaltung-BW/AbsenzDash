from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.classreg_category import ClassregCategory
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler

logger = logging.getLogger(__name__)


def _to_webuntis_date(value: date) -> int:
    return int(value.strftime("%Y%m%d"))


def _from_webuntis_date(value: int) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


async def sync_klassenbuch(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None:
    """getClassregEvents -> klassenbuch_eintrag (TECH-SPEC.md Abschnitt 1.2, 1.3)."""
    rows = await client.call(
        "getClassregEvents", {"startDate": _to_webuntis_date(von), "endDate": _to_webuntis_date(bis)}
    )

    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    kategorie_id_by_webuntis_id = dict((await db.execute(select(ClassregCategory.webuntis_id, ClassregCategory.id))).all())

    existing = (await db.execute(select(KlassenbuchEintrag))).scalars().all()
    by_webuntis_id = {e.webuntis_id: e for e in existing}

    for row in rows or []:
        schueler_id = schueler_id_by_externe_id.get(row["studentid"])
        if schueler_id is None:
            logger.warning("Klassenbuch-Sync: unbekannte externe_id=%s, uebersprungen", row["studentid"])
            continue

        kategorie_id = kategorie_id_by_webuntis_id.get(row.get("categoryId"))
        if kategorie_id is None:
            logger.warning("Klassenbuch-Sync: unbekannte categoryId=%s, uebersprungen", row.get("categoryId"))
            continue

        eintrag = by_webuntis_id.get(row["eventId"])
        if eintrag is None:
            eintrag = KlassenbuchEintrag(
                webuntis_id=row["eventId"], schueler_id=schueler_id, kategorie_id=kategorie_id
            )
            db.add(eintrag)
            by_webuntis_id[row["eventId"]] = eintrag
        else:
            eintrag.schueler_id = schueler_id
            eintrag.kategorie_id = kategorie_id

        eintrag.datum = _from_webuntis_date(row["date"])
        eintrag.text = row.get("text") or None
        eintrag.lesson_id = row.get("lessonId")
        eintrag.erstellt_von_teacher_id = (row.get("createTeacher") or {}).get("id")
        eintrag.geaendert_von_teacher_id = (row.get("updateTeacher") or {}).get("id")

    await db.commit()
