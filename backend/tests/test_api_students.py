import datetime
from datetime import date
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme
from app.models.bereich import Bereich, bereich_klasse
from app.models.benachrichtigung import Benachrichtigung
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schuljahr import Schuljahr
from app.models.schwellwert_regel import SchwellwertRegel

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
    schueler_a = Schueler(externe_id="ext-a", vorname="Max", nachname="Muster", klasse_id=klasse_a.id, aktiv=True)
    schueler_b = Schueler(externe_id="ext-b", vorname="Erika", nachname="Beispiel", klasse_id=klasse_b.id, aktiv=True)
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
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([schueler, regel])
    await db_session.flush()
    db_session.add(SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", aktueller_stand=4, erreichte_stufe_nr=1))
    db_session.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            regel_id=regel.id,
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
    assert item["letzte_benachrichtigung"]["typ"] == "fehlzeiten"
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
            Schueler(externe_id="ext-1", vorname="A", nachname="01", klasse_id=klasse_a.id, aktiv=True),
            Schueler(externe_id="ext-2", vorname="B", nachname="02", klasse_id=klasse_b.id, aktiv=True),
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
async def test_get_student_detail_includes_revoked_ausnahmen(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    aktive_ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="Aktiv", aktiv=True)
    aufgehobene_ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Aufgehoben", aktiv=False)
    db_session.add_all([aktive_ausnahme, aufgehobene_ausnahme])
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    gruende = {a["grund"]: a["aktiv"] for a in body["ausnahmen"]}
    assert gruende == {"Aktiv": True, "Aufgehoben": False}


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


@pytest.mark.asyncio
async def test_create_measure_returns_created_measure_and_writes_audit_log(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    db_session.add_all([schueler, typ])
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/measures",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"massnahmen_typ_id": typ.id, "datum": "2026-02-10", "notiz": "Testnotiz"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["massnahmen_typ_name"] == "Nachsitzen"
    assert body["notiz"] == "Testnotiz"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "massnahme_erfasst"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_create_measure_404s_for_unknown_measure_type(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/measures",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"massnahmen_typ_id": 999999, "datum": "2026-02-10"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_measure_404s_for_out_of_scope_student(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    db_session.add_all([schueler, typ])
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/measures",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"massnahmen_typ_id": typ.id, "datum": "2026-02-10"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_exemption_returns_created_exemption_and_writes_audit_log(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/exemptions",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"kategorie": "fehlzeiten", "grund": "Ärztliches Attest", "gueltig_bis": "2026-12-31"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["kategorie"] == "fehlzeiten"
    assert body["aktiv"] is True

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "ausnahme_erstellt"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_revoke_exemption_sets_inactive_and_writes_audit_log(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Test", aktiv=True)
    db_session.add(ausnahme)
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/students/{schueler.id}/exemptions/{ausnahme.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 204

    # The revoke happens through a separate DB session (the app's `get_db` dependency), so
    # db_session's identity map still holds the pre-revoke `ausnahme` instance (expire_on_commit
    # is False for the app's session factory). Refresh it explicitly to force a fresh read of the
    # row instead of returning the stale cached object.
    await db_session.refresh(ausnahme)
    reloaded = (await db_session.execute(select(Ausnahme).where(Ausnahme.id == ausnahme.id))).scalar_one()
    assert reloaded.aktiv is False

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "ausnahme_aufgehoben"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_revoke_exemption_404s_when_already_revoked(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Test", aktiv=False)
    db_session.add(ausnahme)
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/students/{schueler.id}/exemptions/{ausnahme.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_exemption_404s_for_exemption_belonging_to_different_student(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="Erika", nachname="Beispiel", klasse_id=klasse.id)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler_b.id, kategorie="klassenbuch", grund="Test", aktiv=True)
    db_session.add(ausnahme)
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/students/{schueler_a.id}/exemptions/{ausnahme.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_pdf_returns_pdf_with_all_sections_by_default(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}/export.pdf", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "Muster_Max_export.pdf" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_pdf_filters_by_schuljahr_id(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler, schuljahr])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 2, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"schuljahr_id": schuljahr.id},
        )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_export_pdf_forwards_resolved_schuljahr_zeitraum_to_export_service(db_session, monkeypatch):
    """Route-level Test fuer die schuljahr_id -> (von, bis, schuljahr_name)-Aufloesung: der
    reine Statuscode/PDF-Smoke-Test oben wuerde nicht bemerken, wenn die Route aufhoert, diese
    Werte an export_service.render_student_export_html durchzureichen."""
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler, schuljahr])
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    render_mock = AsyncMock(return_value="<html></html>")
    monkeypatch.setattr("app.api.routes.students.export_service.render_student_export_html", render_mock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"schuljahr_id": schuljahr.id},
        )

    assert response.status_code == 200
    render_mock.assert_awaited_once()
    _, kwargs = render_mock.call_args
    assert kwargs["von"] == date(2024, 9, 9)
    assert kwargs["bis"] == date(2025, 7, 30)
    assert kwargs["schuljahr_name"] == "2024/2025"


@pytest.mark.asyncio
async def test_export_pdf_writes_audit_log_with_requested_sections(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"sections": "fehlzeiten,massnahmen"},
        )

    assert response.status_code == 200
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "export_pdf"))
    entries = audit_result.scalars().all()
    assert len(entries) == 1
    assert entries[0].details == {"sections": ["fehlzeiten", "massnahmen"]}
    assert entries[0].resource_id == str(schueler.id)


@pytest.mark.asyncio
async def test_export_pdf_rejects_unknown_section(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}/export.pdf",
            headers=HEADERS_KLASSENLEHRKRAFT,
            params={"sections": "unbekannt"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_pdf_404s_for_out_of_scope_student(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}/export.pdf", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_students_history_mode_returns_rohzahlen_and_includes_inactive(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    schueler_aktiv = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    schueler_inaktiv = Schueler(externe_id="ext-2", vorname="B", nachname="B", klasse_id=klasse.id, aktiv=False)
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler_aktiv, schueler_inaktiv, schuljahr])
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler_inaktiv.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students?schuljahr_id={schuljahr.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert schueler_inaktiv.id in ids  # inaktive Schueler erscheinen in der Historie
    inaktiv_item = next(item for item in body["items"] if item["id"] == schueler_inaktiv.id)
    assert inaktiv_item["fehltage"] == 1
    assert inaktiv_item["zaehlerstand"] is None


@pytest.mark.asyncio
async def test_get_student_detail_history_mode_filters_four_sections_not_massnahmen(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse.id)
    typ = MassnahmenTyp(name="Gespraech", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u2", email="c@d.de", name="C", rolle="klassenlehrkraft")
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add_all([schueler, typ, nutzer, schuljahr])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Massnahme(schueler_id=schueler.id, massnahmen_typ_id=typ.id, datum=date(2025, 10, 1), erfasst_von_nutzer_id=nutzer.id),
        ]
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}?schuljahr_id={schuljahr.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["fehlzeiten"]) == 1
    assert body["fehlzeiten"][0]["datum"] == "2024-10-01"
    assert len(body["massnahmen"]) == 1  # unabhaengig vom Schuljahr-Filter sichtbar
    assert body["zaehlerstand"] == {}
