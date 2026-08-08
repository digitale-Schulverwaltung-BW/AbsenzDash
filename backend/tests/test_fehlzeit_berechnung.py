from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.models.stundenraster_periode import StundenrasterPeriode
from app.services.fehlzeit_berechnung import dauer_anzeige, fehlstunden_minuten_expr, minuten_zu_fehlstunden


def test_minuten_zu_fehlstunden_rounds_to_two_decimals():
    assert minuten_zu_fehlstunden(65) == Decimal("1.44")  # 65/45 = 1.4444...


def test_minuten_zu_fehlstunden_handles_none_and_zero():
    assert minuten_zu_fehlstunden(None) == Decimal("0.00")
    assert minuten_zu_fehlstunden(0) == Decimal("0.00")


def test_minuten_zu_fehlstunden_exact_hour():
    assert minuten_zu_fehlstunden(90) == Decimal("2.00")


@pytest.mark.asyncio
async def test_fehlstunden_minuten_expr_is_hhmm_aware_across_hour_boundary(db_session):
    """730 -> 815 im WebUntis-HHMM-Format ist 07:30-08:15, also 45 Minuten - eine
    naive Integer-Subtraktion (815 - 730 = 85) waere falsch."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 1, 10), start_zeit=730, end_zeit=815)
    )
    await db_session.commit()

    result = await db_session.execute(
        select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id)
    )
    assert result.scalar_one() == 45


@pytest.mark.asyncio
async def test_fehlstunden_minuten_expr_sums_multiple_rows_within_same_hour(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 1, 10), start_zeit=900, end_zeit=920),
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 1, 11), start_zeit=1000, end_zeit=1010),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(
        select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id)
    )
    assert result.scalar_one() == 30  # 20 + 10


def test_dauer_anzeige_gibt_ganztaegig_zurueck_fuer_typ_tag():
    fehlzeit = Fehlzeit(typ="tag", datum=date(2026, 2, 2), start_zeit=0, end_zeit=2359)
    assert dauer_anzeige(fehlzeit, {}) == "ganztägig"


def test_dauer_anzeige_matches_single_periode():
    # 2026-02-02 ist ein Montag (isoweekday() == 1)
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745)
    perioden_by_wochentag = {
        1: [StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815)],
    }
    assert dauer_anzeige(fehlzeit, perioden_by_wochentag) == "15 Minuten (Stunde 1)"


def test_dauer_anzeige_matches_multiple_aufeinanderfolgende_perioden():
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=900)
    perioden_by_wochentag = {
        1: [
            StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815),
            StundenrasterPeriode(wochentag=1, stunde_nr=2, start_zeit=820, end_zeit=905),
        ],
    }
    assert dauer_anzeige(fehlzeit, perioden_by_wochentag) == "90 Minuten (Stunde 1-2)"


def test_dauer_anzeige_falls_back_to_formatted_time_when_no_periode_matches():
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745)
    assert dauer_anzeige(fehlzeit, {}) == "15 Minuten (7:30–7:45)"


def test_dauer_anzeige_ignores_perioden_of_other_weekdays():
    # Fehlzeit ist Montag (isoweekday 1), Perioden nur fuer Dienstag (2) hinterlegt.
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745)
    perioden_by_wochentag = {
        2: [StundenrasterPeriode(wochentag=2, stunde_nr=1, start_zeit=730, end_zeit=815)],
    }
    assert dauer_anzeige(fehlzeit, perioden_by_wochentag) == "15 Minuten (7:30–7:45)"
