from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import bereich_klasse
from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.core.config import Settings
from app.services.mailer import TEMPLATES_DIR, render_template, send_email

logger = logging.getLogger(__name__)

# Sentinel: unterscheidet "Aufrufer hat keine Zeile uebergeben" von "Aufrufer hat
# uebergeben, dass keine Zeile existiert" - None ist hier ein gueltiger Wert.
_ZAEHLERSTAND_NICHT_ANGEGEBEN: Any = object()


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
    db: AsyncSession,
    schueler_id: int,
    typ: str,
    regel_id: int,
    bestehender: SchuelerZaehlerstand | None = _ZAEHLERSTAND_NICHT_ANGEGEBEN,
) -> SchuelerZaehlerstand:
    zaehlerstand = bestehender
    if zaehlerstand is _ZAEHLERSTAND_NICHT_ANGEGEBEN:
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


async def _resolve_empfaenger(db: AsyncSession, klasse_id: int | None, rollen: list[str]) -> list[dict]:
    empfaenger: list[dict] = []
    for rolle in rollen:
        if rolle == "klassenlehrkraft" and klasse_id is not None:
            result = await db.execute(
                select(Nutzer.id).distinct().join(NutzerKlasse, NutzerKlasse.nutzer_id == Nutzer.id).where(
                    NutzerKlasse.klasse_id == klasse_id
                )
            )
            empfaenger.extend({"rolle": rolle, "nutzer_id": nutzer_id} for nutzer_id in result.scalars().all())
        elif rolle == "bereichsleiter" and klasse_id is not None:
            result = await db.execute(
                select(Nutzer.id)
                .distinct()
                .join(nutzer_bereich, nutzer_bereich.c.nutzer_id == Nutzer.id)
                .join(bereich_klasse, bereich_klasse.c.bereich_id == nutzer_bereich.c.bereich_id)
                .where(bereich_klasse.c.klasse_id == klasse_id)
            )
            empfaenger.extend({"rolle": rolle, "nutzer_id": nutzer_id} for nutzer_id in result.scalars().all())
        elif rolle == "schulleitung":
            result = await db.execute(select(Nutzer.id).where(Nutzer.rolle == "schulleitung"))
            empfaenger.extend({"rolle": rolle, "nutzer_id": nutzer_id} for nutzer_id in result.scalars().all())
    return empfaenger


_TYP_LABEL = {"fehlzeiten": "Fehlzeiten", "klassenbuch": "Klassenbucheinträge"}


def _eindeutige_nutzer_ids(empfaenger: list[dict]) -> list[int]:
    """Ein Nutzer mit mehreren Rollen (z.B. Klassenlehrkraft UND Bereichsleiter) darf nur eine Mail bekommen."""
    return list(dict.fromkeys(e["nutzer_id"] for e in empfaenger))


async def _versende_email(
    db: AsyncSession,
    schueler: Schueler,
    regel: SchwellwertRegel,
    stufe: SchwellwertStufe,
    neuer_stand: int,
    empfaenger: list[dict],
    settings: Settings,
) -> str:
    nutzer_ids = _eindeutige_nutzer_ids(empfaenger)
    result = await db.execute(select(Nutzer.email).where(Nutzer.id.in_(nutzer_ids)))
    to_addresses = list(result.scalars().all())

    klasse_name = "–"
    if schueler.klasse_id is not None:
        klasse_result = await db.execute(select(Klasse.name).where(Klasse.id == schueler.klasse_id))
        gefundener_name = klasse_result.scalar_one_or_none()
        if gefundener_name is not None:
            klasse_name = gefundener_name

    einheit_label = (stufe.einheit or _TYP_LABEL.get(regel.typ, regel.typ)).capitalize()
    dashboard_link = f"{settings.dashboard_base_url}/students/{schueler.id}"

    try:
        subject, body = render_template(
            TEMPLATES_DIR,
            schueler_vorname=schueler.vorname,
            schueler_nachname=schueler.nachname,
            klasse=klasse_name,
            regel_typ=_TYP_LABEL.get(regel.typ, regel.typ),
            stufe_nr=str(stufe.stufe_nr),
            zaehlerstand=str(neuer_stand),
            einheit=einheit_label,
            dashboard_link=dashboard_link,
        )
    except (ValueError, KeyError, OSError):
        logger.exception(
            "Mail-Template fehlerhaft (Admin-Override oder Default) fuer Schueler %d, Regel %d, Stufe %d",
            schueler.id, regel.id, stufe.stufe_nr,
        )
        return "fehler"

    try:
        await send_email(settings, to_addresses, subject, body)
    except Exception:
        logger.exception(
            "E-Mail-Versand fehlgeschlagen fuer Schueler %d, Regel %d, Stufe %d",
            schueler.id, regel.id, stufe.stufe_nr,
        )
        return "fehler"
    return "gesendet"


