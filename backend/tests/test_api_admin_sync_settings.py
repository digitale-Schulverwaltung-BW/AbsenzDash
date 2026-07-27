import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.scheduler import MAIN_SYNC_JOB_ID, create_scheduler, start_scheduler
from app.main import app
from app.models.audit_log import AuditLog
from app.models.einstellung import Einstellung

HEADERS_SCHULLEITUNG = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "schulleitung",
}
HEADERS_KLASSENLEHRKRAFT = {**HEADERS_SCHULLEITUNG, "X-WordPress-Role": "klassenlehrkraft"}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_get_sync_settings_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/sync-settings", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_sync_settings_returns_defaults_without_existing_einstellung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/sync-settings", headers=HEADERS_SCHULLEITUNG)
    assert response.status_code == 200
    body = response.json()
    assert body["sync_interval_cron"] == "*/30 * * * *"
    assert body["schuljahr_start_cache"] is None
    assert body["letzter_sync_am"] is None


@pytest.mark.asyncio
async def test_put_sync_settings_updates_cron_and_reschedules_live_job(db_session):
    db_session.add(Einstellung(sync_interval_cron="*/30 * * * *"))
    await db_session.commit()

    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/admin/sync-settings", headers=HEADERS_SCHULLEITUNG, json={"sync_interval_cron": "*/15 * * * *"}
            )
        assert response.status_code == 200
        assert response.json()["sync_interval_cron"] == "*/15 * * * *"

        job = scheduler.get_job(MAIN_SYNC_JOB_ID)
        now = datetime.datetime(2026, 1, 1, 10, 3, tzinfo=datetime.timezone.utc)
        assert job.trigger.get_next_fire_time(None, now).minute == 15

        db_result = await db_session.execute(select(Einstellung))
        assert db_result.scalar_one().sync_interval_cron == "*/15 * * * *"

        audit_result = await db_session.execute(
            select(AuditLog).where(AuditLog.aktion == "admin_sync_settings_updated")
        )
        assert audit_result.scalar_one() is not None
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_put_sync_settings_rejects_invalid_cron(db_session):
    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/admin/sync-settings", headers=HEADERS_SCHULLEITUNG, json={"sync_interval_cron": "not-a-cron"}
            )
        assert response.status_code == 422
    finally:
        scheduler.shutdown(wait=False)
