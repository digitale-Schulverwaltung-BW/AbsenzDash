from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme


async def create_ausnahme(
    db: AsyncSession,
    schueler_id: int,
    kategorie: str,
    grund: str,
    gueltig_bis: date | None,
    nutzer_id: int,
) -> Ausnahme:
    ausnahme = Ausnahme(
        schueler_id=schueler_id,
        kategorie=kategorie,
        grund=grund,
        gueltig_bis=gueltig_bis,
        aktiv=True,
    )
    db.add(ausnahme)
    await db.flush()

    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="ausnahme_erstellt",
            resource_typ="ausnahme",
            resource_id=str(ausnahme.id),
            details={"schueler_id": schueler_id, "kategorie": kategorie},
        )
    )
    await db.commit()
    return ausnahme


async def revoke_ausnahme(db: AsyncSession, ausnahme: Ausnahme, nutzer_id: int) -> None:
    """Setzt eine Ausnahme auf aktiv=False. Der Aufrufer ist dafuer verantwortlich, dass
    `ausnahme` bereits als existent, zum richtigen Schueler gehoerig und aktiv geprueft wurde."""
    ausnahme.aktiv = False
    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="ausnahme_aufgehoben",
            resource_typ="ausnahme",
            resource_id=str(ausnahme.id),
            details={"schueler_id": ausnahme.schueler_id, "kategorie": ausnahme.kategorie},
        )
    )
    await db.commit()
