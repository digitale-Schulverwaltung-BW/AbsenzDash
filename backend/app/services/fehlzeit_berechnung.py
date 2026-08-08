from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import ColumnElement

from app.models.fehlzeit import Fehlzeit
from app.models.stundenraster_periode import StundenrasterPeriode

STUNDENLAENGE_MINUTEN = 45


def _hhmm_zu_minuten(spalte: ColumnElement) -> ColumnElement:
    """Wandelt eine WebUntis-Uhrzeitspalte im HHMM-Format (z.B. 815 fuer 08:15) in Minuten
    seit Mitternacht um. Eine reine Integer-Subtraktion (end_zeit - start_zeit) waere bei
    Perioden, die eine Stundengrenze ueberschreiten (z.B. 730 -> 815), falsch (85 statt 45
    Minuten) - siehe TECH-SPEC.md Abschnitt 1.2 fuer das HHMM-Format-Beispiel."""
    return (spalte // 100) * 60 + (spalte % 100)


def _hhmm_zu_minuten_wert(value: int) -> int:
    """Wie _hhmm_zu_minuten, aber fuer einen einzelnen Python-Integer statt eine SQL-Spalte
    (fuer die Anzeige-Berechnung ausserhalb einer Query, siehe dauer_anzeige)."""
    return (value // 100) * 60 + (value % 100)


def _hhmm_formatiert(value: int) -> str:
    """Formatiert einen WebUntis-HHMM-Integer (z.B. 730) als Uhrzeit-String ('7:30')."""
    return f"{value // 100}:{value % 100:02d}"


def fehlstunden_minuten_expr() -> ColumnElement:
    """SQL-Ausdruck: Dauer in Minuten je Fehlzeit-Zeile. Nur fuer typ='stunde' sinnvoll -
    bei typ='tag' sind start_zeit/end_zeit feste Platzhalter (0/2359), keine echte Zeitspanne."""
    return _hhmm_zu_minuten(Fehlzeit.end_zeit) - _hhmm_zu_minuten(Fehlzeit.start_zeit)


def minuten_zu_fehlstunden(minuten: int | None) -> Decimal:
    """Rundet eine Minuten-Summe auf Fehlstunden (Dezimalzahl, Basis 45 Minuten/Stunde)."""
    if not minuten:
        return Decimal("0.00")
    return (Decimal(minuten) / Decimal(STUNDENLAENGE_MINUTEN)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dauer_anzeige(fehlzeit: Fehlzeit, perioden_by_wochentag: dict[int, list[StundenrasterPeriode]]) -> str:
    """Anzeige-Label fuer eine Fehlzeit (Schueler-Detail + PDF-Export, siehe
    docs/superpowers/specs/2026-08-08-fehlzeit-stunden-anzeige-design.md):

    - typ='tag' -> 'ganztägig'.
    - typ='stunde' mit Rastertreffer -> '{minuten} Minuten (Stunde {n})' bzw. bei mehreren
      aufeinanderfolgenden Perioden '{minuten} Minuten (Stunde {min}-{max})'.
    - typ='stunde' ohne Rastertreffer (Luecke im Raster, kein Raster synchronisiert) ->
      Fallback auf die formatierte Uhrzeitspanne, '{minuten} Minuten ({start}–{end})'.

    perioden_by_wochentag ist nach ISO-Wochentag (date.isoweekday(), 1=Montag) gruppiert -
    siehe student_query.load_stundenraster_by_wochentag.
    """
    if fehlzeit.typ == "tag":
        return "ganztägig"

    minuten = _hhmm_zu_minuten_wert(fehlzeit.end_zeit) - _hhmm_zu_minuten_wert(fehlzeit.start_zeit)
    perioden = perioden_by_wochentag.get(fehlzeit.datum.isoweekday(), [])
    treffer = [p for p in perioden if p.start_zeit < fehlzeit.end_zeit and p.end_zeit > fehlzeit.start_zeit]

    if treffer:
        stunden_nrs = sorted(p.stunde_nr for p in treffer)
        if stunden_nrs[0] == stunden_nrs[-1]:
            stunde_text = f"Stunde {stunden_nrs[0]}"
        else:
            stunde_text = f"Stunde {stunden_nrs[0]}-{stunden_nrs[-1]}"
        return f"{minuten} Minuten ({stunde_text})"

    return f"{minuten} Minuten ({_hhmm_formatiert(fehlzeit.start_zeit)}–{_hhmm_formatiert(fehlzeit.end_zeit)})"
