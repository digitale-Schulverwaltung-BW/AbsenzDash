# Bundle B — Schüler-Detail Anbindungen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the WebUntis subject short name instead of the long name on "Fach", and add a working PDF-export button (with section checkboxes and Schuljahr-scoping) to the Schüler-Detail page.

**Architecture:** Backend: `webuntis_fehlzeit_sync.py` resolves `fach` to a short name at sync time using a `getSubjects()`-derived lookup (no new DB table — pure string resolution); a one-off script backfills existing rows. `export_student_pdf` gains an optional `schuljahr_id` param, reusing the existing `_resolve_schuljahr_zeitraum` helper and `load_student_detail(von, bis)` machinery from the Schuljahr-Historie feature. Frontend: a new `apiDownload` helper in `client.ts` fetches the PDF as a `Blob` and triggers a browser download; a new `PdfExportSection` component adds section checkboxes and wires in the current `schuljahr` URL param.

**Tech Stack:** FastAPI/SQLAlchemy (async) backend, pytest + pytest-asyncio; React/TypeScript frontend, Vitest + Testing Library.

## Global Constraints

- Commit messages in English (user's global CLAUDE.md).
- Every task ends with passing tests before moving to the next task.
- No new DB schema/migration for the Fach-Kurzname feature — `fehlzeit.fach` stays a plain string column (see design doc "Nicht-Ziele").
- Collision handling: when multiple WebUntis subjects share the same `longName`, the **first** one in `getSubjects()` response order wins — no further disambiguation.

Full design context: [`docs/superpowers/specs/2026-08-04-bundle-b-schueler-detail-anbindungen-design.md`](../specs/2026-08-04-bundle-b-schueler-detail-anbindungen-design.md).

---

## Task 1: Fach-Kurzname — resolve short name during Fehlzeiten-Sync

**Files:**
- Modify: `backend/app/services/webuntis_fehlzeit_sync.py`
- Modify: `backend/tests/test_webuntis_fehlzeit_sync.py`
- Modify: `TECH-SPEC.md` (Abschnitt 1.2, neuer Nachtrag 5)

**Interfaces:**
- Produces: `_build_kurzname_by_longname(subjects: list[dict]) -> dict[str, str]` and `_resolve_fach_kurzname(langname: str | None, kurzname_by_longname: dict[str, str]) -> str | None` in `webuntis_fehlzeit_sync.py` — both reused by Task 3's backfill script via `from app.services.webuntis_fehlzeit_sync import _build_kurzname_by_longname, _resolve_fach_kurzname` (same pattern the test file already uses for `_merge_tag_gruppe`).

The existing test file mocks `client.call` uniformly via `client.call.return_value = {...}`, which returns the *same* payload for every call. Once `sync_fehlzeiten` makes a second distinct call (`getSubjects`), every one of the 16 existing tests would receive the `getTimetableWithAbsences` payload for the `getSubjects` call too and crash. Step 1 fixes this **before** touching production code, so the test suite stays green throughout.

- [ ] **Step 1: Replace the uniform `client.call.return_value` mock with a method-dispatching helper**

Add this helper near the top of `backend/tests/test_webuntis_fehlzeit_sync.py`, right after the imports:

```python
def _make_client(periods, subjects=None):
    """AsyncMock for WebUntisClient that dispatches by method name, so a test can supply a
    getTimetableWithAbsences payload without also having to fake getSubjects (defaults to no
    subjects, i.e. every fach falls back to the raw WebUntis longName)."""
    client = AsyncMock()

    async def _call(method, params):
        if method == "getTimetableWithAbsences":
            return periods
        if method == "getSubjects":
            return subjects if subjects is not None else []
        raise AssertionError(f"unexpected WebUntis call in test: {method}")

    client.call.side_effect = _call
    return client
```

Then, in every existing test in the file, replace the two-line pattern

```python
    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
```

with

```python
    client = _make_client({
        "periodsWithAbsences": [
```

and adjust the matching closing `}` to `})` at the end of that literal (there are 16 occurrences — every `async def test_sync_fehlzeiten_*` test in the file). Leave the two non-async pure-function tests (`test_merge_tag_gruppe_*`) untouched, they don't build a client.

One assertion needs updating because `client.call` is now awaited twice (once for `getSubjects`, once for `getTimetableWithAbsences`) instead of once — `test_sync_fehlzeiten_creates_tag_and_stunde_entries` currently ends with:

```python
    client.call.assert_awaited_once_with(
        "getTimetableWithAbsences", {"options": {"startDate": 20260601, "endDate": 20260630}}
    )
```

Change `assert_awaited_once_with` to `assert_any_await`:

```python
    client.call.assert_any_await(
        "getTimetableWithAbsences", {"options": {"startDate": 20260601, "endDate": 20260630}}
    )
```

- [ ] **Step 2: Run the full test file to confirm it's still green after the mock refactor**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: all existing tests PASS (pure mechanical refactor, no behavior change yet — `sync_fehlzeiten` doesn't call `getSubjects` yet, so the dispatcher's `getSubjects` branch is simply unused so far).

- [ ] **Step 3: Write the failing tests for the two new pure resolver functions**

Add to `backend/tests/test_webuntis_fehlzeit_sync.py`:

```python
from app.services.webuntis_fehlzeit_sync import (
    _build_kurzname_by_longname,
    _merge_tag_gruppe,
    _resolve_fach_kurzname,
    sync_fehlzeiten,
)


def test_build_kurzname_by_longname_maps_longname_to_name():
    subjects = [{"id": 61, "name": "D", "longName": "Deutsch"}, {"id": 62, "name": "M", "longName": "Mathematik"}]
    assert _build_kurzname_by_longname(subjects) == {"Deutsch": "D", "Mathematik": "M"}


def test_build_kurzname_by_longname_first_match_wins_on_collision():
    """Live-bestaetigte Kollision: BK und BKOM tragen an dieser Schule denselben Langnamen
    'Betriebliche Kommunikation' (TECH-SPEC.md Abschnitt 1.2, Nachtrag 5)."""
    subjects = [
        {"id": 16, "name": "BK", "longName": "Betriebliche Kommunikation"},
        {"id": 458, "name": "BKOM", "longName": "Betriebliche Kommunikation"},
    ]
    assert _build_kurzname_by_longname(subjects) == {"Betriebliche Kommunikation": "BK"}


def test_build_kurzname_by_longname_skips_entries_without_longname_or_name():
    subjects = [{"id": 1, "name": "", "longName": "Ohne Kuerzel"}, {"id": 2, "name": "X", "longName": ""}]
    assert _build_kurzname_by_longname(subjects) == {}


def test_resolve_fach_kurzname_returns_kurzname_when_found():
    assert _resolve_fach_kurzname("Deutsch", {"Deutsch": "D"}) == "D"


def test_resolve_fach_kurzname_falls_back_to_langname_when_not_found():
    """z.B. inzwischen umbenanntes/deaktiviertes Fach, das nicht mehr in getSubjects() auftaucht
    (live beobachtet: 'Bildende Kunst')."""
    assert _resolve_fach_kurzname("Bildende Kunst", {"Deutsch": "D"}) == "Bildende Kunst"


def test_resolve_fach_kurzname_returns_none_for_none_input():
    assert _resolve_fach_kurzname(None, {"Deutsch": "D"}) is None


def test_resolve_fach_kurzname_returns_none_for_empty_string_input():
    assert _resolve_fach_kurzname("", {"Deutsch": "D"}) is None
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -k "kurzname" -v`
Expected: FAIL with `ImportError: cannot import name '_build_kurzname_by_longname'`.

- [ ] **Step 5: Implement the two resolver functions**

In `backend/app/services/webuntis_fehlzeit_sync.py`, add these two functions right after `_hhmm_zu_minuten` (before `TAG_MINDESTDAUER_MINUTEN`):

```python
def _build_kurzname_by_longname(subjects: list[dict]) -> dict[str, str]:
    """Baut longName -> Kuerzel aus getSubjects(). Bei Kollision (mehrere Faecher mit
    identischem Langnamen, live bestaetigt fuer 'Betriebliche Kommunikation' -> BK/BKOM,
    siehe TECH-SPEC.md Abschnitt 1.2 Nachtrag 5) gewinnt das erste Vorkommen in
    Antwortreihenfolge -- bewusst keine weitere Disambiguierung, siehe Design-Dok."""
    mapping: dict[str, str] = {}
    for subject in subjects:
        long_name = subject.get("longName")
        kurzname = subject.get("name")
        if long_name and kurzname and long_name not in mapping:
            mapping[long_name] = kurzname
    return mapping


def _resolve_fach_kurzname(langname: str | None, kurzname_by_longname: dict[str, str]) -> str | None:
    """WebUntis' Fehlzeiten-'subjectId'-Feld ist trotz des Namens bereits der Fach-Langname
    (kein numerischer Identifier, siehe TECH-SPEC.md Abschnitt 1.2 Nachtrag 5). Aufloesung
    auf das Kuerzel nur best-effort: unbekannte/veraltete Langnamen (z.B. umbenannte Faecher)
    fallen unveraendert auf den Langnamen zurueck statt auf ein leeres Feld."""
    if not langname:
        return None
    return kurzname_by_longname.get(langname, langname)
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -k "kurzname" -v`
Expected: all 6 PASS.

- [ ] **Step 7: Write a failing integration test that the sync actually uses the resolver**

Add to `backend/tests/test_webuntis_fehlzeit_sync.py`:

```python
@pytest.mark.asyncio
async def test_sync_fehlzeiten_resolves_fach_to_kurzname(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client(
        {
            "periodsWithAbsences": [
                {
                    "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                    "subjectId": "Deutsch", "absentTime": 45, "invalid": False,
                },
            ]
        },
        subjects=[{"id": 61, "name": "D", "longName": "Deutsch"}],
    )

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().one().fach == "D"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_keeps_langname_when_no_matching_subject(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = _make_client(
        {
            "periodsWithAbsences": [
                {
                    "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                    "subjectId": "Bildende Kunst", "absentTime": 45, "invalid": False,
                },
            ]
        },
        subjects=[{"id": 61, "name": "D", "longName": "Deutsch"}],
    )

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert result.scalars().one().fach == "Bildende Kunst"
```

- [ ] **Step 8: Run the new tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -k "resolves_fach_to_kurzname or keeps_langname_when_no_matching" -v`
Expected: FAIL — `fach` is still the raw `subjectId` value (`"Deutsch"` in the first test, which happens to look like it'd pass; check with the collision-free case above where a real getSubjects call is missing entirely — since `sync_fehlzeiten` doesn't call `getSubjects` yet, `client.call.side_effect` for `"getSubjects"` is simply never invoked, so both assertions actually already hold today by coincidence for the langname-fallback test but not for the kurzname test — confirm the kurzname test fails with `fach == "Deutsch"` instead of `"D"`).

- [ ] **Step 9: Wire the resolver into `sync_fehlzeiten`**

In `backend/app/services/webuntis_fehlzeit_sync.py`, inside `sync_fehlzeiten`, right after the existing line

```python
    entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result
```

add:

```python
    subjects_result = await client.call("getSubjects", {})
    kurzname_by_longname = _build_kurzname_by_longname(subjects_result or [])
```

Then change the single line

```python
                    fehlzeit.fach = row.get("subjectId") or None
```

(around line 227, inside the `for row in gruppe:` loop that handles `subjectId`-tragende Zeilen) to:

```python
                    fehlzeit.fach = _resolve_fach_kurzname(row.get("subjectId"), kurzname_by_longname)
```

Leave the other two `fehlzeit.fach = None` assignments (Tag-Ebene-Merges, subjectId-lose Gruppen) untouched — they're not driven by a raw `subjectId` value.

- [ ] **Step 10: Run the full test file to verify everything passes**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: all tests PASS (22 tests: 16 existing + 6 new, plus the 2 pure `_merge_tag_gruppe` tests already counted in the 16).

- [ ] **Step 11: Document the live-verified finding in TECH-SPEC.md**

In `TECH-SPEC.md`, right after the existing "Nachtrag 4" paragraph in Abschnitt 1.2 (before the `excuseStatus`-Absatz that starts with `` `excuseStatus` referenziert **keinen freien String**``), insert:

```markdown
**Nachtrag 5 (2026-08-04, Live-Spike `scratchpad/webuntis_subjects_spike.py` — Fach-Kuerzel statt Langname):** `getTimetableWithAbsences` liefert trotz des Feldnamens `subjectId` **keinen numerischen Identifier** fuer das Fach, sondern den vollen Langnamen als String (bestaetigtes Beispiel: `"subjectId": "Deutsch"`). Vollstaendige Feldliste eines Fehlzeiten-Eintrags: `absenceReason`, `absentTime`, `checked`, `date`, `endTime`, `excuseStatus`, `invalid`, `startTime`, `status`, `studentGroup`, `studentId`, `subjectId`, `teacherIds`, `user`. Fuer die gewuenschte Kurzname-Anzeige (`fehlzeit.fach`, ROADMAP Bundle B) wird deshalb zusaetzlich `getSubjects()` abgefragt (liefert an dieser Schule 466 Faecher, je `id`/`name`/`longName`/`alternateName`) und ueber den Langnamen abgeglichen. Dieser Abgleich ist **nicht garantiert eindeutig**: bestaetigte Kollision `BK` (id 16) und `BKOM` (id 458) tragen beide exakt den Langnamen `"Betriebliche Kommunikation"`; zusaetzlich koennen Langnamen veralten (`"Bildende Kunst"`, live in echten Fehlzeiten-Daten beobachtet, taucht in der aktuellen `getSubjects()`-Liste nicht mehr auf, vermutlich umbenannt/deaktiviert). Bewusste Vereinfachung (Ruecksprache 2026-08-04): bei Kollision gewinnt das erste Fach in `getSubjects()`-Antwortreihenfolge, bei keinem Treffer bleibt der Langname unveraendert stehen — Eindeutigkeit ist kein hartes Ziel, echte Datenpflege-Probleme in den WebUntis-Fach-Stammdaten sind Sache des WebUntis-Admins, kein Software-Problem. Umgesetzt in `webuntis_fehlzeit_sync.py` (`_build_kurzname_by_longname`/`_resolve_fach_kurzname`).
```

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/webuntis_fehlzeit_sync.py backend/tests/test_webuntis_fehlzeit_sync.py TECH-SPEC.md
git commit -m "$(cat <<'EOF'
feat: resolve Fehlzeiten fach to WebUntis subject short name

subjectId in getTimetableWithAbsences is actually the subject long name,
not an id — fach displayed the German long name (e.g. "Deutsch") instead
of the short code teachers actually use. Sync now cross-references
getSubjects() by long name; falls back to the long name unchanged when a
subject can't be resolved (renamed/deactivated) or collides with another
short name (first match wins, live-confirmed BK/BKOM case).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Fach-Kurzname — backfill existing historical Fehlzeiten

**Files:**
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/backfill_fach_kurznamen.py`
- Create: `backend/tests/test_backfill_fach_kurznamen.py`

**Interfaces:**
- Consumes: `_build_kurzname_by_longname`, `_resolve_fach_kurzname` from Task 1 (`app.services.webuntis_fehlzeit_sync`).
- Produces: `async def backfill_fach_kurznamen(client: WebUntisClient, db: AsyncSession) -> int` (returns the number of updated rows) — the `if __name__ == "__main__"` block wires it to real `WebUntisClient(settings)` + `async_session_factory()` for manual one-off execution, matching the existing `run_sync_once` wiring in `sync_orchestrator.py`.

The regular sync only re-processes the window since the last run (`sync_orchestrator._fehlzeiten_zeitraum`), so already-stored `fehlzeit.fach` values from before this change would otherwise keep their raw long name forever. This script applies the same resolver once to all existing rows.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_backfill_fach_kurznamen.py`:

```python
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from scripts.backfill_fach_kurznamen import backfill_fach_kurznamen


@pytest.mark.asyncio
async def test_backfill_resolves_existing_fach_values_to_kurzname(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum="2026-02-01", start_zeit=730, end_zeit=815, fach="Deutsch"),
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum="2026-02-02", start_zeit=730, end_zeit=815, fach="Bildende Kunst"),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum="2026-02-03", start_zeit=0, end_zeit=2359, fach=None),
        ]
    )
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 61, "name": "D", "longName": "Deutsch"}]

    updated = await backfill_fach_kurznamen(client, db_session)

    client.call.assert_awaited_once_with("getSubjects", {})
    assert updated == 1  # nur die tatsaechlich geaenderte Zeile (Deutsch -> D) zaehlt
    rows = {f.datum.isoformat(): f.fach for f in (await db_session.execute(select(Fehlzeit))).scalars().all()}
    assert rows["2026-02-01"] == "D"
    assert rows["2026-02-02"] == "Bildende Kunst"  # unveraendert, kein Treffer in getSubjects
    assert rows["2026-02-03"] is None  # unveraendert, war schon None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_backfill_fach_kurznamen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Create the `scripts` package and the backfill script**

