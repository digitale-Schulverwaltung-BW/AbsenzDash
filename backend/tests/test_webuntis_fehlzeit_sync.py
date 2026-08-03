import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.services.webuntis_fehlzeit_sync import sync_fehlzeiten


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_rows_without_absence_signal(db_session):
    """WebUntis liefert fuer einmal 'gepruefte' Tage die komplette Perioden-Liste des Schuelers
    zurueck, nicht nur echte Abwesenheiten (siehe TECH-SPEC.md Abschnitt 1.2, Nachtrag
    2026-08-03) -- Zeilen ohne excuseStatus/absenceReason/absentTime sind normal besuchter
    Unterricht bzw. Zeitplan-Metadaten ('status: irregular'), unabhaengig von subjectId.
    """
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1",
                "subjectId": "", "status": "irregular", "checked": True, "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "Deutsch", "checked": True,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().all() == []


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
                "subjectId": "", "checked": False, "absenceReason": "krank", "invalid": False,
            },
            {
                "date": 20260625, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "absenceReason": "", "excuseStatus": None, "absentTime": 45,
                "invalid": False,
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
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "unbekannt",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
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
async def test_sync_fehlzeiten_auto_creates_unknown_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "hybrid", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    status_result = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.name == "hybrid"))
    neuer_status = status_result.scalar_one()
    assert neuer_status.zaehlt_als_entschuldigt is False

    fehlzeit_result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = fehlzeit_result.scalar_one()
    assert fehlzeit.excuse_status_id == neuer_status.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_does_not_duplicate_known_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    bestehender_status = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add_all([schueler, bestehender_status])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    status_result = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.name == "entsch."))
    rows = status_result.scalars().all()
    assert len(rows) == 1
    assert rows[0].zaehlt_als_entschuldigt is True  # unveraendert, nicht auf False zurueckgesetzt

    fehlzeit_result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert fehlzeit_result.scalar_one().excuse_status_id == bestehender_status.id


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
                "subjectId": "", "status": "irregular", "absenceReason": "krank", "invalid": False,
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
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
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
async def test_sync_fehlzeiten_merge_truncates_grund_text_to_column_limit(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    # 11 distinct, long absenceReason texts -> naive "; "-join would be well over 500 chars.
    periods = [
        {
            "date": 20260624, "startTime": 730 + i * 45, "endTime": 815 + i * 45, "studentId": "ext-1",
            "subjectId": "", "absenceReason": f"Grund Nummer {i} mit sehr langem Freitext " * 3, "invalid": False,
        }
        for i in range(11)
    ]
    client = AsyncMock()
    client.call.return_value = {"periodsWithAbsences": periods}

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.grund_text is not None
    assert len(fehlzeit.grund_text) <= 500


@pytest.mark.asyncio
async def test_sync_fehlzeiten_keeps_stunde_rows_separate_when_day_has_no_tag_candidate(db_session):
    """Eine subjectId-Zeile wird nur dann eigenstaendig als 'stunde' gefuehrt, wenn ihr Tag
    keine subjectId-lose Abwesenheits-Zeile hat -- hier ein anderer Tag als die 'tag'-Gruppe."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
            {
                "date": 20260625, "startTime": 1425, "endTime": 1510, "studentId": "ext-1",
                "subjectId": "Deutsch", "absenceReason": "krank", "invalid": False,
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
async def test_sync_fehlzeiten_merges_stunde_rows_into_tag_when_same_day_has_tag_candidate(db_session):
    """Kernfall aus der Live-Beobachtung (2026-08-03): ein durchgehend entschuldigter Tag deckt
    sowohl subjectId-lose Leerstunden als auch echte Unterrichtsstunden ab -- alle gehoeren zum
    selben Abwesenheits-Ereignis und muessen zu EINER 'tag'-Zeile zusammengefasst werden, nicht
    zusaetzlich als separate 'stunde'-Zeilen."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add_all([schueler, entschuldigt])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "Englisch", "absenceReason": "priv", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "Mathematik", "absenceReason": "priv", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1110, "endTime": 1155, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "priv", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].typ == "tag"
    assert rows[0].fach is None
    assert rows[0].excuse_status_id == entschuldigt.id


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
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert len(result.scalars().all()) == 1
