from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.services.webuntis_kategorie_sync import sync_kategorien


@pytest.mark.asyncio
async def test_sync_kategorien_creates_categories_with_group_name(db_session):
    client = AsyncMock()
    client.call.side_effect = [
        [{"id": 1, "name": "stören", "longName": "Störung des Unterrichts", "groupId": 10}],
        [{"id": 10, "name": "Störung"}],
    ]

    await sync_kategorien(client, db_session)

    result = await db_session.execute(select(ClassregCategory).where(ClassregCategory.name == "stören"))
    kategorie = result.scalar_one()
    assert kategorie.long_name == "Störung des Unterrichts"
    assert kategorie.group_name == "Störung"
    assert client.call.await_args_list[0].args == ("getClassregCategories", {})
    assert client.call.await_args_list[1].args == ("getClassregCategoryGroups", {})


@pytest.mark.asyncio
async def test_sync_kategorien_updates_existing_category(db_session):
    existing = ClassregCategory(webuntis_id=1, name="stören", long_name="alt", group_name=None)
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.side_effect = [
        [{"id": 1, "name": "stören", "longName": "neu", "groupId": None}],
        [],
    ]

    await sync_kategorien(client, db_session)

    result = await db_session.execute(select(ClassregCategory).where(ClassregCategory.name == "stören"))
    kategorie = result.scalar_one()
    assert kategorie.long_name == "neu"
    assert kategorie.group_name is None
