from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_schulleitung
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.admin import ThresholdRuleIn, ThresholdRuleOut
from app.services import threshold_rule_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_schulleitung)])


@router.get("/threshold-rules")
async def get_threshold_rules(db: Annotated[AsyncSession, Depends(get_db)]) -> list[ThresholdRuleOut]:
    return await threshold_rule_service.list_rules(db)


@router.put("/threshold-rules")
async def put_threshold_rules(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[ThresholdRuleIn],
) -> list[ThresholdRuleOut]:
    return await threshold_rule_service.replace_rules(db, payload, nutzer.id)
