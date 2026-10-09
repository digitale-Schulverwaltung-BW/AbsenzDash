from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisError
from app.integrations.webuntis_duty_client import DutyOption, DutyServiceError
from app.main import app
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.klassendienst_typ import KlassendienstTyp
from app.models.schueler import Schueler
from app.models.schueler_klassendienst import SchuelerKlassendienst
from app.services import klassendienst_typ_service

HEADERS_SCHULLEITUNG = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "schulleitung",
}
HEADERS_KLASSENLEHRKRAFT = {**HEADERS_SCHULLEITUNG, "X-WordPress-Role": "klassenlehrkraft"}
HEADERS_BEREICHSLEITUNG = {**HEADERS_SCHULLEITUNG, "X-WordPress-Role": "bereichsleiter"}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


async def _request(method, url, headers=HEADERS_SCHULLEITUNG, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, headers=headers, **kwargs)


def _eintrag(**overrides):
    return {
        "webuntis_dienst_id": 26,
        "bezeichnung": "Entschuldigungspflicht",
        "kuerzel": "E",
        "beschreibung": "Fehlzeiten sind taggleich zu entschuldigen",
        "aktiv": True,
        **overrides,
    }


@pytest.mark.parametrize("headers", [HEADERS_KLASSENLEHRKRAFT, HEADERS_BEREICHSLEITUNG])
@pytest.mark.parametrize(
    "method,url", [("GET", "/admin/klassendienst-typen"), ("PUT", "/admin/klassendienst-typen"), ("GET", "/admin/klassendienst-typen/webuntis-optionen")]
)
async def test_nur_schulleitung(db_session, method, url, headers):
    kwargs = {"json": []} if method == "PUT" else {}
    response = await _request(method, url, headers=headers, **kwargs)
    assert response.status_code == 403


async def test_get_leer_ohne_seeding(db_session):
    response = await _request("GET", "/admin/klassendienst-typen")
    assert response.status_code == 200
    assert response.json() == []


async def test_put_legt_an_und_schreibt_audit(db_session):
    response = await _request("PUT", "/admin/klassendienst-typen", json=[_eintrag()])
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0] == {
        "id": body[0]["id"],
        "webuntis_dienst_id": 26,
        "bezeichnung": "Entschuldigungspflicht",
        "kuerzel": "E",
        "beschreibung": "Fehlzeiten sind taggleich zu entschuldigen",
        "aktiv": True,
    }
    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_klassendienst_typen_updated"))
    ).scalar_one()
    assert audit.resource_typ == "klassendienst_typ"
    assert audit.details["anzahl_typen"] == 1
    assert (await _request("GET", "/admin/klassendienst-typen")).json() == body


async def test_put_aktualisiert_bestehenden_eintrag_und_normalisiert(db_session):
    typ = KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="Alt", kuerzel="A", aktiv=True)
    db_session.add(typ)
    await db_session.commit()
    typ_id = typ.id

    response = await _request(
        "PUT",
        "/admin/klassendienst-typen",
        json=[_eintrag(id=typ_id, bezeichnung="  Neu  ", kuerzel=" N ", beschreibung="   ", aktiv=False)],
    )
    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == typ_id
    assert body[0]["bezeichnung"] == "Neu"
    assert body[0]["kuerzel"] == "N"
    assert body[0]["beschreibung"] is None
    assert body[0]["aktiv"] is False


async def test_put_entfernter_eintrag_wird_geloescht_und_schueler_zeilen_per_cascade(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="e1", vorname="A", nachname="B", klasse_id=klasse.id, aktiv=True)
    behalten = KlassendienstTyp(webuntis_dienst_id=27, bezeichnung="Attest", kuerzel="A", aktiv=True)
    entfaellt = KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="Entsch", kuerzel="E", aktiv=True)
    db_session.add_all([schueler, behalten, entfaellt])
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerKlassendienst(schueler_id=schueler.id, klassendienst_typ_id=entfaellt.id, von=date(2026, 9, 28), bis=date(2026, 10, 4)),
            SchuelerKlassendienst(schueler_id=schueler.id, klassendienst_typ_id=behalten.id, von=date(2026, 9, 28), bis=date(2026, 10, 4)),
        ]
    )
    await db_session.commit()
    behalten_id, entfaellt_dienst = behalten.id, entfaellt.webuntis_dienst_id

    response = await _request(
        "PUT",
        "/admin/klassendienst-typen",
        json=[_eintrag(id=behalten_id, webuntis_dienst_id=27, bezeichnung="Attest", kuerzel="A")],
    )
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [behalten_id]
    db_session.expire_all()
    rest = (await db_session.execute(select(SchuelerKlassendienst))).scalars().all()
    assert [z.klassendienst_typ_id for z in rest] == [behalten_id]
    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_klassendienst_typen_updated"))
    ).scalar_one()
    assert audit.details["entfernte_dienst_ids"] == [entfaellt_dienst]


