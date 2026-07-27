import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

import app.core.scheduler as scheduler_module
from app.core.database import async_session_factory, engine
from app.models.base import Base
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
