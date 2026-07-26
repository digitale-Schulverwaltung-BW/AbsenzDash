import datetime

import pytest
from sqlalchemy import select

from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel


@pytest.mark.asyncio
async def test_schueler_zaehlerstand_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([schueler, regel])
    await db_session.flush()

    zaehlerstand = SchuelerZaehlerstand(
        schueler_id=schueler.id,
        regel_id=regel.id,
        aktueller_stand=3,
        erreichte_stufe_nr=1,
        letzter_reset_am=datetime.date(2026, 1, 15),
    )
    db_session.add(zaehlerstand)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    loaded = result.scalar_one()
    assert loaded.aktueller_stand == 3
    assert loaded.erreichte_stufe_nr == 1
