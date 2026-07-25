from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.services.asv_csv_import import import_schueler

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "schueler.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _set_csv_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asv_csv_path", str(tmp_path / "schueler.csv"))


@pytest.mark.asyncio
async def test_import_creates_schueler_with_matching_klasse(db_session, tmp_path):
    db_session.add(Klasse(webuntis_id=1, name="AME56"))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"abcd-0018";"abcd-0018";"ext-uuid-1";"Mustermann";"Frank";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-1"))
    schueler = result.scalar_one()
    assert schueler.vorname == "Frank"
    assert schueler.nachname == "Mustermann"
    assert schueler.aktiv is True
    klasse_result = await db_session.execute(select(Klasse).where(Klasse.id == schueler.klasse_id))
    assert klasse_result.scalar_one().name == "AME56"


@pytest.mark.asyncio
async def test_import_leaves_klasse_id_null_for_unknown_klasse(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-2";"Nachname";"Vorname";"";"UNBEKANNT";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-2"))
    assert result.scalar_one().klasse_id is None


@pytest.mark.asyncio
async def test_import_marks_schueler_inactive_after_austrittsdatum(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-3";"Nachname";"Vorname";"";"AME56";"01.01.1990";"26.09.2025";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-3"))
    assert result.scalar_one().aktiv is False


@pytest.mark.asyncio
async def test_import_updates_existing_schueler_by_externe_id(db_session, tmp_path):
    db_session.add(Schueler(externe_id="ext-uuid-4", vorname="Alt", nachname="Name", aktiv=False))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-4";"Name";"Neu";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-4"))
    assert result.scalar_one().vorname == "Neu"


@pytest.mark.asyncio
async def test_import_skips_reprocessing_when_file_unchanged(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-5";"Nachname";"Vorname";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)
    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-5"))
    schueler = result.scalar_one()
    schueler.vorname = "ManuellGeaendert"
    await db_session.commit()

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-5"))
    assert result.scalar_one().vorname == "ManuellGeaendert"
