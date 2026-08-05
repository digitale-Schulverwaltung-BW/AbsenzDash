"""Einmaliges Backfill-Skript: loest fehlzeit.fach fuer bereits bestehende Zeilen auf das
WebUntis-Fach-Kuerzel auf (dieselbe Logik, die der reguläre Sync seit dem Fach-Kurzname-Fix
fuer neu synchronisierte Zeilen bereits anwendet, siehe webuntis_fehlzeit_sync.py). Noetig,
weil der reguläre Sync inkrementell laeuft (nur seit dem letzten Lauf) und bereits gespeicherte
historische Zeilen sonst dauerhaft ihren rohen WebUntis-Langnamen behalten wuerden.

Nutzung (einmalig nach Deploy, z.B. im laufenden Backend-Container):
    python -m scripts.backfill_fach_kurznamen
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisClient
from app.models.fehlzeit import Fehlzeit
from app.services.webuntis_fehlzeit_sync import _build_kurzname_by_longname, _resolve_fach_kurzname

logger = logging.getLogger(__name__)


async def backfill_fach_kurznamen(client: WebUntisClient, db: AsyncSession) -> int:
    """Gibt die Anzahl tatsaechlich geaenderter Zeilen zurueck (fuer Logging/Tests)."""
    subjects = await client.call("getSubjects", {})
    kurzname_by_longname = _build_kurzname_by_longname(subjects or [])

    rows = (await db.execute(select(Fehlzeit).where(Fehlzeit.fach.is_not(None)))).scalars().all()
    updated = 0
    for row in rows:
        neuer_wert = _resolve_fach_kurzname(row.fach, kurzname_by_longname)
        if neuer_wert != row.fach:
            row.fach = neuer_wert
            updated += 1

    await db.commit()
    return updated


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with WebUntisClient(settings) as client:
        async with async_session_factory() as db:
            updated = await backfill_fach_kurznamen(client, db)
            logger.info("Fach-Kurzname-Backfill abgeschlossen: %s Zeile(n) aktualisiert", updated)


if __name__ == "__main__":
    asyncio.run(_main())
