import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import BereichIn, BereichLeiterIn
from app.services.bereich_service import list_bereiche, list_klassen, replace_bereiche


@pytest.mark.asyncio
async def test_list_klassen_returns_all_klassen_sorted_by_name(db_session):
    db_session.add_all([Klasse(webuntis_id=2, name="2BFE"), Klasse(webuntis_id=1, name="1BFE")])
    await db_session.commit()

    result = await list_klassen(db_session)

    assert [k.name for k in result] == ["1BFE", "2BFE"]


@pytest.mark.asyncio
async def test_replace_bereiche_creates_bereich_with_klassen(db_session):
    klasse = Klasse(webuntis_id=1, name="1BFE")
    db_session.add(klasse)
    await db_session.commit()

    payload = [BereichIn(name="Mechatronik", klasse_ids=[klasse.id], leiter=[])]
    result = await replace_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].name == "Mechatronik"
    assert result[0].klasse_ids == [klasse.id]

    listed = await list_bereiche(db_session)
    assert listed[0].name == "Mechatronik"


@pytest.mark.asyncio
async def test_replace_bereiche_creates_nutzer_stub_for_new_leiter(db_session):
    payload = [
        BereichIn(
            name="Mechatronik",
            klasse_ids=[],
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]

    result = await replace_bereiche(db_session, payload, admin_nutzer_id=None)

    assert len(result[0].leiter) == 1
    assert result[0].leiter[0].wp_user_id == "99"

    nutzer = (await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "99"))).scalar_one()
    assert nutzer.rolle == "bereichsleiter"
    assert nutzer.email == "a@b.de"


@pytest.mark.asyncio
async def test_replace_bereiche_does_not_overwrite_rolle_of_existing_nutzer(db_session):
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    payload = [
        BereichIn(
            name="Mechatronik",
            klasse_ids=[],
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]
    await replace_bereiche(db_session, payload, admin_nutzer_id=None)

    await db_session.refresh(nutzer)
    assert nutzer.rolle == "schulleitung"


@pytest.mark.asyncio
async def test_replace_bereiche_removes_bereich_not_in_payload(db_session):
    bereich = Bereich(name="Alt")
    db_session.add(bereich)
    await db_session.commit()

    await replace_bereiche(db_session, [], admin_nutzer_id=None)

    remaining = (await db_session.execute(select(Bereich))).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_replace_bereiche_cascades_klassen_and_leiter_on_delete(db_session):
    klasse = Klasse(webuntis_id=1, name="1BFE")
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")
    db_session.add_all([klasse, nutzer])
    await db_session.flush()
    bereich = Bereich(name="Alt")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))
    await db_session.commit()

    await replace_bereiche(db_session, [], admin_nutzer_id=None)

    assert (await db_session.execute(select(bereich_klasse))).all() == []
    assert (await db_session.execute(select(nutzer_bereich))).all() == []
    # der nutzer selbst bleibt bestehen, nur die Zuordnung verschwindet
    assert (await db_session.execute(select(Nutzer).where(Nutzer.id == nutzer.id))).scalar_one() is not None


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_empty_name(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, [BereichIn(name="   ", klasse_ids=[], leiter=[])], admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_duplicate_name(db_session):
    payload = [
        BereichIn(name="Mechatronik", klasse_ids=[], leiter=[]),
        BereichIn(name="Mechatronik", klasse_ids=[], leiter=[]),
    ]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_duplicate_id(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(id=bereich.id, name="A", klasse_ids=[], leiter=[]),
        BereichIn(id=bereich.id, name="B", klasse_ids=[], leiter=[]),
    ]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_unknown_id(db_session):
    payload = [BereichIn(id=999999, name="X", klasse_ids=[], leiter=[])]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_unknown_klasse_id(db_session):
    payload = [BereichIn(name="Mechatronik", klasse_ids=[999999], leiter=[])]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_unknown_rolle(db_session):
    payload = [
        BereichIn(
            name="Mechatronik", klasse_ids=[],
            leiter=[BereichLeiterIn(wp_user_id="1", email="a@b.de", name="A", rolle="oberlehrer")],
        )
    ]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


from app.models.abteilung import Abteilung
from app.services.bereich_service import vorschlag_aus_abteilungen


@pytest.mark.asyncio
async def test_vorschlag_aus_abteilungen_maps_long_name_and_klassen(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    klasse_zugehoerig = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id)
    klasse_fremd = Klasse(webuntis_id=2, name="2BFE")
    db_session.add_all([klasse_zugehoerig, klasse_fremd])
    await db_session.commit()

    result = await vorschlag_aus_abteilungen(db_session)

    assert len(result) == 1
    assert result[0].name == "Mechatronik"
    assert result[0].klasse_ids == [klasse_zugehoerig.id]


@pytest.mark.asyncio
async def test_vorschlag_aus_abteilungen_falls_back_to_name_without_long_name(db_session):
    db_session.add(Abteilung(webuntis_id=59, name="B-IE", long_name=None))
    await db_session.commit()

    result = await vorschlag_aus_abteilungen(db_session)

    assert result[0].name == "B-IE"
    assert result[0].klasse_ids == []


@pytest.mark.asyncio
async def test_vorschlag_aus_abteilungen_disambiguates_colliding_long_names(db_session):
    db_session.add_all(
        [
            Abteilung(webuntis_id=61, name="BT", long_name="Betriebstechnik"),
            Abteilung(webuntis_id=62, name="B-BT", long_name="Betriebstechnik"),
        ]
    )
    await db_session.commit()

    result = await vorschlag_aus_abteilungen(db_session)

    namen = [v.name for v in result]
    assert len(namen) == len(set(namen))
    assert "Betriebstechnik (BT)" in namen
    assert "Betriebstechnik (B-BT)" in namen


@pytest.mark.asyncio
async def test_vorschlag_aus_abteilungen_leaves_unique_name_unsuffixed(db_session):
    db_session.add_all(
        [
            Abteilung(webuntis_id=61, name="BT", long_name="Betriebstechnik"),
            Abteilung(webuntis_id=62, name="B-BT", long_name="Betriebstechnik"),
            Abteilung(webuntis_id=63, name="B-ME", long_name="Mechatronik"),
        ]
    )
    await db_session.commit()

    result = await vorschlag_aus_abteilungen(db_session)

    namen = [v.name for v in result]
    assert "Mechatronik" in namen
