"""Einmaliges Reparatur-Skript: raeumt "Geister-Klassen" im aktuellen Schuljahr auf.

Ursache: Die Alembic-Migration 935e452806fd (Plan 16) hat beim Anlegen von klasse.schuljahr_id ALLE
bis dahin vorhandenen klasse-Zeilen dem damaligen einstellung.aktuelles_schuljahr_id zugeordnet -
das war bereits das NEUE Schuljahr, obwohl die Zeilen die Klassen des Vorjahres waren. WebUntis
vergibt pro Schuljahr neue Klassen-IDs; sync_klassen legt fuer das neue Jahr also neue Zeilen an und
loescht nie etwas, die alten Zeilen blieben als Geister im aktuellen Schuljahr zurueck (jede Klasse
erscheint doppelt, u.a. in den Bereichs-Vergleichen).

Vorgehen: Als Geister gelten klasse-Zeilen des aktuellen Schuljahres, deren webuntis_id von
getKlassen(schoolyearId=aktuelles Schuljahr) nicht mehr geliefert wird. Jede Geister-Klasse wird in
ihre gleichnamige Zeile eines aelteren Schuljahres (gleiche webuntis_id) hineingemerged:
schueler.klasse_id und schueler_klasse_historie werden umgehaengt (Historie-Zeilen des aktuellen
Schuljahres auf NULL = "unbekannt", der naechste ASV-Import fuellt sie fuer aktive Schueler neu),
nutzer_klasse/bereich_klasse verschwinden per ON DELETE CASCADE mit der Geister-Klasse. Geister ohne
Ziel-Zeile oder mit Verweis aus schwellwert_regel bleiben unangetastet und werden nur gemeldet.
Danach wird bereich_klasse neu aufgebaut und der ASV-mtime zurueckgesetzt, damit der naechste
Sync die CSV erneut einliest.

Nutzung (einmalig, im laufenden Backend-Container; Standard ist ein Trockenlauf):
    python -m scripts.repair_stale_klassen            # Bericht, aendert nichts
    python -m scripts.repair_stale_klassen --apply    # fuehrt die Aenderungen in EINER Transaktion aus
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisClient
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.webuntis_bereich_sync import sync_bereiche

logger = logging.getLogger(__name__)


class RepairAborted(RuntimeError):
    """Abbruch vor jeder Aenderung (fehlendes Schuljahr, leere getKlassen-Antwort)."""


@dataclass
class StaleKlasse:
    id: int
    name: str
    webuntis_id: int
    target_id: int | None
    schueler: int = 0
    historie_repoint: int = 0
    historie_null: int = 0
    nutzer_klasse: int = 0
    nutzer_klasse_manuell: int = 0
    regel_referenziert: bool = False


@dataclass
class RepairReport:
    schuljahr_id: int
    apply: bool
    merged: list[StaleKlasse] = field(default_factory=list)
    unresolved: list[StaleKlasse] = field(default_factory=list)
    rule_blocked: list[StaleKlasse] = field(default_factory=list)


async def repair_stale_klassen(db: AsyncSession, client: WebUntisClient, apply: bool) -> RepairReport:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None or einstellung.aktuelles_schuljahr_id is None:
        raise RepairAborted("einstellung.aktuelles_schuljahr_id ist nicht gesetzt - Abbruch, nichts geaendert.")
    schuljahr_id = einstellung.aktuelles_schuljahr_id

    rows = await client.call("getKlassen", {"schoolyearId": schuljahr_id})
    if not rows:
        raise RepairAborted(
            f"getKlassen lieferte fuer Schuljahr {schuljahr_id} keine Klassen - Abbruch, nichts geaendert "
            "(sonst wuerden alle Klassen als veraltet gelten)."
        )
    webuntis_ids = {row["id"] for row in rows}

    stale = (
        await db.execute(
            select(Klasse.id, Klasse.name, Klasse.webuntis_id)
            .where(Klasse.schuljahr_id == schuljahr_id, Klasse.webuntis_id.not_in(list(webuntis_ids)))
            .order_by(Klasse.name, Klasse.id)
        )
    ).all()
    andere_jahre = (
        await db.execute(
            select(Klasse.id, Klasse.webuntis_id, Klasse.schuljahr_id).where(Klasse.schuljahr_id != schuljahr_id)
        )
    ).all()
    kandidaten: dict[int, list[tuple[int, int]]] = {}
    for klasse_id, webuntis_id, jahr in andere_jahre:
        kandidaten.setdefault(webuntis_id, []).append((jahr, klasse_id))
    regel_klasse_ids = set(
        (await db.execute(select(SchwellwertRegel.klasse_id).where(SchwellwertRegel.klasse_id.is_not(None)))).scalars()
    )

    report = RepairReport(schuljahr_id=schuljahr_id, apply=apply)
    for klasse_id, name, webuntis_id in stale:
        # hoechstes Schuljahr unterhalb des aktuellen bevorzugen, sonst irgendein anderes
        jahre = sorted(kandidaten.get(webuntis_id, []))
        darunter = [c for c in jahre if c[0] < schuljahr_id]
        ziel = (darunter or jahre or [None])[-1]
        eintrag = StaleKlasse(
            id=klasse_id,
            name=name,
            webuntis_id=webuntis_id,
            target_id=ziel[1] if ziel else None,
            regel_referenziert=klasse_id in regel_klasse_ids,
        )
        if eintrag.target_id is None:
            report.unresolved.append(eintrag)
        if eintrag.regel_referenziert:
            report.rule_blocked.append(eintrag)
        if eintrag.target_id is None or eintrag.regel_referenziert:
            continue
        eintrag.schueler = await _count(db, Schueler, Schueler.klasse_id == klasse_id)
        historie = SchuelerKlasseHistorie.klasse_id == klasse_id
        eintrag.historie_repoint = await _count(
            db, SchuelerKlasseHistorie, historie, SchuelerKlasseHistorie.schuljahr_id != schuljahr_id
        )
        eintrag.historie_null = await _count(
            db, SchuelerKlasseHistorie, historie, SchuelerKlasseHistorie.schuljahr_id == schuljahr_id
        )
        eintrag.nutzer_klasse = await _count(db, NutzerKlasse, NutzerKlasse.klasse_id == klasse_id)
        eintrag.nutzer_klasse_manuell = await _count(
            db, NutzerKlasse, NutzerKlasse.klasse_id == klasse_id, NutzerKlasse.quelle == "manuell"
        )
        report.merged.append(eintrag)

    if not apply:
        await db.rollback()
        return report

    for eintrag in report.merged:
        await db.execute(update(Schueler).where(Schueler.klasse_id == eintrag.id).values(klasse_id=eintrag.target_id))
        await db.execute(
            update(SchuelerKlasseHistorie)
            .where(SchuelerKlasseHistorie.klasse_id == eintrag.id, SchuelerKlasseHistorie.schuljahr_id != schuljahr_id)
            .values(klasse_id=eintrag.target_id)
        )
        await db.execute(
            update(SchuelerKlasseHistorie)
            .where(SchuelerKlasseHistorie.klasse_id == eintrag.id, SchuelerKlasseHistorie.schuljahr_id == schuljahr_id)
            .values(klasse_id=None)
        )
        # nutzer_klasse und bereich_klasse haben ON DELETE CASCADE (Migrationen ce9c35768e75 / ac2d1b702760)
        await db.execute(delete(Klasse).where(Klasse.id == eintrag.id))
    await db.flush()

    if report.merged:
        await sync_bereiche(db, schuljahr_id=schuljahr_id)
        einstellung.asv_csv_zuletzt_importiert_mtime = None
    await db.commit()
    return report


async def _count(db: AsyncSession, model, *conditions) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*conditions))).scalar_one()


def format_report(report: RepairReport) -> list[str]:
    lines = [f"Veraltete Klassen im Schuljahr {report.schuljahr_id}:"]
    for e in report.merged:
        lines.append(
            f"  {e.id} / {e.name} / {e.webuntis_id} -> {e.target_id}: {e.schueler} Schueler, "
            f"{e.historie_repoint} Historie umgehaengt, {e.historie_null} Historie -> NULL, "
            f"{e.nutzer_klasse} nutzer_klasse (davon {e.nutzer_klasse_manuell} manuell)"
        )
    lines.append(
        f"Zusammengefuehrt: {len(report.merged)}, ohne Ziel-Klasse (unangetastet): {len(report.unresolved)}, "
        f"durch schwellwert_regel blockiert (unangetastet): {len(report.rule_blocked)}"
    )
    for titel, eintraege in (("Ohne Ziel-Klasse", report.unresolved), ("Durch Schwellwert-Regel blockiert", report.rule_blocked)):
        for e in eintraege:
            lines.append(f"  {titel}: {e.id} / {e.name} / {e.webuntis_id}")
    lines.append(
        "APPLIED - bereich_klasse neu aufgebaut, ASV-mtime zurueckgesetzt; jetzt 'Sync jetzt ausfuehren' starten."
        if report.apply
        else "DRY-RUN - nothing changed, use --apply"
    )
    return lines


async def _main(apply: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    async with WebUntisClient(settings) as client:
        async with async_session_factory() as db:
            try:
                report = await repair_stale_klassen(db, client, apply=apply)
            except RepairAborted as exc:
                logger.error("%s", exc)
                raise SystemExit(1) from exc
            for line in format_report(report):
                logger.info("%s", line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="Aenderungen tatsaechlich schreiben (Standard: Trockenlauf)")
    asyncio.run(_main(parser.parse_args().apply))
