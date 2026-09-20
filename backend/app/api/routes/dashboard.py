from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_wordpress_proxy_nutzer
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.dashboard import NavOptionsOut, StatsOut
from app.services import dashboard_query

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/nav-options")
async def get_nav_options(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: int | None = None,
) -> NavOptionsOut:
    return await dashboard_query.get_nav_options(db, nutzer, schuljahr_id=schuljahr_id)


@router.get("/stats")
async def get_stats(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    bereich_id: int | None = None,
    klasse_id: int | None = None,
) -> StatsOut:
    return await dashboard_query.get_dashboard_stats(db, nutzer, bereich_id, klasse_id)
