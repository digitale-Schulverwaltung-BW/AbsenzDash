from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from scripts.backfill_fach_kurznamen import backfill_fach_kurznamen


@pytest.mark.asyncio
async def test_backfill_resolves_existing_fach_values_to_kurzname(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 2, 1), start_zeit=730, end_zeit=815, fach="Deutsch"),
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=815, fach="Bildende Kunst"),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 2, 3), start_zeit=0, end_zeit=2359, fach=None),
        ]
    )
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 61, "name": "D", "longName": "Deutsch"}]

    updated = await backfill_fach_kurznamen(client, db_session)

    client.call.assert_awaited_once_with("getSubjects", {})
    assert updated == 1  # nur die tatsaechlich geaenderte Zeile (Deutsch -> D) zaehlt
    rows = {f.datum.isoformat(): f.fach for f in (await db_session.execute(select(Fehlzeit))).scalars().all()}
    assert rows["2026-02-01"] == "D"
    assert rows["2026-02-02"] == "Bildende Kunst"  # unveraendert, kein Treffer in getSubjects
    assert rows["2026-02-03"] is None  # unveraendert, war schon None
