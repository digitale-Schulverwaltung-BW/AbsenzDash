import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.services.webuntis_bereich_sync import sync_bereiche


@pytest.mark.asyncio
async def test_sync_bereiche_creates_bereich_per_abteilung_with_matching_klassen(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    klasse_zugehoerig = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id)
    klasse_fremd = Klasse(webuntis_id=2, name="2BFE")
    db_session.add_all([klasse_zugehoerig, klasse_fremd])
    await db_session.commit()

    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "Mechatronik"
    assert bereich.abteilung_id == abteilung.id
    assert bereich.ausgeblendet is False
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == [klasse_zugehoerig.id]


@pytest.mark.asyncio
async def test_sync_bereiche_creates_bereich_with_zero_klassen_for_empty_abteilung(db_session):
    db_session.add(Abteilung(webuntis_id=61, name="B-ALT", long_name="Historisch"))
    await db_session.commit()

    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "Historisch"
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == []


@pytest.mark.asyncio
async def test_sync_bereiche_falls_back_to_name_without_long_name(db_session):
    db_session.add(Abteilung(webuntis_id=59, name="B-IE", long_name=None))
    await db_session.commit()

    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "B-IE"


@pytest.mark.asyncio
async def test_sync_bereiche_disambiguates_colliding_long_names(db_session):
    db_session.add_all(
        [
            Abteilung(webuntis_id=61, name="BT", long_name="Betriebstechnik"),
            Abteilung(webuntis_id=62, name="B-BT", long_name="Betriebstechnik"),
        ]
    )
    await db_session.commit()

    await sync_bereiche(db_session)

    namen = (await db_session.execute(select(Bereich.name))).scalars().all()
    assert sorted(namen) == ["Betriebstechnik (B-BT)", "Betriebstechnik (BT)"]


@pytest.mark.asyncio
async def test_sync_bereiche_updates_name_on_abteilung_rename(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.commit()
    await sync_bereiche(db_session)

    abteilung.long_name = "Mechatronik neu"
    await db_session.commit()
    await sync_bereiche(db_session)

    bereiche = (await db_session.execute(select(Bereich))).scalars().all()
    assert len(bereiche) == 1
    assert bereiche[0].name == "Mechatronik neu"


@pytest.mark.asyncio
async def test_sync_bereiche_rebuilds_bereich_klasse_when_klasse_moves_abteilung(db_session):
    abteilung_a = Abteilung(webuntis_id=1, name="A", long_name="Abteilung A")
    abteilung_b = Abteilung(webuntis_id=2, name="B", long_name="Abteilung B")
    db_session.add_all([abteilung_a, abteilung_b])
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung_a.id)
    db_session.add(klasse)
    await db_session.commit()
    await sync_bereiche(db_session)

    klasse.abteilung_id = abteilung_b.id
    await db_session.commit()
    await sync_bereiche(db_session)

    bereich_a = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_a.id))).scalar_one()
    bereich_b = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_b.id))).scalar_one()
    klasse_ids_a = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_a.id))
    ).scalars().all()
    klasse_ids_b = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_b.id))
    ).scalars().all()
    assert klasse_ids_a == []
    assert klasse_ids_b == [klasse.id]


@pytest.mark.asyncio
async def test_sync_bereiche_never_touches_ausgeblendet_or_leiter(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.commit()
    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    bereich.ausgeblendet = True
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))
    await db_session.commit()

    await sync_bereiche(db_session)

    await db_session.refresh(bereich)
    assert bereich.ausgeblendet is True
    leiter_rows = (
        await db_session.execute(select(nutzer_bereich).where(nutzer_bereich.c.bereich_id == bereich.id))
    ).all()
    assert len(leiter_rows) == 1
