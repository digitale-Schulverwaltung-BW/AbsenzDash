from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr

HEADERS_SCHULLEITUNG = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "schulleitung",
}
HEADERS_KLASSENLEHRKRAFT = {**HEADERS_SCHULLEITUNG, "X-WordPress-Role": "klassenlehrkraft"}

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


def _csv_bytes(rows: list[str]) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_post_preview_rejects_non_schulleitung(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import/preview",
            headers=HEADERS_KLASSENLEHRKRAFT,
            data={"schuljahr_id": str(schuljahr.id)},
            files={"file": ("archiv.csv", _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"']), "text/csv")},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_preview_returns_summary(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import/preview",
            headers=HEADERS_SCHULLEITUNG,
            data={"schuljahr_id": str(schuljahr.id)},
            files={
                "file": (
                    "archiv.csv",
                    _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"']),
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["zeilen_gesamt"] == 1
    assert body["schueler_neu"] == 1
    assert body["schueler_bekannt"] == 0
    assert body["unbekannte_klassen"] == []


@pytest.mark.asyncio
async def test_post_preview_returns_404_for_unknown_schuljahr(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import/preview",
            headers=HEADERS_SCHULLEITUNG,
            data={"schuljahr_id": "999999"},
            files={"file": ("archiv.csv", _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"']), "text/csv")},
        )
    assert response.status_code == 404
