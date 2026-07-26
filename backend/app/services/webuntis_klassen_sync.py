from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.services.nutzer_klasse_sync import seed_nutzer_klasse_from_webuntis


async def sync_klassen(client: WebUntisClient, db: AsyncSession) -> None:
    """getKlassen -> klasse (Upsert nach webuntis_id), danach nutzer_klasse-Seeding (TECH-SPEC.md Abschnitt 1.2)."""
    rows = await client.call("getKlassen", {})

    existing = (await db.execute(select(Klasse))).scalars().all()
    by_webuntis_id = {klasse.webuntis_id: klasse for klasse in existing}

    abteilung_result = await db.execute(select(Abteilung))
    abteilung_id_by_webuntis_id = {a.webuntis_id: a.id for a in abteilung_result.scalars().all()}

    for row in rows:
        klasse = by_webuntis_id.get(row["id"])
        if klasse is None:
            klasse = Klasse(webuntis_id=row["id"], name=row["name"])
            db.add(klasse)
        else:
            klasse.name = row["name"]
        klasse.abteilung_id = abteilung_id_by_webuntis_id.get(row.get("did"))
        klasse.webuntis_teacher1_id = row.get("teacher1")
        klasse.webuntis_teacher2_id = row.get("teacher2")

    await db.flush()
    await seed_nutzer_klasse_from_webuntis(db)
