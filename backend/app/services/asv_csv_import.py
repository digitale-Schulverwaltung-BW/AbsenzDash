from __future__ import annotations

import csv
import logging
import os
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie

logger = logging.getLogger(__name__)


def _parse_datum(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%d.%m.%Y").date()


async def import_schueler(db: AsyncSession) -> None:
    """ASV-BW-CSV -> schueler (Upsert nach externe_id), TECH-SPEC.md Abschnitt 1.3.

    Überspringt Parsen+Upsert, wenn die Datei-mtime seit dem letzten Lauf unverändert ist.

    Pflegt zusätzlich zu schueler.klasse_id einen schueler_klasse_historie-Snapshot für das
    aktuelle Schuljahr (einstellung.aktuelles_schuljahr_id) - siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md.
    """
    mtime = datetime.fromtimestamp(os.path.getmtime(settings.asv_csv_path), tz=timezone.utc)

    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None:
        einstellung = Einstellung()
        db.add(einstellung)
        await db.flush()

    if einstellung.asv_csv_zuletzt_importiert_mtime is not None and mtime <= einstellung.asv_csv_zuletzt_importiert_mtime:
        return

    klasse_id_by_name = dict(
        (
            await db.execute(
                select(Klasse.name, Klasse.id).where(Klasse.schuljahr_id == einstellung.aktuelles_schuljahr_id)
            )
        ).all()
    )
    existing = (await db.execute(select(Schueler))).scalars().all()
    by_externe_id = {schueler.externe_id: schueler for schueler in existing}

    historie_by_schueler_id: dict[int, SchuelerKlasseHistorie] = {}
    if einstellung.aktuelles_schuljahr_id is not None:
        historie_rows = (
            await db.execute(
                select(SchuelerKlasseHistorie).where(
                    SchuelerKlasseHistorie.schuljahr_id == einstellung.aktuelles_schuljahr_id
                )
            )
        ).scalars().all()
        historie_by_schueler_id = {h.schueler_id: h for h in historie_rows}

    heute = datetime.now(timezone.utc).date()

    erwartete_spalten = [
        settings.asv_csv_column_externe_id,
        settings.asv_csv_column_vorname,
        settings.asv_csv_column_nachname,
        settings.asv_csv_column_klasse,
        settings.asv_csv_column_eintrittsdatum,
        settings.asv_csv_column_austrittsdatum,
    ]

    try:
        with open(settings.asv_csv_path, encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=";")

            fehlende_spalten = [spalte for spalte in erwartete_spalten if spalte not in (reader.fieldnames or [])]
            if fehlende_spalten:
                raise ValueError(f"ASV-CSV: fehlende Spalten im Header: {fehlende_spalten}")

            uebersprungene_zeilen = 0
            for zeilen_nr, row in enumerate(reader, start=2):
                try:
                    externe_id = row[settings.asv_csv_column_externe_id]
                    klasse_name = row[settings.asv_csv_column_klasse]
                    eintrittsdatum = _parse_datum(row[settings.asv_csv_column_eintrittsdatum])
                    austrittsdatum = _parse_datum(row[settings.asv_csv_column_austrittsdatum])

                    klasse_id = klasse_id_by_name.get(klasse_name)
                    if klasse_id is None:
                        logger.warning("ASV-CSV: unbekannte Klasse %r für externe_id=%s", klasse_name, externe_id)

                    schueler = by_externe_id.get(externe_id)
                    if schueler is None:
                        schueler = Schueler(externe_id=externe_id)
                        db.add(schueler)
                        by_externe_id[externe_id] = schueler

                    schueler.vorname = row[settings.asv_csv_column_vorname]
                    schueler.nachname = row[settings.asv_csv_column_nachname]
                    schueler.klasse_id = klasse_id
                    schueler.aktiv = bool(
                        eintrittsdatum is not None
                        and eintrittsdatum <= heute
                        and (austrittsdatum is None or austrittsdatum >= heute)
                    )
                    schueler.klassenzuordnung_aktualisiert_am = datetime.now(timezone.utc)

                    if einstellung.aktuelles_schuljahr_id is not None and schueler.id is None:
                        # neue schueler.id wird fuer schueler_klasse_historie benoetigt
                        await db.flush()

                    if einstellung.aktuelles_schuljahr_id is not None:
                        historie = historie_by_schueler_id.get(schueler.id)
                        if historie is None:
                            historie = SchuelerKlasseHistorie(
                                schueler_id=schueler.id,
                                schuljahr_id=einstellung.aktuelles_schuljahr_id,
                                klasse_id=klasse_id,
                            )
                            db.add(historie)
                            historie_by_schueler_id[schueler.id] = historie
                        else:
                            historie.klasse_id = klasse_id
                except (KeyError, ValueError) as exc:
                    uebersprungene_zeilen += 1
                    logger.warning("ASV-CSV: Zeile %d übersprungen (%s)", zeilen_nr, exc)
                    continue

            if uebersprungene_zeilen:
                logger.warning("ASV-CSV: %d Zeile(n) wegen Fehlern übersprungen", uebersprungene_zeilen)
    except UnicodeDecodeError as exc:
        raise OSError(f"ASV-CSV: Datei {settings.asv_csv_path} ist nicht UTF-8-kodiert: {exc}") from exc

    einstellung.asv_csv_zuletzt_importiert_mtime = mtime
    await db.commit()
