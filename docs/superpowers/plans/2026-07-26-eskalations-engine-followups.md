# Eskalations-Engine Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tasks 1 and 2 both modify `backend/app/services/eskalations_pruefung.py` and MUST be executed in order (Task 2 builds directly on Task 1's version of the file) — do not parallelize them.

**Goal:** Close four non-blocking follow-ups flagged by the final whole-branch review of the Eskalations-Engine plan (merged `de1cbdd`): reduce per-sync-run DB round-trips in `pruefe_schwellwerte`, add a missing DB index on `benachrichtigung`, lock in three already-correct-but-untested behaviors with regression tests, and stop per-student log spam when `schuljahr_start_cache` is unset.

**Architecture:** All four items are surgical, behavior-preserving changes to the existing Eskalations-Engine service layer (`backend/app/services/eskalations_pruefung.py`) and its test suite — no new models, no new endpoints, no schema redesign. Task 3 is the only one touching the DB schema (two new indexes on the existing `benachrichtigung` table).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, PostgreSQL (asyncpg), Alembic, pytest + pytest-asyncio against real Postgres (`tests/conftest.py`'s autouse `_reset_database` fixture — no DB mocking).

**Reference:** Original plan `docs/superpowers/plans/2026-07-26-eskalations-engine.md`; design doc `docs/superpowers/specs/2026-07-26-eskalations-engine-design.md`; memory `eskalations-engine-plan3` for the rule-scope, keying, and FK-ondelete decisions this code depends on.

## Global Constraints

- Commit messages in English (user convention).
- Log messages, docstrings, and comments in this project are German — keep that convention.
- No SQLAlchemy `relationship()` declarations — explicit FK columns + manual `select()` joins only (existing project style).
- Test commands use `docker compose -f backend/docker-compose.yml run --rm backend <cmd>` (per `docs/backend-setup.md`), NOT a persistent named container — the Postgres service (`absenzdash-db`, container name from `backend/docker-compose.yml`) must already be running (`docker compose -f backend/docker-compose.yml up -d postgres`; verify with `docker ps`).
- Migrations: generate with `alembic revision --autogenerate -m "..."`, then inspect the generated file before applying. Tests are **not** migration-dependent (`tests/conftest.py` uses `Base.metadata.create_all`/`drop_all` against the shared test DB, wiped on every test run) — but migrations are still produced for production correctness (project convention).
- **Migration-verification gotcha** (from prior plan, do not skip): the shared test DB's schema is reset by `create_all` on every test, so by the time you run `alembic revision --autogenerate` against it, the diff is already empty (schema already matches via `create_all`, not via the migration chain). Verify any new migration against a disposable **shadow database** instead — never against the shared test DB. Task 3 spells out the exact commands.
- Current Alembic head is `fb5871c3593e` (`fb5871c3593e_set_null_regel_id_fks.py`) — confirm this is still true before generating a new migration (`ls backend/alembic/versions/` and check no file has `down_revision = 'fb5871c3593e'` yet).

---

### Task 1: Cache rule resolution and reuse the counter row (query performance)

**Files:**
- Modify: `backend/app/services/eskalations_pruefung.py` (`get_or_create_zaehlerstand`, `pruefe_schwellwerte`)
- Modify: `backend/tests/test_eskalations_pruefung.py`

**Interfaces:**
- Consumes: existing `resolve_schwellwert_regel(db, klasse_id, typ)`, existing `SchuelerZaehlerstand` model.
- Produces: `get_or_create_zaehlerstand(db, schueler_id, typ, regel_id, bestehender=None)` — new optional keyword `bestehender` (default `None`, fully backward compatible with the two existing external call sites in `backend/app/services/massnahme_service.py` and `backend/tests/test_massnahme_service.py`, which all call it with 4 positional args and get identical behavior).

- [ ] **Step 1: Write failing test — rule resolution cached per (klasse_id, typ)**

Add to `backend/tests/test_eskalations_pruefung.py`. First update the imports at the top of the file:

```python
import datetime
from unittest import mock

import pytest
from sqlalchemy import event, select

from app.core.database import engine
from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
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
from app.services import eskalations_pruefung
from app.services.eskalations_pruefung import pruefe_schwellwerte
```

(This replaces the old `import datetime` / `import pytest` / `from sqlalchemy import select` / final `from app.services.eskalations_pruefung import pruefe_schwellwerte` lines — everything else in the import block is unchanged, just re-listed here for completeness so the diff is unambiguous.)

Then append these two tests at the end of the file:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_regel_once_per_klasse_not_per_schueler(db_session):
    """Regel-Aufloesung ist innerhalb eines Sync-Laufs pro (klasse_id, typ) invariant und soll dort
    nur einmal ausgefuehrt werden, nicht einmal pro Schueler (Performance-Fix)."""
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="C", nachname="D", aktiv=True, klasse_id=klasse.id)
    db_session.add_all([schueler_a, schueler_b])
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    original = eskalations_pruefung.resolve_schwellwert_regel
    aufrufe: list[tuple[int | None, str]] = []

    async def _zaehlender_wrapper(db, klasse_id, typ):
        aufrufe.append((klasse_id, typ))
        return await original(db, klasse_id, typ)

    with mock.patch.object(eskalations_pruefung, "resolve_schwellwert_regel", side_effect=_zaehlender_wrapper):
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)

    assert len(aufrufe) == 2
    assert aufrufe.count((klasse.id, "fehlzeiten")) == 1
    assert aufrufe.count((klasse.id, "klassenbuch")) == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_selects_existing_zaehlerstand_only_once(db_session):
    """get_or_create_zaehlerstand soll die im Fenster-Guard bereits geladene Zeile wiederverwenden statt
    sie erneut zu selektieren (Performance-Fix: vorher 2 SELECTs auf schueler_zaehlerstand pro Schueler)."""
    schueler = await _make_schueler(db_session)
    regel = await _make_fehlzeiten_regel(db_session, schwellenwert=5)
    db_session.add(
        SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", regel_id=regel.id, aktueller_stand=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    select_count = 0

    def _count_zaehlerstand_selects(conn, cursor, statement, parameters, context, executemany):
        nonlocal select_count
        if statement.strip().upper().startswith("SELECT") and "schueler_zaehlerstand" in statement:
            select_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _count_zaehlerstand_selects)
    try:
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _count_zaehlerstand_selects)

    assert select_count == 1
