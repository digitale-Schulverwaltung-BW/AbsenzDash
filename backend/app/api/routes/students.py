from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.einstellung import Einstellung
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr
from app.schemas.students import (
    AusnahmeOut,
    BenachrichtigungOut,
    ClassregCategoryCatalogOut,
    ExcuseStatusCatalogOut,
    ExemptionCreateIn,
    FehlzeitSplitOut,
    MassnahmeOut,
    MassnahmenTypCatalogOut,
    MeasureCreateIn,
    StudentCatalogOut,
    StudentDetailOut,
    StudentListOut,
    StudentOverviewOut,
)
from app.services import ausnahme_service, export_service, massnahme_service, student_query

router = APIRouter(prefix="/students", tags=["students"])


async def _resolve_schuljahr_zeitraum(db: AsyncSession, schuljahr_id: int | None) -> tuple[date | None, date | None]:
    """None, None heisst "aktuelles Schuljahr, unveraendertes Verhalten". Ein konkretes
    (von, bis)-Paar heisst "Historie-Modus fuer dieses vergangene Schuljahr"."""
    if schuljahr_id is None:
        return None, None
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is not None and schuljahr_id == einstellung.aktuelles_schuljahr_id:
        return None, None
    schuljahr = await db.get(Schuljahr, schuljahr_id)
    if schuljahr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Schuljahr")
    return schuljahr.start_datum, schuljahr.end_datum


async def _aktuelles_schuljahr_zeitraum(db: AsyncSession) -> tuple[date | None, date | None]:
    """Zeitraum des aktuellen Schuljahres fuer die Fehltage/Fehlstunden/Eintraege-Rohzahlen
    im Normalmodus (kein schuljahr_id-Query-Param). None/None (unbegrenzt) falls noch kein
    aktuelles Schuljahr konfiguriert ist (z.B. vor dem ersten WebUntis-Sync)."""
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None or einstellung.aktuelles_schuljahr_id is None:
        return None, None
    schuljahr = await db.get(Schuljahr, einstellung.aktuelles_schuljahr_id)
    if schuljahr is None:
        return None, None
    return schuljahr.start_datum, schuljahr.end_datum


def _benachrichtigung_out(
    benachrichtigung: Benachrichtigung | None, regel_typ_map: dict[int, str]
) -> BenachrichtigungOut | None:
    if benachrichtigung is None:
        return None
    return BenachrichtigungOut(
        id=benachrichtigung.id,
        regel_id=benachrichtigung.regel_id,
        typ=regel_typ_map.get(benachrichtigung.regel_id) if benachrichtigung.regel_id is not None else None,
        stufe_nr=benachrichtigung.stufe_nr,
        gesendet_am=benachrichtigung.gesendet_am,
        empfaenger=benachrichtigung.empfaenger,
        status=benachrichtigung.status,
    )


@router.get("")
async def get_students(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: Literal["fehlzeiten", "klassenbuch"] | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    nur_aktive: bool = True,
    schuljahr_id: int | None = None,
    sort_by: Literal["nachname", "klasse", "fehltage", "fehlstunden", "klassenbuch_anzahl"] | None = None,
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StudentListOut:
    scope = await resolve_scope(db, nutzer)
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None
    effektiv_von, effektiv_bis = (von, bis) if ist_historie else await _aktuelles_schuljahr_zeitraum(db)

    schueler_list, total = await student_query.list_students(
        db,
        scope=scope,
        klasse_id=klasse_id,
        bereich_id=bereich_id,
        typ=None if ist_historie else typ,
        min_stufe=None if ist_historie else min_stufe,
        nur_auffaellige=False if ist_historie else nur_auffaellige,
        nur_aktive=False if ist_historie else nur_aktive,
        von=effektiv_von,
        bis=effektiv_bis,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
        historie_schuljahr_id=schuljahr_id if ist_historie else None,
    )
    schueler_ids = [schueler.id for schueler in schueler_list]
    rohzahlen = await student_query.load_schueler_rohzahlen(db, schueler_ids, effektiv_von, effektiv_bis)

    if ist_historie:
        klasse_map_historie = await student_query.load_historische_klasse_map(db, schueler_ids, schuljahr_id)
        items = [
            StudentOverviewOut(
                id=schueler.id,
                vorname=schueler.vorname,
                nachname=schueler.nachname,
                klasse=klasse_map_historie[schueler.id],
                fehltage=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehltage"]),
                fehlstunden=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehlstunden"]),
                klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
            )
            for schueler in schueler_list
        ]
        return StudentListOut(items=items, total=total, limit=limit, offset=offset)

    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)

    extras = await student_query.load_overview_extras(db, schueler_ids)
    regel_ids = [
        extras[schueler.id]["letzte_benachrichtigung"].regel_id
        for schueler in schueler_list
        if extras[schueler.id]["letzte_benachrichtigung"] is not None
        and extras[schueler.id]["letzte_benachrichtigung"].regel_id is not None
    ]
    regel_typ_map = await student_query.load_regel_typ_map(db, regel_ids)

    items = [
        StudentOverviewOut(
            id=schueler.id,
            vorname=schueler.vorname,
            nachname=schueler.nachname,
            klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
            zaehlerstand=extras[schueler.id]["zaehlerstand"],
            letzte_benachrichtigung=_benachrichtigung_out(extras[schueler.id]["letzte_benachrichtigung"], regel_typ_map),
            ohne_massnahme_seit_benachrichtigung=extras[schueler.id]["ohne_massnahme_seit_benachrichtigung"],
            fehltage=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehltage"]),
            fehlstunden=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehlstunden"]),
            klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
        )
        for schueler in schueler_list
    ]
    return StudentListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/catalog")
