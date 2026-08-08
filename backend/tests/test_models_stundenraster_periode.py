import pytest
from sqlalchemy.exc import IntegrityError

from app.models.stundenraster_periode import StundenrasterPeriode


@pytest.mark.asyncio
async def test_stundenraster_periode_roundtrip(db_session):
    periode = StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815)
    db_session.add(periode)
    await db_session.commit()

    assert periode.id is not None
    assert periode.wochentag == 1
    assert periode.start_zeit == 730
    assert periode.end_zeit == 815


@pytest.mark.asyncio
async def test_stundenraster_periode_unique_constraint_on_wochentag_stunde_nr(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=800, end_zeit=845))
    with pytest.raises(IntegrityError):
        await db_session.commit()