```

- [ ] **Step 2: Run tests, confirm both fail**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q tests/test_eskalations_pruefung.py -k "resolves_regel_once_per_klasse or selects_existing_zaehlerstand_only_once" -v
```

Expected: FAIL — first test with `assert len(aufrufe) == 2` (actual 4), second with `assert select_count == 1` (actual 2).

- [ ] **Step 3: Implement the caching and row-reuse fix**

In `backend/app/services/eskalations_pruefung.py`, replace the `get_or_create_zaehlerstand` function (currently lines 57-72) with:

```python
async def get_or_create_zaehlerstand(
    db: AsyncSession,
    schueler_id: int,
    typ: str,
    regel_id: int,
    bestehender: SchuelerZaehlerstand | None = None,
) -> SchuelerZaehlerstand:
    zaehlerstand = bestehender
    if zaehlerstand is None:
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
```

Then replace the `pruefe_schwellwerte` function (currently lines 188-236) with:

```python
async def pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung) -> None:
    """Kernschleife: fuer jeden aktiven Schueler und Regel-Typ Zaehlerstand neu berechnen (SPECS.md Abschnitt 5)."""
    schueler_result = await db.execute(select(Schueler).where(Schueler.aktiv.is_(True)))
    alle_schueler = schueler_result.scalars().all()

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
                logger.warning(
                    "Kein Fenster-Start ermittelbar fuer Schueler %d, Regel %d (kein schuljahr_start_cache, "
                    "kein letzter_reset_am) - uebersprungen",
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
                await _schreibe_benachrichtigung(db, schueler, regel, neue_stufe_nr, einstellung)
```

(Note: the per-student `logger.warning` call here is intentionally left untouched — Task 2 hoists it.)

