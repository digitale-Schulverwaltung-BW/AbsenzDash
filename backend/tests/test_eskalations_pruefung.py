import datetime

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
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
            schueler_id=schueler.id, regel_id=regel.id, aktueller_stand=0, letzter_reset_am=datetime.date(2026, 1, 15)
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
