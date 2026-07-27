# PDF-Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GET /students/{schueler_id}/export.pdf` — a configurable-sections PDF export of a student's Fehlzeiten/Klassenbuch/Maßnahmen/Ausnahmen/Benachrichtigungen history, rendered via WeasyPrint, with repeating table headers and a page-numbered footer.

**Architecture:** Reuses the existing `get_scoped_schueler` dependency and `student_query.load_student_detail()` for data access (no new queries beyond two small name-resolution lookups). A new `export_service.py` renders a Jinja2 HTML template to PDF bytes via WeasyPrint. The route validates the `sections` query param, writes an `AuditLog` entry, and returns the PDF with a normalized `Content-Disposition` filename.

**Tech Stack:** FastAPI, SQLAlchemy (async), Jinja2, WeasyPrint. No new DB tables/columns — no Alembic migration in this plan.

## Global Constraints

- Commit messages in English (user's global git workflow convention).
- Code identifiers, docstrings, and inline comments follow the existing codebase convention of German domain language (`Schueler`, `Massnahme`, `Fehlzeit`, etc.) — match the style already in `backend/app/services/student_query.py` and `backend/app/services/massnahme_service.py`.
- No placeholders: every step below has literal, runnable code.
- Reference design doc: [docs/superpowers/specs/2026-07-27-pdf-export-design.md](../specs/2026-07-27-pdf-export-design.md).

---

## File Structure

```
backend/
  requirements.txt                       # + weasyprint, jinja2
  Dockerfile                             # + apt packages for WeasyPrint
  app/
    services/
      student_query.py                   # + load_excuse_status_map, load_classreg_category_map
      export_service.py                  # new: build_export_filename, render_student_export_html, html_to_pdf
    templates/
      export_pdf.html                    # new: Jinja2 template incl. embedded CSS
    api/routes/
      students.py                        # + GET /{schueler_id}/export.pdf
  tests/
    test_student_query.py                # + tests for the two new maps
    test_export_service.py               # new: filename + HTML rendering + PDF bytes tests
    test_api_students.py                 # + integration tests for the new route
docs/
  backend-setup.md                       # + PDF-Export section, "Aktueller Stand" updated
ROADMAP.md                                # PDF-Export moved from "Geplant" to "Abgeschlossen"
```

---

### Task 1: Name-resolution maps for excuse status and Klassenbuch category

**Files:**
- Modify: `backend/app/services/student_query.py`
- Test: `backend/tests/test_student_query.py`

**Interfaces:**
- Produces: `load_excuse_status_map(db: AsyncSession, excuse_status_ids: list[int]) -> dict[int, ExcuseStatus]`
- Produces: `load_classreg_category_map(db: AsyncSession, kategorie_ids: list[int]) -> dict[int, ClassregCategory]`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_student_query.py`:

```python
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus


@pytest.mark.asyncio
async def test_load_excuse_status_map_returns_rows_by_id(db_session):
    status_a = ExcuseStatus(name="E", long_name="Entschuldigt", zaehlt_als_entschuldigt=True)
    status_b = ExcuseStatus(name="U", long_name="Unentschuldigt", zaehlt_als_entschuldigt=False)
    db_session.add_all([status_a, status_b])
    await db_session.commit()

    result = await student_query.load_excuse_status_map(db_session, [status_a.id])
    assert set(result.keys()) == {status_a.id}
    assert result[status_a.id].long_name == "Entschuldigt"


@pytest.mark.asyncio
async def test_load_excuse_status_map_returns_empty_dict_for_empty_input(db_session):
    result = await student_query.load_excuse_status_map(db_session, [])
    assert result == {}


@pytest.mark.asyncio
async def test_load_classreg_category_map_returns_rows_by_id(db_session):
    kategorie = ClassregCategory(name="verspaetet", long_name="Verspätung", group_name="fehlzeiten")
    db_session.add(kategorie)
    await db_session.commit()

    result = await student_query.load_classreg_category_map(db_session, [kategorie.id])
    assert result[kategorie.id].long_name == "Verspätung"


@pytest.mark.asyncio
async def test_load_classreg_category_map_returns_empty_dict_for_empty_input(db_session):
    result = await student_query.load_classreg_category_map(db_session, [])
    assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_student_query.py -k excuse_status_map -v` and the equivalent `-k classreg_category_map`
Expected: FAIL with `AttributeError: module 'app.services.student_query' has no attribute 'load_excuse_status_map'` (and analogous for `load_classreg_category_map`)

- [ ] **Step 3: Implement the two loaders**

In `backend/app/services/student_query.py`, add imports near the top (alongside the existing model imports):

```python
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
```

Add the two functions directly after `load_regel_typ_map` (which ends around line 91):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_student_query.py -v`
Expected: PASS (all tests in the file, including the 4 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/student_query.py backend/tests/test_student_query.py
git commit -m "feat: add excuse-status and classreg-category name-resolution maps"
```

---

### Task 2: Export filename normalization

**Files:**
- Create: `backend/app/services/export_service.py`
- Test: `backend/tests/test_export_service.py`

**Interfaces:**
- Produces: `build_export_filename(nachname: str, vorname: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_export_service.py`:

```python
from app.services import export_service


def test_build_export_filename_transliterates_umlauts():
    assert export_service.build_export_filename("Müller", "Jörg") == "Mueller_Joerg_export.pdf"


def test_build_export_filename_transliterates_eszett():
    assert export_service.build_export_filename("Straß", "Anna") == "Strass_Anna_export.pdf"


def test_build_export_filename_strips_other_diacritics_to_base_letter():
    assert export_service.build_export_filename("Renée", "José") == "Renee_Jose_export.pdf"


def test_build_export_filename_replaces_remaining_special_characters_with_dash():
    assert export_service.build_export_filename("O'Brien", "Anne-Marie") == "O-Brien_Anne-Marie_export.pdf"


def test_build_export_filename_replaces_spaces_with_dash():
    assert export_service.build_export_filename("von Bergmann", "Karl Heinz") == "von-Bergmann_Karl-Heinz_export.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_export_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.export_service'`

- [ ] **Step 3: Implement `build_export_filename`**

Create `backend/app/services/export_service.py`:

```python
from __future__ import annotations

import re
import unicodedata

_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
)


def build_export_filename(nachname: str, vorname: str) -> str:
    """Baut einen sicheren Dateinamen fuer den Content-Disposition-Header: deutsche
    Umlaute/Eszett explizit transliteriert, alle anderen diakritischen Zeichen per
    NFKD-Normalisierung auf den Basis-Buchstaben reduziert, verbleibende
    Nicht-ASCII-/Sonderzeichen (inkl. Leerzeichen) durch '-' ersetzt."""
    raw = f"{nachname}_{vorname}_export".translate(_UMLAUT_MAP)
    ascii_normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9_]+", "-", ascii_normalized).strip("-")
    return f"{normalized}.pdf"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_export_service.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/export_service.py backend/tests/test_export_service.py
git commit -m "feat: add PDF export filename normalization"
```

---

### Task 3: WeasyPrint dependency, Jinja2 template, HTML/PDF rendering

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/Dockerfile`
- Create: `backend/app/templates/export_pdf.html`
- Modify: `backend/app/services/export_service.py`
- Test: `backend/tests/test_export_service.py`

**Interfaces:**
- Consumes: `student_query.load_student_detail(db, schueler_id) -> dict[str, Any]` (Task existing), `student_query.load_excuse_status_map`/`load_classreg_category_map`/`load_regel_typ_map` (Task 1 + existing)
- Produces: `async def render_student_export_html(db: AsyncSession, schueler: Schueler, klasse: Klasse | None, sections: set[str]) -> str`
- Produces: `def html_to_pdf(html: str) -> bytes`

- [ ] **Step 1: Add dependencies**

In `backend/requirements.txt`, add two lines:

```
weasyprint>=62,<63
jinja2>=3.1,<4.0
```

In `backend/Dockerfile`, install WeasyPrint's system libraries before `pip install` (Debian slim base):

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_export_service.py`:

```python
import datetime

import pytest

from app.models.ausnahme import Ausnahme
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.services import export_service


async def _seed_full_student(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    status = ExcuseStatus(name="U", long_name="Unentschuldigt", zaehlt_als_entschuldigt=False)
    kategorie = ClassregCategory(name="verspaetet", long_name="Verspätung")
    typ = MassnahmenTyp(name="Elterngespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="lehrer1", email="l@b.de", name="Lehrer Eins", rolle="klassenlehrkraft")
    db_session.add_all([schueler, status, kategorie, typ, nutzer])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=datetime.date(2026, 2, 1),
            start_zeit=1,
            end_zeit=6,
            excuse_status_id=status.id,
        )
    )
    db_session.add(
        KlassenbuchEintrag(
            webuntis_id=1,
            schueler_id=schueler.id,
            kategorie_id=kategorie.id,
            datum=datetime.date(2026, 2, 2),
            text="Zu spät gekommen",
        )
    )
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 3),
            notiz="Gespräch geführt",
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    db_session.add(Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="Attest", aktiv=True))
    await db_session.commit()
    return schueler, klasse


@pytest.mark.asyncio
async def test_render_student_export_html_includes_all_sections_by_default(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse,
        sections={"fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"},
    )

    assert "Muster" in html
    assert "10a" in html
    assert "Unentschuldigt" in html
    assert "Verspätung" in html
    assert "Elterngespräch" in html
    assert "Attest" in html


@pytest.mark.asyncio
async def test_render_student_export_html_omits_sections_not_requested(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}
    )

    assert "Unentschuldigt" in html
    assert "Verspätung" not in html  # Klassenbuch-Abschnitt
    assert "Elterngespräch" not in html  # Massnahmen-Abschnitt
    assert "Attest" not in html  # Ausnahmen-Abschnitt


@pytest.mark.asyncio
async def test_render_student_export_html_repeats_table_headers_via_thead(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}
    )

    assert "<thead>" in html


@pytest.mark.asyncio
async def test_render_student_export_html_footer_contains_name_and_page_counter(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}
    )

    assert "Muster, Max" in html
    assert "counter(page)" in html
    assert "counter(pages)" in html


def test_html_to_pdf_returns_pdf_bytes():
    pdf_bytes = export_service.html_to_pdf("<html><body><h1>Test</h1></body></html>")
    assert pdf_bytes.startswith(b"%PDF")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_export_service.py -v`
Expected: FAIL with `AttributeError: module 'app.services.export_service' has no attribute 'render_student_export_html'` (and `html_to_pdf`)

- [ ] **Step 4: Create the Jinja2 template**

Create `backend/app/templates/export_pdf.html`:

```html
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<style>
  @page {
    size: A4;
    margin: 2cm 1.5cm 2.2cm 1.5cm;
    @bottom-left { content: "{{ schueler.nachname }}, {{ schueler.vorname }}"; font-size: 9px; }
    @bottom-center { content: "Gedruckt am {{ erstellt_am }}"; font-size: 9px; }
    @bottom-right { content: "Seite " counter(page) " von " counter(pages); font-size: 9px; }
  }
  body { font-family: sans-serif; font-size: 11px; color: #111; }
  h1 { font-size: 16px; margin-bottom: 0; }
  h2 { font-size: 13px; margin-top: 1.5em; margin-bottom: 0.3em; }
  .meta { color: #444; margin-bottom: 1em; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 1em; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #eee; }
</style>
</head>
<body>
  <h1>Fehlzeiten- und Maßnahmenübersicht</h1>
  <div class="meta">
    {{ schueler.nachname }}, {{ schueler.vorname }}{% if klasse %} &middot; Klasse {{ klasse.name }}{% endif %}
  </div>

  {% if "fehlzeiten" in sections %}
  <h2>Fehlzeiten</h2>
  <table>
    <thead>
      <tr><th>Datum</th><th>Typ</th><th>Fach</th><th>Entschuldigungsstatus</th><th>Grund</th></tr>
    </thead>
    <tbody>
      {% for f in fehlzeiten %}
      <tr>
        <td>{{ f.datum }}</td>
        <td>{{ f.typ }}</td>
        <td>{{ f.fach or "" }}</td>
        <td>{{ f.excuse_status_name or "" }}</td>
        <td>{{ f.grund_text or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if "klassenbuch" in sections %}
  <h2>Klassenbucheinträge</h2>
  <table>
    <thead>
      <tr><th>Datum</th><th>Kategorie</th><th>Text</th></tr>
    </thead>
    <tbody>
      {% for k in klassenbuch %}
      <tr>
        <td>{{ k.datum }}</td>
        <td>{{ k.kategorie_name or "" }}</td>
        <td>{{ k.text or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if "massnahmen" in sections %}
  <h2>Maßnahmen</h2>
  <table>
    <thead>
      <tr><th>Datum</th><th>Typ</th><th>Notiz</th><th>Erfasst von</th></tr>
    </thead>
    <tbody>
      {% for m in massnahmen %}
      <tr>
        <td>{{ m.datum }}</td>
        <td>{{ m.massnahmen_typ_name }}</td>
        <td>{{ m.notiz or "" }}</td>
        <td>{{ m.erfasst_von_name }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if "ausnahmen" in sections %}
  <h2>Aktive Ausnahmen</h2>
  <table>
    <thead>
      <tr><th>Kategorie</th><th>Grund</th><th>Gültig bis</th></tr>
    </thead>
    <tbody>
      {% for a in ausnahmen %}
      <tr>
        <td>{{ a.kategorie }}</td>
        <td>{{ a.grund }}</td>
        <td>{{ a.gueltig_bis or "unbefristet" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if "benachrichtigungen" in sections %}
  <h2>Benachrichtigungen</h2>
  <table>
    <thead>
      <tr><th>Zeitpunkt</th><th>Regel-Typ</th><th>Stufe</th><th>Empfänger</th><th>Status</th></tr>
    </thead>
    <tbody>
      {% for b in benachrichtigungen %}
      <tr>
        <td>{{ b.gesendet_am }}</td>
        <td>{{ b.typ or "" }}</td>
        <td>{{ b.stufe_nr }}</td>
        <td>{{ b.empfaenger_text }}</td>
        <td>{{ b.status }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
</body>
</html>
```

- [ ] **Step 5: Implement rendering in `export_service.py`**

Append to `backend/app/services/export_service.py` (keep `build_export_filename` and the module-level `_UMLAUT_MAP` from Task 2, add the following below the existing imports and function):

```python
import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.services import student_query

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)


async def render_student_export_html(
    db: AsyncSession, schueler: Schueler, klasse: Klasse | None, sections: set[str]
) -> str:
    """Laedt die Detaildaten des Schuelers und rendert das PDF-Export-Template zu HTML.
    Enthaelt nur die in `sections` angeforderten Abschnitte; Namen fuer
    excuse_status/classreg_category werden hier aufgeloest (in den *Out-Schemas
    fuer GET /students/{id} bisher nicht aufgeloest)."""
    detail = await student_query.load_student_detail(db, schueler.id)

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
                    "gesendet_am": b.gesendet_am.strftime("%d.%m.%Y %H:%M"),
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
        erstellt_am=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        fehlzeiten=fehlzeiten,
        klassenbuch=klassenbuch,
        massnahmen=massnahmen,
        ausnahmen=ausnahmen,
        benachrichtigungen=benachrichtigungen,
    )


def html_to_pdf(html: str) -> bytes:
    """Duenner Wrapper um WeasyPrint, isoliert damit Tests HTML-Inhalt direkt pruefen
    koennen, ohne PDF-Bytes parsen zu muessen."""
    return HTML(string=html).write_pdf()
```

- [ ] **Step 6: Install dependencies and run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml build backend && docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_export_service.py -v`
Expected: PASS (all tests, including the 5 from Task 2 and the 5 new ones)

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/Dockerfile backend/app/templates/export_pdf.html backend/app/services/export_service.py backend/tests/test_export_service.py
git commit -m "feat: render student PDF export via WeasyPrint with repeating table headers"
```

---

### Task 4: `GET /students/{schueler_id}/export.pdf` route with audit logging

**Files:**
- Modify: `backend/app/api/routes/students.py`
- Test: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `export_service.render_student_export_html`, `export_service.html_to_pdf`, `export_service.build_export_filename` (Task 2/3), `student_query.load_klasse_map` (existing), `get_scoped_schueler`/`get_wordpress_proxy_nutzer` (existing, `app/api/deps.py`)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_students.py`:

```python
@pytest.mark.asyncio
async def test_export_pdf_returns_pdf_with_all_sections_by_default(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}/export.pdf", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "Muster_Max_export.pdf" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_pdf_writes_audit_log_with_requested_sections(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"sections": "fehlzeiten,massnahmen"},
        )

    assert response.status_code == 200
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "export_pdf"))
    entries = audit_result.scalars().all()
    assert len(entries) == 1
    assert entries[0].details == {"sections": ["fehlzeiten", "massnahmen"]}
    assert entries[0].resource_id == str(schueler.id)


