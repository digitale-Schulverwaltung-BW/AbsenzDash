from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog

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
async def test_post_test_email_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/test-email", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_test_email_sends_to_authenticated_user_and_logs_audit_entry(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    mock_send_email = AsyncMock()
    monkeypatch.setattr(admin_module.mailer, "send_email", mock_send_email)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/test-email", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["empfaenger"] == "joerg.seyfried@hhs.karlsruhe.de"

    mock_send_email.assert_awaited_once()
    to_addresses = mock_send_email.await_args.args[1]
    assert to_addresses == ["joerg.seyfried@hhs.karlsruhe.de"]

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_test_email_sent"))
    audit_row = audit_result.scalar_one()
    assert audit_row.details == {"status": "ok", "empfaenger": "joerg.seyfried@hhs.karlsruhe.de"}


@pytest.mark.asyncio
async def test_post_test_email_returns_502_on_smtp_error(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    mock_send_email = AsyncMock(side_effect=OSError("smtp boom"))
    monkeypatch.setattr(admin_module.mailer, "send_email", mock_send_email)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/test-email", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 502

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_test_email_sent"))
    audit_row = audit_result.scalar_one()
    assert audit_row.details == {"status": "fehler", "empfaenger": "joerg.seyfried@hhs.karlsruhe.de"}
