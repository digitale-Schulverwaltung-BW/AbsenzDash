from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

import app.core.scheduler as scheduler_module
from app.core.database import async_session_factory, engine
from app.models.base import Base
from app.models.schuljahr import Schuljahr
from app.services import eskalations_pruefung


@pytest_asyncio.fixture(autouse=True)
async def _reset_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _reset_background_sync_tasks():
    scheduler_module._background_sync_tasks.clear()
    yield


@pytest.fixture(autouse=True)
def mock_send_email(monkeypatch):
    """Suite-weites Sicherheitsnetz: verhindert echte SMTP-Verbindungsversuche (30s-Timeout) aus
    Tests, die pruefe_schwellwerte unmocked durchlaufen lassen (z.B. test_sync_orchestrator.py)."""
    mock = AsyncMock()
    monkeypatch.setattr(eskalations_pruefung, "send_email", mock)
    return mock


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def schuljahr(db_session) -> Schuljahr:
    """Standard-Schuljahr fuer Tests, die Klasse-Zeilen anlegen muessen (Klasse.schuljahr_id ist
    seit diesem Plan NOT NULL). id/Daten sind fuer die meisten Tests irrelevant - nur der
    Fremdschluessel muss aufloesbar sein. Tests, die bereits ein eigenes Schuljahr mit konkreten
    Daten anlegen (z.B. um zwei Jahre zu vergleichen), nutzen weiterhin ihr eigenes und lassen
    diese Fixture ungenutzt."""
    jahr = Schuljahr(id=1, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add(jahr)
    await db_session.flush()
    return jahr
