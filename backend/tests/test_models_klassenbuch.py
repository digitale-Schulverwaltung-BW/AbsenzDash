import datetime

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_klassenbuch_eintrag_roundtrip(db_session):
    schueler = Schueler(webuntis_id=1, vorname="A", nachname="B")
    kategorie = ClassregCategory(name="stören", long_name="Störung des Unterrichts", group_name="Störung")
    db_session.add_all([schueler, kategorie])
    await db_session.flush()

    eintrag = KlassenbuchEintrag(
        webuntis_id=19245,
        schueler_id=schueler.id,
        kategorie_id=kategorie.id,
        datum=datetime.date(2026, 6, 23),
        text="Hat gestört",
        lesson_id=152327,
        erstellt_von_teacher_id=51,
        geaendert_von_teacher_id=51,
    )
    db_session.add(eintrag)
    await db_session.commit()

    result = await db_session.execute(select(KlassenbuchEintrag).where(KlassenbuchEintrag.webuntis_id == 19245))
    loaded = result.scalar_one()
    assert loaded.text == "Hat gestört"
    assert loaded.kategorie_id == kategorie.id
