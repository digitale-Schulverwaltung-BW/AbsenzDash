import datetime

import pytest
from sqlalchemy import select

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler


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
async def test_massnahmen_typ_defaults_to_aktiv(db_session):
    typ = MassnahmenTyp(name="Testtyp", setzt_zaehler_zurueck=False)
    db_session.add(typ)
    await db_session.commit()

    result = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == typ.id))
    assert result.scalar_one().aktiv is True
