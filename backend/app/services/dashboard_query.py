from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import resolve_bereich_scope, resolve_scope
from app.models.bereich import Bereich, bereich_klasse
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.dashboard import (
    NavBereichOut,
    NavKlasseOut,
    NavOptionsOut,
    StatsContext,
    StatsOut,
    StatsOwn,
    StatsVergleichEintrag,
)


async def get_nav_options(db: AsyncSession, nutzer: Nutzer) -> NavOptionsOut:
    bereich_scope = await resolve_bereich_scope(db, nutzer)
    klasse_scope = await resolve_scope(db, nutzer)

    if bereich_scope is not None and not bereich_scope:
        bereiche = []
    else:
        query = select(Bereich).order_by(Bereich.name)
        if bereich_scope is not None:
            query = query.where(Bereich.id.in_(bereich_scope))
        bereiche = (await db.execute(query)).scalars().all()

    if klasse_scope is not None and not klasse_scope:
        klassen = []
    else:
        query = select(Klasse).order_by(Klasse.name)
        if klasse_scope is not None:
            query = query.where(Klasse.id.in_(klasse_scope))
        klassen = (await db.execute(query)).scalars().all()

    # Deliberate simplification: NavKlasseOut.bereich_id is a single value, but bereich_klasse is m:n
    # (a Klasse can in principle belong to more than one Bereich). We pick the lowest bereich_id via
    # func.min() and assume in practice each Klasse belongs to exactly one Bereich at this school (see
    # TECH-SPEC.md). If a Klasse ever legitimately belongs to >1 Bereich, this dropdown mapping will
    # only show it under the lowest-numbered Bereich, while _stats_for_bereich's aggregation below
    # correctly includes it in the totals of every Bereich it belongs to — i.e. the nav dropdown and
    # the numbers can disagree for that edge case. See ROADMAP.md "Technical debt" for the accepted
    # limitation; do not "fix" this by widening bereich_id to a list without reading that entry first.
    klasse_bereich_map = dict(
        (
            await db.execute(
                select(bereich_klasse.c.klasse_id, func.min(bereich_klasse.c.bereich_id)).group_by(
                    bereich_klasse.c.klasse_id
                )
            )
        ).all()
    )

    return NavOptionsOut(
        bereiche=[NavBereichOut(id=b.id, name=b.name) for b in bereiche],
        klassen=[
            NavKlasseOut(id=k.id, name=k.name, bereich_id=klasse_bereich_map.get(k.id)) for k in klassen
        ],
    )


async def _get_schuljahr_start(db: AsyncSession) -> date | None:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    return einstellung.schuljahr_start_cache if einstellung else None


