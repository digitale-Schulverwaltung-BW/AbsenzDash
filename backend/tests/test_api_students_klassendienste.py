from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.api.routes import students as students_route
from app.core.config import settings
from app.core.database import engine
from app.main import app
from app.models.klasse import Klasse
from app.models.klassendienst_typ import KlassendienstTyp
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schueler_klassendienst import SchuelerKlassendienst
from app.models.schuljahr import Schuljahr

HEUTE = date(2026, 10, 8)
HEADERS = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "klassenlehrkraft",
}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")
    monkeypatch.setattr(students_route, "_heute", lambda: HEUTE)


async def _get(url):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url, headers=HEADERS)


async def _klasse_mit_lehrkraft(db_session, schuljahr, name="10a", webuntis_id=1, nutzer=None):
    klasse = Klasse(webuntis_id=webuntis_id, name=name, schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    if nutzer is None:
        nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
        db_session.add(nutzer)
        await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.flush()
    return klasse, nutzer


@pytest.fixture
async def daten(db_session, schuljahr):
    klasse, _ = await _klasse_mit_lehrkraft(db_session, schuljahr)
    s1 = Schueler(externe_id="e1", vorname="A", nachname="Alpha", klasse_id=klasse.id, aktiv=True)
    s2 = Schueler(externe_id="e2", vorname="B", nachname="Beta", klasse_id=klasse.id, aktiv=True)
    entsch = KlassendienstTyp(webuntis_dienst_id=26, bezeichnung="Entschuldigungspflicht", kuerzel="E", beschreibung="Erklärung", aktiv=True)
    attest = KlassendienstTyp(webuntis_dienst_id=27, bezeichnung="Attestpflicht", kuerzel="A", aktiv=True)
    inaktiv = KlassendienstTyp(webuntis_dienst_id=3, bezeichnung="Sprecher", kuerzel="S", aktiv=False)
    db_session.add_all([s1, s2, entsch, attest, inaktiv])
    await db_session.flush()
    db_session.add_all(
        [
            # laeuft heute
            SchuelerKlassendienst(schueler_id=s1.id, klassendienst_typ_id=entsch.id, von=date(2026, 9, 28), bis=date(2026, 10, 11)),
            # beendet
            SchuelerKlassendienst(schueler_id=s1.id, klassendienst_typ_id=attest.id, von=date(2026, 9, 1), bis=date(2026, 9, 20)),
            # zukuenftig
            SchuelerKlassendienst(schueler_id=s1.id, klassendienst_typ_id=attest.id, von=date(2026, 11, 2), bis=date(2026, 11, 8)),
            # inaktiver Typ
            SchuelerKlassendienst(schueler_id=s1.id, klassendienst_typ_id=inaktiv.id, von=date(2026, 9, 28), bis=date(2026, 10, 11)),
        ]
    )
    await db_session.commit()
    return {"klasse": klasse, "s1": s1.id, "s2": s2.id, "entsch": entsch.id, "attest": attest.id}


async def test_uebersicht_zeigt_nur_heute_gueltige_aktive_typen(db_session, daten):
    response = await _get("/students")
    assert response.status_code == 200
    items = {i["id"]: i for i in response.json()["items"]}
    assert items[daten["s1"]]["klassendienste"] == [
        {
            "typ_id": daten["entsch"],
            "kuerzel": "E",
            "bezeichnung": "Entschuldigungspflicht",
            "beschreibung": "Erklärung",
            "von": "2026-09-28",
            "bis": "2026-10-11",
            "aktiv_heute": True,
        }
    ]
    assert items[daten["s2"]]["klassendienste"] == []


async def test_aktiv_heute_grenzen_inklusive(db_session, daten, monkeypatch):
    monkeypatch.setattr(students_route, "_heute", lambda: date(2026, 10, 11))
    items = {i["id"]: i for i in (await _get("/students")).json()["items"]}
    assert [k["aktiv_heute"] for k in items[daten["s1"]]["klassendienste"]] == [True]
    monkeypatch.setattr(students_route, "_heute", lambda: date(2026, 10, 12))
    items = {i["id"]: i for i in (await _get("/students")).json()["items"]}
    assert items[daten["s1"]]["klassendienste"] == []


async def test_detail_liefert_vollstaendige_liste_auch_zukuenftig_und_beendet(db_session, daten):
    response = await _get(f"/students/{daten['s1']}")
    assert response.status_code == 200
    liste = response.json()["klassendienste"]
    assert [(k["kuerzel"], k["von"], k["aktiv_heute"]) for k in liste] == [
        ("A", "2026-09-01", False),
        ("E", "2026-09-28", True),
        ("A", "2026-11-02", False),
    ]
    assert all(k["beschreibung"] in (None, "Erklärung") for k in liste)


async def test_detail_ohne_klassendienste_leere_liste(db_session, daten):
    response = await _get(f"/students/{daten['s2']}")
    assert response.json()["klassendienste"] == []


async def test_scope_fremder_schueler_bleibt_gesperrt(db_session, schuljahr, daten):
    anderer = Nutzer(wp_user_id="x", email="x@y.de", name="X", rolle="klassenlehrkraft")
    db_session.add(anderer)
    await db_session.flush()
    andere, _ = await _klasse_mit_lehrkraft(db_session, schuljahr, name="10b", webuntis_id=2, nutzer=anderer)
    fremd = Schueler(externe_id="e9", vorname="F", nachname="F", klasse_id=andere.id, aktiv=True)
    db_session.add(fremd)
    await db_session.commit()
    assert (await _get(f"/students/{fremd.id}")).status_code in (403, 404)
    ids = [i["id"] for i in (await _get("/students")).json()["items"]]
    assert fremd.id not in ids


async def test_archivmodus_liefert_keine_klassendienste(db_session, daten):
    altes = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(altes)
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerKlasseHistorie(schueler_id=daten["s1"], schuljahr_id=27, klasse_id=daten["klasse"].id),
        ]
    )
    await db_session.commit()
    liste = await _get("/students?schuljahr_id=27")
    assert liste.status_code == 200
    assert all(i["klassendienste"] == [] for i in liste.json()["items"])
    detail = await _get(f"/students/{daten['s1']}?schuljahr_id=27")
    assert detail.status_code == 200
    assert detail.json()["klassendienste"] == []


def _count_statements():
    statements = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    return statements, before


async def test_uebersicht_hat_keine_n_plus_1_queries(db_session, schuljahr, daten):
    async def zaehle():
        statements, before = _count_statements()
        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            response = await _get("/students?limit=200")
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
        assert response.status_code == 200
        return len(statements), len(response.json()["items"])

    await _get("/students")  # Warm-up: der erste Request legt den Nutzer an (INSERT + Audit-Log)
    anzahl_klein, schueler_klein = await zaehle()

    typ_id = daten["entsch"]
    for i in range(15):
        s = Schueler(externe_id=f"x{i}", vorname="V", nachname=f"N{i}", klasse_id=daten["klasse"].id, aktiv=True)
        db_session.add(s)
        await db_session.flush()
        db_session.add(SchuelerKlassendienst(schueler_id=s.id, klassendienst_typ_id=typ_id, von=date(2026, 9, 28), bis=date(2026, 10, 11)))
    await db_session.commit()

    anzahl_gross, schueler_gross = await zaehle()
    assert schueler_gross == schueler_klein + 15
    assert anzahl_gross == anzahl_klein
