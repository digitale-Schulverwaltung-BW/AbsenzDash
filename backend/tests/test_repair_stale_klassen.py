from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr
from app.models.schwellwert_regel import SchwellwertRegel
from scripts.repair_stale_klassen import RepairAborted, format_report, repair_stale_klassen

ALT, NEU = 28, 29
MTIME = datetime(2026, 9, 20, tzinfo=timezone.utc)


async def _seed(db, *, mit_sibling: bool = True):
    """Prod-Szenario: Geister-Klasse (webuntis_id 3511) im aktuellen Schuljahr 29, gleiche webuntis_id
    als echte Vorjahres-Klasse in 28, dazu die echte neue Klasse (webuntis_id 3833) in 29."""
    db.add_all(
        [
            Schuljahr(id=ALT, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29)),
            Schuljahr(id=NEU, name="2026/2027", start_datum=date(2026, 9, 14), end_datum=date(2027, 7, 28)),
        ]
    )
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db.add(abteilung)
    await db.flush()
    ghost = Klasse(webuntis_id=3511, name="1ME", abteilung_id=abteilung.id, schuljahr_id=NEU)
    real = Klasse(webuntis_id=3833, name="2ME", abteilung_id=abteilung.id, schuljahr_id=NEU)
    db.add_all([ghost, real])
    old = None
    if mit_sibling:
        old = Klasse(webuntis_id=3511, name="1ME", abteilung_id=abteilung.id, schuljahr_id=ALT)
        db.add(old)
    db.add(Einstellung(aktuelles_schuljahr_id=NEU, asv_csv_zuletzt_importiert_mtime=MTIME))
    await db.flush()

    schueler = Schueler(externe_id="s1", vorname="A", nachname="B", klasse_id=ghost.id, aktiv=True)
    db.add(schueler)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="N", rolle="klassenlehrkraft")
    db.add(nutzer)
    await db.flush()
    db.add_all(
        [
            SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=ALT, klasse_id=ghost.id),
            SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=NEU, klasse_id=ghost.id),
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=ghost.id, quelle="webuntis_seed"),
        ]
    )
    bereich = Bereich(abteilung_id=abteilung.id, name="Mechatronik")
    db.add(bereich)
    await db.flush()
    for klasse in (ghost, real):
        await db.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db.commit()
    return ghost, real, old, schueler


def _client(rows=None):
    client = AsyncMock()
    client.call.return_value = [{"id": 3833, "name": "2ME"}] if rows is None else rows
    return client


async def _ids(db, stmt):
    db.expire_all()
    return sorted((await db.execute(stmt)).scalars().all())


@pytest.mark.asyncio
async def test_apply_merges_ghost_into_older_year_klasse(db_session):
    ghost, real, old, schueler = await _seed(db_session)
    ghost_id, real_id, old_id, schueler_id = ghost.id, real.id, old.id, schueler.id
    client = _client()

    report = await repair_stale_klassen(db_session, client, apply=True)

    client.call.assert_awaited_once_with("getKlassen", {"schoolyearId": NEU})
    assert [(e.id, e.webuntis_id, e.target_id) for e in report.merged] == [(ghost_id, 3511, old_id)]
    assert (report.merged[0].schueler, report.merged[0].historie_repoint, report.merged[0].historie_null) == (1, 1, 1)
    assert report.merged[0].nutzer_klasse == 1
    assert report.unresolved == [] and report.rule_blocked == []

    assert await _ids(db_session, select(Klasse.id)) == sorted([real_id, old_id])
    assert await _ids(db_session, select(Schueler.klasse_id)) == [old_id]
    historie = {
        (h.schuljahr_id, h.klasse_id)
        for h in (await db_session.execute(select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler_id))).scalars()
    }
    assert historie == {(ALT, old_id), (NEU, None)}
    assert await _ids(db_session, select(NutzerKlasse.id)) == []
    assert await _ids(db_session, select(bereich_klasse.c.klasse_id)) == [real_id]
    real_row = (await db_session.execute(select(Klasse).where(Klasse.id == real_id))).scalar_one()
    assert (real_row.name, real_row.webuntis_id, real_row.schuljahr_id) == ("2ME", 3833, NEU)
    einstellung = (await db_session.execute(select(Einstellung))).scalar_one()
    assert einstellung.asv_csv_zuletzt_importiert_mtime is None


