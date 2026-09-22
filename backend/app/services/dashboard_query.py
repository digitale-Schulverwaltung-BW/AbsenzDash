from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import resolve_bereich_scope, resolve_scope
from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden
from app.services.schuljahr_zeitraum import resolve_schuljahr_zeitraum
from app.models.bereich import Bereich, bereich_klasse
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.nutzer import Nutzer
from app.models.schuljahr import Schuljahr
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.schemas.dashboard import (
    NavBereichOut,
    NavKlasseOut,
    NavOptionsOut,
    NavSchuljahrOut,
    StatsContext,
    StatsOut,
    StatsOwn,
    StatsVergleichEintrag,
)


async def get_nav_options(db: AsyncSession, nutzer: Nutzer, schuljahr_id: int | None = None) -> NavOptionsOut:
    bereich_scope = await resolve_bereich_scope(db, nutzer)
    klasse_scope = await resolve_scope(db, nutzer)

    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    aktuelles_schuljahr_id = einstellung.aktuelles_schuljahr_id if einstellung else None
    effektive_schuljahr_id = schuljahr_id if schuljahr_id is not None else aktuelles_schuljahr_id

    if bereich_scope is not None and not bereich_scope:
        bereiche = []
    else:
        query = select(Bereich).where(Bereich.ausgeblendet.is_(False)).order_by(Bereich.name)
        if bereich_scope is not None:
            query = query.where(Bereich.id.in_(bereich_scope))
        bereiche = (await db.execute(query)).scalars().all()

    if klasse_scope is not None and not klasse_scope:
        klassen = []
    else:
        query = select(Klasse).order_by(Klasse.name)
        if klasse_scope is not None:
            query = query.where(Klasse.id.in_(klasse_scope))
        if effektive_schuljahr_id is not None:
            query = query.where(Klasse.schuljahr_id == effektive_schuljahr_id)
        klassen = (await db.execute(query)).scalars().all()

    klasse_bereich_map = dict(
        (await db.execute(select(bereich_klasse.c.klasse_id, bereich_klasse.c.bereich_id))).all()
    )

    schuljahre_result = await db.execute(select(Schuljahr).order_by(Schuljahr.start_datum.desc()))
    schuljahre = [
        NavSchuljahrOut(id=s.id, name=s.name, start_datum=s.start_datum, end_datum=s.end_datum)
        for s in schuljahre_result.scalars().all()
    ]

    return NavOptionsOut(
        bereiche=[NavBereichOut(id=b.id, name=b.name) for b in bereiche],
        klassen=[
            NavKlasseOut(id=k.id, name=k.name, bereich_id=klasse_bereich_map.get(k.id)) for k in klassen
        ],
        rolle=nutzer.rolle,
        schuljahre=schuljahre,
        aktuelles_schuljahr_id=aktuelles_schuljahr_id,
    )


async def _get_schuljahr_start(db: AsyncSession) -> date | None:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    return einstellung.schuljahr_start_cache if einstellung else None


def _zeitraum_filter(spalte: Any, von: date | None, bis: date | None) -> list[Any]:
    filters: list[Any] = []
    if von is not None:
        filters.append(spalte >= von)
    if bis is not None:
        filters.append(spalte <= bis)
    return filters


