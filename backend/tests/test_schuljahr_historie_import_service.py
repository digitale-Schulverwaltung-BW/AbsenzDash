from datetime import date
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr
from app.services import schuljahr_historie_import_service

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


def _upload(rows: list[str]) -> UploadFile:
    inhalt = ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")
    return UploadFile(filename="archiv.csv", file=BytesIO(inhalt))


async def _seed_schuljahr(db_session, schuljahr_id: int = 27) -> Schuljahr:
    schuljahr = Schuljahr(id=schuljahr_id, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.commit()
    return schuljahr


@pytest.mark.asyncio
async def test_preview_import_counts_known_and_new_schueler(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    db_session.add(Schueler(externe_id="ext-bekannt", vorname="Alt", nachname="Bekannt"))
    await db_session.commit()

    upload = _upload(
        [
            '"a";"a";"ext-bekannt";"Bekannt";"Alt";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
            '"b";"b";"ext-neu";"Neu";"Person";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
        ]
    )

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.zeilen_gesamt == 2
    assert preview.schueler_bekannt == 1
    assert preview.schueler_neu == 1
    assert preview.unbekannte_klassen == []
    assert preview.uebersprungene_zeilen == 0


@pytest.mark.asyncio
async def test_preview_import_reports_unknown_klasse_names(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    upload = _upload(['"a";"a";"ext-1";"N";"V";"";"UNBEKANNT";"01.01.1990";"";"17.03.2020";"ja"'])

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.unbekannte_klassen == ["UNBEKANNT"]


@pytest.mark.asyncio
async def test_preview_import_fetches_missing_klassen_from_webuntis(db_session, monkeypatch):
    """Fehlt eine per Klassenname referenzierte klasse-Zeile fuers gewaehlte Schuljahr komplett,
    wird sync_klassen (Plan 16) automatisch mit schoolyear_id=<gewaehltes Jahr> nachgezogen,
    bevor der endgueltige unbekannte_klassen-Abgleich passiert -- siehe Design-Dok Abschnitt 3."""
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    async def _fake_sync_klassen(client, db, schoolyear_id):
        db.add(Klasse(webuntis_id=1, name="NACHGEZOGEN", schuljahr_id=schoolyear_id))
        await db.flush()

    async def _fake_aenter(self):
        return self

    async def _fake_aexit(self, *args):
        return None

    monkeypatch.setattr(schuljahr_historie_import_service, "sync_klassen", _fake_sync_klassen)
    monkeypatch.setattr(schuljahr_historie_import_service.WebUntisClient, "__aenter__", _fake_aenter)
    monkeypatch.setattr(schuljahr_historie_import_service.WebUntisClient, "__aexit__", _fake_aexit)

    upload = _upload(['"a";"a";"ext-1";"N";"V";"";"NACHGEZOGEN";"01.01.1990";"";"17.03.2020";"ja"'])

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.unbekannte_klassen == []


@pytest.mark.asyncio
async def test_preview_import_raises_404_for_unknown_schuljahr(db_session):
    from fastapi import HTTPException

    upload = _upload(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"'])

    with pytest.raises(HTTPException) as exc_info:
        await schuljahr_historie_import_service.preview_import(db_session, 999999, upload)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_preview_import_counts_skipped_rows_with_broken_dates(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    upload = _upload(
        [
            '"a";"a";"ext-ok";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"',
            '"b";"b";"ext-broken";"N";"V";"";"";"01.01.1990";"";"NICHT-EIN-DATUM";"ja"',
        ]
    )

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.zeilen_gesamt == 1
    assert preview.uebersprungene_zeilen == 1