@pytest.mark.asyncio
async def test_dry_run_changes_nothing(db_session):
    ghost, real, old, _ = await _seed(db_session)
    ghost_id, real_id, old_id = ghost.id, real.id, old.id

    report = await repair_stale_klassen(db_session, _client(), apply=False)

    assert [e.id for e in report.merged] == [ghost_id]
    assert await _ids(db_session, select(Klasse.id)) == sorted([ghost_id, real_id, old_id])
    assert await _ids(db_session, select(Schueler.klasse_id)) == [ghost_id]
    assert await _ids(db_session, select(SchuelerKlasseHistorie.klasse_id)) == [ghost_id, ghost_id]
    assert await _ids(db_session, select(bereich_klasse.c.klasse_id)) == sorted([ghost_id, real_id])
    assert len(await _ids(db_session, select(NutzerKlasse.id))) == 1
    einstellung = (await db_session.execute(select(Einstellung))).scalar_one()
    assert einstellung.asv_csv_zuletzt_importiert_mtime == MTIME


@pytest.mark.asyncio
async def test_stale_without_sibling_is_unresolved_and_untouched(db_session):
    ghost, real, _, _ = await _seed(db_session, mit_sibling=False)
    ghost_id, real_id = ghost.id, real.id

    report = await repair_stale_klassen(db_session, _client(), apply=True)

    assert report.merged == []
    assert [e.id for e in report.unresolved] == [ghost_id]
    assert await _ids(db_session, select(Klasse.id)) == sorted([ghost_id, real_id])
    assert await _ids(db_session, select(Schueler.klasse_id)) == [ghost_id]
    assert await _ids(db_session, select(bereich_klasse.c.klasse_id)) == sorted([ghost_id, real_id])
    einstellung = (await db_session.execute(select(Einstellung))).scalar_one()
    assert einstellung.asv_csv_zuletzt_importiert_mtime == MTIME


@pytest.mark.asyncio
async def test_stale_referenced_by_schwellwert_regel_is_untouched_and_reported(db_session):
    ghost, real, old, _ = await _seed(db_session)
    ghost_id, real_id, old_id = ghost.id, real.id, old.id
    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=ghost_id))
    await db_session.commit()

    report = await repair_stale_klassen(db_session, _client(), apply=True)

    assert report.merged == []
    assert [e.id for e in report.rule_blocked] == [ghost_id]
    assert await _ids(db_session, select(Klasse.id)) == sorted([ghost_id, real_id, old_id])
    assert await _ids(db_session, select(Schueler.klasse_id)) == [ghost_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], None])
async def test_empty_getklassen_aborts_without_changes(db_session, rows):
    ghost, real, old, _ = await _seed(db_session)
    ids = sorted([ghost.id, real.id, old.id])
    client = AsyncMock()
    client.call.return_value = rows

    with pytest.raises(RepairAborted):
        await repair_stale_klassen(db_session, client, apply=True)

    assert await _ids(db_session, select(Klasse.id)) == ids
    einstellung = (await db_session.execute(select(Einstellung))).scalar_one()
    assert einstellung.asv_csv_zuletzt_importiert_mtime == MTIME


@pytest.mark.asyncio
async def test_missing_aktuelles_schuljahr_aborts(db_session):
    db_session.add(Einstellung())
    await db_session.commit()

    with pytest.raises(RepairAborted):
        await repair_stale_klassen(db_session, _client(), apply=True)


@pytest.mark.asyncio
async def test_second_apply_run_is_noop(db_session):
    ghost, real, old, _ = await _seed(db_session)
    ids = sorted([real.id, old.id])
    await repair_stale_klassen(db_session, _client(), apply=True)
    # ASV-mtime simuliert einen zwischenzeitlich erfolgten Sync
    einstellung = (await db_session.execute(select(Einstellung))).scalar_one()
    einstellung.asv_csv_zuletzt_importiert_mtime = MTIME
    await db_session.commit()

    report = await repair_stale_klassen(db_session, _client(), apply=True)

    assert report.merged == [] and report.unresolved == [] and report.rule_blocked == []
    assert await _ids(db_session, select(Klasse.id)) == ids
    einstellung = (await db_session.execute(select(Einstellung))).scalar_one()
    assert einstellung.asv_csv_zuletzt_importiert_mtime == MTIME


@pytest.mark.asyncio
async def test_format_report_mentions_mode_without_personal_data(db_session):
    await _seed(db_session)
    dry = "\n".join(format_report(await repair_stale_klassen(db_session, _client(), apply=False)))
    assert "DRY-RUN - nothing changed, use --apply" in dry and "1ME / 3511" in dry
    assert "Schueler" in dry
    applied = "\n".join(format_report(await repair_stale_klassen(db_session, _client(), apply=True)))
    assert "APPLIED" in applied
