import datetime
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.ausnahme import Ausnahme
from app.models.bereich import Bereich, bereich_klasse
from app.models.benachrichtigung import Benachrichtigung
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.stundenraster_periode import StundenrasterPeriode
from app.services import student_query


@pytest.mark.asyncio
async def test_list_students_scopes_by_klasse_ids(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id, aktiv=True)
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id, aktiv=True)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope={klasse_a.id})
    assert total == 1
    assert [s.id for s in items] == [schueler_a.id]


@pytest.mark.asyncio
async def test_list_students_returns_empty_for_empty_scope(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=set())
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_students_filters_by_bereich_id(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id, aktiv=True)
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id, aktiv=True)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, bereich_id=bereich.id)
    assert total == 1
    assert [s.id for s in items] == [schueler_a.id]


@pytest.mark.asyncio
async def test_list_students_filters_by_min_stufe_and_typ(db_session):
    schueler_hoch = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    schueler_niedrig = Schueler(externe_id="ext-2", vorname="B", nachname="B", aktiv=True)
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
    schueler_auffaellig = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    schueler_unauffaellig = Schueler(externe_id="ext-2", vorname="B", nachname="B", aktiv=True)
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
        Schueler(externe_id=f"ext-{i}", vorname="A", nachname=f"{i:02d}", aktiv=True) for i in range(5)
    ]
    db_session.add_all(schueler_list)
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, limit=2, offset=1)
    assert total == 5
    assert len(items) == 2
    assert [s.nachname for s in items] == ["01", "02"]


@pytest.mark.asyncio
async def test_load_zaehlerstand_map_synthesizes_default_for_missing_typ(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", aktueller_stand=3, erreichte_stufe_nr=1))
    await db_session.commit()

    result = await student_query.load_zaehlerstand_map(db_session, [schueler.id])
    assert result[schueler.id]["fehlzeiten"] == {"aktueller_stand": 3, "erreichte_stufe_nr": 1}
    assert result[schueler.id]["klassenbuch"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}


@pytest.mark.asyncio
async def test_load_letzte_benachrichtigung_map_returns_latest_per_schueler(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
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
    schueler_ohne = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    schueler_mit = Schueler(externe_id="ext-2", vorname="B", nachname="B", aktiv=True)
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
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
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


@pytest.mark.asyncio
async def test_load_student_detail_includes_active_and_revoked_ausnahmen(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    aktive_ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="Aktiv", aktiv=True)
    aufgehobene_ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Aufgehoben", aktiv=False)
    db_session.add_all([aktive_ausnahme, aufgehobene_ausnahme])
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)
    assert {(a.grund, a.aktiv) for a in detail["ausnahmen"]} == {("Aktiv", True), ("Aufgehoben", False)}


@pytest.mark.asyncio
async def test_list_students_excludes_inactive_students_by_default(db_session):
    aktiv = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    inaktiv = Schueler(externe_id="ext-2", vorname="B", nachname="B", aktiv=False)
    db_session.add_all([aktiv, inaktiv])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None)
    assert total == 1
    assert [s.id for s in items] == [aktiv.id]

    items, total = await student_query.list_students(db_session, scope=None, nur_aktive=False)
    assert total == 2


@pytest.mark.asyncio
async def test_list_students_klasse_id_filter_cannot_widen_scope(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    db_session.add_all(
        [
            Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id, aktiv=True),
            Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id, aktiv=True),
        ]
    )
    await db_session.commit()

    # scope is klasse_a only; caller asks for klasse_b anyway - must get nothing, not klasse_b's student
    items, total = await student_query.list_students(db_session, scope={klasse_a.id}, klasse_id=klasse_b.id)
    assert total == 0
    assert items == []


@pytest.mark.asyncio
async def test_list_students_sorts_by_fehlstunden_descending(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler_wenig = Schueler(externe_id="ext-wenig", vorname="Wenig", nachname="Fehlstunden", klasse_id=klasse.id, aktiv=True)
    schueler_viel = Schueler(externe_id="ext-viel", vorname="Viel", nachname="Fehlstunden", klasse_id=klasse.id, aktiv=True)
    db_session.add_all([schueler_wenig, schueler_viel])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler_wenig.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=800, end_zeit=815),
            Fehlzeit(schueler_id=schueler_viel.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=730, end_zeit=815),
            Fehlzeit(schueler_id=schueler_viel.id, typ="stunde", datum=date(2025, 10, 2), start_zeit=730, end_zeit=815),
        ]
    )
    await db_session.commit()

    items, _ = await student_query.list_students(
        db_session, scope=None, von=date(2025, 9, 1), bis=date(2026, 7, 30), sort_by="fehlstunden", sort_dir="desc"
    )

    assert [s.id for s in items] == [schueler_viel.id, schueler_wenig.id]


