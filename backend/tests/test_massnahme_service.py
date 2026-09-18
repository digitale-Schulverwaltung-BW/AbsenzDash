import datetime

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import get_or_create_zaehlerstand
from app.services.massnahme_service import record_massnahme


@pytest.mark.asyncio
async def test_record_massnahme_resets_both_zaehlerstaende(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    fehlzeiten_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    klassenbuch_regel = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, fehlzeiten_regel, klassenbuch_regel, typ, nutzer])
    await db_session.flush()

    fz_zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", fehlzeiten_regel.id)
    fz_zaehlerstand.aktueller_stand = 5
    fz_zaehlerstand.erreichte_stufe_nr = 1
    kb_zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "klassenbuch", klassenbuch_regel.id)
    kb_zaehlerstand.aktueller_stand = 3
    kb_zaehlerstand.erreichte_stufe_nr = 1
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
    by_typ = {z.typ: z for z in result.scalars().all()}
    assert by_typ["fehlzeiten"].aktueller_stand == 0
    assert by_typ["fehlzeiten"].erreichte_stufe_nr is None
    assert by_typ["fehlzeiten"].letzter_reset_am == datetime.date(2026, 1, 20)
    assert by_typ["klassenbuch"].aktueller_stand == 0
    assert by_typ["klassenbuch"].erreichte_stufe_nr is None

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
async def test_record_massnahme_resets_by_typ_even_if_current_regel_differs_from_original(db_session, schuljahr):
    """Simuliert einen echten Klassenwechsel: der Zaehlerstand entstand unter einer klassen-
    spezifischen Regel fuer die alte Klasse; zwischen Entstehung und Massnahmen-Erfassung wechselt
    der Schueler die Klasse, wodurch eine ANDERE klassen-spezifische Regel (gleicher typ) fuer ihn
    zustaendig wird. Der Reset muss unter der jetzt aufgeloesten Regel erfolgen."""
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_a.id)
    alte_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_a.id)
    db_session.add_all([schueler, alte_regel])
    await db_session.flush()
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", alte_regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    schueler.klasse_id = klasse_b.id
    neue_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_b.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([neue_regel, typ, nutzer])
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
async def test_record_massnahme_skips_typ_with_no_applicable_regel(db_session):
    """Fuer 'klassenbuch' existiert (noch) keine Regel im System - der Reset fuer diesen typ wird
    uebersprungen, ohne Fehler, statt einen Zaehlerstand mit regel_id=None zu erzwingen."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    fehlzeiten_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, fehlzeiten_regel, typ, nutzer])
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
    assert len(rows) == 1
    assert rows[0].typ == "fehlzeiten"
    assert rows[0].aktueller_stand == 0


@pytest.mark.asyncio
async def test_record_massnahme_writes_audit_log_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, typ, nutzer])
    await db_session.flush()

    massnahme = await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "massnahme"))
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].aktion == "massnahme_erfasst"
    assert entries[0].resource_id == str(massnahme.id)
    assert entries[0].user_id == nutzer.id
