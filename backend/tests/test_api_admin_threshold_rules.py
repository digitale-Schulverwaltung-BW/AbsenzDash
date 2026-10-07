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
async def test_put_threshold_rules_replaces_schulweit_rule_with_new_one(db_session):
    """Regression: die alte schulweite Regel wird implizit gelöscht (id fehlt im Payload), während
    im selben Request eine neue schulweite Regel desselben typs angelegt wird. Ohne ein `flush()`
    der Löschungen VOR dem ersten Insert kollidiert das INSERT mit dem noch vorhandenen alten Satz
    im partiellen Unique-Index `uq_schwellwert_regel_schulweit` (bisher: unbehandelter 500er)."""
    alte_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(alte_regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=alte_regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=4,
            fehlzeiten_filter="nur_unentschuldigt", empfaenger_rollen=["klassenlehrkraft"],
        )
    )
    await db_session.commit()

    payload = [_regel_payload(stufen=[_stufe_payload(schwellenwert=10)])]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    schulweite = [r for r in body if r["typ"] == "fehlzeiten" and r["geltungsbereich"] == "schulweit"]
    assert len(schulweite) == 1
    assert schulweite[0]["id"] != alte_regel.id
    assert schulweite[0]["stufen"][0]["schwellenwert"] == 10

    remaining = await db_session.execute(select(SchwellwertRegel))
    assert [r.id for r in remaining.scalars().all()] == [schulweite[0]["id"]]


@pytest.mark.asyncio
async def test_put_threshold_rules_reorders_stufe_nr(db_session):
    """Regression: Vertauschen von stufe_nr 1<->2 auf zwei bestehenden Stufen derselben Regel.
    Ein naives In-Place-Update erzeugt zwischenzeitlich ein doppeltes (regel_id, stufe_nr)-Paar und
    verletzt `uq_schwellwert_stufe_regel_stufe_nr` (bisher: unbehandelter 500er). Die Stufen-ids
    müssen dabei stabil bleiben."""
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    stufe_a = SchwellwertStufe(
        regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=4,
        fehlzeiten_filter="nur_unentschuldigt", empfaenger_rollen=["klassenlehrkraft"],
    )
    stufe_b = SchwellwertStufe(
        regel_id=regel.id, stufe_nr=2, einheit="fehltage", schwellenwert=8,
        fehlzeiten_filter="nur_unentschuldigt", empfaenger_rollen=["klassenlehrkraft"],
    )
    db_session.add_all([stufe_a, stufe_b])
    await db_session.commit()

    payload = [
        _regel_payload(
            id=regel.id,
            stufen=[
                _stufe_payload(id=stufe_a.id, stufe_nr=2, schwellenwert=4),
                _stufe_payload(id=stufe_b.id, stufe_nr=1, schwellenwert=8),
            ],
        )
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    stufen_by_id = {s["id"]: s for s in body[0]["stufen"]}
    assert set(stufen_by_id) == {stufe_a.id, stufe_b.id}
    assert stufen_by_id[stufe_a.id]["stufe_nr"] == 2
    assert stufen_by_id[stufe_a.id]["schwellenwert"] == 4
    assert stufen_by_id[stufe_b.id]["stufe_nr"] == 1
    assert stufen_by_id[stufe_b.id]["schwellenwert"] == 8


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_duplicate_id_in_payload(db_session):
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.commit()

    payload = [
        _regel_payload(id=regel.id),
        _regel_payload(id=regel.id, typ="klassenbuch", stufen=[_stufe_payload(einheit=None)]),
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 422
    assert "Duplicate id in payload" in response.json()["detail"]

    await db_session.rollback()
    unchanged = await db_session.execute(select(SchwellwertRegel))
    rows = unchanged.scalars().all()
    assert len(rows) == 1
    assert rows[0].typ == "fehlzeiten"


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
async def test_put_threshold_rules_rejects_new_rule_with_stray_stufe_id(db_session):
    payload = [_regel_payload(stufen=[_stufe_payload(id=999999)])]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422

    remaining = await db_session.execute(select(SchwellwertRegel))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_threshold_rules_accepts_klasse_specific_rule(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.commit()

    payload = [_regel_payload(geltungsbereich="klasse", klasse_id=klasse.id)]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    assert response.json()[0]["klasse_id"] == klasse.id


async def _lege_klassen_an(db_session, schuljahr):
    a1 = Abteilung(webuntis_id=1, name="A1")
    a2 = Abteilung(webuntis_id=2, name="A2")
    db_session.add_all([a1, a2])
    await db_session.flush()
    db_session.add_all(
        [
            Klasse(webuntis_id=1, name="1a", abteilung_id=a1.id, schuljahr_id=schuljahr.id),
            Klasse(webuntis_id=2, name="2a", abteilung_id=a2.id, schuljahr_id=schuljahr.id),
            Klasse(webuntis_id=3, name="3a", abteilung_id=a2.id, schuljahr_id=schuljahr.id),
            Klasse(webuntis_id=4, name="4a", abteilung_id=None, schuljahr_id=schuljahr.id),
        ]
    )
    await db_session.commit()
    return a1.id


async def _get_coverage():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/threshold-rules/coverage", headers=HEADERS_SCHULLEITUNG)
    assert response.status_code == 200
    return {eintrag["typ"]: eintrag for eintrag in response.json()}


@pytest.mark.asyncio
async def test_coverage_zaehlt_klassen_ohne_regel_bei_nur_abteilungsregel(db_session, schuljahr):
    a1_id = await _lege_klassen_an(db_session, schuljahr)
    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=a1_id))
    await db_session.commit()

    coverage = await _get_coverage()

    assert coverage["fehlzeiten"] == {"typ": "fehlzeiten", "hat_schulweite_regel": False, "klassen_ohne_regel": 3}
    assert coverage["klassenbuch"]["klassen_ohne_regel"] == 4


@pytest.mark.asyncio
async def test_coverage_schulweite_regel_deckt_alles_ab(db_session, schuljahr):
    await _lege_klassen_an(db_session, schuljahr)
    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit"))
    await db_session.commit()

    coverage = await _get_coverage()

    assert coverage["fehlzeiten"] == {"typ": "fehlzeiten", "hat_schulweite_regel": True, "klassen_ohne_regel": 0}


@pytest.mark.asyncio
async def test_coverage_klassenregel_deckt_einzelne_klasse_ab(db_session, schuljahr):
    await _lege_klassen_an(db_session, schuljahr)
    klasse_id = (await db_session.execute(select(Klasse.id).where(Klasse.name == "4a"))).scalar_one()
    db_session.add(SchwellwertRegel(typ="klassenbuch", geltungsbereich="klasse", klasse_id=klasse_id))
    await db_session.commit()

    coverage = await _get_coverage()

    assert coverage["klassenbuch"]["klassen_ohne_regel"] == 3


@pytest.mark.asyncio
async def test_coverage_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/threshold-rules/coverage", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403