@pytest.mark.asyncio
async def test_export_pdf_rejects_unknown_section(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"sections": "unbekannt"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_pdf_404s_for_out_of_scope_student(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}/export.pdf", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -k export_pdf -v`
Expected: FAIL with `404 Not Found` (route doesn't exist yet) on the first two tests, since FastAPI has no matching route

- [ ] **Step 3: Implement the route**

In `backend/app/api/routes/students.py`, add imports:

```python
from fastapi import Response
from app.models.audit_log import AuditLog
from app.services import export_service
```

Add the route at the end of the file:

```python
_EXPORT_SECTIONS = {"fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"}


@router.get("/{schueler_id}/export.pdf")
async def export_student_pdf(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sections: str | None = None,
) -> Response:
    if sections:
        requested = {s.strip().lower() for s in sections.split(",") if s.strip()}
        unknown = requested - _EXPORT_SECTIONS
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown sections: {sorted(unknown)}",
            )
    else:
        requested = set(_EXPORT_SECTIONS)

    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    html = await export_service.render_student_export_html(db, schueler, klasse, requested)
    pdf_bytes = export_service.html_to_pdf(html)

    db.add(
        AuditLog(
            user_id=nutzer.id,
            aktion="export_pdf",
            resource_typ="schueler",
            resource_id=str(schueler.id),
            details={"sections": sorted(requested)},
        )
    )
    await db.commit()

    filename = export_service.build_export_filename(schueler.nachname, schueler.vorname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: PASS (full file, including the 4 new tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -v`
Expected: PASS (no regressions in unrelated tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/students.py backend/tests/test_api_students.py
git commit -m "feat: add GET /students/{id}/export.pdf endpoint with audit logging"
```

---

### Task 5: Documentation updates

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/backend-setup.md`

- [ ] **Step 1: Update ROADMAP.md**

In `ROADMAP.md`, move the PDF-Export line from the "Geplant" list into the "Abgeschlossen" table as a new row (append after the Plan 6 row):

```markdown
| **Plan 7** — [Backend REST-API fürs WP-Plugin — PDF-Export](docs/superpowers/plans/2026-07-27-pdf-export.md) | `GET /students/{id}/export.pdf` mit konfigurierbaren Abschnitten (`sections`-Query-Parameter: `fehlzeiten`/`klassenbuch`/`massnahmen`/`ausnahmen`/`benachrichtigungen`, Default = alle), Klartext-Auflösung von Entschuldigungsstatus/Klassenbuch-Kategorie, Audit-Log-Eintrag pro Export, WeasyPrint-Rendering mit seitenübergreifend wiederholtem Tabellenkopf und Fußzeile (Schülername/Druckdatum/Seitenzahl) (TECH-SPEC.md §3, SPECS.md §7) | Zeitraum-Filter, zusätzliche Schüler-Stammdaten (Geburtsdatum/Adresse) |
```

Remove point 1 ("Backend: REST-API fürs WP-Plugin — PDF-Export...") from the "Geplant" list, renumbering the remaining points (2→1, 3→2, 4→3).

- [ ] **Step 2: Update docs/backend-setup.md**

Add a new section after "## Admin-Endpunkte (ab Plan 6)":

```markdown
## PDF-Export (ab Plan 7)

- **`GET /students/{id}/export.pdf`**: liefert ein PDF mit Fehlzeiten-/Klassenbuch-/Maßnahmen-/Ausnahmen-/Benachrichtigungs-Historie eines Schülers. Optionaler `sections`-Query-Parameter (kommasepariert, z.B. `?sections=fehlzeiten,massnahmen`) wählt die enthaltenen Abschnitte aus; ohne Parameter sind alle fünf enthalten. Rollenoffen, aber scope-geprüft wie `GET /students/{id}`.
- **Abhängigkeit:** WeasyPrint benötigt System-Bibliotheken (Pango/Cairo/GDK-Pixbuf), die im mitgelieferten `Dockerfile` bereits installiert werden — bei einem Rebuild des Images (`docker compose -f backend/docker-compose.yml build backend`) ist nichts weiter zu tun.
- **Audit-Log:** jeder Export erzeugt einen `audit_log`-Eintrag (`aktion="export_pdf"`) mit den angeforderten `sections`, da der Export für offizielle Meldungen (§90/Bußgeldverfahren) gedacht ist.
```

Update the "Aktueller Stand" paragraph at the bottom:

```markdown
## Aktueller Stand

Plan 1-7 sind abgeschlossen: Backend-Grundgerüst & Datenmodell (Plan 1), WebUntis-Sync inkl. ASV-BW-CSV-Import (Plan 2), Eskalations-Engine mit Schwellwerten/Benachrichtigungen/Maßnahmen (Plan 3), echter E-Mail-Versand (Plan 4), REST-Kern-Endpunkte fürs WP-Plugin (`/students`, Plan 5), die Admin-Konfigurationsendpunkte (`/admin/...`, Plan 6) und der PDF-Export (`/students/{id}/export.pdf`, Plan 7). Noch offen: das Frontend und das WordPress-Plugin selbst (siehe ROADMAP.md, Abschnitt "Geplant").
```

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md docs/backend-setup.md
git commit -m "docs: mark PDF-Export (Plan 7) as completed in ROADMAP and backend-setup"
```

---

## Self-Review Notes

- **Spec coverage:** SPECS.md §7 (PDF-Export, konfigurierbare Abschnitte) → Task 3+4. TECH-SPEC.md §3 (`GET /students/{id}/export.pdf`) → Task 4. Design doc's page-break/footer requirement → Task 3 (`<thead>` + `@page` margin boxes), verified by dedicated tests. Filename normalization requirement → Task 2. Audit logging → Task 4. Name resolution for excuse status/Klassenbuch category → Task 1+3.
- **No new migration needed:** confirmed no model/schema changes — only new service functions, a template, and a route.
- **Type/signature consistency:** `render_student_export_html(db, schueler, klasse, sections)` is used identically in Task 3's own test and in Task 4's route. `build_export_filename(nachname, vorname)` matches its Task 2 definition and Task 4's usage. `html_to_pdf(html) -> bytes` matches across Task 3 and Task 4.
