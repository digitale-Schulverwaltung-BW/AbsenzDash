from unittest.mock import AsyncMock

import pytest

from app.services.webuntis_teacher_service import list_teachers


@pytest.mark.asyncio
async def test_list_teachers_maps_id_and_kuerzel():
    client = AsyncMock()
    client.call.return_value = [{"id": 42, "name": "ABC", "active": True}]

    result = await list_teachers(client)

    assert result == [{"id": 42, "kuerzel": "ABC"}] or (result[0].id == 42 and result[0].kuerzel == "ABC")
    client.call.assert_awaited_once_with("getTeachers", {})


@pytest.mark.asyncio
async def test_list_teachers_sorts_by_kuerzel_and_excludes_inactive():
    client = AsyncMock()
    client.call.return_value = [
        {"id": 2, "name": "MUE", "active": True},
        {"id": 1, "name": "ABC", "active": True},
        {"id": 3, "name": "XYZ", "active": False},
    ]

    result = await list_teachers(client)

    assert [t.kuerzel for t in result] == ["ABC", "MUE"]