Create `backend/scripts/__init__.py` (empty file).

Create `backend/scripts/backfill_fach_kurznamen.py`:

```python
"""Einmaliges Backfill-Skript: loest fehlzeit.fach fuer bereits bestehende Zeilen auf das
WebUntis-Fach-Kuerzel auf (dieselbe Logik, die der reguläre Sync seit dem Fach-Kurzname-Fix
fuer neu synchronisierte Zeilen bereits anwendet, siehe webuntis_fehlzeit_sync.py). Noetig,
weil der reguläre Sync inkrementell laeuft (nur seit dem letzten Lauf) und bereits gespeicherte
historische Zeilen sonst dauerhaft ihren rohen WebUntis-Langnamen behalten wuerden.

Nutzung (einmalig nach Deploy, z.B. im laufenden Backend-Container):
    python -m scripts.backfill_fach_kurznamen
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisClient
from app.models.fehlzeit import Fehlzeit
from app.services.webuntis_fehlzeit_sync import _build_kurzname_by_longname, _resolve_fach_kurzname

logger = logging.getLogger(__name__)


async def backfill_fach_kurznamen(client: WebUntisClient, db: AsyncSession) -> int:
    """Gibt die Anzahl tatsaechlich geaenderter Zeilen zurueck (fuer Logging/Tests)."""
    subjects = await client.call("getSubjects", {})
    kurzname_by_longname = _build_kurzname_by_longname(subjects or [])

    rows = (await db.execute(select(Fehlzeit).where(Fehlzeit.fach.is_not(None)))).scalars().all()
    updated = 0
    for row in rows:
        neuer_wert = _resolve_fach_kurzname(row.fach, kurzname_by_longname)
        if neuer_wert != row.fach:
            row.fach = neuer_wert
            updated += 1

    await db.commit()
    return updated


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with WebUntisClient(settings) as client:
        async with async_session_factory() as db:
            updated = await backfill_fach_kurznamen(client, db)
            logger.info("Fach-Kurzname-Backfill abgeschlossen: %s Zeile(n) aktualisiert", updated)


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_backfill_fach_kurznamen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/__init__.py backend/scripts/backfill_fach_kurznamen.py backend/tests/test_backfill_fach_kurznamen.py
git commit -m "$(cat <<'EOF'
feat: add one-off backfill script for historical Fehlzeiten fach values

The regular sync only reprocesses the window since its last run, so
already-stored fach values (raw WebUntis long names) wouldn't otherwise
get resolved to short names by the sync fix alone. Run once after deploy:
python -m scripts.backfill_fach_kurznamen

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: PDF-Export — Schuljahr-Filter im Backend

**Files:**
- Modify: `backend/app/services/export_service.py`
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/app/templates/export_pdf.html`
- Modify: `backend/tests/test_export_service.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- Produces: `render_student_export_html(db, schueler, klasse, sections, von=None, bis=None, schuljahr_name=None)` — Task 4/5 (frontend) call the route, not this function directly, but the signature is documented here so a reviewer can check the route wiring.

- [ ] **Step 1: Write the failing service-level tests**

Add to `backend/tests/test_export_service.py`:

```python
@pytest.mark.asyncio
async def test_render_student_export_html_filters_fehlzeiten_by_von_bis(db_session):
    schueler, klasse = await _seed_full_student(db_session)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2024, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"},
        von=datetime.date(2026, 1, 1), bis=datetime.date(2026, 12, 31),
    )

    assert "01.02.2026" in html  # aus _seed_full_student, liegt im Zeitraum
    assert "01.10.2024" not in html  # ausserhalb des Zeitraums


