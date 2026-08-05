from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import ROLLEN, Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import AbteilungOut, BereichIn, BereichLeiterOut, BereichOut


async def list_abteilungen(db: AsyncSession) -> list[AbteilungOut]:
    result = await db.execute(select(Abteilung).order_by(Abteilung.name))
    return [AbteilungOut(id=a.id, name=a.name) for a in result.scalars().all()]


async def _bereich_out(db: AsyncSession, bereich: Bereich) -> BereichOut:
    klasse_namen = (
        await db.execute(
            select(Klasse.name)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
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
        klasse_namen=list(klasse_namen),
        ausgeblendet=bereich.ausgeblendet,
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
        if bereich.id in seen_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {bereich.id}")
        seen_ids.add(bereich.id)
    for bereich in payload:
        for leiter in bereich.leiter:
            if leiter.rolle not in ROLLEN:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rolle: {leiter.rolle}")


async def _get_or_create_nutzer_stub(db: AsyncSession, wp_user_id: str, email: str, name: str, rolle: str) -> Nutzer:
    """Get-or-Create fuer eine als Bereichsleiter zugewiesene Person.

    Setzt `rolle` NUR bei Neuanlage (nutzer.rolle ist NOT NULL, ein frisch
    zugewiesener Bereichsleiter ohne vorherigen Login braucht einen gueltigen
    Startwert). Eine bereits bestehende `nutzer`-Zeile behaelt ihre Rolle --
    die Rollenzuweisung selbst passiert ausschliesslich ueber die
    Rollen-Zuweisungs-Seite, nicht hier.
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


async def update_bereiche(db: AsyncSession, payload: list[BereichIn], admin_nutzer_id: int) -> list[BereichOut]:
    """Aktualisiert `ausgeblendet` und die Bereichsleiter-Zuordnung fuer bestehende,
    sync-abgeleitete Bereiche.

    Kann keine Bereiche anlegen oder loeschen -- das uebernimmt ausschliesslich
    webuntis_bereich_sync.sync_bereiche bei jedem WebUntis-Sync-Lauf, siehe
    docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.
    """
    _validate_payload(payload)

    existing = (await db.execute(select(Bereich))).scalars().all()
    by_id = {b.id: b for b in existing}

    unknown_ids = {item.id for item in payload} - set(by_id.keys())
    if unknown_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown id(s): {sorted(unknown_ids)}")

    result_bereiche: list[Bereich] = []
    for item in payload:
        bereich = by_id[item.id]
        bereich.ausgeblendet = item.ausgeblendet
        result_bereiche.append(bereich)

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

    return [await _bereich_out(db, b) for b in result_bereiche]
