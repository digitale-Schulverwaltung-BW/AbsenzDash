from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_schulleitung
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.admin import (
    ExcuseStatusIn,
    ExcuseStatusOut,
    MeasureTypeIn,
    MeasureTypeOut,
    SyncSettingsIn,
    SyncSettingsOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
)
from app.services import (
    excuse_status_service,
    measure_type_service,
    sync_settings_service,
    threshold_rule_service,
)

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


@router.get("/measure-types")
async def get_measure_types(db: Annotated[AsyncSession, Depends(get_db)]) -> list[MeasureTypeOut]:
    return await measure_type_service.list_measure_types(db)


@router.put("/measure-types")
async def put_measure_types(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[MeasureTypeIn],
) -> list[MeasureTypeOut]:
    return await measure_type_service.replace_measure_types(db, payload, nutzer.id)


@router.get("/excuse-statuses")
async def get_excuse_statuses(db: Annotated[AsyncSession, Depends(get_db)]) -> list[ExcuseStatusOut]:
    return await excuse_status_service.list_excuse_statuses(db)


@router.put("/excuse-statuses")
async def put_excuse_statuses(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[ExcuseStatusIn],
) -> list[ExcuseStatusOut]:
    return await excuse_status_service.replace_excuse_statuses(db, payload, nutzer.id)


@router.get("/sync-settings")
async def get_sync_settings(db: Annotated[AsyncSession, Depends(get_db)]) -> SyncSettingsOut:
    return await sync_settings_service.get_sync_settings(db)


@router.put("/sync-settings")
async def put_sync_settings(
    request: Request,
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: SyncSettingsIn,
) -> SyncSettingsOut:
    scheduler = request.app.state.scheduler
    return await sync_settings_service.update_sync_settings(db, scheduler, payload.sync_interval_cron, nutzer.id)
