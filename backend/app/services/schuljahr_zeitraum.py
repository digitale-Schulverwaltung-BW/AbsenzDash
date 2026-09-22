from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.einstellung import Einstellung
from app.models.schuljahr import Schuljahr


async def resolve_schuljahr_zeitraum(db: AsyncSession, schuljahr_id: int | None) -> tuple[date | None, date | None]:
    """None, None heisst "aktuelles Schuljahr, unveraendertes Verhalten". Ein konkretes
    (von, bis)-Paar heisst "Historie-Modus fuer dieses vergangene Schuljahr".

    Urspruenglich privat als _resolve_schuljahr_zeitraum in app/api/routes/students.py
    (Plan 16/17); hierher ausgelagert, damit app/services/dashboard_query.py dieselbe
    Schuljahr-Modus-Erkennung nutzen kann, ohne sie zu duplizieren, siehe
    docs/superpowers/specs/2026-09-22-dashboard-stats-schuljahr-design.md. Verhalten
    unveraendert gegenueber der bisherigen students.py-Fassung."""
    if schuljahr_id is None:
        return None, None
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is not None and schuljahr_id == einstellung.aktuelles_schuljahr_id:
        return None, None
    schuljahr = await db.get(Schuljahr, schuljahr_id)
    if schuljahr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Schuljahr")
    return schuljahr.start_datum, schuljahr.end_datum
