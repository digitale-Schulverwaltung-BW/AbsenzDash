"""Warnt beim Start, falls die DB nicht auf der von diesem Code erwarteten Alembic-Revision steht.

Wendet Migrationen bewusst NICHT automatisch an: manche Migrationen brauchen einen manuellen
Vorbereitungsschritt (z.B. den `TRUNCATE fehlzeit`-Reset vor dem Fehlzeiten-Merge-Fix, siehe
docs/deployment.md), den ein automatisches `alembic upgrade head` beim Containerstart unbemerkt
umgehen würde.
"""

import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _get_head_revision() -> str | None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config).get_current_head()


async def warn_if_migrations_pending(engine: AsyncEngine) -> None:
    head = _get_head_revision()
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            current = result.scalar_one_or_none()
        except ProgrammingError:
            current = None

    if current != head:
        logger.warning(
            "Datenbank-Schema ist NICHT aktuell (Alembic-Revision der DB: %s, vom Code erwartet: %s). "
            "`alembic upgrade head` ausfuehren, bevor produktiv genutzt wird -- vorher pruefen, ob die "
            "ausstehende(n) Migration(en) einen manuellen Vorbereitungsschritt brauchen "
            "(siehe docs/deployment.md).",
            current,
            head,
        )
