import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.integrations.webuntis_client import WebUntisError
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.services.webuntis_fehlzeit_sync import (
    _build_kurzname_by_longname,
    _merge_tag_gruppe,
    _resolve_fach_kurzname,
    sync_fehlzeiten,
)


def _make_client(periods, subjects=None, subjects_raises=False):
	"""AsyncMock for WebUntisClient that dispatches by method name, so a test can supply a
	getTimetableWithAbsences payload without also having to fake getSubjects (defaults to no
	subjects, i.e. every fach falls back to the raw WebUntis longName).

	subjects_raises=True simulates getSubjects failing with a WebUntisError (e.g. permission
	change, transient error), to verify the sync degrades gracefully instead of aborting."""
	client = AsyncMock()

	async def _call(method, params):
		if method == "getTimetableWithAbsences":
			return periods
		if method == "getSubjects":
			if subjects_raises:
				raise WebUntisError("getSubjects fehlgeschlagen")
			return subjects if subjects is not None else []
		raise AssertionError(f"unexpected WebUntis call in test: {method}")

	client.call.side_effect = _call
	return client


def test_build_kurzname_by_longname_maps_longname_to_name():
    subjects = [{"id": 61, "name": "D", "longName": "Deutsch"}, {"id": 62, "name": "M", "longName": "Mathematik"}]
    assert _build_kurzname_by_longname(subjects) == {"Deutsch": "D", "Mathematik": "M"}


def test_build_kurzname_by_longname_first_match_wins_on_collision():
    """Live-bestaetigte Kollision: BK und BKOM tragen an dieser Schule denselben Langnamen
    'Betriebliche Kommunikation' (TECH-SPEC.md Abschnitt 1.2, Nachtrag 5)."""
    subjects = [
        {"id": 16, "name": "BK", "longName": "Betriebliche Kommunikation"},
        {"id": 458, "name": "BKOM", "longName": "Betriebliche Kommunikation"},
    ]
    assert _build_kurzname_by_longname(subjects) == {"Betriebliche Kommunikation": "BK"}


def test_build_kurzname_by_longname_skips_entries_without_longname_or_name():
    subjects = [{"id": 1, "name": "", "longName": "Ohne Kuerzel"}, {"id": 2, "name": "X", "longName": ""}]
    assert _build_kurzname_by_longname(subjects) == {}


def test_resolve_fach_kurzname_returns_kurzname_when_found():
    assert _resolve_fach_kurzname("Deutsch", {"Deutsch": "D"}) == "D"


def test_resolve_fach_kurzname_falls_back_to_langname_when_not_found():
    """z.B. inzwischen umbenanntes/deaktiviertes Fach, das nicht mehr in getSubjects() auftaucht
    (live beobachtet: 'Bildende Kunst')."""
    assert _resolve_fach_kurzname("Bildende Kunst", {"Deutsch": "D"}) == "Bildende Kunst"


def test_resolve_fach_kurzname_returns_none_for_none_input():
    assert _resolve_fach_kurzname(None, {"Deutsch": "D"}) is None


