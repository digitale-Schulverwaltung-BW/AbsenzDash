from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.stundenraster_periode import StundenrasterPeriode

logger = logging.getLogger(__name__)

# WebUntis' eigene Wochentag-Konvention (1=Sonntag...7=Samstag, siehe TECH-SPEC.md
# Abschnitt 1.4) auf ISO-Wochentag (1=Montag...7=Sonntag, wie date.isoweekday())
# umgerechnet - intern wird ausschliesslich ISO verwendet.
_WEBUNTIS_TAG_ZU_ISO = {1: 7, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}


async def sync_stundenraster(client: WebUntisClient, db: AsyncSession) -> None:
    """getTimegridUnits -> stundenraster_periode (TECH-SPEC.md Abschnitt 1.4).

    getTimegridUnits nimmt ausschliesslich einen leeren Parameter-Body entgegen (live
    verifiziert, jeder zusaetzliche Parameter fuehrt zu 'Method not found') und liefert
    den schulweiten Stundenraster. Schlaegt der Aufruf fehl (z.B. waehrend der
    Schuljahres-Uebergangsluecke, TECH-SPEC.md Abschnitt 1.3a/1.4) oder liefert eine
    leere/None-Antwort, bleibt die Tabelle unveraendert - kein kritischer Sync-Schritt,
    der Uhrzeit-Fallback in fehlzeit_berechnung.dauer_anzeige greift automatisch.
    """
    try:
        tage = await client.call("getTimegridUnits", {})
    except WebUntisError as exc:
        logger.warning("getTimegridUnits fehlgeschlagen, stundenraster_periode bleibt unveraendert: %s", exc)
        return

    if not tage:
        logger.warning("getTimegridUnits lieferte keine Daten, stundenraster_periode bleibt unveraendert")
        return

    neue_perioden: list[StundenrasterPeriode] = []

    for tag in tage:
        try:
            tag_day = tag.get("day")
        except AttributeError:
            logger.warning("getTimegridUnits: Tag-Eintrag ist kein Objekt (%r), uebersprungen", tag)
            continue

        wochentag = _WEBUNTIS_TAG_ZU_ISO.get(tag_day)
        if wochentag is None:
            logger.warning("getTimegridUnits: unbekannter Wochentag-Wert %s, uebersprungen", tag_day)
            continue

        try:
            roh_time_units = tag.get("timeUnits", []) or []
        except (TypeError, AttributeError) as exc:
            logger.warning(
                "getTimegridUnits: timeUnits fuer Wochentag %s nicht lesbar (%s), uebersprungen",
                wochentag,
                exc,
            )
            continue

        gueltige_units = []
        for unit in roh_time_units:
            try:
                start_zeit = unit["startTime"]
                end_zeit = unit["endTime"]
            except (TypeError, KeyError) as exc:
                logger.warning(
                    "getTimegridUnits: timeUnit fuer Wochentag %s fehlerhaft (%s), uebersprungen",
                    wochentag,
                    exc,
                )
                continue
            gueltige_units.append((start_zeit, end_zeit))

        try:
            gueltige_units.sort(key=lambda zeiten: zeiten[0])
        except TypeError as exc:
            logger.warning(
                "getTimegridUnits: timeUnits fuer Wochentag %s nicht sortierbar (%s), uebersprungen",
                wochentag,
                exc,
            )
            continue

        for stunde_nr, (start_zeit, end_zeit) in enumerate(gueltige_units, start=1):
            neue_perioden.append(
                StundenrasterPeriode(
                    wochentag=wochentag,
                    stunde_nr=stunde_nr,
                    start_zeit=start_zeit,
                    end_zeit=end_zeit,
                )
            )

    if not neue_perioden:
        logger.warning(
            "getTimegridUnits lieferte keine verwertbaren Perioden, stundenraster_periode bleibt unveraendert"
        )
        return

    await db.execute(delete(StundenrasterPeriode))
    db.add_all(neue_perioden)
    await db.commit()
