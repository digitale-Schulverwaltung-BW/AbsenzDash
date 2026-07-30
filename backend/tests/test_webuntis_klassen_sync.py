from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.services.webuntis_klassen_sync import sync_klassen


@pytest.mark.asyncio
async def test_sync_klassen_creates_new_klasse(db_session):
    client = AsyncMock()
    client.call.return_value = [
        {"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None},
    ]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.name == "10a"
    assert klasse.webuntis_teacher1_id == 63
    assert klasse.webuntis_teacher2_id is None
    client.call.assert_awaited_once_with("getKlassen", {"schoolyearId": 28})


@pytest.mark.asyncio
async def test_sync_klassen_updates_existing_klasse(db_session):
    existing = Klasse(webuntis_id=1, name="alt", webuntis_teacher1_id=1)
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 1, "name": "neu", "teacher1": 2, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 1))
    klasse = result.scalar_one()
    assert klasse.name == "neu"
    assert klasse.webuntis_teacher1_id == 2


@pytest.mark.asyncio
async def test_sync_klassen_triggers_nutzer_klasse_seeding(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft", webuntis_teacher_id=63)
    db_session.add(nutzer)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(NutzerKlasse))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].quelle == "webuntis_seed"


@pytest.mark.asyncio
async def test_sync_klassen_resolves_abteilung_id_from_did(db_session):
    abteilung = Abteilung(webuntis_id=64, name="A-2BFE")
    db_session.add(abteilung)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "did": 64, "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.abteilung_id == abteilung.id


@pytest.mark.asyncio
async def test_sync_klassen_leaves_abteilung_id_none_when_did_unresolvable(db_session):
    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "did": 999, "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.abteilung_id is None
