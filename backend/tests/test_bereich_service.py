import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import BereichIn, BereichLeiterIn
from app.services.bereich_service import list_abteilungen, list_bereiche, update_bereiche


@pytest.mark.asyncio
async def test_list_abteilungen_returns_all_sorted_by_name(db_session):
    db_session.add_all([Abteilung(webuntis_id=2, name="B"), Abteilung(webuntis_id=1, name="A")])
    await db_session.commit()

    result = await list_abteilungen(db_session)

    assert [a.name for a in result] == ["A", "B"]


@pytest.mark.asyncio
async def test_list_bereiche_includes_klasse_namen_and_ausgeblendet(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="1BFE", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik", ausgeblendet=True)
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    result = await list_bereiche(db_session)

    assert result[0].name == "Mechatronik"
    assert result[0].klasse_namen == ["1BFE"]
    assert result[0].ausgeblendet is True


@pytest.mark.asyncio
async def test_update_bereiche_sets_ausgeblendet(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [BereichIn(id=bereich.id, ausgeblendet=True, leiter=[])]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].ausgeblendet is True
    await db_session.refresh(bereich)
    assert bereich.ausgeblendet is True


@pytest.mark.asyncio
async def test_update_bereiche_does_not_change_name_or_klassen(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="1BFE", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    payload = [BereichIn(id=bereich.id, ausgeblendet=False, leiter=[])]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].name == "Mechatronik"
    assert result[0].klasse_namen == ["1BFE"]


@pytest.mark.asyncio
async def test_update_bereiche_creates_nutzer_stub_for_new_leiter(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(
            id=bereich.id,
            ausgeblendet=False,
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert len(result[0].leiter) == 1
    assert result[0].leiter[0].wp_user_id == "99"
    nutzer = (await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "99"))).scalar_one()
    assert nutzer.rolle == "bereichsleiter"


@pytest.mark.asyncio
async def test_update_bereiche_does_not_overwrite_rolle_of_existing_nutzer(db_session):
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="schulleitung")
    bereich = Bereich(name="Mechatronik")
    db_session.add_all([nutzer, bereich])
    await db_session.commit()

    payload = [
        BereichIn(
            id=bereich.id,
            ausgeblendet=False,
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]
    await update_bereiche(db_session, payload, admin_nutzer_id=None)

    await db_session.refresh(nutzer)
    assert nutzer.rolle == "schulleitung"


@pytest.mark.asyncio
async def test_update_bereiche_replaces_leiter_set(db_session):
    bereich = Bereich(name="Mechatronik")
    nutzer_alt = Nutzer(wp_user_id="1", email="a@b.de", name="Alt", rolle="bereichsleiter")
    db_session.add_all([bereich, nutzer_alt])
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer_alt.id))
    await db_session.commit()

    payload = [BereichIn(id=bereich.id, ausgeblendet=False, leiter=[])]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].leiter == []
    remaining = (await db_session.execute(select(nutzer_bereich))).all()
    assert remaining == []
    # der Nutzer selbst bleibt bestehen, nur die Zuordnung verschwindet
    assert (await db_session.execute(select(Nutzer).where(Nutzer.id == nutzer_alt.id))).scalar_one() is not None


@pytest.mark.asyncio
async def test_update_bereiche_rejects_duplicate_id(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(id=bereich.id, ausgeblendet=False, leiter=[]),
        BereichIn(id=bereich.id, ausgeblendet=True, leiter=[]),
    ]
    with pytest.raises(HTTPException) as exc_info:
        await update_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_bereiche_rejects_unknown_id(db_session):
    payload = [BereichIn(id=999999, ausgeblendet=False, leiter=[])]
    with pytest.raises(HTTPException) as exc_info:
        await update_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_bereiche_rejects_unknown_rolle(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(
            id=bereich.id, ausgeblendet=False,
            leiter=[BereichLeiterIn(wp_user_id="1", email="a@b.de", name="A", rolle="oberlehrer")],
        )
    ]
    with pytest.raises(HTTPException) as exc_info:
        await update_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422
