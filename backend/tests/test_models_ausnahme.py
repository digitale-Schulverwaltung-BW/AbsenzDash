import datetime

import pytest
from sqlalchemy import select

from app.models.ausnahme import Ausnahme
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_ausnahme_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()

    ausnahme = Ausnahme(
        schueler_id=schueler.id,
        kategorie="fehlzeiten",
        grund="Chronische Erkrankung",
        gueltig_bis=datetime.date(2026, 12, 31),
    )
    db_session.add(ausnahme)
    await db_session.commit()

    result = await db_session.execute(select(Ausnahme).where(Ausnahme.schueler_id == schueler.id))
    loaded = result.scalar_one()
    assert loaded.grund == "Chronische Erkrankung"
    assert loaded.aktiv is True
