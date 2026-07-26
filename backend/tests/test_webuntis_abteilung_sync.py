from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.services.webuntis_abteilung_sync import sync_abteilungen


@pytest.mark.asyncio
async def test_sync_abteilungen_creates_new_abteilung(db_session):
    client = AsyncMock()
    client.call.return_value = [{"id": 64, "name": "A-2BFE", "longName": "A-2BFE"}]

    await sync_abteilungen(client, db_session)

    result = await db_session.execute(select(Abteilung).where(Abteilung.webuntis_id == 64))
    abteilung = result.scalar_one()
    assert abteilung.name == "A-2BFE"
    assert abteilung.long_name == "A-2BFE"
    client.call.assert_awaited_once_with("getDepartments", {})


@pytest.mark.asyncio
async def test_sync_abteilungen_updates_existing_abteilung(db_session):
    existing = Abteilung(webuntis_id=64, name="alt", long_name="alt")
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 64, "name": "neu", "longName": "Neuer Name"}]

    await sync_abteilungen(client, db_session)

    result = await db_session.execute(select(Abteilung).where(Abteilung.webuntis_id == 64))
    abteilung = result.scalar_one()
    assert abteilung.name == "neu"
    assert abteilung.long_name == "Neuer Name"