- [ ] **Step 4: Run the two new tests, confirm they pass**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q tests/test_eskalations_pruefung.py -k "resolves_regel_once_per_klasse or selects_existing_zaehlerstand_only_once" -v
```

Expected: PASS (2/2).

- [ ] **Step 5: Run the full test suite, confirm no regressions**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q
```

Expected: PASS, all green (this is a pure refactor — no existing test's assertions should change).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eskalations_pruefung.py backend/tests/test_eskalations_pruefung.py
git commit -m "perf: cache rule resolution per class and reuse counter row in pruefe_schwellwerte"
```

---

### Task 2: Hoist the missing-fenster-start log warning (log spam)

**Files:**
- Modify: `backend/app/services/eskalations_pruefung.py` (`pruefe_schwellwerte`)
- Modify: `backend/tests/test_eskalations_pruefung.py`

**Interfaces:**
- Consumes: `pruefe_schwellwerte` as left by Task 1.
- Produces: no change to `pruefe_schwellwerte`'s signature or return behavior — only which/how many log lines are emitted.

- [ ] **Step 1: Write failing test — warning logged once, not per student**

Add `import logging` to the top of `backend/tests/test_eskalations_pruefung.py` (alphabetically after `import datetime`, since `unittest` was added in Task 1 as a `from` import in its own group):

```python
import datetime
import logging
from unittest import mock
```

Append this test:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_logs_missing_schuljahr_start_once_not_per_schueler(db_session, caplog):
    """Fehlender schuljahr_start_cache soll pro Sync-Lauf nur einmal geloggt werden, nicht einmal pro
    Schueler (Log-Spam-Fix: vorher eine Warnzeile pro Schueler ohne eigenen letzter_reset_am)."""
    for i in range(3):
        db_session.add(Schueler(externe_id=f"ext-{i}", vorname="A", nachname="B", aktiv=True))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=None)
    with caplog.at_level(logging.WARNING, logger="app.services.eskalations_pruefung"):
        await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)

    fenster_warnungen = [r for r in caplog.records if "schuljahr_start_cache" in r.getMessage()]
    assert len(fenster_warnungen) == 1
```

- [ ] **Step 2: Run test, confirm it fails**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q tests/test_eskalations_pruefung.py -k logs_missing_schuljahr_start_once -v
```

Expected: FAIL — `assert len(fenster_warnungen) == 1` with actual 3 (one per student).

- [ ] **Step 3: Hoist the warning**

In `backend/app/services/eskalations_pruefung.py`, replace `pruefe_schwellwerte` again (the version from Task 1) with:

```python
async def pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung) -> None:
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
                await _schreibe_benachrichtigung(db, schueler, regel, neue_stufe_nr, einstellung)
```

(The per-student warning branch is kept — reachable only in the currently-impossible-but-defensive case where `schuljahr_start_cache` is set yet `fenster_kandidaten` still ends up empty; harmless dead-code-shaped safety net, cheap to keep, matches the review's explicit ask to preserve a per-student path for the rarer case.)

- [ ] **Step 4: Run the new test, confirm it passes**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q tests/test_eskalations_pruefung.py -k logs_missing_schuljahr_start_once -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite, confirm no regressions**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q
```

Expected: PASS, all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eskalations_pruefung.py backend/tests/test_eskalations_pruefung.py
git commit -m "fix: log missing schuljahr_start_cache once per sync run instead of once per student"
```

---

### Task 3: Add missing indexes on `benachrichtigung.schueler_id`/`regel_id`

**Files:**
- Modify: `backend/app/models/benachrichtigung.py`
- Create: `backend/tests/test_models_benachrichtigung.py` addition (append test)
- Create: Alembic migration

**Interfaces:**
- No Python-callable interface changes — purely a schema addition.

- [ ] **Step 1: Write failing test — indexes exist**

Append to `backend/tests/test_models_benachrichtigung.py` (add `from sqlalchemy import text` to the existing `from sqlalchemy import select` import line, making it `from sqlalchemy import select, text`):

```python
@pytest.mark.asyncio
async def test_benachrichtigung_has_indexes_on_schueler_id_and_regel_id(db_session):
    result = await db_session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'benachrichtigung'")
    )
    indexdefs = [row[0] for row in result.all()]
    assert any("(schueler_id)" in d for d in indexdefs)
    assert any("(regel_id)" in d for d in indexdefs)
