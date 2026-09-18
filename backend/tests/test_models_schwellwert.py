import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe


@pytest.mark.asyncio
async def test_schwellwert_regel_stufe_roundtrip(db_session):
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()

    stufe = SchwellwertStufe(
        regel_id=regel.id,
        stufe_nr=1,
        einheit="fehltage",
        schwellenwert=4,
        fehlzeiten_filter="nur_unentschuldigt",
        empfaenger_rollen=["klassenlehrkraft"],
    )
    db_session.add(stufe)
    await db_session.commit()

    result = await db_session.execute(select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id))
    loaded = result.scalar_one()
    assert loaded.schwellenwert == 4
    assert loaded.empfaenger_rollen == ["klassenlehrkraft"]


@pytest.mark.asyncio
async def test_schwellwert_regel_prevents_duplicate_abteilung_regel_same_typ(db_session):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id))
    await db_session.commit()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_schwellwert_regel_prevents_duplicate_klasse_regel_same_typ(db_session, schuljahr):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=abteilung.id, schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse.id))
    await db_session.commit()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_schwellwert_regel_prevents_duplicate_schulweit_same_typ(db_session):
    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit"))
    await db_session.commit()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
