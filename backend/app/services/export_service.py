from __future__ import annotations

import datetime
import re
import unicodedata
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.services import student_query

_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
)
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)
_BERLIN_TZ = ZoneInfo("Europe/Berlin")


def build_export_filename(nachname: str, vorname: str) -> str:
    """Baut einen sicheren Dateinamen fuer den Content-Disposition-Header: deutsche
    Umlaute/Eszett explizit transliteriert, alle anderen diakritischen Zeichen per
    NFKD-Normalisierung auf den Basis-Buchstaben reduziert, verbleibende
    Nicht-ASCII-/Sonderzeichen (inkl. Leerzeichen) durch '-' ersetzt."""
    raw = f"{nachname}_{vorname}_export".translate(_UMLAUT_MAP)
    ascii_normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9_]+", "-", ascii_normalized).strip("-")
    return f"{normalized}.pdf"


async def render_student_export_html(
    db: AsyncSession,
    schueler: Schueler,
    klasse: Klasse | None,
    sections: set[str],
    von: datetime.date | None = None,
    bis: datetime.date | None = None,
    schuljahr_name: str | None = None,
) -> str:
    """Laedt die Detaildaten des Schuelers und rendert das PDF-Export-Template zu HTML.
    Enthaelt nur die in `sections` angeforderten Abschnitte; Namen fuer
    excuse_status/classreg_category werden hier aufgeloest (in den *Out-Schemas
    fuer GET /students/{id} bisher nicht aufgeloest)."""
    detail = await student_query.load_student_detail(db, schueler.id, von=von, bis=bis)

    fehlzeiten: list[dict[str, Any]] = []
    if "fehlzeiten" in sections:
        excuse_status_ids = [f.excuse_status_id for f in detail["fehlzeiten"] if f.excuse_status_id is not None]
        excuse_status_map = await student_query.load_excuse_status_map(db, excuse_status_ids)
        for f in detail["fehlzeiten"]:
            status = excuse_status_map.get(f.excuse_status_id) if f.excuse_status_id is not None else None
            fehlzeiten.append(
                {
                    "datum": f.datum.strftime("%d.%m.%Y"),
                    "typ": f.typ,
                    "fach": f.fach,
                    "excuse_status_name": (status.long_name or status.name) if status else None,
                    "grund_text": f.grund_text,
                }
            )

    klassenbuch: list[dict[str, Any]] = []
    if "klassenbuch" in sections:
        kategorie_ids = [k.kategorie_id for k in detail["klassenbuch"]]
        kategorie_map = await student_query.load_classreg_category_map(db, kategorie_ids)
        for k in detail["klassenbuch"]:
            kategorie = kategorie_map.get(k.kategorie_id)
            klassenbuch.append(
                {
                    "datum": k.datum.strftime("%d.%m.%Y"),
                    "kategorie_name": (kategorie.long_name or kategorie.name) if kategorie else None,
                    "text": k.text,
                }
            )

    massnahmen: list[dict[str, Any]] = []
    if "massnahmen" in sections:
        for massnahme, typ_name, nutzer_name in detail["massnahmen"]:
            massnahmen.append(
                {
                    "datum": massnahme.datum.strftime("%d.%m.%Y"),
                    "massnahmen_typ_name": typ_name,
                    "notiz": massnahme.notiz,
                    "erfasst_von_name": nutzer_name,
                }
            )

    ausnahmen: list[dict[str, Any]] = []
    if "ausnahmen" in sections:
        for a in detail["ausnahmen"]:
            ausnahmen.append(
                {
                    "kategorie": a.kategorie,
                    "grund": a.grund,
                    "gueltig_bis": a.gueltig_bis.strftime("%d.%m.%Y") if a.gueltig_bis else None,
                }
            )

    benachrichtigungen: list[dict[str, Any]] = []
    if "benachrichtigungen" in sections:
        regel_ids = [b.regel_id for b in detail["benachrichtigungen"] if b.regel_id is not None]
        regel_typ_map = await student_query.load_regel_typ_map(db, regel_ids)
        for b in detail["benachrichtigungen"]:
            benachrichtigungen.append(
                {
                    "gesendet_am": b.gesendet_am.astimezone(_BERLIN_TZ).strftime("%d.%m.%Y %H:%M"),
                    "typ": regel_typ_map.get(b.regel_id) if b.regel_id is not None else None,
                    "stufe_nr": b.stufe_nr,
                    "empfaenger_text": ", ".join(e.get("rolle", "?") for e in b.empfaenger) or "-",
                    "status": b.status,
                }
            )

    template = _jinja_env.get_template("export_pdf.html")
    return template.render(
        schueler=schueler,
        klasse=klasse,
        sections=sections,
        erstellt_am=datetime.datetime.now(_BERLIN_TZ).strftime("%d.%m.%Y %H:%M"),
        fehlzeiten=fehlzeiten,
        klassenbuch=klassenbuch,
        massnahmen=massnahmen,
        ausnahmen=ausnahmen,
        benachrichtigungen=benachrichtigungen,
        schuljahr_name=schuljahr_name,
    )


def html_to_pdf(html: str) -> bytes:
    """Duenner Wrapper um WeasyPrint, isoliert damit Tests HTML-Inhalt direkt pruefen
    koennen, ohne PDF-Bytes parsen zu muessen."""
    return HTML(string=html).write_pdf()
