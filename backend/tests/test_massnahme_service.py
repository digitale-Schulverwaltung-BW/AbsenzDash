import datetime

import pytest
from sqlalchemy import select

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import get_or_create_zaehlerstand
from app.services.massnahme_service import record_massnahme


@pytest.mark.asyncio
async def test_record_massnahme_resets_linked_zaehlerstand(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, regel, typ, nutzer])
    await db_session.flush()

    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel.id))
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", regel.id)
    zaehlerstand.aktueller_stand = 5
    zaehlerstand.erreichte_stufe_nr = 1
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.typ == "fehlzeiten"
        )
    )
    reloaded = result.scalar_one()
    assert reloaded.aktueller_stand == 0
    assert reloaded.erreichte_stufe_nr is None
    assert reloaded.letzter_reset_am == datetime.date(2026, 1, 20)
    assert reloaded.regel_id == regel.id

    massnahme_result = await db_session.execute(select(Massnahme).where(Massnahme.schueler_id == schueler.id))
    assert massnahme_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_record_massnahme_does_not_reset_when_flag_false(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, regel, typ, nutzer])
    await db_session.flush()

    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel.id))
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.typ == "fehlzeiten"
        )
    )
    assert result.scalar_one().aktueller_stand == 5


@pytest.mark.asyncio
async def test_record_massnahme_resets_by_typ_even_if_current_regel_differs_from_original(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    alte_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([schueler, alte_regel])
    await db_session.flush()
    # Zaehlerstand entstand urspruenglich unter alte_regel (z.B. vor einem Klassenwechsel)
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", alte_regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    neue_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=None)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([neue_regel, typ, nutzer])
    await db_session.flush()
    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=neue_regel.id))
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1  # gleiche Zeile, nicht eine neue - Zaehlerstand ist pro (schueler, typ), nicht pro regel
    assert rows[0].aktueller_stand == 0
    assert rows[0].regel_id == neue_regel.id  # zuletzt angewendete Regel aktualisiert
