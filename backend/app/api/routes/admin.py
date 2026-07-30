from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_schulleitung
from app.core.config import settings
from app.core.database import get_db
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.audit_log import AuditLog
from app.models.nutzer import Nutzer
from app.schemas.admin import (
    AbteilungOut,
    BereichIn,
    BereichOut,
    BereichVorschlagOut,
    ExcuseStatusIn,
    ExcuseStatusOut,
    KlasseOut,
    MeasureTypeIn,
    MeasureTypeOut,
    SyncNowOut,
    SyncSettingsIn,
    SyncSettingsOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
    WebUntisTeacherOut,
)
from app.services import (
    bereich_service,
    excuse_status_service,
    measure_type_service,
    sync_settings_service,
    threshold_rule_service,
    webuntis_teacher_service,
)
from app.services.sync_orchestrator import run_sync_once

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_schulleitung)])


@router.get("/klassen")
async def get_klassen(db: Annotated[AsyncSession, Depends(get_db)]) -> list[KlasseOut]:
    return await bereich_service.list_klassen(db)


@router.get("/abteilungen")
async def get_abteilungen(db: Annotated[AsyncSession, Depends(get_db)]) -> list[AbteilungOut]:
    return await bereich_service.list_abteilungen(db)


@router.get("/bereiche")
async def get_bereiche(db: Annotated[AsyncSession, Depends(get_db)]) -> list[BereichOut]:
    return await bereich_service.list_bereiche(db)


@router.put("/bereiche")
async def put_bereiche(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[BereichIn],
) -> list[BereichOut]:
    return await bereich_service.replace_bereiche(db, payload, nutzer.id)


@router.get("/bereiche/vorschlag-aus-abteilungen")
async def get_bereiche_vorschlag(db: Annotated[AsyncSession, Depends(get_db)]) -> list[BereichVorschlagOut]:
    return await bereich_service.vorschlag_aus_abteilungen(db)


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


@router.get("/webuntis-teachers")
async def get_webuntis_teachers() -> list[WebUntisTeacherOut]:
    try:
        async with WebUntisClient(settings) as client:
            return await webuntis_teacher_service.list_teachers(client)
    except WebUntisError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"WebUntis nicht erreichbar: {exc}")


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


@router.post("/sync-now")
async def post_sync_now(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncNowOut:
    # nutzer.id wird vor dem try-Block gelesen: db.rollback() im Fehlerpfad
    # expired alle an der Session haengenden Objekte (auch `nutzer`, da dieselbe
    # Request-Session ueber die require_schulleitung-Dependency geladen wurde).
    # Ein spaeterer Zugriff auf ein expired Attribut ausserhalb eines await
    # loest unter AsyncSession einen MissingGreenlet-Fehler aus, statt einen
    # sauberen Re-Query anzustossen.
    nutzer_id = nutzer.id
    try:
        await run_sync_once(db)
    except (WebUntisError, OSError) as exc:
        await db.rollback()
        db.add(
            AuditLog(
                user_id=nutzer_id,
                aktion="admin_sync_now_triggered",
                resource_typ="einstellung",
                details={"status": "fehler"},
            )
        )
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Sync fehlgeschlagen: {exc}")

    abgeschlossen_am = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="admin_sync_now_triggered",
            resource_typ="einstellung",
            details={"status": "ok"},
        )
    )
    await db.commit()
    return SyncNowOut(status="ok", abgeschlossen_am=abgeschlossen_am)