@pytest.mark.asyncio
async def test_render_student_export_html_does_not_filter_massnahmen_by_von_bis(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"massnahmen"},
        von=datetime.date(2030, 1, 1), bis=datetime.date(2030, 12, 31),
    )

    assert "Elterngespräch" in html  # Massnahme liegt ausserhalb des Zeitraums, bleibt trotzdem sichtbar


@pytest.mark.asyncio
async def test_render_student_export_html_shows_schuljahr_name_in_meta_when_given(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"}, schuljahr_name="2024/2025",
    )

    assert "2024/2025" in html


@pytest.mark.asyncio
async def test_render_student_export_html_shows_gesamte_historie_when_no_schuljahr_given(db_session):
    schueler, klasse = await _seed_full_student(db_session)

    html = await export_service.render_student_export_html(
        db_session, schueler, klasse, sections={"fehlzeiten"},
    )

    assert "gesamte Historie" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_export_service.py -k "von_bis or schuljahr" -v`
Expected: FAIL — `render_student_export_html()` doesn't accept `von`/`bis`/`schuljahr_name` yet (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Add `von`/`bis`/`schuljahr_name` to `render_student_export_html`**

In `backend/app/services/export_service.py`, change the signature:

```python
async def render_student_export_html(
    db: AsyncSession,
    schueler: Schueler,
    klasse: Klasse | None,
    sections: set[str],
    von: datetime.date | None = None,
    bis: datetime.date | None = None,
    schuljahr_name: str | None = None,
) -> str:
```

and change the body's data-loading line from

```python
    detail = await student_query.load_student_detail(db, schueler.id)
