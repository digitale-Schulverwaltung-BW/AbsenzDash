import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.bereich import Bereich, bereich_klasse
from app.models.benachrichtigung import Benachrichtigung
from app.models.klasse import Klasse
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand

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


async def _seed_klassenlehrkraft(db_session, klasse_ids):
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    for klasse_id in klasse_ids:
        db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_id, quelle="webuntis_seed"))
    await db_session.commit()
    return nutzer


@pytest.mark.asyncio
async def test_get_students_rejects_missing_wordpress_secret():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-Secret": "wrong"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_students_returns_only_students_in_callers_scope(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="Max", nachname="Muster", klasse_id=klasse_a.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="Erika", nachname="Beispiel", klasse_id=klasse_b.id)
    db_session.add_all([schueler_a, schueler_b])
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [schueler_a.id]
    assert body["items"][0]["klasse"] == {"id": klasse_a.id, "name": "10a"}


@pytest.mark.asyncio
async def test_get_students_response_includes_zaehlerstand_and_letzte_benachrichtigung(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", aktueller_stand=4, erreichte_stufe_nr=1))
    db_session.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            stufe_nr=1,
            gesendet_am=datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc),
            empfaenger=[{"rolle": "klassenlehrkraft", "nutzer_id": 1}],
            status="gesendet",
        )
    )
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["zaehlerstand"]["fehlzeiten"] == {"aktueller_stand": 4, "erreichte_stufe_nr": 1}
    assert item["zaehlerstand"]["klassenbuch"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}
    assert item["letzte_benachrichtigung"]["stufe_nr"] == 1
    assert item["ohne_massnahme_seit_benachrichtigung"] is True


@pytest.mark.asyncio
async def test_get_students_pagination_and_bereich_filter(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_b.id))
    db_session.add_all(
        [
            Schueler(externe_id="ext-1", vorname="A", nachname="01", klasse_id=klasse_a.id),
            Schueler(externe_id="ext-2", vorname="B", nachname="02", klasse_id=klasse_b.id),
        ]
    )
    nutzer = Nutzer(wp_user_id="bereichsleiter1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    headers = {**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-User": "bereichsleiter1", "X-WordPress-Role": "bereichsleiter"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=headers, params={"limit": 1, "offset": 0, "bereich_id": bereich.id})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["nachname"] == "01"


@pytest.mark.asyncio
async def test_get_student_detail_returns_all_sublists(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="lehrkraft1", email="l@b.de", name="Lehrer A", rolle="klassenlehrkraft")
    db_session.add_all([typ, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 5),
            notiz="Elterngespräch geführt",
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}",
            headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-User": "lehrkraft1", "X-WordPress-Name": "Lehrer A"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["klasse"] == {"id": klasse.id, "name": "10a"}
    assert len(body["massnahmen"]) == 1
    assert body["massnahmen"][0]["massnahmen_typ_name"] == "Gespräch"
    assert body["massnahmen"][0]["erfasst_von_name"] == "Lehrer A"
    assert body["fehlzeiten"] == []
    assert body["ausnahmen"] == []


@pytest.mark.asyncio
async def test_get_student_detail_404s_for_out_of_scope_student(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 404
