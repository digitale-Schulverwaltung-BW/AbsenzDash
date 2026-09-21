from __future__ import annotations

import os
import tempfile

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr
from app.schemas.admin import HistorieImportPreviewOut, HistorieImportResultOut
from app.services.asv_csv_import import _parse_datum, lese_asv_csv_zeilen
from app.services.webuntis_klassen_sync import sync_klassen


async def _schuljahr_oder_404(db: AsyncSession, schuljahr_id: int) -> Schuljahr:
    schuljahr = await db.get(Schuljahr, schuljahr_id)
    if schuljahr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Schuljahr")
    return schuljahr


async def _speichere_upload_temporaer(file: UploadFile) -> str:
    inhalt = await file.read()
    fd, pfad = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "wb") as tmp:
        tmp.write(inhalt)
    return pfad


def _parse_zeilen(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    """Parst externe_id/klasse_name/vorname/nachname aus den Rohzeilen (identisches
    Fehlerhandling wie import_schueler: KeyError/ValueError -> Zeile ueberspringen). Eintritts-/
    Austrittsdatum werden nur validiert, nicht weiterverwendet -- der historische Import ruehrt
    schueler.aktiv nicht an (Design-Dok Nicht-Ziel)."""
    geparste: list[dict[str, str]] = []
    uebersprungen = 0
    for row in rows:
        try:
            externe_id = row[settings.asv_csv_column_externe_id]
            klasse_name = row[settings.asv_csv_column_klasse]
            vorname = row[settings.asv_csv_column_vorname]
            nachname = row[settings.asv_csv_column_nachname]
            _parse_datum(row[settings.asv_csv_column_eintrittsdatum])
            _parse_datum(row[settings.asv_csv_column_austrittsdatum])
        except (KeyError, ValueError):
            uebersprungen += 1
            continue
        if not externe_id:
            uebersprungen += 1
            continue
        geparste.append(
            {"externe_id": externe_id, "klasse_name": klasse_name, "vorname": vorname, "nachname": nachname}
        )
    return geparste, uebersprungen


async def _klasse_id_by_name(db: AsyncSession, schuljahr_id: int) -> dict[str, int]:
    return dict(
        (await db.execute(select(Klasse.name, Klasse.id).where(Klasse.schuljahr_id == schuljahr_id))).all()
    )


async def _bekannte_externe_ids(db: AsyncSession, externe_ids: set[str]) -> set[str]:
    if not externe_ids:
        return set()
    result = await db.execute(select(Schueler.externe_id).where(Schueler.externe_id.in_(externe_ids)))
    return set(result.scalars().all())


async def _klassen_von_webuntis_nachziehen(db: AsyncSession, schuljahr_id: int) -> None:
    try:
        async with WebUntisClient(settings) as client:
            await sync_klassen(client, db, schoolyear_id=schuljahr_id)
    except WebUntisError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"WebUntis nicht erreichbar: {exc}")


async def _lese_und_parse_upload(file: UploadFile) -> tuple[list[dict[str, str]], int]:
    tmp_pfad = await _speichere_upload_temporaer(file)
    try:
        rows = lese_asv_csv_zeilen(tmp_pfad)
    except (ValueError, OSError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    finally:
        os.unlink(tmp_pfad)
    return _parse_zeilen(rows)


async def preview_import(db: AsyncSession, schuljahr_id: int, file: UploadFile) -> HistorieImportPreviewOut:
    """Vorschau vor dem eigentlichen Schreiben (siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md, Abschnitt 3):
    parst die hochgeladene CSV, matched Klassennamen gegen klasse-Zeilen des gewaehlten
    Schuljahres (fehlen sie komplett, wird per WebUntis getKlassen via sync_klassen
    nachgezogen), matched externe_id gegen bestehende schueler. Schreibt selbst NICHTS in die DB
    (der Klassen-Nachzug via sync_klassen ist ein Seiteneffekt von WebUntis-Daten, kein
    Schreiben rueckwirkend erfundener Daten -- bewusst in Kauf genommen, siehe Design-Dok)."""
    await _schuljahr_oder_404(db, schuljahr_id)
    geparste_zeilen, uebersprungen = await _lese_und_parse_upload(file)

    klasse_namen = {z["klasse_name"] for z in geparste_zeilen if z["klasse_name"]}
    klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)
    fehlende_namen = klasse_namen - set(klasse_id_by_name.keys())
    if fehlende_namen:
        await _klassen_von_webuntis_nachziehen(db, schuljahr_id)
        klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)
        fehlende_namen = klasse_namen - set(klasse_id_by_name.keys())

    externe_ids = {z["externe_id"] for z in geparste_zeilen}
    bekannte_externe_ids = await _bekannte_externe_ids(db, externe_ids)

    return HistorieImportPreviewOut(
        zeilen_gesamt=len(geparste_zeilen),
        schueler_bekannt=len(externe_ids & bekannte_externe_ids),
        schueler_neu=len(externe_ids - bekannte_externe_ids),
        unbekannte_klassen=sorted(fehlende_namen),
        uebersprungene_zeilen=uebersprungen,
    )


