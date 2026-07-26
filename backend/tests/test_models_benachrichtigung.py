import datetime

import pytest
from sqlalchemy import select

from app.models.benachrichtigung import Benachrichtigung
from app.models.schueler import Schueler
from app.models.schwellwert_regel import SchwellwertRegel


@pytest.mark.asyncio
async def test_benachrichtigung_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([schueler, regel])
    await db_session.flush()

    benachrichtigung = Benachrichtigung(
        schueler_id=schueler.id,
        regel_id=regel.id,
        stufe_nr=1,
        gesendet_am=datetime.datetime(2026, 1, 20, 8, 0, tzinfo=datetime.timezone.utc),
        empfaenger=[{"rolle": "klassenlehrkraft", "nutzer_id": 1}],
        status="gesendet",
    )
    db_session.add(benachrichtigung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    loaded = result.scalar_one()
    assert loaded.status == "gesendet"
    assert loaded.empfaenger == [{"rolle": "klassenlehrkraft", "nutzer_id": 1}]
