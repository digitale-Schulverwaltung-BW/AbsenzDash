import datetime

import pytest
from sqlalchemy import select

from app.models.klasse import Klasse
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
    """Simuliert einen echten Klassenwechsel: der Zaehlerstand entstand unter einer klassen-
    spezifischen Regel fuer die alte Klasse; zwischen Entstehung und Massnahmen-Erfassung wechselt
    der Schueler die Klasse, wodurch eine ANDERE klassen-spezifische Regel (gleicher typ) fuer ihn
    zustaendig wird. Beide Regeln sind fuer den Schueler zu ihrer jeweiligen Zeit tatsaechlich die
    aufgeloeste Regel - daher muss der Reset stattfinden und regel_id auf die neue Regel zeigen."""
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_a.id)
    alte_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_a.id)
    db_session.add_all([schueler, alte_regel])
    await db_session.flush()
    # Zaehlerstand entstand urspruenglich unter alte_regel, waehrend der Schueler noch in klasse_a war
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", alte_regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    # Klassenwechsel: Schueler wechselt von klasse_a nach klasse_b
    schueler.klasse_id = klasse_b.id
    neue_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_b.id)
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


@pytest.mark.asyncio
async def test_record_massnahme_does_not_reset_when_linked_regel_does_not_apply_to_student(db_session):
    """Der MassnahmenTyp ist NUR mit einer klassen-spezifischen Regel fuer eine ANDERE Klasse
    verknuepft als die, in der der Schueler aktuell ist. Die fuer den Schueler tatsaechlich
    aufgeloeste Regel (schulweit, da keine klassen-/abteilungsspezifische Regel fuer seine Klasse
    existiert) ist nicht die verknuepfte Regel - der Zaehlerstand darf daher NICHT zurueckgesetzt
    (oder gar neu angelegt) werden."""
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_a.id)
    schulweite_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    andere_klasse_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_b.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, schulweite_regel, andere_klasse_regel, typ, nutzer])
    await db_session.flush()

    # Zaehlerstand des Schuelers existiert bereits, gefuehrt unter der fuer ihn tatsaechlich
    # geltenden schulweiten Regel.
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", schulweite_regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    # MassnahmenTyp ist nur mit der Regel fuer klasse_b verknuepft - nicht mit der schulweiten,
    # die fuer diesen Schueler (in klasse_a) tatsaechlich aufgeloest wird.
    await db_session.execute(
        massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=andere_klasse_regel.id)
    )
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
    assert len(rows) == 1  # kein neuer Zaehlerstand fuer den unbeteiligten Schueler angelegt
    assert rows[0].aktueller_stand == 5  # nicht zurueckgesetzt
    assert rows[0].regel_id == schulweite_regel.id  # unveraendert