@pytest.mark.asyncio
async def test_list_students_sorts_by_fehltage_ascending(db_session):
    schueler_null = Schueler(externe_id="ext-0", vorname="Null", nachname="A", aktiv=True)
    schueler_zwei = Schueler(externe_id="ext-2", vorname="Zwei", nachname="B", aktiv=True)
    db_session.add_all([schueler_null, schueler_zwei])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler_zwei.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_zwei.id, typ="tag", datum=date(2025, 10, 2), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    items, _ = await student_query.list_students(
        db_session, scope=None, von=date(2025, 9, 1), bis=date(2026, 7, 30), sort_by="fehltage", sort_dir="asc"
    )

    assert [s.id for s in items] == [schueler_null.id, schueler_zwei.id]


@pytest.mark.asyncio
async def test_list_students_default_sort_is_unchanged_name_order(db_session):
    schueler_z = Schueler(externe_id="ext-z", vorname="A", nachname="Zeta", aktiv=True)
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="Anton", aktiv=True)
    db_session.add_all([schueler_z, schueler_a])
    await db_session.commit()

    items, _ = await student_query.list_students(db_session, scope=None)

    assert [s.id for s in items] == [schueler_a.id, schueler_z.id]


@pytest.mark.asyncio
async def test_load_excuse_status_map_returns_rows_by_id(db_session):
    status_a = ExcuseStatus(name="E", long_name="Entschuldigt", zaehlt_als_entschuldigt=True)
    status_b = ExcuseStatus(name="U", long_name="Unentschuldigt", zaehlt_als_entschuldigt=False)
    db_session.add_all([status_a, status_b])
    await db_session.commit()

    result = await student_query.load_excuse_status_map(db_session, [status_a.id])
    assert set(result.keys()) == {status_a.id}
    assert result[status_a.id].long_name == "Entschuldigt"


@pytest.mark.asyncio
async def test_load_excuse_status_map_returns_empty_dict_for_empty_input(db_session):
    result = await student_query.load_excuse_status_map(db_session, [])
    assert result == {}


@pytest.mark.asyncio
async def test_load_classreg_category_map_returns_rows_by_id(db_session):
    kategorie = ClassregCategory(name="verspaetet", long_name="Verspätung", group_name="fehlzeiten")
    db_session.add(kategorie)
    await db_session.commit()

    result = await student_query.load_classreg_category_map(db_session, [kategorie.id])
    assert result[kategorie.id].long_name == "Verspätung"


@pytest.mark.asyncio
async def test_load_classreg_category_map_returns_empty_dict_for_empty_input(db_session):
    result = await student_query.load_classreg_category_map(db_session, [])
    assert result == {}


@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_counts_within_range(db_session):
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B")
    kategorie = ClassregCategory(name="stören", long_name="Störung des Unterrichts", group_name="Störung")
    db_session.add_all([schueler_a, schueler_b, kategorie])
    await db_session.flush()

    db_session.add_all(
        [
            # schueler_a: 2 Fehltage, 1 Fehlstunde (730-815 = 45 Min. -> 1.00 Fehlstunde) within range,
            # 1 Fehltag outside range
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2025, 11, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_a.id, typ="stunde", datum=date(2025, 10, 5), start_zeit=730, end_zeit=815),
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            KlassenbuchEintrag(
                schueler_id=schueler_a.id, webuntis_id=1, kategorie_id=kategorie.id, datum=date(2025, 10, 2)
            ),
            # schueler_b: nothing in range
            Fehlzeit(schueler_id=schueler_b.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(
        db_session, [schueler_a.id, schueler_b.id], date(2025, 9, 15), date(2026, 7, 29)
    )

    assert result[schueler_a.id]["fehltage"] == {"gesamt": 2, "entschuldigt": 0, "unentschuldigt": 2}
    assert result[schueler_a.id]["fehlstunden"] == {
        "gesamt": Decimal("1.00"), "entschuldigt": Decimal("0.00"), "unentschuldigt": Decimal("1.00"),
    }
    assert result[schueler_a.id]["klassenbuch_anzahl"] == 1
    assert result[schueler_b.id]["fehltage"] == {"gesamt": 0, "entschuldigt": 0, "unentschuldigt": 0}
    assert result[schueler_b.id]["fehlstunden"] == {
        "gesamt": Decimal("0.00"), "entschuldigt": Decimal("0.00"), "unentschuldigt": Decimal("0.00"),
    }
    assert result[schueler_b.id]["klassenbuch_anzahl"] == 0


@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_splits_by_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, entschuldigt, nicht_entschuldigt])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(
                schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359,
                excuse_status_id=entschuldigt.id,
            ),
            Fehlzeit(
                schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 2), start_zeit=0, end_zeit=2359,
                excuse_status_id=nicht_entschuldigt.id,
            ),
            # kein excuse_status_id gesetzt -> zaehlt als unentschuldigt
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 3), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(db_session, [schueler.id], date(2025, 9, 15), date(2026, 7, 29))

    assert result[schueler.id]["fehltage"] == {"gesamt": 3, "entschuldigt": 1, "unentschuldigt": 2}


