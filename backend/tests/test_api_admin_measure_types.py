import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schwellwert_regel import SchwellwertRegel

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
async def test_get_measure_types_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/measure-types", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_measure_types_creates_type(db_session):
    payload = [{"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True, "betroffene_regel_ids": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Nachsitzen"
    assert body[0]["aktiv"] is True

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_measure_types_updated"))
    assert audit_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_measure_types_upserts_and_reassigns_betroffene_regeln(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    regel_a = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    regel_b = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    db_session.add_all([typ, regel_a, regel_b])
    await db_session.commit()

    payload = [
        {
            "id": typ.id, "name": "Nachsitzen", "setzt_zaehler_zurueck": True,
            "aktiv": False, "betroffene_regel_ids": [regel_a.id, regel_b.id],
        }
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == typ.id
    assert body[0]["aktiv"] is False
    assert sorted(body[0]["betroffene_regel_ids"]) == sorted([regel_a.id, regel_b.id])


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_when_deleting_used_type(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([typ, schueler, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 1, 20),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 409

    remaining = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == typ.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_when_deleting_used_type_alongside_new_type(db_session):
    """Regression test: the in-use type is deleted implicitly (omitted from payload) while a
    brand-new type is created in the same request. Creating a new type calls `await db.flush()`
    (to obtain its id for the massnahmen_typ_regel association) before the final `db.commit()`.
    That explicit flush also flushes the pending delete of the in-use type, so the FK violation
    surfaces there. If that flush isn't inside the try/except around IntegrityError, it propagates
    as an unhandled 500 instead of the documented 409 (see brief's own test, which only sends an
    empty payload and never reaches this flush call)."""
    used_typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([used_typ, schueler, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=used_typ.id,
            datum=datetime.date(2026, 1, 20),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    payload = [
        {"name": "Neuer Typ", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []}
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 409

    remaining = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == used_typ.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_with_name_conflict_message(db_session):
    """Regression: die IntegrityError-Ursache ist hier eine UNIQUE-Verletzung auf `name` (der neue
    Typ wird eingefügt, bevor die Umbenennung des bestehenden Typs den Namen freigibt) — kein
    FK-in-Verwendung-Konflikt. Die alte Sammelmeldung war faktisch falsch und rendert mit leerer
    `removed_names`-Liste sogar als '... bereits verwendet: .'."""
    bestehend = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    db_session.add(bestehend)
    await db_session.commit()

    payload = [
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []},
        {
            "id": bestehend.id, "name": "Bußgeld", "setzt_zaehler_zurueck": True,
            "aktiv": True, "betroffene_regel_ids": [],
        },
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Name bereits vergeben" in detail
    assert "bereits verwendet" not in detail

    await db_session.rollback()
    remaining = await db_session.execute(select(MassnahmenTyp))
    rows = remaining.scalars().all()
    assert [r.name for r in rows] == ["Nachsitzen"]


@pytest.mark.asyncio
async def test_put_measure_types_rejects_duplicate_id_in_payload(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    db_session.add(typ)
    await db_session.commit()

    payload = [
        {"id": typ.id, "name": "A", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []},
        {"id": typ.id, "name": "B", "setzt_zaehler_zurueck": True, "aktiv": False, "betroffene_regel_ids": []},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 422
    assert "Duplicate id in payload" in response.json()["detail"]

    await db_session.rollback()
    remaining = await db_session.execute(select(MassnahmenTyp))
    rows = remaining.scalars().all()
    assert [(r.name, r.setzt_zaehler_zurueck) for r in rows] == [("Nachsitzen", True)]


@pytest.mark.asyncio
async def test_put_measure_types_deletes_unused_type(db_session):
    typ = MassnahmenTyp(name="Tippfehler", setzt_zaehler_zurueck=False, aktiv=True)
    db_session.add(typ)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 200
    remaining = await db_session.execute(select(MassnahmenTyp))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_measure_types_rejects_duplicate_name(db_session):
    payload = [
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True, "betroffene_regel_ids": []},
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_measure_types_rejects_empty_name(db_session):
    payload = [{"name": "   ", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_measure_types_rejects_unknown_regel_id(db_session):
    payload = [
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True, "betroffene_regel_ids": [999999]}
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_measure_types_rejects_unknown_id(db_session):
    payload = [
        {"id": 999999, "name": "X", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []}
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422