async def test_put_leere_liste_entfernt_alle(db_session):
    db_session.add(KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="E", kuerzel="E", aktiv=True))
    await db_session.commit()
    response = await _request("PUT", "/admin/klassendienst-typen", json=[])
    assert response.status_code == 200
    assert response.json() == []


async def test_put_dienst_id_nach_loeschen_wiederverwendbar(db_session):
    db_session.add(KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="Alt", kuerzel="A", aktiv=True))
    await db_session.commit()
    response = await _request("PUT", "/admin/klassendienst-typen", json=[_eintrag(bezeichnung="Neu")])
    assert response.status_code == 200
    assert response.json()[0]["bezeichnung"] == "Neu"


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ([_eintrag(), _eintrag(bezeichnung="Andere")], "Duplicate webuntis_dienst_id"),
        ([_eintrag(kuerzel="  ")], "kuerzel must not be empty"),
        ([_eintrag(kuerzel="x" * 11)], "kuerzel must not be longer"),
        ([_eintrag(bezeichnung="  ")], "bezeichnung must not be empty"),
        ([_eintrag(bezeichnung="x" * 101)], "bezeichnung must not be longer"),
        ([_eintrag(beschreibung="x" * 301)], "beschreibung must not be longer"),
        ([_eintrag(webuntis_dienst_id=0)], "positive"),
        ([_eintrag(id=99999)], "Unknown klassendienst type id"),
    ],
)
async def test_put_validierung(db_session, payload, fragment):
    response = await _request("PUT", "/admin/klassendienst-typen", json=payload)
    assert response.status_code == 422
    assert fragment in response.text
    assert (await db_session.execute(select(KlassendienstTyp))).scalars().all() == []


async def test_put_beschreibung_300_zeichen_erlaubt(db_session):
    response = await _request("PUT", "/admin/klassendienst-typen", json=[_eintrag(beschreibung="x" * 300)])
    assert response.status_code == 200


async def test_put_doppelte_id_im_payload(db_session):
    typ = KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="E", kuerzel="E", aktiv=True)
    db_session.add(typ)
    await db_session.commit()
    response = await _request(
        "PUT",
        "/admin/klassendienst-typen",
        json=[_eintrag(id=typ.id), _eintrag(id=typ.id, webuntis_dienst_id=27)],
    )
    assert response.status_code == 422


async def test_put_tausch_der_dienst_ids_ist_409(db_session):
    a = KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="A", kuerzel="A", aktiv=True)
    b = KlassendienstTyp(webuntis_dienst_id=27, bezeichnung="B", kuerzel="B", aktiv=True)
    db_session.add_all([a, b])
    await db_session.commit()
    response = await _request(
        "PUT",
        "/admin/klassendienst-typen",
        json=[_eintrag(id=a.id, webuntis_dienst_id=27), _eintrag(id=b.id, webuntis_dienst_id=26)],
    )
    assert response.status_code == 409


# --- webuntis-optionen ---


class _FakeUntis:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _patch_optionen(monkeypatch, *, options=None, error=None, login_error=None):
    class FakeClient(_FakeUntis):
        def __init__(self, _settings):
            if login_error is not None:
                raise login_error

    class FakeDuty:
        def __init__(self, client, _settings):
            pass

        async def get_duty_options(self):
            if error is not None:
                raise error
            return options

    monkeypatch.setattr(klassendienst_typ_service, "WebUntisClient", FakeClient)
    monkeypatch.setattr(klassendienst_typ_service, "StudentDutyClient", FakeDuty)


async def test_optionen_liefert_vorschlagsliste(db_session, monkeypatch):
    _patch_optionen(monkeypatch, options=[DutyOption(26, "Entschuldigungspflicht"), DutyOption(1, "Klassenordner")])
    response = await _request("GET", "/admin/klassendienst-typen/webuntis-optionen")
    assert response.status_code == 200
    assert response.json() == {
        "optionen": [{"id": 26, "bezeichnung": "Entschuldigungspflicht"}, {"id": 1, "bezeichnung": "Klassenordner"}],
        "hinweis": None,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"error": DutyServiceError("forbidden", "HTTP 403")},
        {"error": RuntimeError("boom")},
        {"login_error": WebUntisError("Login fehlgeschlagen")},
        {"login_error": OSError("Netzwerk")},
    ],
)
async def test_optionen_fehler_liefert_leere_liste_mit_hinweis_nie_500(db_session, monkeypatch, kwargs):
    _patch_optionen(monkeypatch, **kwargs)
    response = await _request("GET", "/admin/klassendienst-typen/webuntis-optionen")
    assert response.status_code == 200
    body = response.json()
    assert body["optionen"] == []
    assert body["hinweis"]


async def test_optionen_unbekannte_form_liefert_leere_liste_mit_hinweis(db_session, monkeypatch):
    _patch_optionen(monkeypatch, options=[])
    response = await _request("GET", "/admin/klassendienst-typen/webuntis-optionen")
    assert response.status_code == 200
    assert response.json()["optionen"] == []
    assert response.json()["hinweis"]
