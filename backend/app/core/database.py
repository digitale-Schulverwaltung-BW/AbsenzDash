from collections.abc import AsyncGenerator

import asyncpg
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# PostgreSQL-SQLSTATE für "unique_violation"
UNIQUE_VIOLATION_SQLSTATE = "23505"

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def ist_unique_violation(exc: IntegrityError) -> bool:
    """Unterscheidet eine UNIQUE-Verletzung von anderen IntegrityError-Ursachen (v.a. FK-Verletzung).

    Der asyncpg-Dialekt übersetzt die asyncpg-Exception in eine eigene DBAPI-Exception: `exc.orig`
    ist also *nicht* das asyncpg-Objekt selbst, sondern trägt dessen `sqlstate`/`pgcode` und hat es
    als `__cause__`. Beide Wege werden geprüft, damit der Check nicht an SQLAlchemy-Interna hängt.
    """
    orig = exc.orig
    if orig is None:
        return False
    if getattr(orig, "sqlstate", None) == UNIQUE_VIOLATION_SQLSTATE:
        return True
    if getattr(orig, "pgcode", None) == UNIQUE_VIOLATION_SQLSTATE:
        return True
    return isinstance(orig, asyncpg.exceptions.UniqueViolationError) or isinstance(
        getattr(orig, "__cause__", None), asyncpg.exceptions.UniqueViolationError
    )
