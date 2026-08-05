import datetime
import logging
from contextlib import contextmanager
from decimal import Decimal
from unittest import mock

import pytest
from sqlalchemy import event, select

from app.core.config import settings
from app.core.database import engine
from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.services import eskalations_pruefung
from app.services.eskalations_pruefung import pruefe_schwellwerte


async def _make_schueler(db_session, aktiv: bool = True) -> Schueler:
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=aktiv)
    db_session.add(schueler)
    await db_session.flush()
    return schueler


async def _make_fehlzeiten_regel(db_session, schwellenwert: int = 4) -> SchwellwertRegel:
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=1,
            einheit="fehltage",
            schwellenwert=schwellenwert,
            fehlzeiten_filter="alle",
            empfaenger_rollen=["klassenlehrkraft"],
        )
    )
    await db_session.commit()
    return regel


async def _make_zweistufige_fehlzeiten_regel(
    db_session,
    schwellenwert_stufe1: int = 2,
    schwellenwert_stufe2: int = 5,
    einheit: str = "fehltage",
    fehlzeiten_filter: str = "alle",
) -> SchwellwertRegel:
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=1,
            einheit=einheit,
            schwellenwert=schwellenwert_stufe1,
            fehlzeiten_filter=fehlzeiten_filter,
            empfaenger_rollen=["klassenlehrkraft"],
        )
    )
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=2,
            einheit=einheit,
            schwellenwert=schwellenwert_stufe2,
            fehlzeiten_filter=fehlzeiten_filter,
            empfaenger_rollen=["bereichsleiter"],
        )
    )
    await db_session.commit()
    return regel


