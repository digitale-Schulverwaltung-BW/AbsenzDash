from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden

ZAEHLERSTAND_TYPEN = ("fehlzeiten", "klassenbuch")

SORTIERBARE_FELDER = ("nachname", "klasse", "fehltage", "fehlstunden", "klassenbuch_anzahl")


async def list_students(
    db: AsyncSession,
    scope: set[int] | None,
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: str | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    nur_aktive: bool = True,
    von: date | None = None,
    bis: date | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Schueler], int]:
    """Liefert die fuer den Scope sichtbaren Schueler (gefiltert, sortiert, paginiert) sowie
    die Gesamtzahl (nach Filtern, vor Pagination). von/bis grenzen den Zeitraum fuer die
    Fehltage/Fehlstunden/Einträge-Sortierung ein (None/None = unbegrenzt)."""
    if scope is not None and not scope:
        return [], 0
    if sort_by is not None and sort_by not in SORTIERBARE_FELDER:
        raise ValueError(f"Unbekanntes sort_by: {sort_by}")

    conditions = []
    if nur_aktive:
        conditions.append(Schueler.aktiv.is_(True))
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

    richtung = desc if sort_dir == "desc" else asc
    if sort_by is None or sort_by == "nachname":
        query = query.order_by(Schueler.nachname, Schueler.vorname, Schueler.id)
    elif sort_by == "klasse":
        query = query.outerjoin(Klasse, Klasse.id == Schueler.klasse_id).order_by(
            richtung(Klasse.name), Schueler.nachname, Schueler.id
        )
    elif sort_by == "klassenbuch_anzahl":
        subq = (
            select(KlassenbuchEintrag.schueler_id, func.count().label("anzahl"))
            .where(*_klassenbuch_datum_filter(von, bis))
            .group_by(KlassenbuchEintrag.schueler_id)
            .subquery()
        )
        query = query.outerjoin(subq, subq.c.schueler_id == Schueler.id).order_by(
            richtung(func.coalesce(subq.c.anzahl, 0)), Schueler.nachname, Schueler.id
        )
    elif sort_by == "fehltage":
        subq = (
            select(Fehlzeit.schueler_id, func.count().label("anzahl"))
            .where(Fehlzeit.typ == "tag", Fehlzeit.invalid.is_(False), *_fehlzeit_datum_filter(von, bis))
            .group_by(Fehlzeit.schueler_id)
            .subquery()
        )
        query = query.outerjoin(subq, subq.c.schueler_id == Schueler.id).order_by(
            richtung(func.coalesce(subq.c.anzahl, 0)), Schueler.nachname, Schueler.id
        )
    else:  # sort_by == "fehlstunden"
        subq = (
            select(Fehlzeit.schueler_id, func.sum(fehlstunden_minuten_expr()).label("minuten"))
            .where(Fehlzeit.typ == "stunde", Fehlzeit.invalid.is_(False), *_fehlzeit_datum_filter(von, bis))
            .group_by(Fehlzeit.schueler_id)
            .subquery()
        )
        query = query.outerjoin(subq, subq.c.schueler_id == Schueler.id).order_by(
            richtung(func.coalesce(subq.c.minuten, 0)), Schueler.nachname, Schueler.id
        )

    result = await db.execute(query.offset(offset).limit(limit))
    return list(result.scalars().all()), total


async def load_klasse_map(db: AsyncSession, klasse_ids: list[int]) -> dict[int, Klasse]:
    if not klasse_ids:
        return {}
    result = await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)))
    return {klasse.id: klasse for klasse in result.scalars().all()}


async def load_regel_typ_map(db: AsyncSession, regel_ids: list[int]) -> dict[int, str]:
    """Pro regel_id der zugehoerige typ ('fehlzeiten'/'klassenbuch'), fuer die Anzeige
    im 'Benachrichtigt'-Badge (SPECS.md Abschnitt 7)."""
    if not regel_ids:
        return {}
    result = await db.execute(
        select(SchwellwertRegel.id, SchwellwertRegel.typ).where(SchwellwertRegel.id.in_(regel_ids))
    )
    return dict(result.all())


async def load_excuse_status_map(db: AsyncSession, excuse_status_ids: list[int]) -> dict[int, ExcuseStatus]:
    """Pro excuse_status_id die zugehoerige Stammdaten-Zeile, fuer die Klartext-Anzeige
    im PDF-Export (Fehlzeit.excuse_status_id ist sonst nirgends aufgeloest)."""
    if not excuse_status_ids:
        return {}
    result = await db.execute(select(ExcuseStatus).where(ExcuseStatus.id.in_(excuse_status_ids)))
    return {status.id: status for status in result.scalars().all()}


async def load_classreg_category_map(db: AsyncSession, kategorie_ids: list[int]) -> dict[int, ClassregCategory]:
    """Pro kategorie_id die zugehoerige Stammdaten-Zeile, fuer die Klartext-Anzeige
    im PDF-Export (KlassenbuchEintrag.kategorie_id ist sonst nirgends aufgeloest)."""
    if not kategorie_ids:
        return {}
    result = await db.execute(select(ClassregCategory).where(ClassregCategory.id.in_(kategorie_ids)))
    return {kategorie.id: kategorie for kategorie in result.scalars().all()}


