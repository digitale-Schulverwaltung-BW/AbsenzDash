from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.database import ist_unique_violation
from app.models.audit_log import AuditLog
from app.models.massnahmen_typ import MassnahmenTyp
from app.schemas.admin import MeasureTypeIn, MeasureTypeOut


def _typ_out(typ: MassnahmenTyp) -> MeasureTypeOut:
    return MeasureTypeOut(
        id=typ.id,
        name=typ.name,
        setzt_zaehler_zurueck=typ.setzt_zaehler_zurueck,
        aktiv=typ.aktiv,
    )


async def list_measure_types(db: AsyncSession) -> list[MeasureTypeOut]:
    result = await db.execute(select(MassnahmenTyp).order_by(MassnahmenTyp.id))
    return [_typ_out(t) for t in result.scalars().all()]


def _validate_payload(payload: list[MeasureTypeIn]) -> None:
    seen_ids: set[int] = set()
    for typ in payload:
        if typ.id is None:
            continue
        if typ.id in seen_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {typ.id}")
        seen_ids.add(typ.id)

    seen_names: set[str] = set()
    for typ in payload:
        if not typ.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if typ.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {typ.name}")
        seen_names.add(typ.name)


async def replace_measure_types(
    db: AsyncSession, payload: list[MeasureTypeIn], nutzer_id: int
) -> list[MeasureTypeOut]:
    _validate_payload(payload)

    existing_result = await db.execute(select(MassnahmenTyp))
    existing_by_id = {t.id: t for t in existing_result.scalars().all()}

    for typ_in in payload:
        if typ_in.id is not None and typ_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown measure type id: {typ_in.id}")

    payload_ids = {t.id for t in payload if t.id is not None}
    removed_ids = [tid for tid in existing_by_id if tid not in payload_ids]
    removed_names = [existing_by_id[tid].name for tid in removed_ids]

    try:
        for typ_id in removed_ids:
            await db.delete(existing_by_id[typ_id])

        for typ_in in payload:
            if typ_in.id is not None:
                typ = existing_by_id[typ_in.id]
                typ.name = typ_in.name
                typ.setzt_zaehler_zurueck = typ_in.setzt_zaehler_zurueck
                typ.aktiv = typ_in.aktiv
            else:
                db.add(
                    MassnahmenTyp(
                        name=typ_in.name, setzt_zaehler_zurueck=typ_in.setzt_zaehler_zurueck, aktiv=typ_in.aktiv
                    )
                )

        db.add(
            AuditLog(
                user_id=nutzer_id,
                aktion="admin_measure_types_updated",
                resource_typ="massnahmen_typ",
                details={"anzahl_typen": len(payload)},
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ist_unique_violation(exc):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Name bereits vergeben — bitte einen eindeutigen Namen für den Maßnahmen-Typ wählen.",
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kann folgende(n) Maßnahmen-Typ(en) nicht löschen, da bereits verwendet: "
            f"{', '.join(removed_names)}. Stattdessen deaktivieren (aktiv=false).",
        )

    return await list_measure_types(db)