```

to

```python
    detail = await student_query.load_student_detail(db, schueler.id, von=von, bis=bis)
```

Then in the `template.render(...)` call at the bottom of the function, add `schuljahr_name=schuljahr_name` to the keyword arguments (alongside the existing `schueler=schueler, klasse=klasse, sections=sections, ...`).

- [ ] **Step 4: Add the Zeitraum meta line to the template**

In `backend/app/templates/export_pdf.html`, change:

```html
  <div class="meta">
    {{ schueler.nachname }}, {{ schueler.vorname }}{% if klasse %} &middot; Klasse {{ klasse.name }}{% endif %}
  </div>
```

to:

```html
  <div class="meta">
    {{ schueler.nachname }}, {{ schueler.vorname }}{% if klasse %} &middot; Klasse {{ klasse.name }}{% endif %}
    &middot; {% if schuljahr_name %}Schuljahr {{ schuljahr_name }}{% else %}gesamte Historie{% endif %}
  </div>
```

- [ ] **Step 5: Run the service-level tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_export_service.py -v`
Expected: all PASS (existing tests unaffected — `von`/`bis`/`schuljahr_name` all default to the prior unfiltered/no-label behavior).

- [ ] **Step 6: Write the failing API-level test**

Add to `backend/tests/test_api_students.py`, right after `test_export_pdf_returns_pdf_with_all_sections_by_default`:

