import os
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr
from app.services.asv_csv_import import import_schueler

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "schueler.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _set_csv_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asv_csv_path", str(tmp_path / "schueler.csv"))


@pytest.fixture(autouse=True)
def _set_csv_archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asv_csv_archive_dir", str(tmp_path / "archiv"))


async def _seed_aktuelles_schuljahr(db_session, schuljahr_id: int = 30) -> Schuljahr:
    schuljahr = Schuljahr(id=schuljahr_id, name="2025/2026", start_datum=date(2025, 9, 8), end_datum=date(2026, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_id))
    await db_session.commit()
    return schuljahr


@pytest.mark.asyncio
async def test_import_creates_schueler_with_matching_klasse(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
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
async def test_import_upserts_schueler_klasse_historie_for_aktuelles_schuljahr(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-hist";"Name";"Vor";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-hist"))).scalar_one()
    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
        )
    ).scalar_one()
    assert historie.schuljahr_id == schuljahr.id
    assert historie.klasse_id == schueler.klasse_id


@pytest.mark.asyncio
async def test_import_updates_existing_historie_row_on_reimport(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    klasse_alt = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_neu = Klasse(webuntis_id=2, name="BME12", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-uuid-hist2", vorname="A", nachname="B", klasse_id=klasse_alt.id)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse_alt.id))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-hist2";"B";"A";"";"BME12";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
        )
    ).scalar_one()
    assert historie.klasse_id == klasse_neu.id


@pytest.mark.asyncio
async def test_import_skips_historie_write_when_no_aktuelles_schuljahr(db_session, tmp_path):
    """Bootstrap-Edge-Case (in Produktion nicht erreichbar, da import_schueler ausschliesslich
    aus run_sync_once NACH resolve_aktuelles_schuljahr aufgerufen wird, siehe sync_orchestrator.py)
    - import_schueler darf trotzdem nicht crashen, wenn direkt ohne Einstellung aufgerufen."""
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-nohist";"Name";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-nohist"))).scalar_one()
    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
        )
    ).scalar_one_or_none()
    assert historie is None


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


@pytest.mark.asyncio
async def test_import_archives_csv_under_schuljahr_name(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-archiv-1";"Name";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    archiv_datei = Path(settings.asv_csv_archive_dir) / "2025-2026.csv"
    assert archiv_datei.exists()
    assert archiv_datei.read_text(encoding="utf-8") == Path(settings.asv_csv_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_import_overwrites_archive_on_reimport_of_same_schuljahr(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    _write_csv(tmp_path, ['"x";"x";"ext-archiv-2";"Alt";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'])
    await import_schueler(db_session)

    # neue mtime erzwingen, damit der zweite Lauf nicht per mtime-Check uebersprungen wird
    neue_zeit = datetime.now().timestamp() + 5
    _write_csv(tmp_path, ['"x";"x";"ext-archiv-2";"Neu";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'])
    os.utime(settings.asv_csv_path, (neue_zeit, neue_zeit))

    await import_schueler(db_session)

    archiv_datei = Path(settings.asv_csv_archive_dir) / "2025-2026.csv"
    inhalt = archiv_datei.read_text(encoding="utf-8")
    assert '"Neu"' in inhalt
    assert '"Alt"' not in inhalt
    # genau eine Datei pro Schuljahr, kein "eine Datei pro Import"
    assert len(list(Path(settings.asv_csv_archive_dir).iterdir())) == 1


@pytest.mark.asyncio
async def test_import_skips_archiving_when_no_aktuelles_schuljahr(db_session, tmp_path):
    _write_csv(tmp_path, ['"x";"x";"ext-archiv-3";"Name";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'])

    await import_schueler(db_session)

    assert not Path(settings.asv_csv_archive_dir).exists() or list(Path(settings.asv_csv_archive_dir).iterdir()) == []


def test_lese_asv_csv_zeilen_returns_parsed_rows(tmp_path):
    from app.services.asv_csv_import import lese_asv_csv_zeilen

    path = _write_csv(tmp_path, ['"a";"a";"ext-1";"Nachname";"Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'])

    rows = lese_asv_csv_zeilen(str(path))

    assert len(rows) == 1
    assert rows[0]["idnumber"] == "ext-1"


def test_lese_asv_csv_zeilen_raises_value_error_on_missing_header_column(tmp_path):
    from app.services.asv_csv_import import lese_asv_csv_zeilen

    header_ohne_idnumber = "login;shortname;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"
    path = tmp_path / "schueler.csv"
    path.write_text(header_ohne_idnumber + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        lese_asv_csv_zeilen(str(path))


def test_lese_asv_csv_zeilen_raises_os_error_on_invalid_encoding(tmp_path):
    from app.services.asv_csv_import import lese_asv_csv_zeilen

    path = tmp_path / "schueler.csv"
    zeilen = [HEADER.encode("utf-8"), b'"x";"x";"ext-1";"M\xfcller";"Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"']
    path.write_bytes(b"\n".join(zeilen) + b"\n")

    with pytest.raises(OSError):
        lese_asv_csv_zeilen(str(path))
