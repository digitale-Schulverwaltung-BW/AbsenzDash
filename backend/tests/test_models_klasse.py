import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.schuljahr import Schuljahr


async def _seed_schuljahre(db_session) -> tuple[Schuljahr, Schuljahr]:
    from datetime import date

    alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([alt, neu])
    await db_session.flush()
    return alt, neu


@pytest.mark.asyncio
async def test_klasse_roundtrip(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    klasse = Klasse(
        webuntis_id=3499, name="10a", webuntis_teacher1_id=63, webuntis_teacher2_id=434, schuljahr_id=schuljahr.id
    )
    db_session.add(klasse)
    await db_session.commit()

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    loaded = result.scalar_one()
    assert loaded.name == "10a"
    assert loaded.webuntis_teacher1_id == 63
    assert loaded.schuljahr_id == schuljahr.id


@pytest.mark.asyncio
async def test_klasse_schuljahr_id_is_required(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    db_session.add(Klasse(webuntis_id=1, name="10a"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_klasse_allows_same_webuntis_id_in_different_schuljahre(db_session):
    alt, neu = await _seed_schuljahre(db_session)
    db_session.add_all(
        [
            Klasse(webuntis_id=1, name="10a", schuljahr_id=alt.id),
            Klasse(webuntis_id=1, name="10b", schuljahr_id=neu.id),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 1))
    rows = result.scalars().all()
    assert {r.schuljahr_id for r in rows} == {alt.id, neu.id}


@pytest.mark.asyncio
async def test_klasse_forbids_same_webuntis_id_and_schuljahr_id_twice(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    db_session.add(Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id))
    await db_session.commit()

    db_session.add(Klasse(webuntis_id=1, name="10a-dup", schuljahr_id=schuljahr.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_bereich_klasse_association(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    klasse = Klasse(webuntis_id=1, name="11b", schuljahr_id=schuljahr.id)
    bereich = Bereich(name="Kaufmännischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()

    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    result = await db_session.execute(select(bereich_klasse))
    row = result.first()
    assert row.bereich_id == bereich.id
    assert row.klasse_id == klasse.id
