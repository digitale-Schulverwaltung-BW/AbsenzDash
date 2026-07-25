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
    await scheduler_module._run_main_sync_job(fake_scheduler)

    run_full_sync_mock.assert_awaited_once()
    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == scheduler_module.MAIN_SYNC_JOB_ID
    now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
    next_fire = kwargs["trigger"].get_next_fire_time(None, now)
    assert next_fire.minute == 20


@pytest.mark.asyncio
async def test_run_main_sync_job_reschedules_even_when_sync_raises(monkeypatch, db_session):
    db_session.add(Einstellung(sync_interval_cron="*/25 * * * *"))
    await db_session.commit()

    run_full_sync_mock = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(scheduler_module, "run_full_sync", run_full_sync_mock)

    fake_scheduler = Mock()
    with pytest.raises(RuntimeError, match="boom"):
        await scheduler_module._run_main_sync_job(fake_scheduler)

    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == scheduler_module.MAIN_SYNC_JOB_ID
    now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
    next_fire = kwargs["trigger"].get_next_fire_time(None, now)
    assert next_fire.minute == 25
