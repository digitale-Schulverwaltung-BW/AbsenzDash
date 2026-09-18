from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse


async def sync_bereiche(db: AsyncSession, schuljahr_id: int) -> None:
    """Leitet bereich/bereich_klasse verbindlich aus abteilung/klasse.abteilung_id ab (Bundle D).

    Legt fuer jede Abteilung genau einen Bereich an (1:1) und haelt bereich_klasse mit dem
    aktuellen klasse.abteilung_id-Stand synchron. `ausgeblendet` und die Bereichsleiter-
    Zuordnung (nutzer_bereich) sind reine Admin-Domaene und werden hier nie angefasst.
    Bereiche werden nie geloescht -- eine Abteilung mit aktuell 0 Klassen bekommt einfach
    eine leere bereich_klasse-Menge, siehe
    docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.

    Die `klasse`-Abfrage ist bewusst auf `schuljahr_id` gescopet: seit klasse.schuljahr_id
    (siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md) existiert pro
    Jahr eine eigene, nie geloeschte Zeile je webuntis_id - ohne diesen Filter wuerden Klassen
    mehrerer Schuljahre gleichzeitig im selben Bereich landen.
    """
    abteilungen = (await db.execute(select(Abteilung).order_by(Abteilung.name))).scalars().all()
    klassen = (await db.execute(select(Klasse).where(Klasse.schuljahr_id == schuljahr_id))).scalars().all()
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
    resolved_names: dict[int, str] = {}
    for abteilung, name in zip(abteilungen, namen):
        resolved_names[abteilung.id] = f"{name} ({abteilung.name})" if namen_anzahl[name] > 1 else name

    # Erst alle Umbenennungen bestehender Bereiche flushen, bevor neue Bereiche angelegt werden --
    # sonst kann ein neu angelegter Bereich mit dem noch nicht weggeschriebenen alten Namen eines
    # umzubenennenden Bereichs kollidieren (unique constraint auf bereich.name).
    for abteilung in abteilungen:
        bereich = bereich_by_abteilung_id.get(abteilung.id)
        if bereich is not None:
            bereich.name = resolved_names[abteilung.id]
    await db.flush()

    for abteilung in abteilungen:
        bereich = bereich_by_abteilung_id.get(abteilung.id)
        if bereich is None:
            bereich = Bereich(abteilung_id=abteilung.id, name=resolved_names[abteilung.id])
            db.add(bereich)
            await db.flush()
            bereich_by_abteilung_id[abteilung.id] = bereich

        await db.execute(delete(bereich_klasse).where(bereich_klasse.c.bereich_id == bereich.id))
        for klasse_id in klassen_by_abteilung.get(abteilung.id, []):
            await db.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_id))

    await db.flush()
