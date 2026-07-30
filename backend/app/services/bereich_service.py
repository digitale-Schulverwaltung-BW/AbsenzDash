from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import ist_unique_violation
from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import ROLLEN, Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import AbteilungOut, BereichIn, BereichLeiterOut, BereichOut, BereichVorschlagOut, KlasseOut


async def list_klassen(db: AsyncSession) -> list[KlasseOut]:
    result = await db.execute(select(Klasse).order_by(Klasse.name))
    return [KlasseOut(id=k.id, name=k.name) for k in result.scalars().all()]


async def list_abteilungen(db: AsyncSession) -> list[AbteilungOut]:
    result = await db.execute(select(Abteilung).order_by(Abteilung.name))
    return [AbteilungOut(id=a.id, name=a.name) for a in result.scalars().all()]


async def _bereich_out(db: AsyncSession, bereich: Bereich) -> BereichOut:
    klasse_ids = (
        await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    leiter_rows = (
        await db.execute(
            select(Nutzer)
            .join(nutzer_bereich, nutzer_bereich.c.nutzer_id == Nutzer.id)
            .where(nutzer_bereich.c.bereich_id == bereich.id)
        )
    ).scalars().all()
    return BereichOut(
        id=bereich.id,
        name=bereich.name,
        klasse_ids=sorted(klasse_ids),
        leiter=[
            BereichLeiterOut(nutzer_id=n.id, wp_user_id=n.wp_user_id, email=n.email, name=n.name)
            for n in leiter_rows
        ],
    )


async def list_bereiche(db: AsyncSession) -> list[BereichOut]:
    result = await db.execute(select(Bereich).order_by(Bereich.name))
    return [await _bereich_out(db, b) for b in result.scalars().all()]


def _validate_payload(payload: list[BereichIn]) -> None:
    seen_ids: set[int] = set()
    for bereich in payload:
        if bereich.id is not None:
            if bereich.id in seen_ids:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {bereich.id}")
            seen_ids.add(bereich.id)

    seen_names: set[str] = set()
    for bereich in payload:
        if not bereich.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if bereich.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {bereich.name}")
        seen_names.add(bereich.name)

    for bereich in payload:
        for leiter in bereich.leiter:
            if leiter.rolle not in ROLLEN:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rolle: {leiter.rolle}")


async def _validate_klasse_ids_exist(db: AsyncSession, payload: list[BereichIn]) -> None:
    klasse_ids = {kid for bereich in payload for kid in bereich.klasse_ids}
    if not klasse_ids:
        return
    result = await db.execute(select(Klasse.id).where(Klasse.id.in_(klasse_ids)))
    missing = klasse_ids - set(result.scalars().all())
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown klasse_id(s): {sorted(missing)}")


async def _get_or_create_nutzer_stub(db: AsyncSession, wp_user_id: str, email: str, name: str, rolle: str) -> Nutzer:
    """Get-or-Create fuer eine als Bereichsleiter zugewiesene Person.

    Setzt `rolle` NUR bei Neuanlage (nutzer.rolle ist NOT NULL, ein frisch
    zugewiesener Bereichsleiter ohne vorherigen Login braucht einen gueltigen
    Startwert). Eine bereits bestehende `nutzer`-Zeile behaelt ihre Rolle --
    die Rollenzuweisung selbst passiert ausschliesslich ueber die
    Rollen-Zuweisungs-Seite, nicht hier (siehe Plan, "Wichtiger Umsetzungshinweis").
    """
    result = await db.execute(select(Nutzer).where(Nutzer.wp_user_id == wp_user_id))
    nutzer = result.scalar_one_or_none()
    if nutzer is None:
        nutzer = Nutzer(wp_user_id=wp_user_id, email=email, name=name, rolle=rolle)
        db.add(nutzer)
        await db.flush()
    else:
        nutzer.email = email
        nutzer.name = name
    return nutzer


async def replace_bereiche(db: AsyncSession, payload: list[BereichIn], admin_nutzer_id: int) -> list[BereichOut]:
    _validate_payload(payload)
    await _validate_klasse_ids_exist(db, payload)

    existing = (await db.execute(select(Bereich))).scalars().all()
    by_id = {b.id: b for b in existing}
    payload_ids = {b.id for b in payload if b.id is not None}

    unknown_ids = payload_ids - set(by_id.keys())
    if unknown_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown id(s): {sorted(unknown_ids)}")

    try:
        for bereich in existing:
            if bereich.id not in payload_ids:
                await db.delete(bereich)
        await db.flush()

        result_bereiche: list[Bereich] = []
        for item in payload:
            if item.id is not None:
                bereich = by_id[item.id]
                bereich.name = item.name
            else:
                bereich = Bereich(name=item.name)
                db.add(bereich)
                await db.flush()
            result_bereiche.append(bereich)

            await db.execute(delete(bereich_klasse).where(bereich_klasse.c.bereich_id == bereich.id))
            for klasse_id in item.klasse_ids:
                await db.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_id))

            await db.execute(delete(nutzer_bereich).where(nutzer_bereich.c.bereich_id == bereich.id))
            for leiter in item.leiter:
                nutzer = await _get_or_create_nutzer_stub(db, leiter.wp_user_id, leiter.email, leiter.name, leiter.rolle)
                await db.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))

        db.add(
            AuditLog(
                user_id=admin_nutzer_id,
                aktion="admin_bereiche_updated",
                resource_typ="bereich",
                details={"anzahl": len(payload)},
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ist_unique_violation(exc):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Name bereits vergeben — bitte einen eindeutigen Namen für den Bereich wählen.",
            )
        raise

    return [await _bereich_out(db, b) for b in result_bereiche]


async def vorschlag_aus_abteilungen(db: AsyncSession) -> list[BereichVorschlagOut]:
    """Einmal-Vorschlag zur Vorbefuellung der Bereichsdefinition (1:1 pro Abteilung).

    Kein Schreibzugriff, kein `quelle`-Flag -- reiner Formular-Vorschlag, siehe Design-Dok
    Abschnitt 'GET /admin/bereiche/vorschlag-aus-abteilungen'.
    """
    abteilungen = (await db.execute(select(Abteilung).order_by(Abteilung.name))).scalars().all()
    klassen = (await db.execute(select(Klasse))).scalars().all()

    klassen_by_abteilung: dict[int, list[int]] = {}
    for klasse in klassen:
        if klasse.abteilung_id is not None:
            klassen_by_abteilung.setdefault(klasse.abteilung_id, []).append(klasse.id)

    return [
        BereichVorschlagOut(
            name=abteilung.long_name or abteilung.name,
            klasse_ids=sorted(klassen_by_abteilung.get(abteilung.id, [])),
        )
        for abteilung in abteilungen
    ]
