import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_scoped_schueler, resolve_bereich_scope, resolve_scope
from app.core.config import settings
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler

test_app = FastAPI()


@test_app.get("/scoped/{schueler_id}")
async def scoped(schueler: Schueler = Depends(get_scoped_schueler)):
    return {"id": schueler.id}


HEADERS_BASE = {
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
async def test_resolve_scope_returns_none_for_schulleitung(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.flush()

    assert await resolve_scope(db_session, nutzer) is None


@pytest.mark.asyncio
async def test_resolve_scope_returns_assigned_klassen_for_klassenlehrkraft(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    scope = await resolve_scope(db_session, nutzer)
    assert scope == {klasse_a.id}


@pytest.mark.asyncio
async def test_resolve_scope_returns_no_klassen_for_klassenlehrkraft_without_assignment(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.commit()

    assert await resolve_scope(db_session, nutzer) == set()


@pytest.mark.asyncio
async def test_resolve_scope_returns_bereich_klassen_for_bereichsleiter(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    scope = await resolve_scope(db_session, nutzer)
    assert scope == {klasse_a.id}


@pytest.mark.asyncio
async def test_get_scoped_schueler_returns_student_in_scope(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    nutzer_row = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer_row)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer_row.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/scoped/{schueler.id}", headers=HEADERS_BASE)
    assert response.status_code == 200
    assert response.json() == {"id": schueler.id}


@pytest.mark.asyncio
async def test_get_scoped_schueler_404s_for_student_outside_scope(db_session, schuljahr):
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    db_session.add(schueler)
    await db_session.flush()
    nutzer_row = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer_row)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer_row.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/scoped/{schueler.id}", headers=HEADERS_BASE)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_scoped_schueler_404s_for_unknown_id(db_session):
    nutzer_row = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer_row)
    await db_session.commit()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scoped/999999", headers=HEADERS_BASE)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_bereich_scope_returns_none_for_schulleitung(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    assert await resolve_bereich_scope(db_session, nutzer) is None


@pytest.mark.asyncio
async def test_resolve_bereich_scope_returns_assigned_bereiche_for_bereichsleiter(db_session):
    bereich_a = Bereich(name="Ausbildung")
    bereich_b = Bereich(name="Berufsschule")
    db_session.add_all([bereich_a, bereich_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich_a.id))
    await db_session.commit()

    scope = await resolve_bereich_scope(db_session, nutzer)
    assert scope == {bereich_a.id}


@pytest.mark.asyncio
async def test_resolve_bereich_scope_returns_empty_set_for_klassenlehrkraft(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.commit()

    assert await resolve_bereich_scope(db_session, nutzer) == set()
