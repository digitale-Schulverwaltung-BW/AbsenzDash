# Schuljahr-Auswahl/-Historie Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `schuljahr` cache table fed from WebUntis, use it to fix the current sync outage (`getKlassen` needs an explicit `schoolyearId` when WebUntis has no "current" schoolyear), and expose it as a nav-wide Schuljahr selector that switches Schülerliste/Schüler-Detail into a read-only historical view for past schoolyears.

**Architecture:** Backend gains a small `schuljahr` reference table (upserted from `getSchoolyears` on every sync) and a resolver function that determines the "effective current" schoolyear (WebUntis's answer, or the most recent cached one if WebUntis has none) — this replaces today's narrow try/except hotfix in `sync_orchestrator.py`. `GET /students` and `GET /students/{id}` gain an optional `schuljahr_id` query param; when it differs from the resolved current schoolyear, both switch to a filtered/raw-data view instead of the live escalation-badge view. Frontend adds one nav-wide dropdown (URL param `schuljahr`, like the existing `bereich`/`klasse` params) that drives both pages.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Alembic / pytest (backend, `backend/`); React 18 / TypeScript / react-router-dom v6 / @tanstack/react-query / Vitest + RTL (frontend, `frontend/`).

## Global Constraints

- The `schuljahr` table is a pure cache (upserted from WebUntis's `getSchoolyears`, never deleted) — no manual admin CRUD, no override UI anywhere (see design doc's "Nicht-Ziele").
- History mode (a `schuljahr_id` other than the current one) drops the `aktiv=true` default filter in `GET /students` — former/inactive students must be included.
- In Schüler-Detail history mode, `fehlzeiten`/`klassenbuch`/`ausnahmen`/`benachrichtigungen` are date-filtered; `massnahmen` is **never** filtered, in any mode (SPECS.md §4 already documents measures as schoolyear-independent).
- No historical `klasse`-Zuordnung, no PDF-export period filter, no manual "current schoolyear" override anywhere — all deliberately out of scope (design doc).
- Deviation from the design doc, discovered while writing this plan: `Ausnahme` has no `gueltig_von` column (only `gueltig_bis`, nullable, plus `TimestampMixin.created_at`). Use `created_at` as the practical start-of-validity date in the overlap filter instead of the non-existent `gueltig_von` — see Task 6.

---

## Task 1: `schuljahr` cache table + `Einstellung.aktuelles_schuljahr_id`

**Files:**
- Create: `backend/app/models/schuljahr.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/einstellung.py`
- Create: `backend/alembic/versions/<new_hash>_add_schuljahr_table.py`
- Test: `backend/tests/test_models_schuljahr.py`

**Interfaces:**
- Produces: `Schuljahr` model (`id: int` — the WebUntis `schoolyearId`, not autoincrement; `name: str`; `start_datum: date`; `end_datum: date`). `Einstellung.aktuelles_schuljahr_id: int | None` (FK `schuljahr.id`, `ondelete="SET NULL"`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_models_schuljahr.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.schuljahr import Schuljahr


@pytest.mark.asyncio
async def test_schuljahr_roundtrip(db_session):
    schuljahr = Schuljahr(
        id=28,
        name="2025/2026",
        start_datum=datetime.date(2025, 9, 15),
        end_datum=datetime.date(2026, 7, 29),
    )
    db_session.add(schuljahr)
    await db_session.commit()

    result = await db_session.execute(select(Schuljahr).where(Schuljahr.id == 28))
    loaded = result.scalar_one()
    assert loaded.name == "2025/2026"
    assert loaded.start_datum == datetime.date(2025, 9, 15)
    assert loaded.end_datum == datetime.date(2026, 7, 29)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models_schuljahr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.schuljahr'`.

- [ ] **Step 3: Create the model**

`backend/app/models/schuljahr.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Schuljahr(Base, TimestampMixin):
    """Cache der WebUntis-Schuljahre (getSchoolyears), bei jedem Sync-Lauf per Upsert
    aktualisiert. `id` ist die WebUntis-schoolyearId, kein eigener Autoincrement - alte
    Schuljahre werden nie geloescht, auch wenn WebUntis sie irgendwann nicht mehr liefert."""

    __tablename__ = "schuljahr"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(20))
    start_datum: Mapped[date] = mapped_column(Date)
    end_datum: Mapped[date] = mapped_column(Date)
```

In `backend/app/models/__init__.py`, add the import (match the existing alphabetical-ish grouping and `__all__` list style already used for other models — insert `from app.models.schuljahr import Schuljahr` and add `"Schuljahr"` to `__all__`).

In `backend/app/models/einstellung.py`, add the new column:

```python
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Einstellung(Base, TimestampMixin):
    __tablename__ = "einstellung"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_interval_cron: Mapped[str] = mapped_column(String(50), default="*/30 * * * *")
    schuljahr_start_cache: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktuelles_schuljahr_id: Mapped[int | None] = mapped_column(
        ForeignKey("schuljahr.id", ondelete="SET NULL"), nullable=True
    )
    initialer_import_abgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)
    asv_csv_zuletzt_importiert_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    letzter_sync_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

(Only the import line gains `ForeignKey` and the one new `aktuelles_schuljahr_id` column — everything else in the file is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models_schuljahr.py -v`
Expected: PASS.

- [ ] **Step 5: Write the migration**

Find the current head: `cd backend && python -m alembic heads` (expected: `c5cfcd490245`). Generate a real revision: `python -m alembic revision -m "add schuljahr table"`, then fill in the body (replace `<new_hash>` with whatever was generated, in both the filename and the `revision =` line):

```python
"""add schuljahr table

Neue Stammdaten-Cache-Tabelle fuer WebUntis-Schuljahre (getSchoolyears), plus eine
Referenzspalte auf einstellung, die festhaelt, welches Schuljahr der letzte Sync-Lauf
als "aktuell" behandelt hat (siehe docs/superpowers/specs/2026-07-30-schuljahr-auswahl-design.md).

Revision ID: <new_hash>
Revises: c5cfcd490245
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "<new_hash>"
down_revision = "c5cfcd490245"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schuljahr",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("start_datum", sa.Date(), nullable=False),
        sa.Column("end_datum", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("einstellung", sa.Column("aktuelles_schuljahr_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_einstellung_aktuelles_schuljahr_id",
        "einstellung",
        "schuljahr",
        ["aktuelles_schuljahr_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_einstellung_aktuelles_schuljahr_id", "einstellung", type_="foreignkey")
    op.drop_column("einstellung", "aktuelles_schuljahr_id")
    op.drop_table("schuljahr")
```

- [ ] **Step 6: Verify the migration runs**

Run `python -m alembic upgrade head` against the dev DB (via `docker exec absenzdash-backend alembic upgrade head` if running in Docker, matching how prior migrations in this repo were verified). Confirm no error, then `alembic downgrade -1 && alembic upgrade head` to confirm a clean round-trip.

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && python -m pytest` (or via Docker: `docker exec absenzdash-backend python -m pytest`)
Expected: all tests pass, including the new one.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/schuljahr.py backend/app/models/__init__.py backend/app/models/einstellung.py \
  backend/alembic/versions backend/tests/test_models_schuljahr.py
git commit -m "feat: add schuljahr cache table and einstellung.aktuelles_schuljahr_id"
```

---

## Task 2: Schuljahr-Resolver + sync wiring (fixes the `getKlassen` outage)

**Files:**
- Modify: `backend/app/services/webuntis_klassen_sync.py`
- Modify: `backend/app/services/sync_orchestrator.py`
- Test: `backend/tests/test_webuntis_klassen_sync.py`
- Test: `backend/tests/test_sync_orchestrator.py`

**Interfaces:**
- Consumes: `Schuljahr` model (Task 1), `Einstellung.aktuelles_schuljahr_id` (Task 1).
- Produces: `async def resolve_aktuelles_schuljahr(client: WebUntisClient, db: AsyncSession) -> Schuljahr` in `sync_orchestrator.py` — refreshes the `schuljahr` cache from `getSchoolyears`, then returns the resolved current `Schuljahr` row (never `None` once at least one schoolyear has ever been cached; only `None`-able before the very first successful `getSchoolyears` call, which cannot happen in practice since WebUntis has always returned a non-empty list per the 2026-07-23 spike). `sync_klassen(client: WebUntisClient, db: AsyncSession, schoolyear_id: int) -> None` — signature gains a required `schoolyear_id` param.

- [ ] **Step 1: Write the failing test for `sync_klassen`**

Read `backend/tests/test_webuntis_klassen_sync.py` first to see its current test(s) and fixture style, then add/adjust a test asserting the `schoolyearId` param is sent:

```python
@pytest.mark.asyncio
async def test_sync_klassen_passes_schoolyear_id(db_session):
    client = AsyncMock()
    client.call.return_value = []

    await sync_klassen(client, db_session, schoolyear_id=28)

    client.call.assert_awaited_once_with("getKlassen", {"schoolyearId": 28})
```

(Match the existing imports/style in that file — it already imports `AsyncMock` and `sync_klassen` per the current test suite; add `schoolyear_id=28` to any other existing calls to `sync_klassen(...)` in that file so they don't break on the now-required parameter.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_webuntis_klassen_sync.py -v`
Expected: FAIL — `sync_klassen()` doesn't accept `schoolyear_id` yet, and/or the assertion on call args fails since `{}` is currently sent.

- [ ] **Step 3: Update `sync_klassen`**

In `backend/app/services/webuntis_klassen_sync.py`, change the signature and call:

```python
async def sync_klassen(client: WebUntisClient, db: AsyncSession, schoolyear_id: int) -> None:
```

and change `await client.call("getKlassen", {})` to `await client.call("getKlassen", {"schoolyearId": schoolyear_id})`. No other changes to this file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_webuntis_klassen_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for the resolver + orchestrator wiring**

Read `backend/tests/test_sync_orchestrator.py` in full first (it already has `test_run_full_sync_continues_when_no_active_schoolyear`, added by today's hotfix — this test's fake client and assertions need updating since the hotfix logic it tests is being replaced). Add:

```python
@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_uses_current_schoolyear(db_session, monkeypatch):
    client = AsyncMock()
    client.call = AsyncMock(
        side_effect=lambda method, _params: (
            [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
            if method == "getSchoolyears"
            else {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}
        )
    )

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"
    assert schuljahr.start_datum == date(2025, 9, 15)
    assert schuljahr.end_datum == date(2026, 7, 29)

    result = await db_session.execute(select(Schuljahr).order_by(Schuljahr.id))
    cached = result.scalars().all()
    assert [s.id for s in cached] == [27, 28]


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_falls_back_to_newest_cached_when_webuntis_has_none(db_session):
    """WebUntis meldet kein aktives Schuljahr (Uebergangszeitraum, siehe Live-Fund
    2026-07-30) - getCurrentSchoolyear wirft einen Fehler, getSchoolyears liefert aber
    weiterhin die volle Liste. Der Resolver faellt auf das juengste bekannte Schuljahr
    (hoechstes end_datum) zurueck, statt den ganzen Sync-Lauf abzubrechen."""
    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
        if method == "getCurrentSchoolyear":
            raise WebUntisError(
                'Cannot invoke "com.grupet.web.basic.Schoolyear.getEndDate()" because "schoolyear" is null'
            )
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"


@pytest.mark.asyncio
async def test_run_full_sync_continues_when_getklassen_fails_without_active_schoolyear(db_session, monkeypatch):
    """Reproduziert den Live-Fund vom 2026-07-30: getKlassen wirft denselben NPE wie
    getCurrentSchoolyear, wenn kein schoolyearId explizit mitgegeben wird. Mit der
    Resolver-Loesung bekommt getKlassen jetzt IMMER eine explizite schoolyearId, auch
    wenn getCurrentSchoolyear selbst fehlschlaegt - der Sync darf deshalb nicht mehr
    abbrechen."""

    class _FakeWebUntisClientKeinAktivesSchuljahr:
        def __init__(self, _settings):
            async def _call(method, params):
                if method == "getSchoolyears":
                    return [{"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}]
                if method == "getCurrentSchoolyear":
                    raise WebUntisError('... "schoolyear" is null')
                if method == "getKlassen":
                    assert params == {"schoolyearId": 28}
                    return []
                return {}

            self.call = AsyncMock(side_effect=_call)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClientKeinAktivesSchuljahr)

    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalar_one()
    assert einstellung.letzter_sync_am is not None
    assert einstellung.aktuelles_schuljahr_id == 28
```

Also **replace** the now-obsolete `test_run_full_sync_continues_when_no_active_schoolyear` (today's hotfix test) — it asserted `schuljahr_start_cache` stays unchanged when `getCurrentSchoolyear` fails; with the resolver's fallback-to-newest-cached logic, `schuljahr_start_cache` (and the new `aktuelles_schuljahr_id`) now correctly get SET to the fallback schoolyear's values instead of staying at their pre-existing value, since we now have a real answer (the cached list) instead of nothing to fall back on. Replace that test's body with an assertion matching the new, better behavior: `schuljahr_start_cache == date(2025, 9, 15)` and `aktuelles_schuljahr_id == 28` after a run where `getCurrentSchoolyear` fails but `getSchoolyears` succeeds (essentially merge it with `test_run_full_sync_continues_when_getklassen_fails_without_active_schoolyear` above — keep whichever single test covers both "doesn't crash" and "sets the right fallback values" without duplicating fixtures; use your judgment on final naming, but don't leave the old assertion, which is no longer correct behavior, in the suite).

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_sync_orchestrator.py -v`
Expected: FAIL — `resolve_aktuelles_schuljahr` doesn't exist yet, `run_sync_once`/`run_full_sync` don't set `aktuelles_schuljahr_id`, and `sync_klassen` is still called without `schoolyear_id`.

- [ ] **Step 7: Implement the resolver and rewire `run_sync_once`**

In `backend/app/services/sync_orchestrator.py`, add the imports `from datetime import date, datetime, timedelta, timezone` (already present — just confirm `date` is imported, it's used for the new function's return type) and `from app.models.schuljahr import Schuljahr` and `from sqlalchemy import select` (already imported). Add the new function (place it above `run_sync_once`):

```python
async def resolve_aktuelles_schuljahr(client: WebUntisClient, db: AsyncSession) -> Schuljahr:
    """Aktualisiert den schuljahr-Cache aus getSchoolyears und liefert das aktuell
    gueltige Schuljahr zurueck. Wenn WebUntis kein aktuelles Schuljahr kennt (z.B.
    Uebergangszeitraum zwischen zwei Schuljahren, siehe Live-Fund 2026-07-30), wird
    ersatzweise das juengste im Cache bekannte Schuljahr (hoechstes end_datum)
    zurueckgegeben - so bekommen nachfolgende schuljahresgebundene WebUntis-Aufrufe
    (z.B. getKlassen) immer eine gueltige schoolyearId, auch waehrend der Luecke."""
    rows = await client.call("getSchoolyears", {})
    for row in rows:
        start = datetime.strptime(str(row["startDate"]), "%Y%m%d").date()
        end = datetime.strptime(str(row["endDate"]), "%Y%m%d").date()
        bestehend = await db.get(Schuljahr, row["id"])
        if bestehend is None:
            db.add(Schuljahr(id=row["id"], name=row["name"], start_datum=start, end_datum=end))
        else:
            bestehend.name = row["name"]
            bestehend.start_datum = start
            bestehend.end_datum = end
    await db.flush()

    try:
        aktuell = await client.call("getCurrentSchoolyear", {})
        return await db.get(Schuljahr, aktuell["id"])
    except WebUntisError as exc:
        logger.warning(
            "getCurrentSchoolyear fehlgeschlagen, kein aktives Schuljahr in WebUntis "
            "konfiguriert; verwende juengstes bekanntes Schuljahr als Fallback: %s",
            exc,
        )
        result = await db.execute(select(Schuljahr).order_by(Schuljahr.end_datum.desc()).limit(1))
        return result.scalar_one()
```

Replace the existing try/except block in `run_sync_once` (the one added by today's hotfix, currently around the `getCurrentSchoolyear` call) and the plain `await sync_klassen(client, db)` call. The relevant section of `run_sync_once` becomes:

```python
async def run_sync_once(db: AsyncSession) -> None:
    async with WebUntisClient(settings) as client:
        einstellung = await get_or_create_einstellung(db)

        aktuelles_schuljahr = await resolve_aktuelles_schuljahr(client, db)
        einstellung.aktuelles_schuljahr_id = aktuelles_schuljahr.id
        if aktuelles_schuljahr.start_datum != einstellung.schuljahr_start_cache:
            einstellung.schuljahr_start_cache = aktuelles_schuljahr.start_datum

        await sync_abteilungen(client, db)
        await sync_klassen(client, db, schoolyear_id=aktuelles_schuljahr.id)
        await sync_kategorien(client, db)
        await import_schueler(db)

        heute = datetime.now(timezone.utc).date()
        von, bis = _fehlzeiten_zeitraum(einstellung, heute)
        await sync_fehlzeiten(client, db, von, bis)
        await sync_klassenbuch(client, db, von, bis)

        await pruefe_schwellwerte(db, heute, einstellung, settings)

        einstellung.letzter_sync_am = datetime.now(timezone.utc)
        if not einstellung.initialer_import_abgeschlossen:
            einstellung.initialer_import_abgeschlossen = True
        await db.commit()
```

Note the resolver now runs **first** (before `sync_abteilungen`/`sync_klassen`/etc.), since `sync_klassen` needs its result — this reorders the function but doesn't change what any of the other calls do (per the live spike, `getDepartments`/`getClassregCategories`/`getClassregCategoryGroups`/`getTeachers` don't need a schoolyear context, so their position relative to each other is unaffected).

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_sync_orchestrator.py tests/test_webuntis_klassen_sync.py -v`
Expected: all PASS.

- [ ] **Step 9: Run the full backend test suite**

Run: `cd backend && python -m pytest`
Expected: all pass — this also catches any other test file with a stale `sync_klassen(client, db)` call missing the now-required `schoolyear_id` param (grep `sync_klassen(` across `backend/tests/` if any failures point there).

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/webuntis_klassen_sync.py backend/app/services/sync_orchestrator.py \
  backend/tests/test_webuntis_klassen_sync.py backend/tests/test_sync_orchestrator.py
git commit -m "fix: resolve effective schuljahr and pass it to getKlassen, fixing the sync outage"
```

---

## Task 3: `GET /dashboard/nav-options` gains `schuljahre`

**Files:**
- Modify: `backend/app/schemas/dashboard.py`
- Modify: `backend/app/services/dashboard_query.py`
- Test: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- Consumes: `Schuljahr` model (Task 1).
- Produces: `NavOptionsOut.schuljahre: list[NavSchuljahrOut]`, `NavSchuljahrOut = {id: int, name: str, start_datum: date, end_datum: date}`, ordered by `start_datum` descending (newest first).

- [ ] **Step 1: Write the failing test**

Read `backend/tests/test_dashboard_query.py` first (it already has `test_get_nav_options_includes_rolle` from the admin-bereich plan) to match its exact fixture style, then add:

```python
@pytest.mark.asyncio
async def test_get_nav_options_includes_schuljahre_newest_first(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add_all(
        [
            nutzer,
            Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30)),
            Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29)),
        ]
    )
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert [s.id for s in result.schuljahre] == [28, 27]
    assert result.schuljahre[0].name == "2025/2026"
```

(Add `from app.models.schuljahr import Schuljahr` and `from datetime import date` to that file's imports if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_dashboard_query.py -k schuljahre -v`
Expected: FAIL — `NavOptionsOut` has no `schuljahre` attribute.

- [ ] **Step 3: Add the schema**

In `backend/app/schemas/dashboard.py`, add a new class near `NavKlasseOut` and extend `NavOptionsOut`:

```python
class NavSchuljahrOut(BaseModel):
    id: int
    name: str
    start_datum: date
    end_datum: date


class NavOptionsOut(BaseModel):
    bereiche: list[NavBereichOut]
    klassen: list[NavKlasseOut]
    rolle: str
    schuljahre: list[NavSchuljahrOut]
```

(`date` needs to be imported from `datetime` in this file if it isn't already — check the top of the file.)

- [ ] **Step 4: Populate it in the service**

In `backend/app/services/dashboard_query.py`, add the import `from app.models.schuljahr import Schuljahr` and `NavSchuljahrOut` to the existing `from app.schemas.dashboard import (...)` block. In `get_nav_options`, before the `return NavOptionsOut(...)` call, add:

```python
    schuljahre_result = await db.execute(select(Schuljahr).order_by(Schuljahr.start_datum.desc()))
    schuljahre = [
        NavSchuljahrOut(id=s.id, name=s.name, start_datum=s.start_datum, end_datum=s.end_datum)
        for s in schuljahre_result.scalars().all()
    ]
```

and add `schuljahre=schuljahre` to the `NavOptionsOut(...)` constructor call.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_dashboard_query.py -v`
Expected: all PASS (including the existing `rolle` test, unaffected by this change).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/dashboard.py backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "feat: include cached Schuljahre in GET /dashboard/nav-options"
```

---

## Task 4: `GET /admin/sync-settings` shows the schoolyear the sync is actually using

**Files:**
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/services/sync_settings_service.py`
- Test: `backend/tests/test_api_admin_sync_settings.py`

**Interfaces:**
- Consumes: `Einstellung.aktuelles_schuljahr_id` (Task 1).
- Produces: `SyncSettingsOut.aktuelles_schuljahr: SyncSchuljahrOut | None`, `SyncSchuljahrOut = {id: int, name: str}`.

- [ ] **Step 1: Write the failing test**

Read `backend/tests/test_api_admin_sync_settings.py` first to match its exact HTTP-test style (headers, `db_session` fixture), then add:

```python
@pytest.mark.asyncio
async def test_get_sync_settings_includes_aktuelles_schuljahr(db_session):
    db_session.add(Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29)))
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=28))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/sync-settings", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    body = response.json()
    assert body["aktuelles_schuljahr"] == {"id": 28, "name": "2025/2026"}


