# Schuljahr-Historisierung (Klassenzugehörigkeit) & Rollover-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Fix `resolve_aktuelles_schuljahr()` so the escalation counter's rollover timing tracks the calendar date instead of lagging during WebUntis's "no active schoolyear" transition gap. (2) Make `klasse`-Zugehörigkeit schuljahresgebunden, so that switching the Schuljahr-Dropdown to a past year also changes the roster/class shown, via a new `schueler_klasse_historie` snapshot table.

**Architecture:** `klasse` gains a `schuljahr_id` FK (one row per class per schoolyear instead of one overwritten-in-place row); a new `schueler_klasse_historie` table holds one snapshot row per student per schoolyear, written by the ASV-CSV-Import on every run (for the currently resolved schoolyear) and bulk-snapshotted for **all** students at the moment `sync_orchestrator.py` detects a real schoolyear rollover. `GET /students`, `GET /students/{id}` and `GET /dashboard/nav-options` read from this historie table (or year-scoped `klasse` rows) instead of the live `schueler.klasse_id`/unscoped `klasse` table whenever `_resolve_schuljahr_zeitraum` resolves history mode.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Alembic / pytest (backend, `backend/`); React 18 / TypeScript (frontend, `frontend/`) — no frontend changes are expected (see Task 11).

**Referenz:** [Design-Dokument](../specs/2026-09-18-schuljahr-historisierung-design.md)

## Wichtige Abweichungen vom Design-Dok (beim Schreiben dieses Plans festgestellt)

Der Code hat sich seit dem Design-Dok (2026-09-18, selber Tag) bereits weiterentwickelt und ist an mehreren Stellen weiter als das Dok annimmt — und an einer Stelle wurde ein zusätzliches, vom Design-Dok nicht genanntes Korrektheitsproblem gefunden, das durch das `klasse.schuljahr_id`-Feature erst entsteht:

1. **`resolve_aktuelles_schuljahr()` existiert bereits** in `sync_orchestrator.py` (aus Plan 13, seither mehrfach gehärtet: `_juengstes_bereits_gestartetes_schuljahr`-Fallback ignoriert bereits nicht-gestartete Zukunfts-Schuljahre). Es fehlt aber genau die im Design-Dok verlangte Priorität: der Code fragt heute **zuerst** `getCurrentSchoolyear` und fällt nur bei Fehler/unbekannter ID auf den Cache zurück. Der Fix ist eine gezielte Umstellung der Reihenfolge (Task 1), kein Neubau.
2. **`_resolve_schuljahr_zeitraum`/`ist_historie`/`_aktuelles_schuljahr_zeitraum` existieren bereits** in `backend/app/api/routes/students.py`, inklusive Rohzahlen-Historie-Modus (`fehltage`/`fehlstunden`/`klassenbuch_anzahl` als `{gesamt, entschuldigt, unentschuldigt}`-Split), `zaehlerstand=None`/`{}` im Historie-Modus und dem am 2026-09-18 gefixten Normalmodus-Clamping (`aa53b8e`). Was fehlt, ist ausschließlich die `klasse`-Auflösung: beide Endpunkte lesen `klasse` heute in **jedem** Modus aus der live `schueler.klasse_id`/unscoped `klasse`-Tabelle (siehe `students.py:131`, `154`, `202-203`). Dieser Plan ergänzt nur noch die fehlende Klassen-Historie (Task 8/9), baut die Zeitraum-Auflösung nicht neu.
3. **`GET /dashboard/nav-options` liefert bereits `schuljahre`/`aktuelles_schuljahr_id`** (`NavOptionsOut` hat beide Felder, `dashboard_query.get_nav_options` befüllt sie). Die Route selbst nimmt aber noch keinen `schuljahr_id`-Query-Param an, und die `klassen`-Liste ist komplett unscoped (`select(Klasse).order_by(Klasse.name)`, `dashboard_query.py:47`). Task 10 ergänzt den Query-Param und die Scope-Filterung.
4. **Neu entdecktes, vom Design-Dok nicht genanntes Problem: `sync_bereiche` muss ebenfalls schuljahresgebunden gefiltert werden.** `sync_bereiche(db)` (`webuntis_bereich_sync.py:24`) liest heute **alle** `klasse`-Zeilen unscoped und baut daraus bei **jedem** Sync-Lauf `bereich_klasse` komplett neu (delete+insert je Abteilung). Sobald `klasse` pro Schuljahr eigene Zeilen bekommt (Task 2) und alte Zeilen nie gelöscht werden, würde `bereich_klasse` ab dem zweiten Rollover unter diesem Feature Klassen mehrerer Schuljahre gleichzeitig demselben Bereich zuordnen — das ist kein Historie-Problem, sondern eine waschechte Regression im **Normalmodus** (Bereichsleiter-Navigation, `/dashboard/stats` je Bereich, `nav-options`-Klassenliste über `resolve_scope`). Dieser Plan ergänzt daher **Task 4** (nicht im Design-Dok, aber notwendig, damit dieses Feature keine bestehende Funktionalität kaputt macht) — `sync_bereiche` bekommt einen Pflicht-Parameter `schuljahr_id` und filtert seine `klasse`-Abfrage darauf.
5. **Bekannte, bewusst nicht gefixte Randnotiz:** `seed_nutzer_klasse_from_webuntis` (`nutzer_klasse_sync.py`) iteriert ebenfalls unscoped über alle `klasse`-Zeilen und wird von `sync_klassen` nach jedem Sync aufgerufen — nach diesem Plan legt sie pro Jahr und Lehrkraft eine weitere `nutzer_klasse`-Zeile an (eine je Schuljahr-Klasse-Zeile mit passender `webuntis_teacher_id`), statt nur die aktuelle zu pflegen. Das ist funktional unschädlich (siehe Task 10: die betroffenen Lesepfade filtern explizit auf das relevante Schuljahr, sodass alte `nutzer_klasse`-Zeilen nirgends sichtbar werden), aber sorgt für unbegrenztes Wachstum von `nutzer_klasse` über die Jahre. Explizit **nicht** Teil dieses Plans (Design-Dok-Nicht-Ziel: "Historisierung von nutzer_klasse/Scope bleibt unverändert") — als Hinweis für eine spätere, separate Aufräum-Aufgabe hier dokumentiert.
6. **`Klasse.schuljahr_id` als `NOT NULL` FK hat einen sehr großen Blast Radius auf die Testsuite**, den das Design-Dok naturgemäß nicht erwähnt: `grep -rn "Klasse(webuntis_id" backend/tests/` findet **97 Konstruktor-Aufrufe in 18 Dateien**. Postgres (kein SQLite — `backend/.env`: `DATABASE_URL=postgresql+asyncpg://...`) erzwingt die FK strikt, jeder dieser Aufrufe muss künftig einen gültigen `schuljahr_id` mitbekommen. Task 2 behandelt das als eigenen, explizit mechanischen Sweep-Schritt (Checkliste + gemeinsame `schuljahr`-Fixture in `conftest.py`), statt jede Datei einzeln in diesem Dokument zu diffen.

## Global Constraints

- **Nicht-Ziele (Design-Dok, hier bewusst wiederholt, damit Implementierer nicht scope-creepen):**
  - Keine unterjährige Klassenwechsel-Historie — `schueler_klasse_historie` ist ein Snapshot pro Schüler und Schuljahr, keine von/bis-Historie.
  - Keine rückwirkende Befüllung der Historie für Schuljahre vor Einführung dieses Features — fehlende Zeilen liefern explizit `klasse=None` ("unbekannt"), nie einen Fallback auf die aktuelle Klasse.
  - Keine Schuljahresbindung von `schueler_zaehlerstand` — der Eskalations-Zählerstand bleibt ein laufender, nicht historisierter Wert (SPECS.md §5 unverändert); nur die Rollover-**Timing**-Logik in `resolve_aktuelles_schuljahr` wird gefixt (Task 1).
  - Keine Historisierung von `nutzer_klasse`/Scope-Auflösung (`resolve_scope`/`resolve_bereich_scope` bleiben unverändert auf der aktuellen Zuordnung basierend) — siehe Punkt 5 oben.
  - `massnahmen` bleiben in jedem Modus ungefiltert (bereits bestehendes Verhalten aus Plan 13, hier nicht angefasst).
- **`Klasse.schuljahr_id` ist `NOT NULL`** (Design-Dok-Entscheidung) — jede Produktionsstelle, die eine `Klasse`-Zeile anlegt (aktuell nur `webuntis_klassen_sync.sync_klassen`), muss den Wert immer mitgeben; es gibt keinen Code-Pfad, der eine `Klasse` ohne `schuljahr_id` anlegen darf.
- **`schueler_klasse_historie.klasse_id` ist nullable** — ein Schüler kann zu diesem Zeitpunkt ohne Klasse gewesen sein (z.B. frisch importiert, unbekannte ASV-Klasse).
- Aktueller Alembic-Head zum Zeitpunkt der Planerstellung: **`c9a67c39ff2b`** (`backend/alembic/versions/c9a67c39ff2b_add_stundenraster_periode_table.py`).
- Lokaler Dev-Stack läuft als Docker-Container: `absenzdash-backend` (Backend), `absenzdash-db` (Postgres). Migrationstests laufen gegen diese Container; Alembic wird in diesem Plan **nicht** gegen eine echte/Prod-DB ausgeführt (nur gegen den lokalen Dev-Stack, analog zu früheren Plänen).
- Commit-Messages auf Englisch (Projekt-Konvention).
- Nach Abschluss jedes Tasks committen; nach Abschluss des gesamten Plans `ROADMAP.md` aktualisieren (`CLAUDE.md`-Konvention, siehe Task 12).

---

