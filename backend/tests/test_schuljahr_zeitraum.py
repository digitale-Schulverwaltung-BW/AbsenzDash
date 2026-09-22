from datetime import date

import pytest
from fastapi import HTTPException

from app.models.einstellung import Einstellung
from app.models.schuljahr import Schuljahr
from app.services.schuljahr_zeitraum import resolve_schuljahr_zeitraum


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_none_when_no_schuljahr_id_given(db_session):
    von, bis = await resolve_schuljahr_zeitraum(db_session, None)
    assert (von, bis) == (None, None)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_none_when_schuljahr_id_matches_aktuelles(db_session, schuljahr):
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr.id))
    await db_session.commit()

    von, bis = await resolve_schuljahr_zeitraum(db_session, schuljahr.id)

    assert (von, bis) == (None, None)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_returns_bounds_for_past_schuljahr(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await db_session.commit()

    von, bis = await resolve_schuljahr_zeitraum(db_session, schuljahr_alt.id)

    assert von == date(2024, 9, 9)
    assert bis == date(2025, 7, 30)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_returns_bounds_when_no_einstellung_row_exists(db_session, schuljahr):
    # Kein Einstellung-Row -> "aktuelles_schuljahr_id" ist unbestimmt, jede uebergebene schuljahr_id
    # zaehlt dann als "vergangenes/anderes Schuljahr" (Historie-Modus).
    von, bis = await resolve_schuljahr_zeitraum(db_session, schuljahr.id)
    assert (von, bis) == (schuljahr.start_datum, schuljahr.end_datum)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_404s_for_unknown_schuljahr_id(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await resolve_schuljahr_zeitraum(db_session, 999999)
    assert exc_info.value.status_code == 404
