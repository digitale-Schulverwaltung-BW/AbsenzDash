import pytest

from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import resolve_schwellwert_regel


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_prefers_klasse_specific(db_session):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=abteilung.id)
    db_session.add(klasse)
    await db_session.flush()

    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    abteilungsregel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id)
    klassenregel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse.id)
    db_session.add_all([schulweit, abteilungsregel, klassenregel])
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, klasse.id, "fehlzeiten")

    assert result.id == klassenregel.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_falls_back_to_abteilung(db_session):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=abteilung.id)
    db_session.add(klasse)
    await db_session.flush()

    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    abteilungsregel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id)
    db_session.add_all([schulweit, abteilungsregel])
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, klasse.id, "fehlzeiten")

    assert result.id == abteilungsregel.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_falls_back_to_schulweit_without_klasse(db_session):
    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(schulweit)
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, None, "fehlzeiten")

    assert result.id == schulweit.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_returns_none_when_no_rule_matches(db_session):
    result = await resolve_schwellwert_regel(db_session, None, "fehlzeiten")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_handles_nonexistent_klasse_id_gracefully(db_session):
    """Defensive: eine klasse_id ohne zugehoerige Klasse-Zeile darf nicht crashen, sondern soll
    auf die schulweite Regel zurueckfallen (kann in der Praxis nicht vorkommen, z.B. bei
    Race Conditions oder inkonsistenten Fremdschluesseln in Tests)."""
    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(schulweit)
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, 999999, "fehlzeiten")

    assert result.id == schulweit.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_falls_back_to_schulweit_when_klasse_has_no_abteilung(db_session):
    """Eine Klasse ohne Abteilung (abteilung_id=None) soll die Abteilungs-Auflösung ueberspringen und
    direkt auf die schulweite Regel zurueckfallen, statt zu crashen oder faelschlich None zu liefern."""
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=None)
    db_session.add(klasse)
    await db_session.flush()

    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(schulweit)
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, klasse.id, "fehlzeiten")

    assert result.id == schulweit.id