@pytest.mark.asyncio
async def test_get_sync_settings_aktuelles_schuljahr_null_before_first_sync(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/sync-settings", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json()["aktuelles_schuljahr"] is None
```

(Add `from app.models.schuljahr import Schuljahr` and `from datetime import date` to that file's imports if not already present — check what's already imported first.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_admin_sync_settings.py -k aktuelles_schuljahr -v`
Expected: FAIL — `SyncSettingsOut` has no `aktuelles_schuljahr` key in its response.

- [ ] **Step 3: Add the schema**

In `backend/app/schemas/admin.py`, add near `SyncSettingsOut`:

```python
class SyncSchuljahrOut(BaseModel):
    id: int
    name: str


class SyncSettingsOut(BaseModel):
    sync_interval_cron: str
    schuljahr_start_cache: date | None
    letzter_sync_am: datetime | None
    aktuelles_schuljahr: SyncSchuljahrOut | None
```

- [ ] **Step 4: Populate it in the service**

In `backend/app/services/sync_settings_service.py`, add the import `from app.models.schuljahr import Schuljahr`, add `SyncSchuljahrOut` to the `from app.schemas.admin import (...)` block, and change `_settings_out` to be async and look up the schoolyear:

```python
async def _settings_out(db: AsyncSession, einstellung: Einstellung) -> SyncSettingsOut:
    aktuelles_schuljahr = None
    if einstellung.aktuelles_schuljahr_id is not None:
        schuljahr = await db.get(Schuljahr, einstellung.aktuelles_schuljahr_id)
        if schuljahr is not None:
            aktuelles_schuljahr = SyncSchuljahrOut(id=schuljahr.id, name=schuljahr.name)
    return SyncSettingsOut(
        sync_interval_cron=einstellung.sync_interval_cron,
        schuljahr_start_cache=einstellung.schuljahr_start_cache,
        letzter_sync_am=einstellung.letzter_sync_am,
        aktuelles_schuljahr=aktuelles_schuljahr,
    )
```

Add `from sqlalchemy.ext.asyncio import AsyncSession` to this file's imports if not already present (it's already used as a type hint on `get_sync_settings`/`update_sync_settings`, so it should already be imported — just confirm). Update both call sites (`get_sync_settings` and `update_sync_settings`) from `_settings_out(einstellung)` to `await _settings_out(db, einstellung)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api_admin_sync_settings.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/sync_settings_service.py backend/tests/test_api_admin_sync_settings.py
git commit -m "feat: show the schoolyear the sync is actually using in GET /admin/sync-settings"
```

