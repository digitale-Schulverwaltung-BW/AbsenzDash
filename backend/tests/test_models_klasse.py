import pytest
from sqlalchemy import select

from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse


@pytest.mark.asyncio
async def test_klasse_roundtrip(db_session):
    klasse = Klasse(webuntis_id=3499, name="10a", webuntis_teacher1_id=63, webuntis_teacher2_id=434)
    db_session.add(klasse)
    await db_session.commit()

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    loaded = result.scalar_one()
    assert loaded.name == "10a"
    assert loaded.webuntis_teacher1_id == 63


@pytest.mark.asyncio
async def test_bereich_klasse_association(db_session):
    klasse = Klasse(webuntis_id=1, name="11b")
    bereich = Bereich(name="Kaufmännischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()

    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    result = await db_session.execute(select(bereich_klasse))
    row = result.first()
    assert row.bereich_id == bereich.id
    assert row.klasse_id == klasse.id
