from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ausnahme import Ausnahme
from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe

logger = logging.getLogger(__name__)


async def resolve_schwellwert_regel(
    db: AsyncSession, klasse_id: int | None, typ: str
) -> SchwellwertRegel | None:
    """Loest die zutreffende Regel nach Praezedenz auf: klassen-spezifisch > abteilungs-spezifisch > schulweit."""
    if klasse_id is not None:
        result = await db.execute(
            select(SchwellwertRegel).where(SchwellwertRegel.typ == typ, SchwellwertRegel.klasse_id == klasse_id)
        )
        regel = result.scalar_one_or_none()
        if regel is not None:
            return regel

        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is not None and klasse.abteilung_id is not None:
            result = await db.execute(
                select(SchwellwertRegel).where(
                    SchwellwertRegel.typ == typ, SchwellwertRegel.abteilung_id == klasse.abteilung_id
                )
            )
            regel = result.scalar_one_or_none()
            if regel is not None:
                return regel

    result = await db.execute(
        select(SchwellwertRegel).where(SchwellwertRegel.typ == typ, SchwellwertRegel.geltungsbereich == "schulweit")
    )
    return result.scalar_one_or_none()


async def get_or_create_zaehlerstand(
    db: AsyncSession, schueler_id: int, typ: str, regel_id: int
) -> SchuelerZaehlerstand:
    result = await db.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler_id, SchuelerZaehlerstand.typ == typ
        )
    )
    zaehlerstand = result.scalar_one_or_none()
    if zaehlerstand is None:
        zaehlerstand = SchuelerZaehlerstand(schueler_id=schueler_id, typ=typ, regel_id=regel_id, aktueller_stand=0)
        db.add(zaehlerstand)
        await db.flush()
    else:
        zaehlerstand.regel_id = regel_id  # kann sich bei Klassenwechsel aendern; Zaehlerstand selbst bleibt erhalten
    return zaehlerstand


async def _zaehle_fuer_stufe(
    db: AsyncSession, regel: SchwellwertRegel, stufe: SchwellwertStufe, schueler_id: int, fenster_start: date
) -> int:
    if regel.typ == "fehlzeiten":
        query = select(func.count()).select_from(Fehlzeit).where(
            Fehlzeit.schueler_id == schueler_id,
            Fehlzeit.datum >= fenster_start,
            Fehlzeit.invalid.is_(False),
            Fehlzeit.typ == ("tag" if stufe.einheit == "fehltage" else "stunde"),
        )
        if stufe.fehlzeiten_filter == "nur_unentschuldigt":
            query = query.outerjoin(ExcuseStatus, Fehlzeit.excuse_status_id == ExcuseStatus.id).where(
                or_(Fehlzeit.excuse_status_id.is_(None), ExcuseStatus.zaehlt_als_entschuldigt.is_(False))
            )
        result = await db.execute(query)
        return result.scalar_one()

    result = await db.execute(
        select(func.count()).select_from(KlassenbuchEintrag).where(
            KlassenbuchEintrag.schueler_id == schueler_id, KlassenbuchEintrag.datum >= fenster_start
        )
    )
    return result.scalar_one()


async def _ermittle_erreichte_stufe(
    db: AsyncSession, regel: SchwellwertRegel, schueler_id: int, fenster_start: date
) -> tuple[int | None, int]:
    """Prueft Stufen absteigend; gibt (erreichte_stufe_nr, aktueller_stand) zurueck.

    aktueller_stand ist bei keiner erreichten Stufe der Zaehlwert nach Stufe-1-Definition
    (letzte Loop-Iteration, da absteigend sortiert) - fuer Fortschrittsanzeige im Dashboard.
    """
    stufen_result = await db.execute(
        select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id).order_by(SchwellwertStufe.stufe_nr.desc())
    )
    stufen = stufen_result.scalars().all()

    letzter_stand = 0
    for stufe in stufen:
        anzahl = await _zaehle_fuer_stufe(db, regel, stufe, schueler_id, fenster_start)
        letzter_stand = anzahl
        if anzahl >= stufe.schwellenwert:
            return stufe.stufe_nr, anzahl

    return None, letzter_stand


async def _hat_aktive_ausnahme(db: AsyncSession, schueler_id: int, kategorie: str, heute: date) -> bool:
    result = await db.execute(
        select(Ausnahme).where(
            Ausnahme.schueler_id == schueler_id,
            Ausnahme.kategorie == kategorie,
            Ausnahme.aktiv.is_(True),
            or_(Ausnahme.gueltig_bis.is_(None), Ausnahme.gueltig_bis >= heute),
        )
    )
    return result.first() is not None


async def pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung) -> None:
    """Kernschleife: fuer jeden aktiven Schueler und Regel-Typ Zaehlerstand neu berechnen (SPECS.md Abschnitt 5)."""
    schueler_result = await db.execute(select(Schueler).where(Schueler.aktiv.is_(True)))
    alle_schueler = schueler_result.scalars().all()

    for typ in ("fehlzeiten", "klassenbuch"):
        for schueler in alle_schueler:
            if await _hat_aktive_ausnahme(db, schueler.id, typ, heute):
                continue

            regel = await resolve_schwellwert_regel(db, schueler.klasse_id, typ)
            if regel is None:
                continue

            bestehender_result = await db.execute(
                select(SchuelerZaehlerstand).where(
                    SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.typ == typ
                )
            )
            bestehender_zaehlerstand = bestehender_result.scalar_one_or_none()

            fenster_kandidaten = [
                d
                for d in (
                    einstellung.schuljahr_start_cache,
                    bestehender_zaehlerstand.letzter_reset_am if bestehender_zaehlerstand else None,
                )
                if d is not None
            ]
            if not fenster_kandidaten:
                logger.warning(
                    "Kein Fenster-Start ermittelbar fuer Schueler %d, Regel %d (kein schuljahr_start_cache, "
                    "kein letzter_reset_am) - uebersprungen",
                    schueler.id,
                    regel.id,
                )
                continue
            fenster_start = max(fenster_kandidaten)

            zaehlerstand = await get_or_create_zaehlerstand(db, schueler.id, typ, regel.id)
            neue_stufe_nr, neuer_stand = await _ermittle_erreichte_stufe(db, regel, schueler.id, fenster_start)

            zaehlerstand.erreichte_stufe_nr = neue_stufe_nr
            zaehlerstand.aktueller_stand = neuer_stand