---

## Task 5: `GET /students` — Schuljahr-Historie (Rohzahlen)

**Files:**
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/api/routes/students.py`
- Test: `backend/tests/test_student_query.py`
- Test: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `Einstellung.aktuelles_schuljahr_id`, `Schuljahr` model (Task 1).
- Produces: `student_query.load_schueler_rohzahlen(db, schueler_ids, von, bis) -> dict[int, dict[str, int]]`, keys `"fehltage"`, `"fehlstunden"`, `"klassenbuch_anzahl"`. `StudentOverviewOut` fields `zaehlerstand`, `letzte_benachrichtigung`, `ohne_massnahme_seit_benachrichtigung` become optional (`None` in history mode); new optional fields `fehltage: int | None`, `fehlstunden: int | None`, `klassenbuch_anzahl: int | None`.

**Chosen semantics (resolving ambiguity not fully pinned down in the design doc):** history mode is "raw data, not escalation-derived" — the three counts are computed directly from `fehlzeit`/`klassenbuch_eintrag` rows in the schoolyear's date range, regardless of `excuse_status.zaehlt_als_entschuldigt` (i.e. entschuldigte and unentschuldigte Fehlzeiten are both counted — this is deliberately different from the escalation engine's "nur_unentschuldigt" filter, since the point of the historic view is a complete record, not an escalation trigger). In history mode the list does **not** show the "Benachrichtigt" column at all (no `letzte_benachrichtigung`/`ohne_massnahme_seit_benachrichtigung` — those are live-escalation concepts with no historical meaning), and `min_stufe`/`nur_auffaellige`/`typ` query params are ignored (they only make sense against live `schueler_zaehlerstand`, which doesn't apply here).

- [ ] **Step 1: Write the failing service-level test**

Read `backend/tests/test_student_query.py` in full first, then add:

```python
@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_counts_within_range(db_session):
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B")
    db_session.add_all([schueler_a, schueler_b])
    await db_session.flush()

    db_session.add_all(
        [
            # schueler_a: 2 Fehltage, 1 Fehlstunde within range, 1 Fehltag outside range
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2025, 11, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_a.id, typ="stunde", datum=date(2025, 10, 5), start_zeit=730, end_zeit=815),
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            KlassenbuchEintrag(schueler_id=schueler_a.id, webuntis_id=1, kategorie_id=1, datum=date(2025, 10, 2)),
            # schueler_b: nothing in range
            Fehlzeit(schueler_id=schueler_b.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(
        db_session, [schueler_a.id, schueler_b.id], date(2025, 9, 15), date(2026, 7, 29)
    )

    assert result[schueler_a.id] == {"fehltage": 2, "fehlstunden": 1, "klassenbuch_anzahl": 1}
    assert result[schueler_b.id] == {"fehltage": 0, "fehlstunden": 0, "klassenbuch_anzahl": 0}
```

(Adapt imports at the top of the file if `date`/`Fehlzeit`/`KlassenbuchEintrag` aren't already imported there — they likely already are, given the file's existing tests.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_student_query.py -k rohzahlen -v`
Expected: FAIL — `load_schueler_rohzahlen` doesn't exist.

- [ ] **Step 3: Implement `load_schueler_rohzahlen`**

In `backend/app/services/student_query.py`, add (near `load_overview_extras`):

```python
async def load_schueler_rohzahlen(
    db: AsyncSession, schueler_ids: list[int], von: date, bis: date
) -> dict[int, dict[str, int]]:
    ergebnis = {sid: {"fehltage": 0, "fehlstunden": 0, "klassenbuch_anzahl": 0} for sid in schueler_ids}
    if not schueler_ids:
        return ergebnis

    fehlzeit_result = await db.execute(
        select(Fehlzeit.schueler_id, Fehlzeit.typ, func.count())
        .where(Fehlzeit.schueler_id.in_(schueler_ids), Fehlzeit.datum.between(von, bis))
        .group_by(Fehlzeit.schueler_id, Fehlzeit.typ)
    )
    for schueler_id, typ, anzahl in fehlzeit_result.all():
        if typ == "tag":
            ergebnis[schueler_id]["fehltage"] = anzahl
        elif typ == "stunde":
            ergebnis[schueler_id]["fehlstunden"] = anzahl

    klassenbuch_result = await db.execute(
        select(KlassenbuchEintrag.schueler_id, func.count())
        .where(KlassenbuchEintrag.schueler_id.in_(schueler_ids), KlassenbuchEintrag.datum.between(von, bis))
        .group_by(KlassenbuchEintrag.schueler_id)
    )
    for schueler_id, anzahl in klassenbuch_result.all():
        ergebnis[schueler_id]["klassenbuch_anzahl"] = anzahl

    return ergebnis
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_student_query.py -k rohzahlen -v`
Expected: PASS.

- [ ] **Step 5: Extend the schema**

In `backend/app/schemas/students.py`, change `StudentOverviewOut` (lines 33-42) to:

```python
class StudentOverviewOut(BaseModel):
    id: int
    vorname: str
    nachname: str
    klasse: KlasseOut | None
    zaehlerstand: dict[str, ZaehlerstandOut] | None = None
    letzte_benachrichtigung: BenachrichtigungOut | None = None
    ohne_massnahme_seit_benachrichtigung: bool | None = None
    fehltage: int | None = None
    fehlstunden: int | None = None
    klassenbuch_anzahl: int | None = None
```

- [ ] **Step 6: Write the failing HTTP-level test**

Read `backend/tests/test_api_students.py` in full first (already has `_seed_klassenlehrkraft` and `HEADERS_KLASSENLEHRKRAFT`), then add:

```python
@pytest.mark.asyncio
async def test_get_students_history_mode_returns_rohzahlen_and_includes_inactive(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    schueler_aktiv = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    schueler_inaktiv = Schueler(externe_id="ext-2", vorname="B", nachname="B", klasse_id=klasse.id, aktiv=False)
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler_aktiv, schueler_inaktiv, schuljahr])
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler_inaktiv.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students?schuljahr_id={schuljahr.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert schueler_inaktiv.id in ids  # inaktive Schueler erscheinen in der Historie
    inaktiv_item = next(item for item in body["items"] if item["id"] == schueler_inaktiv.id)
    assert inaktiv_item["fehltage"] == 1
    assert inaktiv_item["zaehlerstand"] is None
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_students.py -k history_mode -v`
Expected: FAIL — the route doesn't accept `schuljahr_id` yet, and inactive students are excluded by the default `nur_aktive=True`.

- [ ] **Step 8: Wire up the route**

The current full contents of `backend/app/api/routes/students.py:1-33` (imports/router setup) and `:52-102` (`get_students`) are:

```python
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.students import (
    AusnahmeOut,
    BenachrichtigungOut,
    ClassregCategoryCatalogOut,
    ExcuseStatusCatalogOut,
    ExemptionCreateIn,
    MassnahmeOut,
    MassnahmenTypCatalogOut,
    MeasureCreateIn,
    StudentCatalogOut,
    StudentDetailOut,
    StudentListOut,
    StudentOverviewOut,
)
from app.services import ausnahme_service, export_service, massnahme_service, student_query

router = APIRouter(prefix="/students", tags=["students"])
```

```python
@router.get("")
async def get_students(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: Literal["fehlzeiten", "klassenbuch"] | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    nur_aktive: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StudentListOut:
    scope = await resolve_scope(db, nutzer)
    schueler_list, total = await student_query.list_students(
        db,
        scope=scope,
        klasse_id=klasse_id,
        bereich_id=bereich_id,
        typ=typ,
        min_stufe=min_stufe,
        nur_auffaellige=nur_auffaellige,
        nur_aktive=nur_aktive,
        limit=limit,
        offset=offset,
    )
    schueler_ids = [schueler.id for schueler in schueler_list]
    extras = await student_query.load_overview_extras(db, schueler_ids)
    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)
    regel_ids = [
        extras[schueler.id]["letzte_benachrichtigung"].regel_id
        for schueler in schueler_list
        if extras[schueler.id]["letzte_benachrichtigung"] is not None
        and extras[schueler.id]["letzte_benachrichtigung"].regel_id is not None
    ]
    regel_typ_map = await student_query.load_regel_typ_map(db, regel_ids)

    items = [
        StudentOverviewOut(
            id=schueler.id,
            vorname=schueler.vorname,
            nachname=schueler.nachname,
            klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
            zaehlerstand=extras[schueler.id]["zaehlerstand"],
            letzte_benachrichtigung=_benachrichtigung_out(extras[schueler.id]["letzte_benachrichtigung"], regel_typ_map),
            ohne_massnahme_seit_benachrichtigung=extras[schueler.id]["ohne_massnahme_seit_benachrichtigung"],
        )
        for schueler in schueler_list
    ]
    return StudentListOut(items=items, total=total, limit=limit, offset=offset)
```

Change the imports block to add three lines (`date` to the top, plus two model imports):

```python
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.einstellung import Einstellung
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr
from app.schemas.students import (
    AusnahmeOut,
    BenachrichtigungOut,
    ClassregCategoryCatalogOut,
    ExcuseStatusCatalogOut,
    ExemptionCreateIn,
    MassnahmeOut,
    MassnahmenTypCatalogOut,
    MeasureCreateIn,
    StudentCatalogOut,
    StudentDetailOut,
    StudentListOut,
    StudentOverviewOut,
)
from app.services import ausnahme_service, export_service, massnahme_service, student_query

router = APIRouter(prefix="/students", tags=["students"])


async def _resolve_schuljahr_zeitraum(db: AsyncSession, schuljahr_id: int | None) -> tuple[date | None, date | None]:
    """None, None heisst "aktuelles Schuljahr, unveraendertes Verhalten". Ein konkretes
    (von, bis)-Paar heisst "Historie-Modus fuer dieses vergangene Schuljahr"."""
    if schuljahr_id is None:
        return None, None
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is not None and schuljahr_id == einstellung.aktuelles_schuljahr_id:
        return None, None
    schuljahr = await db.get(Schuljahr, schuljahr_id)
    if schuljahr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Schuljahr")
    return schuljahr.start_datum, schuljahr.end_datum
```

Replace `get_students` in full:

```python
@router.get("")
async def get_students(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: Literal["fehlzeiten", "klassenbuch"] | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    nur_aktive: bool = True,
    schuljahr_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StudentListOut:
    scope = await resolve_scope(db, nutzer)
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None

    schueler_list, total = await student_query.list_students(
        db,
        scope=scope,
        klasse_id=klasse_id,
        bereich_id=bereich_id,
        typ=None if ist_historie else typ,
        min_stufe=None if ist_historie else min_stufe,
        nur_auffaellige=False if ist_historie else nur_auffaellige,
        nur_aktive=False if ist_historie else nur_aktive,
        limit=limit,
        offset=offset,
    )
    schueler_ids = [schueler.id for schueler in schueler_list]
    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)

    if ist_historie:
        rohzahlen = await student_query.load_schueler_rohzahlen(db, schueler_ids, von, bis)
        items = [
            StudentOverviewOut(
                id=schueler.id,
                vorname=schueler.vorname,
                nachname=schueler.nachname,
                klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
                fehltage=rohzahlen[schueler.id]["fehltage"],
                fehlstunden=rohzahlen[schueler.id]["fehlstunden"],
                klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
            )
            for schueler in schueler_list
        ]
        return StudentListOut(items=items, total=total, limit=limit, offset=offset)

    extras = await student_query.load_overview_extras(db, schueler_ids)
    regel_ids = [
        extras[schueler.id]["letzte_benachrichtigung"].regel_id
        for schueler in schueler_list
        if extras[schueler.id]["letzte_benachrichtigung"] is not None
        and extras[schueler.id]["letzte_benachrichtigung"].regel_id is not None
    ]
    regel_typ_map = await student_query.load_regel_typ_map(db, regel_ids)

    items = [
        StudentOverviewOut(
            id=schueler.id,
            vorname=schueler.vorname,
            nachname=schueler.nachname,
            klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
            zaehlerstand=extras[schueler.id]["zaehlerstand"],
            letzte_benachrichtigung=_benachrichtigung_out(extras[schueler.id]["letzte_benachrichtigung"], regel_typ_map),
            ohne_massnahme_seit_benachrichtigung=extras[schueler.id]["ohne_massnahme_seit_benachrichtigung"],
        )
        for schueler in schueler_list
    ]
    return StudentListOut(items=items, total=total, limit=limit, offset=offset)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api_students.py tests/test_student_query.py -v`
Expected: all PASS.

- [ ] **Step 10: Run the full backend test suite**

Run: `cd backend && python -m pytest`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/students.py backend/app/services/student_query.py backend/app/api/routes/students.py \
  backend/tests/test_student_query.py backend/tests/test_api_students.py
git commit -m "feat: add schuljahr_id history mode to GET /students"
```

---

## Task 6: `GET /students/{id}` — Schuljahr-Historie in vier Abschnitten

**Files:**
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/api/routes/students.py`
- Test: `backend/tests/test_student_query.py`
- Test: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `Einstellung.aktuelles_schuljahr_id`, `Schuljahr` model (Task 1).
- Produces: `student_query.load_student_detail(db, schueler_id, von=None, bis=None) -> dict[str, Any]` — signature gains two optional params; when both are `None` (default), behavior is byte-for-byte identical to today (all rows, `zaehlerstand` populated). When set, `fehlzeiten`/`klassenbuch`/`ausnahmen`/`benachrichtigungen` are filtered by the range, `massnahmen` is unaffected, and `zaehlerstand` is `{}` (not populated — not meaningful for a past year). `StudentDetailOut.zaehlerstand` becomes `dict[str, ZaehlerstandOut]` still required but may be an **empty dict** in history mode (not `None` — keeps the type simpler than the list endpoint, since the frontend already does `Object.entries(...)` which handles an empty dict gracefully with zero iterations, unlike `null`).

**Ausnahme overlap filter — deviation from the design doc:** `Ausnahme` has no `gueltig_von` column (confirmed: only `gueltig_bis`, nullable, plus `TimestampMixin.created_at`). Use `Ausnahme.created_at`'s date as the practical start-of-validity: an Ausnahme's overlap condition is `func.date(Ausnahme.created_at) <= bis AND (Ausnahme.gueltig_bis IS NULL OR Ausnahme.gueltig_bis >= von)`.

- [ ] **Step 1: Write the failing service-level test**

Read `backend/tests/test_student_query.py`'s existing `load_student_detail` tests first, then add:

```python
@pytest.mark.asyncio
async def test_load_student_detail_filters_by_range_except_massnahmen(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, typ, nutzer])
    await db_session.flush()

    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            KlassenbuchEintrag(schueler_id=schueler.id, webuntis_id=1, kategorie_id=1, datum=date(2025, 11, 1)),
            KlassenbuchEintrag(schueler_id=schueler.id, webuntis_id=2, kategorie_id=1, datum=date(2024, 11, 1)),
            Benachrichtigung(
                schueler_id=schueler.id, stufe_nr=1, gesendet_am=datetime(2025, 12, 1, tzinfo=timezone.utc),
                empfaenger=[], status="gesendet",
            ),
            Benachrichtigung(
                schueler_id=schueler.id, stufe_nr=1, gesendet_am=datetime(2024, 12, 1, tzinfo=timezone.utc),
                empfaenger=[], status="gesendet",
            ),
            Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="im Bereich", gueltig_bis=None),
            Massnahme(schueler_id=schueler.id, massnahmen_typ_id=typ.id, datum=date(2024, 6, 1), erfasst_von_nutzer_id=nutzer.id),
        ]
    )
    await db_session.commit()

    detail = await student_query.load_student_detail(
        db_session, schueler.id, von=date(2025, 9, 15), bis=date(2026, 7, 29)
    )

    assert [f.datum for f in detail["fehlzeiten"]] == [date(2025, 10, 1)]
    assert [k.datum for k in detail["klassenbuch"]] == [date(2025, 11, 1)]
    assert len(detail["benachrichtigungen"]) == 1
    assert len(detail["ausnahmen"]) == 1  # unbefristet, created vor dem Zeitraum, gilt trotzdem als ueberlappend
    assert len(detail["massnahmen"]) == 1  # Massnahmen NIE gefiltert, auch die von 2024 bleibt sichtbar
    assert detail["zaehlerstand"] == {}
```

(Adapt imports if `datetime`/`timezone`/`Benachrichtigung`/`Ausnahme`/`Massnahme`/`MassnahmenTyp`/`Nutzer` aren't already imported in this test file — they likely partly are already, given existing tests in the file cover similar models.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_student_query.py -k filters_by_range -v`
Expected: FAIL — `load_student_detail` doesn't accept `von`/`bis` yet.

- [ ] **Step 3: Update `load_student_detail`**

In `backend/app/services/student_query.py`, change the signature and add the range filters (only to `fehlzeiten`, `klassenbuch`, `ausnahmen`, `benachrichtigungen`; `massnahmen` untouched):

```python
async def load_student_detail(
    db: AsyncSession, schueler_id: int, von: date | None = None, bis: date | None = None
) -> dict[str, Any]:
    fehlzeiten_query = select(Fehlzeit).where(Fehlzeit.schueler_id == schueler_id)
    klassenbuch_query = select(KlassenbuchEintrag).where(KlassenbuchEintrag.schueler_id == schueler_id)
    ausnahmen_query = select(Ausnahme).where(Ausnahme.schueler_id == schueler_id)
    benachrichtigungen_query = select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id)

    if von is not None and bis is not None:
        fehlzeiten_query = fehlzeiten_query.where(Fehlzeit.datum.between(von, bis))
        klassenbuch_query = klassenbuch_query.where(KlassenbuchEintrag.datum.between(von, bis))
        ausnahmen_query = ausnahmen_query.where(
            func.date(Ausnahme.created_at) <= bis, or_(Ausnahme.gueltig_bis.is_(None), Ausnahme.gueltig_bis >= von)
        )
        benachrichtigungen_query = benachrichtigungen_query.where(
            func.date(Benachrichtigung.gesendet_am).between(von, bis)
        )

    fehlzeiten = (await db.execute(fehlzeiten_query.order_by(Fehlzeit.datum.desc()))).scalars().all()
    klassenbuch = (await db.execute(klassenbuch_query.order_by(KlassenbuchEintrag.datum.desc()))).scalars().all()
    ausnahmen = (await db.execute(ausnahmen_query)).scalars().all()
    benachrichtigungen = (
        (await db.execute(benachrichtigungen_query.order_by(Benachrichtigung.gesendet_am.desc()))).scalars().all()
    )

    massnahmen_result = await db.execute(
        select(Massnahme, MassnahmenTyp.name, Nutzer.name)
        .join(MassnahmenTyp, Massnahme.massnahmen_typ_id == MassnahmenTyp.id)
        .join(Nutzer, Massnahme.erfasst_von_nutzer_id == Nutzer.id)
        .where(Massnahme.schueler_id == schueler_id)
        .order_by(Massnahme.datum.desc())
    )

    zaehlerstand: dict[str, Any] = {}
    if von is None and bis is None:
        zaehlerstand = (await load_zaehlerstand_map(db, [schueler_id]))[schueler_id]

    return {
        "fehlzeiten": fehlzeiten,
        "klassenbuch": klassenbuch,
        "massnahmen": massnahmen_result.all(),
        "ausnahmen": ausnahmen,
        "benachrichtigungen": benachrichtigungen,
        "zaehlerstand": zaehlerstand,
    }
```

**Important — exact key name:** the dict key is `"zaehlerstand"`, not `"zaehlerstand_map"` — `backend/app/api/routes/students.py:159` already reads `zaehlerstand=detail["zaehlerstand"]` when building `StudentDetailOut`, so this rewrite must keep that exact key to avoid breaking the existing route code (which Step 7 below leaves untouched at that line). Read the existing function body first (lines 204-247 per the earlier investigation) to confirm the exact current shape of the `massnahmen` query and the `zaehlerstand` construction (via `load_zaehlerstand_map`) before replacing it, so the massnahmen-join logic and the per-typ dict shape stay identical to today's behavior — only the four filtered queries and the added `von`/`bis` params are new. Add `from sqlalchemy import or_` to the imports if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_student_query.py -v`
Expected: all PASS, including pre-existing `load_student_detail` tests (called with no `von`/`bis`, so they exercise the unchanged default path).

- [ ] **Step 5: Write the failing HTTP-level test**

Add to `backend/tests/test_api_students.py`:

```python
@pytest.mark.asyncio
async def test_get_student_detail_history_mode_filters_four_sections_not_massnahmen(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse.id)
    typ = MassnahmenTyp(name="Gespraech", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u2", email="c@d.de", name="C", rolle="klassenlehrkraft")
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler, typ, nutzer, schuljahr])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Massnahme(schueler_id=schueler.id, massnahmen_typ_id=typ.id, datum=date(2025, 10, 1), erfasst_von_nutzer_id=nutzer.id),
        ]
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}?schuljahr_id={schuljahr.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["fehlzeiten"]) == 1
    assert body["fehlzeiten"][0]["datum"] == "2024-10-01"
    assert len(body["massnahmen"]) == 1  # unabhaengig vom Schuljahr-Filter sichtbar
    assert body["zaehlerstand"] == {}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_students.py -k history_mode_filters -v`
Expected: FAIL — the route doesn't accept `schuljahr_id` yet.

- [ ] **Step 7: Wire up the route**

`_resolve_schuljahr_zeitraum` already exists from Task 5 (same file) — reuse it here, don't duplicate it. The current `get_student_detail` (`backend/app/api/routes/students.py:126-165`) is:

```python
@router.get("/{schueler_id}")
async def get_student_detail(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudentDetailOut:
    detail = await student_query.load_student_detail(db, schueler.id)
    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    benachrichtigung_regel_ids = [b.regel_id for b in detail["benachrichtigungen"] if b.regel_id is not None]
    regel_typ_map = await student_query.load_regel_typ_map(db, benachrichtigung_regel_ids)
    benachrichtigungen = [_benachrichtigung_out(b, regel_typ_map) for b in detail["benachrichtigungen"]]

    massnahmen = [
        MassnahmeOut(
            id=massnahme.id,
            massnahmen_typ_id=massnahme.massnahmen_typ_id,
            massnahmen_typ_name=typ_name,
            datum=massnahme.datum,
            notiz=massnahme.notiz,
            erfasst_von_nutzer_id=massnahme.erfasst_von_nutzer_id,
            erfasst_von_name=nutzer_name,
        )
        for massnahme, typ_name, nutzer_name in detail["massnahmen"]
    ]

    return StudentDetailOut(
        id=schueler.id,
        vorname=schueler.vorname,
        nachname=schueler.nachname,
        klasse=klasse,
        zaehlerstand=detail["zaehlerstand"],
        fehlzeiten=detail["fehlzeiten"],
        klassenbuch=detail["klassenbuch"],
        massnahmen=massnahmen,
        ausnahmen=detail["ausnahmen"],
        benachrichtigungen=benachrichtigungen,
    )
```

Change only the signature and the `load_student_detail` call — every other line stays exactly as-is (the `zaehlerstand=detail["zaehlerstand"]` line at the end is untouched and will naturally receive the empty dict in history mode):

```python
@router.get("/{schueler_id}")
async def get_student_detail(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: int | None = None,
) -> StudentDetailOut:
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    detail = await student_query.load_student_detail(db, schueler.id, von=von, bis=bis)
    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    benachrichtigung_regel_ids = [b.regel_id for b in detail["benachrichtigungen"] if b.regel_id is not None]
    regel_typ_map = await student_query.load_regel_typ_map(db, benachrichtigung_regel_ids)
    benachrichtigungen = [_benachrichtigung_out(b, regel_typ_map) for b in detail["benachrichtigungen"]]

    massnahmen = [
        MassnahmeOut(
            id=massnahme.id,
            massnahmen_typ_id=massnahme.massnahmen_typ_id,
            massnahmen_typ_name=typ_name,
            datum=massnahme.datum,
            notiz=massnahme.notiz,
            erfasst_von_nutzer_id=massnahme.erfasst_von_nutzer_id,
            erfasst_von_name=nutzer_name,
        )
        for massnahme, typ_name, nutzer_name in detail["massnahmen"]
    ]

    return StudentDetailOut(
        id=schueler.id,
        vorname=schueler.vorname,
        nachname=schueler.nachname,
        klasse=klasse,
        zaehlerstand=detail["zaehlerstand"],
        fehlzeiten=detail["fehlzeiten"],
        klassenbuch=detail["klassenbuch"],
        massnahmen=massnahmen,
        ausnahmen=detail["ausnahmen"],
        benachrichtigungen=benachrichtigungen,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api_students.py tests/test_student_query.py -v`
Expected: all PASS.

- [ ] **Step 9: Run the full backend test suite**

Run: `cd backend && python -m pytest`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/student_query.py backend/app/api/routes/students.py \
  backend/tests/test_student_query.py backend/tests/test_api_students.py
git commit -m "feat: add schuljahr_id history mode to GET /students/{id}"
```

---

## Task 7: Frontend — Types, `useNavOptions`, Schuljahr-Dropdown

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/Navigation/Navigation.tsx`
- Modify: `frontend/src/components/Navigation/Navigation.module.css`
- Test: `frontend/src/components/Navigation/Navigation.test.tsx`

**Interfaces:**
- Produces: `NavOptions.schuljahre: NavSchuljahr[]`, `NavSchuljahr = {id: number, name: string, start_datum: string, end_datum: string}`. URL param `schuljahr` (string, the schoolyear's `id`), following the exact same pattern as `bereich`/`klasse`.

- [ ] **Step 1: Add the type**

In `frontend/src/api/types.ts`, add near `NavKlasse` and extend `NavOptions`:

```ts
export interface NavSchuljahr {
  id: number;
  name: string;
  start_datum: string;
  end_datum: string;
}

export interface NavOptions {
  bereiche: NavBereich[];
  klassen: NavKlasse[];
  rolle: string;
  schuljahre: NavSchuljahr[];
}
```

- [ ] **Step 2: Write the failing test**

Read `frontend/src/components/Navigation/Navigation.test.tsx` in full first (it already mocks `useNavOptions` and has Admin-link tests — every existing `mockUseNavOptions.mockReturnValue({ data: {...} })` call in this file needs `schuljahre: []` added to its `data` object so they keep passing with the new required field). Then add:

```tsx
it("shows the Schuljahr dropdown, newest first, right-aligned", () => {
  mockUseNavOptions.mockReturnValue({
    data: {
      bereiche: [], klassen: [], rolle: "klassenlehrkraft",
      schuljahre: [
        { id: 28, name: "2025/2026", start_datum: "2025-09-15", end_datum: "2026-07-29" },
        { id: 27, name: "2024/2025", start_datum: "2024-09-09", end_datum: "2025-07-30" },
      ],
    },
    isLoading: false,
    isError: false,
  } as any);
  render(<MemoryRouter><Navigation /></MemoryRouter>);

  const select = screen.getByLabelText("Schuljahr") as HTMLSelectElement;
  const options = Array.from(select.options).map((o) => o.textContent);
  expect(options).toEqual(["Aktuelles Schuljahr", "2025/2026", "2024/2025"]);
});

it("sets the schuljahr URL param on change and clears it when reset to current", () => {
  mockUseNavOptions.mockReturnValue({
    data: {
      bereiche: [], klassen: [], rolle: "klassenlehrkraft",
      schuljahre: [{ id: 27, name: "2024/2025", start_datum: "2024-09-09", end_datum: "2025-07-30" }],
    },
    isLoading: false,
    isError: false,
  } as any);
  render(<MemoryRouter initialEntries={["/schueler"]}><Navigation /></MemoryRouter>);

  fireEvent.change(screen.getByLabelText("Schuljahr"), { target: { value: "27" } });
  expect(screen.getByLabelText("Schuljahr")).toHaveValue("27");

  fireEvent.change(screen.getByLabelText("Schuljahr"), { target: { value: "" } });
  expect(screen.getByLabelText("Schuljahr")).toHaveValue("");
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/Navigation/Navigation.test.tsx`
Expected: FAIL — no "Schuljahr" labeled element exists yet.

- [ ] **Step 4: Implement the dropdown**

In `frontend/src/components/Navigation/Navigation.tsx`, add a `handleSchuljahrChange` function (same shape as `handleBereichChange`/`handleKlasseChange`, but it does **not** clear `bereich`/`klasse` params — schoolyear and bereich/klasse scoping are independent axes) and render the dropdown as the last child of `<nav>`:

```tsx
  function handleSchuljahrChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete("schuljahr");
    } else {
      next.set("schuljahr", value);
    }
    setSearchParams(next);
  }
```

and, after the existing Klasse `<select>` block, add:

```tsx
      <select
        aria-label="Schuljahr"
        className={styles.schuljahrSelect}
        value={searchParams.get("schuljahr") ?? ""}
        onChange={(event) => handleSchuljahrChange(event.target.value)}
      >
        <option value="">Aktuelles Schuljahr</option>
        {data.schuljahre.map((schuljahr) => (
          <option key={schuljahr.id} value={schuljahr.id}>
            {schuljahr.name}
          </option>
        ))}
      </select>
```

In `frontend/src/components/Navigation/Navigation.module.css`, add:

```css
.schuljahrSelect {
  margin-left: auto;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Navigation/Navigation.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all pass — this catches any other test file with a stale `NavOptions` mock missing `schuljahre` (e.g. `App.test.tsx`, `main.test.tsx`, any Admin page test mocking `useNavOptions`). Fix every one found by adding `schuljahre: []` to its mocked `data` object.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/components/Navigation/Navigation.tsx \
  frontend/src/components/Navigation/Navigation.module.css frontend/src/components/Navigation/Navigation.test.tsx
git commit -m "feat: add Schuljahr dropdown to the navigation"
```

(If Step 6 required fixing other test files, `git add` those too before committing, and mention it in the commit body as a one-line note.)

---

## Task 8: Frontend — Schülerliste Historie-Modus

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/hooks/useStudents.ts`
- Modify: `frontend/src/pages/StudentList/StudentList.tsx`
- Test: `frontend/src/api/hooks/useStudents.test.tsx`
- Test: `frontend/src/pages/StudentList/StudentList.test.tsx`

**Interfaces:**
- Consumes: `NavOptions.schuljahre` (Task 7, via the `schuljahr` URL param already wired into the nav).
- Produces: `StudentListParams.schuljahrId: number | null` (new field). `StudentOverview` gains optional `fehltage`/`fehlstunden`/`klassenbuch_anzahl: number | null` and `zaehlerstand`/`letzte_benachrichtigung`/`ohne_massnahme_seit_benachrichtigung` become nullable, mirroring the backend's Task 5 schema change.

- [ ] **Step 1: Update the types**

In `frontend/src/api/types.ts`, change `StudentOverview`:

```ts
export interface StudentOverview {
  id: number;
  vorname: string;
  nachname: string;
  klasse: Klasse | null;
  zaehlerstand: Record<string, Zaehlerstand> | null;
  letzte_benachrichtigung: Benachrichtigung | null;
  ohne_massnahme_seit_benachrichtigung: boolean | null;
  fehltage: number | null;
  fehlstunden: number | null;
  klassenbuch_anzahl: number | null;
}
```

- [ ] **Step 2: Write the failing hook test**

Read `frontend/src/api/hooks/useStudents.test.tsx` (if it exists — check first; if there's no dedicated test file for this hook, look at how `useStudentCatalog.test.tsx` or similar simple GET hooks are tested and create one matching that pattern) and add a case asserting `schuljahr_id` is included in the query string when `schuljahrId` is set, and omitted when `null`:

```tsx
it("includes schuljahr_id in the query string when set", () => {
  const params: StudentListParams = {
    bereichId: null, klasseId: null, minStufe: null, nurAuffaellige: false, offset: 0, schuljahrId: 27,
  };
  // however this file asserts query strings today (check existing tests for the exact
  // assertion style — likely via a spy on apiGet's call argument), assert the built path
  // contains "schuljahr_id=27".
});
```

(If no test file exists yet for this hook, write one from scratch following the `useSyncSettings.test.tsx` GET-hook pattern: spy on `apiGet`, `renderHook`, assert the call argument string.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/hooks/useStudents.test.tsx`
Expected: FAIL — `StudentListParams` has no `schuljahrId` field yet / the built query string doesn't include it.

- [ ] **Step 4: Update the hook**

In `frontend/src/api/hooks/useStudents.ts`, add `schuljahrId: number | null` to `StudentListParams` and a corresponding line in `buildQuery`:

```ts
export interface StudentListParams {
  bereichId: number | null;
  klasseId: number | null;
  minStufe: number | null;
  nurAuffaellige: boolean;
  offset: number;
  schuljahrId: number | null;
}

function buildQuery(params: StudentListParams): string {
  const query = new URLSearchParams();
  if (params.bereichId !== null) query.set("bereich_id", String(params.bereichId));
  if (params.klasseId !== null) query.set("klasse_id", String(params.klasseId));
  if (params.minStufe !== null) query.set("min_stufe", String(params.minStufe));
  if (params.nurAuffaellige) query.set("nur_auffaellige", "true");
  if (params.schuljahrId !== null) query.set("schuljahr_id", String(params.schuljahrId));
  query.set("offset", String(params.offset));
  return query.toString();
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/hooks/useStudents.test.tsx`
Expected: PASS.

- [ ] **Step 6: Write the failing StudentList test**

Read `frontend/src/pages/StudentList/StudentList.test.tsx` in full first (it has a `BASE_STUDENT` fixture and asserts `useStudents` call args via `toHaveBeenLastCalledWith`). Update `BASE_STUDENT` to include `fehltage: null, fehlstunden: null, klassenbuch_anzahl: null` (so existing tests, which construct history-agnostic students, keep matching the new required fields). Add:

```tsx
it("reads schuljahr from the URL and passes it to useStudents", () => {
  mockUseStudents.mockReturnValue({
    data: { items: [], total: 0, limit: 50, offset: 0 }, isLoading: false, isError: false,
  } as any);
  renderList(["/schueler?schuljahr=27"]);
  expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ schuljahrId: 27 }));
});

it("shows raw counts instead of Ampel-badges and no Benachrichtigt column in history mode", () => {
  mockUseStudents.mockReturnValue({
    data: {
      items: [
        {
          ...BASE_STUDENT,
          zaehlerstand: null,
          letzte_benachrichtigung: null,
          ohne_massnahme_seit_benachrichtigung: null,
          fehltage: 4,
          fehlstunden: 2,
          klassenbuch_anzahl: 3,
        },
      ],
      total: 1, limit: 50, offset: 0,
    },
    isLoading: false, isError: false,
  } as any);
  renderList(["/schueler?schuljahr=27"]);

  expect(screen.getByText("4")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
  expect(screen.getByText("3")).toBeInTheDocument();
  expect(screen.queryByText("Fehlzeiten: –")).not.toBeInTheDocument();
  expect(screen.queryByText("Benachrichtigt")).not.toBeInTheDocument();
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/StudentList/StudentList.test.tsx`
Expected: FAIL — `schuljahrId` isn't read from the URL yet, and the table doesn't branch on history mode.

- [ ] **Step 8: Implement the history-mode branch**

In `frontend/src/pages/StudentList/StudentList.tsx`, read the new param (near the existing `bereich`/`klasse`/`min_stufe` reads):

```ts
  const schuljahrParam = searchParams.get("schuljahr");
  const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;
  const isHistoryMode = schuljahrId !== null;
```

Pass `schuljahrId` into the `useStudents({...})` call. Change the table header (the 4-column `<thead>`) to branch:

```tsx
        <tr>
          <th>Name</th>
          <th>Klasse</th>
          {isHistoryMode ? (
            <>
              <th>Fehltage</th>
              <th>Fehlstunden</th>
              <th>Klassenbuch</th>
            </>
          ) : (
            <>
              <th>Zählerstand</th>
              <th>Benachrichtigt</th>
            </>
          )}
        </tr>
```

and the row rendering similarly — replace the existing Zählerstand/Benachrichtigt `<td>`s with a conditional:

```tsx
          {isHistoryMode ? (
            <>
              <td>{student.fehltage}</td>
              <td>{student.fehlstunden}</td>
              <td>{student.klassenbuch_anzahl}</td>
            </>
          ) : (
            <>
              <td>
                {Object.entries(student.zaehlerstand ?? {}).map(([typ, stand]) => (
                  <StatusBadge
                    key={typ}
                    label={`${ZAEHLERSTAND_LABEL[typ]}: ${stand.erreichte_stufe_nr ?? "–"}`}
                    tone={stufeToTone(stand.erreichte_stufe_nr)}
                  />
                ))}
              </td>
              <td>
                <NotificationFlyout benachrichtigung={student.letzte_benachrichtigung} />
              </td>
            </>
          )}
```

(Read the existing full row-rendering block first — lines 90-117 per the earlier investigation — to place this correctly relative to the Name/Klasse `<td>`s, which are unaffected and stay first in the row regardless of mode.)

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/StudentList/StudentList.test.tsx`
Expected: PASS.

- [ ] **Step 10: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/hooks/useStudents.ts frontend/src/api/hooks/useStudents.test.tsx \
  frontend/src/pages/StudentList/StudentList.tsx frontend/src/pages/StudentList/StudentList.test.tsx
git commit -m "feat: add Schuljahr-Historie mode to the Schülerliste"
```

---

## Task 9: Frontend — Schüler-Detail Historie-Modus

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/hooks/useStudentDetail.ts`
- Modify: `frontend/src/pages/StudentDetail/StudentDetail.tsx`
- Test: `frontend/src/api/hooks/useStudentDetail.test.tsx`
- Test: `frontend/src/pages/StudentDetail/StudentDetail.test.tsx`

**Interfaces:**
- Consumes: the `schuljahr` URL param (Task 7).
- Produces: `useStudentDetail(studentId: number, schuljahrId: number | null)` — signature gains a second required param. `StudentDetail.zaehlerstand: Record<string, Zaehlerstand>` stays a plain (possibly empty) object, matching the backend's Task 6 shape — no type change needed there.

- [ ] **Step 1: Write the failing hook test**

Read `frontend/src/api/hooks/useStudentDetail.test.tsx` in full first. Add:

```tsx
it("includes schuljahr_id in the request and query key when set", async () => {
  const getSpy = vi.spyOn(client, "apiGet").mockResolvedValue({} as any);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  const { result } = renderHook(() => useStudentDetail(7, 27), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  expect(getSpy).toHaveBeenCalledWith("students/7?schuljahr_id=27");
});

it("omits schuljahr_id from the request when null", async () => {
  const getSpy = vi.spyOn(client, "apiGet").mockResolvedValue({} as any);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }

  const { result } = renderHook(() => useStudentDetail(7, null), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  expect(getSpy).toHaveBeenCalledWith("students/7");
});
```

(Match the exact imports already present in the file — `QueryClient`/`QueryClientProvider`/`renderHook`/`waitFor` from the existing test, plus `ReactNode` from `"react"` if not already imported.) Also update the existing `"fetches students/:id and uses studentDetailQueryKey as its query key"` test — it currently calls `useStudentDetail(7)` with one argument; update the call site to `useStudentDetail(7, null)` and update the `studentDetailQueryKey(7)` assertion to match whatever the new key shape is (see Step 4 below — the key becomes `["student-detail", 7, null]` when called with `schuljahrId: null`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/hooks/useStudentDetail.test.tsx`
Expected: FAIL — `useStudentDetail` only takes one argument today.

- [ ] **Step 3: Update the hook**

In `frontend/src/api/hooks/useStudentDetail.ts`, keep `studentDetailQueryKey(studentId)` **unchanged** (its three call sites in `useCreateMeasure.ts`/`useCreateExemption.ts`/`useRevokeExemption.ts` rely on it as an invalidation prefix — TanStack Query's `invalidateQueries` matches by key prefix, so a query keyed `["student-detail", studentId, schuljahrId]` is still invalidated by `invalidateQueries({ queryKey: ["student-detail", studentId] })`; don't touch those three files). Change only `useStudentDetail` itself:

```ts
export function useStudentDetail(studentId: number, schuljahrId: number | null) {
  return useQuery({
    queryKey: [...studentDetailQueryKey(studentId), schuljahrId] as const,
    queryFn: () =>
      apiGet<StudentDetail>(
        schuljahrId !== null ? `students/${studentId}?schuljahr_id=${schuljahrId}` : `students/${studentId}`,
      ),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/hooks/useStudentDetail.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write the failing StudentDetail test**

Read `frontend/src/pages/StudentDetail/StudentDetail.test.tsx` in full first (it mocks `useStudentDetail` wholesale, so update every existing `mockUseStudentDetail.mockReturnValue(...)`/similar call to account for the hook now needing to be invoked with two args — the mock itself doesn't need arg-shape changes, but any assertion on how it was *called* does). Add:

```tsx
it("passes the schuljahr URL param through to useStudentDetail and hides the Zählerstand badges when in history mode", () => {
  mockUseStudentDetail.mockReturnValue({
    data: { ...DETAIL, zaehlerstand: {} },
    isLoading: false,
    isError: false,
  } as any);
  render(
    <MemoryRouter initialEntries={["/schueler/7?schuljahr=27"]}>
      <Routes>
        <Route path="/schueler/:id" element={<StudentDetail />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(mockUseStudentDetail).toHaveBeenLastCalledWith(7, 27);
  expect(screen.queryByText(/Fehlzeiten: /)).not.toBeInTheDocument();
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/StudentDetail/StudentDetail.test.tsx`
Expected: FAIL — `StudentDetail.tsx` doesn't read `useSearchParams` yet and calls `useStudentDetail(studentId)` with one argument.

- [ ] **Step 7: Implement the history-mode wiring**

In `frontend/src/pages/StudentDetail/StudentDetail.tsx`, add `useSearchParams` to the `react-router-dom` import, read the param, and pass it through:

```tsx
import { useParams, useSearchParams } from "react-router-dom";
...
export function StudentDetail() {
  const { id } = useParams<{ id: string }>();
  const studentId = Number(id);
  const [searchParams] = useSearchParams();
  const schuljahrParam = searchParams.get("schuljahr");
  const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;
  const { data: student, isLoading, isError } = useStudentDetail(studentId, schuljahrId);
  const { data: catalog } = useStudentCatalog();
```

For the header Zählerstand badges (lines 37-45 per the earlier investigation), no code change is needed beyond what's already there — `Object.entries({})` (an empty object, which is what the backend now returns for `zaehlerstand` in history mode per Task 6) naturally produces zero badges, satisfying "hides the Zählerstand badges when in history mode" without any conditional. Everything else in the component (the five section components) already receives its arrays straight from `student.fehlzeiten`/`student.klassenbuch`/`student.massnahmen`/`student.ausnahmen`/`student.benachrichtigungen` — since the backend (Task 6) does the filtering, no client-side filtering logic is needed here at all; the component doesn't need to know which mode it's in beyond passing `schuljahrId` into the hook.

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/StudentDetail/StudentDetail.test.tsx`
Expected: PASS.

- [ ] **Step 9: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/hooks/useStudentDetail.ts frontend/src/api/hooks/useStudentDetail.test.tsx \
  frontend/src/pages/StudentDetail/StudentDetail.tsx frontend/src/pages/StudentDetail/StudentDetail.test.tsx
git commit -m "feat: add Schuljahr-Historie mode to Schüler-Detail"
```

---

## Task 10: Frontend — Sync-Einstellungen zeigt das aktuell verwendete Schuljahr

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/Admin/SyncSettings.tsx`
- Test: `frontend/src/pages/Admin/SyncSettings.test.tsx`

**Interfaces:**
- Consumes: `SyncSettings.aktuelles_schuljahr` (new field, mirrors backend Task 4).

- [ ] **Step 1: Update the type**

In `frontend/src/api/types.ts`, change `SyncSettings`:

```ts
export interface SyncSettings {
  sync_interval_cron: string;
  schuljahr_start_cache: string | null;
  letzter_sync_am: string | null;
  aktuelles_schuljahr: { id: number; name: string } | null;
}
```

- [ ] **Step 2: Write the failing test**

Read `frontend/src/pages/Admin/SyncSettings.test.tsx` in full first — update its existing mocked `useSyncSettings` return values to include `aktuelles_schuljahr` (e.g. `null` for the tests that don't care about it). Add:

```tsx
it("shows the schoolyear the sync is currently using", () => {
  vi.mocked(useSyncSettings).mockReturnValue({
    data: {
      sync_interval_cron: "*/30 * * * *",
      schuljahr_start_cache: "2025-09-15",
      letzter_sync_am: "2026-07-29T06:00:00Z",
      aktuelles_schuljahr: { id: 28, name: "2025/2026" },
    },
    isLoading: false,
    isError: false,
  } as any);
  vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
  vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any);

  render(<SyncSettings />);
  expect(screen.getByText(/2025\/2026/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Admin/SyncSettings.test.tsx`
Expected: FAIL — the page doesn't render `aktuelles_schuljahr` anywhere yet.

- [ ] **Step 4: Implement the display**

In `frontend/src/pages/Admin/SyncSettings.tsx`, add a line after the existing "Schuljahresbeginn"/"Letzter Sync" paragraphs:

```tsx
      <p>
        Für den Sync verwendetes Schuljahr:{" "}
        {data.aktuelles_schuljahr ? data.aktuelles_schuljahr.name : "unbekannt (noch kein erfolgreicher Sync)"}
      </p>
```

(Read the existing JSX around the "Schuljahresbeginn"/"Letzter Sync" `<p>` tags first to place this consistently — same section, same styling, just one more line.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/Admin/SyncSettings.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/pages/Admin/SyncSettings.tsx frontend/src/pages/Admin/SyncSettings.test.tsx
git commit -m "feat: show the schuljahr the sync is using on the Sync-Einstellungen page"
```

---

## Task 11: Documentation

**Files:**
- Modify: `ROADMAP.md`
- Modify: `SPECS.md`
- Modify: `TECH-SPEC.md`

- [ ] **Step 1: Update TECH-SPEC.md**

Add `schuljahr` to the §2 datamodel table (id/name/start_datum/end_datum, "Cache aus getSchoolyears, siehe Abschnitt 1.3a"), add `aktuelles_schuljahr_id` to the `einstellung` row's field list, and update Abschnitt 1.3a's description of how the schoolyear is resolved (replace the outdated "der Sync-Job fragt bei jedem Lauf getCurrentSchoolyear ab..." paragraph with the new resolver behavior: refreshes the `schuljahr` cache from `getSchoolyears`, then tries `getCurrentSchoolyear`, falling back to the newest cached entry if WebUntis has none — note the live-verified reason why this was needed: `getKlassen` itself fails with the same NPE as `getCurrentSchoolyear` unless given an explicit `schoolyearId`). Add the two new endpoints to the §3 table: the `schuljahr_id` query param on `GET /students`/`GET /students/{id}`, and the `schuljahre`/`aktuelles_schuljahr` additions to `GET /dashboard/nav-options`/`GET /admin/sync-settings`.

- [ ] **Step 2: Update SPECS.md**

Add a short paragraph near §4/§7 (wherever Schülerliste/-Detail are described) documenting the new Schuljahr-Dropdown and history mode: raw counts in the list (including inactive students), date-filtered history sections in Detail except Maßnahmen, no manual override anywhere.

- [ ] **Step 3: Update ROADMAP.md**

Move the "Schuljahr-Auswahl/-Historie" entry from "Geplant" to "Abgeschlossen" as **Plan 13**, following the exact table-row format of existing entries, linking to `docs/superpowers/plans/2026-07-30-schuljahr-auswahl.md`, and noting explicitly that this plan also fixed the live sync outage discovered the same day (superseding the narrower `47d7e55` hotfix).

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md SPECS.md TECH-SPEC.md
git commit -m "docs: sync SPECS.md, TECH-SPEC.md and ROADMAP.md with the schuljahr-auswahl plan"
```
