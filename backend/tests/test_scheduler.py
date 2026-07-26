import asyncio
import gc
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
async def test_run_main_sync_job_registers_and_deregisters_task_in_background_set(monkeypatch, db_session):
    """Regression test for the bookkeeping fix in commit e54c3ff: while a sync
    is running, its task must be registered in the module-level
    `_background_sync_tasks` set (the strong reference required per asyncio's
    docs, since the event loop itself only holds a weak one), and the
    done-callback must discard it from that set once the task completes.

    Note: this test does NOT demonstrate GC-survival on its own. While the
    task is suspended on `release_sync.wait()`, the `release_sync`/
    `sync_started` Event objects held by this test function are themselves
    GC roots that transitively keep the task alive (Event._waiters ->
    Future._callbacks -> the task's __wakeup), independent of whether
    `_background_sync_tasks` exists at all. The `gc.collect()` call below is
    kept only as harmless defense-in-depth; the real coverage is the
    set-membership assertions before and after."""
    db_session.add(Einstellung(sync_interval_cron="*/20 * * * *"))
    await db_session.commit()

    sync_started = asyncio.Event()
    release_sync = asyncio.Event()

    async def _slow_sync(_session_factory):
        sync_started.set()
        await release_sync.wait()

    monkeypatch.setattr(scheduler_module, "run_full_sync", _slow_sync)

    fake_scheduler = Mock()
    # Deliberately don't keep our own reference to the returned task anywhere a
    # GC pass could trivially find it.
    await scheduler_module._run_main_sync_job(fake_scheduler)
    await asyncio.wait_for(sync_started.wait(), timeout=1)

    assert len(scheduler_module._background_sync_tasks) == 1
    assert all(not t.done() for t in scheduler_module._background_sync_tasks)

    gc.collect()

    # Still present and still running.
    assert len(scheduler_module._background_sync_tasks) == 1
    assert all(not t.done() for t in scheduler_module._background_sync_tasks)

    release_sync.set()

    async def _wait_until_removed():
        while scheduler_module._background_sync_tasks:
            await asyncio.sleep(0.01)

    # Proves the done-callback fired and discarded the task from the set.
    await asyncio.wait_for(_wait_until_removed(), timeout=1)

    assert scheduler_module._background_sync_tasks == set()


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
