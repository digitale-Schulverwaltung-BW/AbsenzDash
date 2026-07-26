import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.scheduler as scheduler_module
from app.core.database import async_session_factory, engine
from app.models.base import Base


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


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
