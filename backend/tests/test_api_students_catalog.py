import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.massnahmen_typ import MassnahmenTyp

HEADERS_KLASSENLEHRKRAFT = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "klassenlehrkraft",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_get_catalog_accessible_for_non_schulleitung_role(db_session):
    aktiv_typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False, aktiv=True)
    inaktiv_typ = MassnahmenTyp(name="Alt", setzt_zaehler_zurueck=False, aktiv=False)
    status = ExcuseStatus(name="E", long_name="Entschuldigt", zaehlt_als_entschuldigt=True, aktiv=True)
    kategorie = ClassregCategory(name="LSU", long_name="Lehrstoffunterbrechung")
    db_session.add_all([aktiv_typ, inaktiv_typ, status, kategorie])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students/catalog", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert [t["name"] for t in body["massnahmen_typen"]] == ["Gespräch"]
    assert body["excuse_statuses"] == [{"id": status.id, "name": "E", "long_name": "Entschuldigt"}]
    assert body["classreg_categories"] == [
        {"id": kategorie.id, "name": "LSU", "long_name": "Lehrstoffunterbrechung"}
    ]


@pytest.mark.asyncio
async def test_get_catalog_rejects_missing_wordpress_secret():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/students/catalog", headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-Secret": "wrong"}
        )
    assert response.status_code == 401
