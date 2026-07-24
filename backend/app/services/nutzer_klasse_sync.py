from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse


async def seed_nutzer_klasse_from_webuntis(db: AsyncSession) -> None:
    """Setzt alle 'webuntis_seed'-Zuordnungen aus Klasse.webuntis_teacher1_id/2 neu auf.

    Manuell gepflegte Zuordnungen (quelle='manuell') bleiben unangetastet
    (TECH-SPEC.md Abschnitt 2.1).
    """
    await db.execute(delete(NutzerKlasse).where(NutzerKlasse.quelle == "webuntis_seed"))

    klassen = (await db.execute(select(Klasse))).scalars().all()
    nutzer_result = await db.execute(select(Nutzer).where(Nutzer.webuntis_teacher_id.is_not(None)))
    nutzer_by_teacher_id = {nutzer.webuntis_teacher_id: nutzer for nutzer in nutzer_result.scalars()}

    for klasse in klassen:
        nutzer_ids: set[int] = set()
        for teacher_id in (klasse.webuntis_teacher1_id, klasse.webuntis_teacher2_id):
            if teacher_id is None:
                continue
            nutzer = nutzer_by_teacher_id.get(teacher_id)
            if nutzer is None:
                continue
            nutzer_ids.add(nutzer.id)
        for nutzer_id in nutzer_ids:
            db.add(NutzerKlasse(nutzer_id=nutzer_id, klasse_id=klasse.id, quelle="webuntis_seed"))

    await db.commit()
