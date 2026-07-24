import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.bereich import Bereich
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse


@pytest.mark.asyncio
async def test_nutzer_roundtrip(db_session):
    nutzer = Nutzer(
        wp_user_id="jseyfried",
        email="joerg.seyfried@hhs.karlsruhe.de",
        name="Jörg Seyfried",
        rolle="klassenlehrkraft",
        webuntis_teacher_id=63,
    )
    db_session.add(nutzer)
    await db_session.commit()

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    loaded = result.scalar_one()
    assert loaded.rolle == "klassenlehrkraft"
    assert loaded.webuntis_teacher_id == 63


@pytest.mark.asyncio
async def test_nutzer_klasse_unique_per_quelle(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add_all([nutzer, klasse])
    await db_session.flush()

    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_nutzer_bereich_association(db_session):
    nutzer = Nutzer(wp_user_id="u2", email="c@d.de", name="C", rolle="bereichsleiter")
    bereich = Bereich(name="Gewerblicher Bereich")
    db_session.add_all([nutzer, bereich])
    await db_session.flush()

    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    result = await db_session.execute(select(nutzer_bereich))
    row = result.first()
    assert row.nutzer_id == nutzer.id
    assert row.bereich_id == bereich.id
