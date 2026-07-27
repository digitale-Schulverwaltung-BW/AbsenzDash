from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.database import ist_unique_violation
from app.models.audit_log import AuditLog
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.schwellwert_regel import SchwellwertRegel
from app.schemas.admin import MeasureTypeIn, MeasureTypeOut


async def _typ_out(db: AsyncSession, typ: MassnahmenTyp) -> MeasureTypeOut:
    result = await db.execute(
        select(massnahmen_typ_regel.c.regel_id).where(massnahmen_typ_regel.c.massnahmen_typ_id == typ.id)
    )
    return MeasureTypeOut(
        id=typ.id,
        name=typ.name,
        setzt_zaehler_zurueck=typ.setzt_zaehler_zurueck,
        aktiv=typ.aktiv,
        betroffene_regel_ids=sorted(result.scalars().all()),
    )


async def list_measure_types(db: AsyncSession) -> list[MeasureTypeOut]:
    result = await db.execute(select(MassnahmenTyp).order_by(MassnahmenTyp.id))
    return [await _typ_out(db, t) for t in result.scalars().all()]


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


async def _validate_regel_ids_exist(db: AsyncSession, payload: list[MeasureTypeIn]) -> None:
    regel_ids = {rid for typ in payload for rid in typ.betroffene_regel_ids}
    if not regel_ids:
        return
    result = await db.execute(select(SchwellwertRegel.id).where(SchwellwertRegel.id.in_(regel_ids)))
    missing = regel_ids - set(result.scalars().all())
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown regel_id(s): {sorted(missing)}")


async def replace_measure_types(
    db: AsyncSession, payload: list[MeasureTypeIn], nutzer_id: int
) -> list[MeasureTypeOut]:
    _validate_payload(payload)
    await _validate_regel_ids_exist(db, payload)

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
                typ = MassnahmenTyp(
                    name=typ_in.name, setzt_zaehler_zurueck=typ_in.setzt_zaehler_zurueck, aktiv=typ_in.aktiv
                )
                db.add(typ)
                await db.flush()

            await db.execute(massnahmen_typ_regel.delete().where(massnahmen_typ_regel.c.massnahmen_typ_id == typ.id))
            for regel_id in typ_in.betroffene_regel_ids:
                await db.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel_id))

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
