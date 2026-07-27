import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_schulleitung
from app.core.config import settings
from app.models.nutzer import Nutzer

admin_test_app = FastAPI()


@admin_test_app.get("/schulleitung-only")
async def schulleitung_only(nutzer: Nutzer = Depends(require_schulleitung)):
    return {"id": nutzer.id}


HEADERS_BASE = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_require_schulleitung_allows_schulleitung(db_session):
    transport = ASGITransport(app=admin_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/schulleitung-only", headers={**HEADERS_BASE, "X-WordPress-Role": "schulleitung"}
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_require_schulleitung_rejects_klassenlehrkraft(db_session):
    transport = ASGITransport(app=admin_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/schulleitung-only", headers={**HEADERS_BASE, "X-WordPress-Role": "klassenlehrkraft"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_require_schulleitung_rejects_bereichsleiter(db_session):
    transport = ASGITransport(app=admin_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/schulleitung-only", headers={**HEADERS_BASE, "X-WordPress-Role": "bereichsleiter"}
        )
    assert response.status_code == 403