async def _aggregate(
    db: AsyncSession,
    klasse_ids: list[int] | None,
    von: date | None,
    bis: date | None,
    historie_schuljahr_id: int | None = None,
) -> StatsOwn:
    """Aggregiert Rohzahlen ueber alle Schueler der gegebenen Klassen (None = alle Klassen).
    von/bis grenzen den Zeitraum beidseitig ein (None je Seite = unbegrenzt in diese Richtung) --
    aktuelles Schuljahr uebergibt (schuljahr_start_cache, None), vergangenes Schuljahr
    (schuljahr.start_datum, schuljahr.end_datum), siehe get_dashboard_stats.

    historie_schuljahr_id (Default None) schaltet die Schuelerbasis von der live
    Schueler.klasse_id/aktiv auf schueler_klasse_historie fuers gewaehlte Schuljahr um -- exakt
    das Roster-Prinzip aus student_query.list_students' historie_schuljahr_id-Parameter (Plan 17),
    hier lokal nachgebaut, da nur schueler_id's gebraucht werden, keine paginierten/sortierten
    Schueler-Objekte. Kein aktiv-Filter im Historie-Modus -- ein Schueler mit Snapshot fuers
    Schuljahr zaehlt unabhaengig vom heutigen aktiv-Status, siehe
    docs/superpowers/specs/2026-09-22-dashboard-stats-schuljahr-design.md."""
    leer = StatsOwn(
        anzahl_schueler=0,
        avg_fehltage=0.0,
        avg_fehlstunden=0.0,
        avg_klassenbuch=0.0,
        anzahl_klassenbuch=0,
        anzahl_massnahmen=0,
    )
    if klasse_ids is not None and not klasse_ids:
        return leer

    if historie_schuljahr_id is None:
        schueler_query = select(Schueler.id).where(Schueler.aktiv.is_(True))
        if klasse_ids is not None:
            schueler_query = schueler_query.where(Schueler.klasse_id.in_(klasse_ids))
    else:
        schueler_query = select(SchuelerKlasseHistorie.schueler_id).where(
            SchuelerKlasseHistorie.schuljahr_id == historie_schuljahr_id
        )
        if klasse_ids is not None:
            schueler_query = schueler_query.where(SchuelerKlasseHistorie.klasse_id.in_(klasse_ids))
    schueler_ids = (await db.execute(schueler_query)).scalars().all()
    anzahl_schueler = len(schueler_ids)
    if anzahl_schueler == 0:
        return leer

    fehltage = (
        await db.execute(
            select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "tag",
                Fehlzeit.invalid.is_(False),
                *_zeitraum_filter(Fehlzeit.datum, von, bis),
            )
        )
    ).scalar_one()
    fehlstunden_minuten = (
        await db.execute(
            select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "stunde",
                Fehlzeit.invalid.is_(False),
                *_zeitraum_filter(Fehlzeit.datum, von, bis),
            )
        )
    ).scalar_one()
    fehlstunden = minuten_zu_fehlstunden(fehlstunden_minuten)
    klassenbuch = (
        await db.execute(
            select(func.count()).select_from(KlassenbuchEintrag).where(
                KlassenbuchEintrag.schueler_id.in_(schueler_ids),
                *_zeitraum_filter(KlassenbuchEintrag.datum, von, bis),
            )
        )
    ).scalar_one()
    massnahmen = (
        await db.execute(
            select(func.count()).select_from(Massnahme).where(
                Massnahme.schueler_id.in_(schueler_ids),
                *_zeitraum_filter(Massnahme.datum, von, bis),
            )
        )
    ).scalar_one()

    return StatsOwn(
        anzahl_schueler=anzahl_schueler,
        avg_fehltage=round(fehltage / anzahl_schueler, 2),
        avg_fehlstunden=round(float(fehlstunden) / anzahl_schueler, 2),
        avg_klassenbuch=round(klassenbuch / anzahl_schueler, 2),
        anzahl_klassenbuch=klassenbuch,
        anzahl_massnahmen=massnahmen,
    )


def _leerer_context() -> StatsContext:
    return StatsContext(bereich_id=None, bereich_name=None, klasse_id=None, klasse_name=None)


