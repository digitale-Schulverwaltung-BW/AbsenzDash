from httpx import ASGITransport, AsyncClient
import pytest

from app.core.config import settings
from app.main import app
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse

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
async def test_get_nav_options_returns_only_scoped_klassen(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard/nav-options", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["bereiche"] == []
    assert [k["id"] for k in body["klassen"]] == [klasse.id]


@pytest.mark.asyncio
async def test_get_stats_rejects_bereich_id_for_klassenlehrkraft():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/dashboard/stats", params={"bereich_id": 1}, headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_stats_returns_klasse_level_for_own_klasse(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard/stats", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "klasse"
    assert body["context"]["klasse_id"] == klasse.id
