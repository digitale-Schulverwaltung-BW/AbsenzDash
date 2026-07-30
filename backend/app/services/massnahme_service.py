from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.schueler import Schueler
from app.services.eskalations_pruefung import get_or_create_zaehlerstand, resolve_schwellwert_regel


async def record_massnahme(
    db: AsyncSession,
    schueler_id: int,
    massnahmen_typ_id: int,
    datum: date,
    notiz: str | None,
    erfasst_von_nutzer_id: int,
) -> Massnahme:
    """Erfasst eine Massnahme; setzt bei setzt_zaehler_zurueck=True beide Zaehlerstaende
    (fehlzeiten und klassenbuch) des Schuelers zurueck, jeweils unter der fuer ihn aktuell
    aufgeloesten Regel (resolve_schwellwert_regel) - ohne Regel-Verknuepfung, siehe
    docs/superpowers/specs/2026-07-30-admin-bereich-design.md.
    """
    massnahme = Massnahme(
        schueler_id=schueler_id,
        massnahmen_typ_id=massnahmen_typ_id,
        datum=datum,
        notiz=notiz,
        erfasst_von_nutzer_id=erfasst_von_nutzer_id,
    )
    db.add(massnahme)
    await db.flush()

    db.add(
        AuditLog(
            user_id=erfasst_von_nutzer_id,
            aktion="massnahme_erfasst",
            resource_typ="massnahme",
            resource_id=str(massnahme.id),
            details={"schueler_id": schueler_id, "massnahmen_typ_id": massnahmen_typ_id},
        )
    )

    typ_row = (await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == massnahmen_typ_id))).scalar_one()
    if typ_row.setzt_zaehler_zurueck:
        schueler = (await db.execute(select(Schueler).where(Schueler.id == schueler_id))).scalar_one()
        for typ in ("fehlzeiten", "klassenbuch"):
            regel = await resolve_schwellwert_regel(db, schueler.klasse_id, typ)
            if regel is None:
                continue
            zaehlerstand = await get_or_create_zaehlerstand(db, schueler_id, typ, regel.id)
            zaehlerstand.letzter_reset_am = datum
            zaehlerstand.aktueller_stand = 0
            zaehlerstand.erreichte_stufe_nr = None

    await db.commit()
    return massnahme
