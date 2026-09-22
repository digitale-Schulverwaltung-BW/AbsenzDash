from datetime import date

from httpx import ASGITransport, AsyncClient
import pytest

from app.core.config import settings
from app.main import app
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr

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
async def test_get_nav_options_returns_only_scoped_klassen(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
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
async def test_get_stats_returns_klasse_level_for_own_klasse(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
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


@pytest.mark.asyncio
async def test_get_stats_accepts_schuljahr_id_and_scopes_to_historical_roster(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add_all(
        [
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_alt.id, quelle="webuntis_seed"),
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_neu.id, quelle="webuntis_seed"),
        ]
    )
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_neu.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id)
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/dashboard/stats", params={"schuljahr_id": schuljahr_alt.id}, headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    body = response.json()
    # Scope enthaelt beide NutzerKlasse-Zeilen (klasse_alt + klasse_neu, siehe Plan-17-Abweichung 4)
    # -> len(klasse_scope) == 2, deshalb "eigene_klassen"-Level statt eines einzelnen "klasse"-Levels
    # (kein neuer historie-bewusster Scope-Check in diesem Plan, siehe Abweichung 7). Die eigentliche
    # Pruefung hier ist, dass die Rohzahlen trotzdem korrekt auf die historische schueler_klasse_historie
    # skaliert werden (nur klasse_alt hat einen Historie-Eintrag fuer schuljahr_alt).
    assert body["level"] == "eigene_klassen"
    assert body["own"]["anzahl_schueler"] == 1


@pytest.mark.asyncio
async def test_get_stats_schuljahr_id_for_aktuelles_schuljahr_behaves_like_omitted(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr.id))
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ohne_param = await client.get("/dashboard/stats", headers=HEADERS_KLASSENLEHRKRAFT)
        mit_aktuellem_param = await client.get(
            "/dashboard/stats", params={"schuljahr_id": schuljahr.id}, headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert ohne_param.json() == mit_aktuellem_param.json()
