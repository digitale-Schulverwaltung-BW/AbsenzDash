from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisError
from app.main import app
from app.models.audit_log import AuditLog
from app.services.sync_orchestrator import SyncAlreadyRunningError

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
async def test_post_sync_now_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_sync_now_returns_ok_and_logs_audit_entry(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    monkeypatch.setattr(admin_module, "run_sync_once", AsyncMock())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    admin_module.run_sync_once.assert_awaited_once()
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_sync_now_triggered"))
    audit_row = audit_result.scalar_one()
    assert audit_row.details == {"status": "ok"}


@pytest.mark.asyncio
async def test_post_sync_now_returns_409_when_sync_already_running(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    mock_run_once = AsyncMock(side_effect=SyncAlreadyRunningError("bereits aktiv"))
    monkeypatch.setattr(admin_module, "run_sync_once", mock_run_once)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 409
    mock_run_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_sync_now_returns_502_on_webuntis_error_without_retry(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    mock_run_once = AsyncMock(side_effect=WebUntisError("boom"))
    monkeypatch.setattr(admin_module, "run_sync_once", mock_run_once)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 502
    mock_run_once.assert_awaited_once()

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_sync_now_triggered"))
    audit_row = audit_result.scalar_one()
    assert audit_row.details == {"status": "fehler"}
