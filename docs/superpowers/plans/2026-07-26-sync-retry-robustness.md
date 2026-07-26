# Sync-Orchestrator Retry-Robustheit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two Important-severity findings deliberately deferred from Plan 2 (Backend WebUntis-Sync-Job): the retry loop holds one DB session open across the entire retry window, and a failing/retrying sync run blocks the next regularly scheduled cron sync instead of letting it run independently (TECH-SPEC.md §1.3b).

**Architecture:** `run_full_sync` currently takes one `AsyncSession` and reuses it across all retry attempts with `asyncio.sleep` in between. Change it to take a session **factory** (`async_sessionmaker[AsyncSession]`) and open a fresh session per attempt, closing it before sleeping. Separately, `app/core/scheduler.py`'s `_run_main_sync_job` currently awaits the entire retry sequence before rescheduling the next cron occurrence, which is exactly what blocks the regular cadence. Change it to fire the sync (with its own retry loop) as a background `asyncio.Task` and reschedule the next cron occurrence immediately, independent of how long that task takes.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, APScheduler (`AsyncIOScheduler`), pytest + pytest-asyncio, Postgres via asyncpg.

## Global Constraints

- Commit messages in English (user's global convention).
- Log messages and docstrings in this codebase are German — keep that style in any new/changed log lines or docstrings (see existing `logger.warning("Sync-Lauf fehlgeschlagen ...")`).
- No local Python 3.11 interpreter or venv is set up in this worktree. All test runs in this plan MUST use the persistent Docker container `absenzdash-test-runner`, which already has `requirements-dev.txt` installed and is networked to the running `absenzdash-db` Postgres container (network `backend_default`). Run tests via:
  ```bash
  docker exec absenzdash-test-runner python -m pytest -q <args>
  ```
  from anywhere (no need to `cd`; the container's workdir `/app` is already bind-mounted to this worktree's `backend/` directory, so file edits are picked up immediately — no rebuild/restart needed).
- Do not modify anything under `.venv/` — there isn't one; don't create one either, the Docker container is the only test runner needed.
- Don't add concurrency locking/mutex protection between overlapping sync runs — TECH-SPEC.md §1.3b explicitly requires the next regular run to proceed independently even while a previous one is still retrying, so overlapping execution is expected behavior, not a bug to guard against.

---

### Task 1: Fresh DB session per retry attempt in `run_full_sync`

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py:1-81` (imports + `run_full_sync`)
- Modify: `backend/tests/test_sync_orchestrator.py:1-88` (call-site updates + import)

**Interfaces:**
- Produces: `run_full_sync(session_factory: async_sessionmaker[AsyncSession]) -> None` — signature change from the current `run_full_sync(db: AsyncSession) -> None`. Task 2 (scheduler.py) depends on this new signature: it will call `run_full_sync(async_session_factory)`, passing the `async_session_factory` object from `app.core.database` directly (not a session instance).

- [ ] **Step 1: Update the failing tests first (call-site + import)**

Edit `backend/tests/test_sync_orchestrator.py`. Add the import at the top (after the existing imports):

```python
from app.core.database import async_session_factory
```

Then replace every `sync_orchestrator.run_full_sync(db_session)` call (there are 4 occurrences, in `test_run_full_sync_sets_letzter_sync_am_and_initial_import_flag`, `test_run_full_sync_calls_phases_in_order`, `test_run_full_sync_retries_on_failure_and_succeeds`, `test_run_full_sync_gives_up_after_max_attempts`) with:

```python
    await sync_orchestrator.run_full_sync(async_session_factory)
```

Keep the `db_session` fixture parameter in each test signature unchanged — it's still used afterward in these tests to query the DB state (e.g. `await db_session.execute(select(Einstellung))`), and it's a separate session against the same Postgres instance/engine, so it will see whatever `run_full_sync` committed via its own internal sessions.

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_sync_orchestrator.py -v
```

Expected: FAIL — `TypeError` or `AttributeError`-style errors, since `run_full_sync` doesn't yet accept a session factory (it still expects/uses `db` as an `AsyncSession` and will error when methods like `.execute` are called on the sessionmaker object instead).

- [ ] **Step 3: Update `run_full_sync`'s signature and body**

In `backend/app/services/sync_orchestrator.py`, change the import line:

```python
from sqlalchemy.ext.asyncio import AsyncSession
```

to:

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
```

Then replace the entire `run_full_sync` function (lines 65-81) with:

```python
async def run_full_sync(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Orchestriert einen vollstaendigen WebUntis-Sync-Lauf mit Retry (TECH-SPEC.md Abschnitt 1.3b).

    Oeffnet pro Versuch eine frische DB-Session statt eine einzige Session ueber
    die komplette Retry-Wartezeit (bis zu ~2h bei Default-Settings) offenzuhalten.
    """
    max_attempts = settings.webuntis_sync_retry_max_attempts
    delay_seconds = settings.webuntis_sync_retry_delay_minutes * 60

    for attempt in range(1, max_attempts + 1):
        try:
            async with session_factory() as db:
                await _run_once(db)
            return
        except (WebUntisError, OSError) as exc:
            logger.warning("Sync-Lauf fehlgeschlagen (Versuch %d/%d): %s", attempt, max_attempts, exc)
            if attempt == max_attempts:
                logger.error("Sync-Lauf endgueltig abgebrochen nach %d Versuchen", max_attempts)
                return
            await asyncio.sleep(delay_seconds)
```

Note what changed: the session is now opened fresh inside the loop via `async with session_factory() as db:`, scoped to just the `_run_once` call for that attempt. The old explicit `await db.rollback()` is removed — it's no longer needed because exiting the `async with` block on exception closes that attempt's session, which discards its uncommitted transaction (equivalent to a rollback), and the next attempt gets an entirely fresh session/connection instead of a reused, possibly-broken one. The `await asyncio.sleep(delay_seconds)` now runs after the session is already closed, so no DB connection is held idle during the wait.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_sync_orchestrator.py -v
```

Expected: PASS — all tests in this file green, including `test_run_full_sync_gives_up_after_max_attempts` which verifies no `Einstellung` row (or no `letzter_sync_am`) persists after all attempts fail (proving the discarded-transaction-per-attempt behavior works correctly against the real Postgres test DB).

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Expected: PASS — `test_scheduler.py` tests will now fail here because they still call `run_full_sync(db)` indirectly through `scheduler.py`'s current code — that's expected and fixed in Task 2. If anything else fails, stop and investigate before proceeding.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py
git commit -m "fix: open a fresh DB session per sync retry attempt

Avoids holding one DB connection idle across the entire retry window
(up to ~90 min at default settings)."
```

---

### Task 2: Decouple retry backoff from the regular sync cadence

**Files:**
- Modify: `backend/app/core/scheduler.py:1-50`
- Modify: `backend/tests/test_scheduler.py:1-81`

**Interfaces:**
- Consumes: `run_full_sync(session_factory: async_sessionmaker[AsyncSession]) -> None` from Task 1.
- Produces: `_run_main_sync_job(scheduler: AsyncIOScheduler) -> asyncio.Task[None]` — return type changes from `None` to the created background `asyncio.Task`, so tests (and nothing else — it's only ever invoked by APScheduler as a job callback, which ignores the return value) can `await` it to know when the background sync has finished.

- [ ] **Step 1: Write the new/updated failing tests**

Replace the entire contents of `backend/tests/test_scheduler.py` with:

```python
import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import scheduler as scheduler_module
from app.models.einstellung import Einstellung


@pytest.mark.asyncio
async def test_start_scheduler_registers_job_with_configured_cron(db_session):
    db_session.add(Einstellung(sync_interval_cron="*/15 * * * *"))
    await db_session.commit()

    scheduler = scheduler_module.create_scheduler()
    try:
        await scheduler_module.start_scheduler(scheduler)
        job = scheduler.get_job(scheduler_module.MAIN_SYNC_JOB_ID)
        assert job is not None

        now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
        next_fire = job.trigger.get_next_fire_time(None, now)
        assert next_fire.minute == 15
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_start_scheduler_falls_back_to_default_cron_without_einstellung(db_session):
    scheduler = scheduler_module.create_scheduler()
    try:
        await scheduler_module.start_scheduler(scheduler)
        job = scheduler.get_job(scheduler_module.MAIN_SYNC_JOB_ID)
        assert job is not None

        now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
        next_fire = job.trigger.get_next_fire_time(None, now)
        assert next_fire.minute == 30
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_run_main_sync_job_runs_sync_and_reschedules(monkeypatch, db_session):
    db_session.add(Einstellung(sync_interval_cron="*/20 * * * *"))
    await db_session.commit()

    run_full_sync_mock = AsyncMock()
    monkeypatch.setattr(scheduler_module, "run_full_sync", run_full_sync_mock)

    fake_scheduler = Mock()
    task = await scheduler_module._run_main_sync_job(fake_scheduler)
    await task

    run_full_sync_mock.assert_awaited_once()
    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == scheduler_module.MAIN_SYNC_JOB_ID
    now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
    next_fire = kwargs["trigger"].get_next_fire_time(None, now)
    assert next_fire.minute == 20


@pytest.mark.asyncio
async def test_run_main_sync_job_reschedules_without_waiting_for_sync_to_finish(monkeypatch, db_session):
    """Regression test for TECH-SPEC.md §1.3b: a still-retrying sync run must
    not block the next regular cron occurrence from being scheduled."""
    db_session.add(Einstellung(sync_interval_cron="*/20 * * * *"))
    await db_session.commit()

    sync_started = asyncio.Event()
    release_sync = asyncio.Event()

    async def _slow_sync(_session_factory):
        sync_started.set()
        await release_sync.wait()

    monkeypatch.setattr(scheduler_module, "run_full_sync", _slow_sync)

    fake_scheduler = Mock()
    task = await scheduler_module._run_main_sync_job(fake_scheduler)
    await asyncio.wait_for(sync_started.wait(), timeout=1)

    # The sync is still blocked on release_sync at this point, yet the job
    # must already have rescheduled the next regular occurrence.
    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == scheduler_module.MAIN_SYNC_JOB_ID
    now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
    next_fire = kwargs["trigger"].get_next_fire_time(None, now)
    assert next_fire.minute == 20

    release_sync.set()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_run_main_sync_job_logs_unexpected_sync_errors_without_propagating(monkeypatch, db_session, caplog):
    db_session.add(Einstellung(sync_interval_cron="*/25 * * * *"))
    await db_session.commit()

    run_full_sync_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(scheduler_module, "run_full_sync", run_full_sync_mock)

    fake_scheduler = Mock()
    with caplog.at_level(logging.ERROR):
        task = await scheduler_module._run_main_sync_job(fake_scheduler)
        await task

    run_full_sync_mock.assert_awaited_once()
    assert "boom" in caplog.text
    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == scheduler_module.MAIN_SYNC_JOB_ID
    now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
    next_fire = kwargs["trigger"].get_next_fire_time(None, now)
    assert next_fire.minute == 25
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_scheduler.py -v
```

Expected: FAIL — `_run_main_sync_job` currently returns `None`, so `await task` (where `task = await scheduler_module._run_main_sync_job(...)`) will raise `TypeError: object NoneType can't be used in 'await' expression` in the three tests that call it.

- [ ] **Step 3: Update `scheduler.py`**

Replace the full contents of `backend/app/core/scheduler.py` with:

```python
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.einstellung import Einstellung
from app.services.sync_orchestrator import run_full_sync

logger = logging.getLogger(__name__)

MAIN_SYNC_JOB_ID = "webuntis_main_sync"


async def _read_sync_interval_cron() -> str:
    async with async_session_factory() as db:
        result = await db.execute(select(Einstellung))
        einstellung = result.scalars().first()
        return einstellung.sync_interval_cron if einstellung else "*/30 * * * *"


async def _run_sync_task() -> None:
    try:
        await run_full_sync(async_session_factory)
    except Exception:
        logger.exception("Unerwarteter Fehler im Sync-Hintergrund-Task")


async def _run_main_sync_job(scheduler: AsyncIOScheduler) -> asyncio.Task[None]:
    """Stoesst den Sync-Lauf (inkl. seiner eigenen Retry-Logik) als
    Hintergrund-Task an und plant den naechsten regulaeren Cron-Termin sofort
    neu — unabhaengig davon, wie lange der Sync-Lauf (mit Retries bis zu ~2h)
    noch braucht (TECH-SPEC.md Abschnitt 1.3b)."""
    task = asyncio.create_task(_run_sync_task())
    cron_expr = await _read_sync_interval_cron()
    scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=CronTrigger.from_crontab(cron_expr))
    return task


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    cron_expr = await _read_sync_interval_cron()
    logger.info(f"Registering {MAIN_SYNC_JOB_ID} job with cron expression: {cron_expr}")
    scheduler.add_job(
        _run_main_sync_job,
        trigger=CronTrigger.from_crontab(cron_expr),
        id=MAIN_SYNC_JOB_ID,
        args=[scheduler],
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started with {MAIN_SYNC_JOB_ID} job registered")
```

Key points for whoever implements this:
- `_run_sync_task` wraps `run_full_sync` in a `try/except Exception` purely so that an unexpected error doesn't turn into a silent "Task exception was never retrieved" warning from asyncio (since nothing else ever awaits this background task in production) — it's still logged loudly via `logger.exception`, consistent with the project's "kein stiller Datenverlust" principle already stated in TECH-SPEC.md §1.3b for the retry loop itself.
- `_run_main_sync_job` creates the background task **first**, then awaits `_read_sync_interval_cron()` and reschedules — so the reschedule always happens quickly regardless of how long the sync itself takes.
- Reference `run_full_sync` and `async_session_factory` by their bare module-level names (as already imported) rather than via a local alias, so `monkeypatch.setattr(scheduler_module, "run_full_sync", ...)` in tests keeps working exactly as it did before.

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_scheduler.py -v
```

Expected: PASS — all 5 tests green, including `test_run_main_sync_job_reschedules_without_waiting_for_sync_to_finish`, which directly proves the fix (reschedule happens while the sync mock is still blocked).

- [ ] **Step 5: Run the full test suite**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Expected: PASS — all tests, including Task 1's `test_sync_orchestrator.py`, now green together (57 tests before this plan, net +2 from the new scheduler test = 59; run the suite and confirm the actual final count with 0 failures).

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/scheduler.py backend/tests/test_scheduler.py
git commit -m "fix: decouple sync retry backoff from the regular cron cadence

A sync run that is still retrying (up to ~2h) no longer blocks the next
regularly scheduled sync from starting, per TECH-SPEC.md 1.3b."
```

---

### Task 3: Update ROADMAP.md to close out the tech-debt entry

**Files:**
- Modify: `ROADMAP.md` (repo root, section "Bekannte offene technische Schulden")

**Interfaces:**
- None — documentation-only change, no code interfaces involved.

- [ ] **Step 1: Remove the resolved tech-debt bullet**

In `ROADMAP.md`, find the section:

```markdown
## Bekannte offene technische Schulden

- **Sync-Orchestrator-Retry-Robustheit** (aus Plan 2, bewusst zurückgestellt): DB-Session bleibt über den gesamten Retry-Loop offen (bis zu ~90 Min bei Default-Settings); ein fehlgeschlagener Lauf blockiert den nächsten regulären Cron-Termin statt unabhängig davon zu laufen (Abweichung von TECH-SPEC.md §1.3b). Siehe Memory `plan2_known_followups` für Details.
```

Remove that section entirely (the whole `## Bekannte offene technische Schulden` heading plus its one bullet), since both findings are now fixed and there are no other entries in it. Also update the `Stand:` date at the top of the file to today's date.

- [ ] **Step 2: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: close out sync-orchestrator retry-robustness tech debt in ROADMAP"
```
