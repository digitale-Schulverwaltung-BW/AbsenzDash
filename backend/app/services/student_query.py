from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import bereich_klasse
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand

ZAEHLERSTAND_TYPEN = ("fehlzeiten", "klassenbuch")


async def list_students(
    db: AsyncSession,
    scope: set[int] | None,
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: str | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Schueler], int]:
    """Liefert die fuer den Scope sichtbaren Schueler (gefiltert, paginiert) sowie die
    Gesamtzahl (nach Filtern, vor Pagination)."""
    if scope is not None and not scope:
        return [], 0

    conditions = []
    if scope is not None:
        conditions.append(Schueler.klasse_id.in_(scope))
    if klasse_id is not None:
        conditions.append(Schueler.klasse_id == klasse_id)
    if bereich_id is not None:
        bereich_klassen = select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_id)
        conditions.append(Schueler.klasse_id.in_(bereich_klassen))

    if min_stufe is not None or nur_auffaellige:
        typen = [typ] if typ is not None else list(ZAEHLERSTAND_TYPEN)
        zaehlerstand_conditions = [SchuelerZaehlerstand.typ.in_(typen)]
        if min_stufe is not None:
            zaehlerstand_conditions.append(SchuelerZaehlerstand.erreichte_stufe_nr >= min_stufe)
        else:
            zaehlerstand_conditions.append(SchuelerZaehlerstand.erreichte_stufe_nr.is_not(None))
        matching_ids = select(SchuelerZaehlerstand.schueler_id).where(*zaehlerstand_conditions)
        conditions.append(Schueler.id.in_(matching_ids))

    count_query = select(func.count()).select_from(Schueler)
    query = select(Schueler)
    for condition in conditions:
        count_query = count_query.where(condition)
        query = query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    result = await db.execute(query.order_by(Schueler.nachname, Schueler.vorname).offset(offset).limit(limit))
    return list(result.scalars().all()), total


async def load_klasse_map(db: AsyncSession, klasse_ids: list[int]) -> dict[int, Klasse]:
    if not klasse_ids:
        return {}
    result = await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)))
    return {klasse.id: klasse for klasse in result.scalars().all()}


async def load_zaehlerstand_map(db: AsyncSession, schueler_ids: list[int]) -> dict[int, dict[str, dict[str, Any]]]:
    """Pro schueler_id ein dict {typ: {aktueller_stand, erreichte_stufe_nr}}, mit
    {aktueller_stand: 0, erreichte_stufe_nr: None} synthetisiert fuer fehlende Typen."""
    result: dict[int, dict[str, dict[str, Any]]] = {
        schueler_id: {typ: {"aktueller_stand": 0, "erreichte_stufe_nr": None} for typ in ZAEHLERSTAND_TYPEN}
        for schueler_id in schueler_ids
    }
    if not schueler_ids:
        return result

    rows = (
        await db.execute(select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id.in_(schueler_ids)))
    ).scalars().all()
    for row in rows:
        result[row.schueler_id][row.typ] = {
            "aktueller_stand": row.aktueller_stand,
            "erreichte_stufe_nr": row.erreichte_stufe_nr,
        }
    return result


async def load_letzte_benachrichtigung_map(db: AsyncSession, schueler_ids: list[int]) -> dict[int, Benachrichtigung]:
    """Pro schueler_id die zeitlich juengste Benachrichtigung (falls vorhanden)."""
    if not schueler_ids:
        return {}
    result = await db.execute(
        select(Benachrichtigung)
        .where(Benachrichtigung.schueler_id.in_(schueler_ids))
        .order_by(Benachrichtigung.schueler_id, Benachrichtigung.gesendet_am.desc())
    )
    letzte: dict[int, Benachrichtigung] = {}
    for row in result.scalars().all():
        letzte.setdefault(row.schueler_id, row)
    return letzte


async def load_ohne_massnahme_map(
    db: AsyncSession, schueler_ids: list[int], letzte_benachrichtigung: dict[int, Benachrichtigung]
) -> dict[int, bool]:
    """True, wenn eine letzte Benachrichtigung existiert und seitdem keine Massnahme erfasst wurde."""
    if not schueler_ids:
        return {}
    result = await db.execute(
        select(Massnahme.schueler_id, func.max(Massnahme.datum))
        .where(Massnahme.schueler_id.in_(schueler_ids))
        .group_by(Massnahme.schueler_id)
    )
    letzte_massnahme_datum: dict[int, date] = dict(result.all())

    ohne_massnahme: dict[int, bool] = {}
    for schueler_id in schueler_ids:
        benachrichtigung = letzte_benachrichtigung.get(schueler_id)
        if benachrichtigung is None:
            ohne_massnahme[schueler_id] = False
            continue
        massnahme_datum = letzte_massnahme_datum.get(schueler_id)
        ohne_massnahme[schueler_id] = (
            massnahme_datum is None or massnahme_datum < benachrichtigung.gesendet_am.date()
        )
    return ohne_massnahme


async def load_overview_extras(db: AsyncSession, schueler_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Buendelt die Batch-Queries oben zu einem dict pro schueler_id fuer die Uebersicht."""
    zaehlerstand_map = await load_zaehlerstand_map(db, schueler_ids)
    letzte_benachrichtigung_map = await load_letzte_benachrichtigung_map(db, schueler_ids)
    ohne_massnahme_map = await load_ohne_massnahme_map(db, schueler_ids, letzte_benachrichtigung_map)
    return {
        schueler_id: {
            "zaehlerstand": zaehlerstand_map[schueler_id],
            "letzte_benachrichtigung": letzte_benachrichtigung_map.get(schueler_id),
            "ohne_massnahme_seit_benachrichtigung": ohne_massnahme_map.get(schueler_id, False),
        }
        for schueler_id in schueler_ids
    }


async def load_student_detail(db: AsyncSession, schueler_id: int) -> dict[str, Any]:
    """Laedt alle Unterlisten fuer die Detailansicht eines Schuelers."""
    fehlzeiten = (
        await db.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler_id).order_by(Fehlzeit.datum.desc()))
    ).scalars().all()
    klassenbuch = (
        await db.execute(
            select(KlassenbuchEintrag)
            .where(KlassenbuchEintrag.schueler_id == schueler_id)
            .order_by(KlassenbuchEintrag.datum.desc())
        )
    ).scalars().all()
    massnahmen_rows = (
        await db.execute(
            select(Massnahme, MassnahmenTyp.name, Nutzer.name)
            .join(MassnahmenTyp, MassnahmenTyp.id == Massnahme.massnahmen_typ_id)
            .join(Nutzer, Nutzer.id == Massnahme.erfasst_von_nutzer_id)
            .where(Massnahme.schueler_id == schueler_id)
            .order_by(Massnahme.datum.desc())
        )
    ).all()
    ausnahmen = (
        await db.execute(
            select(Ausnahme).where(Ausnahme.schueler_id == schueler_id, Ausnahme.aktiv.is_(True))
        )
    ).scalars().all()
    benachrichtigungen = (
        await db.execute(
            select(Benachrichtigung)
            .where(Benachrichtigung.schueler_id == schueler_id)
            .order_by(Benachrichtigung.gesendet_am.desc())
        )
    ).scalars().all()
    zaehlerstand_map = await load_zaehlerstand_map(db, [schueler_id])

    return {
        "fehlzeiten": list(fehlzeiten),
        "klassenbuch": list(klassenbuch),
        "massnahmen": list(massnahmen_rows),
        "ausnahmen": list(ausnahmen),
        "benachrichtigungen": list(benachrichtigungen),
        "zaehlerstand": zaehlerstand_map[schueler_id],
    }
