import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_schueler_roundtrip(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()

    schueler = Schueler(
        externe_id="8a9041a6-95a2b47f-0195-a30963ad-0018",
        vorname="Max",
        nachname="Mustermann",
        klasse_id=klasse.id,
        aktiv=True,
    )
    db_session.add(schueler)
    await db_session.commit()

    result = await db_session.execute(
        select(Schueler).where(Schueler.externe_id == "8a9041a6-95a2b47f-0195-a30963ad-0018")
    )
    loaded = result.scalar_one()
    assert loaded.nachname == "Mustermann"
    assert loaded.aktiv is True
    assert loaded.klasse_id == klasse.id


@pytest.mark.asyncio
async def test_fehlzeit_unique_constraint_prevents_duplicate_sync(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    excuse_status = ExcuseStatus(name="nicht entsch.", long_name="nicht entschuldigt", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, excuse_status])
    await db_session.flush()

    kwargs = dict(
        schueler_id=schueler.id,
        typ="stunde",
        datum=datetime.date(2026, 7, 1),
        start_zeit=730,
        end_zeit=815,
        fach="Deutsch",
        excuse_status_id=excuse_status.id,
    )
    db_session.add(Fehlzeit(**kwargs))
    await db_session.commit()

    db_session.add(Fehlzeit(**kwargs))
    with pytest.raises(IntegrityError):
        await db_session.commit()
