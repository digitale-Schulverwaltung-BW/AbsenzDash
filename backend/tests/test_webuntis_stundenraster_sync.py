from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.integrations.webuntis_client import WebUntisError
from app.models.stundenraster_periode import StundenrasterPeriode
from app.services.webuntis_stundenraster_sync import sync_stundenraster


@pytest.mark.asyncio
async def test_sync_stundenraster_converts_webuntis_weekday_to_iso_and_sorts_stunde_nr(db_session):
    client = AsyncMock()
    client.call.return_value = [
        {
            "day": 2,  # WebUntis: 2 = Montag
            "timeUnits": [
                {"name": "2", "startTime": 815, "endTime": 900},
                {"name": "1", "startTime": 730, "endTime": 815},
            ],
        },
    ]

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode).order_by(StundenrasterPeriode.stunde_nr))
    perioden = result.scalars().all()
    assert [(p.wochentag, p.stunde_nr, p.start_zeit, p.end_zeit) for p in perioden] == [
        (1, 1, 730, 815),
        (1, 2, 815, 900),
    ]
    assert client.call.await_args.args == ("getTimegridUnits", {})


@pytest.mark.asyncio
async def test_sync_stundenraster_replaces_existing_periods(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=1, end_zeit=2))
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"day": 2, "timeUnits": [{"name": "1", "startTime": 730, "endTime": 815}]},
    ]

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    perioden = result.scalars().all()
    assert len(perioden) == 1
    assert perioden[0].start_zeit == 730


@pytest.mark.asyncio
async def test_sync_stundenraster_keeps_old_data_when_call_fails(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    client = AsyncMock()
    client.call.side_effect = WebUntisError("boom")

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    perioden = result.scalars().all()
    assert len(perioden) == 1
    assert perioden[0].start_zeit == 730


@pytest.mark.asyncio
async def test_sync_stundenraster_keeps_old_data_when_response_is_empty(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = None

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_sync_stundenraster_skips_unknown_weekday_value(db_session):
    client = AsyncMock()
    client.call.return_value = [
        {"day": 99, "timeUnits": [{"name": "1", "startTime": 730, "endTime": 815}]},
    ]

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    assert result.scalars().all() == []
