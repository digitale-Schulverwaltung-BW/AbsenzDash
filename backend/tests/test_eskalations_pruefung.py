import datetime

import pytest
from sqlalchemy import select

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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.aktueller_stand == 2
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "gesendet"
    assert benachrichtigung.empfaenger == [{"rolle": "klassenlehrkraft", "nutzer_id": nutzer.id}]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_no_repeat_benachrichtigung_on_unchanged_stufe(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 21), einstellung)
    await db_session.commit()

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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

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
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.empfaenger == [{"rolle": "bereichsleiter", "nutzer_id": bereichsleiter.id}]
