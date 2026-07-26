from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
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
    """Erfasst eine Massnahme; setzt bei setzt_zaehler_zurueck=True den Zaehlerstand des Schuelers
    fuer jeden Regel-Typ zurueck, FUER DEN DIE VERKNUEPFTE REGEL AUCH TATSAECHLICH GILT (nicht
    blind fuer jede verknuepfte Regel-Zeile - eine Regel kann klassen-/abteilungsspezifisch sein
    und nicht auf diesen Schueler zutreffen).
    """
    massnahme = Massnahme(
        schueler_id=schueler_id,
        massnahmen_typ_id=massnahmen_typ_id,
        datum=datum,
        notiz=notiz,
        erfasst_von_nutzer_id=erfasst_von_nutzer_id,
    )
    db.add(massnahme)

    typ_row = (await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == massnahmen_typ_id))).scalar_one()
    if typ_row.setzt_zaehler_zurueck:
        verknuepfte_regel_ids = set(
            (
                await db.execute(
                    select(massnahmen_typ_regel.c.regel_id).where(
                        massnahmen_typ_regel.c.massnahmen_typ_id == massnahmen_typ_id
                    )
                )
            )
            .scalars()
            .all()
        )
        schueler = (await db.execute(select(Schueler).where(Schueler.id == schueler_id))).scalar_one()
        betroffene_typen = {"fehlzeiten", "klassenbuch"}
        for typ in betroffene_typen:
            regel = await resolve_schwellwert_regel(db, schueler.klasse_id, typ)
            if regel is None or regel.id not in verknuepfte_regel_ids:
                continue
            zaehlerstand = await get_or_create_zaehlerstand(db, schueler_id, typ, regel.id)
            zaehlerstand.letzter_reset_am = datum
            zaehlerstand.aktueller_stand = 0
            zaehlerstand.erreichte_stufe_nr = None

    await db.commit()
    return massnahme
