from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr


@pytest.mark.asyncio
async def test_schueler_klasse_historie_roundtrip(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add_all([klasse, schueler])
    await db_session.flush()

    historie = SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id)
    db_session.add(historie)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id)
    )
    loaded = result.scalar_one()
    assert loaded.schuljahr_id == schuljahr.id
    assert loaded.klasse_id == klasse.id


@pytest.mark.asyncio
async def test_schueler_klasse_historie_klasse_id_is_nullable(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add_all([schuljahr, schueler])
    await db_session.flush()

    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    await db_session.commit()  # darf nicht scheitern


@pytest.mark.asyncio
async def test_schueler_klasse_historie_unique_per_schueler_and_schuljahr(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add_all([schuljahr, schueler])
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    await db_session.commit()

    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    with pytest.raises(IntegrityError):
        await db_session.commit()
