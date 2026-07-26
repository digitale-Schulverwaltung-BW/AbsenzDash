from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.abteilung import Abteilung


async def sync_abteilungen(client: WebUntisClient, db: AsyncSession) -> None:
    """getDepartments -> abteilung (muss vor sync_klassen laufen, da klasse.abteilung_id referenziert)."""
    rows = await client.call("getDepartments", {})

    existing = (await db.execute(select(Abteilung))).scalars().all()
    by_webuntis_id = {abteilung.webuntis_id: abteilung for abteilung in existing}

    for row in rows:
        abteilung = by_webuntis_id.get(row["id"])
        if abteilung is None:
            abteilung = Abteilung(webuntis_id=row["id"], name=row["name"])
            db.add(abteilung)
        else:
            abteilung.name = row["name"]
        abteilung.long_name = row.get("longName")

    await db.commit()