async def commit_import(
    db: AsyncSession, schuljahr_id: int, file: UploadFile, admin_nutzer_id: int
) -> HistorieImportResultOut:
    """Schreibt schueler_klasse_historie fuer schuljahr_id (Upsert je schueler_id) -- ruehrt
    schueler.klasse_id/aktiv/vorname/nachname fuer BESTEHENDE Schueler nicht an (das sind
    "aktuelle Wahrheit", siehe Design-Dok Nicht-Ziele). Fuer eine komplett unbekannte externe_id
    wird ein minimaler Schueler-Stammsatz angelegt (nur externe_id+Name; klasse_id/aktiv bleiben
    Spalten-Default, da fuer einen moeglicherweise laengst ausgeschiedenen Schueler nicht sinnvoll
    befuellbar). Idempotent: ein erneuter Import fuers selbe Schuljahr aktualisiert bestehende
    schueler_klasse_historie-Zeilen statt sie zu duplizieren (Update-Fall, z.B. eine spaeter
    aufgetauchte vollstaendigere Archiv-CSV)."""
    await _schuljahr_oder_404(db, schuljahr_id)
    geparste_zeilen, uebersprungen = await _lese_und_parse_upload(file)

    klasse_namen = {z["klasse_name"] for z in geparste_zeilen if z["klasse_name"]}
    klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)
    if klasse_namen - set(klasse_id_by_name.keys()):
        await _klassen_von_webuntis_nachziehen(db, schuljahr_id)
        klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)

    externe_ids = {z["externe_id"] for z in geparste_zeilen}
    existing_schueler = (
        await db.execute(select(Schueler).where(Schueler.externe_id.in_(externe_ids)))
    ).scalars().all()
    by_externe_id = {s.externe_id: s for s in existing_schueler}

    existing_historie = (
        await db.execute(select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schuljahr_id == schuljahr_id))
    ).scalars().all()
    historie_by_schueler_id = {h.schueler_id: h for h in existing_historie}

    neu_angelegte_schueler = 0
    zeilen_verarbeitet = 0
    for zeile in geparste_zeilen:
        klasse_id = klasse_id_by_name.get(zeile["klasse_name"])
        schueler = by_externe_id.get(zeile["externe_id"])
        if schueler is None:
            schueler = Schueler(externe_id=zeile["externe_id"], vorname=zeile["vorname"], nachname=zeile["nachname"])
            db.add(schueler)
            await db.flush()
            by_externe_id[zeile["externe_id"]] = schueler
            neu_angelegte_schueler += 1

        historie = historie_by_schueler_id.get(schueler.id)
        if historie is None:
            historie = SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_id, klasse_id=klasse_id)
            db.add(historie)
            historie_by_schueler_id[schueler.id] = historie
        else:
            historie.klasse_id = klasse_id
        zeilen_verarbeitet += 1

    db.add(
        AuditLog(
            user_id=admin_nutzer_id,
            aktion="admin_schuljahr_historie_import",
            resource_typ="schuljahr",
            resource_id=str(schuljahr_id),
            details={
                "schuljahr_id": schuljahr_id,
                "zeilen_gesamt": zeilen_verarbeitet,
                "neu_angelegte_schueler": neu_angelegte_schueler,
                "uebersprungene_zeilen": uebersprungen,
            },
        )
    )
    await db.commit()

    return HistorieImportResultOut(
        zeilen_verarbeitet=zeilen_verarbeitet,
        neu_angelegte_schueler=neu_angelegte_schueler,
        uebersprungene_zeilen=uebersprungen,
    )
