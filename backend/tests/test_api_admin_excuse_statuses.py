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
async def test_put_excuse_statuses_returns_409_when_deleting_used_status_alongside_other_status(db_session):
    """Regression (analog zu test_put_measure_types_returns_409_when_deleting_used_type_alongside_new_type):
    nicht-leerer Payload — ein anderer Status bleibt/entsteht, während der noch von einer `Fehlzeit`
    referenzierte Status implizit (id fehlt im Payload) gelöscht wird."""
    used_status = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    kept_status = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    db_session.add_all([used_status, kept_status, schueler])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 20), start_zeit=1, end_zeit=6,
            excuse_status_id=used_status.id,
        )
    )
    await db_session.commit()

    payload = [
        {
            "id": kept_status.id, "name": "nicht entsch.", "long_name": None,
            "zaehlt_als_entschuldigt": False, "aktiv": True,
        },
        {"name": "hybrid", "long_name": None, "zaehlt_als_entschuldigt": True, "aktiv": True},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 409
    assert "bereits verwendet" in response.json()["detail"]

    await db_session.rollback()
    remaining = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.id == used_status.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_excuse_statuses_returns_409_with_name_conflict_message(db_session):
    """Regression: der bestehende (unbenutzte) Status wird gelöscht und im selben Payload unter
    demselben Namen neu angelegt. SQLAlchemy schreibt INSERTs vor DELETEs — die Ursache ist also
    eine UNIQUE-Verletzung auf `name`, nicht ein FK-in-Verwendung-Konflikt."""
    alt = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    db_session.add(alt)
    await db_session.commit()

    payload = [
        {"name": "Attest", "long_name": "Ärztliches Attest", "zaehlt_als_entschuldigt": True, "aktiv": True}
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Name bereits vergeben" in detail
    assert "bereits verwendet" not in detail


@pytest.mark.asyncio
async def test_put_excuse_statuses_rejects_duplicate_id_in_payload(db_session):
    status_row = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    db_session.add(status_row)
    await db_session.commit()

    payload = [
        {"id": status_row.id, "name": "A", "long_name": None, "zaehlt_als_entschuldigt": True, "aktiv": True},
        {"id": status_row.id, "name": "B", "long_name": None, "zaehlt_als_entschuldigt": False, "aktiv": False},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 422
    assert "Duplicate id in payload" in response.json()["detail"]

    await db_session.rollback()
    remaining = await db_session.execute(select(ExcuseStatus))
    rows = remaining.scalars().all()
    assert [(r.name, r.aktiv) for r in rows] == [("Attest", True)]


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