async def get_student_catalog(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudentCatalogOut:
    typen = (
        await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.aktiv.is_(True)).order_by(MassnahmenTyp.name))
    ).scalars().all()
    excuse_statuses = await student_query.load_all_excuse_statuses(db)
    classreg_categories = await student_query.load_all_classreg_categories(db)
    return StudentCatalogOut(
        massnahmen_typen=[MassnahmenTypCatalogOut(id=typ.id, name=typ.name) for typ in typen],
        excuse_statuses=[
            ExcuseStatusCatalogOut(id=s.id, name=s.name, long_name=s.long_name) for s in excuse_statuses
        ],
        classreg_categories=[
            ClassregCategoryCatalogOut(id=c.id, name=c.name, long_name=c.long_name) for c in classreg_categories
        ],
    )


@router.get("/{schueler_id}")
async def get_student_detail(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: int | None = None,
) -> StudentDetailOut:
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None
    if ist_historie and not await student_query.student_hat_historie_eintrag(db, schueler.id, schuljahr_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Schüler war in diesem Schuljahr nicht eingeschrieben"
        )
    effektiv_von, effektiv_bis = (von, bis) if ist_historie else await _aktuelles_schuljahr_zeitraum(db)
    detail = await student_query.load_student_detail(
        db, schueler.id, von=effektiv_von, bis=effektiv_bis, ist_historie=ist_historie
    )
    if ist_historie:
        klasse_map_historie = await student_query.load_historische_klasse_map(db, [schueler.id], schuljahr_id)
        klasse = klasse_map_historie[schueler.id]
    else:
        klasse = None
        if schueler.klasse_id is not None:
            klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
            klasse = klasse_map.get(schueler.klasse_id)

    benachrichtigung_regel_ids = [b.regel_id for b in detail["benachrichtigungen"] if b.regel_id is not None]
    regel_typ_map = await student_query.load_regel_typ_map(db, benachrichtigung_regel_ids)
    benachrichtigungen = [_benachrichtigung_out(b, regel_typ_map) for b in detail["benachrichtigungen"]]

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
        fehltage=FehlzeitSplitOut(**detail["fehltage"]),
        fehlstunden=FehlzeitSplitOut(**detail["fehlstunden"]),
        klassenbuch_anzahl=detail["klassenbuch_anzahl"],
        fehlzeiten=detail["fehlzeiten"],
        klassenbuch=detail["klassenbuch"],
        massnahmen=massnahmen,
        ausnahmen=detail["ausnahmen"],
        benachrichtigungen=benachrichtigungen,
    )


@router.post("/{schueler_id}/measures", status_code=status.HTTP_201_CREATED)
async def create_measure(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: MeasureCreateIn,
) -> MassnahmeOut:
    typ = (
        await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == body.massnahmen_typ_id))
    ).scalar_one_or_none()
    if typ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Measure type not found")

    massnahme = await massnahme_service.record_massnahme(
        db,
        schueler_id=schueler.id,
        massnahmen_typ_id=body.massnahmen_typ_id,
        datum=body.datum,
        notiz=body.notiz,
        erfasst_von_nutzer_id=nutzer.id,
    )
    return MassnahmeOut(
        id=massnahme.id,
        massnahmen_typ_id=massnahme.massnahmen_typ_id,
        massnahmen_typ_name=typ.name,
        datum=massnahme.datum,
        notiz=massnahme.notiz,
        erfasst_von_nutzer_id=massnahme.erfasst_von_nutzer_id,
        erfasst_von_name=nutzer.name,
    )


@router.post("/{schueler_id}/exemptions", status_code=status.HTTP_201_CREATED)
async def create_exemption(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: ExemptionCreateIn,
) -> AusnahmeOut:
    ausnahme = await ausnahme_service.create_ausnahme(
        db,
        schueler_id=schueler.id,
        kategorie=body.kategorie,
        grund=body.grund,
        gueltig_bis=body.gueltig_bis,
        nutzer_id=nutzer.id,
    )
    return AusnahmeOut.model_validate(ausnahme)


@router.delete("/{schueler_id}/exemptions/{exemption_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_exemption(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    exemption_id: int,
) -> None:
    ausnahme = (await db.execute(select(Ausnahme).where(Ausnahme.id == exemption_id))).scalar_one_or_none()
    if ausnahme is None or ausnahme.schueler_id != schueler.id or not ausnahme.aktiv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exemption not found")
    await ausnahme_service.revoke_ausnahme(db, ausnahme, nutzer.id)


_EXPORT_SECTIONS = {"fehlzeiten", "klassenbuch", "massnahmen", "ausnahmen", "benachrichtigungen"}


@router.get("/{schueler_id}/export.pdf", responses={200: {"content": {"application/pdf": {}}}})
async def export_student_pdf(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sections: str | None = None,
    schuljahr_id: int | None = None,
) -> Response:
    if sections:
        requested = {s.strip().lower() for s in sections.split(",") if s.strip()}
        unknown = requested - _EXPORT_SECTIONS
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown sections: {sorted(unknown)}",
            )
    else:
        requested = set(_EXPORT_SECTIONS)

    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    schuljahr_name = None
    if von is not None:
        schuljahr = await db.get(Schuljahr, schuljahr_id)
        schuljahr_name = schuljahr.name if schuljahr is not None else None

    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    html = await export_service.render_student_export_html(
        db, schueler, klasse, requested, von=von, bis=bis, schuljahr_name=schuljahr_name
    )
    pdf_bytes = export_service.html_to_pdf(html)

    db.add(
        AuditLog(
            user_id=nutzer.id,
            aktion="export_pdf",
            resource_typ="schueler",
            resource_id=str(schueler.id),
            details={"sections": sorted(requested)},
        )
    )
    await db.commit()

    filename = export_service.build_export_filename(schueler.nachname, schueler.vorname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