async def load_all_excuse_statuses(db: AsyncSession) -> list[ExcuseStatus]:
    """Alle Entschuldigungsstatus-Stammdaten (auch inaktive, da historische
    Fehlzeiten auf einen inzwischen deaktivierten Status verweisen koennen)."""
    result = await db.execute(select(ExcuseStatus).order_by(ExcuseStatus.name))
    return list(result.scalars().all())


async def load_all_classreg_categories(db: AsyncSession) -> list[ClassregCategory]:
    """Alle Klassenbuch-Kategorie-Stammdaten."""
    result = await db.execute(select(ClassregCategory).order_by(ClassregCategory.name))
    return list(result.scalars().all())


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


def _fehlzeit_datum_filter(von: date | None, bis: date | None) -> list[Any]:
    filters: list[Any] = []
    if von is not None:
        filters.append(Fehlzeit.datum >= von)
    if bis is not None:
        filters.append(Fehlzeit.datum <= bis)
    return filters


def _klassenbuch_datum_filter(von: date | None, bis: date | None) -> list[Any]:
    filters: list[Any] = []
    if von is not None:
        filters.append(KlassenbuchEintrag.datum >= von)
    if bis is not None:
        filters.append(KlassenbuchEintrag.datum <= bis)
    return filters


def _leerer_fehltage_split() -> dict[str, int]:
    return {"gesamt": 0, "entschuldigt": 0, "unentschuldigt": 0}


def _leerer_fehlstunden_split() -> dict[str, Decimal]:
    return {"gesamt": Decimal("0.00"), "entschuldigt": Decimal("0.00"), "unentschuldigt": Decimal("0.00")}


async def load_schueler_rohzahlen(
    db: AsyncSession, schueler_ids: list[int], von: date | None, bis: date | None
) -> dict[int, dict[str, Any]]:
    """Fehltage/Fehlstunden (je als {gesamt, entschuldigt, unentschuldigt}) plus
    klassenbuch_anzahl fuer den angegebenen Zeitraum. von=None/bis=None heisst
    unbegrenzt (all-time) - genutzt sowohl im Historie-Modus (vergangenes Schuljahr)
    als auch im Normalmodus (aktuelles Schuljahr, oder all-time falls noch keines
    konfiguriert ist). Entschuldigt/unentschuldigt-Split: Zeilen ohne excuse_status_id
    zaehlen als unentschuldigt (sicherer Default, konsistent mit der Eskalations-Engine,
    siehe eskalations_pruefung.py). Rundung: Fehlstunden werden erst am Ende aus den
    aufsummierten Roh-Minuten gerundet (einmal fuer gesamt, einmal je fuer entschuldigt/
    unentschuldigt) - nicht aus der Summe zweier bereits gerundeter Werte. Dadurch stimmt
    "gesamt" mit dem ueberein, was eskalations_pruefung.py/dashboard_query.py fuer denselben
    Zeitraum berechnen (einmalige Rundung der Gesamt-Minuten); "entschuldigt + unentschuldigt"
    kann davon aufgrund unabhaengiger Rundung der beiden Teilwerte um 0.01 abweichen."""
    ergebnis: dict[int, dict[str, Any]] = {
        sid: {
            "fehltage": _leerer_fehltage_split(),
            "fehlstunden": _leerer_fehlstunden_split(),
            "klassenbuch_anzahl": 0,
        }
        for sid in schueler_ids
    }
    if not schueler_ids:
        return ergebnis

    fehlstunden_minuten: dict[int, dict[str, int]] = {
        sid: {"gesamt": 0, "entschuldigt": 0, "unentschuldigt": 0} for sid in schueler_ids
    }

    entschuldigt_expr = func.coalesce(ExcuseStatus.zaehlt_als_entschuldigt, False).label("entschuldigt")
    fehlzeit_result = await db.execute(
        select(
            Fehlzeit.schueler_id,
            Fehlzeit.typ,
            entschuldigt_expr,
            func.count().label("anzahl"),
            func.sum(fehlstunden_minuten_expr()).label("minuten"),
        )
        .outerjoin(ExcuseStatus, Fehlzeit.excuse_status_id == ExcuseStatus.id)
        .where(
            Fehlzeit.schueler_id.in_(schueler_ids),
            Fehlzeit.invalid.is_(False),
            *_fehlzeit_datum_filter(von, bis),
        )
        .group_by(Fehlzeit.schueler_id, Fehlzeit.typ, entschuldigt_expr)
    )
    for schueler_id, typ, entschuldigt, anzahl, minuten in fehlzeit_result.all():
        split_key = "entschuldigt" if entschuldigt else "unentschuldigt"
        if typ == "tag":
            ergebnis[schueler_id]["fehltage"]["gesamt"] += anzahl
            ergebnis[schueler_id]["fehltage"][split_key] += anzahl
        elif typ == "stunde":
            fehlstunden_minuten[schueler_id]["gesamt"] += minuten
            fehlstunden_minuten[schueler_id][split_key] += minuten

    for schueler_id, minuten_split in fehlstunden_minuten.items():
        ergebnis[schueler_id]["fehlstunden"] = {
            "gesamt": minuten_zu_fehlstunden(minuten_split["gesamt"]),
            "entschuldigt": minuten_zu_fehlstunden(minuten_split["entschuldigt"]),
            "unentschuldigt": minuten_zu_fehlstunden(minuten_split["unentschuldigt"]),
        }

    klassenbuch_result = await db.execute(
        select(KlassenbuchEintrag.schueler_id, func.count())
        .where(KlassenbuchEintrag.schueler_id.in_(schueler_ids), *_klassenbuch_datum_filter(von, bis))
        .group_by(KlassenbuchEintrag.schueler_id)
    )
    for schueler_id, anzahl in klassenbuch_result.all():
        ergebnis[schueler_id]["klassenbuch_anzahl"] = anzahl

    return ergebnis