@contextmanager
def _zaehle_zaehlerstand_selects():
    count = 0

    def _zaehler(conn, cursor, statement, parameters, context, executemany):
        nonlocal count
        if statement.strip().upper().startswith("SELECT") and "schueler_zaehlerstand" in statement:
            count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _zaehler)
    try:
        yield lambda: count
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _zaehler)


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_reaches_stufe_when_threshold_met(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=2)
    for tag in range(2):
        db_session.add(
            Fehlzeit(
                schueler_id=schueler.id,
                typ="tag",
                datum=datetime.date(2026, 1, 10 + tag),
                start_zeit=0,
                end_zeit=0,
            )
        )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1
    assert zaehlerstand.aktueller_stand == 2


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_no_stufe_when_below_threshold(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=4)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr is None
    assert zaehlerstand.aktueller_stand == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_respects_fenster_start_from_letzter_reset(db_session):
    schueler = await _make_schueler(db_session)
    regel = await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        SchuelerZaehlerstand(
            schueler_id=schueler.id,
            typ="fehlzeiten",
            regel_id=regel.id,
            aktueller_stand=0,
            letzter_reset_am=datetime.date(2026, 1, 15),
        )
    )
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0
        )
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.aktueller_stand == 0
    assert zaehlerstand.erreichte_stufe_nr is None


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_counts_klassenbuch_eintraege_for_klassenbuch_regel(db_session):
    schueler = await _make_schueler(db_session)
    kategorie = ClassregCategory(name="stören")
    db_session.add(kategorie)
    await db_session.flush()
    regel = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(regel_id=regel.id, stufe_nr=1, schwellenwert=2, empfaenger_rollen=["klassenlehrkraft"])
    )
    for i in range(2):
        db_session.add(
            KlassenbuchEintrag(
                webuntis_id=100 + i, schueler_id=schueler.id, kategorie_id=kategorie.id, datum=datetime.date(2026, 1, 10 + i)
            )
        )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_skips_when_no_fenster_start_determinable(db_session):
    """Weder schuljahr_start_cache noch ein vorhandener letzter_reset_am -> kein Fenster, kein Zaehlerstand."""
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=None)
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_multistage_reaches_highest_met_stufe(db_session):
    schueler = await _make_schueler(db_session)
    await _make_zweistufige_fehlzeiten_regel(db_session, schwellenwert_stufe1=2, schwellenwert_stufe2=5)
    for tag in range(6):
        db_session.add(
            Fehlzeit(
                schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 1 + tag), start_zeit=0, end_zeit=0
            )
        )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 2
    assert zaehlerstand.aktueller_stand == 6


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_multistage_reaches_lower_stufe_not_higher(db_session):
    schueler = await _make_schueler(db_session)
    await _make_zweistufige_fehlzeiten_regel(db_session, schwellenwert_stufe1=2, schwellenwert_stufe2=5)
    for tag in range(3):
        db_session.add(
            Fehlzeit(
                schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 1 + tag), start_zeit=0, end_zeit=0
            )
        )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1
    assert zaehlerstand.aktueller_stand == 3


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_multistage_no_stufe_met_still_counts(db_session):
    schueler = await _make_schueler(db_session)
    await _make_zweistufige_fehlzeiten_regel(db_session, schwellenwert_stufe1=2, schwellenwert_stufe2=5)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr is None
    assert zaehlerstand.aktueller_stand == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_nur_unentschuldigt_excludes_entschuldigte_fehlzeiten(db_session):
    schueler = await _make_schueler(db_session)
    regel = await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    stufe_result = await db_session.execute(select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id))
    stufe = stufe_result.scalar_one()
    stufe.fehlzeiten_filter = "nur_unentschuldigt"

    entschuldigt_status = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add(entschuldigt_status)
    await db_session.flush()

    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=datetime.date(2026, 1, 10),
            start_zeit=0,
            end_zeit=0,
            excuse_status_id=entschuldigt_status.id,
        )
    )
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=datetime.date(2026, 1, 11),
            start_zeit=0,
            end_zeit=0,
            excuse_status_id=None,
        )
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.aktueller_stand == 1
    assert zaehlerstand.erreichte_stufe_nr == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_skips_schueler_with_active_ausnahme(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    db_session.add(Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="Testgrund", aktiv=True))
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_ignores_expired_ausnahme(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    db_session.add(
        Ausnahme(
            schueler_id=schueler.id,
            kategorie="fehlzeiten",
            grund="Abgelaufen",
            aktiv=True,
            gueltig_bis=datetime.date(2026, 1, 1),
        )
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_fehlstunden_only_counts_stunde_typ(db_session):
    schueler = await _make_schueler(db_session)
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=1,
            einheit="fehlstunden",
            schwellenwert=2,
            fehlzeiten_filter="alle",
            empfaenger_rollen=["klassenlehrkraft"],
        )
    )
    for i in range(2):
        db_session.add(
            Fehlzeit(
                schueler_id=schueler.id,
                typ="stunde",
                fach="D",
                datum=datetime.date(2026, 1, 10 + i),
                start_zeit=800,
                end_zeit=845,
            )
        )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 15), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.aktueller_stand == Decimal("2.00")  # 2 x 45 Min. = 90 Min. / 45 = 2.00 Fehlstunden
    assert zaehlerstand.erreichte_stufe_nr == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_excludes_invalid_fehlzeiten(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=datetime.date(2026, 1, 10),
            start_zeit=0,
            end_zeit=0,
            invalid=False,
        )
    )
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=datetime.date(2026, 1, 11),
            start_zeit=0,
            end_zeit=0,
            invalid=True,
        )
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.aktueller_stand == 1
    assert zaehlerstand.erreichte_stufe_nr == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_writes_benachrichtigung_on_newly_reached_stufe(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    nutzer_id = nutzer.id
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "gesendet"
    assert benachrichtigung.empfaenger == [{"rolle": "klassenlehrkraft", "nutzer_id": nutzer_id}]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_no_repeat_benachrichtigung_on_unchanged_stufe(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 21), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_kein_empfaenger_when_no_klassenlehrkraft_registered(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    db_session.add(schueler)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "kein_empfaenger"
    assert benachrichtigung.empfaenger == []


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_initial_import_status_before_first_full_sync(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "initial_import"


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_bereichsleiter_empfaenger(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    bereich = Bereich(name="Kaufmaennischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    bereichsleiter = Nutzer(wp_user_id="u2", email="b@b.de", name="Leiter", rolle="bereichsleiter")
    db_session.add_all([schueler, bereichsleiter])
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=bereichsleiter.id, bereich_id=bereich.id))

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["bereichsleiter"],
        )
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    bereichsleiter_id = bereichsleiter.id
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.empfaenger == [{"rolle": "bereichsleiter", "nutzer_id": bereichsleiter_id}]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_klassenlehrkraft_empfaenger_without_duplicate(db_session):
    """Ein Lehrer mit zwei NutzerKlasse-Zeilen (webuntis_seed + manuell) fuer dieselbe Klasse
    darf nur EINMAL als Empfaenger auftauchen (Regression fuer fehlendes .distinct())."""
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="manuell"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    nutzer_id = nutzer.id
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.empfaenger == [{"rolle": "klassenlehrkraft", "nutzer_id": nutzer_id}]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_regel_once_per_klasse_not_per_schueler(db_session):
    """Regel-Aufloesung ist innerhalb eines Sync-Laufs pro (klasse_id, typ) invariant und soll dort
    nur einmal ausgefuehrt werden, nicht einmal pro Schueler (Performance-Fix)."""
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="C", nachname="D", aktiv=True, klasse_id=klasse.id)
    db_session.add_all([schueler_a, schueler_b])
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    original = eskalations_pruefung.resolve_schwellwert_regel
    aufrufe: list[tuple[int | None, str]] = []

    async def _zaehlender_wrapper(db, klasse_id, typ):
        aufrufe.append((klasse_id, typ))
        return await original(db, klasse_id, typ)

    with mock.patch.object(eskalations_pruefung, "resolve_schwellwert_regel", side_effect=_zaehlender_wrapper):
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)

    assert len(aufrufe) == 2
    assert aufrufe.count((klasse.id, "fehlzeiten")) == 1
    assert aufrufe.count((klasse.id, "klassenbuch")) == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_selects_existing_zaehlerstand_only_once(db_session):
    """get_or_create_zaehlerstand soll die im Fenster-Guard bereits geladene Zeile wiederverwenden statt
    sie erneut zu selektieren (Performance-Fix: vorher 2 SELECTs auf schueler_zaehlerstand pro Schueler)."""
    schueler = await _make_schueler(db_session)
    regel = await _make_fehlzeiten_regel(db_session, schwellenwert=5)
    db_session.add(
        SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", regel_id=regel.id, aktueller_stand=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    with _zaehle_zaehlerstand_selects() as get_count:
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)

    assert get_count() == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_selects_zaehlerstand_only_once_when_none_exists(db_session):
    """Auch wenn noch kein SchuelerZaehlerstand existiert (z.B. neuer Schueler), darf nur EIN SELECT
    auf schueler_zaehlerstand ausgefuehrt werden, kein redundanter zweiter SELECT in
    get_or_create_zaehlerstand."""
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=5)
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    with _zaehle_zaehlerstand_selects() as get_count:
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)

    assert get_count() == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_logs_missing_schuljahr_start_once_not_per_schueler(db_session, caplog):
    """Fehlender schuljahr_start_cache soll pro Sync-Lauf nur einmal geloggt werden, nicht einmal pro
    Schueler (Log-Spam-Fix: vorher eine Warnzeile pro Schueler ohne eigenen letzter_reset_am)."""
    for i in range(3):
        db_session.add(Schueler(externe_id=f"ext-{i}", vorname="A", nachname="B", aktiv=True))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=None)
    with caplog.at_level(logging.WARNING, logger="app.services.eskalations_pruefung"):
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)

    fenster_warnungen = [r for r in caplog.records if "schuljahr_start_cache" in r.getMessage()]
    assert len(fenster_warnungen) == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_ausnahme_kategorie_is_independent_across_typen(db_session):
    """Eine aktive Ausnahme fuer Kategorie 'klassenbuch' darf die 'fehlzeiten'-Verarbeitung desselben
    Schuelers nicht unterdruecken (regressionstestet die klassenbuch->fehlzeiten Richtung; die
    umgekehrte Richtung folgt aus derselben Kategorie-Filterlogik in _hat_aktive_ausnahme)."""
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    db_session.add(Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Testgrund", aktiv=True))
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.typ == "fehlzeiten"
        )
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_bereichsleiter_empfaenger_without_duplicate(db_session):
    """Ein Bereichsleiter, der zwei Bereiche leitet, die beide auf dieselbe Klasse gemappt sind, darf nur
    EINMAL als Empfaenger auftauchen (Regression fuer fehlendes .distinct(), bereichsleiter-Fall — bisher
    nur fuer klassenlehrkraft abgedeckt)."""
    klasse = Klasse(webuntis_id=1, name="10a")
    bereich_a = Bereich(name="Kaufmaennischer Bereich")
    bereich_b = Bereich(name="Technischer Bereich")
    db_session.add_all([klasse, bereich_a, bereich_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_a.id, klasse_id=klasse.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_b.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    bereichsleiter = Nutzer(wp_user_id="u2", email="b@b.de", name="Leiter", rolle="bereichsleiter")
    db_session.add_all([schueler, bereichsleiter])
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=bereichsleiter.id, bereich_id=bereich_a.id))
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=bereichsleiter.id, bereich_id=bereich_b.id))

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=1,
            einheit="fehltage",
            schwellenwert=1,
            fehlzeiten_filter="alle",
            empfaenger_rollen=["bereichsleiter"],
        )
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    bereichsleiter_id = bereichsleiter.id
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.empfaenger == [{"rolle": "bereichsleiter", "nutzer_id": bereichsleiter_id}]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_status_fehler_when_send_email_raises(db_session, mock_send_email):
    mock_send_email.side_effect = OSError("Connection refused")
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    assert result.scalar_one().status == "fehler"


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_status_fehler_when_template_malformed(db_session, mock_send_email, monkeypatch, tmp_path):
    """Ein fehlerhaftes Admin-Template-Override (hier: Tippfehler im Platzhalternamen, fuehrt zu
    KeyError in render_template) darf den Sync-Lauf nicht abbrechen - analog zum send_email-Fehlerfall
    landet das auf status='fehler', und pruefe_schwellwerte wirft keine Exception."""
    (tmp_path / "email_benachrichtigung.txt.default").write_text(
        "Betreff $nicht_existierender_platzhalter\n\nBody-Text.", encoding="utf-8"
    )
    monkeypatch.setattr(eskalations_pruefung, "TEMPLATES_DIR", tmp_path)

    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    assert result.scalar_one().status == "fehler"
    mock_send_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_dedupes_recipient_addresses_for_send(db_session, mock_send_email):
    """Ein Nutzer, der fuer dieselbe Klasse sowohl Klassenlehrkraft als auch Bereichsleiter ist,
    darf beim tatsaechlichen Versand nur EINMAL im To-Feld auftauchen (Log-Eintrag behaelt beide Rollen)."""
    klasse = Klasse(webuntis_id=1, name="10a")
    bereich = Bereich(name="Kaufmaennischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["klassenlehrkraft", "bereichsleiter"],
        )
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_awaited_once()
    call_args = mock_send_email.await_args
    assert call_args.args[1] == ["a@b.de"]