## Task 1: Rollover-Fix — datumsbasierte Priorität in `resolve_aktuelles_schuljahr`

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py`
- Test: `backend/tests/test_sync_orchestrator.py`

**Interfaces:**
- Ändert nur das interne Verhalten von `resolve_aktuelles_schuljahr(client, db) -> Schuljahr` (Signatur unverändert) — nach dem Cache-Refresh wird zuerst nach einer gecachten `Schuljahr`-Zeile mit `start_datum <= heute <= end_datum` gesucht; nur wenn keine existiert, wird wie bisher `getCurrentSchoolyear` (dann `_juengstes_bereits_gestartetes_schuljahr`) als Fallback verwendet.

- [x] **Step 1: Fehlschlagenden Test schreiben**

In `backend/tests/test_sync_orchestrator.py`, füge nach `test_resolve_aktuelles_schuljahr_falls_back_when_current_id_not_in_cache` (Zeile ~322) ein:

```python
@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_prefers_date_covering_cached_row_over_stale_getcurrentschoolyear(db_session):
    """Reproduziert den Live-Fund vom 2026-09-18 (Root Cause Eskalationsstufe, siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md): WebUntis hat intern
    noch nicht auf das neue Schuljahr umgeschaltet (getCurrentSchoolyear meldet weiterhin das
    alte), obwohl getSchoolyears das neue Schuljahr laengst listet und dessen start_datum
    laut Kalenderdatum bereits begonnen hat. Der Resolver muss das per Datum passende gecachte
    Schuljahr VORZIEHEN statt sich auf die (in dieser Uebergangsphase falsche) Antwort von
    getCurrentSchoolyear zu verlassen - sonst kippt schuljahr_start_cache nicht rechtzeitig um
    und das Eskalations-Zaehlfenster zaehlt faelschlich weiter Fehlzeiten aus dem Vorjahr mit."""
    heute = datetime.now(timezone.utc).date()

    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {
                    "id": 28,
                    "name": "2025/2026",
                    "startDate": (heute - timedelta(days=365)).strftime("%Y%m%d"),
                    "endDate": (heute - timedelta(days=5)).strftime("%Y%m%d"),
                },
                {
                    "id": 29,
                    "name": "2026/2027",
                    "startDate": (heute - timedelta(days=4)).strftime("%Y%m%d"),
                    "endDate": (heute + timedelta(days=300)).strftime("%Y%m%d"),
                },
            ]
        if method == "getCurrentSchoolyear":
            # WebUntis meldet in der Uebergangsluecke noch das ALTE Schuljahr, obwohl das neue
            # laut Kalenderdatum und getSchoolyears bereits laeuft.
            return {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 29
    assert schuljahr.name == "2026/2027"
```

- [x] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py -k prefers_date_covering -v`
Expected: FAIL — der Test erwartet `schuljahr.id == 29`, der aktuelle Code liefert `28` (Antwort von `getCurrentSchoolyear`).

- [x] **Step 3: Resolver umbauen**

In `backend/app/services/sync_orchestrator.py`, in `resolve_aktuelles_schuljahr` (aktuell Zeilen 85-127), füge nach `await db.flush()` (Zeile 106) und vor dem `try:`-Block Folgendes ein:

```python
    await db.flush()

    heute = datetime.now(timezone.utc).date()
    datumstreffer = await db.execute(
        select(Schuljahr)
        .where(Schuljahr.start_datum <= heute, Schuljahr.end_datum >= heute)
        .order_by(Schuljahr.end_datum.desc())
        .limit(1)
    )
    passendes_schuljahr = datumstreffer.scalar_one_or_none()
    if passendes_schuljahr is not None:
        return passendes_schuljahr

    try:
        aktuell = await client.call("getCurrentSchoolyear", {})
    ...
```

(Der restliche `try`/`except`-Block und die anschließende `db.get`-Prüfung bleiben unverändert — nur der neue Block wird davor eingefügt.)

Aktualisiere den Docstring der Funktion (ersetze den bestehenden Text):

```python
async def resolve_aktuelles_schuljahr(client: WebUntisClient, db: AsyncSession) -> Schuljahr:
    """Aktualisiert den schuljahr-Cache aus getSchoolyears und liefert das aktuell gueltige
    Schuljahr zurueck - datumsbasiert bevorzugt: die zuerst gepruefte Quelle ist eine gecachte
    Schuljahr-Zeile, deren [start_datum, end_datum] das heutige Kalenderdatum abdeckt. Das ist
    noetig, weil WebUntis' eigenes 'aktuelles Schuljahr' (getCurrentSchoolyear) waehrend der
    Uebergangsluecke zwischen zwei Schuljahren zeitweise dem Kalenderdatum hinterherhinkt (Live-
    Fund 2026-09-18, siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md)
    - ohne diesen Vorrang wuerde einstellung.aktuelles_schuljahr_id/schuljahr_start_cache zu spaet
    umkippen und das Eskalations-Zaehlfenster faelschlich noch Fehlzeiten des Vorjahres mitzaehlen.
    Nur wenn KEINE gecachte Zeile das heutige Datum abdeckt (echte Luecke: WebUntis hat das neue
    Schuljahr noch gar nicht angelegt), wird wie bisher auf getCurrentSchoolyear zurueckgegriffen,
    und bei dessen Fehlschlag/einer im Cache unbekannten ID auf das juengste bereits gestartete
    Schuljahr (siehe _juengstes_bereits_gestartetes_schuljahr)."""
```

- [x] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py -v`
Expected: alle Tests PASS — insbesondere bleiben die bestehenden Fallback-Tests (`..._uses_current_schoolyear`, `..._falls_back_to_newest_cached...`, `..._fallback_ignores_future_not_yet_started...`, `..._falls_back_when_current_id_not_in_cache`) grün, weil ihre hartkodierten Testdaten (Schuljahre 2024/2025, 2025/2026) das tatsächliche Testlaufdatum (2026 und später) nicht mehr abdecken und der neue Datums-Check dort keinen Treffer liefert, wodurch der bestehende Fallback-Pfad unverändert greift.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py
git commit -m "fix: prefer date-covering cached schoolyear over stale getCurrentSchoolyear answer"
```

---

## Task 2: `klasse.schuljahr_id` — Modell, Migration, Testsuite-Sweep

**Files:**
- Modify: `backend/app/models/klasse.py`
- Create: `backend/alembic/versions/<hash_a>_add_klasse_schuljahr_id.py`
- Modify: `backend/tests/test_models_klasse.py`
- Modify: `backend/tests/conftest.py`
- Modify (mechanischer Sweep, siehe Step 6): alle 18 in Step 6 gelisteten Testdateien

**Interfaces:**
- Produces: `Klasse.schuljahr_id: int` (FK `schuljahr.id`, `NOT NULL`). Unique-Constraint wechselt von `webuntis_id` allein zu `(webuntis_id, schuljahr_id)` (Name: `uq_klasse_webuntis_id_schuljahr_id`). `webuntis_id` bleibt (nicht-eindeutig) indiziert.
- Produces: `tests/conftest.py`-Fixture `schuljahr` (siehe Step 6) — Standard-`Schuljahr`-Zeile für Tests, die `Klasse`-Zeilen anlegen müssen.

- [x] **Step 1: Fehlschlagende Modell-Tests schreiben**

Ersetze den kompletten Inhalt von `backend/tests/test_models_klasse.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.schuljahr import Schuljahr


async def _seed_schuljahre(db_session) -> tuple[Schuljahr, Schuljahr]:
    from datetime import date

    alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([alt, neu])
    await db_session.flush()
    return alt, neu


@pytest.mark.asyncio
async def test_klasse_roundtrip(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    klasse = Klasse(
        webuntis_id=3499, name="10a", webuntis_teacher1_id=63, webuntis_teacher2_id=434, schuljahr_id=schuljahr.id
    )
    db_session.add(klasse)
    await db_session.commit()

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    loaded = result.scalar_one()
    assert loaded.name == "10a"
    assert loaded.webuntis_teacher1_id == 63
    assert loaded.schuljahr_id == schuljahr.id


@pytest.mark.asyncio
async def test_klasse_schuljahr_id_is_required(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    db_session.add(Klasse(webuntis_id=1, name="10a"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_klasse_allows_same_webuntis_id_in_different_schuljahre(db_session):
    alt, neu = await _seed_schuljahre(db_session)
    db_session.add_all(
        [
            Klasse(webuntis_id=1, name="10a", schuljahr_id=alt.id),
            Klasse(webuntis_id=1, name="10b", schuljahr_id=neu.id),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 1))
    rows = result.scalars().all()
    assert {r.schuljahr_id for r in rows} == {alt.id, neu.id}


@pytest.mark.asyncio
async def test_klasse_forbids_same_webuntis_id_and_schuljahr_id_twice(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    db_session.add(Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id))
    await db_session.commit()

    db_session.add(Klasse(webuntis_id=1, name="10a-dup", schuljahr_id=schuljahr.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_bereich_klasse_association(db_session):
    _, schuljahr = await _seed_schuljahre(db_session)
    klasse = Klasse(webuntis_id=1, name="11b", schuljahr_id=schuljahr.id)
    bereich = Bereich(name="Kaufmännischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()

    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    result = await db_session.execute(select(bereich_klasse))
    row = result.first()
    assert row.bereich_id == bereich.id
    assert row.klasse_id == klasse.id
```

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_models_klasse.py -v`
Expected: FAIL — `Klasse()` akzeptiert `schuljahr_id` noch nicht als Argument (`TypeError`), bzw. `test_klasse_schuljahr_id_is_required`/`..._forbids_same_webuntis_id...` schlagen fehl, weil die aktuelle Spalte noch nullable/unique-per-webuntis_id-only ist.

- [x] **Step 3: Modell ändern**

Ersetze den kompletten Inhalt von `backend/app/models/klasse.py`:

```python
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Klasse(Base, TimestampMixin):
    """Eine Klasse ist seit diesem Modell schuljahresgebunden - WebUntis selbst behandelt eine
    Klasse bereits als jahresgebundenes Konzept (getKlassen verlangt zwingend eine schoolyearId),
    siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md. Pro (webuntis_id,
    schuljahr_id) existiert genau eine Zeile statt eines pro Jahr ueberschriebenen Datensatzes -
    alte Jahre werden nie geloescht."""

    __tablename__ = "klasse"
    __table_args__ = (
        UniqueConstraint("webuntis_id", "schuljahr_id", name="uq_klasse_webuntis_id_schuljahr_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(50))
    abteilung_id: Mapped[int | None] = mapped_column(ForeignKey("abteilung.id"), nullable=True)
    webuntis_teacher1_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webuntis_teacher2_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schuljahr_id: Mapped[int] = mapped_column(ForeignKey("schuljahr.id"), nullable=False)
```

- [x] **Step 4: Migration schreiben**

```bash
docker exec absenzdash-backend python -m alembic revision -m "add klasse schuljahr_id"
```

Fülle die generierte Datei unter `backend/alembic/versions/` (Revision-ID/Create-Date aus dem generierten Stub übernehmen, `<hash_a>` durch den echten Wert ersetzen):

```python
"""add klasse schuljahr_id

Macht klasse schuljahresgebunden (siehe docs/superpowers/specs/2026-09-18-schuljahr-
historisierung-design.md): neue Spalte schuljahr_id (FK schuljahr.id, NOT NULL), Unique-
Constraint wechselt von webuntis_id allein zu (webuntis_id, schuljahr_id). Bestehende Zeilen
werden per Best-Effort-Backfill auf einstellung.aktuelles_schuljahr_id gesetzt - es gibt keine
Moeglichkeit, fruehere Jahreszuordnungen rueckwirkend zu rekonstruieren (Nicht-Ziel).

Revision ID: <hash_a>
Revises: c9a67c39ff2b
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "<hash_a>"
down_revision = "c9a67c39ff2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("klasse", sa.Column("schuljahr_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE klasse SET schuljahr_id = (SELECT aktuelles_schuljahr_id FROM einstellung ORDER BY id LIMIT 1) "
        "WHERE schuljahr_id IS NULL"
    )
    op.alter_column("klasse", "schuljahr_id", nullable=False)
    op.create_foreign_key("fk_klasse_schuljahr_id", "klasse", "schuljahr", ["schuljahr_id"], ["id"])
    op.drop_index("ix_klasse_webuntis_id", table_name="klasse")
    op.create_index("ix_klasse_webuntis_id", "klasse", ["webuntis_id"], unique=False)
    op.create_unique_constraint("uq_klasse_webuntis_id_schuljahr_id", "klasse", ["webuntis_id", "schuljahr_id"])


def downgrade() -> None:
    op.drop_constraint("uq_klasse_webuntis_id_schuljahr_id", "klasse", type_="unique")
    op.drop_index("ix_klasse_webuntis_id", table_name="klasse")
    op.create_index("ix_klasse_webuntis_id", "klasse", ["webuntis_id"], unique=True)
    op.drop_constraint("fk_klasse_schuljahr_id", "klasse", type_="foreignkey")
    op.drop_column("klasse", "schuljahr_id")
```

**Achtung Backfill-Edge-Case:** Falls die Ziel-DB `einstellung.aktuelles_schuljahr_id IS NULL` hat (z.B. noch nie erfolgreich gesynct) UND bereits `klasse`-Zeilen existieren, bleibt `schuljahr_id` nach dem `UPDATE` `NULL` und `alter_column(..., nullable=False)` schlägt fehl. Vor dem Ausführen gegen eine DB mit Altdaten (nicht der leere lokale Dev-Stack) manuell prüfen: `SELECT aktuelles_schuljahr_id FROM einstellung;` — falls `NULL` und `klasse` nicht leer ist, zuerst einen Sync-Lauf durchführen (setzt `aktuelles_schuljahr_id`) oder die Migration um einen expliziten Fallback-Wert ergänzen, bevor sie angewendet wird.

- [x] **Step 5: Migration gegen den Dev-Stack verifizieren**

```bash
docker exec absenzdash-backend python -m alembic upgrade head
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d klasse"
docker exec absenzdash-backend python -m alembic downgrade -1
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d klasse"
docker exec absenzdash-backend python -m alembic upgrade head
```

Erwartet: nach `upgrade head` zeigt `\d klasse` die neue Spalte `schuljahr_id` (NOT NULL), den FK `fk_klasse_schuljahr_id`, den nicht-eindeutigen Index `ix_klasse_webuntis_id` und den Unique-Constraint `uq_klasse_webuntis_id_schuljahr_id`; nach `downgrade -1` ist alles auf den alten Stand zurück (`ix_klasse_webuntis_id` wieder `UNIQUE`, keine `schuljahr_id`-Spalte); erneutes `upgrade head` läuft sauber durch.

- [x] **Step 6: Testsuite-Sweep — `schuljahr`-Fixture + alle betroffenen `Klasse(...)`-Konstruktoraufrufe**

Füge in `backend/tests/conftest.py` (nach den bestehenden Imports/Fixtures) eine wiederverwendbare Fixture hinzu:

```python
from datetime import date

from app.models.schuljahr import Schuljahr


@pytest_asyncio.fixture
async def schuljahr(db_session) -> Schuljahr:
    """Standard-Schuljahr fuer Tests, die Klasse-Zeilen anlegen muessen (Klasse.schuljahr_id ist
    seit diesem Plan NOT NULL). id/Daten sind fuer die meisten Tests irrelevant - nur der
    Fremdschluessel muss aufloesbar sein. Tests, die bereits ein eigenes Schuljahr mit konkreten
    Daten anlegen (z.B. um zwei Jahre zu vergleichen), nutzen weiterhin ihr eigenes und lassen
    diese Fixture ungenutzt."""
    jahr = Schuljahr(id=1, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add(jahr)
    await db_session.flush()
    return jahr
```

Grep-Checkliste (Stand Planerstellung, `grep -rn "Klasse(webuntis_id" backend/tests/*.py | wc -l` → 97 Treffer in 18 Dateien) — für jede Datei: Testfunktionen, die `Klasse(webuntis_id=..., ...)` konstruieren, bekommen den `schuljahr`-Fixture-Parameter und jeder `Klasse(...)`-Aufruf bekommt `schuljahr_id=schuljahr.id` (bzw. `schuljahr_id=<eigenes bereits im Test angelegtes Schuljahr>.id`, falls der Test schon selbst ein `Schuljahr` mit spezifischen Daten anlegt — z.B. `test_api_students.py`/`test_dashboard_query.py`, die bereits IDs wie 27/28/30 verwenden):

| Datei | Treffer | Hinweis |
|---|---|---|
| `test_api_students.py` | 30 | mehrere Tests legen bereits eigene `Schuljahr`-Zeilen an (z.B. `test_get_students_history_mode_...`) — dort deren `.id` verwenden, nicht die generische Fixture |
| `test_dashboard_query.py` | 20 | s.o. |
| `test_api_deps_scope.py` | 10 | generische `schuljahr`-Fixture nutzen |
| `test_eskalations_pruefung.py` | 11 | generische Fixture |
| `test_nutzer_klasse_sync.py` | 4 | generische Fixture |
| `test_webuntis_bereich_sync.py` | 3 | wird in Task 4 ohnehin komplett überarbeitet — dort erledigt |
| `test_massnahme_service.py` | 2 | generische Fixture |
| `test_api_admin_threshold_rules.py` | 1 | generische Fixture |
| `test_api_dashboard.py` | 2 | generische Fixture |
| `test_asv_csv_import.py` | 1 | wird in Task 6 ohnehin komplett überarbeitet — dort erledigt |
| `test_bereich_service.py` | 2 | generische Fixture |
| `test_export_service.py` | 2 | generische Fixture |
| `test_eskalations_pruefung_regelaufloesung.py` | 3 | generische Fixture |
| `test_models_nutzer.py` | 1 | generische Fixture |
| `test_models_schueler.py` | 1 | generische Fixture |
| `test_models_schwellwert.py` | 1 | generische Fixture |
| `test_student_query.py` | 5 | generische Fixture |
| `test_webuntis_klassen_sync.py` | 1 | wird in Task 3 ohnehin komplett überarbeitet — dort erledigt |

Beispiel-Diff (einfacher Fall, z.B. `test_models_nutzer.py`):

```python
# vorher
async def test_...(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")

# nachher
async def test_...(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
```

Beispiel-Diff (zwei `Klasse`-Instanzen in einem Test, z.B. `test_api_deps_scope.py`):

```python
# vorher
async def test_...(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")

# nachher
async def test_...(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
```

Nach jeder Datei: `docker exec absenzdash-backend python -m pytest tests/<datei> -v` und iterieren, bis alle `IntegrityError`/`TypeError`-Fehlschläge behoben sind. `test_webuntis_klassen_sync.py`, `test_webuntis_bereich_sync.py` und `test_asv_csv_import.py` werden bewusst NICHT hier, sondern in ihren jeweiligen Tasks (3, 4, 6) mit vollständigem Kontext überarbeitet, da sie ohnehin für neues Verhalten umgeschrieben werden.

- [x] **Step 7: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: außer den in Task 3/4/6 noch zu behebenden Dateien (`test_webuntis_klassen_sync.py`, `test_webuntis_bereich_sync.py`, `test_asv_csv_import.py` — diese schlagen an dieser Stelle noch mit `IntegrityError` fehl, das ist erwartet) sind alle anderen Tests grün. Das ist der einzige Task in diesem Plan, nach dem die Gesamtsuite bewusst noch nicht vollständig grün ist.

- [x] **Step 8: Commit**

```bash
git add backend/app/models/klasse.py backend/alembic/versions/ backend/tests/conftest.py backend/tests/test_models_klasse.py \
  backend/tests/test_api_students.py backend/tests/test_dashboard_query.py backend/tests/test_api_deps_scope.py \
  backend/tests/test_eskalations_pruefung.py backend/tests/test_nutzer_klasse_sync.py backend/tests/test_massnahme_service.py \
  backend/tests/test_api_admin_threshold_rules.py backend/tests/test_api_dashboard.py backend/tests/test_bereich_service.py \
  backend/tests/test_export_service.py backend/tests/test_eskalations_pruefung_regelaufloesung.py backend/tests/test_models_nutzer.py \
  backend/tests/test_models_schueler.py backend/tests/test_models_schwellwert.py backend/tests/test_student_query.py
git commit -m "feat: make klasse schoolyear-scoped (schuljahr_id, composite unique key)"
```

---

## Task 3: `sync_klassen` — Upsert nach `(webuntis_id, schuljahr_id)`

**Files:**
- Modify: `backend/app/services/webuntis_klassen_sync.py`
- Modify: `backend/tests/test_webuntis_klassen_sync.py`

**Interfaces:**
- `sync_klassen(client, db, schoolyear_id)` — Signatur unverändert, aber der interne Upsert-Schlüssel wird von `webuntis_id` allein zu `(webuntis_id, schoolyear_id)`.

- [x] **Step 1: Fehlschlagenden Test schreiben**

Ersetze den kompletten Inhalt von `backend/tests/test_webuntis_klassen_sync.py`:

```python
from datetime import date
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schuljahr import Schuljahr
from app.services.webuntis_klassen_sync import sync_klassen


async def _seed_schuljahr(db_session, schuljahr_id: int = 28) -> Schuljahr:
    schuljahr = Schuljahr(id=schuljahr_id, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add(schuljahr)
    await db_session.commit()
    return schuljahr


@pytest.mark.asyncio
async def test_sync_klassen_creates_new_klasse(db_session):
    await _seed_schuljahr(db_session)
    client = AsyncMock()
    client.call.return_value = [
        {"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None},
    ]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.name == "10a"
    assert klasse.webuntis_teacher1_id == 63
    assert klasse.webuntis_teacher2_id is None
    assert klasse.schuljahr_id == 28
    client.call.assert_awaited_once_with("getKlassen", {"schoolyearId": 28})


@pytest.mark.asyncio
async def test_sync_klassen_updates_existing_klasse(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    existing = Klasse(webuntis_id=1, name="alt", webuntis_teacher1_id=1, schuljahr_id=schuljahr.id)
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 1, "name": "neu", "teacher1": 2, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 1))
    klasse = result.scalar_one()
    assert klasse.name == "neu"
    assert klasse.webuntis_teacher1_id == 2


@pytest.mark.asyncio
async def test_sync_klassen_creates_separate_rows_per_schuljahr_for_same_webuntis_id(db_session):
    """Kernverhalten dieses Tasks: derselbe webuntis_id-Wert darf in zwei unterschiedlichen
    Schuljahren zu zwei getrennten Klasse-Zeilen fuehren, statt dieselbe Zeile zu ueberschreiben
    (siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md)."""
    db_session.add_all(
        [
            Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30)),
            Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29)),
        ]
    )
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=27)
    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499).order_by(Klasse.schuljahr_id))
    rows = result.scalars().all()
    assert [r.schuljahr_id for r in rows] == [27, 28]
    assert rows[0].id != rows[1].id


@pytest.mark.asyncio
async def test_sync_klassen_triggers_nutzer_klasse_seeding(db_session):
    await _seed_schuljahr(db_session)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft", webuntis_teacher_id=63)
    db_session.add(nutzer)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(NutzerKlasse))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].quelle == "webuntis_seed"


@pytest.mark.asyncio
async def test_sync_klassen_resolves_abteilung_id_from_did(db_session):
    await _seed_schuljahr(db_session)
    abteilung = Abteilung(webuntis_id=64, name="A-2BFE")
    db_session.add(abteilung)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "did": 64, "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.abteilung_id == abteilung.id


@pytest.mark.asyncio
async def test_sync_klassen_leaves_abteilung_id_none_when_did_unresolvable(db_session):
    await _seed_schuljahr(db_session)
    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "did": 999, "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session, schoolyear_id=28)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.abteilung_id is None
```

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_webuntis_klassen_sync.py -v`
Expected: FAIL — bestehende Tests scheitern an der fehlenden `Schuljahr`-Zeile (FK-Verletzung), der neue Test `test_sync_klassen_creates_separate_rows_per_schuljahr_for_same_webuntis_id` scheitert zusätzlich daran, dass `sync_klassen` die zweite Zeile fälschlich als Update der ersten behandelt (heutiges `by_webuntis_id`-Dict ist über ALLE Klasse-Zeilen aufgebaut, nicht schuljahr-gefiltert).

- [x] **Step 3: `sync_klassen` anpassen**

In `backend/app/services/webuntis_klassen_sync.py`, ändere:

```python
    existing = (await db.execute(select(Klasse))).scalars().all()
    by_webuntis_id = {klasse.webuntis_id: klasse for klasse in existing}
```

zu:

```python
    existing = (
        await db.execute(select(Klasse).where(Klasse.schuljahr_id == schoolyear_id))
    ).scalars().all()
    by_webuntis_id = {klasse.webuntis_id: klasse for klasse in existing}
```

und:

```python
        if klasse is None:
            klasse = Klasse(webuntis_id=row["id"], name=row["name"])
            db.add(klasse)
```

zu:

```python
        if klasse is None:
            klasse = Klasse(webuntis_id=row["id"], name=row["name"], schuljahr_id=schoolyear_id)
            db.add(klasse)
```

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_webuntis_klassen_sync.py -v`
Expected: alle 6 Tests PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/webuntis_klassen_sync.py backend/tests/test_webuntis_klassen_sync.py
git commit -m "fix: key sync_klassen upsert by (webuntis_id, schoolyear_id)"
```

---

## Task 4: `sync_bereiche` — Klassen-Abfrage auf das aktuelle Schuljahr scopen

*(Nicht im Design-Dok, aber notwendig — siehe "Wichtige Abweichungen" Punkt 4 oben: ohne diesen Fix vermischt `bereich_klasse` ab dem zweiten Rollover unter diesem Feature Klassen mehrerer Schuljahre im selben Bereich.)*

**Files:**
- Modify: `backend/app/services/webuntis_bereich_sync.py`
- Modify: `backend/app/services/sync_orchestrator.py`
- Modify: `backend/tests/test_webuntis_bereich_sync.py`

**Interfaces:**
- `sync_bereiche(db, schuljahr_id)` — neuer Pflicht-Parameter `schuljahr_id: int`.

- [x] **Step 1: Fehlschlagende Tests schreiben**

Ersetze den kompletten Inhalt von `backend/tests/test_webuntis_bereich_sync.py`:

```python
from datetime import date

import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.schuljahr import Schuljahr
from app.services.webuntis_bereich_sync import sync_bereiche


async def _seed_schuljahr(db_session, schuljahr_id: int = 28) -> Schuljahr:
    schuljahr = Schuljahr(id=schuljahr_id, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add(schuljahr)
    await db_session.flush()
    return schuljahr


@pytest.mark.asyncio
async def test_sync_bereiche_creates_bereich_per_abteilung_with_matching_klassen(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    klasse_zugehoerig = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id, schuljahr_id=schuljahr.id)
    klasse_fremd = Klasse(webuntis_id=2, name="2BFE", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_zugehoerig, klasse_fremd])
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "Mechatronik"
    assert bereich.abteilung_id == abteilung.id
    assert bereich.ausgeblendet is False
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == [klasse_zugehoerig.id]


@pytest.mark.asyncio
async def test_sync_bereiche_ignores_klassen_from_other_schuljahre(db_session):
    """Regression (siehe 'Wichtige Abweichungen' Punkt 4): klasse.schuljahr_id trennt seit Task 2
    mehrere Jahrgaenge derselben webuntis_id in getrennte, nie geloeschte Zeilen. sync_bereiche
    baut bereich_klasse bei JEDEM Sync-Lauf komplett neu (delete+insert je Abteilung) - ohne
    Schuljahr-Filter wuerden alte Klassen-Zeilen frueherer Jahre das Mapping jedes Jahr weiter
    aufblaehen und Klassen mehrerer Schuljahre gleichzeitig im selben Bereich zeigen."""
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add_all([schuljahr_alt, schuljahr_neu, abteilung])
    await db_session.flush()
    klasse_altes_jahr = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id, schuljahr_id=schuljahr_alt.id)
    klasse_neues_jahr = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id, schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_altes_jahr, klasse_neues_jahr])
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr_neu.id)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == [klasse_neues_jahr.id]


@pytest.mark.asyncio
async def test_sync_bereiche_creates_bereich_with_zero_klassen_for_empty_abteilung(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    db_session.add(Abteilung(webuntis_id=61, name="B-ALT", long_name="Historisch"))
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "Historisch"
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == []


@pytest.mark.asyncio
async def test_sync_bereiche_falls_back_to_name_without_long_name(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    db_session.add(Abteilung(webuntis_id=59, name="B-IE", long_name=None))
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "B-IE"


@pytest.mark.asyncio
async def test_sync_bereiche_disambiguates_colliding_long_names(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    db_session.add_all(
        [
            Abteilung(webuntis_id=61, name="BT", long_name="Betriebstechnik"),
            Abteilung(webuntis_id=62, name="B-BT", long_name="Betriebstechnik"),
        ]
    )
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    namen = (await db_session.execute(select(Bereich.name))).scalars().all()
    assert sorted(namen) == ["Betriebstechnik (B-BT)", "Betriebstechnik (BT)"]


@pytest.mark.asyncio
async def test_sync_bereiche_updates_name_on_abteilung_rename(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.commit()
    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    abteilung.long_name = "Mechatronik neu"
    await db_session.commit()
    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereiche = (await db_session.execute(select(Bereich))).scalars().all()
    assert len(bereiche) == 1
    assert bereiche[0].name == "Mechatronik neu"


@pytest.mark.asyncio
async def test_sync_bereiche_rebuilds_bereich_klasse_when_klasse_moves_abteilung(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    abteilung_a = Abteilung(webuntis_id=1, name="A", long_name="Abteilung A")
    abteilung_b = Abteilung(webuntis_id=2, name="B", long_name="Abteilung B")
    db_session.add_all([abteilung_a, abteilung_b])
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung_a.id, schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.commit()
    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    klasse.abteilung_id = abteilung_b.id
    await db_session.commit()
    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereich_a = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_a.id))).scalar_one()
    bereich_b = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_b.id))).scalar_one()
    klasse_ids_a = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_a.id))
    ).scalars().all()
    klasse_ids_b = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_b.id))
    ).scalars().all()
    assert klasse_ids_a == []
    assert klasse_ids_b == [klasse.id]


@pytest.mark.asyncio
async def test_sync_bereiche_handles_rename_new_abteilung_name_collision(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    abteilung_a = Abteilung(webuntis_id=51, name="A", long_name="Foo")
    db_session.add(abteilung_a)
    await db_session.commit()
    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    abteilung_a.long_name = "Foo Neu"
    abteilung_b = Abteilung(webuntis_id=52, name="B", long_name="Foo")
    db_session.add(abteilung_b)
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereich_a = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_a.id))).scalar_one()
    bereich_b = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_b.id))).scalar_one()
    assert bereich_a.name == "Foo Neu"
    assert bereich_b.name == "Foo"


@pytest.mark.asyncio
async def test_sync_bereiche_never_touches_ausgeblendet_or_leiter(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.commit()
    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    bereich.ausgeblendet = True
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))
    await db_session.commit()

    await sync_bereiche(db_session, schuljahr_id=schuljahr.id)

    await db_session.refresh(bereich)
    assert bereich.ausgeblendet is True
    leiter_rows = (
        await db_session.execute(select(nutzer_bereich).where(nutzer_bereich.c.bereich_id == bereich.id))
    ).all()
    assert len(leiter_rows) == 1
```

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_webuntis_bereich_sync.py -v`
Expected: FAIL — `sync_bereiche()` akzeptiert `schuljahr_id` noch nicht (`TypeError`), und `test_sync_bereiche_ignores_klassen_from_other_schuljahre` würde bei ungefixter Implementierung ohnehin beide Klassen-Zeilen zurückgeben.

- [x] **Step 3: `sync_bereiche` anpassen**

In `backend/app/services/webuntis_bereich_sync.py`, ändere die Signatur und die Klassen-Abfrage:

```python
async def sync_bereiche(db: AsyncSession, schuljahr_id: int) -> None:
    """..."""
    abteilungen = (await db.execute(select(Abteilung).order_by(Abteilung.name))).scalars().all()
    klassen = (await db.execute(select(Klasse).where(Klasse.schuljahr_id == schuljahr_id))).scalars().all()
```

(Rest der Funktion unverändert.) Ergänze im Docstring einen Satz, dass `klassen` bewusst auf das übergebene Schuljahr gescopet ist, da `klasse`-Zeilen älterer Jahre nie gelöscht werden.

- [x] **Step 4: Aufrufer anpassen**

In `backend/app/services/sync_orchestrator.py`, ändere in `_run_sync_once_impl`:

```python
        await sync_bereiche(db)
```

zu:

```python
        await sync_bereiche(db, schuljahr_id=aktuelles_schuljahr.id)
```

- [x] **Step 5: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_webuntis_bereich_sync.py tests/test_sync_orchestrator.py -v`
Expected: alle Tests PASS (`test_sync_orchestrator.py` mockt `sync_bereiche` vollständig, der zusätzliche Keyword-Parameter ist für `AsyncMock` unproblematisch).

- [x] **Step 6: Commit**

```bash
git add backend/app/services/webuntis_bereich_sync.py backend/app/services/sync_orchestrator.py backend/tests/test_webuntis_bereich_sync.py
git commit -m "fix: scope sync_bereiche's klasse lookup to the current schuljahr"
```

---

## Task 5: `schueler_klasse_historie` — Modell und Migration

**Files:**
- Create: `backend/app/models/schueler_klasse_historie.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/<hash_b>_add_schueler_klasse_historie.py`
- Test: `backend/tests/test_models_schueler_klasse_historie.py`

**Interfaces:**
- Produces: `SchuelerKlasseHistorie` (`id`, `schueler_id` FK, `schuljahr_id` FK, `klasse_id` FK nullable), unique `(schueler_id, schuljahr_id)`.

- [x] **Step 1: Fehlschlagenden Test schreiben**

Erstelle `backend/tests/test_models_schueler_klasse_historie.py`:

```python
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr


@pytest.mark.asyncio
async def test_schueler_klasse_historie_roundtrip(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add_all([schuljahr, klasse, schueler])
    await db_session.flush()

    historie = SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id)
    db_session.add(historie)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
    )
    loaded = result.scalar_one()
    assert loaded.schuljahr_id == schuljahr.id
    assert loaded.klasse_id == klasse.id


@pytest.mark.asyncio
async def test_schueler_klasse_historie_klasse_id_is_nullable(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add_all([schuljahr, schueler])
    await db_session.flush()

    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    await db_session.commit()  # darf nicht scheitern


@pytest.mark.asyncio
async def test_schueler_klasse_historie_unique_per_schueler_and_schuljahr(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add_all([schuljahr, schueler])
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    await db_session.commit()

    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [x] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_models_schueler_klasse_historie.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.schueler_klasse_historie'`.

- [x] **Step 3: Modell erstellen**

`backend/app/models/schueler_klasse_historie.py`:

```python
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerKlasseHistorie(Base, TimestampMixin):
    """Ein Snapshot pro Schueler und Schuljahr (wie ein Zeugnis-Eintrag) - keine unterjaehrige
    Wechsel-Historie. Geschrieben/aktualisiert vom ASV-CSV-Import (fuer das jeweils aktuelle
    Schuljahr, bei jedem Import) und einmalig fuer ALLE Schueler beim Erkennen eines echten
    Schuljahreswechsels in sync_orchestrator.py. Fehlende Zeilen (Schuljahre vor Einfuehrung
    dieses Features) bedeuten explizit 'unbekannt', nicht 'aktuelle Klasse', siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md."""

    __tablename__ = "schueler_klasse_historie"
    __table_args__ = (
        UniqueConstraint("schueler_id", "schuljahr_id", name="uq_schueler_klasse_historie_schueler_schuljahr"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    schuljahr_id: Mapped[int] = mapped_column(ForeignKey("schuljahr.id", ondelete="CASCADE"))
    klasse_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("klasse.id", ondelete="SET NULL"), nullable=True
    )
```

In `backend/app/models/__init__.py`, füge alphabetisch ein:

```python
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

(nach `from app.models.schueler import Schueler`, vor `from app.models.schueler_zaehlerstand import SchuelerZaehlerstand`) und in `__all__` entsprechend `"SchuelerKlasseHistorie",`.

- [x] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_models_schueler_klasse_historie.py -v`
Expected: alle 3 Tests PASS.

- [x] **Step 5: Migration schreiben**

```bash
docker exec absenzdash-backend python -m alembic revision -m "add schueler_klasse_historie table"
```

Fülle die generierte Datei (`<hash_b>` durch echten Wert ersetzen, `down_revision` muss `<hash_a>` aus Task 2 sein):

```python
"""add schueler_klasse_historie table

Revision ID: <hash_b>
Revises: <hash_a>
Create Date: 2026-09-18
"""

from alembic import op
import sqlalchemy as sa

revision = "<hash_b>"
down_revision = "<hash_a>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schueler_klasse_historie",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schueler_id", sa.Integer(), nullable=False),
        sa.Column("schuljahr_id", sa.Integer(), nullable=False),
        sa.Column("klasse_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["schueler_id"], ["schueler.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schuljahr_id"], ["schuljahr.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["klasse_id"], ["klasse.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schueler_id", "schuljahr_id", name="uq_schueler_klasse_historie_schueler_schuljahr"),
    )


def downgrade() -> None:
    op.drop_table("schueler_klasse_historie")
```

- [x] **Step 6: Migration gegen den Dev-Stack verifizieren**

```bash
docker exec absenzdash-backend python -m alembic upgrade head
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d schueler_klasse_historie"
docker exec absenzdash-backend python -m alembic downgrade -1
docker exec absenzdash-backend python -m alembic upgrade head
```

- [x] **Step 7: Commit**

```bash
git add backend/app/models/schueler_klasse_historie.py backend/app/models/__init__.py \
  backend/alembic/versions/ backend/tests/test_models_schueler_klasse_historie.py
git commit -m "feat: add schueler_klasse_historie table and model"
```

---

## Task 6: ASV-CSV-Import — Historie-Snapshot pro Import

**Files:**
- Modify: `backend/app/services/asv_csv_import.py`
- Modify: `backend/tests/test_asv_csv_import.py`

**Interfaces:**
- `import_schueler(db)` — Signatur unverändert. Zusätzlich zum bestehenden `schueler.klasse_id`-Schreiben wird `schueler_klasse_historie(schueler_id, schuljahr_id=einstellung.aktuelles_schuljahr_id, klasse_id=<ermittelte klasse_id>)` upserted, sofern `aktuelles_schuljahr_id` gesetzt ist. Der `klasse_id_by_name`-Lookup wird auf `Klasse.schuljahr_id == einstellung.aktuelles_schuljahr_id` gescopet (vorher unscoped über alle Jahre).

- [x] **Step 1: Fehlschlagende Tests schreiben**

Ersetze den kompletten Inhalt von `backend/tests/test_asv_csv_import.py`:

```python
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr
from app.services.asv_csv_import import import_schueler

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "schueler.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _set_csv_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asv_csv_path", str(tmp_path / "schueler.csv"))


async def _seed_aktuelles_schuljahr(db_session, schuljahr_id: int = 30) -> Schuljahr:
    schuljahr = Schuljahr(id=schuljahr_id, name="2025/2026", start_datum=date(2025, 9, 8), end_datum=date(2026, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_id))
    await db_session.commit()
    return schuljahr


@pytest.mark.asyncio
async def test_import_creates_schueler_with_matching_klasse(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"abcd-0018";"abcd-0018";"ext-uuid-1";"Mustermann";"Frank";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-1"))
    schueler = result.scalar_one()
    assert schueler.vorname == "Frank"
    assert schueler.nachname == "Mustermann"
    assert schueler.aktiv is True
    klasse_result = await db_session.execute(select(Klasse).where(Klasse.id == schueler.klasse_id))
    assert klasse_result.scalar_one().name == "AME56"


@pytest.mark.asyncio
async def test_import_upserts_schueler_klasse_historie_for_aktuelles_schuljahr(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-hist";"Name";"Vor";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-hist"))).scalar_one()
    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
        )
    ).scalar_one()
    assert historie.schuljahr_id == schuljahr.id
    assert historie.klasse_id == schueler.klasse_id


@pytest.mark.asyncio
async def test_import_updates_existing_historie_row_on_reimport(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    klasse_alt = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    klasse_neu = Klasse(webuntis_id=2, name="BME12", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-uuid-hist2", vorname="A", nachname="B", klasse_id=klasse_alt.id)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse_alt.id))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-hist2";"B";"A";"";"BME12";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
        )
    ).scalar_one()
    assert historie.klasse_id == klasse_neu.id


@pytest.mark.asyncio
async def test_import_skips_historie_write_when_no_aktuelles_schuljahr(db_session, tmp_path):
    """Bootstrap-Edge-Case (in Produktion nicht erreichbar, da import_schueler ausschliesslich
    aus run_sync_once NACH resolve_aktuelles_schuljahr aufgerufen wird, siehe sync_orchestrator.py)
    - import_schueler darf trotzdem nicht crashen, wenn direkt ohne Einstellung aufgerufen."""
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-nohist";"Name";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-nohist"))).scalar_one()
    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
        )
    ).scalar_one_or_none()
    assert historie is None


@pytest.mark.asyncio
async def test_import_leaves_klasse_id_null_for_unknown_klasse(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-2";"Nachname";"Vorname";"";"UNBEKANNT";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-2"))
    assert result.scalar_one().klasse_id is None


@pytest.mark.asyncio
async def test_import_marks_schueler_inactive_after_austrittsdatum(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-3";"Nachname";"Vorname";"";"AME56";"01.01.1990";"26.09.2025";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-3"))
    assert result.scalar_one().aktiv is False


@pytest.mark.asyncio
async def test_import_updates_existing_schueler_by_externe_id(db_session, tmp_path):
    db_session.add(Schueler(externe_id="ext-uuid-4", vorname="Alt", nachname="Name", aktiv=False))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-4";"Name";"Neu";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-4"))
    assert result.scalar_one().vorname == "Neu"


@pytest.mark.asyncio
async def test_import_raises_value_error_on_missing_header_column(db_session, tmp_path):
    header_ohne_idnumber = "login;shortname;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"
    path = tmp_path / "schueler.csv"
    path.write_text(
        "\n".join(
            [
                header_ohne_idnumber,
                '"abcd-0018";"abcd-0018";"Mustermann";"Frank";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        await import_schueler(db_session)


@pytest.mark.asyncio
async def test_import_skips_broken_row_but_keeps_valid_rows(db_session, tmp_path):
    _write_csv(
        tmp_path,
        [
            '"a";"a";"ext-uuid-ok-1";"Nachname1";"Vorname1";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
            # kaputtes Datum in Eintrittsdatum -> _parse_datum wirft ValueError, Zeile wird uebersprungen
            '"b";"b";"ext-uuid-broken";"Nachname2";"Vorname2";"";"AME56";"01.01.1990";"";"NICHT-EIN-DATUM";"ja"',
            '"c";"c";"ext-uuid-ok-2";"Nachname3";"Vorname3";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
        ],
    )

    await import_schueler(db_session)

    result_ok_1 = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-ok-1"))
    assert result_ok_1.scalar_one_or_none() is not None

    result_ok_2 = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-ok-2"))
    assert result_ok_2.scalar_one_or_none() is not None

    result_broken = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-broken"))
    assert result_broken.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_import_raises_os_error_on_invalid_encoding(db_session, tmp_path):
    path = tmp_path / "schueler.csv"
    # Latin-1-kodierter Umlaut (0xFC = 'ü'), der als UTF-8 nicht dekodierbar ist.
    zeilen = [
        HEADER.encode("utf-8"),
        b'"x";"x";"ext-uuid-bad-encoding";"M\xfcller";"Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
    ]
    path.write_bytes(b"\n".join(zeilen) + b"\n")

    with pytest.raises(OSError):
        await import_schueler(db_session)


@pytest.mark.asyncio
async def test_import_skips_reprocessing_when_file_unchanged(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-5";"Nachname";"Vorname";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)
    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-5"))
    schueler = result.scalar_one()
    schueler.vorname = "ManuellGeaendert"
    await db_session.commit()

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-5"))
    assert result.scalar_one().vorname == "ManuellGeaendert"
```

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_asv_csv_import.py -v`
Expected: FAIL — die neuen Historie-Tests scheitern (`scalar_one()` findet keine Zeile), da `import_schueler` `schueler_klasse_historie` noch nicht schreibt. `test_import_creates_schueler_with_matching_klasse` schlägt zusätzlich fehl, weil `klasse_id_by_name` noch unscoped ist — an dieser Stelle (vor Step 3) sollte dieser Test noch zufällig passen (unscoped findet die einzige `Klasse`-Zeile auch), das ist erwartbar.

- [x] **Step 3: `import_schueler` erweitern**

In `backend/app/services/asv_csv_import.py`, füge den Import hinzu:

```python
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

Ändere:

```python
    klasse_id_by_name = dict((await db.execute(select(Klasse.name, Klasse.id))).all())
    existing = (await db.execute(select(Schueler))).scalars().all()
    by_externe_id = {schueler.externe_id: schueler for schueler in existing}
```

zu:

```python
    klasse_id_by_name = dict(
        (
            await db.execute(
                select(Klasse.name, Klasse.id).where(Klasse.schuljahr_id == einstellung.aktuelles_schuljahr_id)
            )
        ).all()
    )
    existing = (await db.execute(select(Schueler))).scalars().all()
    by_externe_id = {schueler.externe_id: schueler for schueler in existing}

    historie_by_schueler_id: dict[int, SchuelerKlasseHistorie] = {}
    if einstellung.aktuelles_schuljahr_id is not None:
        historie_rows = (
            await db.execute(
                select(SchuelerKlasseHistorie).where(
                    SchuelerKlasseHistorie.schuljahr_id == einstellung.aktuelles_schuljahr_id
                )
            )
        ).scalars().all()
        historie_by_schueler_id = {h.schueler_id: h for h in historie_rows}
```

Ändere im Zeilen-Loop:

```python
                    schueler = by_externe_id.get(externe_id)
                    if schueler is None:
                        schueler = Schueler(externe_id=externe_id)
                        db.add(schueler)
                        by_externe_id[externe_id] = schueler

                    schueler.vorname = row[settings.asv_csv_column_vorname]
                    schueler.nachname = row[settings.asv_csv_column_nachname]
                    schueler.klasse_id = klasse_id
                    schueler.aktiv = bool(
                        eintrittsdatum is not None
                        and eintrittsdatum <= heute
                        and (austrittsdatum is None or austrittsdatum >= heute)
                    )
                    schueler.klassenzuordnung_aktualisiert_am = datetime.now(timezone.utc)
```

zu:

```python
                    schueler = by_externe_id.get(externe_id)
                    if schueler is None:
                        schueler = Schueler(externe_id=externe_id)
                        db.add(schueler)
                        by_externe_id[externe_id] = schueler
                        # neue schueler.id wird gleich fuer schueler_klasse_historie benoetigt
                        await db.flush()

                    schueler.vorname = row[settings.asv_csv_column_vorname]
                    schueler.nachname = row[settings.asv_csv_column_nachname]
                    schueler.klasse_id = klasse_id
                    schueler.aktiv = bool(
                        eintrittsdatum is not None
                        and eintrittsdatum <= heute
                        and (austrittsdatum is None or austrittsdatum >= heute)
                    )
                    schueler.klassenzuordnung_aktualisiert_am = datetime.now(timezone.utc)

                    if einstellung.aktuelles_schuljahr_id is not None:
                        historie = historie_by_schueler_id.get(schueler.id)
                        if historie is None:
                            historie = SchuelerKlasseHistorie(
                                schueler_id=schueler.id,
                                schuljahr_id=einstellung.aktuelles_schuljahr_id,
                                klasse_id=klasse_id,
                            )
                            db.add(historie)
                            historie_by_schueler_id[schueler.id] = historie
                        else:
                            historie.klasse_id = klasse_id
```

Ergänze im Docstring von `import_schueler` einen Hinweis, dass zusätzlich zu `schueler.klasse_id` ein `schueler_klasse_historie`-Snapshot für das aktuelle Schuljahr gepflegt wird (siehe Design-Dok).

**Abweichung von der obigen Snippet-Reihenfolge:** Das `await db.flush()` für neue `Schueler`-Zeilen darf nicht direkt nach `Schueler(externe_id=externe_id)` stehen (wie oben skizziert), weil `vorname`/`nachname` NOT-NULL-Spalten ohne Default sind und zu diesem Zeitpunkt noch nicht gesetzt sind — das verletzt den NOT-NULL-Constraint. Der Flush wurde stattdessen hinter das Setzen von `vorname`/`nachname`/`klasse_id`/`aktiv`/`klassenzuordnung_aktualisiert_am` verschoben (nur ausgeführt, wenn `schueler.id is None`), unmittelbar vor dem Historie-Block, der `schueler.id` benötigt.

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_asv_csv_import.py -v`
Expected: alle Tests PASS.

- [x] **Step 5: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS (nach Task 2's Sweep + Task 3/4/6 sind jetzt alle `Klasse`-Konstruktoraufrufe der gesamten Suite gültig).

- [x] **Step 6: Commit**

```bash
git add backend/app/services/asv_csv_import.py backend/tests/test_asv_csv_import.py
git commit -m "feat: snapshot schueler_klasse_historie on every ASV-CSV import"
```

---

## Task 7: Rollover-Erkennung — Bulk-Snapshot für ALLE Schüler

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py`
- Modify: `backend/tests/test_sync_orchestrator.py`

**Interfaces:**
- Produces: `async def _snapshot_klassenzugehoerigkeit_bei_rollover(db: AsyncSession, neues_schuljahr_id: int) -> None`, aufgerufen aus `_run_sync_once_impl`, sobald `einstellung.aktuelles_schuljahr_id` sich gegenüber dem vorherigen Wert ändert (und vorher nicht `None` war — der allererste Sync ist kein "Wechsel").

- [x] **Step 1: Fehlschlagende Tests schreiben**

Füge in `backend/tests/test_sync_orchestrator.py` folgende Imports hinzu (nach den bestehenden):

```python
from app.models.klasse import Klasse
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

Füge folgende Tests an (nach den bestehenden `resolve_aktuelles_schuljahr`-Tests):

```python
@pytest.mark.asyncio
async def test_snapshot_klassenzugehoerigkeit_bei_rollover_covers_all_schueler_including_inactive(db_session):
    schuljahr_neu = Schuljahr(id=29, name="2026/2027", start_datum=date(2026, 9, 14), end_datum=date(2027, 7, 30))
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=28)
    schuljahr_alt = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse])
    await db_session.flush()
    schueler_aktiv = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    schueler_inaktiv = Schueler(externe_id="ext-2", vorname="B", nachname="B", klasse_id=klasse.id, aktiv=False)
    schueler_ohne_klasse = Schueler(externe_id="ext-3", vorname="C", nachname="C", klasse_id=None, aktiv=True)
    db_session.add_all([schueler_aktiv, schueler_inaktiv, schueler_ohne_klasse])
    await db_session.commit()

    await sync_orchestrator._snapshot_klassenzugehoerigkeit_bei_rollover(db_session, neues_schuljahr_id=29)

    result = await db_session.execute(
        select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schuljahr_id == 29)
    )
    by_schueler_id = {h.schueler_id: h for h in result.scalars().all()}
    assert by_schueler_id[schueler_aktiv.id].klasse_id == klasse.id
    assert by_schueler_id[schueler_inaktiv.id].klasse_id == klasse.id  # auch inaktive Schueler
    assert by_schueler_id[schueler_ohne_klasse.id].klasse_id is None


@pytest.mark.asyncio
async def test_snapshot_klassenzugehoerigkeit_bei_rollover_does_not_overwrite_existing_row(db_session):
    """Falls fuer das neue Schuljahr bereits eine Zeile existiert (z.B. weil import_schueler im
    selben Sync-Lauf zufaellig vorher gelaufen ist), darf der Rollover-Snapshot sie nicht
    ueberschreiben."""
    schuljahr_neu = Schuljahr(id=29, name="2026/2027", start_datum=date(2026, 9, 14), end_datum=date(2027, 7, 30))
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=28)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=29)
    schuljahr_alt = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse_alt, klasse_neu])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_alt.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=29, klasse_id=klasse_neu.id))
    await db_session.commit()

    await sync_orchestrator._snapshot_klassenzugehoerigkeit_bei_rollover(db_session, neues_schuljahr_id=29)

    historie = (
        await db_session.execute(
            select(SchuelerKlasseHistorie).where(
                SchuelerKlasseHistorie.schueler_id == schueler.id, SchuelerKlasseHistorie.schuljahr_id == 29
            )
        )
    ).scalar_one()
    assert historie.klasse_id == klasse_neu.id  # unveraendert, nicht auf klasse_alt zurueckgesetzt


@pytest.mark.asyncio
async def test_run_full_sync_triggers_rollover_snapshot_only_on_real_change(db_session, monkeypatch):
    """End-to-End: beim allerersten Sync (aktuelles_schuljahr_id vorher None) und bei einem
    Sync-Lauf ohne Schuljahreswechsel darf kein Rollover-Snapshot geschrieben werden; nur wenn
    sich aktuelles_schuljahr_id tatsaechlich AENDERT."""
    aufgerufen_mit: list[int] = []
    monkeypatch.setattr(
        sync_orchestrator,
        "_snapshot_klassenzugehoerigkeit_bei_rollover",
        AsyncMock(side_effect=lambda db, neues_schuljahr_id: aufgerufen_mit.append(neues_schuljahr_id)),
    )

    # Erster Sync-Lauf: aktuelles_schuljahr_id vorher None -> kein Rollover.
    await sync_orchestrator.run_full_sync(async_session_factory)
    assert aufgerufen_mit == []

    # Zweiter Sync-Lauf mit demselben Schuljahr (id 28 laut _FakeWebUntisClient) -> weiterhin kein Rollover.
    await sync_orchestrator.run_full_sync(async_session_factory)
    assert aufgerufen_mit == []


@pytest.mark.asyncio
async def test_run_full_sync_triggers_rollover_snapshot_when_schuljahr_changes(db_session, monkeypatch):
    aufgerufen_mit: list[int] = []
    monkeypatch.setattr(
        sync_orchestrator,
        "_snapshot_klassenzugehoerigkeit_bei_rollover",
        AsyncMock(side_effect=lambda db, neues_schuljahr_id: aufgerufen_mit.append(neues_schuljahr_id)),
    )
    db_session.add(Einstellung(aktuelles_schuljahr_id=27))  # simuliert vorherigen Sync mit anderem Schuljahr
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)  # _FakeWebUntisClient liefert id 28

    assert aufgerufen_mit == [28]
```

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py -k snapshot_klassenzugehoerigkeit -v`
Expected: FAIL — `sync_orchestrator._snapshot_klassenzugehoerigkeit_bei_rollover` existiert noch nicht (`AttributeError`).

- [x] **Step 3: Funktion implementieren und verdrahten**

In `backend/app/services/sync_orchestrator.py`, füge den Import hinzu:

```python
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

Füge die neue Funktion ein (nach `_juengstes_bereits_gestartetes_schuljahr`, vor `resolve_aktuelles_schuljahr`):

```python
async def _snapshot_klassenzugehoerigkeit_bei_rollover(db: AsyncSession, neues_schuljahr_id: int) -> None:
    """Bei einem echten Schuljahreswechsel wird fuer ALLE Schueler (auch inaktive/ausgeschiedene)
    einmalig ein Snapshot ihrer zu diesem Zeitpunkt noch aktuellen schueler.klasse_id (i.d.R. noch
    die Klasse des alten Schuljahres, da import_schueler in diesem Sync-Lauf erst DANACH laeuft)
    fuers neue Schuljahr geschrieben, siehe
    docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md. Ohne diesen Snapshot
    wuerden Schueler, die ausscheiden BEVOR sie je ein ASV-CSV-Update unter dem neuen Schuljahr
    bekommen (import_schueler deckt nur noch in der CSV gelistete Schueler ab), permanent ohne
    Historie-Eintrag fuer das neue Schuljahr bleiben. Bereits vorhandene Zeilen werden nicht
    ueberschrieben - der regulaere ASV-CSV-Import-Pfad, der im selben Sync-Lauf direkt danach
    laeuft, uebernimmt ab dann die laufende Pflege dieser Zeile fuer aktuell eingeschriebene
    Schueler."""
    bereits_erfasst = set(
        (
            await db.execute(
                select(SchuelerKlasseHistorie.schueler_id).where(
                    SchuelerKlasseHistorie.schuljahr_id == neues_schuljahr_id
                )
            )
        ).scalars().all()
    )
    alle_schueler = (await db.execute(select(Schueler.id, Schueler.klasse_id))).all()
    for schueler_id, klasse_id in alle_schueler:
        if schueler_id in bereits_erfasst:
            continue
        db.add(SchuelerKlasseHistorie(schueler_id=schueler_id, schuljahr_id=neues_schuljahr_id, klasse_id=klasse_id))
    await db.flush()
```

Ändere in `_run_sync_once_impl`:

```python
        aktuelles_schuljahr = await resolve_aktuelles_schuljahr(client, db)
        einstellung.aktuelles_schuljahr_id = aktuelles_schuljahr.id
        if aktuelles_schuljahr.start_datum != einstellung.schuljahr_start_cache:
            einstellung.schuljahr_start_cache = aktuelles_schuljahr.start_datum

        await sync_abteilungen(client, db)
```

zu:

```python
        aktuelles_schuljahr = await resolve_aktuelles_schuljahr(client, db)
        vorheriges_schuljahr_id = einstellung.aktuelles_schuljahr_id
        einstellung.aktuelles_schuljahr_id = aktuelles_schuljahr.id
        if aktuelles_schuljahr.start_datum != einstellung.schuljahr_start_cache:
            einstellung.schuljahr_start_cache = aktuelles_schuljahr.start_datum

        ist_rollover = vorheriges_schuljahr_id is not None and vorheriges_schuljahr_id != aktuelles_schuljahr.id
        if ist_rollover:
            await _snapshot_klassenzugehoerigkeit_bei_rollover(db, aktuelles_schuljahr.id)

        await sync_abteilungen(client, db)
```

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py -v`
Expected: alle Tests PASS.

- [x] **Step 5: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py
git commit -m "feat: snapshot klasse assignment for all students when a real schuljahr rollover happens"
```

---

## Task 8: `GET /students` — Klasse aus Historie im Historie-Modus

**Files:**
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/api/routes/students.py`
- Test: `backend/tests/test_student_query.py`
- Test: `backend/tests/test_api_students.py`

**Interfaces:**
- Produces: `student_query.load_historische_klasse_map(db, schueler_ids, schuljahr_id) -> dict[int, Klasse | None]`.

- [x] **Step 1: Fehlschlagenden Service-Test schreiben**

Füge in `backend/tests/test_student_query.py` (am Ende) hinzu (Imports `Schuljahr`, `SchuelerKlasseHistorie` ergänzen):

```python
@pytest.mark.asyncio
async def test_load_historische_klasse_map_reads_from_historie_not_live_klasse_id(db_session, schuljahr):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([schuljahr_alt, klasse_alt, klasse_neu])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_neu.id)
    schueler_ohne_snapshot = Schueler(externe_id="ext-2", vorname="C", nachname="D", klasse_id=klasse_neu.id)
    db_session.add_all([schueler, schueler_ohne_snapshot])
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id))
    await db_session.commit()

    result = await student_query.load_historische_klasse_map(
        db_session, [schueler.id, schueler_ohne_snapshot.id], schuljahr_alt.id
    )

    assert result[schueler.id].name == "10a"  # aus der Historie, NICHT die live klasse_neu
    assert result[schueler_ohne_snapshot.id] is None  # keine Historie-Zeile -> unbekannt


@pytest.mark.asyncio
async def test_load_historische_klasse_map_none_when_historie_klasse_id_is_null(db_session, schuljahr):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    await db_session.commit()

    result = await student_query.load_historische_klasse_map(db_session, [schueler.id], schuljahr.id)

    assert result[schueler.id] is None
```

(Ergänze am Dateianfang: `from app.models.schueler_klasse_historie import SchuelerKlasseHistorie`, `from app.models.schuljahr import Schuljahr` — falls noch nicht vorhanden.)

- [x] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_student_query.py -k historische_klasse_map -v`
Expected: FAIL — `load_historische_klasse_map` existiert nicht.

- [x] **Step 3: `load_historische_klasse_map` implementieren**

In `backend/app/services/student_query.py`, füge den Import hinzu:

```python
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

Füge die Funktion ein (nach `load_klasse_map`):

```python
async def load_historische_klasse_map(
    db: AsyncSession, schueler_ids: list[int], schuljahr_id: int
) -> dict[int, Klasse | None]:
    """Klassenzugehoerigkeit je Schueler fuer ein vergangenes Schuljahr, aus
    schueler_klasse_historie statt der live schueler.klasse_id/aktuellen klasse-Tabelle
    (Historie-Modus, siehe docs/superpowers/specs/2026-09-18-schuljahr-historisierung-design.md).
    Fehlt eine Historie-Zeile (Schuljahre vor Einfuehrung dieses Features) oder ist ihr klasse_id
    NULL, liefert das Ergebnis fuer diesen Schueler None (Frontend zeigt 'unbekannt') statt eines
    Fallbacks auf die aktuelle Klasse (bewusste Nutzer-Entscheidung, Design-Dok 'Nicht-Ziele')."""
    result: dict[int, Klasse | None] = {sid: None for sid in schueler_ids}
    if not schueler_ids:
        return result

    rows = (
        await db.execute(
            select(SchuelerKlasseHistorie.schueler_id, Klasse)
            .outerjoin(Klasse, Klasse.id == SchuelerKlasseHistorie.klasse_id)
            .where(
                SchuelerKlasseHistorie.schueler_id.in_(schueler_ids),
                SchuelerKlasseHistorie.schuljahr_id == schuljahr_id,
            )
        )
    ).all()
    for schueler_id, klasse in rows:
        result[schueler_id] = klasse
    return result
```

- [x] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_student_query.py -k historische_klasse_map -v`
Expected: PASS.

- [x] **Step 5: Fehlschlagenden HTTP-Test schreiben**

Füge in `backend/tests/test_api_students.py` hinzu (Import `SchuelerKlasseHistorie` ergänzen):

```python
@pytest.mark.asyncio
async def test_get_students_history_mode_shows_klasse_from_historie_not_live_klasse_id(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse_alt, klasse_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await _seed_klassenlehrkraft(db_session, [klasse_neu.id])
    # Schueler ist aktuell (live) in klasse_neu, war im alten Schuljahr aber in klasse_alt.
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_neu.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students?schuljahr_id={schuljahr_alt.id}", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == schueler.id)
    assert item["klasse"] == {"id": klasse_alt.id, "name": "10a"}
```

- [x] **Step 6: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -k shows_klasse_from_historie -v`
Expected: FAIL — die Route liefert weiterhin `klasse_neu` (live `schueler.klasse_id`).

- [x] **Step 7: Route anpassen**

In `backend/app/api/routes/students.py`, in `get_students`, ändere den Historie-Zweig:

```python
    schueler_ids = [schueler.id for schueler in schueler_list]
    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)
    rohzahlen = await student_query.load_schueler_rohzahlen(db, schueler_ids, effektiv_von, effektiv_bis)

    if ist_historie:
        items = [
            StudentOverviewOut(
                id=schueler.id,
                vorname=schueler.vorname,
                nachname=schueler.nachname,
                klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
                fehltage=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehltage"]),
                fehlstunden=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehlstunden"]),
                klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
            )
            for schueler in schueler_list
        ]
        return StudentListOut(items=items, total=total, limit=limit, offset=offset)
```

zu:

```python
    schueler_ids = [schueler.id for schueler in schueler_list]
    rohzahlen = await student_query.load_schueler_rohzahlen(db, schueler_ids, effektiv_von, effektiv_bis)

    if ist_historie:
        klasse_map_historie = await student_query.load_historische_klasse_map(db, schueler_ids, schuljahr_id)
        items = [
            StudentOverviewOut(
                id=schueler.id,
                vorname=schueler.vorname,
                nachname=schueler.nachname,
                klasse=klasse_map_historie[schueler.id],
                fehltage=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehltage"]),
                fehlstunden=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehlstunden"]),
                klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
            )
            for schueler in schueler_list
        ]
        return StudentListOut(items=items, total=total, limit=limit, offset=offset)

    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)
```

(Der ursprüngliche `klasse_ids`/`klasse_map`-Aufbau wird also hinter den `if ist_historie:`-Zweig verschoben, da er im Normalmodus weiterhin benötigt wird, im Historie-Modus aber durch `load_historische_klasse_map` ersetzt ist. Der Rest der Funktion — Normalmodus-Zweig mit `extras`/`regel_typ_map`/`items` — bleibt unverändert und nutzt weiterhin `klasse_map`.)

- [x] **Step 8: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py tests/test_student_query.py -v`
Expected: alle Tests PASS.

- [x] **Step 9: Commit**

```bash
git add backend/app/services/student_query.py backend/app/api/routes/students.py \
  backend/tests/test_student_query.py backend/tests/test_api_students.py
git commit -m "feat: resolve klasse from schueler_klasse_historie in GET /students history mode"
```

---

## Task 9: `GET /students/{id}` — Klasse aus Historie im Historie-Modus

**Files:**
- Modify: `backend/app/api/routes/students.py`
- Test: `backend/tests/test_api_students.py`

- [ ] **Step 1: Fehlschlagende Tests schreiben**

Füge in `backend/tests/test_api_students.py` hinzu:

```python
@pytest.mark.asyncio
async def test_get_student_detail_history_mode_shows_klasse_from_historie(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse_alt, klasse_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await _seed_klassenlehrkraft(db_session, [klasse_neu.id])
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_neu.id)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}?schuljahr_id={schuljahr_alt.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    assert response.json()["klasse"] == {"id": klasse_alt.id, "name": "10a"}


@pytest.mark.asyncio
async def test_get_student_detail_history_mode_klasse_is_none_without_historie_snapshot(db_session):
    """Schuljahre vor Einfuehrung dieses Features haben keine schueler_klasse_historie-Zeilen -
    die API liefert dann explizit klasse=None statt eines Fallbacks auf die aktuelle Klasse
    (Nutzer-Entscheidung, siehe Design-Dok 'Nicht-Ziele')."""
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await _seed_klassenlehrkraft(db_session, [klasse_neu.id])
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_neu.id)
    db_session.add(schueler)
    await db_session.commit()
    # keine SchuelerKlasseHistorie-Zeile fuer schuljahr_alt angelegt

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}?schuljahr_id={schuljahr_alt.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    assert response.json()["klasse"] is None
```

- [ ] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -k shows_klasse_from_historie -v`
Expected: FAIL — `get_student_detail` liefert weiterhin die live `klasse_neu` (bzw. die zweite Test-Erwartung stimmt zufällig, weil aktuell keine Historie gelesen wird — der erste Test ist der maßgebliche Fehlschlag).

- [ ] **Step 3: Route anpassen**

In `backend/app/api/routes/students.py`, in `get_student_detail`, ändere:

```python
    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)
```

zu:

```python
    if ist_historie:
        klasse_map_historie = await student_query.load_historische_klasse_map(db, [schueler.id], schuljahr_id)
        klasse = klasse_map_historie[schueler.id]
    else:
        klasse = None
        if schueler.klasse_id is not None:
            klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
            klasse = klasse_map.get(schueler.klasse_id)
```

- [ ] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -v`
Expected: alle Tests PASS.

- [ ] **Step 5: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/students.py backend/tests/test_api_students.py
git commit -m "feat: resolve klasse from schueler_klasse_historie in GET /students/{id} history mode"
```

---

## Task 10: `GET /dashboard/nav-options` — `schuljahr_id`-Param + jahresgebundene Klassenliste

**Files:**
- Modify: `backend/app/api/routes/dashboard.py`
- Modify: `backend/app/services/dashboard_query.py`
- Test: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- `get_nav_options(db, nutzer, schuljahr_id: int | None = None)` — neuer optionaler Parameter. Ohne Angabe (oder mit dem aktuellen Schuljahr) unverändertes Verhalten, aber jetzt implizit auf `Klasse.schuljahr_id == aktuelles_schuljahr_id` gescopet. Mit einer historischen `schuljahr_id` wird die `klassen`-Liste auf `Klasse.schuljahr_id == schuljahr_id` gescopet.

- [ ] **Step 1: Fehlschlagende Tests schreiben**

Füge in `backend/tests/test_dashboard_query.py` hinzu:

```python
@pytest.mark.asyncio
async def test_get_nav_options_klassen_scoped_to_aktuelles_schuljahr_by_default(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse_alt, klasse_neu, nutzer])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert [k.id for k in result.klassen] == [klasse_neu.id]


@pytest.mark.asyncio
async def test_get_nav_options_klassen_scoped_to_requested_historical_schuljahr(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add_all([schuljahr_alt, schuljahr_neu, klasse_alt, klasse_neu, nutzer])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer, schuljahr_id=schuljahr_alt.id)

    assert [k.id for k in result.klassen] == [klasse_alt.id]
```

- [ ] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -k klassen_scoped -v`
Expected: FAIL — `get_nav_options` liefert beide Klassen (bzw. akzeptiert `schuljahr_id` noch nicht als Keyword-Argument).

- [ ] **Step 3: `get_nav_options` anpassen**

In `backend/app/services/dashboard_query.py`, ändere die Funktionssignatur und den `klassen`-Aufbau:

```python
async def get_nav_options(db: AsyncSession, nutzer: Nutzer, schuljahr_id: int | None = None) -> NavOptionsOut:
    bereich_scope = await resolve_bereich_scope(db, nutzer)
    klasse_scope = await resolve_scope(db, nutzer)

    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    aktuelles_schuljahr_id = einstellung.aktuelles_schuljahr_id if einstellung else None
    effektive_schuljahr_id = schuljahr_id if schuljahr_id is not None else aktuelles_schuljahr_id

    if bereich_scope is not None and not bereich_scope:
        bereiche = []
    else:
        query = select(Bereich).where(Bereich.ausgeblendet.is_(False)).order_by(Bereich.name)
        if bereich_scope is not None:
            query = query.where(Bereich.id.in_(bereich_scope))
        bereiche = (await db.execute(query)).scalars().all()

    if klasse_scope is not None and not klasse_scope:
        klassen = []
    else:
        query = select(Klasse).order_by(Klasse.name)
        if klasse_scope is not None:
            query = query.where(Klasse.id.in_(klasse_scope))
        if effektive_schuljahr_id is not None:
            query = query.where(Klasse.schuljahr_id == effektive_schuljahr_id)
        klassen = (await db.execute(query)).scalars().all()

    klasse_bereich_map = dict(
        (await db.execute(select(bereich_klasse.c.klasse_id, bereich_klasse.c.bereich_id))).all()
    )

    schuljahre_result = await db.execute(select(Schuljahr).order_by(Schuljahr.start_datum.desc()))
    schuljahre = [
        NavSchuljahrOut(id=s.id, name=s.name, start_datum=s.start_datum, end_datum=s.end_datum)
        for s in schuljahre_result.scalars().all()
    ]

    return NavOptionsOut(
        bereiche=[NavBereichOut(id=b.id, name=b.name) for b in bereiche],
        klassen=[
            NavKlasseOut(id=k.id, name=k.name, bereich_id=klasse_bereich_map.get(k.id)) for k in klassen
        ],
        rolle=nutzer.rolle,
        schuljahre=schuljahre,
        aktuelles_schuljahr_id=aktuelles_schuljahr_id,
    )
```

(Kernänderung: `einstellung`/`aktuelles_schuljahr_id`/`effektive_schuljahr_id` werden jetzt VOR dem `klassen`-Query berechnet statt danach, und der `klassen`-Query bekommt den zusätzlichen `Klasse.schuljahr_id`-Filter. Der restliche Funktionskörper — `bereiche`, `klasse_bereich_map`, `schuljahre`, Rückgabe — bleibt unverändert.)

In `backend/app/api/routes/dashboard.py`, ändere die Route:

```python
@router.get("/nav-options")
async def get_nav_options(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: int | None = None,
) -> NavOptionsOut:
    return await dashboard_query.get_nav_options(db, nutzer, schuljahr_id=schuljahr_id)
```

- [ ] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py tests/test_api_dashboard.py -v`
Expected: alle Tests PASS — insbesondere bleiben die bestehenden `test_get_nav_options_for_*`-Tests grün, da sie keine `Einstellung`/`schuljahr_id` setzen und `effektive_schuljahr_id` dann `None` bleibt (Filter wird übersprungen, identisch zum bisherigen Verhalten).

- [ ] **Step 5: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/dashboard.py backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "feat: scope GET /dashboard/nav-options klassen list to the (requested or current) schuljahr"
```

---

## Task 11: Vollständiger Testlauf + Frontend-Verifikation

**Files:**
- Keine Code-Änderungen erwartet (Verifikationstask) — außer eventuell kleine Anpassungen, falls die Verifikation etwas findet.

- [ ] **Step 1: Vollen Backend-Testlauf**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [ ] **Step 2: Frontend-Verifikation (kein Code-Change erwartet)**

Bereits während der Planerstellung geprüft:
- `frontend/src/pages/StudentList/StudentList.tsx:166`: `<td>{student.klasse?.name ?? "—"}</td>`
- `frontend/src/pages/StudentDetail/StudentDetail.tsx:44`: `<p>{student.klasse?.name ?? "—"}</p>`

Beide Stellen behandeln `klasse === null` bereits null-safe (Fallback `"—"`) — kein neuer UI-Zustand nötig, deckt sich mit der bestehenden Behandlung schon heute klassenloser Schüler. Als Bestätigung: `cd frontend && npm test` einmal durchlaufen lassen und sicherstellen, dass nichts an `Fehlzeit`/`StudentOverviewOut`/`StudentDetailOut`-Typen in `frontend/src/api/types.ts` bricht (dieser Plan ändert keine Response-Felder, nur deren Inhalt im Historie-Modus).

Run: `cd frontend && npm test`
Expected: alle Tests PASS (keine Anpassung nötig, sofern die Backend-Response-Struktur für `klasse` unverändert `{id, name} | null` bleibt — das ist der Fall, siehe `KlasseOut`).

- [ ] **Step 3: Manuelle Verifikation im Dev-Stack (optional, empfohlen)**

- Sync-Lauf auslösen (`POST /admin/sync-settings/trigger` o.ä.), prüfen dass `klasse`-Zeilen jetzt `schuljahr_id` tragen: `docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "SELECT webuntis_id, name, schuljahr_id FROM klasse LIMIT 10;"`.
- `GET /students?schuljahr_id=<ein_altes_jahr>` gegen den Dev-Stack aufrufen (mit gültigem WordPress-Proxy-Header) und prüfen, dass `klasse` entweder eine (mangels Altdaten wahrscheinlich `null`) Historie-Zuordnung oder explizit `null` zeigt, nie einen Fallback auf die aktuelle Klasse.

- [ ] **Step 4: Commit**

Falls Step 1/2 keine Änderungen erfordern, entfällt dieser Commit. Falls doch etwas gefixt werden musste:

```bash
git add -A
git commit -m "fix: address issues found during full-suite/frontend verification"
```

---

## Task 12: Dokumentation

**Files:**
- Modify: `ROADMAP.md`
- Modify: `TECH-SPEC.md`
- Modify: `SPECS.md`

- [ ] **Step 1: TECH-SPEC.md aktualisieren**

Ergänze `klasse` im §2-Datenmodell um `schuljahr_id` (FK `schuljahr.id`, NOT NULL, Teil des Unique-Constraints `(webuntis_id, schuljahr_id)`). Füge die neue Tabelle `schueler_klasse_historie` hinzu (`id`, `schueler_id`, `schuljahr_id`, `klasse_id` nullable, unique `(schueler_id, schuljahr_id)` — "Ein-Zeile-pro-Schüler-pro-Jahr-Snapshot, geschrieben vom ASV-CSV-Import und beim Rollover"). Aktualisiere §1.3a's Beschreibung von `resolve_aktuelles_schuljahr`: die zuerst geprüfte Quelle ist jetzt eine gecachte `Schuljahr`-Zeile, deren Datumsbereich das heutige Kalenderdatum abdeckt, `getCurrentSchoolyear` ist nur noch Fallback für die echte Übergangslücke. Ergänze §3 um den `schuljahr_id`-Query-Param auf `GET /dashboard/nav-options`.

- [ ] **Step 2: SPECS.md aktualisieren**

Ergänze bei der Beschreibung von Schülerliste/-Detail (§4/§7) einen Absatz: im Historie-Modus (vergangenes Schuljahr) wird die angezeigte Klasse aus dem zu diesem Schuljahr gehörenden Snapshot gelesen; fehlt dieser (Schuljahre vor Einführung dieses Features), zeigt die Ansicht explizit "unbekannt" statt der aktuellen Klasse.

- [ ] **Step 3: ROADMAP.md aktualisieren**

Trage den Eintrag "Schuljahr-Historisierung (Klassenzugehörigkeit) & Rollover-Fix" als **Plan 14** (oder die nächste freie Nummer, in der Datei nachschauen) unter "Abgeschlossen" ein, mit Link auf `docs/superpowers/plans/2026-09-18-schuljahr-historisierung.md`, und einem Hinweis, dass Task 4 (`sync_bereiche`-Scoping) eine während der Planung entdeckte, vom ursprünglichen Design-Dok nicht vorgesehene notwendige Korrektur war.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md SPECS.md TECH-SPEC.md
git commit -m "docs: sync SPECS.md, TECH-SPEC.md and ROADMAP.md with the schuljahr-historisierung plan"
```
