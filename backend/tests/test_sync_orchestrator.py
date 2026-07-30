from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisError
from app.models.benachrichtigung import Benachrichtigung
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.services import sync_orchestrator
from app.services.eskalations_pruefung import pruefe_schwellwerte as real_pruefe_schwellwerte
from app.services.webuntis_klassen_sync import sync_klassen as real_sync_klassen


class _FakeWebUntisClient:
    def __init__(self, _settings):
        async def _call(method, _params):
            if method == "getSchoolyears":
                return [{"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}]
            return {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}

        self.call = AsyncMock(side_effect=_call)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture(autouse=True)
def _patch_phases(monkeypatch):
    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClient)
    monkeypatch.setattr(sync_orchestrator, "sync_abteilungen", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_klassen", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_kategorien", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "import_schueler", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_fehlzeiten", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_klassenbuch", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "pruefe_schwellwerte", AsyncMock())


@pytest.mark.asyncio
async def test_run_full_sync_sets_letzter_sync_am_and_initial_import_flag(db_session):
    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalar_one()
    assert einstellung.letzter_sync_am is not None
    assert einstellung.initialer_import_abgeschlossen is True
    assert einstellung.schuljahr_start_cache is not None


@pytest.mark.asyncio
async def test_run_full_sync_calls_phases_in_order(db_session):
    calls = []
    sync_orchestrator.sync_abteilungen.side_effect = lambda *a: calls.append("abteilungen")
    sync_orchestrator.sync_klassen.side_effect = lambda *a, **kw: calls.append("klassen")
    sync_orchestrator.sync_kategorien.side_effect = lambda *a: calls.append("kategorien")
    sync_orchestrator.import_schueler.side_effect = lambda *a: calls.append("schueler")
    sync_orchestrator.sync_fehlzeiten.side_effect = lambda *a: calls.append("fehlzeiten")
    sync_orchestrator.sync_klassenbuch.side_effect = lambda *a: calls.append("klassenbuch")
    sync_orchestrator.pruefe_schwellwerte.side_effect = lambda *a: calls.append("schwellwerte")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert calls == ["abteilungen", "klassen", "kategorien", "schueler", "fehlzeiten", "klassenbuch", "schwellwerte"]


@pytest.mark.asyncio
async def test_run_full_sync_retries_on_failure_and_succeeds(db_session, monkeypatch):
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 3)
    sync_orchestrator.sync_fehlzeiten.side_effect = [WebUntisError("boom"), None]

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert sync_orchestrator.sync_fehlzeiten.await_count == 2
    result = await db_session.execute(select(Einstellung))
    assert result.scalar_one().letzter_sync_am is not None


@pytest.mark.asyncio
async def test_run_full_sync_gives_up_after_max_attempts(db_session, monkeypatch):
    sleep_mock = AsyncMock()
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 2)
    sync_orchestrator.sync_fehlzeiten.side_effect = WebUntisError("boom")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert sync_orchestrator.sync_fehlzeiten.await_count == 2
    assert sleep_mock.await_count == 1
    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalars().first()
    assert einstellung is None or einstellung.letzter_sync_am is None


def test_fehlzeiten_zeitraum_with_letzter_sync_am():
    """Branch 1: letzter_sync_am is set, von = letzter_sync_am - 1 day."""
    sync_date = datetime(2024, 7, 15, 10, 30, tzinfo=timezone.utc)
    einstellung = Einstellung(letzter_sync_am=sync_date)
    heute = date(2024, 7, 20)
    schuljahr_ende = date(2025, 7, 31)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == date(2024, 7, 14)
    assert bis == heute


def test_fehlzeiten_zeitraum_with_schuljahr_start_cache():
    """Branch 2: schuljahr_start_cache is set, von = schuljahr_start_cache."""
    schuljahr_start = date(2024, 9, 1)
    einstellung = Einstellung(schuljahr_start_cache=schuljahr_start)
    heute = date(2024, 7, 20)
    schuljahr_ende = date(2025, 7, 31)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == schuljahr_start
    assert bis == heute


