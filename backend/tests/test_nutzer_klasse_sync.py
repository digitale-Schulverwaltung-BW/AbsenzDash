import pytest
from sqlalchemy import select

from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.services.nutzer_klasse_sync import seed_nutzer_klasse_from_webuntis


@pytest.mark.asyncio
async def test_seeds_nutzer_klasse_for_matching_teacher(db_session, schuljahr):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft", webuntis_teacher_id=63)
    klasse = Klasse(webuntis_id=3499, name="10a", webuntis_teacher1_id=63, schuljahr_id=schuljahr.id)
    db_session.add_all([nutzer, klasse])
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].nutzer_id == nutzer.id
    assert rows[0].klasse_id == klasse.id
    assert rows[0].quelle == "webuntis_seed"


@pytest.mark.asyncio
async def test_skips_teacher_without_matching_nutzer(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="11b", webuntis_teacher1_id=999, schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_dedupes_when_both_teacher_slots_resolve_to_same_nutzer(db_session, schuljahr):
    nutzer = Nutzer(wp_user_id="u2", email="c@d.de", name="C", rolle="klassenlehrkraft", webuntis_teacher_id=77)
    klasse = Klasse(webuntis_id=42, name="9c", webuntis_teacher1_id=77, webuntis_teacher2_id=77, schuljahr_id=schuljahr.id)
    db_session.add_all([nutzer, klasse])
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].nutzer_id == nutzer.id
    assert rows[0].klasse_id == klasse.id


@pytest.mark.asyncio
async def test_preserves_manual_assignments_and_refreshes_seeded_ones(db_session, schuljahr):
    nutzer_alt = Nutzer(wp_user_id="alt", email="alt@b.de", name="Alt", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    nutzer_neu = Nutzer(wp_user_id="neu", email="neu@b.de", name="Neu", rolle="klassenlehrkraft", webuntis_teacher_id=2)
    nutzer_co = Nutzer(wp_user_id="co", email="co@b.de", name="Co", rolle="klassenlehrkraft")
    klasse = Klasse(webuntis_id=1, name="10a", webuntis_teacher1_id=1, schuljahr_id=schuljahr.id)
    db_session.add_all([nutzer_alt, nutzer_neu, nutzer_co, klasse])
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)
    db_session.add(NutzerKlasse(nutzer_id=nutzer_co.id, klasse_id=klasse.id, quelle="manuell"))
    await db_session.commit()

    klasse.webuntis_teacher1_id = 2
    await db_session.commit()
    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    rows = {(row.nutzer_id, row.quelle) for row in result.scalars().all()}
    assert (nutzer_neu.id, "webuntis_seed") in rows
    assert (nutzer_co.id, "manuell") in rows
    assert (nutzer_alt.id, "webuntis_seed") not in rows
