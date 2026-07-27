from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.audit_log import AuditLog
from app.models.excuse_status import ExcuseStatus
from app.schemas.admin import ExcuseStatusIn, ExcuseStatusOut


def _status_out(status_row: ExcuseStatus) -> ExcuseStatusOut:
    return ExcuseStatusOut(
        id=status_row.id,
        name=status_row.name,
        long_name=status_row.long_name,
        zaehlt_als_entschuldigt=status_row.zaehlt_als_entschuldigt,
        aktiv=status_row.aktiv,
    )


async def list_excuse_statuses(db: AsyncSession) -> list[ExcuseStatusOut]:
    result = await db.execute(select(ExcuseStatus).order_by(ExcuseStatus.id))
    return [_status_out(s) for s in result.scalars().all()]


def _validate_payload(payload: list[ExcuseStatusIn]) -> None:
    seen_names: set[str] = set()
    for status_in in payload:
        if not status_in.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if status_in.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {status_in.name}")
        seen_names.add(status_in.name)


async def replace_excuse_statuses(
    db: AsyncSession, payload: list[ExcuseStatusIn], nutzer_id: int
) -> list[ExcuseStatusOut]:
    _validate_payload(payload)

    existing_result = await db.execute(select(ExcuseStatus))
    existing_by_id = {s.id: s for s in existing_result.scalars().all()}

    for status_in in payload:
        if status_in.id is not None and status_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown excuse status id: {status_in.id}")

    payload_ids = {s.id for s in payload if s.id is not None}
    removed_ids = [sid for sid in existing_by_id if sid not in payload_ids]
    removed_names = [existing_by_id[sid].name for sid in removed_ids]

    try:
        for status_id in removed_ids:
            await db.delete(existing_by_id[status_id])

        for status_in in payload:
            if status_in.id is not None:
                status_row = existing_by_id[status_in.id]
                status_row.name = status_in.name
                status_row.long_name = status_in.long_name
                status_row.zaehlt_als_entschuldigt = status_in.zaehlt_als_entschuldigt
                status_row.aktiv = status_in.aktiv
            else:
                db.add(
                    ExcuseStatus(
                        name=status_in.name,
                        long_name=status_in.long_name,
                        zaehlt_als_entschuldigt=status_in.zaehlt_als_entschuldigt,
                        aktiv=status_in.aktiv,
                    )
                )

        db.add(
            AuditLog(
                user_id=nutzer_id,
                aktion="admin_excuse_statuses_updated",
                resource_typ="excuse_status",
                details={"anzahl_status": len(payload)},
            )
        )

        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kann folgende(n) Entschuldigungsstatus nicht löschen, da bereits verwendet: "
            f"{', '.join(removed_names)}. Stattdessen deaktivieren (aktiv=false).",
        )

    return await list_excuse_statuses(db)
