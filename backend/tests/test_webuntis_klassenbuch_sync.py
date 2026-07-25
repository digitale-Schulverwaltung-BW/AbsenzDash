import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler
from app.services.webuntis_klassenbuch_sync import sync_klassenbuch


@pytest.mark.asyncio
async def test_sync_klassenbuch_creates_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    kategorie = ClassregCategory(name="stören", webuntis_id=1)
    db_session.add_all([schueler, kategorie])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {
            "eventId": 19245, "studentid": "ext-1", "subject": "D", "categoryId": 1, "date": 20260623,
            "text": "Hat gestört", "lessonId": 152327,
            "createTeacher": {"id": 51, "name": "X"}, "updateTeacher": {"id": 51, "name": "X"},
        }
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag).where(KlassenbuchEintrag.webuntis_id == 19245))
    eintrag = result.scalar_one()
    assert eintrag.schueler_id == schueler.id
    assert eintrag.kategorie_id == kategorie.id
    assert eintrag.text == "Hat gestört"
    assert eintrag.erstellt_von_teacher_id == 51
    client.call.assert_awaited_once_with("getClassregEvents", {"startDate": 20260601, "endDate": 20260630})


@pytest.mark.asyncio
async def test_sync_klassenbuch_skips_unknown_externe_id(db_session):
    kategorie = ClassregCategory(name="stören", webuntis_id=1)
    db_session.add(kategorie)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"eventId": 1, "studentid": "unbekannt", "subject": "D", "categoryId": 1, "date": 20260623, "text": ""}
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_klassenbuch_skips_unknown_kategorie(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"eventId": 1, "studentid": "ext-1", "subject": "D", "categoryId": 999, "date": 20260623, "text": ""}
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_klassenbuch_upserts_existing_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    kategorie = ClassregCategory(name="stören", webuntis_id=1)
    db_session.add_all([schueler, kategorie])
    await db_session.commit()

    existing = KlassenbuchEintrag(
        webuntis_id=1, schueler_id=schueler.id, kategorie_id=kategorie.id,
        datum=datetime.date(2026, 6, 23), text="alt",
    )
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"eventId": 1, "studentid": "ext-1", "subject": "D", "categoryId": 1, "date": 20260623, "text": "neu"}
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].text == "neu"
