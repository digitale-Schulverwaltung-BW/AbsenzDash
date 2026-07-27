import datetime

import pytest
from sqlalchemy import select

from app.models.bereich import Bereich, bereich_klasse
from app.models.benachrichtigung import Benachrichtigung
from app.models.klasse import Klasse
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.services import student_query


@pytest.mark.asyncio
async def test_list_students_scopes_by_klasse_ids(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope={klasse_a.id})
    assert total == 1
    assert [s.id for s in items] == [schueler_a.id]


@pytest.mark.asyncio
async def test_list_students_returns_empty_for_empty_scope(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=set())
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_students_filters_by_bereich_id(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, bereich_id=bereich.id)
    assert total == 1
    assert [s.id for s in items] == [schueler_a.id]


@pytest.mark.asyncio
async def test_list_students_filters_by_min_stufe_and_typ(db_session):
    schueler_hoch = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    schueler_niedrig = Schueler(externe_id="ext-2", vorname="B", nachname="B")
    db_session.add_all([schueler_hoch, schueler_niedrig])
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerZaehlerstand(schueler_id=schueler_hoch.id, typ="fehlzeiten", aktueller_stand=8, erreichte_stufe_nr=2),
            SchuelerZaehlerstand(schueler_id=schueler_niedrig.id, typ="fehlzeiten", aktueller_stand=2, erreichte_stufe_nr=1),
        ]
    )
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, typ="fehlzeiten", min_stufe=2)
    assert total == 1
    assert [s.id for s in items] == [schueler_hoch.id]


@pytest.mark.asyncio
async def test_list_students_nur_auffaellige_excludes_students_without_reached_stufe(db_session):
    schueler_auffaellig = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    schueler_unauffaellig = Schueler(externe_id="ext-2", vorname="B", nachname="B")
    db_session.add_all([schueler_auffaellig, schueler_unauffaellig])
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerZaehlerstand(schueler_id=schueler_auffaellig.id, typ="klassenbuch", aktueller_stand=5, erreichte_stufe_nr=1),
            SchuelerZaehlerstand(schueler_id=schueler_unauffaellig.id, typ="klassenbuch", aktueller_stand=1, erreichte_stufe_nr=None),
        ]
    )
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, nur_auffaellige=True)
    assert total == 1
    assert [s.id for s in items] == [schueler_auffaellig.id]


@pytest.mark.asyncio
async def test_list_students_pagination(db_session):
    schueler_list = [
        Schueler(externe_id=f"ext-{i}", vorname="A", nachname=f"{i:02d}") for i in range(5)
    ]
    db_session.add_all(schueler_list)
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, limit=2, offset=1)
    assert total == 5
    assert len(items) == 2
    assert [s.nachname for s in items] == ["01", "02"]


@pytest.mark.asyncio
async def test_load_zaehlerstand_map_synthesizes_default_for_missing_typ(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", aktueller_stand=3, erreichte_stufe_nr=1))
    await db_session.commit()

    result = await student_query.load_zaehlerstand_map(db_session, [schueler.id])
    assert result[schueler.id]["fehlzeiten"] == {"aktueller_stand": 3, "erreichte_stufe_nr": 1}
    assert result[schueler.id]["klassenbuch"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}


@pytest.mark.asyncio
async def test_load_letzte_benachrichtigung_map_returns_latest_per_schueler(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    aelter = Benachrichtigung(
        schueler_id=schueler.id,
        stufe_nr=1,
        gesendet_am=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        empfaenger=[],
        status="gesendet",
    )
    neuer = Benachrichtigung(
        schueler_id=schueler.id,
        stufe_nr=2,
        gesendet_am=datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc),
        empfaenger=[],
        status="gesendet",
    )
    db_session.add_all([aelter, neuer])
    await db_session.commit()

    result = await student_query.load_letzte_benachrichtigung_map(db_session, [schueler.id])
    assert result[schueler.id].stufe_nr == 2


@pytest.mark.asyncio
async def test_load_ohne_massnahme_map_flags_missing_followup(db_session):
    schueler_ohne = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    schueler_mit = Schueler(externe_id="ext-2", vorname="B", nachname="B")
    db_session.add_all([schueler_ohne, schueler_mit])
    await db_session.flush()
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([typ, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler_mit.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 5),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    benachrichtigung_zeitpunkt = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    letzte_benachrichtigung = {
        schueler_ohne.id: Benachrichtigung(
            schueler_id=schueler_ohne.id, stufe_nr=1, gesendet_am=benachrichtigung_zeitpunkt, empfaenger=[], status="gesendet"
        ),
        schueler_mit.id: Benachrichtigung(
            schueler_id=schueler_mit.id, stufe_nr=1, gesendet_am=benachrichtigung_zeitpunkt, empfaenger=[], status="gesendet"
        ),
    }

    result = await student_query.load_ohne_massnahme_map(
        db_session, [schueler_ohne.id, schueler_mit.id], letzte_benachrichtigung
    )
    assert result[schueler_ohne.id] is True
    assert result[schueler_mit.id] is False


@pytest.mark.asyncio
async def test_load_student_detail_aggregates_all_sublists(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer A", rolle="klassenlehrkraft")
    db_session.add_all([typ, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 5),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)
    assert detail["fehlzeiten"] == []
    assert detail["klassenbuch"] == []
    assert detail["ausnahmen"] == []
    assert detail["benachrichtigungen"] == []
    assert len(detail["massnahmen"]) == 1
    massnahme, typ_name, nutzer_name = detail["massnahmen"][0]
    assert typ_name == "Gespräch"
    assert nutzer_name == "Lehrer A"
    assert detail["zaehlerstand"]["fehlzeiten"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}
