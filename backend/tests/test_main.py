import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import scheduler as scheduler_module
from app.main import app, lifespan
from app.models.einstellung import Einstellung


@pytest.mark.asyncio
async def test_health_check_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_lifespan_shutdown_cancels_pending_sync_task(monkeypatch, db_session):
    """Regression test for the shutdown-robustness follow-up flagged in the
    review of commit 1ce9bd4: app shutdown must cancel and await any in-flight
    sync background task instead of abandoning it silently."""
    db_session.add(Einstellung(sync_interval_cron="*/20 * * * *"))
    await db_session.commit()

    sync_started = asyncio.Event()
    release_sync = asyncio.Event()

    async def _slow_sync(_session_factory):
        sync_started.set()
        await release_sync.wait()

    monkeypatch.setattr(scheduler_module, "run_full_sync", _slow_sync)

    task = None

    async def _drive_lifespan():
        nonlocal task
        async with lifespan(app):
            task = await scheduler_module._run_main_sync_job(app.state.scheduler)
            await asyncio.wait_for(sync_started.wait(), timeout=1)
            assert task in scheduler_module._background_sync_tasks

    await asyncio.wait_for(_drive_lifespan(), timeout=2)

    assert task.done()
    assert task.cancelled()
    assert scheduler_module._background_sync_tasks == set()
