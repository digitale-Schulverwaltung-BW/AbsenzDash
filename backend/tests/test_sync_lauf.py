"""Tests fuer den Sync-Verlauf (Tabelle sync_lauf) und den Hintergrund-Sync."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisError
from app.main import app
from app.models.audit_log import AuditLog
from app.models.nutzer import Nutzer
from app.models.sync_lauf import SyncLauf
from app.services import sync_lauf_service, sync_orchestrator
from app.services.webuntis_klassendienst_sync import KlassendienstSyncErgebnis
from tests.test_sync_orchestrator import _FakeWebUntisClient

HEADERS_SL = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "schulleitung",
}
HEADERS_KL = {**HEADERS_SL, "X-WordPress-Role": "klassenlehrkraft"}


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")
    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClient)
    for name in (
        "sync_abteilungen", "sync_klassen", "sync_bereiche", "sync_kategorien", "sync_stundenraster",
        "import_schueler", "sync_fehlzeiten", "sync_klassenbuch", "pruefe_schwellwerte",
    ):
        monkeypatch.setattr(sync_orchestrator, name, AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_klassendienste", AsyncMock(return_value=KlassendienstSyncErgebnis()))
    sync_orchestrator._manuelle_sync_tasks.clear()


async def _laeufe():
    async with async_session_factory() as s:
        return list((await s.execute(select(SyncLauf).order_by(SyncLauf.id))).scalars().all())


async def _warte_auf_tasks():
    tasks = list(sync_orchestrator._manuelle_sync_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _post(headers=HEADERS_SL):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.post("/admin/sync-now", headers=headers)


async def _get_status(headers=HEADERS_SL):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/admin/sync-status", headers=headers)


# ---------- Bereinigung ----------

def test_bereinige_enthaelt_klasse_und_kuerzt_auf_300():
    text = sync_lauf_service.fehler_kurz_aus(WebUntisError("x" * 1000))
    assert text.startswith("WebUntisError: ")
    assert len(text) <= 300


@pytest.mark.parametrize(
    "meldung,verboten",
    [
        ("Auth failed token=abc123SECRETxyz789", "abc123SECRETxyz789"),
        ("Cookie: JSESSIONID=DEADBEEF1234567890ABCDEF; Path=/", "DEADBEEF1234567890ABCDEF"),
        ("Authorization: Bearer eyJhbGciOi.JIUzI1NiJ9.sig_nature-1234", "eyJhbGciOi"),
        ("csrf=0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
        ("GET https://x.webuntis.com/WebUntis/api?schoolname=_abc&session=SECRET123 failed", "SECRET123"),
        ("Fehler bei max.mustermann@schule.de", "max.mustermann@schule.de"),
        ("Zeile 1\nZeile 2 mit Daten", "Zeile 2"),
    ],
)
def test_bereinige_entfernt_geheimnisse(meldung, verboten):
    ergebnis = sync_lauf_service.fehler_kurz_aus(ValueError(meldung))
    assert verboten not in ergebnis
    assert ergebnis.startswith("ValueError")


def test_bereinige_datenbankfehler_ohne_parameter():
    from sqlalchemy.exc import IntegrityError

    exc = IntegrityError("INSERT INTO schueler ...", {"nachname": "Mustermann"}, Exception("dup Mustermann"))
    ergebnis = sync_lauf_service.fehler_kurz_aus(exc)
    assert "Mustermann" not in ergebnis
    assert ergebnis.startswith("IntegrityError")


# ---------- run_sync_once / Phasen ----------

@pytest.mark.asyncio
async def test_run_sync_once_ohne_neue_parameter_bleibt_kompatibel(db_session):
    await sync_orchestrator.run_sync_once(db_session)
    laeufe = await _laeufe()
    assert len(laeufe) == 1
    assert laeufe[0].status == "ok"
    assert laeufe[0].ausgeloest_von == "manuell"
    assert laeufe[0].beendet_am is not None
    assert laeufe[0].fehler_kurz is None


@pytest.mark.asyncio
async def test_phasenuebergaenge_werden_in_reihenfolge_gesetzt(db_session, monkeypatch):
    phasen: list[str] = []
    original = sync_lauf_service.phase_setzen

    async def _spion(lauf_id, phase):
        phasen.append(phase)
        await original(lauf_id, phase)

    monkeypatch.setattr(sync_orchestrator.sync_lauf_service, "phase_setzen", _spion)
    await sync_orchestrator.run_sync_once(db_session, ausgeloest_von="zeitplan")
    assert phasen == [
        "WebUntis-Stammdaten", "Schüler-Import", "Fehlzeiten", "Klassenbuch", "Klassendienste", "Eskalationsprüfung",
    ]
    assert (await _laeufe())[0].phase == "Eskalationsprüfung"


@pytest.mark.asyncio
async def test_phase_ist_waehrend_des_laufs_in_anderer_session_sichtbar(db_session):
    gesehen = {}

    async def _fehlzeiten(*a, **kw):
        async with async_session_factory() as s:
            row = (await s.execute(select(SyncLauf))).scalar_one()
            gesehen["status"], gesehen["phase"] = row.status, row.phase

    sync_orchestrator.sync_fehlzeiten.side_effect = _fehlzeiten
    await sync_orchestrator.run_sync_once(db_session)
    assert gesehen == {"status": "laufend", "phase": "Fehlzeiten"}


@pytest.mark.asyncio
async def test_fehler_wird_vermerkt_und_weitergereicht_ohne_geheimnisse(db_session):
    sync_orchestrator.sync_fehlzeiten.side_effect = WebUntisError("login token=TOPSECRETTOKEN1234 Max Mustermann")
    with pytest.raises(WebUntisError):
        await sync_orchestrator.run_sync_once(db_session, ausgeloest_von="zeitplan")
    lauf = (await _laeufe())[0]
    assert lauf.status == "fehler"
    assert lauf.beendet_am is not None
    assert lauf.phase == "Fehlzeiten"
    assert lauf.ausgeloest_von == "zeitplan"
    assert "TOPSECRETTOKEN1234" not in lauf.fehler_kurz
    assert lauf.fehler_kurz.startswith("WebUntisError")
    assert len(lauf.fehler_kurz) <= 300


@pytest.mark.asyncio
async def test_already_running_legt_keine_zeile_an(db_session):
    await sync_orchestrator._sync_lock.acquire()
    try:
        with pytest.raises(sync_orchestrator.SyncAlreadyRunningError):
            await sync_orchestrator.run_sync_once(db_session)
    finally:
        sync_orchestrator._sync_lock.release()
    assert await _laeufe() == []


@pytest.mark.asyncio
async def test_zeitplan_pfad_schreibt_zeitplan_und_retry_legt_zeile_je_versuch_an(db_session, monkeypatch):
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 3)
    sync_orchestrator.sync_fehlzeiten.side_effect = [WebUntisError("boom"), None]
    await sync_orchestrator.run_full_sync(async_session_factory)
    laeufe = await _laeufe()
    assert [(l.status, l.ausgeloest_von) for l in laeufe] == [("fehler", "zeitplan"), ("ok", "zeitplan")]


@pytest.mark.asyncio
async def test_run_full_sync_exception_semantik_unveraendert(db_session, monkeypatch):
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 1)
    sync_orchestrator.sync_fehlzeiten.side_effect = WebUntisError("boom")
    await sync_orchestrator.run_full_sync(async_session_factory)  # wirft nicht


# ---------- Aufraeumen / 6h / Kuerzung ----------

async def _lauf(status="laufend", alter_h=0.0, **kw):
    async with async_session_factory() as s:
        row = SyncLauf(
            gestartet_am=datetime.now(timezone.utc) - timedelta(hours=alter_h),
            status=status,
            ausgeloest_von=kw.pop("ausgeloest_von", "manuell"),
            **kw,
        )
        s.add(row)
        await s.commit()
        return row.id


@pytest.mark.asyncio
async def test_start_aufraeumen_setzt_laufend_auf_abgebrochen(db_session):
    a = await _lauf("laufend")
    b = await _lauf("ok")
    n = await sync_lauf_service.verwaiste_laeufe_abbrechen()
    assert n == 1
    laeufe = {l.id: l for l in await _laeufe()}
    assert laeufe[a].status == "abgebrochen" and laeufe[a].beendet_am is not None
    assert laeufe[b].status == "ok"


@pytest.mark.asyncio
async def test_lifespan_raeumt_verwaiste_laeufe_auf(db_session):
    from app.main import lifespan

    a = await _lauf("laufend")
    async with lifespan(app):
        pass
    assert {l.id: l.status for l in await _laeufe()}[a] == "abgebrochen"


@pytest.mark.asyncio
async def test_verlauf_wird_auf_200_gekuerzt(db_session):
    async with async_session_factory() as s:
        for _ in range(205):
            s.add(SyncLauf(gestartet_am=datetime.now(timezone.utc), status="ok", ausgeloest_von="zeitplan"))
        await s.commit()
    neue_id = await sync_lauf_service.lauf_anlegen("manuell", None)
    laeufe = await _laeufe()
    assert len(laeufe) == 200
    assert laeufe[-1].id == neue_id


# ---------- sync-status ----------

@pytest.mark.asyncio
async def test_status_leer(db_session):
    r = await _get_status()
    assert r.status_code == 200
    assert r.json() == {"laeuft": False, "aktueller_lauf": None, "letzter_lauf": None}


@pytest.mark.asyncio
async def test_status_nur_schulleitung(db_session):
    assert (await _get_status(HEADERS_KL)).status_code == 403


@pytest.mark.asyncio
async def test_status_laufend_und_letzter_lauf(db_session):
    await _lauf("fehler", alter_h=2, fehler_kurz="WebUntisError: x", beendet_am=datetime.now(timezone.utc))
    await _lauf("ok", alter_h=1, beendet_am=datetime.now(timezone.utc))
    lid = await _lauf("laufend", alter_h=0.1, phase="Fehlzeiten")
    body = (await _get_status()).json()
    assert body["laeuft"] is True
    assert set(body["aktueller_lauf"]) == {"id", "gestartet_am", "phase", "ausgeloest_von"}
    assert body["aktueller_lauf"]["id"] == lid and body["aktueller_lauf"]["phase"] == "Fehlzeiten"
    assert set(body["letzter_lauf"]) == {
        "id", "status", "gestartet_am", "beendet_am", "ausgeloest_von", "fehler_kurz",
    }
    assert body["letzter_lauf"]["status"] == "ok"


@pytest.mark.asyncio
async def test_status_laufend_aelter_6h_gilt_als_abgebrochen(db_session):
    lid = await _lauf("laufend", alter_h=7)
    body = (await _get_status()).json()
    assert body["laeuft"] is False and body["aktueller_lauf"] is None
    assert body["letzter_lauf"]["id"] == lid
    assert body["letzter_lauf"]["status"] == "abgebrochen"


# ---------- POST /admin/sync-now ----------

@pytest.mark.asyncio
async def test_sync_now_nur_schulleitung(db_session):
    assert (await _post(HEADERS_KL)).status_code == 403
    assert await _laeufe() == []


@pytest.mark.asyncio
async def test_sync_now_antwortet_202_und_task_laeuft_weiter(db_session):
    freigabe = asyncio.Event()

    async def _warten(*a, **kw):
        await freigabe.wait()

    sync_orchestrator.sync_fehlzeiten.side_effect = _warten

    r = await _post()
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "gestartet" and isinstance(body["lauf_id"], int)

    # Antwort ist raus, der Sync haengt noch -> Status "laeuft"
    assert len(sync_orchestrator._manuelle_sync_tasks) == 1
    for _ in range(100):
        s = (await _get_status()).json()
        if s["aktueller_lauf"] and s["aktueller_lauf"]["phase"] == "Fehlzeiten":
            break
        await asyncio.sleep(0.02)
    assert s["laeuft"] is True and s["aktueller_lauf"]["id"] == body["lauf_id"]
    assert s["aktueller_lauf"]["ausgeloest_von"] == "manuell"

    freigabe.set()
    await _warte_auf_tasks()
    lauf = (await _laeufe())[0]
    assert lauf.status == "ok" and lauf.id == body["lauf_id"]
    nutzer = (await db_session.execute(select(Nutzer))).scalar_one()
    assert lauf.nutzer_id == nutzer.id
    assert sync_orchestrator.sync_laeuft() is False
    assert (await _get_status()).json()["letzter_lauf"]["status"] == "ok"

    audit = (await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_sync_now_triggered"))).scalar_one()
    assert audit.details == {"status": "gestartet", "lauf_id": body["lauf_id"]}
    assert audit.user_id == nutzer.id


@pytest.mark.asyncio
async def test_sync_now_409_wenn_sync_laeuft(db_session):
    await sync_orchestrator._sync_lock.acquire()
    try:
        r = await _post()
    finally:
        sync_orchestrator._sync_lock.release()
    assert r.status_code == 409
    assert await _laeufe() == []
    assert (
        await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_sync_now_triggered"))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_doppelter_post_startet_nur_einen_lauf(db_session):
    freigabe = asyncio.Event()

    async def _warten(*a, **kw):
        await freigabe.wait()

    sync_orchestrator.sync_fehlzeiten.side_effect = _warten
    assert (await _get_status()).status_code == 200  # legt den Nutzer an (sonst Race bei Erstanlage)
    r1, r2 = await asyncio.gather(_post(), _post())
    assert sorted([r1.status_code, r2.status_code]) == [202, 409]
    freigabe.set()
    await _warte_auf_tasks()
    laeufe = await _laeufe()
    assert len(laeufe) == 1 and laeufe[0].status == "ok"
    assert sync_orchestrator.sync_fehlzeiten.await_count == 1


@pytest.mark.asyncio
async def test_sync_now_fehler_wird_im_lauf_vermerkt_ohne_unbehandelte_ausnahme(db_session, caplog):
    sync_orchestrator.sync_fehlzeiten.side_effect = WebUntisError("kaputt token=GEHEIMGEHEIM12345 Erika Musterfrau")
    r = await _post()
    assert r.status_code == 202
    await _warte_auf_tasks()
    # Task-Ausnahme wurde behandelt (kein "exception was never retrieved")
    lauf = (await _laeufe())[0]
    assert lauf.status == "fehler"
    assert "GEHEIMGEHEIM12345" not in lauf.fehler_kurz
    body = (await _get_status()).json()
    assert body["laeuft"] is False
    assert body["letzter_lauf"]["status"] == "fehler"
    assert body["letzter_lauf"]["fehler_kurz"].startswith("WebUntisError")
    assert sync_orchestrator.sync_fehlzeiten.await_count == 1  # kein Retry
    assert sync_orchestrator.sync_laeuft() is False  # Sperre wieder frei
    assert (await _post()).status_code == 202  # neuer Start moeglich
    await _warte_auf_tasks()


@pytest.mark.asyncio
async def test_sync_now_unerwarteter_fehler_wird_vermerkt(db_session):
    sync_orchestrator.pruefe_schwellwerte.side_effect = RuntimeError("unerwartet")
    assert (await _post()).status_code == 202
    await _warte_auf_tasks()
    lauf = (await _laeufe())[0]
    assert lauf.status == "fehler" and lauf.fehler_kurz.startswith("RuntimeError")
    assert sync_orchestrator.sync_laeuft() is False


@pytest.mark.asyncio
async def test_abbruch_des_tasks_markiert_lauf_als_abgebrochen(db_session):
    freigabe = asyncio.Event()

    async def _warten(*a, **kw):
        await freigabe.wait()

    sync_orchestrator.sync_fehlzeiten.side_effect = _warten
    assert (await _post()).status_code == 202
    for _ in range(100):
        if (await _laeufe())[0].phase == "Fehlzeiten":
            break
        await asyncio.sleep(0.02)
    for t in list(sync_orchestrator._manuelle_sync_tasks):
        t.cancel()
    await _warte_auf_tasks()
    lauf = (await _laeufe())[0]
    assert lauf.status == "abgebrochen" and lauf.beendet_am is not None
    assert sync_orchestrator.sync_laeuft() is False
