from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.models.schueler import Schueler
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.students import MassnahmeOut, StudentDetailOut, StudentListOut, StudentOverviewOut
from app.services import student_query

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
async def get_students(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: Literal["fehlzeiten", "klassenbuch"] | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StudentListOut:
    scope = await resolve_scope(db, nutzer)
    schueler_list, total = await student_query.list_students(
        db,
        scope=scope,
        klasse_id=klasse_id,
        bereich_id=bereich_id,
        typ=typ,
        min_stufe=min_stufe,
        nur_auffaellige=nur_auffaellige,
        limit=limit,
        offset=offset,
    )
    schueler_ids = [schueler.id for schueler in schueler_list]
    extras = await student_query.load_overview_extras(db, schueler_ids)
    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)

    items = [
        StudentOverviewOut(
            id=schueler.id,
            vorname=schueler.vorname,
            nachname=schueler.nachname,
            klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
            zaehlerstand=extras[schueler.id]["zaehlerstand"],
            letzte_benachrichtigung=extras[schueler.id]["letzte_benachrichtigung"],
            ohne_massnahme_seit_benachrichtigung=extras[schueler.id]["ohne_massnahme_seit_benachrichtigung"],
        )
        for schueler in schueler_list
    ]
    return StudentListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{schueler_id}")
async def get_student_detail(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudentDetailOut:
    detail = await student_query.load_student_detail(db, schueler.id)
    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    massnahmen = [
        MassnahmeOut(
            id=massnahme.id,
            massnahmen_typ_id=massnahme.massnahmen_typ_id,
            massnahmen_typ_name=typ_name,
            datum=massnahme.datum,
            notiz=massnahme.notiz,
            erfasst_von_nutzer_id=massnahme.erfasst_von_nutzer_id,
            erfasst_von_name=nutzer_name,
        )
        for massnahme, typ_name, nutzer_name in detail["massnahmen"]
    ]

    return StudentDetailOut(
        id=schueler.id,
        vorname=schueler.vorname,
        nachname=schueler.nachname,
        klasse=klasse,
        zaehlerstand=detail["zaehlerstand"],
        fehlzeiten=detail["fehlzeiten"],
        klassenbuch=detail["klassenbuch"],
        massnahmen=massnahmen,
        ausnahmen=detail["ausnahmen"],
        benachrichtigungen=detail["benachrichtigungen"],
    )
