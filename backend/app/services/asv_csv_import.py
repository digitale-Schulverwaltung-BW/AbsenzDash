from __future__ import annotations

import csv
import logging
import os
import shutil
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr

logger = logging.getLogger(__name__)


def _parse_datum(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%d.%m.%Y").date()


def _archiviere_csv(quelle: str, archiv_verzeichnis: str, schuljahr_name: str) -> None:
    """Kopiert die soeben verarbeitete ASV-CSV nach <archiv_verzeichnis>/<schuljahr_name>.csv
    (ein Stand pro Schuljahr, bei jedem weiteren Import desselben Jahres ueberschrieben) -- siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md. schuljahr_name
    enthaelt ein "/" (z.B. "2025/2026", siehe app/models/schuljahr.py) -- wird durch "-" ersetzt,
    da ein woertliches "/" im Dateinamen auf Linux ein Unterverzeichnis erzeugen wuerde statt
    einer einzelnen Datei. archiv_verzeichnis muss auf ein persistentes Volume zeigen
    (ASV_CSV_ARCHIVE_DIR), nicht das fluechtige Live-Mount-Verzeichnis von asv_csv_path."""
    os.makedirs(archiv_verzeichnis, exist_ok=True)
    ziel_dateiname = f"{schuljahr_name.replace('/', '-')}.csv"
    shutil.copyfile(quelle, os.path.join(archiv_verzeichnis, ziel_dateiname))


def _erwartete_spalten() -> list[str]:
    return [
        settings.asv_csv_column_externe_id,
        settings.asv_csv_column_vorname,
        settings.asv_csv_column_nachname,
        settings.asv_csv_column_klasse,
        settings.asv_csv_column_eintrittsdatum,
        settings.asv_csv_column_austrittsdatum,
    ]


def lese_asv_csv_zeilen(pfad: str) -> list[dict[str, str]]:
    """Oeffnet+parst eine ASV-CSV-Datei (Spalten-Validierung, UTF-8, Delimiter ';') und liefert
    die Rohzeilen als Liste von dicts (Spaltenname -> Wert), OHNE sie zu verarbeiten -- gemeinsame
    Grundlage fuer den laufenden Live-Import (import_schueler) und den rueckwirkenden
    Admin-Import (schuljahr_historie_import_service.py), siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md. Wirft ValueError
    bei fehlenden Header-Spalten, OSError bei ungueltiger Kodierung -- identische
    Fehlerbehandlung wie zuvor inline in import_schueler."""
    try:
        with open(pfad, encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=";")
            fehlende_spalten = [s for s in _erwartete_spalten() if s not in (reader.fieldnames or [])]
            if fehlende_spalten:
                raise ValueError(f"ASV-CSV: fehlende Spalten im Header: {fehlende_spalten}")
            return list(reader)
    except UnicodeDecodeError as exc:
        raise OSError(f"ASV-CSV: Datei {pfad} ist nicht UTF-8-kodiert: {exc}") from exc


async def import_schueler(db: AsyncSession) -> None:
    """ASV-BW-CSV -> schueler (Upsert nach externe_id), TECH-SPEC.md Abschnitt 1.3.

    Überspringt Parsen+Upsert, wenn die Datei-mtime seit dem letzten Lauf unverändert ist.

    Pflegt zusätzlich zu schueler.klasse_id einen schueler_klasse_historie-Snapshot für das
    aktuelle Schuljahr (einstellung.aktuelles_schuljahr_id) - siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md.

    Archiviert bei jedem tatsächlich verarbeiteten Lauf (mtime-Check nicht übersprungen) die
    rohe ASV-CSV zusätzlich nach <asv_csv_archive_dir>/<schuljahr.name mit "/" -> "-">.csv (ein
    Stand pro Schuljahr, überschrieben bei jedem weiteren Import desselben Jahres), sofern
    einstellung.aktuelles_schuljahr_id gesetzt ist - siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md.
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

    rows = lese_asv_csv_zeilen(settings.asv_csv_path)

    uebersprungene_zeilen = 0
    for zeilen_nr, row in enumerate(rows, start=2):
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

    if einstellung.aktuelles_schuljahr_id is not None:
        aktuelles_schuljahr = await db.get(Schuljahr, einstellung.aktuelles_schuljahr_id)
        if aktuelles_schuljahr is not None:
            _archiviere_csv(settings.asv_csv_path, settings.asv_csv_archive_dir, aktuelles_schuljahr.name)

    einstellung.asv_csv_zuletzt_importiert_mtime = mtime
    await db.commit()