```python
@pytest.mark.asyncio
async def test_export_pdf_filters_by_schuljahr_id(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler, schuljahr])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 2, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"schuljahr_id": schuljahr.id},
        )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
```

(A byte-level PDF content assertion for the date filtering itself is already covered at the service level in Task 3 Step 1 — this test only proves the route accepts and forwards `schuljahr_id` end-to-end without erroring.)

`Fehlzeit`, `Schuljahr`, and `date` are already imported at the top of `backend/tests/test_api_students.py` — no new imports needed.

- [ ] **Step 7: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_students.py -k "filters_by_schuljahr_id" -v`
Expected: FAIL — either a 422 (unexpected query param currently ignored, so this actually could return 200 with wrong content) or, more likely, PASS-looking-but-wrong; **treat this step as a checkpoint** — if it already returns 200 before Step 8's change, that just confirms the param is currently silently ignored (FastAPI ignores unknown query params by default), not that filtering happened. Proceed to Step 8 regardless; Step 9 re-verifies correctness at the point that matters (Task 3 Step 1's service-level test, already passing).

- [ ] **Step 8: Wire `schuljahr_id` into the `export_student_pdf` route**

In `backend/app/api/routes/students.py`, change the `export_student_pdf` signature from:

```python
async def export_student_pdf(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sections: str | None = None,
) -> Response:
```

to:

```python
async def export_student_pdf(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sections: str | None = None,
    schuljahr_id: int | None = None,
) -> Response:
```

Then, right before the existing line

```python
    klasse = None
    if schueler.klasse_id is not None:
