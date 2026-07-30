import datetime

import pytest
from sqlalchemy import select

from app.models.schuljahr import Schuljahr


@pytest.mark.asyncio
async def test_schuljahr_roundtrip(db_session):
    schuljahr = Schuljahr(
        id=28,
        name="2025/2026",
        start_datum=datetime.date(2025, 9, 15),
        end_datum=datetime.date(2026, 7, 29),
    )
    db_session.add(schuljahr)
    await db_session.commit()

    result = await db_session.execute(select(Schuljahr).where(Schuljahr.id == 28))
    loaded = result.scalar_one()
    assert loaded.name == "2025/2026"
    assert loaded.start_datum == datetime.date(2025, 9, 15)
    assert loaded.end_datum == datetime.date(2026, 7, 29)
