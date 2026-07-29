from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse

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
async def test_get_klassen_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/klassen", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_klassen_returns_all_klassen(db_session):
    db_session.add(Klasse(webuntis_id=1, name="1BFE"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/klassen", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "1BFE"}] or response.json()[0]["name"] == "1BFE"


@pytest.mark.asyncio
async def test_get_bereiche_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_bereiche_creates_and_logs_audit(db_session):
    payload = [{"name": "Mechatronik", "klasse_ids": [], "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Mechatronik"

    audit = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_bereiche_updated"))
    assert audit.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_bereiche_rejects_unknown_klasse_id(db_session):
    payload = [{"name": "Mechatronik", "klasse_ids": [999999], "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


from app.models.abteilung import Abteilung


@pytest.mark.asyncio
async def test_get_vorschlag_aus_abteilungen_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche/vorschlag-aus-abteilungen", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_vorschlag_aus_abteilungen_returns_one_per_abteilung(db_session):
    db_session.add(Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche/vorschlag-aus-abteilungen", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json() == [{"name": "Mechatronik", "klasse_ids": []}]
