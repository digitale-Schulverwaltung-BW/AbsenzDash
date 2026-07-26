import datetime

import pytest
from sqlalchemy import select

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schwellwert_regel import SchwellwertRegel


@pytest.mark.asyncio
async def test_massnahme_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, typ, nutzer])
    await db_session.flush()

    massnahme = Massnahme(
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz="Testnotiz",
        erfasst_von_nutzer_id=nutzer.id,
    )
    db_session.add(massnahme)
    await db_session.commit()

    result = await db_session.execute(select(Massnahme).where(Massnahme.schueler_id == schueler.id))
    loaded = result.scalar_one()
    assert loaded.notiz == "Testnotiz"


@pytest.mark.asyncio
async def test_massnahmen_typ_regel_association(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([typ, regel])
    await db_session.flush()

    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel.id))
    await db_session.commit()

    result = await db_session.execute(select(massnahmen_typ_regel))
    row = result.first()
    assert row.massnahmen_typ_id == typ.id
    assert row.regel_id == regel.id
