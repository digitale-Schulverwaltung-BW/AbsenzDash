import logging

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import engine
from app.core.migration_check import _get_head_revision, warn_if_migrations_pending


@pytest_asyncio.fixture(autouse=True)
async def _drop_alembic_version_table():
    # _reset_database (conftest, autouse) wischt nur Base.metadata-Tabellen -- alembic_version
    # gehoert nicht dazu (wird von Alembic selbst verwaltet), muss hier separat weggeraeumt werden,
    # sonst blutet eine von einem Test angelegte Zeile in den naechsten Test derselben Datei durch.
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.mark.asyncio
async def test_warns_when_alembic_version_table_missing(caplog):
    # _reset_database (autouse) erstellt das Schema per Base.metadata.create_all, nicht per
    # Alembic-Migrationen -- die alembic_version-Tabelle existiert im Testschema also nie.
    with caplog.at_level(logging.WARNING):
        await warn_if_migrations_pending(engine)

    assert "NICHT aktuell" in caplog.text


@pytest.mark.asyncio
async def test_no_warning_when_current_revision_matches_head(caplog):
    head = _get_head_revision()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": head})

    with caplog.at_level(logging.WARNING):
        await warn_if_migrations_pending(engine)

    assert "NICHT aktuell" not in caplog.text


@pytest.mark.asyncio
async def test_warns_when_current_revision_differs_from_head(caplog):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:rev)"), {"rev": "veraltete_revision"}
        )

    with caplog.at_level(logging.WARNING):
        await warn_if_migrations_pending(engine)

    assert "NICHT aktuell" in caplog.text
    assert "veraltete_revision" in caplog.text
