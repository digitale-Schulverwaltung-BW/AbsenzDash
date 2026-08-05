from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.bereich import Bereich

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
async def test_get_bereiche_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_bereiche_returns_klasse_namen_and_ausgeblendet(db_session):
    db_session.add(Bereich(name="Mechatronik", ausgeblendet=True))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    body = response.json()[0]
    assert body["name"] == "Mechatronik"
    assert body["klasse_namen"] == []
    assert body["ausgeblendet"] is True


@pytest.mark.asyncio
async def test_put_bereiche_updates_ausgeblendet_and_logs_audit(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [{"id": bereich.id, "ausgeblendet": True, "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    assert response.json()[0]["ausgeblendet"] is True

    audit = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_bereiche_updated"))
    assert audit.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_bereiche_rejects_unknown_id(db_session):
    payload = [{"id": 999999, "ausgeblendet": False, "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_abteilungen_returns_all(db_session):
    abteilung_a = Abteilung(webuntis_id=1, name="Kaufmännisch")
    abteilung_b = Abteilung(webuntis_id=2, name="Gewerblich")
    db_session.add_all([abteilung_a, abteilung_b])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/abteilungen", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    names = sorted(item["name"] for item in response.json())
    assert names == ["Gewerblich", "Kaufmännisch"]


@pytest.mark.asyncio
async def test_get_abteilungen_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/abteilungen", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403
