from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import get_or_create_zaehlerstand


async def record_massnahme(
    db: AsyncSession,
    schueler_id: int,
    massnahmen_typ_id: int,
    datum: date,
    notiz: str | None,
    erfasst_von_nutzer_id: int,
) -> Massnahme:
    """Erfasst eine Massnahme; setzt bei setzt_zaehler_zurueck=True die verknuepften Zaehlerstaende zurueck.

    Der Zaehlerstand ist pro (schueler_id, typ) gefuehrt, nicht pro regel_id (SPECS.md Abschnitt 5,
    Zaehler ueberlebt Klassenwechsel) - daher wird hier ueber die verknuepften Regeln deren `typ`
    aufgeloest, statt direkt mit `regel_id` zu resetten.
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
        regeln_result = await db.execute(
            select(SchwellwertRegel)
            .join(massnahmen_typ_regel, massnahmen_typ_regel.c.regel_id == SchwellwertRegel.id)
            .where(massnahmen_typ_regel.c.massnahmen_typ_id == massnahmen_typ_id)
        )
        for regel in regeln_result.scalars().all():
            zaehlerstand = await get_or_create_zaehlerstand(db, schueler_id, regel.typ, regel.id)
            zaehlerstand.letzter_reset_am = datum
            zaehlerstand.aktueller_stand = 0
            zaehlerstand.erreichte_stufe_nr = None

    await db.commit()
    return massnahme