```

insert:

```python
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    schuljahr_name = None
    if von is not None:
        schuljahr = await db.get(Schuljahr, schuljahr_id)
        schuljahr_name = schuljahr.name if schuljahr is not None else None
```

Finally, change the call

```python
    html = await export_service.render_student_export_html(db, schueler, klasse, requested)
```

to:

```python
    html = await export_service.render_student_export_html(
        db, schueler, klasse, requested, von=von, bis=bis, schuljahr_name=schuljahr_name
    )
```

- [ ] **Step 9: Run both test files to verify everything passes**

Run: `cd backend && python -m pytest tests/test_export_service.py tests/test_api_students.py -v`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/export_service.py backend/app/api/routes/students.py backend/app/templates/export_pdf.html backend/tests/test_export_service.py backend/tests/test_api_students.py
git commit -m "$(cat <<'EOF'
feat: add Schuljahr filter to student PDF export

The export previously ignored the school-year filter entirely, always
pulling the full history across all years. Reuses the existing
_resolve_schuljahr_zeitraum/load_student_detail(von, bis) machinery from
the Schuljahr-Historie feature. Massnahmen stay unfiltered, matching the
same decision already made for the detail view. PDF now states the
covered period ("Schuljahr 2024/2025" or "gesamte Historie").

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: PDF-Export — `apiDownload` in `client.ts`

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `apiDownload(path: string): Promise<{ blob: Blob; filename: string }>` — consumed by Task 6's `PdfExportSection`.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/api/client.test.ts`:

```typescript
describe("apiDownload", () => {
  it("sends the nonce header and returns the blob with a filename parsed from Content-Disposition", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob(["%PDF-1.4"], { type: "application/pdf" }), {
        status: 200,
        headers: { "Content-Disposition": 'attachment; filename="Muster_Max_export.pdf"' },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiDownload("students/1/export.pdf?sections=fehlzeiten");

    expect(result.filename).toBe("Muster_Max_export.pdf");
    expect(result.blob.type).toBe("application/pdf");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/students/1/export.pdf?sections=fehlzeiten",
      { headers: { "X-WP-Nonce": "abc123" } },
    );
  });

  it("falls back to a generic filename when Content-Disposition is missing", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(new Blob(["%PDF-1.4"]), { status: 200 })),
    );

    const result = await apiDownload("students/1/export.pdf");

    expect(result.filename).toBe("export.pdf");
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
      basename: "/absenzdash",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));

    await expect(apiDownload("students/1/export.pdf")).rejects.toBeInstanceOf(ApiError);
  });
});
```

Update the import at the top of the file to include `apiDownload`:

```typescript
import { ApiError, apiDelete, apiDownload, apiGet, apiPost, apiPut } from "./client";
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `apiDownload` is not exported yet.

- [ ] **Step 3: Implement `apiDownload`**

In `frontend/src/api/client.ts`, add after the existing `apiDelete` function:

```typescript
function filenameFromContentDisposition(header: string | null): string {
  if (!header) {
    return "export.pdf";
  }
  const match = /filename="?([^";]+)"?/.exec(header);
  return match ? match[1] : "export.pdf";
}

export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    headers: { "X-WP-Nonce": config.nonce },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with status ${response.status}`);
  }
  const blob = await response.blob();
  const filename = filenameFromContentDisposition(response.headers.get("Content-Disposition"));
  return { blob, filename };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "$(cat <<'EOF'
feat: add apiDownload helper for binary file downloads

Needed for the upcoming PDF-export button — apiGet only handles JSON
responses. Parses the filename from Content-Disposition (the backend
always sets it for export.pdf), with a generic fallback.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: PDF-Export — `PdfExportSection` component

**Files:**
- Create: `frontend/src/components/StudentDetail/pdfExportSections.ts`
- Create: `frontend/src/components/StudentDetail/pdfExportSections.test.ts`
- Create: `frontend/src/components/StudentDetail/PdfExportSection.tsx`
- Create: `frontend/src/components/StudentDetail/PdfExportSection.test.tsx`
- Modify: `frontend/src/pages/StudentDetail/StudentDetail.tsx`

**Interfaces:**
- Consumes: `apiDownload` (Task 4, `../../api/client`), `useNavOptions` (existing, `../../api/hooks/useNavOptions`).
- Produces: `PdfExportSection({ studentId, schuljahrId }: { studentId: number; schuljahrId: number | null })`, a default export from `pdfExportSections.ts`: `ALL_SECTIONS: readonly string[]`, `buildSectionsParam(selected: Set<string>): string | undefined`.

- [ ] **Step 1: Write the failing tests for the pure sections-URL helper**

Create `frontend/src/components/StudentDetail/pdfExportSections.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { ALL_SECTIONS, buildSectionsParam } from "./pdfExportSections";

describe("ALL_SECTIONS", () => {
  it("lists the five backend section values", () => {
    expect(ALL_SECTIONS).toEqual(["fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"]);
  });
});

