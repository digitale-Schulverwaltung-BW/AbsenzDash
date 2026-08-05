from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import ColumnElement

from app.models.fehlzeit import Fehlzeit

STUNDENLAENGE_MINUTEN = 45


def _hhmm_zu_minuten(spalte: ColumnElement) -> ColumnElement:
    """Wandelt eine WebUntis-Uhrzeitspalte im HHMM-Format (z.B. 815 fuer 08:15) in Minuten
    seit Mitternacht um. Eine reine Integer-Subtraktion (end_zeit - start_zeit) waere bei
    Perioden, die eine Stundengrenze ueberschreiten (z.B. 730 -> 815), falsch (85 statt 45
    Minuten) - siehe TECH-SPEC.md Abschnitt 1.2 fuer das HHMM-Format-Beispiel."""
    return (spalte // 100) * 60 + (spalte % 100)


def fehlstunden_minuten_expr() -> ColumnElement:
    """SQL-Ausdruck: Dauer in Minuten je Fehlzeit-Zeile. Nur fuer typ='stunde' sinnvoll -
    bei typ='tag' sind start_zeit/end_zeit feste Platzhalter (0/2359), keine echte Zeitspanne."""
    return _hhmm_zu_minuten(Fehlzeit.end_zeit) - _hhmm_zu_minuten(Fehlzeit.start_zeit)


def minuten_zu_fehlstunden(minuten: int | None) -> Decimal:
    """Rundet eine Minuten-Summe auf Fehlstunden (Dezimalzahl, Basis 45 Minuten/Stunde)."""
    if not minuten:
        return Decimal("0.00")
    return (Decimal(minuten) / Decimal(STUNDENLAENGE_MINUTEN)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
