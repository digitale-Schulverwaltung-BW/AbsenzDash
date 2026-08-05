from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse


async def sync_bereiche(db: AsyncSession) -> None:
    """Leitet bereich/bereich_klasse verbindlich aus abteilung/klasse.abteilung_id ab (Bundle D).

    Legt fuer jede Abteilung genau einen Bereich an (1:1) und haelt bereich_klasse mit dem
    aktuellen klasse.abteilung_id-Stand synchron. `ausgeblendet` und die Bereichsleiter-
    Zuordnung (nutzer_bereich) sind reine Admin-Domaene und werden hier nie angefasst.
    Bereiche werden nie geloescht -- eine Abteilung mit aktuell 0 Klassen bekommt einfach
    eine leere bereich_klasse-Menge, siehe
    docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.
    """
    abteilungen = (await db.execute(select(Abteilung).order_by(Abteilung.name))).scalars().all()
    klassen = (await db.execute(select(Klasse))).scalars().all()
    existing_bereiche = (await db.execute(select(Bereich))).scalars().all()
    bereich_by_abteilung_id = {b.abteilung_id: b for b in existing_bereiche if b.abteilung_id is not None}

    klassen_by_abteilung: dict[int, list[int]] = {}
    for klasse in klassen:
        if klasse.abteilung_id is not None:
            klassen_by_abteilung.setdefault(klasse.abteilung_id, []).append(klasse.id)

    namen = [abteilung.long_name or abteilung.name for abteilung in abteilungen]
    # zwei Abteilungen koennen denselben long_name tragen (z.B. "BT" und "B-BT" -> beide
    # "Betriebstechnik"); bereich.name ist unique, kollidierende Namen muessen also
    # disambiguiert werden. Nicht-kollidierende Namen bleiben unveraendert.
    namen_anzahl = Counter(namen)

    for abteilung, name in zip(abteilungen, namen):
        if namen_anzahl[name] > 1:
            name = f"{name} ({abteilung.name})"

        bereich = bereich_by_abteilung_id.get(abteilung.id)
        if bereich is None:
            bereich = Bereich(abteilung_id=abteilung.id, name=name)
            db.add(bereich)
            await db.flush()
        else:
            bereich.name = name

        await db.execute(delete(bereich_klasse).where(bereich_klasse.c.bereich_id == bereich.id))
        for klasse_id in klassen_by_abteilung.get(abteilung.id, []):
            await db.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_id))

    await db.flush()
