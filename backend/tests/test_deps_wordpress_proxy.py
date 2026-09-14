import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_wordpress_proxy_nutzer
from app.core.config import settings
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.nutzer import Nutzer

test_app = FastAPI()


@test_app.get("/whoami")
async def whoami(nutzer: Nutzer = Depends(get_wordpress_proxy_nutzer)):
    return {"id": nutzer.id, "rolle": nutzer.rolle}


HEADERS_BASE = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Jörg Seyfried".encode("latin-1"),
    "X-WordPress-Role": "klassenlehrkraft",
    "X-WordPress-WebUntis-Code": "63",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_rejects_wrong_secret():
    transport = ASGITransport(app=test_app)
    headers = {**HEADERS_BASE, "X-WordPress-Secret": "wrong"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_unknown_role():
    transport = ASGITransport(app=test_app)
    headers = {**HEADERS_BASE, "X-WordPress-Role": "hausmeister"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_creates_nutzer_on_first_proxy_request(db_session):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=HEADERS_BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["rolle"] == "klassenlehrkraft"

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    nutzer = result.scalar_one()
    assert nutzer.webuntis_teacher_id == 63

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "nutzer"))
    audit_entries = audit_result.scalars().all()
    assert len(audit_entries) == 1
    assert audit_entries[0].aktion == "wordpress_proxy_created"


@pytest.mark.asyncio
async def test_updates_existing_nutzer_on_repeat_request(db_session):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/whoami", headers=HEADERS_BASE)
        headers_updated_role = {**HEADERS_BASE, "X-WordPress-Role": "bereichsleiter"}
        response = await client.get("/whoami", headers=headers_updated_role)

    assert response.status_code == 200
    assert response.json()["rolle"] == "bereichsleiter"

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    assert len(result.scalars().all()) == 1  # kein Duplikat


@pytest.mark.asyncio
async def test_identical_repeat_request_does_not_create_second_audit_entry(db_session):
    """M-3: ein unveraendertes Repeat-Request darf keinen zweiten AuditLog-Eintrag erzeugen."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/whoami", headers=HEADERS_BASE)
        response = await client.get("/whoami", headers=HEADERS_BASE)

    assert response.status_code == 200

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "nutzer"))
    audit_entries = audit_result.scalars().all()
    assert len(audit_entries) == 1
    assert audit_entries[0].aktion == "wordpress_proxy_created"


@pytest.mark.asyncio
async def test_rejects_non_numeric_webuntis_code():
    transport = ASGITransport(app=test_app)
    headers = {**HEADERS_BASE, "X-WordPress-WebUntis-Code": "abc"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_decodes_utf8_name_header_without_mojibake(db_session):
    """A UTF-8-sending WordPress proxy must not corrupt umlauts in Nutzer.name.

    Starlette always decodes incoming header bytes as Latin-1. If the proxy
    actually sent UTF-8 bytes for the name, that decode alone would produce
    mojibake (e.g. "Jörg" -> "JÃ¶rg"). get_wordpress_proxy_nutzer must recover
    the original UTF-8 text before storing it.
    """
    transport = ASGITransport(app=test_app)
    headers = {**HEADERS_BASE, "X-WordPress-Name": "Jörg Müller".encode("utf-8")}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=headers)
    assert response.status_code == 200

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    nutzer = result.scalar_one()
    assert nutzer.name == "Jörg Müller"