```

- [ ] **Step 2: Run test, confirm it fails**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q tests/test_models_benachrichtigung.py -v
```

Expected: FAIL — `assert any("(schueler_id)" in d for d in indexdefs)` is False (only the primary key index exists).

- [ ] **Step 3: Add `index=True` to the model columns**

In `backend/app/models/benachrichtigung.py`, replace the `schueler_id` and `regel_id` column definitions:

```python
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"), index=True)
    regel_id: Mapped[int | None] = mapped_column(
        ForeignKey("schwellwert_regel.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

- [ ] **Step 4: Run test, confirm it passes**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q tests/test_models_benachrichtigung.py -v
```

Expected: PASS (2/2) — `tests/conftest.py`'s `create_all` picks up `index=True` immediately, no migration needed for the test to go green.

- [ ] **Step 5: Run the full test suite, confirm no regressions**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q
```

Expected: PASS, all green.

- [ ] **Step 6: Generate the migration**

```bash
docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add benachrichtigung schueler_id and regel_id indexes"
```

Open the generated file in `backend/alembic/versions/`. Confirm:
- `down_revision = 'fb5871c3593e'`
- `upgrade()` contains two `op.create_index(...)` calls, one for `schueler_id`, one for `regel_id`, on table `'benachrichtigung'`
- `downgrade()` contains the two matching `op.drop_index(...)` calls

- [ ] **Step 7: Verify the migration against a disposable shadow database**

The shared test DB's schema is reset by `create_all` on every test run, so autogenerate against it always shows an empty diff — verify against a throwaway database instead:

```bash
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "CREATE DATABASE absenzdash_shadow;"
docker compose -f backend/docker-compose.yml run --rm -e DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash_shadow backend alembic upgrade head
docker exec absenzdash-db psql -U absenzdash -d absenzdash_shadow -c "\d benachrichtigung"
```

Expected: the `\d benachrichtigung` output's `Indexes:` section lists an index on `schueler_id` and one on `regel_id`, in addition to the primary key.

Confirm autogenerate now sees zero diff against the shadow DB (proves the migration matches the models exactly):

```bash
docker compose -f backend/docker-compose.yml run --rm -e DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash_shadow backend alembic revision --autogenerate -m "shadow_check_noop"
```

Open the newly generated file — `upgrade()`/`downgrade()` bodies should both be `pass` (no diff). Delete this throwaway file (it must never be committed):

```bash
rm backend/alembic/versions/*shadow_check_noop.py
```

Verify downgrade symmetry, then drop the shadow database:

```bash
docker compose -f backend/docker-compose.yml run --rm -e DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash_shadow backend alembic downgrade -1
docker exec absenzdash-db psql -U absenzdash -d absenzdash_shadow -c "\d benachrichtigung"
```

Expected: the two new indexes are gone (back to only the primary key). Then:

```bash
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "DROP DATABASE absenzdash_shadow WITH (FORCE);"
```

- [ ] **Step 8: Apply the migration to the real dev/test database**

```bash
docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/benachrichtigung.py backend/tests/test_models_benachrichtigung.py backend/alembic/versions/
git commit -m "perf: add missing indexes on benachrichtigung.schueler_id and regel_id"
```

---

### Task 4: Three missing regression tests (no code changes)

**Files:**
- Modify: `backend/tests/test_eskalations_pruefung_regelaufloesung.py`
- Modify: `backend/tests/test_eskalations_pruefung.py`

**Interfaces:**
- None — these lock in already-correct behavior with committed tests. No production code changes in this task.

- [ ] **Step 1: Add the Abteilung-less-Klasse fallback test**

Append to `backend/tests/test_eskalations_pruefung_regelaufloesung.py`:

```python
@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_falls_back_to_schulweit_when_klasse_has_no_abteilung(db_session):
    """Eine Klasse ohne Abteilung (abteilung_id=None) soll die Abteilungs-Auflösung ueberspringen und
    direkt auf die schulweite Regel zurueckfallen, statt zu crashen oder faelschlich None zu liefern."""
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=None)
    db_session.add(klasse)
    await db_session.flush()

    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(schulweit)
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, klasse.id, "fehlzeiten")

    assert result.id == schulweit.id
```

- [ ] **Step 2: Add the cross-category Ausnahme independence test**

Append to `backend/tests/test_eskalations_pruefung.py`:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_ausnahme_kategorie_is_independent_across_typen(db_session):
    """Eine aktive Ausnahme fuer Kategorie 'klassenbuch' darf die 'fehlzeiten'-Verarbeitung desselben
    Schuelers nicht unterdruecken (Kategorien sind unabhaengig voneinander)."""
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    db_session.add(Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Testgrund", aktiv=True))
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.typ == "fehlzeiten"
        )
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1
```

- [ ] **Step 3: Add the bereichsleiter duplicate-recipient mirror test**

Append to `backend/tests/test_eskalations_pruefung.py`:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_bereichsleiter_empfaenger_without_duplicate(db_session):
    """Ein Bereichsleiter, der zwei Bereiche leitet, die beide auf dieselbe Klasse gemappt sind, darf nur
    EINMAL als Empfaenger auftauchen (Regression fuer fehlendes .distinct(), bereichsleiter-Fall — bisher
    nur fuer klassenlehrkraft abgedeckt)."""
    klasse = Klasse(webuntis_id=1, name="10a")
    bereich_a = Bereich(name="Kaufmaennischer Bereich")
    bereich_b = Bereich(name="Technischer Bereich")
    db_session.add_all([klasse, bereich_a, bereich_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_a.id, klasse_id=klasse.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_b.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    bereichsleiter = Nutzer(wp_user_id="u2", email="b@b.de", name="Leiter", rolle="bereichsleiter")
    db_session.add_all([schueler, bereichsleiter])
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=bereichsleiter.id, bereich_id=bereich_a.id))
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=bereichsleiter.id, bereich_id=bereich_b.id))

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=1,
            einheit="fehltage",
            schwellenwert=1,
            fehlzeiten_filter="alle",
            empfaenger_rollen=["bereichsleiter"],
        )
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    bereichsleiter_id = bereichsleiter.id
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.empfaenger == [{"rolle": "bereichsleiter", "nutzer_id": bereichsleiter_id}]
```

- [ ] **Step 4: Run all three new tests, confirm they pass immediately**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q \
  tests/test_eskalations_pruefung_regelaufloesung.py -k falls_back_to_schulweit_when_klasse_has_no_abteilung -v
docker compose -f backend/docker-compose.yml run --rm backend pytest -q \
  tests/test_eskalations_pruefung.py -k "ausnahme_kategorie_is_independent or resolves_bereichsleiter_empfaenger_without_duplicate" -v
```

Expected: PASS (3/3) — these lock in behavior that is already correct, no implementation change needed.

- [ ] **Step 5: Run the full test suite, confirm no regressions**

```bash
docker compose -f backend/docker-compose.yml run --rm backend pytest -q
```

Expected: PASS, all green.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_eskalations_pruefung_regelaufloesung.py backend/tests/test_eskalations_pruefung.py
git commit -m "test: lock in Abteilung-less-Klasse fallback, cross-category Ausnahme independence, and bereichsleiter duplicate-recipient handling"
```

---

## Self-Review

**Spec coverage:** All four review items are covered — Task 1 (query caching + zaehlerstand reuse), Task 2 (log-spam hoist), Task 3 (missing index migration), Task 4 (three regression tests). No review item left unaddressed.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code and exact commands.

**Type consistency:** `get_or_create_zaehlerstand`'s new `bestehender: SchuelerZaehlerstand | None = None` parameter is additive-only and checked against both existing call sites (`massnahme_service.py`, `test_massnahme_service.py`) — both call with 4 positional args and are unaffected. `regel_cache: dict[int | None, SchwellwertRegel | None]` keys on `Klasse.abteilung_id`'s sibling `Schueler.klasse_id` (also `int | None`), consistent with `resolve_schwellwert_regel`'s existing `klasse_id: int | None` parameter type.
