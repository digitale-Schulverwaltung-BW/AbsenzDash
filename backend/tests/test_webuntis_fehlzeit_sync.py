import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.services.webuntis_fehlzeit_sync import sync_fehlzeiten


@pytest.mark.asyncio
async def test_sync_fehlzeiten_creates_tag_and_stunde_entries(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1",
                "subjectId": "", "checked": False, "invalid": False,
            },
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "absenceReason": "", "excuseStatus": None, "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = {f.typ: f for f in result.scalars().all()}
    assert rows["tag"].start_zeit == 0
    assert rows["stunde"].fach == "Deutsch"
    client.call.assert_awaited_once_with(
        "getTimetableWithAbsences", {"options": {"startDate": 20260601, "endDate": 20260630}}
    )


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_invalid_entries(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {"date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1", "subjectId": "", "invalid": True},
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_unknown_externe_id(db_session):
    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {"date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "unbekannt", "subjectId": "", "invalid": False},
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_resolves_excuse_status_by_name(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    excuse_status = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, excuse_status])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == excuse_status.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_upserts_existing_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    existing = Fehlzeit(
        schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 6, 24), start_zeit=0, end_zeit=2359
    )
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1",
                "subjectId": "", "status": "irregular", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merges_multiple_tag_rows_into_one_day(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].typ == "tag"
    assert rows[0].start_zeit == 0
    assert rows[0].end_zeit == 2359


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_prefers_unentschuldigt_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, entschuldigt, nicht_entschuldigt])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == nicht_entschuldigt.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_keeps_entschuldigt_when_all_periods_entschuldigt(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add_all([schueler, entschuldigt])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == entschuldigt.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_concatenates_distinct_grund_text(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "Krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "Krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "Arzttermin", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.grund_text == "Krank; Arzttermin"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_keeps_stunde_rows_separate(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1425, "endTime": 1510, "studentId": "ext-1",
                "subjectId": "Deutsch", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = {f.typ: f for f in result.scalars().all()}
    assert len(rows) == 2
    assert rows["tag"].start_zeit == 0
    assert rows["stunde"].fach == "Deutsch"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_is_idempotent_across_reruns(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert len(result.scalars().all()) == 1
