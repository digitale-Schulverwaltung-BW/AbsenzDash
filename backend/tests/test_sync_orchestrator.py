from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.integrations.webuntis_client import WebUntisError
from app.models.einstellung import Einstellung
from app.services import sync_orchestrator


class _FakeWebUntisClient:
    def __init__(self, _settings):
        self.call = AsyncMock(return_value={"startDate": 20250915, "endDate": 20260729})

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
    sync_orchestrator.sync_klassen.side_effect = lambda *a: calls.append("klassen")
    sync_orchestrator.sync_kategorien.side_effect = lambda *a: calls.append("kategorien")
    sync_orchestrator.import_schueler.side_effect = lambda *a: calls.append("schueler")
    sync_orchestrator.sync_fehlzeiten.side_effect = lambda *a: calls.append("fehlzeiten")
    sync_orchestrator.sync_klassenbuch.side_effect = lambda *a: calls.append("klassenbuch")

    await sync_orchestrator.run_full_sync(async_session_factory)

    assert calls == ["abteilungen", "klassen", "kategorien", "schueler", "fehlzeiten", "klassenbuch"]


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

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute)

    assert von == date(2024, 7, 14)
    assert bis == heute


def test_fehlzeiten_zeitraum_with_schuljahr_start_cache():
    """Branch 2: schuljahr_start_cache is set, von = schuljahr_start_cache."""
    schuljahr_start = date(2024, 9, 1)
    einstellung = Einstellung(schuljahr_start_cache=schuljahr_start)
    heute = date(2024, 7, 20)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute)

    assert von == schuljahr_start
    assert bis == heute


def test_fehlzeiten_zeitraum_fallback():
    """Branch 3: Both letzter_sync_am and schuljahr_start_cache are None, von = heute."""
    einstellung = Einstellung()
    heute = date(2024, 7, 20)

    von, bis = sync_orchestrator._fehlzeiten_zeitraum(einstellung, heute)

    assert von == heute
    assert bis == heute
