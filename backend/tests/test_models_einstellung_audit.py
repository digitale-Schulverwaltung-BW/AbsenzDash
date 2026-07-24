import datetime

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.einstellung import Einstellung


@pytest.mark.asyncio
async def test_einstellung_defaults(db_session):
    einstellung = Einstellung()
    db_session.add(einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Einstellung))
    loaded = result.scalar_one()
    assert loaded.initialer_import_abgeschlossen is False
    assert loaded.schuljahr_start_cache is None


@pytest.mark.asyncio
async def test_audit_log_roundtrip(db_session):
    entry = AuditLog(
        user_id=None,
        aktion="wordpress_proxy_created",
        resource_typ="nutzer",
        resource_id="1",
        details={"quelle": "wordpress_proxy"},
    )
    db_session.add(entry)
    await db_session.commit()

    result = await db_session.execute(select(AuditLog).where(AuditLog.resource_id == "1"))
    loaded = result.scalar_one()
    assert loaded.aktion == "wordpress_proxy_created"
    assert loaded.details == {"quelle": "wordpress_proxy"}
    assert isinstance(loaded.zeitpunkt, datetime.datetime)