@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_fehlstunden_gesamt_rounds_combined_minutes_once(db_session):
    """Regression: 'gesamt' muss aus der Summe der Roh-Minuten beider Buckets EINMAL gerundet
    werden, nicht aus der Summe zweier bereits (je fuer sich) gerundeter Bucket-Werte. 25 Min.
    entschuldigt + 25 Min. unentschuldigt = 50 Min. gesamt -> round(50/45, 2) = 1.11. Die alte,
    fehlerhafte Implementierung haette stattdessen round(25/45,2) + round(25/45,2) = 0.56 + 0.56
    = 1.12 geliefert - ein 0.01-Diskrepanz gegenueber eskalations_pruefung.py/dashboard_query.py,
    die beide einmalig ueber die Gesamt-Minuten runden."""
    schueler = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, entschuldigt, nicht_entschuldigt])
    await db_session.flush()
    db_session.add_all(
        [
            # 800-825 = 25 Minuten, entschuldigt
            Fehlzeit(
                schueler_id=schueler.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=800, end_zeit=825,
                excuse_status_id=entschuldigt.id,
            ),
            # 900-925 = 25 Minuten, unentschuldigt
            Fehlzeit(
                schueler_id=schueler.id, typ="stunde", datum=date(2025, 10, 2), start_zeit=900, end_zeit=925,
                excuse_status_id=nicht_entschuldigt.id,
            ),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(db_session, [schueler.id], date(2025, 9, 15), date(2026, 7, 29))

    assert result[schueler.id]["fehlstunden"] == {
        "gesamt": Decimal("1.11"), "entschuldigt": Decimal("0.56"), "unentschuldigt": Decimal("0.56"),
    }


@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_without_date_range_counts_all_time(db_session):
    schueler = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2020, 1, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 1, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(db_session, [schueler.id], None, None)

    assert result[schueler.id]["fehltage"]["gesamt"] == 2


@pytest.mark.asyncio
async def test_load_student_detail_filters_by_range_except_massnahmen(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    kategorie = ClassregCategory(name="stören", long_name="Störung des Unterrichts", group_name="Störung")
    db_session.add_all([schueler, typ, nutzer, kategorie])
    await db_session.flush()

    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            KlassenbuchEintrag(schueler_id=schueler.id, webuntis_id=1, kategorie_id=kategorie.id, datum=date(2025, 11, 1)),
            KlassenbuchEintrag(schueler_id=schueler.id, webuntis_id=2, kategorie_id=kategorie.id, datum=date(2024, 11, 1)),
            Benachrichtigung(
                schueler_id=schueler.id, stufe_nr=1, gesendet_am=datetime.datetime(2025, 12, 1, tzinfo=datetime.timezone.utc),
                empfaenger=[], status="gesendet",
            ),
            Benachrichtigung(
                schueler_id=schueler.id, stufe_nr=1, gesendet_am=datetime.datetime(2024, 12, 1, tzinfo=datetime.timezone.utc),
                empfaenger=[], status="gesendet",
            ),
            Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="im Bereich", gueltig_bis=None),
            Massnahme(schueler_id=schueler.id, massnahmen_typ_id=typ.id, datum=date(2024, 6, 1), erfasst_von_nutzer_id=nutzer.id),
        ]
    )
    await db_session.commit()

    # bis liegt bewusst weit in der Zukunft (statt am "Ende des Schuljahres 2025/2026"), damit der
    # Test unabhaengig vom tatsaechlichen Testlaufdatum ist: Ausnahme.created_at wird beim Insert
    # auf "jetzt" gesetzt, und die Ausnahme soll trotzdem als ueberlappend gelten (unbefristet).
    detail = await student_query.load_student_detail(
        db_session, schueler.id, von=date(2025, 9, 15), bis=date(2099, 12, 31), ist_historie=True
    )

    assert [f.datum for f in detail["fehlzeiten"]] == [date(2025, 10, 1)]
    assert [k.datum for k in detail["klassenbuch"]] == [date(2025, 11, 1)]
    assert len(detail["benachrichtigungen"]) == 1
    assert len(detail["ausnahmen"]) == 1  # unbefristet, created vor dem Zeitraum, gilt trotzdem als ueberlappend
    assert len(detail["massnahmen"]) == 1  # Massnahmen NIE gefiltert, auch die von 2024 bleibt sichtbar
    assert detail["zaehlerstand"] == {}


@pytest.mark.asyncio
async def test_load_student_detail_computes_dauer_anzeige_for_fehlzeiten(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 2, 2), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745),
        ]
    )
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)

    by_typ = {f.typ: f for f in detail["fehlzeiten"]}
    assert by_typ["tag"].dauer_anzeige == "ganztägig"
    assert by_typ["stunde"].dauer_anzeige == "15 Minuten (7:30–7:45)"


@pytest.mark.asyncio
async def test_load_student_detail_uses_stundenraster_when_available(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745))
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)

    assert detail["fehlzeiten"][0].dauer_anzeige == "15 Minuten (Stunde 1)"