describe("buildSectionsParam", () => {
  it("returns undefined when every section is selected (matches backend default)", () => {
    expect(buildSectionsParam(new Set(ALL_SECTIONS))).toBeUndefined();
  });

  it("returns a comma-joined list when only some sections are selected", () => {
    expect(buildSectionsParam(new Set(["fehlzeiten", "massnahmen"]))).toBe("fehlzeiten,massnahmen");
  });

  it("returns an empty string when nothing is selected", () => {
    expect(buildSectionsParam(new Set())).toBe("");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/StudentDetail/pdfExportSections.test.ts`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Implement `pdfExportSections.ts`**

Create `frontend/src/components/StudentDetail/pdfExportSections.ts`:

```typescript
export const ALL_SECTIONS = ["fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"] as const;

/**
 * Baut den sections-Query-Param aus den angehakten Checkboxen. Sind alle angehakt (Normalfall),
 * wird der Parameter weggelassen -- entspricht dem Backend-Default und ergibt eine kuerzere URL.
 */
export function buildSectionsParam(selected: Set<string>): string | undefined {
  if (selected.size === ALL_SECTIONS.length) {
    return undefined;
  }
  return Array.from(selected).join(",");
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/StudentDetail/pdfExportSections.test.ts`
Expected: all PASS.

- [ ] **Step 5: Write the failing component tests**

Create `frontend/src/components/StudentDetail/PdfExportSection.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiDownload } from "../../api/client";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { PdfExportSection } from "./PdfExportSection";

vi.mock("../../api/client");
vi.mock("../../api/hooks/useNavOptions");

const mockApiDownload = vi.mocked(apiDownload);
const mockUseNavOptions = vi.mocked(useNavOptions);

function mockNavOptions() {
  mockUseNavOptions.mockReturnValue({
    data: {
      bereiche: [],
      klassen: [],
      rolle: "klassenlehrkraft",
      schuljahre: [{ id: 27, name: "2024/2025", start_datum: "2024-09-09", end_datum: "2025-07-30" }],
      aktuelles_schuljahr_id: null,
    },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

// URL.createObjectURL/revokeObjectURL don't exist in jsdom.
beforeEach(() => {
  window.URL.createObjectURL = vi.fn().mockReturnValue("blob:mock");
  window.URL.revokeObjectURL = vi.fn();
});

describe("PdfExportSection", () => {
  it("renders five checkboxes, all checked by default", () => {
    mockNavOptions();
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    for (const label of ["Fehlzeiten", "Klassenbuch", "Maßnahmen", "Ausnahmen", "Benachrichtigungen"]) {
      expect(screen.getByLabelText(label)).toBeChecked();
    }
  });

  it("blocks export and shows an inline hint when every checkbox is unchecked", async () => {
    mockNavOptions();
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    for (const label of ["Fehlzeiten", "Klassenbuch", "Maßnahmen", "Ausnahmen", "Benachrichtigungen"]) {
      await userEvent.click(screen.getByLabelText(label));
    }
    await userEvent.click(screen.getByText("PDF exportieren"));

    expect(mockApiDownload).not.toHaveBeenCalled();
    expect(screen.getByText("Bitte mindestens einen Abschnitt auswählen.")).toBeInTheDocument();
  });

  it("downloads without a sections param and without schuljahr_id when everything is default", async () => {
    mockNavOptions();
    mockApiDownload.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "export.pdf" });
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    await userEvent.click(screen.getByText("PDF exportieren"));

    await waitFor(() => expect(mockApiDownload).toHaveBeenCalledWith("students/1/export.pdf"));
  });

  it("includes schuljahr_id and shows the resolved Schuljahr name when one is selected", async () => {
    mockNavOptions();
    mockApiDownload.mockResolvedValue({ blob: new Blob(["%PDF"]), filename: "export.pdf" });
    render(<PdfExportSection studentId={1} schuljahrId={27} />);

    expect(screen.getByText("Export für Schuljahr 2024/2025")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Benachrichtigungen"));
    await userEvent.click(screen.getByText("PDF exportieren"));

    await waitFor(() =>
      expect(mockApiDownload).toHaveBeenCalledWith(
        "students/1/export.pdf?sections=fehlzeiten,klassenbuch,massnahmen,ausnahmen&schuljahr_id=27",
      ),
    );
  });

  it("shows an error message when the download fails", async () => {
    mockNavOptions();
    mockApiDownload.mockRejectedValue(new Error("boom"));
    render(<PdfExportSection studentId={1} schuljahrId={null} />);

    await userEvent.click(screen.getByText("PDF exportieren"));

    await waitFor(() => expect(screen.getByText("Fehler beim Export — bitte erneut versuchen.")).toBeInTheDocument());
  });
});
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/StudentDetail/PdfExportSection.test.tsx`
Expected: FAIL — `PdfExportSection.tsx` doesn't exist yet.

- [ ] **Step 7: Implement `PdfExportSection.tsx`**

Create `frontend/src/components/StudentDetail/PdfExportSection.tsx`:

```typescript
import { useState } from "react";
import { apiDownload } from "../../api/client";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import styles from "./StudentDetail.module.css";
import { ALL_SECTIONS, buildSectionsParam } from "./pdfExportSections";

const SECTION_LABELS: Record<(typeof ALL_SECTIONS)[number], string> = {
  fehlzeiten: "Fehlzeiten",
  klassenbuch: "Klassenbuch",
  massnahmen: "Maßnahmen",
  ausnahmen: "Ausnahmen",
  benachrichtigungen: "Benachrichtigungen",
};

interface PdfExportSectionProps {
  studentId: number;
  schuljahrId: number | null;
}

export function PdfExportSection({ studentId, schuljahrId }: PdfExportSectionProps) {
  const { data: navOptions } = useNavOptions();
  const [selected, setSelected] = useState<Set<string>>(new Set(ALL_SECTIONS));
  const [isPending, setIsPending] = useState(false);
  const [attemptedExport, setAttemptedExport] = useState(false);
  const [error, setError] = useState(false);

  const schuljahrName = schuljahrId != null ? navOptions?.schuljahre.find((s) => s.id === schuljahrId)?.name : undefined;

  function toggleSection(section: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  }

  async function handleExport() {
    setAttemptedExport(true);
    if (selected.size === 0) {
      return;
    }
    setError(false);
    setIsPending(true);
    try {
      const params = new URLSearchParams();
      const sectionsParam = buildSectionsParam(selected);
      if (sectionsParam) {
        params.set("sections", sectionsParam);
      }
      if (schuljahrId != null) {
        params.set("schuljahr_id", String(schuljahrId));
      }
      const query = params.toString();
      const path = `students/${studentId}/export.pdf${query ? `?${query}` : ""}`;
      const { blob, filename } = await apiDownload(path);

      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError(true);
    } finally {
      setIsPending(false);
    }
  }

  return (
    <section className={styles.section}>
      <h3>PDF-Export</h3>
      {schuljahrName && <p>Export für Schuljahr {schuljahrName}</p>}
      <fieldset>
        <legend>Abschnitte</legend>
        {ALL_SECTIONS.map((section) => (
          <label key={section}>
            <input
              type="checkbox"
              aria-label={SECTION_LABELS[section]}
              checked={selected.has(section)}
              onChange={() => toggleSection(section)}
            />{" "}
            {SECTION_LABELS[section]}
          </label>
        ))}
      </fieldset>
      {attemptedExport && selected.size === 0 && (
        <p className={styles.formError}>Bitte mindestens einen Abschnitt auswählen.</p>
      )}
      <button type="button" onClick={handleExport} disabled={isPending}>
        PDF exportieren
      </button>
      {error && <p className={styles.formError}>Fehler beim Export — bitte erneut versuchen.</p>}
    </section>
  );
}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/StudentDetail/PdfExportSection.test.tsx`
Expected: all PASS.

- [ ] **Step 9: Wire `PdfExportSection` into `StudentDetail.tsx`**

In `frontend/src/pages/StudentDetail/StudentDetail.tsx`, add the import:

```typescript
import { PdfExportSection } from "../../components/StudentDetail/PdfExportSection";
```

and add the section as the last element inside the outer `<div>`, right after the existing Benachrichtigungen `<section>`:

```tsx
      <PdfExportSection studentId={studentId} schuljahrId={schuljahrId} />
```

(`schuljahrId` is already computed earlier in the component via `const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;` — no new state needed.)

- [ ] **Step 10: Run the full frontend test suite to verify nothing broke**

Run: `cd frontend && npx vitest run`
Expected: all test files PASS (check in particular `StudentDetail.test.tsx` still passes — it likely needs `useNavOptions` mocked now too if it doesn't already mock it; if it fails with a real `fetch`/`absenzdashConfig` error, add `vi.mock("../../api/hooks/useNavOptions")` with a minimal mock return value to that test file, following the same pattern as `PdfExportSection.test.tsx` Step 5).

- [ ] **Step 11: Commit**

```bash
git add frontend/src/components/StudentDetail/pdfExportSections.ts frontend/src/components/StudentDetail/pdfExportSections.test.ts frontend/src/components/StudentDetail/PdfExportSection.tsx frontend/src/components/StudentDetail/PdfExportSection.test.tsx frontend/src/pages/StudentDetail/StudentDetail.tsx frontend/src/pages/StudentDetail/StudentDetail.test.tsx
git commit -m "$(cat <<'EOF'
feat: add PDF-export button to Schüler-Detail page

Section checkboxes (all five backend sections, all checked by default)
plus a Schuljahr-aware export button — picks up the currently selected
schuljahr URL param and passes it through to the (now Schuljahr-aware,
see previous commit) export endpoint. Blocks export client-side when no
section is selected, same pattern as the recent threshold-rule 422 fix.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Manual verification

- [ ] **Step 1: Backend — run the full test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS, no regressions.

- [ ] **Step 2: Frontend — run the full test suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all tests PASS, no type errors.

- [ ] **Step 3: Update ROADMAP.md**

In `ROADMAP.md`, mark Bundle B's two bullet points as done (✅ **Erledigt <Datum>**, following the exact pattern already used for Bundle E's three sub-points), summarizing the Fach-Kurzname resolution + collision handling and the PDF-export button + Schuljahr-Filter.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md
git commit -m "$(cat <<'EOF'
docs: mark Bundle B as complete in ROADMAP

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