_DEFAULT_TEMPLATE_CONTENT = """AbsenzDash: Stufe $stufe_nr erreicht – $schueler_vorname $schueler_nachname

Schüler/in: $schueler_vorname $schueler_nachname ($klasse)
Regel: $regel_typ
Erreichte Stufe: $stufe_nr
Aktueller Zählerstand: $zaehlerstand $einheit

Details im Dashboard: $dashboard_link

Diese E-Mail wurde automatisch von AbsenzDash versendet."""


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_renders_expected_mail_content(db_session, mock_send_email, monkeypatch, tmp_path):
    """Hermetisch: schreibt eine eigene .default-Datei nach tmp_path statt gegen das echte
    TEMPLATES_DIR zu testen, damit ein lokal angelegtes, nicht versioniertes Admin-Override in
    backend/app/templates/email_benachrichtigung.txt die Assertions nicht unbemerkt beeinflusst."""
    (tmp_path / "email_benachrichtigung.txt.default").write_text(_DEFAULT_TEMPLATE_CONTENT, encoding="utf-8")
    monkeypatch.setattr(eskalations_pruefung, "TEMPLATES_DIR", tmp_path)

    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_awaited_once()
    call_args = mock_send_email.await_args
    subject, body = call_args.args[2], call_args.args[3]
    assert "Max Muster" in subject
    assert "10a" in body
    assert f"{settings.dashboard_base_url}/students/{schueler_id}" in body


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_kein_empfaenger_does_not_call_send_email(db_session, mock_send_email):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    db_session.add(schueler)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_initial_import_does_not_call_send_email(db_session, mock_send_email):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_not_awaited()