def test_fehlzeiten_zeitraum_fallback():
    """Branch 3: Both letzter_sync_am and schuljahr_start_cache are None, von = heute."""
    einstellung = Einstellung()
    heute = date(2024, 7, 20)
    schuljahr_ende = date(2025, 7, 31)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert von == heute
    assert bis == heute


def test_fehlzeiten_zeitraum_clamps_bis_to_schuljahr_ende_in_uebergangsluecke():
    """Regression Live-Fund 2026-07-30: Schuljahr 2025/2026 endete am 2026-07-29,
    2026/2027 ist in WebUntis noch nicht als aktuell konfiguriert - wir befinden uns
    in der Uebergangsluecke. Ohne Clamping waere bis=heute (2026-07-30), was aus dem
    Schuljahr herausfaellt und getTimetableWithAbsences mit 'startDate and endDate are
    not within a single school year' fehlschlagen laesst. bis muss stattdessen auf
    schuljahr_ende gekappt werden."""
    einstellung = Einstellung(schuljahr_start_cache=date(2025, 9, 15))
    heute = date(2026, 7, 30)
    schuljahr_ende = date(2026, 7, 29)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute, schuljahr_ende)

    assert bis == schuljahr_ende
    assert von <= bis


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_uses_current_schoolyear(db_session, monkeypatch):
    client = AsyncMock()
    client.call = AsyncMock(
        side_effect=lambda method, _params: (
            [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
            if method == "getSchoolyears"
            else {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}
        )
    )

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"
    assert schuljahr.start_datum == date(2025, 9, 15)
    assert schuljahr.end_datum == date(2026, 7, 29)

    result = await db_session.execute(select(Schuljahr).order_by(Schuljahr.id))
    cached = result.scalars().all()
    assert [s.id for s in cached] == [27, 28]


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_falls_back_to_newest_cached_when_webuntis_has_none(db_session):
    """WebUntis meldet kein aktives Schuljahr (Uebergangszeitraum, siehe Live-Fund
    2026-07-30) - getCurrentSchoolyear wirft einen Fehler, getSchoolyears liefert aber
    weiterhin die volle Liste. Der Resolver faellt auf das juengste bekannte Schuljahr
    (hoechstes end_datum) zurueck, statt den ganzen Sync-Lauf abzubrechen."""
    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
        if method == "getCurrentSchoolyear":
            raise WebUntisError(
                'Cannot invoke "com.grupet.web.basic.Schoolyear.getEndDate()" because "schoolyear" is null'
            )
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_fallback_ignores_future_not_yet_started_schuljahr(db_session):
    """Regression: WebUntis meldet kein aktives Schuljahr, aber ein Admin hat bereits
    das naechste Schuljahr (2026/2027, startet erst naechsten Monat) in WebUntis
    angelegt. Der Fallback darf dieses zukuenftige Schuljahr NICHT waehlen (hoechstes
    end_datum), sonst wird schuljahr_start_cache auf ein Datum in der Zukunft gesetzt
    und jedes Eskalations-Zaehlfenster laeuft leer. Er muss stattdessen das juengste
    bereits gestartete Schuljahr (2025/2026, gestern beendet) waehlen."""
    heute = datetime.now(timezone.utc).date()
    gestern = heute - timedelta(days=1)
    naechster_monat = heute + timedelta(days=30)
    ende_naechstes_jahr = naechster_monat + timedelta(days=300)

    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {
                    "id": 27,
                    "name": "2024/2025",
                    "startDate": (heute - timedelta(days=400)).strftime("%Y%m%d"),
                    "endDate": (heute - timedelta(days=35)).strftime("%Y%m%d"),
                },
                {
                    "id": 28,
                    "name": "2025/2026",
                    "startDate": (heute - timedelta(days=34)).strftime("%Y%m%d"),
                    "endDate": gestern.strftime("%Y%m%d"),
                },
                {
                    "id": 29,
                    "name": "2026/2027",
                    "startDate": naechster_monat.strftime("%Y%m%d"),
                    "endDate": ende_naechstes_jahr.strftime("%Y%m%d"),
                },
            ]
        if method == "getCurrentSchoolyear":
            raise WebUntisError(
                'Cannot invoke "com.grupet.web.basic.Schoolyear.getEndDate()" because "schoolyear" is null'
            )
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"
    assert schuljahr.start_datum <= heute