async def _aggregate(db: AsyncSession, klasse_ids: list[int] | None, schuljahr_start: date | None) -> StatsOwn:
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

    schueler_query = select(Schueler.id).where(Schueler.aktiv.is_(True))
    if klasse_ids is not None:
        schueler_query = schueler_query.where(Schueler.klasse_id.in_(klasse_ids))
    schueler_ids = (await db.execute(schueler_query)).scalars().all()
    anzahl_schueler = len(schueler_ids)
    if anzahl_schueler == 0:
        return leer

    datumsfilter = [] if schuljahr_start is None else [schuljahr_start]

    fehltage = (
        await db.execute(
            select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "tag",
                Fehlzeit.invalid.is_(False),
                *([Fehlzeit.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    fehlstunden = (
        await db.execute(
            select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "stunde",
                Fehlzeit.invalid.is_(False),
                *([Fehlzeit.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    klassenbuch = (
        await db.execute(
            select(func.count()).select_from(KlassenbuchEintrag).where(
                KlassenbuchEintrag.schueler_id.in_(schueler_ids),
                *([KlassenbuchEintrag.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    massnahmen = (
        await db.execute(
            select(func.count()).select_from(Massnahme).where(
                Massnahme.schueler_id.in_(schueler_ids),
                *([Massnahme.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()

    return StatsOwn(
        anzahl_schueler=anzahl_schueler,
        avg_fehltage=round(fehltage / anzahl_schueler, 2),
        avg_fehlstunden=round(fehlstunden / anzahl_schueler, 2),
        avg_klassenbuch=round(klassenbuch / anzahl_schueler, 2),
        anzahl_klassenbuch=klassenbuch,
        anzahl_massnahmen=massnahmen,
    )


def _leerer_context() -> StatsContext:
    return StatsContext(bereich_id=None, bereich_name=None, klasse_id=None, klasse_name=None)


async def _stats_for_bereich(db: AsyncSession, bereich: Bereich, schuljahr_start: date | None) -> StatsOut:
    klassen = (
        await db.execute(
            select(Klasse)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
    ).scalars().all()
    own = await _aggregate(db, [k.id for k in klassen], schuljahr_start)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(
        level="bereich",
        context=StatsContext(bereich_id=bereich.id, bereich_name=bereich.name, klasse_id=None, klasse_name=None),
        own=own,
        vergleich=vergleich,
    )


async def _stats_schulweit(db: AsyncSession, schuljahr_start: date | None) -> StatsOut:
    own = await _aggregate(db, None, schuljahr_start)
    bereiche = (await db.execute(select(Bereich).order_by(Bereich.name))).scalars().all()
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        stats = await _aggregate(db, list(klasse_ids), schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    return StatsOut(level="schule", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_bereiche(db: AsyncSession, bereich_ids: set[int], schuljahr_start: date | None) -> StatsOut:
    bereiche = (
        await db.execute(select(Bereich).where(Bereich.id.in_(bereich_ids)).order_by(Bereich.name))
    ).scalars().all()
    alle_klasse_ids: list[int] = []
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        alle_klasse_ids.extend(klasse_ids)
        stats = await _aggregate(db, list(klasse_ids), schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    own = await _aggregate(db, alle_klasse_ids, schuljahr_start)
    return StatsOut(level="eigene_bereiche", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_klassen(db: AsyncSession, klasse_ids: set[int], schuljahr_start: date | None) -> StatsOut:
    klassen = (
        await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)).order_by(Klasse.name))
    ).scalars().all()
    own = await _aggregate(db, list(klasse_ids), schuljahr_start)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(level="eigene_klassen", context=_leerer_context(), own=own, vergleich=vergleich)


async def get_dashboard_stats(
    db: AsyncSession, nutzer: Nutzer, bereich_id: int | None, klasse_id: int | None
) -> StatsOut:
    if nutzer.rolle == "klassenlehrkraft" and bereich_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="klassenlehrkraft cannot pass bereich_id"
        )

    schuljahr_start = await _get_schuljahr_start(db)

    if klasse_id is not None:
        klasse_scope = await resolve_scope(db, nutzer)
        if klasse_scope is not None and klasse_id not in klasse_scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        own = await _aggregate(db, [klasse.id], schuljahr_start)
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
        return await _stats_for_bereich(db, bereich, schuljahr_start)

    if nutzer.rolle == "schulleitung":
        return await _stats_schulweit(db, schuljahr_start)

    if nutzer.rolle == "bereichsleiter":
        bereich_scope = await resolve_bereich_scope(db, nutzer)
        if len(bereich_scope) == 1:
            bereich = (
                await db.execute(select(Bereich).where(Bereich.id == next(iter(bereich_scope))))
            ).scalar_one()
            return await _stats_for_bereich(db, bereich, schuljahr_start)
        return await _stats_eigene_bereiche(db, bereich_scope, schuljahr_start)

    klasse_scope = await resolve_scope(db, nutzer)
    if len(klasse_scope) == 1:
        klasse = (await db.execute(select(Klasse).where(Klasse.id == next(iter(klasse_scope))))).scalar_one()
        own = await _aggregate(db, [klasse.id], schuljahr_start)
        return StatsOut(
            level="klasse",
            context=StatsContext(bereich_id=None, bereich_name=None, klasse_id=klasse.id, klasse_name=klasse.name),
            own=own,
            vergleich=[],
        )
    return await _stats_eigene_klassen(db, klasse_scope, schuljahr_start)
