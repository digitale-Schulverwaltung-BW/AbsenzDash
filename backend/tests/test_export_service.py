import datetime

import pytest

from app.models.ausnahme import Ausnahme
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
from app.models.schuljahr import Schuljahr
from app.services import export_service


def test_build_export_filename_transliterates_umlauts():
    assert export_service.build_export_filename("Müller", "Jörg") == "Mueller_Joerg_export.pdf"


def test_build_export_filename_transliterates_eszett():
    assert export_service.build_export_filename("Straß", "Anna") == "Strass_Anna_export.pdf"


def test_build_export_filename_strips_other_diacritics_to_base_letter():
    assert export_service.build_export_filename("Renée", "José") == "Renee_Jose_export.pdf"


def test_build_export_filename_replaces_remaining_special_characters_with_dash():
    assert export_service.build_export_filename("O'Brien", "Anne-Marie") == "O-Brien_Anne-Marie_export.pdf"


def test_build_export_filename_replaces_spaces_with_dash():
    assert export_service.build_export_filename("von Bergmann", "Karl Heinz") == "von-Bergmann_Karl-Heinz_export.pdf"


async def _seed_full_student(db_session):
    schuljahr = Schuljahr(id=1, name="2025/2026", start_datum=datetime.date(2025, 9, 15), end_datum=datetime.date(2026, 7, 29))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    status = ExcuseStatus(name="U", long_name="Unentschuldigt", zaehlt_als_entschuldigt=False)
    kategorie = ClassregCategory(name="verspaetet", long_name="Verspätung")
    typ = MassnahmenTyp(name="Elterngespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="lehrer1", email="l@b.de", name="Lehrer Eins", rolle="klassenlehrkraft")
    db_session.add_all([schueler, status, kategorie, typ, nutzer])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=datetime.date(2026, 2, 1),
            start_zeit=1,
            end_zeit=6,
            excuse_status_id=status.id,
        )
    )
    db_session.add(
        KlassenbuchEintrag(
            webuntis_id=1,
            schueler_id=schueler.id,
            kategorie_id=kategorie.id,
            datum=datetime.date(2026, 2, 2),
            text="Zu spät gekommen",
        )
    )
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 3),
            notiz="Gespräch geführt",
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    db_session.add(Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="Attest", aktiv=True))
    await db_session.commit()
    return schueler, klasse


@pytest.mark.asyncio
async def test_render_student_export_html_includes_all_sections_by_default(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse,
        sections={"fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"},
    )

    assert "Muster" in html
    assert "10a" in html
    assert "Unentschuldigt" in html
    assert "Verspätung" in html
    assert "Elterngespräch" in html
    assert "Attest" in html


@pytest.mark.asyncio
async def test_render_student_export_html_omits_sections_not_requested(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}
    )

    assert "Unentschuldigt" in html
    assert "Verspätung" not in html  # Klassenbuch-Abschnitt
    assert "Elterngespräch" not in html  # Massnahmen-Abschnitt
    assert "Attest" not in html  # Ausnahmen-Abschnitt


@pytest.mark.asyncio
async def test_render_student_export_html_repeats_table_headers_via_thead(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}
    )

    assert "<thead>" in html


@pytest.mark.asyncio
async def test_render_student_export_html_footer_contains_name_and_page_counter(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}
    )

    assert "Muster, Max" in html
    assert "counter(page)" in html
    assert "counter(pages)" in html


def test_html_to_pdf_returns_pdf_bytes():
    pdf_bytes = export_service.html_to_pdf("<html><body><h1>Test</h1></body></html>")
    assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_render_student_export_html_converts_gesendet_am_to_berlin_local_time(db_session):
    schueler, klasse = await _seed_full_student(db_session)
    db_session.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            regel_id=None,
            stufe_nr=1,
            gesendet_am=datetime.datetime(2026, 2, 1, 8, 0, tzinfo=datetime.timezone.utc),
            empfaenger=[{"rolle": "klassenlehrkraft"}],
            status="gesendet",
        )
    )
    await db_session.commit()

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"benachrichtigungen"}
    )

    # 08:00 UTC in Februar (Winterzeit, UTC+1) -> 09:00 Berlin-Lokalzeit
    assert "01.02.2026 09:00" in html


@pytest.mark.asyncio
async def test_render_student_export_html_filters_fehlzeiten_by_von_bis(db_session):
    schueler, klasse = await _seed_full_student(db_session)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2024, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"},
        von=datetime.date(2026, 1, 1), bis=datetime.date(2026, 12, 31),
    )

    assert "01.02.2026" in html  # aus _seed_full_student, liegt im Zeitraum
    assert "01.10.2024" not in html  # ausserhalb des Zeitraums


@pytest.mark.asyncio
async def test_render_student_export_html_does_not_filter_massnahmen_by_von_bis(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"massnahmen"},
        von=datetime.date(2030, 1, 1), bis=datetime.date(2030, 12, 31),
    )

    assert "Elterngespräch" in html  # Massnahme liegt ausserhalb des Zeitraums, bleibt trotzdem sichtbar


@pytest.mark.asyncio
async def test_render_student_export_html_shows_schuljahr_name_in_meta_when_given(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}, schuljahr_name="2024/2025",
    )

    assert "2024/2025" in html


@pytest.mark.asyncio
async def test_render_student_export_html_shows_gesamte_historie_when_no_schuljahr_given(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"},
    )

    assert "gesamte Historie" in html


@pytest.mark.asyncio
async def test_render_student_export_html_shows_dauer_anzeige_for_fehlzeiten(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=datetime.date(2026, 2, 2), start_zeit=730, end_zeit=745)
    )
    await db_session.commit()

    html = await export_service.render_student_export_html(db_session, schueler, klasse, sections={"fehlzeiten"})

    assert "15 Minuten (7:30–7:45)" in html