@pytest.mark.asyncio
async def test_resolve_aktuelles_schuljahr_falls_back_when_current_id_not_in_cache(db_session):
    """Regression: getCurrentSchoolyear liefert eine schoolyearId, die im gerade aus
    getSchoolyears aktualisierten Cache nicht enthalten ist (inkonsistente WebUntis-
    Antworten zwischen zwei Aufrufen). db.get(Schuljahr, ...) liefert dann None - der
    Resolver darf NICHT None zurueckgeben (das wuerde run_sync_once mit einem
    AttributeError ausserhalb der Retry-Behandlung abstuerzen lassen), sondern muss
    auf das juengste bereits gestartete Schuljahr zurueckfallen."""
    client = AsyncMock()

    async def _call(method, _params):
        if method == "getSchoolyears":
            return [
                {"id": 27, "name": "2024/2025", "startDate": 20240909, "endDate": 20250730},
                {"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729},
            ]
        if method == "getCurrentSchoolyear":
            return {"id": 999, "name": "unbekannt", "startDate": 20260101, "endDate": 20261231}
        raise AssertionError(f"unexpected call: {method}")

    client.call = AsyncMock(side_effect=_call)

    schuljahr = await sync_orchestrator.resolve_aktuelles_schuljahr(client, db_session)

    assert schuljahr is not None
    assert schuljahr.id == 28
    assert schuljahr.name == "2025/2026"


@pytest.mark.asyncio
async def test_run_full_sync_continues_when_getklassen_fails_without_active_schoolyear(db_session, monkeypatch):
    """Reproduziert den Live-Fund vom 2026-07-30: getKlassen wirft denselben NPE wie
    getCurrentSchoolyear, wenn kein schoolyearId explizit mitgegeben wird. Mit der
    Resolver-Loesung bekommt getKlassen jetzt IMMER eine explizite schoolyearId, auch
    wenn getCurrentSchoolyear selbst fehlschlaegt - der Sync darf deshalb nicht mehr
    abbrechen, und schuljahr_start_cache/aktuelles_schuljahr_id werden korrekt auf das
    Fallback-Schuljahr gesetzt."""

    class _FakeWebUntisClientKeinAktivesSchuljahr:
        def __init__(self, _settings):
            async def _call(method, params):
                if method == "getSchoolyears":
                    return [{"id": 28, "name": "2025/2026", "startDate": 20250915, "endDate": 20260729}]
                if method == "getCurrentSchoolyear":
                    raise WebUntisError('... "schoolyear" is null')
                if method == "getKlassen":
                    assert params == {"schoolyearId": 28}
                    return []
                return {}

            self.call = AsyncMock(side_effect=_call)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClientKeinAktivesSchuljahr)
    monkeypatch.setattr(sync_orchestrator, "sync_klassen", real_sync_klassen)

    vorhandener_cache = date(2025, 9, 1)
    db_session.add(Einstellung(schuljahr_start_cache=vorhandener_cache))
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalar_one()
    assert einstellung.letzter_sync_am is not None
    assert einstellung.aktuelles_schuljahr_id == 28
    assert einstellung.schuljahr_start_cache == date(2025, 9, 15)


@pytest.mark.asyncio
async def test_run_full_sync_end_to_end_triggers_benachrichtigung(db_session, monkeypatch):
    """Einziger Test in dieser Datei, der pruefe_schwellwerte NICHT mockt - prueft die reale Verdrahtung."""
    monkeypatch.setattr(sync_orchestrator, "pruefe_schwellwerte", real_pruefe_schwellwerte)

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["schulleitung"],
        )
    )
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=date(2025, 9, 1))
    db_session.add(einstellung)
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    assert result.scalar_one().status == "kein_empfaenger"