async def load_student_detail(
    db: AsyncSession, schueler_id: int, von: date | None = None, bis: date | None = None
) -> dict[str, Any]:
    """Laedt alle Unterlisten fuer die Detailansicht eines Schuelers.

    Ohne von/bis (Standard): unveraendertes Verhalten, alle Zeilen, zaehlerstand befuellt.
    Mit von/bis (Historie-Modus fuer ein vergangenes Schuljahr): fehlzeiten/klassenbuch/
    ausnahmen/benachrichtigungen werden auf den Zeitraum gefiltert; massnahmen bleibt bewusst
    ungefiltert (SPECS.md: Massnahmen sollen unabhaengig vom betrachteten Schuljahr sichtbar
    bleiben); zaehlerstand ist in diesem Modus nicht aussagekraeftig (bezieht sich nur auf das
    aktuelle Schuljahr) und wird daher als leeres dict geliefert.
    """
    fehlzeiten_query = select(Fehlzeit).where(Fehlzeit.schueler_id == schueler_id)
    klassenbuch_query = select(KlassenbuchEintrag).where(KlassenbuchEintrag.schueler_id == schueler_id)
    # Liefert alle Ausnahmen (aktiv und aufgehoben) fuer die Detailansicht - das Design (siehe
    # docs/superpowers/specs/2026-07-28-schuelerliste-detail-design.md Abschnitt 5, Punkt 5) will
    # eine "Liste aller Eintraege" inkl. aktiv-Status, nicht nur die aktiven.
    ausnahmen_query = select(Ausnahme).where(Ausnahme.schueler_id == schueler_id)
    benachrichtigungen_query = select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id)

    if von is not None and bis is not None:
        fehlzeiten_query = fehlzeiten_query.where(Fehlzeit.datum.between(von, bis))
        klassenbuch_query = klassenbuch_query.where(KlassenbuchEintrag.datum.between(von, bis))
        # Ausnahme hat keine gueltig_von-Spalte (nur gueltig_bis, nullable, plus created_at aus
        # TimestampMixin) - created_at's Datum dient als praktischer Start der Gueltigkeit.
        ausnahmen_query = ausnahmen_query.where(
            func.date(Ausnahme.created_at) <= bis, or_(Ausnahme.gueltig_bis.is_(None), Ausnahme.gueltig_bis >= von)
        )
        benachrichtigungen_query = benachrichtigungen_query.where(
            func.date(Benachrichtigung.gesendet_am).between(von, bis)
        )

    fehlzeiten = (await db.execute(fehlzeiten_query.order_by(Fehlzeit.datum.desc()))).scalars().all()
    klassenbuch = (await db.execute(klassenbuch_query.order_by(KlassenbuchEintrag.datum.desc()))).scalars().all()
    ausnahmen = (await db.execute(ausnahmen_query)).scalars().all()
    benachrichtigungen = (
        (await db.execute(benachrichtigungen_query.order_by(Benachrichtigung.gesendet_am.desc()))).scalars().all()
    )

    massnahmen_rows = (
        await db.execute(
            select(Massnahme, MassnahmenTyp.name, Nutzer.name)
            .join(MassnahmenTyp, MassnahmenTyp.id == Massnahme.massnahmen_typ_id)
            .join(Nutzer, Nutzer.id == Massnahme.erfasst_von_nutzer_id)
            .where(Massnahme.schueler_id == schueler_id)
            .order_by(Massnahme.datum.desc())
        )
    ).all()

    zaehlerstand: dict[str, Any] = {}
    if von is None and bis is None:
        zaehlerstand = (await load_zaehlerstand_map(db, [schueler_id]))[schueler_id]

    rohzahlen = (await load_schueler_rohzahlen(db, [schueler_id], von, bis))[schueler_id]

    return {
        "fehlzeiten": list(fehlzeiten),
        "klassenbuch": list(klassenbuch),
        "massnahmen": list(massnahmen_rows),
        "ausnahmen": list(ausnahmen),
        "benachrichtigungen": list(benachrichtigungen),
        "zaehlerstand": zaehlerstand,
        "fehltage": rohzahlen["fehltage"],
        "fehlstunden": rohzahlen["fehlstunden"],
        "klassenbuch_anzahl": rohzahlen["klassenbuch_anzahl"],
    }
