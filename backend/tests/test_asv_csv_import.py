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
async def test_import_raises_value_error_on_missing_header_column(db_session, tmp_path):
    header_ohne_idnumber = "login;shortname;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"
    path = tmp_path / "schueler.csv"
    path.write_text(
        "\n".join(
            [
                header_ohne_idnumber,
                '"abcd-0018";"abcd-0018";"Mustermann";"Frank";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        await import_schueler(db_session)


@pytest.mark.asyncio
async def test_import_skips_broken_row_but_keeps_valid_rows(db_session, tmp_path):
    _write_csv(
        tmp_path,
        [
            '"a";"a";"ext-uuid-ok-1";"Nachname1";"Vorname1";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
            # kaputtes Datum in Eintrittsdatum -> _parse_datum wirft ValueError, Zeile wird uebersprungen
            '"b";"b";"ext-uuid-broken";"Nachname2";"Vorname2";"";"AME56";"01.01.1990";"";"NICHT-EIN-DATUM";"ja"',
            '"c";"c";"ext-uuid-ok-2";"Nachname3";"Vorname3";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
        ],
    )

    await import_schueler(db_session)

    result_ok_1 = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-ok-1"))
    assert result_ok_1.scalar_one_or_none() is not None

    result_ok_2 = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-ok-2"))
    assert result_ok_2.scalar_one_or_none() is not None

    result_broken = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-broken"))
    assert result_broken.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_import_raises_os_error_on_invalid_encoding(db_session, tmp_path):
    path = tmp_path / "schueler.csv"
    # Latin-1-kodierter Umlaut (0xFC = 'ü'), der als UTF-8 nicht dekodierbar ist.
    zeilen = [
        HEADER.encode("utf-8"),
        b'"x";"x";"ext-uuid-bad-encoding";"M\xfcller";"Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
    ]
    path.write_bytes(b"\n".join(zeilen) + b"\n")

    with pytest.raises(OSError):
        await import_schueler(db_session)


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