async def _stats_for_bereich(
    db: AsyncSession, bereich: Bereich, von: date | None, bis: date | None, historie_schuljahr_id: int | None
) -> StatsOut:
    klassen = (
        await db.execute(
            select(Klasse)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
    ).scalars().all()
    own = await _aggregate(db, [k.id for k in klassen], von, bis, historie_schuljahr_id)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(
        level="bereich",
        context=StatsContext(bereich_id=bereich.id, bereich_name=bereich.name, klasse_id=None, klasse_name=None),
        own=own,
        vergleich=vergleich,
    )


async def _stats_schulweit(db: AsyncSession, von: date | None, bis: date | None, historie_schuljahr_id: int | None) -> StatsOut:
    own = await _aggregate(db, None, von, bis, historie_schuljahr_id)
    bereiche = (
        await db.execute(select(Bereich).where(Bereich.ausgeblendet.is_(False)).order_by(Bereich.name))
    ).scalars().all()
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        stats = await _aggregate(db, list(klasse_ids), von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    return StatsOut(level="schule", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_bereiche(
    db: AsyncSession, bereich_ids: set[int], von: date | None, bis: date | None, historie_schuljahr_id: int | None
) -> StatsOut:
    bereiche = (
        await db.execute(
            select(Bereich)
            .where(Bereich.id.in_(bereich_ids), Bereich.ausgeblendet.is_(False))
            .order_by(Bereich.name)
        )
    ).scalars().all()
    alle_klasse_ids: list[int] = []
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        alle_klasse_ids.extend(klasse_ids)
        stats = await _aggregate(db, list(klasse_ids), von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    own = await _aggregate(db, alle_klasse_ids, von, bis, historie_schuljahr_id)
    return StatsOut(level="eigene_bereiche", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_klassen(
    db: AsyncSession, klasse_ids: set[int], von: date | None, bis: date | None, historie_schuljahr_id: int | None
) -> StatsOut:
    klassen = (
        await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)).order_by(Klasse.name))
    ).scalars().all()
    own = await _aggregate(db, list(klasse_ids), von, bis, historie_schuljahr_id)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(level="eigene_klassen", context=_leerer_context(), own=own, vergleich=vergleich)


async def get_dashboard_stats(
    db: AsyncSession,
    nutzer: Nutzer,
    bereich_id: int | None,
    klasse_id: int | None,
    schuljahr_id: int | None = None,
) -> StatsOut:
    if nutzer.rolle == "klassenlehrkraft" and bereich_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="klassenlehrkraft cannot pass bereich_id"
        )

    von, bis = await resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None
    historie_schuljahr_id = schuljahr_id if ist_historie else None
    if not ist_historie:
        von = await _get_schuljahr_start(db)
        bis = None

    if klasse_id is not None:
        klasse_scope = await resolve_scope(db, nutzer)
        if klasse_scope is not None and klasse_id not in klasse_scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        own = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        return StatsOut(
            level="klasse",
            context=StatsContext(bereich_id=None, bereich_name=None, klasse_id=klasse.id, klasse_name=klasse.name),
            own=own,
            vergleich=[],
        )

    if bereich_id is not None:
        bereich_scope = await resolve_bereich_scope(db, nutzer)
        if bereich_scope is not None and bereich_id not in bereich_scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bereich nicht gefunden")
        bereich = (await db.execute(select(Bereich).where(Bereich.id == bereich_id))).scalar_one_or_none()
        if bereich is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bereich nicht gefunden")
        return await _stats_for_bereich(db, bereich, von, bis, historie_schuljahr_id)

    if nutzer.rolle == "schulleitung":
        return await _stats_schulweit(db, von, bis, historie_schuljahr_id)

    if nutzer.rolle == "bereichsleiter":
        bereich_scope = await resolve_bereich_scope(db, nutzer)
        if len(bereich_scope) == 1:
            bereich = (
                await db.execute(select(Bereich).where(Bereich.id == next(iter(bereich_scope))))
            ).scalar_one()
            return await _stats_for_bereich(db, bereich, von, bis, historie_schuljahr_id)
        return await _stats_eigene_bereiche(db, bereich_scope, von, bis, historie_schuljahr_id)

    klasse_scope = await resolve_scope(db, nutzer)
    if len(klasse_scope) == 1:
        klasse = (await db.execute(select(Klasse).where(Klasse.id == next(iter(klasse_scope))))).scalar_one()
        own = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        return StatsOut(
            level="klasse",
            context=StatsContext(bereich_id=None, bereich_name=None, klasse_id=klasse.id, klasse_name=klasse.name),
            own=own,
            vergleich=[],
        )
    return await _stats_eigene_klassen(db, klasse_scope, von, bis, historie_schuljahr_id)