async def _schreibe_benachrichtigung(
    db: AsyncSession,
    schueler: Schueler,
    regel: SchwellwertRegel,
    stufe_nr: int,
    neuer_stand: int,
    einstellung: Einstellung,
    settings: Settings,
) -> None:
    stufe = (
        await db.execute(
            select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id, SchwellwertStufe.stufe_nr == stufe_nr)
        )
    ).scalar_one()

    if not einstellung.initialer_import_abgeschlossen:
        status = "initial_import"
        empfaenger: list[dict] = []
    else:
        empfaenger = await _resolve_empfaenger(db, schueler.klasse_id, stufe.empfaenger_rollen)
        if not empfaenger:
            status = "kein_empfaenger"
        else:
            status = await _versende_email(db, schueler, regel, stufe, neuer_stand, empfaenger, settings)

    db.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            regel_id=regel.id,
            stufe_nr=stufe_nr,
            gesendet_am=datetime.now(timezone.utc),
            empfaenger=empfaenger,
            status=status,
        )
    )


async def pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung, settings: Settings) -> None:
    """Kernschleife: fuer jeden aktiven Schueler und Regel-Typ Zaehlerstand neu berechnen (SPECS.md Abschnitt 5)."""
    schueler_result = await db.execute(select(Schueler).where(Schueler.aktiv.is_(True)))
    alle_schueler = schueler_result.scalars().all()

    kein_schuljahr_start = einstellung.schuljahr_start_cache is None
    if kein_schuljahr_start:
        logger.warning(
            "einstellung.schuljahr_start_cache ist nicht gesetzt - Schueler ohne eigenen letzter_reset_am "
            "werden in diesem Lauf uebersprungen"
        )

    for typ in ("fehlzeiten", "klassenbuch"):
        regel_cache: dict[int | None, SchwellwertRegel | None] = {}
        for schueler in alle_schueler:
            if await _hat_aktive_ausnahme(db, schueler.id, typ, heute):
                continue

            if schueler.klasse_id not in regel_cache:
                regel_cache[schueler.klasse_id] = await resolve_schwellwert_regel(db, schueler.klasse_id, typ)
            regel = regel_cache[schueler.klasse_id]
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
                # Defensiv: bei gesetztem schuljahr_start_cache aktuell nicht erreichbar
                # (Kandidatenliste waere nie leer); Warnung nur fuer kuenftige Fenster-Quellen.
                if not kein_schuljahr_start:
                    logger.warning(
                        "Kein Fenster-Start ermittelbar fuer Schueler %d, Regel %d (kein letzter_reset_am) - "
                        "uebersprungen",
                        schueler.id,
                        regel.id,
                    )
                continue
            fenster_start = max(fenster_kandidaten)

            zaehlerstand = await get_or_create_zaehlerstand(
                db, schueler.id, typ, regel.id, bestehender=bestehender_zaehlerstand
            )
            neue_stufe_nr, neuer_stand = await _ermittle_erreichte_stufe(db, regel, schueler.id, fenster_start)

            alte_stufe_nr = zaehlerstand.erreichte_stufe_nr
            zaehlerstand.erreichte_stufe_nr = neue_stufe_nr
            zaehlerstand.aktueller_stand = neuer_stand

            if neue_stufe_nr is not None and (alte_stufe_nr is None or neue_stufe_nr > alte_stufe_nr):
                await _schreibe_benachrichtigung(db, schueler, regel, neue_stufe_nr, neuer_stand, einstellung, settings)
