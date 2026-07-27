import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe

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


def _stufe_payload(**overrides):
    base = {
        "stufe_nr": 1,
        "einheit": "fehltage",
        "schwellenwert": 4,
        "fehlzeiten_filter": "nur_unentschuldigt",
        "empfaenger_rollen": ["klassenlehrkraft"],
    }
    base.update(overrides)
    return base


def _regel_payload(**overrides):
    base = {
        "typ": "fehlzeiten",
        "geltungsbereich": "schulweit",
        "abteilung_id": None,
        "klasse_id": None,
        "stufen": [_stufe_payload()],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_get_threshold_rules_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/threshold-rules", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_threshold_rules_creates_rule_with_stufen(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=[_regel_payload()]
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["typ"] == "fehlzeiten"
    assert body[0]["geltungsbereich"] == "schulweit"
    assert len(body[0]["stufen"]) == 1
    assert body[0]["stufen"][0]["schwellenwert"] == 4

    audit_result = await db_session.execute(
        select(AuditLog).where(AuditLog.aktion == "admin_threshold_rules_updated")
    )
    assert audit_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_threshold_rules_upserts_by_id_and_deletes_omitted(db_session):
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    stufe = SchwellwertStufe(
        regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=4,
        fehlzeiten_filter="nur_unentschuldigt", empfaenger_rollen=["klassenlehrkraft"],
    )
    other_regel = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    db_session.add_all([stufe, other_regel])
    await db_session.commit()

    payload = [
        _regel_payload(
            id=regel.id,
            stufen=[_stufe_payload(id=stufe.id, schwellenwert=8)],
        )
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == regel.id
    assert body[0]["stufen"][0]["id"] == stufe.id
    assert body[0]["stufen"][0]["schwellenwert"] == 8

    remaining = await db_session.execute(select(SchwellwertRegel))
    assert [r.id for r in remaining.scalars().all()] == [regel.id]


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_duplicate_schulweit_rule(db_session):
    transport = ASGITransport(app=app)
    payload = [_regel_payload(), _regel_payload()]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422

    remaining = await db_session.execute(select(SchwellwertRegel))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_unknown_klasse_id(db_session):
    transport = ASGITransport(app=app)
    payload = [_regel_payload(geltungsbereich="klasse", klasse_id=999999)]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_rule_without_stufen(db_session):
    transport = ASGITransport(app=app)
    payload = [_regel_payload(stufen=[])]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_threshold_rules_accepts_klasse_specific_rule(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.commit()

    payload = [_regel_payload(geltungsbereich="klasse", klasse_id=klasse.id)]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    assert response.json()[0]["klasse_id"] == klasse.id
