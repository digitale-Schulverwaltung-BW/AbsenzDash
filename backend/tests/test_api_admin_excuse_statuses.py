import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler

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
async def test_get_excuse_statuses_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/excuse-statuses", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_excuse_statuses_creates_status(db_session):
    payload = [{"name": "Attest", "long_name": "Ärztliches Attest", "zaehlt_als_entschuldigt": True, "aktiv": True}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Attest"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_excuse_statuses_updated"))
    assert audit_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_excuse_statuses_deletes_unused_typo_entry(db_session):
    status_row = ExcuseStatus(name="Atest", zaehlt_als_entschuldigt=True, aktiv=True)
    db_session.add(status_row)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 200
    remaining = await db_session.execute(select(ExcuseStatus))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_excuse_statuses_returns_409_when_deleting_used_status(db_session):
    status_row = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    db_session.add_all([status_row, schueler])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 20), start_zeit=1, end_zeit=6,
            excuse_status_id=status_row.id,
        )
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 409
    remaining = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.id == status_row.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_excuse_statuses_can_deactivate_instead_of_delete(db_session):
    status_row = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    db_session.add_all([status_row, schueler])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 20), start_zeit=1, end_zeit=6,
            excuse_status_id=status_row.id,
        )
    )
    await db_session.commit()

    payload = [
        {"id": status_row.id, "name": "Attest", "long_name": None, "zaehlt_als_entschuldigt": True, "aktiv": False}
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    assert response.json()[0]["aktiv"] is False


@pytest.mark.asyncio
async def test_put_excuse_statuses_rejects_duplicate_name(db_session):
    payload = [
        {"name": "Attest", "zaehlt_als_entschuldigt": True, "aktiv": True},
        {"name": "Attest", "zaehlt_als_entschuldigt": False, "aktiv": True},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422
