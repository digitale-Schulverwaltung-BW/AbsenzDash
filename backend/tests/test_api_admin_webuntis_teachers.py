from httpx import ASGITransport, AsyncClient

import pytest

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisError
from app.main import app

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


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def call(self, method, params):
        assert method == "getTeachers"
        return self._rows


class _FailingClient:
    async def __aenter__(self):
        raise WebUntisError("WebUntis nicht erreichbar")

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_get_webuntis_teachers_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/webuntis-teachers", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_webuntis_teachers_returns_sorted_list(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    monkeypatch.setattr(
        admin_module, "WebUntisClient", lambda settings: _FakeClient([{"id": 1, "name": "ABC", "active": True}])
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/webuntis-teachers", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "kuerzel": "ABC"}]


@pytest.mark.asyncio
async def test_get_webuntis_teachers_returns_502_on_webuntis_error(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    monkeypatch.setattr(admin_module, "WebUntisClient", lambda settings: _FailingClient())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/webuntis-teachers", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 502
