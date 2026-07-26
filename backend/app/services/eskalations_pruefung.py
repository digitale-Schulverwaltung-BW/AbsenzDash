from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.klasse import Klasse
from app.models.schwellwert_regel import SchwellwertRegel


async def resolve_schwellwert_regel(
    db: AsyncSession, klasse_id: int | None, typ: str
) -> SchwellwertRegel | None:
    """Loest die zutreffende Regel nach Praezedenz auf: klassen-spezifisch > abteilungs-spezifisch > schulweit."""
    if klasse_id is not None:
        result = await db.execute(
            select(SchwellwertRegel).where(SchwellwertRegel.typ == typ, SchwellwertRegel.klasse_id == klasse_id)
        )
        regel = result.scalar_one_or_none()
        if regel is not None:
            return regel

        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is not None and klasse.abteilung_id is not None:
            result = await db.execute(
                select(SchwellwertRegel).where(
                    SchwellwertRegel.typ == typ, SchwellwertRegel.abteilung_id == klasse.abteilung_id
                )
            )
            regel = result.scalar_one_or_none()
            if regel is not None:
                return regel

    result = await db.execute(
        select(SchwellwertRegel).where(SchwellwertRegel.typ == typ, SchwellwertRegel.geltungsbereich == "schulweit")
    )
    return result.scalar_one_or_none()
