import datetime

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme
from app.models.schueler import Schueler
from app.services.ausnahme_service import create_ausnahme, revoke_ausnahme


@pytest.mark.asyncio
async def test_create_ausnahme_persists_and_writes_audit_log(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()

    ausnahme = await create_ausnahme(
        db_session,
        schueler_id=schueler.id,
        kategorie="fehlzeiten",
        grund="Ärztliches Attest",
        gueltig_bis=datetime.date(2026, 12, 31),
        nutzer_id=1,
    )

    assert ausnahme.id is not None
    assert ausnahme.aktiv is True

    reloaded = (
        await db_session.execute(select(Ausnahme).where(Ausnahme.id == ausnahme.id))
    ).scalar_one()
    assert reloaded.kategorie == "fehlzeiten"
    assert reloaded.grund == "Ärztliches Attest"
    assert reloaded.gueltig_bis == datetime.date(2026, 12, 31)

    audit_entries = (
        (await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "ausnahme")))
        .scalars()
        .all()
    )
    assert len(audit_entries) == 1
    assert audit_entries[0].aktion == "ausnahme_erstellt"
    assert audit_entries[0].resource_id == str(ausnahme.id)


@pytest.mark.asyncio
async def test_revoke_ausnahme_sets_inactive_and_writes_audit_log(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Test", aktiv=True)
    db_session.add(ausnahme)
    await db_session.commit()

    await revoke_ausnahme(db_session, ausnahme, nutzer_id=1)

    reloaded = (
        await db_session.execute(select(Ausnahme).where(Ausnahme.id == ausnahme.id))
    ).scalar_one()
    assert reloaded.aktiv is False

    audit_entries = (
        (await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "ausnahme")))
        .scalars()
        .all()
    )
    assert len(audit_entries) == 1
    assert audit_entries[0].aktion == "ausnahme_aufgehoben"
    assert audit_entries[0].resource_id == str(ausnahme.id)