def test_resolve_fach_kurzname_returns_none_for_empty_string_input():
    assert _resolve_fach_kurzname("", {"Deutsch": "D"}) is None


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

    client = _make_client({
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
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_creates_tag_and_stunde_entries(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client({
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
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = {f.typ: f for f in result.scalars().all()}
    assert rows["tag"].start_zeit == 0
    assert rows["stunde"].fach == "Deutsch"
    client.call.assert_any_await(
        "getTimetableWithAbsences", {"options": {"startDate": 20260601, "endDate": 20260630}}
    )


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_invalid_entries(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client({
        "periodsWithAbsences": [
            {"date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1", "subjectId": "", "invalid": True},
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_unknown_externe_id(db_session):
    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "unbekannt",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_resolves_excuse_status_by_name(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    excuse_status = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, excuse_status])
    await db_session.commit()

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == excuse_status.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_auto_creates_unknown_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "hybrid", "invalid": False,
            },
        ]
    })

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

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    })

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

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1",
                "subjectId": "", "status": "irregular", "absenceReason": "krank", "invalid": False,
            },
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merges_multiple_tag_rows_into_one_day(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client({
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
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].typ == "tag"
    assert rows[0].start_zeit == 0
    assert rows[0].end_zeit == 2359


def test_merge_tag_gruppe_prefers_unentschuldigt_status():
    """Direkter Unit-Test von _merge_tag_gruppe (nicht ueber sync_fehlzeiten): seit der
    Signatur-Gruppierung (Nachtrag 2026-08-03) bekommt die Funktion durch sync_fehlzeiten nur
    noch Gruppen mit identischem excuseStatus uebergeben -- das "unentschuldigt gewinnt"-
    Verhalten der Funktion selbst bleibt aber als Sicherheitsnetz getestet, falls sie
    andernorts mit gemischtem Status aufgerufen wird."""
    entschuldigt_id = 1
    nicht_entschuldigt_id = 2
    excuse_status_id_by_name = {"entsch.": entschuldigt_id, "nicht entsch.": nicht_entschuldigt_id}
    zaehlt_als_entschuldigt_by_id = {entschuldigt_id: True, nicht_entschuldigt_id: False}

    rows = [
        {"excuseStatus": "entsch."},
        {"excuseStatus": "nicht entsch."},
    ]

    merged_excuse_status_id, _ = _merge_tag_gruppe(rows, excuse_status_id_by_name, zaehlt_als_entschuldigt_by_id)
    assert merged_excuse_status_id == nicht_entschuldigt_id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_keeps_entschuldigt_when_all_periods_entschuldigt(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add_all([schueler, entschuldigt])
    await db_session.commit()

    client = _make_client({
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
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == entschuldigt.id


def test_merge_tag_gruppe_concatenates_distinct_grund_text():
    """Direkter Unit-Test von _merge_tag_gruppe -- ueber sync_fehlzeiten ist dieser Pfad seit
    der Signatur-Gruppierung nicht mehr erreichbar (Zeilen mit unterschiedlichem absenceReason
    landen in unterschiedlichen Gruppen), die Dedup-/Zusammenfuege-Logik der Funktion selbst
    bleibt aber als Sicherheitsnetz getestet."""
    rows = [
        {"absenceReason": "Krank"},
        {"absenceReason": "Krank"},
        {"absenceReason": "Arzttermin"},
    ]

    _, merged_grund_text = _merge_tag_gruppe(rows, {}, {})
    assert merged_grund_text == "Krank; Arzttermin"


def test_merge_tag_gruppe_truncates_grund_text_to_column_limit():
    # 11 distinct, long absenceReason texts -> naive "; "-join would be well over 500 chars.
    rows = [{"absenceReason": f"Grund Nummer {i} mit sehr langem Freitext " * 3} for i in range(11)]

    _, merged_grund_text = _merge_tag_gruppe(rows, {}, {})
    assert merged_grund_text is not None
    assert len(merged_grund_text) <= 500


@pytest.mark.asyncio
async def test_sync_fehlzeiten_keeps_stunde_rows_separate_when_day_has_no_tag_candidate(db_session):
    """Eine subjectId-Zeile wird nur dann eigenstaendig als 'stunde' gefuehrt, wenn ihr Tag
    keine subjectId-lose Abwesenheits-Zeile hat -- hier ein anderer Tag als die 'tag'-Gruppe."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client({
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
    })

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

    client = _make_client({
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
                "date": 20260624, "startTime": 1110, "endTime": 1245, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "priv", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    })

    # subjectId-lose Zeile allein deckt 95 Minuten ab (>= Schwelle) und teilt die Signatur
    # (entsch., priv) mit den beiden subjectId-Zeilen -- alle drei gehoeren in dieselbe Gruppe,
    # trotz der grossen Luecke zur letzten Unterrichtsstunde (Mittagspause).
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

    client = _make_client({
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
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_sync_fehlzeiten_keeps_short_subjectid_less_blocks_as_stunde_not_tag(db_session):
    """Live-Fund (2026-08-03): eine einzelne kurze subjectId-lose Randstunde (z.B. eine
    45-Minuten-Stunde ohne Fach) ist kein ganzer Fehltag."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "invalid": False,
            },
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.typ == "stunde"
    assert fehlzeit.start_zeit == 730
    assert fehlzeit.end_zeit == 815
    assert fehlzeit.fach is None


@pytest.mark.asyncio
async def test_sync_fehlzeiten_keeps_separate_short_verspaetungen_apart(db_session):
    """Kernfall aus der Live-Beobachtung (2026-08-03, Schueler 81, 24.09.2025): zwei kurze,
    zeitlich weit auseinanderliegende Verspaetungen (eine entschuldigt, eine nicht) am selben
    Tag sind zwei eigenstaendige Ereignisse, kein gemeinsamer ganzer Fehltag."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, entschuldigt, nicht_entschuldigt])
    await db_session.commit()

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 925, "endTime": 934, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "verspätet", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1110, "endTime": 1119, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "verspätet", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = sorted(result.scalars().all(), key=lambda f: f.start_zeit)
    assert len(rows) == 2
    assert all(r.typ == "stunde" for r in rows)
    assert rows[0].start_zeit == 925 and rows[0].end_zeit == 934
    assert rows[0].excuse_status_id == entschuldigt.id
    assert rows[1].start_zeit == 1110 and rows[1].end_zeit == 1119
    assert rows[1].excuse_status_id == nicht_entschuldigt.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_writes_separate_entries_for_different_reasons_same_day(db_session):
    """Live-Muster aus der Stichprobe (2026-08-03): eine kurze Verspätung am Morgen und eine
    separate, laenger andauernde Krankmeldung am Nachmittag desselben Tages sind zwei
    unabhaengige Ereignisse -- eine kurze 'stunde'-Zeile und eine eigene 'tag'-Zeile, nicht
    ein einziger, faelschlich zusammengefuehrter Eintrag."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, nicht_entschuldigt])
    await db_session.commit()

    client = _make_client({
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "verspätet", "excuseStatus": "nicht entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1425, "endTime": 1510, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "excuseStatus": "nicht entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1515, "endTime": 1600, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "excuseStatus": "nicht entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1605, "endTime": 1650, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "krank", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    })

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = {r.typ: r for r in result.scalars().all()}
    assert len(rows) == 2
    assert rows["stunde"].start_zeit == 730 and rows["stunde"].end_zeit == 815
    assert rows["tag"].start_zeit == 0 and rows["tag"].end_zeit == 2359
    assert rows["tag"].grund_text == "krank"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_resolves_fach_to_kurzname(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client(
        {
            "periodsWithAbsences": [
                {
                    "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                    "subjectId": "Deutsch", "absentTime": 45, "invalid": False,
                },
            ]
        },
        subjects=[{"id": 61, "name": "D", "longName": "Deutsch"}],
    )

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().one().fach == "D"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_keeps_langname_when_no_matching_subject(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client(
        {
            "periodsWithAbsences": [
                {
                    "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                    "subjectId": "Bildende Kunst", "absentTime": 45, "invalid": False,
                },
            ]
        },
        subjects=[{"id": 61, "name": "D", "longName": "Deutsch"}],
    )

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().one().fach == "Bildende Kunst"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_survives_getsubjects_failure(db_session):
    """getSubjects ist nur fuer die Fach-Kuerzel-Aufloesung relevant (Anzeige-Detail) - ein
    Fehler dabei darf den restlichen Sync nicht abbrechen, sondern soll wie bei fehlenden/
    nicht passenden subjects auf den Langnamen zurueckfallen (siehe _resolve_fach_kurzname)."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client(
        {
            "periodsWithAbsences": [
                {
                    "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                    "subjectId": "Deutsch", "absentTime": 45, "invalid": False,
                },
            ]
        },
        subjects_raises=True,
    )

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().one().fach == "Deutsch"
