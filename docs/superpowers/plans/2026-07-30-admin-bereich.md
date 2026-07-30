# Admin-Bereich (gebündelt) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Dashboard-SPA "Admin"-Bereich (Schwellwert-Regeln, Maßnahmen-Katalog, Entschuldigungsstatus, Sync-Einstellungen), reachable only by `schulleitung`, on top of the existing `/admin/*` backend endpoints — plus the two backend changes the design requires: auto-seeding `excuse_status` from the WebUntis sync, and removing the `massnahmen_typ_regel` junction table in favor of an unconditional reset.

**Architecture:** Backend changes are additive/simplifying to existing FastAPI routes/services (no new subsystem). Frontend adds a new `pages/Admin/` area with 4 subpages under a role-gated `/admin/*` route tree, following the existing SPA conventions (React Query hooks in `api/hooks/`, CSS Modules, `httpx`/vitest test patterns already used by `StudentDetail`/`StudentList`).

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Alembic / pytest (backend, `backend/`); React 18 / TypeScript / react-router-dom v6 / @tanstack/react-query / Vitest + React Testing Library (frontend, `frontend/`).

## Global Constraints

- Every new/changed admin endpoint stays behind `require_schulleitung` (`backend/app/api/deps.py:146-152`) — no partial role access (per [design doc](../specs/2026-07-30-admin-bereich-design.md)).
- Threshold-rule UI only offers `geltungsbereich` `schulweit`/`abteilung` — no `klasse` option (design doc).
- Excuse-status admin page is read-only except the `zaehlt_als_entschuldigt` checkbox per row — no name/long_name/aktiv editing, no delete (design doc).
- Measure-type reset behaviour becomes unconditional: `setzt_zaehler_zurueck=true` resets **both** `fehlzeiten` and `klassenbuch` counters for the student, no per-rule linkage (design doc).
- All backend service/schema/model changes follow existing repo conventions exactly (German field/variable names, `from __future__ import annotations`, existing test fixture names `db_session`/`HEADERS_SCHULLEITUNG`/`HEADERS_KLASSENLEHRKRAFT`).
- Every task ends green: run the affected test file(s) before committing.

---

## Task 1: Backend — Excuse-Status auto-seed during WebUntis sync

**Files:**
- Modify: `backend/app/services/webuntis_fehlzeit_sync.py:96-107`
- Test: `backend/tests/test_webuntis_fehlzeit_sync.py`

**Interfaces:**
- Consumes: `app.models.excuse_status.ExcuseStatus` (existing: `id`, `name`, `long_name`, `zaehlt_als_entschuldigt`, `aktiv`).
- Produces: no new public function — `sync_fehlzeiten` behaviour changes (unknown `excuseStatus` strings are now persisted instead of mapping to `None`).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_webuntis_fehlzeit_sync.py` (after `test_sync_fehlzeiten_resolves_excuse_status_by_name`):

```python
@pytest.mark.asyncio
async def test_sync_fehlzeiten_auto_creates_unknown_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "hybrid", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    status_result = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.name == "hybrid"))
    neuer_status = status_result.scalar_one()
    assert neuer_status.zaehlt_als_entschuldigt is False

    fehlzeit_result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = fehlzeit_result.scalar_one()
    assert fehlzeit.excuse_status_id == neuer_status.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_does_not_duplicate_known_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    bestehender_status = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add_all([schueler, bestehender_status])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    status_result = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.name == "entsch."))
    rows = status_result.scalars().all()
    assert len(rows) == 1
    assert rows[0].zaehlt_als_entschuldigt is True  # unveraendert, nicht auf False zurueckgesetzt

    fehlzeit_result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert fehlzeit_result.scalar_one().excuse_status_id == bestehender_status.id
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: the two new tests FAIL (`test_sync_fehlzeiten_auto_creates_unknown_excuse_status` fails because no `ExcuseStatus` row named `"hybrid"` gets created; `test_sync_fehlzeiten_does_not_duplicate_known_excuse_status` should already PASS since it doesn't yet exercise new behavior — if it also fails, re-check the assertion).

- [ ] **Step 3: Implement auto-seeding**

In `backend/app/services/webuntis_fehlzeit_sync.py`, replace lines 102-106:

```python
    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())
    zaehlt_als_entschuldigt_by_id = dict(
        (await db.execute(select(ExcuseStatus.id, ExcuseStatus.zaehlt_als_entschuldigt))).all()
    )
```

with:

```python
    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())

    # excuse_status wird nicht manuell vorgepflegt (siehe TECH-SPEC.md Abschnitt 1.2/5) - unbekannte
    # WebUntis-excuseStatus-Namen automatisch anlegen statt sie dauerhaft als NULL zu importieren.
    # zaehlt_als_entschuldigt=False als sicherer Default: das Flag ist ueber keine WebUntis-JSON-RPC-
    # Methode abrufbar, ein Mensch muss es im Admin-Bereich bestaetigen.
    unbekannte_namen = {
        row.get("excuseStatus")
        for row in entries or []
        if row.get("excuseStatus") and row.get("excuseStatus") not in excuse_status_id_by_name
    }
    for name in unbekannte_namen:
        db.add(ExcuseStatus(name=name, zaehlt_als_entschuldigt=False))
        logger.info(
            "Fehlzeiten-Sync: unbekannter excuseStatus '%s' automatisch angelegt (zaehlt_als_entschuldigt=False)",
            name,
        )
    if unbekannte_namen:
        await db.flush()
        excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())

    zaehlt_als_entschuldigt_by_id = dict(
        (await db.execute(select(ExcuseStatus.id, ExcuseStatus.zaehlt_als_entschuldigt))).all()
    )
```

Note `entries` is already computed above this block (line 100: `entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result`) — the new code reads it, no reordering of the surrounding function needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: all tests PASS (including the two new ones and the 4 pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/webuntis_fehlzeit_sync.py backend/tests/test_webuntis_fehlzeit_sync.py
git commit -m "feat: auto-create unknown excuse statuses during WebUntis sync"
```

---

## Task 2: Backend — Remove `massnahmen_typ_regel`, unconditional counter reset

**Files:**
- Create: `backend/alembic/versions/<new_hash>_drop_massnahmen_typ_regel.py`
- Modify: `backend/app/models/massnahmen_typ.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/schemas/admin.py:44-57` (`MeasureTypeIn`/`MeasureTypeOut`)
- Modify: `backend/app/services/measure_type_service.py`
- Modify: `backend/app/services/massnahme_service.py:15-73` (`record_massnahme`)
- Modify: `backend/tests/test_models_massnahme.py`
- Modify: `backend/tests/test_massnahme_service.py`
- Modify: `backend/tests/test_api_admin_measure_types.py`

**Interfaces:**
- Consumes: `resolve_schwellwert_regel(db, klasse_id, typ) -> SchwellwertRegel | None` and `get_or_create_zaehlerstand(db, schueler_id, typ, regel_id) -> SchuelerZaehlerstand` (both existing, `backend/app/services/eskalations_pruefung.py:35-61`/`64-...`, unchanged signatures).
- Produces: `MeasureTypeIn`/`MeasureTypeOut` no longer have a `betroffene_regel_ids` field. `record_massnahme` keeps its exact existing signature.

- [ ] **Step 1: Write the failing tests (model + service layer)**

Replace `backend/tests/test_models_massnahme.py` in full with:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_massnahme_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, typ, nutzer])
    await db_session.flush()

    massnahme = Massnahme(
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz="Testnotiz",
        erfasst_von_nutzer_id=nutzer.id,
    )
    db_session.add(massnahme)
    await db_session.commit()

    result = await db_session.execute(select(Massnahme).where(Massnahme.schueler_id == schueler.id))
    loaded = result.scalar_one()
    assert loaded.notiz == "Testnotiz"


@pytest.mark.asyncio
async def test_massnahmen_typ_defaults_to_aktiv(db_session):
    typ = MassnahmenTyp(name="Testtyp", setzt_zaehler_zurueck=False)
    db_session.add(typ)
    await db_session.commit()

    result = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == typ.id))
    assert result.scalar_one().aktiv is True
```

(This drops `test_massnahmen_typ_regel_association` entirely — the table it tests is being removed.)

Replace `backend/tests/test_massnahme_service.py` in full with:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import get_or_create_zaehlerstand
from app.services.massnahme_service import record_massnahme


@pytest.mark.asyncio
async def test_record_massnahme_resets_both_zaehlerstaende(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    fehlzeiten_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    klassenbuch_regel = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, fehlzeiten_regel, klassenbuch_regel, typ, nutzer])
    await db_session.flush()

    fz_zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", fehlzeiten_regel.id)
    fz_zaehlerstand.aktueller_stand = 5
    fz_zaehlerstand.erreichte_stufe_nr = 1
    kb_zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "klassenbuch", klassenbuch_regel.id)
    kb_zaehlerstand.aktueller_stand = 3
    kb_zaehlerstand.erreichte_stufe_nr = 1
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    by_typ = {z.typ: z for z in result.scalars().all()}
    assert by_typ["fehlzeiten"].aktueller_stand == 0
    assert by_typ["fehlzeiten"].erreichte_stufe_nr is None
    assert by_typ["fehlzeiten"].letzter_reset_am == datetime.date(2026, 1, 20)
    assert by_typ["klassenbuch"].aktueller_stand == 0
    assert by_typ["klassenbuch"].erreichte_stufe_nr is None

    massnahme_result = await db_session.execute(select(Massnahme).where(Massnahme.schueler_id == schueler.id))
    assert massnahme_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_record_massnahme_does_not_reset_when_flag_false(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, regel, typ, nutzer])
    await db_session.flush()

    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.typ == "fehlzeiten"
        )
    )
    assert result.scalar_one().aktueller_stand == 5


@pytest.mark.asyncio
async def test_record_massnahme_resets_by_typ_even_if_current_regel_differs_from_original(db_session):
    """Simuliert einen echten Klassenwechsel: der Zaehlerstand entstand unter einer klassen-
    spezifischen Regel fuer die alte Klasse; zwischen Entstehung und Massnahmen-Erfassung wechselt
    der Schueler die Klasse, wodurch eine ANDERE klassen-spezifische Regel (gleicher typ) fuer ihn
    zustaendig wird. Der Reset muss unter der jetzt aufgeloesten Regel erfolgen."""
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_a.id)
    alte_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_a.id)
    db_session.add_all([schueler, alte_regel])
    await db_session.flush()
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, "fehlzeiten", alte_regel.id)
    zaehlerstand.aktueller_stand = 5
    await db_session.commit()

    schueler.klasse_id = klasse_b.id
    neue_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse_b.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([neue_regel, typ, nutzer])
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1  # gleiche Zeile, nicht eine neue - Zaehlerstand ist pro (schueler, typ), nicht pro regel
    assert rows[0].aktueller_stand == 0
    assert rows[0].regel_id == neue_regel.id  # zuletzt angewendete Regel aktualisiert


@pytest.mark.asyncio
async def test_record_massnahme_skips_typ_with_no_applicable_regel(db_session):
    """Fuer 'klassenbuch' existiert (noch) keine Regel im System - der Reset fuer diesen typ wird
    uebersprungen, ohne Fehler, statt einen Zaehlerstand mit regel_id=None zu erzwingen."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    fehlzeiten_regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, fehlzeiten_regel, typ, nutzer])
    await db_session.commit()

    await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].typ == "fehlzeiten"
    assert rows[0].aktueller_stand == 0


@pytest.mark.asyncio
async def test_record_massnahme_writes_audit_log_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, typ, nutzer])
    await db_session.flush()

    massnahme = await record_massnahme(
        db_session,
        schueler_id=schueler.id,
        massnahmen_typ_id=typ.id,
        datum=datetime.date(2026, 1, 20),
        notiz=None,
        erfasst_von_nutzer_id=nutzer.id,
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "massnahme"))
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].aktion == "massnahme_erfasst"
    assert entries[0].resource_id == str(massnahme.id)
    assert entries[0].user_id == nutzer.id
```

(This drops `test_record_massnahme_does_not_reset_when_linked_regel_does_not_apply_to_student` — the scenario it guards against, a measure type linked only to an unrelated rule, no longer exists once linkage is removed — and adds `test_record_massnahme_resets_both_zaehlerstaende` and `test_record_massnahme_skips_typ_with_no_applicable_regel` to cover the new unconditional-but-per-typ-resolved behaviour.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_models_massnahme.py tests/test_massnahme_service.py -v`
Expected: FAIL — `massnahmen_typ_regel` import still required by the (not-yet-changed) `massnahme_service.py`, and `test_record_massnahme_resets_both_zaehlerstaende`/`test_record_massnahme_skips_typ_with_no_applicable_regel` fail because the current implementation still checks `massnahmen_typ_regel` membership, which is empty in these new tests (nothing was ever inserted into the junction table), so nothing gets reset.

- [ ] **Step 3: Simplify `record_massnahme`**

In `backend/app/services/massnahme_service.py`, remove the `massnahmen_typ_regel` import (line 10, `from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel` → `from app.models.massnahmen_typ import MassnahmenTyp`), and replace the reset block (originally lines 51-72):

```python
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
```

Also update the function's docstring (originally lines 16-20):

```python
    """Erfasst eine Massnahme; setzt bei setzt_zaehler_zurueck=True beide Zaehlerstaende
    (fehlzeiten und klassenbuch) des Schuelers zurueck, jeweils unter der fuer ihn aktuell
    aufgeloesten Regel (resolve_schwellwert_regel) - ohne Regel-Verknuepfung, siehe
    docs/superpowers/specs/2026-07-30-admin-bereich-design.md.
    """
```

Confirm `resolve_schwellwert_regel` and `get_or_create_zaehlerstand` are already imported at the top of the file (they are, per existing code) — no import changes needed for those two.

- [ ] **Step 4: Remove the junction table from the model layer**

Replace `backend/app/models/massnahmen_typ.py` in full:

```python
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MassnahmenTyp(Base, TimestampMixin):
    __tablename__ = "massnahmen_typ"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    setzt_zaehler_zurueck: Mapped[bool] = mapped_column(Boolean, default=False)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
```

In `backend/app/models/__init__.py`, remove the `massnahmen_typ_regel` import/re-export (keep the `MassnahmenTyp` import) — find the two lines referencing it (per Explore agent's report: lines 14 and 39) and delete only the `massnahmen_typ_regel` name from each (e.g. `from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel` → `from app.models.massnahmen_typ import MassnahmenTyp`, and remove `"massnahmen_typ_regel"` from the `__all__` list if present).

- [ ] **Step 5: Simplify the schema**

In `backend/app/schemas/admin.py`, remove `betroffene_regel_ids` from both `MeasureTypeIn` and `MeasureTypeOut` (lines 44-57):

```python
class MeasureTypeIn(BaseModel):
    id: int | None = None
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool = True


class MeasureTypeOut(BaseModel):
    id: int
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool = True
```

- [ ] **Step 6: Simplify `measure_type_service.py`**

Replace `backend/app/services/measure_type_service.py` in full:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.database import ist_unique_violation
from app.models.audit_log import AuditLog
from app.models.massnahmen_typ import MassnahmenTyp
from app.schemas.admin import MeasureTypeIn, MeasureTypeOut


def _typ_out(typ: MassnahmenTyp) -> MeasureTypeOut:
    return MeasureTypeOut(
        id=typ.id,
        name=typ.name,
        setzt_zaehler_zurueck=typ.setzt_zaehler_zurueck,
        aktiv=typ.aktiv,
    )


async def list_measure_types(db: AsyncSession) -> list[MeasureTypeOut]:
    result = await db.execute(select(MassnahmenTyp).order_by(MassnahmenTyp.id))
    return [_typ_out(t) for t in result.scalars().all()]


def _validate_payload(payload: list[MeasureTypeIn]) -> None:
    seen_ids: set[int] = set()
    for typ in payload:
        if typ.id is None:
            continue
        if typ.id in seen_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {typ.id}")
        seen_ids.add(typ.id)

    seen_names: set[str] = set()
    for typ in payload:
        if not typ.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if typ.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {typ.name}")
        seen_names.add(typ.name)


async def replace_measure_types(
    db: AsyncSession, payload: list[MeasureTypeIn], nutzer_id: int
) -> list[MeasureTypeOut]:
    _validate_payload(payload)

    existing_result = await db.execute(select(MassnahmenTyp))
    existing_by_id = {t.id: t for t in existing_result.scalars().all()}

    for typ_in in payload:
        if typ_in.id is not None and typ_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown measure type id: {typ_in.id}")

    payload_ids = {t.id for t in payload if t.id is not None}
    removed_ids = [tid for tid in existing_by_id if tid not in payload_ids]
    removed_names = [existing_by_id[tid].name for tid in removed_ids]

    try:
        for typ_id in removed_ids:
            await db.delete(existing_by_id[typ_id])

        for typ_in in payload:
            if typ_in.id is not None:
                typ = existing_by_id[typ_in.id]
                typ.name = typ_in.name
                typ.setzt_zaehler_zurueck = typ_in.setzt_zaehler_zurueck
                typ.aktiv = typ_in.aktiv
            else:
                db.add(
                    MassnahmenTyp(
                        name=typ_in.name, setzt_zaehler_zurueck=typ_in.setzt_zaehler_zurueck, aktiv=typ_in.aktiv
                    )
                )

        db.add(
            AuditLog(
                user_id=nutzer_id,
                aktion="admin_measure_types_updated",
                resource_typ="massnahmen_typ",
                details={"anzahl_typen": len(payload)},
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ist_unique_violation(exc):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Name bereits vergeben — bitte einen eindeutigen Namen für den Maßnahmen-Typ wählen.",
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kann folgende(n) Maßnahmen-Typ(en) nicht löschen, da bereits verwendet: "
            f"{', '.join(removed_names)}. Stattdessen deaktivieren (aktiv=false).",
        )

    return await list_measure_types(db)
```

(Note `_typ_out` is now synchronous and no longer takes `db` — it no longer queries the junction table. `replace_measure_types` no longer needs a flush-before-insert-into-junction-table step for new rows, so the `await db.flush()` that used to sit inside the `else` branch for new types is gone too — verify this doesn't reintroduce the flush-ordering bug from `test_put_measure_types_returns_409_when_deleting_used_type_alongside_new_type`, see Step 7.)

- [ ] **Step 7: Update the API test file**

Replace `backend/tests/test_api_admin_measure_types.py` in full — same as the current file but with every `"betroffene_regel_ids": [...]` key removed from every payload dict, `test_put_measure_types_upserts_and_reassigns_betroffene_regeln` renamed/simplified to no longer assert on `betroffene_regel_ids`, and `test_put_measure_types_rejects_unknown_regel_id` deleted (the field it tests no longer exists):

```python
import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler

HEADERS_SCHULLEITUNG = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "schulleitung",
}
HEADERS_KLASSENLEHRKRAFT = {**HEADERS_SCHULLEITUNG, "X-WordPress-Role": "klassenlehrkraft"}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_get_measure_types_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/measure-types", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_measure_types_creates_type(db_session):
    payload = [{"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body[0]["name"] == "Nachsitzen"
    assert body[0]["aktiv"] is True

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_measure_types_updated"))
    assert audit_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_measure_types_upserts_existing_type(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    db_session.add(typ)
    await db_session.commit()

    payload = [{"id": typ.id, "name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": False}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == typ.id
    assert body[0]["aktiv"] is False


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_when_deleting_used_type(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([typ, schueler, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 1, 20),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 409

    remaining = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == typ.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_when_deleting_used_type_alongside_new_type(db_session):
    """Regression test: the in-use type is deleted implicitly (omitted from payload) while a
    brand-new type is created in the same request. The delete-then-insert-then-commit sequence
    must surface the FK violation as a 409, not an unhandled 500."""
    used_typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([used_typ, schueler, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=used_typ.id,
            datum=datetime.date(2026, 1, 20),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    payload = [{"name": "Neuer Typ", "setzt_zaehler_zurueck": False, "aktiv": True}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 409

    remaining = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == used_typ.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_with_name_conflict_message(db_session):
    bestehend = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    db_session.add(bestehend)
    await db_session.commit()

    payload = [
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": False, "aktiv": True},
        {"id": bestehend.id, "name": "Bußgeld", "setzt_zaehler_zurueck": True, "aktiv": True},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Name bereits vergeben" in detail
    assert "bereits verwendet" not in detail

    await db_session.rollback()
    remaining = await db_session.execute(select(MassnahmenTyp))
    rows = remaining.scalars().all()
    assert [r.name for r in rows] == ["Nachsitzen"]


@pytest.mark.asyncio
async def test_put_measure_types_rejects_duplicate_id_in_payload(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    db_session.add(typ)
    await db_session.commit()

    payload = [
        {"id": typ.id, "name": "A", "setzt_zaehler_zurueck": False, "aktiv": True},
        {"id": typ.id, "name": "B", "setzt_zaehler_zurueck": True, "aktiv": False},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 422
    assert "Duplicate id in payload" in response.json()["detail"]

    await db_session.rollback()
    remaining = await db_session.execute(select(MassnahmenTyp))
    rows = remaining.scalars().all()
    assert [(r.name, r.setzt_zaehler_zurueck) for r in rows] == [("Nachsitzen", True)]


@pytest.mark.asyncio
async def test_put_measure_types_deletes_unused_type(db_session):
    typ = MassnahmenTyp(name="Tippfehler", setzt_zaehler_zurueck=False, aktiv=True)
    db_session.add(typ)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 200
    remaining = await db_session.execute(select(MassnahmenTyp))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_measure_types_rejects_duplicate_name(db_session):
    payload = [
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True},
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": False, "aktiv": True},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_measure_types_rejects_empty_name(db_session):
    payload = [{"name": "   ", "setzt_zaehler_zurueck": False, "aktiv": True}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_measure_types_rejects_unknown_id(db_session):
    payload = [{"id": 999999, "name": "X", "setzt_zaehler_zurueck": False, "aktiv": True}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422
```

- [ ] **Step 8: Run all affected backend tests**

Run: `cd backend && python -m pytest tests/test_models_massnahme.py tests/test_massnahme_service.py tests/test_api_admin_measure_types.py -v`
Expected: all PASS.

- [ ] **Step 9: Write the migration**

Find the current Alembic head first: `cd backend && python -m alembic heads` (expected: `ecbb0df17a38`). Create `backend/alembic/versions/<new_hash>_drop_massnahmen_typ_regel.py` (use `python -m alembic revision -m "drop massnahmen_typ_regel"` to get a real hash, then fill in the body):

```python
"""drop massnahmen_typ_regel

Massnahmen-Typen setzen bei setzt_zaehler_zurueck=True jetzt unconditional beide
Zaehlerstaende (fehlzeiten + klassenbuch) des Schuelers zurueck, statt an spezifische
schwellwert_regel-Zeilen gebunden zu sein (siehe docs/superpowers/specs/2026-07-30-admin-bereich-design.md).
Das eliminiert die vorher moegliche "Admin-Falle": eine Verknuepfung nur mit der schulweiten
Regel, die bei Schuelern unter einer spezifischeren Regel still keinen Reset ausloeste.

Revision ID: <new_hash>
Revises: ecbb0df17a38
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "<new_hash>"
down_revision = "ecbb0df17a38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("massnahmen_typ_regel")


def downgrade() -> None:
    op.create_table(
        "massnahmen_typ_regel",
        sa.Column("massnahmen_typ_id", sa.Integer(), nullable=False),
        sa.Column("regel_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["massnahmen_typ_id"], ["massnahmen_typ.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["regel_id"], ["schwellwert_regel.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("massnahmen_typ_id", "regel_id"),
    )
```

Replace `<new_hash>` in both the filename and the `revision =` line with whatever `alembic revision` generated.

- [ ] **Step 10: Verify the migration runs**

Run: `cd backend && python -m alembic upgrade head` against a disposable/dev database (check `backend/README.md` or `docker-compose.yml` for how the dev DB is normally reached — do not run against a database with real school data). Confirm no error, and that `python -m alembic downgrade -1 && python -m alembic upgrade head` round-trips cleanly.

- [ ] **Step 11: Run the full backend test suite**

Run: `cd backend && python -m pytest`
Expected: all tests pass (this catches any remaining stray reference to `massnahmen_typ_regel` the earlier steps missed).

- [ ] **Step 12: Commit**

```bash
git add backend/alembic/versions backend/app/models/massnahmen_typ.py backend/app/models/__init__.py \
  backend/app/schemas/admin.py backend/app/services/measure_type_service.py backend/app/services/massnahme_service.py \
  backend/tests/test_models_massnahme.py backend/tests/test_massnahme_service.py backend/tests/test_api_admin_measure_types.py
git commit -m "refactor: measures reset both counters unconditionally, drop massnahmen_typ_regel"
```

---

## Task 3: Backend — Expose the current user's role to the frontend

**Files:**
- Modify: `backend/app/schemas/dashboard.py:19-21` (`NavOptionsOut`)
- Modify: `backend/app/services/dashboard_query.py` (`get_nav_options`, return statement)
- Test: `backend/tests/test_dashboard_query.py` or `backend/tests/test_api_dashboard.py` (whichever file already covers `nav-options` — check with `grep -rl "nav-options\|get_nav_options" backend/tests/` and add to that file)

**Interfaces:**
- Produces: `NavOptionsOut` gains `rolle: str` — every consumer of this response (frontend `NavOptions` type, Task 5) must add the matching field.

- [ ] **Step 1: Write the failing test**

Run `grep -rn "get_nav_options\|nav-options" backend/tests/*.py` to find the existing test file/tests for this endpoint. Add a new test there (adapt the exact `Nutzer`/fixture construction to match what neighboring tests in that file already do — they already build a `Nutzer` with a `rolle`):

```python
@pytest.mark.asyncio
async def test_get_nav_options_includes_rolle(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert result.rolle == "schulleitung"
```

(Add whatever imports this needs — `from app.models.nutzer import Nutzer`, `from app.services import dashboard_query` — matching the existing import style at the top of the chosen test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/<chosen_file>.py -k test_get_nav_options_includes_rolle -v`
Expected: FAIL with `AttributeError: 'NavOptionsOut' object has no attribute 'rolle'` or a Pydantic validation error.

- [ ] **Step 3: Add the field**

In `backend/app/schemas/dashboard.py`, change:

```python
class NavOptionsOut(BaseModel):
    bereiche: list[NavBereichOut]
    klassen: list[NavKlasseOut]
```

to:

```python
class NavOptionsOut(BaseModel):
    bereiche: list[NavBereichOut]
    klassen: list[NavKlasseOut]
    rolle: str
```

In `backend/app/services/dashboard_query.py`, find the `return NavOptionsOut(` call at the end of `get_nav_options` and add `rolle=nutzer.rolle` as one of its keyword arguments (the function already receives `nutzer: Nutzer` as a parameter, so no new lookup is needed).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/<chosen_file>.py -k test_get_nav_options_includes_rolle -v`
Expected: PASS. Then run the full file: `python -m pytest tests/<chosen_file>.py -v` to make sure no existing test asserting the exact `NavOptionsOut`/JSON shape broke.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/dashboard.py backend/app/services/dashboard_query.py backend/tests/<chosen_file>.py
git commit -m "feat: include current user's role in GET /dashboard/nav-options"
```

---

## Task 4: Backend — `GET /admin/abteilungen`

**Files:**
- Modify: `backend/app/schemas/admin.py` (add `AbteilungOut`)
- Modify: `backend/app/services/bereich_service.py` (add `list_abteilungen`)
- Modify: `backend/app/api/routes/admin.py` (add route)
- Test: `backend/tests/test_api_admin_bereiche.py` or wherever `GET /admin/klassen`/`GET /admin/bereiche` are already tested — check with `grep -rln "admin/klassen\|admin/bereiche" backend/tests/`

**Interfaces:**
- Produces: `GET /admin/abteilungen -> list[AbteilungOut]` where `AbteilungOut = {id: int, name: str}`, `schulleitung`-only (inherits the router-level dependency).

- [ ] **Step 1: Write the failing test**

Add to the test file identified above (mirror the exact structure of that file's existing `GET /admin/klassen` test):

```python
@pytest.mark.asyncio
async def test_get_abteilungen_returns_all(db_session):
    abteilung_a = Abteilung(webuntis_id=1, name="Kaufmännisch")
    abteilung_b = Abteilung(webuntis_id=2, name="Gewerblich")
    db_session.add_all([abteilung_a, abteilung_b])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/abteilungen", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    names = sorted(item["name"] for item in response.json())
    assert names == ["Gewerblich", "Kaufmännisch"]


@pytest.mark.asyncio
async def test_get_abteilungen_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/abteilungen", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403
```

(Add `from app.models.abteilung import Abteilung` to the file's imports if not already present.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/<chosen_file>.py -k test_get_abteilungen -v`
Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Add the schema**

In `backend/app/schemas/admin.py`, add (near `KlasseOut`):

```python
class AbteilungOut(BaseModel):
    id: int
    name: str
```

- [ ] **Step 4: Add the service function**

In `backend/app/services/bereich_service.py`, add (near `list_klassen`, matching its exact style):

```python
async def list_abteilungen(db: AsyncSession) -> list[AbteilungOut]:
    result = await db.execute(select(Abteilung).order_by(Abteilung.name))
    return [AbteilungOut(id=a.id, name=a.name) for a in result.scalars().all()]
```

Add the needed imports at the top of the file: `from app.models.abteilung import Abteilung` and add `AbteilungOut` to the existing `from app.schemas.admin import (...)` block.

- [ ] **Step 5: Add the route**

In `backend/app/api/routes/admin.py`, add `AbteilungOut` to the existing `from app.schemas.admin import (...)` block, and add the route next to `get_klassen`:

```python
@router.get("/abteilungen")
async def get_abteilungen(db: Annotated[AsyncSession, Depends(get_db)]) -> list[AbteilungOut]:
    return await bereich_service.list_abteilungen(db)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/<chosen_file>.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/bereich_service.py backend/app/api/routes/admin.py backend/tests/<chosen_file>.py
git commit -m "feat: add GET /admin/abteilungen for the threshold-rules admin UI"
```

---

## Task 5: Frontend — API client PUT support, admin types, role-gated Admin nav + route

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/hooks/useNavOptions.ts` (no code change needed — already generic — but note it now returns `rolle`)
- Create: `frontend/src/components/Navigation/Navigation.tsx` (modify)
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/api/client.test.ts`, `frontend/src/components/Navigation/Navigation.test.tsx`, `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: `apiPut<T>(path: string, body: unknown): Promise<T>` (mirrors `apiPost`). `NavOptions.rolle: string`. A `RequireSchulleitung` wrapper component used by `App.tsx` to gate the `/admin/*` route subtree.
- Consumes: `useNavOptions()` (existing, now returns `rolle`).

- [ ] **Step 1: Write the failing test for `apiPut`**

Read `frontend/src/api/client.test.ts` first to copy its exact mocking style for `fetch`/`window.absenzdashConfig` (it already has tests for `apiGet`/`apiPost`/`apiDelete` — follow that pattern exactly). Add a test analogous to the existing `apiPost` test but for `apiPut`, asserting `method: "PUT"` is sent and the JSON response is returned.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL — `apiPut` is not exported yet.

- [ ] **Step 3: Implement `apiPut`**

In `frontend/src/api/client.ts`, add after `apiPost`:

```ts
export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "PUT",
    headers: { "X-WP-Nonce": config.nonce, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, `PUT ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Add admin types**

In `frontend/src/api/types.ts`, update `NavOptions` and add the new admin types:

```ts
export interface NavOptions {
  bereiche: NavBereich[];
  klassen: NavKlasse[];
  rolle: string;
}

export interface SchwellwertStufe {
  id?: number;
  stufe_nr: number;
  einheit: "fehltage" | "fehlstunden" | null;
  schwellenwert: number;
  fehlzeiten_filter: "nur_unentschuldigt" | "alle" | null;
  empfaenger_rollen: string[];
}

export interface ThresholdRule {
  id?: number;
  typ: "fehlzeiten" | "klassenbuch";
  geltungsbereich: "schulweit" | "abteilung";
  abteilung_id: number | null;
  stufen: SchwellwertStufe[];
}

export interface MeasureType {
  id?: number;
  name: string;
  setzt_zaehler_zurueck: boolean;
  aktiv: boolean;
}

export interface ExcuseStatus {
  id: number;
  name: string;
  long_name: string | null;
  zaehlt_als_entschuldigt: boolean;
  aktiv: boolean;
}

export interface SyncSettings {
  sync_interval_cron: string;
  schuljahr_start_cache: string | null;
  letzter_sync_am: string | null;
}

export interface Abteilung {
  id: number;
  name: string;
}
```

(`ThresholdRule`/`SchwellwertStufe` omit `klasse_id` entirely — the frontend only ever sends `abteilung_id`, matching the design's `schulweit`/`abteilung`-only scope. The backend schema still has `klasse_id: int | None = None` — Pydantic defaults it to `null` when the frontend omits it, so no backend change is required for this restriction.)

- [ ] **Step 6: Add the Admin nav link, gated by role**

In `frontend/src/components/Navigation/Navigation.tsx`, add after the "Schülerliste" `<Link>` (inside the existing `.tabs` div):

```tsx
        {data.rolle === "schulleitung" && (
          <Link
            to={{ pathname: "/admin", search: location.search }}
            className={location.pathname.startsWith("/admin") ? styles.tabActive : styles.tab}
          >
            Admin
          </Link>
        )}
```

- [ ] **Step 7: Add a route guard and register the (not-yet-built) Admin routes**

In `frontend/src/App.tsx`, add a small guard component and the nested admin routes (the actual `Admin*` page components are created in Tasks 6-9 — for this task, stub them minimally so the route tree compiles and is testable; the stubs get replaced file-by-file in later tasks, so don't create placeholder files under `pages/Admin/` here — instead, leave the admin route registration to Task 6, which is the first task that creates a real page component. For this task, only add the guard component and export it, without wiring a route yet):

```tsx
import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { Navigation } from "./components/Navigation/Navigation";
import { Landing } from "./pages/Landing/Landing";
import { StudentDetail } from "./pages/StudentDetail/StudentDetail";
import { StudentList } from "./pages/StudentList/StudentList";

function Layout() {
  return (
    <div>
      <Navigation />
      <main>
        <Outlet />
      </main>
    </div>
  );
}

export function RequireSchulleitung({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useNavOptions();
  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (data?.rolle !== "schulleitung") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/schueler" element={<StudentList />} />
        <Route path="/schueler/:id" element={<StudentDetail />} />
      </Route>
    </Routes>
  );
}
```

This step only introduces `RequireSchulleitung` as an exported helper — it isn't used by any route yet, so add a short test for it directly (Step 8) rather than relying on an `/admin` route test that doesn't exist until Task 6.

- [ ] **Step 8: Write tests for the nav link and the guard**

In `frontend/src/components/Navigation/Navigation.test.tsx`, add two cases (mirroring the existing mock-`useNavOptions` setup already in that file — check how `mockUseNavOptions.mockReturnValue` is structured there and add `rolle` to every existing mock's returned `data` object so those tests keep passing):

```tsx
it("shows the Admin link for schulleitung", () => {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [], rolle: "schulleitung" },
    isLoading: false,
    isError: false,
  } as any);
  render(<MemoryRouter><Navigation /></MemoryRouter>);
  expect(screen.getByText("Admin")).toBeInTheDocument();
});

it("hides the Admin link for other roles", () => {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [], rolle: "klassenlehrkraft" },
    isLoading: false,
    isError: false,
  } as any);
  render(<MemoryRouter><Navigation /></MemoryRouter>);
  expect(screen.queryByText("Admin")).not.toBeInTheDocument();
});
```

(Check the exact mock import/setup names already used at the top of `Navigation.test.tsx` and match them — the Explore report notes this file already mocks `useNavOptions`.)

In `frontend/src/App.test.tsx`, add `rolle: "klassenlehrkraft"` to the existing `mockUseNavOptions.mockReturnValue({ data: { bereiche: [], klassen: [] }, ...})` call in `setupMocks()` (all 4 existing tests reuse this one `setupMocks()` function) so the existing tests keep passing with the now-required field.

Add a new test in `App.test.tsx` for `RequireSchulleitung` directly (import it as a named export):

```tsx
import { RequireSchulleitung } from "./App";

it("RequireSchulleitung redirects non-schulleitung users away", () => {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [], rolle: "klassenlehrkraft" },
    isLoading: false,
    isError: false,
  } as any);
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<div>Startseite</div>} />
        <Route path="/geschuetzt" element={<RequireSchulleitung><div>Geheim</div></RequireSchulleitung>} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.queryByText("Geheim")).not.toBeInTheDocument();
});
```

(This needs `Routes`/`Route` imported from `react-router-dom` in the test file if not already.)

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/client.test.ts src/components/Navigation/Navigation.test.tsx src/App.test.tsx`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/types.ts frontend/src/components/Navigation/Navigation.tsx \
  frontend/src/App.tsx frontend/src/api/client.test.ts frontend/src/components/Navigation/Navigation.test.tsx frontend/src/App.test.tsx
git commit -m "feat: add apiPut, admin types, and role-gated Admin nav entry"
```

---

## Task 6: Frontend — Sync-Einstellungen page (first Admin subpage; wires up the route tree)

**Files:**
- Create: `frontend/src/pages/Admin/AdminLayout.tsx`
- Create: `frontend/src/pages/Admin/AdminLayout.module.css`
- Create: `frontend/src/pages/Admin/SyncSettings.tsx`
- Create: `frontend/src/api/hooks/useSyncSettings.ts`
- Create: `frontend/src/api/hooks/useUpdateSyncSettings.ts`
- Create: `frontend/src/api/hooks/useTriggerSyncNow.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/api/hooks/useSyncSettings.test.tsx`, `frontend/src/pages/Admin/SyncSettings.test.tsx`, `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `apiGet`/`apiPut`/`apiPost` (Task 5), `SyncSettings` type (Task 5), `RequireSchulleitung` (Task 5).
- Produces: `AdminLayout` component (renders the 4-tab sub-nav + `<Outlet/>`) reused by Tasks 7-9.

- [ ] **Step 1: Write the failing hook tests**

Create `frontend/src/api/hooks/useSyncSettings.test.tsx` (mirror `useStudentCatalog.test.tsx`'s structure exactly):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useSyncSettings } from "./useSyncSettings";

describe("useSyncSettings", () => {
  it("fetches admin/sync-settings", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue({
      sync_interval_cron: "*/30 * * * *",
      schuljahr_start_cache: "2025-09-15",
      letzter_sync_am: "2026-07-29T06:00:00Z",
    });

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useSyncSettings(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.sync_interval_cron).toBe("*/30 * * * *");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/hooks/useSyncSettings.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the three hooks**

`frontend/src/api/hooks/useSyncSettings.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { SyncSettings } from "../types";

export function useSyncSettings() {
  return useQuery({
    queryKey: ["admin", "sync-settings"],
    queryFn: () => apiGet<SyncSettings>("admin/sync-settings"),
  });
}
```

`frontend/src/api/hooks/useUpdateSyncSettings.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { SyncSettings } from "../types";

export function useUpdateSyncSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sync_interval_cron: string) => apiPut<SyncSettings>("admin/sync-settings", { sync_interval_cron }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "sync-settings"] }),
  });
}
```

`frontend/src/api/hooks/useTriggerSyncNow.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPost } from "../client";

interface SyncNowResult {
  status: string;
  abgeschlossen_am: string;
}

export function useTriggerSyncNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<SyncNowResult>("admin/sync-now", {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "sync-settings"] }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/hooks/useSyncSettings.test.tsx`
Expected: PASS.

- [ ] **Step 5: Create the Admin layout (sub-nav + outlet)**

`frontend/src/pages/Admin/AdminLayout.module.css`:

```css
.subnav {
  display: flex;
  gap: 1rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #eee;
}

.subtab,
.subtabActive {
  text-decoration: none;
  color: inherit;
  padding-bottom: 0.25rem;
}

.subtabActive {
  border-bottom: 2px solid #1e40af;
  font-weight: 600;
}
```

`frontend/src/pages/Admin/AdminLayout.tsx`:

```tsx
import { Link, Outlet, useLocation } from "react-router-dom";
import styles from "./AdminLayout.module.css";

const TABS = [
  { path: "/admin/schwellwerte", label: "Schwellwert-Regeln" },
  { path: "/admin/massnahmen", label: "Maßnahmen-Katalog" },
  { path: "/admin/entschuldigungsstatus", label: "Entschuldigungsstatus" },
  { path: "/admin/sync", label: "Sync-Einstellungen" },
];

export function AdminLayout() {
  const location = useLocation();
  return (
    <div>
      <nav className={styles.subnav}>
        {TABS.map((tab) => (
          <Link
            key={tab.path}
            to={tab.path}
            className={location.pathname === tab.path ? styles.subtabActive : styles.subtab}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
```

- [ ] **Step 6: Create the Sync-Einstellungen page**

`frontend/src/pages/Admin/SyncSettings.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useSyncSettings } from "../../api/hooks/useSyncSettings";
import { useUpdateSyncSettings } from "../../api/hooks/useUpdateSyncSettings";
import { useTriggerSyncNow } from "../../api/hooks/useTriggerSyncNow";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function SyncSettings() {
  const { data, isLoading, isError } = useSyncSettings();
  const { mutate: updateSettings, isPending: isSaving, error: saveError } = useUpdateSyncSettings();
  const { mutate: triggerSync, isPending: isSyncing, isSuccess: syncSucceeded, error: syncError } = useTriggerSyncNow();
  const [cron, setCron] = useState("");

  useEffect(() => {
    if (data) {
      setCron(data.sync_interval_cron);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Sync-Einstellungen.</p>;
  }

  return (
    <section className={styles.section}>
      <h3>Sync-Einstellungen</h3>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          updateSettings(cron);
        }}
      >
        <label>
          Sync-Intervall (Cron-Ausdruck)
          <input aria-label="Sync-Intervall" type="text" value={cron} onChange={(event) => setCron(event.target.value)} required />
        </label>
        <button type="submit" disabled={isSaving}>
          Speichern
        </button>
        {saveError && <p className={styles.formError}>Fehler beim Speichern — Cron-Ausdruck prüfen.</p>}
      </form>
      <p>Schuljahresbeginn: {data.schuljahr_start_cache ?? "unbekannt (kein aktives Schuljahr in WebUntis)"}</p>
      <p>Letzter Sync: {data.letzter_sync_am ?? "noch nie"}</p>
      <button type="button" onClick={() => triggerSync()} disabled={isSyncing}>
        Sync jetzt ausführen
      </button>
      {syncSucceeded && <p>Sync erfolgreich ausgeführt.</p>}
      {syncError && <p className={styles.formError}>Sync fehlgeschlagen.</p>}
    </section>
  );
}
```

- [ ] **Step 7: Wire the Admin route tree into `App.tsx`**

In `frontend/src/App.tsx`, add imports and register the nested route:

```tsx
import { AdminLayout } from "./pages/Admin/AdminLayout";
import { SyncSettings } from "./pages/Admin/SyncSettings";
```

and inside `<Routes>`, nested under the existing `<Route element={<Layout />}>`:

```tsx
        <Route
          path="/admin"
          element={
            <RequireSchulleitung>
              <AdminLayout />
            </RequireSchulleitung>
          }
        >
          <Route path="sync" element={<SyncSettings />} />
        </Route>
```

(The other 3 tabs — `schwellwerte`, `massnahmen`, `entschuldigungsstatus` — are added as sibling `<Route>` entries in Tasks 7-9; leave them unregistered until their page components exist, matching the "no placeholder routes" spirit.)

- [ ] **Step 8: Write a component test for `SyncSettings`**

Create `frontend/src/pages/Admin/SyncSettings.test.tsx` (mirror the mocking style from `App.test.tsx`'s `useCreateMeasure` mocks):

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useSyncSettings } from "../../api/hooks/useSyncSettings";
import { useUpdateSyncSettings } from "../../api/hooks/useUpdateSyncSettings";
import { useTriggerSyncNow } from "../../api/hooks/useTriggerSyncNow";
import { SyncSettings } from "./SyncSettings";

vi.mock("../../api/hooks/useSyncSettings");
vi.mock("../../api/hooks/useUpdateSyncSettings");
vi.mock("../../api/hooks/useTriggerSyncNow");

describe("SyncSettings", () => {
  it("shows the current cron, schoolyear start, and last sync time", () => {
    vi.mocked(useSyncSettings).mockReturnValue({
      data: { sync_interval_cron: "*/30 * * * *", schuljahr_start_cache: "2025-09-15", letzter_sync_am: "2026-07-29T06:00:00Z" },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any);

    render(<SyncSettings />);
    expect(screen.getByDisplayValue("*/30 * * * *")).toBeInTheDocument();
    expect(screen.getByText(/2025-09-15/)).toBeInTheDocument();
  });

  it("submits the edited cron expression", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useSyncSettings).mockReturnValue({
      data: { sync_interval_cron: "*/30 * * * *", schuljahr_start_cache: null, letzter_sync_am: null },
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateSyncSettings).mockReturnValue({ mutate: updateMutate, isPending: false, error: null } as any);
    vi.mocked(useTriggerSyncNow).mockReturnValue({ mutate: vi.fn(), isPending: false, isSuccess: false, error: null } as any);

    render(<SyncSettings />);
    const input = screen.getByLabelText("Sync-Intervall");
    await userEvent.clear(input);
    await userEvent.type(input, "0 * * * *");
    await userEvent.click(screen.getByText("Speichern"));

    expect(updateMutate).toHaveBeenCalledWith("0 * * * *");
  });
});
```

Check whether `@testing-library/user-event` is already a dependency (`grep user-event frontend/package.json`) — if not, add it: `cd frontend && npm install --save-dev @testing-library/user-event` and check whether other tests in the repo already use it (if none do, this introduces the pattern; keep it, it's the standard RTL companion for simulating typing).

- [ ] **Step 9: Update `App.test.tsx` for the new route**

Add a test to `frontend/src/App.test.tsx`:

```tsx
it("renders the Admin sync-settings route for schulleitung", () => {
  setupMocks();
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [], rolle: "schulleitung" },
    isLoading: false,
    isError: false,
  } as any);
  vi.mocked(useSyncSettings).mockReturnValue({
    data: { sync_interval_cron: "*/30 * * * *", schuljahr_start_cache: null, letzter_sync_am: null },
    isLoading: false,
    isError: false,
  } as any);
  render(
    <MemoryRouter initialEntries={["/admin/sync"]}>
      <App />
    </MemoryRouter>,
  );
  expect(screen.getByText("Sync-Einstellungen")).toBeInTheDocument();
});
```

Add the needed `vi.mock("./api/hooks/useSyncSettings")` and `import { useSyncSettings } from "./api/hooks/useSyncSettings";` at the top of the file, alongside the existing mocks.

- [ ] **Step 10: Run all affected frontend tests**

Run: `cd frontend && npx vitest run src/api/hooks/useSyncSettings.test.tsx src/pages/Admin/SyncSettings.test.tsx src/App.test.tsx`
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/pages/Admin frontend/src/api/hooks/useSyncSettings.ts frontend/src/api/hooks/useUpdateSyncSettings.ts \
  frontend/src/api/hooks/useTriggerSyncNow.ts frontend/src/api/hooks/useSyncSettings.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: add Admin layout and Sync-Einstellungen page"
```

---

## Task 7: Frontend — Entschuldigungsstatus page (read-only + checkbox)

**Files:**
- Create: `frontend/src/pages/Admin/ExcuseStatuses.tsx`
- Create: `frontend/src/api/hooks/useExcuseStatuses.ts`
- Create: `frontend/src/api/hooks/useUpdateExcuseStatuses.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/api/hooks/useExcuseStatuses.test.tsx`, `frontend/src/pages/Admin/ExcuseStatuses.test.tsx`

**Interfaces:**
- Consumes: `ExcuseStatus` type (Task 5), `apiGet`/`apiPut`.
- Produces: none consumed elsewhere.

- [ ] **Step 1: Write the failing hook test**

`frontend/src/api/hooks/useExcuseStatuses.test.tsx` (same shape as Task 6 Step 1, adjusted for the endpoint/type):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useExcuseStatuses } from "./useExcuseStatuses";

describe("useExcuseStatuses", () => {
  it("fetches admin/excuse-statuses", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue([
      { id: 1, name: "entsch.", long_name: "entschuldigt", zaehlt_als_entschuldigt: true, aktiv: true },
    ]);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useExcuseStatuses(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe("entsch.");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/hooks/useExcuseStatuses.test.tsx`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the hooks**

`frontend/src/api/hooks/useExcuseStatuses.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { ExcuseStatus } from "../types";

export function useExcuseStatuses() {
  return useQuery({
    queryKey: ["admin", "excuse-statuses"],
    queryFn: () => apiGet<ExcuseStatus[]>("admin/excuse-statuses"),
  });
}
```

`frontend/src/api/hooks/useUpdateExcuseStatuses.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { ExcuseStatus } from "../types";

export function useUpdateExcuseStatuses() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (statuses: ExcuseStatus[]) => apiPut<ExcuseStatus[]>("admin/excuse-statuses", statuses),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "excuse-statuses"] }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/hooks/useExcuseStatuses.test.tsx`
Expected: PASS.

- [ ] **Step 5: Implement the page**

`frontend/src/pages/Admin/ExcuseStatuses.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useExcuseStatuses } from "../../api/hooks/useExcuseStatuses";
import { useUpdateExcuseStatuses } from "../../api/hooks/useUpdateExcuseStatuses";
import type { ExcuseStatus } from "../../api/types";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function ExcuseStatuses() {
  const { data, isLoading, isError } = useExcuseStatuses();
  const { mutate, isPending, error } = useUpdateExcuseStatuses();
  const [rows, setRows] = useState<ExcuseStatus[]>([]);

  useEffect(() => {
    if (data) {
      setRows(data);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Entschuldigungsstatus.</p>;
  }

  function toggle(id: number) {
    setRows((current) =>
      current.map((row) => (row.id === id ? { ...row, zaehlt_als_entschuldigt: !row.zaehlt_als_entschuldigt } : row)),
    );
  }

  return (
    <section className={styles.section}>
      <h3>Entschuldigungsstatus</h3>
      <p>
        Namen werden automatisch beim WebUntis-Sync übernommen und können hier nicht geändert werden — nur ob ein
        Status als entschuldigt zählt.
      </p>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Entschuldigt</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.name}</td>
              <td>
                <input
                  aria-label={`Entschuldigt: ${row.name}`}
                  type="checkbox"
                  checked={row.zaehlt_als_entschuldigt}
                  onChange={() => toggle(row.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => mutate(rows)} disabled={isPending}>
        Speichern
      </button>
      {error && <p className={styles.formError}>Fehler beim Speichern.</p>}
    </section>
  );
}
```

- [ ] **Step 6: Register the route**

In `frontend/src/App.tsx`, import `ExcuseStatuses` and add `<Route path="entschuldigungsstatus" element={<ExcuseStatuses />} />` as a sibling of the `sync` route inside the `/admin` route.

- [ ] **Step 7: Write the page test**

`frontend/src/pages/Admin/ExcuseStatuses.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useExcuseStatuses } from "../../api/hooks/useExcuseStatuses";
import { useUpdateExcuseStatuses } from "../../api/hooks/useUpdateExcuseStatuses";
import { ExcuseStatuses } from "./ExcuseStatuses";

vi.mock("../../api/hooks/useExcuseStatuses");
vi.mock("../../api/hooks/useUpdateExcuseStatuses");

describe("ExcuseStatuses", () => {
  it("renders each status with a checkbox, no name input", () => {
    vi.mocked(useExcuseStatuses).mockReturnValue({
      data: [{ id: 1, name: "nicht entsch.", long_name: null, zaehlt_als_entschuldigt: false, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateExcuseStatuses).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);

    render(<ExcuseStatuses />);
    expect(screen.getByText("nicht entsch.")).toBeInTheDocument();
    expect(screen.getByLabelText("Entschuldigt: nicht entsch.")).not.toBeChecked();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("toggles the checkbox and submits the full updated list", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useExcuseStatuses).mockReturnValue({
      data: [{ id: 1, name: "hybrid", long_name: null, zaehlt_als_entschuldigt: false, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateExcuseStatuses).mockReturnValue({ mutate: updateMutate, isPending: false, error: null } as any);

    render(<ExcuseStatuses />);
    await userEvent.click(screen.getByLabelText("Entschuldigt: hybrid"));
    await userEvent.click(screen.getByText("Speichern"));

    expect(updateMutate).toHaveBeenCalledWith([
      { id: 1, name: "hybrid", long_name: null, zaehlt_als_entschuldigt: true, aktiv: true },
    ]);
  });
});
```

- [ ] **Step 8: Run tests**

Run: `cd frontend && npx vitest run src/api/hooks/useExcuseStatuses.test.tsx src/pages/Admin/ExcuseStatuses.test.tsx`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/Admin/ExcuseStatuses.tsx frontend/src/pages/Admin/ExcuseStatuses.test.tsx \
  frontend/src/api/hooks/useExcuseStatuses.ts frontend/src/api/hooks/useUpdateExcuseStatuses.ts \
  frontend/src/api/hooks/useExcuseStatuses.test.tsx frontend/src/App.tsx
git commit -m "feat: add Entschuldigungsstatus admin page"
```

---

## Task 8: Frontend — Maßnahmen-Katalog page

**Files:**
- Create: `frontend/src/pages/Admin/MeasureTypes.tsx`
- Create: `frontend/src/api/hooks/useMeasureTypes.ts`
- Create: `frontend/src/api/hooks/useUpdateMeasureTypes.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/api/hooks/useMeasureTypes.test.tsx`, `frontend/src/pages/Admin/MeasureTypes.test.tsx`

**Interfaces:**
- Consumes: `MeasureType` type (Task 5, already without `betroffene_regel_ids` per Task 2's backend change).

- [ ] **Step 1: Write the failing hook test**

`frontend/src/api/hooks/useMeasureTypes.test.tsx` (same shape as Task 7 Step 1):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useMeasureTypes } from "./useMeasureTypes";

describe("useMeasureTypes", () => {
  it("fetches admin/measure-types", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue([
      { id: 1, name: "Nachsitzen", setzt_zaehler_zurueck: true, aktiv: true },
    ]);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useMeasureTypes(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].name).toBe("Nachsitzen");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/hooks/useMeasureTypes.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement the hooks**

`frontend/src/api/hooks/useMeasureTypes.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { MeasureType } from "../types";

export function useMeasureTypes() {
  return useQuery({
    queryKey: ["admin", "measure-types"],
    queryFn: () => apiGet<MeasureType[]>("admin/measure-types"),
  });
}
```

`frontend/src/api/hooks/useUpdateMeasureTypes.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { MeasureType } from "../types";

export function useUpdateMeasureTypes() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (types: MeasureType[]) => apiPut<MeasureType[]>("admin/measure-types", types),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "measure-types"] }),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/hooks/useMeasureTypes.test.tsx`
Expected: PASS.

- [ ] **Step 5: Implement the page (full CRUD: edit rows, add row, remove row)**

`frontend/src/pages/Admin/MeasureTypes.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMeasureTypes } from "../../api/hooks/useMeasureTypes";
import { useUpdateMeasureTypes } from "../../api/hooks/useUpdateMeasureTypes";
import type { MeasureType } from "../../api/types";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function MeasureTypes() {
  const { data, isLoading, isError } = useMeasureTypes();
  const { mutate, isPending, error } = useUpdateMeasureTypes();
  const [rows, setRows] = useState<MeasureType[]>([]);

  useEffect(() => {
    if (data) {
      setRows(data);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden des Maßnahmen-Katalogs.</p>;
  }

  function updateRow(index: number, patch: Partial<MeasureType>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRow(index: number) {
    setRows((current) => current.filter((_, i) => i !== index));
  }

  function addRow() {
    setRows((current) => [...current, { name: "", setzt_zaehler_zurueck: false, aktiv: true }]);
  }

  return (
    <section className={styles.section}>
      <h3>Maßnahmen-Katalog</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Setzt Zähler zurück</th>
            <th>Aktiv</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id ?? `neu-${index}`}>
              <td>
                <input
                  aria-label={`Name Zeile ${index + 1}`}
                  type="text"
                  value={row.name}
                  onChange={(event) => updateRow(index, { name: event.target.value })}
                />
              </td>
              <td>
                <input
                  aria-label={`Setzt Zähler zurück Zeile ${index + 1}`}
                  type="checkbox"
                  checked={row.setzt_zaehler_zurueck}
                  onChange={(event) => updateRow(index, { setzt_zaehler_zurueck: event.target.checked })}
                />
              </td>
              <td>
                <input
                  aria-label={`Aktiv Zeile ${index + 1}`}
                  type="checkbox"
                  checked={row.aktiv}
                  onChange={(event) => updateRow(index, { aktiv: event.target.checked })}
                />
              </td>
              <td>
                <button type="button" onClick={() => removeRow(index)}>
                  Entfernen
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={addRow}>
        Neuer Maßnahmen-Typ
      </button>
      <button type="button" onClick={() => mutate(rows)} disabled={isPending}>
        Speichern
      </button>
      {error && <p className={styles.formError}>Fehler beim Speichern — z.B. Name bereits vergeben.</p>}
    </section>
  );
}
```

- [ ] **Step 6: Register the route**

In `frontend/src/App.tsx`, import `MeasureTypes` and add `<Route path="massnahmen" element={<MeasureTypes />} />` inside the `/admin` route.

- [ ] **Step 7: Write the page test**

`frontend/src/pages/Admin/MeasureTypes.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useMeasureTypes } from "../../api/hooks/useMeasureTypes";
import { useUpdateMeasureTypes } from "../../api/hooks/useUpdateMeasureTypes";
import { MeasureTypes } from "./MeasureTypes";

vi.mock("../../api/hooks/useMeasureTypes");
vi.mock("../../api/hooks/useUpdateMeasureTypes");

describe("MeasureTypes", () => {
  it("renders existing types and adds a new row", async () => {
    vi.mocked(useMeasureTypes).mockReturnValue({
      data: [{ id: 1, name: "Nachsitzen", setzt_zaehler_zurueck: true, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateMeasureTypes).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);

    render(<MeasureTypes />);
    expect(screen.getByDisplayValue("Nachsitzen")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Neuer Maßnahmen-Typ"));
    expect(screen.getByLabelText("Name Zeile 2")).toBeInTheDocument();
  });

  it("submits the full edited list on Speichern", async () => {
    const updateMutate = vi.fn();
    vi.mocked(useMeasureTypes).mockReturnValue({
      data: [{ id: 1, name: "Gespräch", setzt_zaehler_zurueck: false, aktiv: true }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateMeasureTypes).mockReturnValue({ mutate: updateMutate, isPending: false, error: null } as any);

    render(<MeasureTypes />);
    await userEvent.click(screen.getByLabelText("Setzt Zähler zurück Zeile 1"));
    await userEvent.click(screen.getByText("Speichern"));

    expect(updateMutate).toHaveBeenCalledWith([
      { id: 1, name: "Gespräch", setzt_zaehler_zurueck: true, aktiv: true },
    ]);
  });
});
```

- [ ] **Step 8: Run tests**

Run: `cd frontend && npx vitest run src/api/hooks/useMeasureTypes.test.tsx src/pages/Admin/MeasureTypes.test.tsx`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/Admin/MeasureTypes.tsx frontend/src/pages/Admin/MeasureTypes.test.tsx \
  frontend/src/api/hooks/useMeasureTypes.ts frontend/src/api/hooks/useUpdateMeasureTypes.ts \
  frontend/src/api/hooks/useMeasureTypes.test.tsx frontend/src/App.tsx
git commit -m "feat: add Maßnahmen-Katalog admin page"
```

---

## Task 9: Frontend — Schwellwert-Regeln page (nested Stufen editor)

**Files:**
- Create: `frontend/src/pages/Admin/ThresholdRules.tsx`
- Create: `frontend/src/pages/Admin/ThresholdRules.module.css`
- Create: `frontend/src/api/hooks/useThresholdRules.ts`
- Create: `frontend/src/api/hooks/useUpdateThresholdRules.ts`
- Create: `frontend/src/api/hooks/useAbteilungen.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/api/hooks/useThresholdRules.test.tsx`, `frontend/src/pages/Admin/ThresholdRules.test.tsx`

**Interfaces:**
- Consumes: `ThresholdRule`/`SchwellwertStufe`/`Abteilung` types (Task 5), `GET /admin/abteilungen` (Task 4).

- [ ] **Step 1: Write the failing hook tests**

`frontend/src/api/hooks/useThresholdRules.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useThresholdRules } from "./useThresholdRules";

describe("useThresholdRules", () => {
  it("fetches admin/threshold-rules", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(client, "apiGet").mockResolvedValue([
      {
        id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null,
        stufen: [{ id: 1, stufe_nr: 1, einheit: "fehltage", schwellenwert: 4, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: ["klassenlehrkraft"] }],
      },
    ]);

    function wrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
    }

    const { result } = renderHook(() => useThresholdRules(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].stufen[0].schwellenwert).toBe(4);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/hooks/useThresholdRules.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement the hooks**

`frontend/src/api/hooks/useThresholdRules.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { ThresholdRule } from "../types";

export function useThresholdRules() {
  return useQuery({
    queryKey: ["admin", "threshold-rules"],
    queryFn: () => apiGet<ThresholdRule[]>("admin/threshold-rules"),
  });
}
```

`frontend/src/api/hooks/useUpdateThresholdRules.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiPut } from "../client";
import type { ThresholdRule } from "../types";

export function useUpdateThresholdRules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rules: ThresholdRule[]) => apiPut<ThresholdRule[]>("admin/threshold-rules", rules),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "threshold-rules"] }),
  });
}
```

`frontend/src/api/hooks/useAbteilungen.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { Abteilung } from "../types";

export function useAbteilungen() {
  return useQuery({
    queryKey: ["admin", "abteilungen"],
    queryFn: () => apiGet<Abteilung[]>("admin/abteilungen"),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/hooks/useThresholdRules.test.tsx`
Expected: PASS.

- [ ] **Step 5: Implement the page**

`frontend/src/pages/Admin/ThresholdRules.module.css`:

```css
.rule {
  border: 1px solid #eee;
  border-radius: 4px;
  padding: 0.75rem;
  margin-bottom: 1rem;
}

.stufenRow {
  display: flex;
  gap: 0.75rem;
  align-items: flex-end;
  flex-wrap: wrap;
  padding: 0.5rem 0;
  border-top: 1px solid #f5f5f5;
}

.stufenRow label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
}
```

`frontend/src/pages/Admin/ThresholdRules.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useAbteilungen } from "../../api/hooks/useAbteilungen";
import { useThresholdRules } from "../../api/hooks/useThresholdRules";
import { useUpdateThresholdRules } from "../../api/hooks/useUpdateThresholdRules";
import type { SchwellwertStufe, ThresholdRule } from "../../api/types";
import styles from "./ThresholdRules.module.css";
import sectionStyles from "../../components/StudentDetail/StudentDetail.module.css";

const ROLLEN = ["klassenlehrkraft", "bereichsleiter", "schulleitung"] as const;

function leereStufe(stufeNr: number): SchwellwertStufe {
  return { stufe_nr: stufeNr, einheit: "fehltage", schwellenwert: 1, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: [] };
}

function leereRegel(): ThresholdRule {
  return { typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [leereStufe(1)] };
}

export function ThresholdRules() {
  const { data, isLoading, isError } = useThresholdRules();
  const { data: abteilungen } = useAbteilungen();
  const { mutate, isPending, error } = useUpdateThresholdRules();
  const [rules, setRules] = useState<ThresholdRule[]>([]);

  useEffect(() => {
    if (data) {
      setRules(data);
    }
  }, [data]);

  if (isLoading) {
    return <p>Lädt…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Schwellwert-Regeln.</p>;
  }

  function updateRule(index: number, patch: Partial<ThresholdRule>) {
    setRules((current) => current.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  }

  function updateStufe(ruleIndex: number, stufeIndex: number, patch: Partial<SchwellwertStufe>) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : { ...rule, stufen: rule.stufen.map((stufe, j) => (j === stufeIndex ? { ...stufe, ...patch } : stufe)) },
      ),
    );
  }

  function toggleRolle(ruleIndex: number, stufeIndex: number, rolle: string) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex
          ? rule
          : {
              ...rule,
              stufen: rule.stufen.map((stufe, j) =>
                j !== stufeIndex
                  ? stufe
                  : {
                      ...stufe,
                      empfaenger_rollen: stufe.empfaenger_rollen.includes(rolle)
                        ? stufe.empfaenger_rollen.filter((r) => r !== rolle)
                        : [...stufe.empfaenger_rollen, rolle],
                    },
              ),
            },
      ),
    );
  }

  function addStufe(ruleIndex: number) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex ? rule : { ...rule, stufen: [...rule.stufen, leereStufe(rule.stufen.length + 1)] },
      ),
    );
  }

  function removeStufe(ruleIndex: number, stufeIndex: number) {
    setRules((current) =>
      current.map((rule, i) =>
        i !== ruleIndex ? rule : { ...rule, stufen: rule.stufen.filter((_, j) => j !== stufeIndex) },
      ),
    );
  }

  function removeRule(index: number) {
    setRules((current) => current.filter((_, i) => i !== index));
  }

  function addRule() {
    setRules((current) => [...current, leereRegel()]);
  }

  return (
    <section className={sectionStyles.section}>
      <h3>Schwellwert-Regeln</h3>
      {rules.map((rule, ruleIndex) => (
        <div className={styles.rule} key={rule.id ?? `neu-${ruleIndex}`}>
          <label>
            Typ
            <select
              aria-label={`Typ Regel ${ruleIndex + 1}`}
              value={rule.typ}
              onChange={(event) => updateRule(ruleIndex, { typ: event.target.value as ThresholdRule["typ"] })}
            >
              <option value="fehlzeiten">Fehlzeiten</option>
              <option value="klassenbuch">Klassenbuch</option>
            </select>
          </label>
          <label>
            Geltungsbereich
            <select
              aria-label={`Geltungsbereich Regel ${ruleIndex + 1}`}
              value={rule.geltungsbereich}
              onChange={(event) =>
                updateRule(ruleIndex, {
                  geltungsbereich: event.target.value as ThresholdRule["geltungsbereich"],
                  abteilung_id: event.target.value === "schulweit" ? null : rule.abteilung_id,
                })
              }
            >
              <option value="schulweit">Schulweit</option>
              <option value="abteilung">Abteilung</option>
            </select>
          </label>
          {rule.geltungsbereich === "abteilung" && (
            <label>
              Abteilung
              <select
                aria-label={`Abteilung Regel ${ruleIndex + 1}`}
                value={rule.abteilung_id ?? ""}
                onChange={(event) => updateRule(ruleIndex, { abteilung_id: Number(event.target.value) })}
              >
                <option value="">Bitte wählen</option>
                {(abteilungen ?? []).map((abteilung) => (
                  <option key={abteilung.id} value={abteilung.id}>
                    {abteilung.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {rule.stufen.map((stufe, stufeIndex) => (
            <div className={styles.stufenRow} key={stufe.id ?? `neu-${stufeIndex}`}>
              <span>Stufe {stufe.stufe_nr}</span>
              {rule.typ === "fehlzeiten" && (
                <label>
                  Einheit
                  <select
                    aria-label={`Einheit Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                    value={stufe.einheit ?? "fehltage"}
                    onChange={(event) =>
                      updateStufe(ruleIndex, stufeIndex, { einheit: event.target.value as SchwellwertStufe["einheit"] })
                    }
                  >
                    <option value="fehltage">Fehltage</option>
                    <option value="fehlstunden">Fehlstunden</option>
                  </select>
                </label>
              )}
              <label>
                Schwellenwert
                <input
                  aria-label={`Schwellenwert Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                  type="number"
                  min={1}
                  value={stufe.schwellenwert}
                  onChange={(event) => updateStufe(ruleIndex, stufeIndex, { schwellenwert: Number(event.target.value) })}
                />
              </label>
              {rule.typ === "fehlzeiten" && (
                <label>
                  Filter
                  <select
                    aria-label={`Filter Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                    value={stufe.fehlzeiten_filter ?? "nur_unentschuldigt"}
                    onChange={(event) =>
                      updateStufe(ruleIndex, stufeIndex, {
                        fehlzeiten_filter: event.target.value as SchwellwertStufe["fehlzeiten_filter"],
                      })
                    }
                  >
                    <option value="nur_unentschuldigt">Nur unentschuldigt</option>
                    <option value="alle">Alle</option>
                  </select>
                </label>
              )}
              <fieldset>
                <legend>Empfänger</legend>
                {ROLLEN.map((rolle) => (
                  <label key={rolle}>
                    <input
                      type="checkbox"
                      aria-label={`${rolle} Regel ${ruleIndex + 1} Stufe ${stufeIndex + 1}`}
                      checked={stufe.empfaenger_rollen.includes(rolle)}
                      onChange={() => toggleRolle(ruleIndex, stufeIndex, rolle)}
                    />{" "}
                    {rolle}
                  </label>
                ))}
              </fieldset>
              <button type="button" onClick={() => removeStufe(ruleIndex, stufeIndex)}>
                Stufe entfernen
              </button>
            </div>
          ))}
          <button type="button" onClick={() => addStufe(ruleIndex)}>
            Stufe hinzufügen
          </button>
          <button type="button" onClick={() => removeRule(ruleIndex)}>
            Regel entfernen
          </button>
        </div>
      ))}
      <button type="button" onClick={addRule}>
        Neue Regel
      </button>
      <button type="button" onClick={() => mutate(rules)} disabled={isPending}>
        Speichern
      </button>
      {error && <p className={sectionStyles.formError}>Fehler beim Speichern — Regeln prüfen (z.B. doppelte Abteilungs-Regel).</p>}
    </section>
  );
}
```

- [ ] **Step 6: Register the route**

In `frontend/src/App.tsx`, import `ThresholdRules` and add `<Route path="schwellwerte" element={<ThresholdRules />} />` inside the `/admin` route.

- [ ] **Step 7: Write the page test**

`frontend/src/pages/Admin/ThresholdRules.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useAbteilungen } from "../../api/hooks/useAbteilungen";
import { useThresholdRules } from "../../api/hooks/useThresholdRules";
import { useUpdateThresholdRules } from "../../api/hooks/useUpdateThresholdRules";
import { ThresholdRules } from "./ThresholdRules";

vi.mock("../../api/hooks/useThresholdRules");
vi.mock("../../api/hooks/useUpdateThresholdRules");
vi.mock("../../api/hooks/useAbteilungen");

describe("ThresholdRules", () => {
  it("renders an existing schulweite Regel with its Stufen", () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [
        {
          id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null,
          stufen: [{ id: 1, stufe_nr: 1, einheit: "fehltage", schwellenwert: 4, fehlzeiten_filter: "nur_unentschuldigt", empfaenger_rollen: ["klassenlehrkraft"] }],
        },
      ],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);
    expect(screen.getByDisplayValue("4")).toBeInTheDocument();
    expect(screen.getByLabelText("klassenlehrkraft Regel 1 Stufe 1")).toBeChecked();
  });

  it("shows the Abteilung dropdown only when geltungsbereich is abteilung", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({
      data: [{ id: 5, name: "Kaufmännisch" }],
      isLoading: false,
      isError: false,
    } as any);

    render(<ThresholdRules />);
    expect(screen.queryByLabelText("Abteilung Regel 1")).not.toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Geltungsbereich Regel 1"), "abteilung");
    expect(screen.getByLabelText("Abteilung Regel 1")).toBeInTheDocument();
    expect(screen.getByText("Kaufmännisch")).toBeInTheDocument();
  });

  it("adds and removes a Stufe", async () => {
    vi.mocked(useThresholdRules).mockReturnValue({
      data: [{ id: 1, typ: "fehlzeiten", geltungsbereich: "schulweit", abteilung_id: null, stufen: [] }],
      isLoading: false,
      isError: false,
    } as any);
    vi.mocked(useUpdateThresholdRules).mockReturnValue({ mutate: vi.fn(), isPending: false, error: null } as any);
    vi.mocked(useAbteilungen).mockReturnValue({ data: [], isLoading: false, isError: false } as any);

    render(<ThresholdRules />);
    await userEvent.click(screen.getByText("Stufe hinzufügen"));
    expect(screen.getByText("Stufe 1")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Stufe entfernen"));
    expect(screen.queryByText("Stufe 1")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Run tests**

Run: `cd frontend && npx vitest run src/api/hooks/useThresholdRules.test.tsx src/pages/Admin/ThresholdRules.test.tsx`
Expected: all PASS.

- [ ] **Step 9: Run the complete frontend test suite**

Run: `cd frontend && npm test`
Expected: all PASS (catches any regression across all 9 tasks, e.g. a stale `NavOptions` mock missing `rolle` in a test file not touched by this plan).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/Admin/ThresholdRules.tsx frontend/src/pages/Admin/ThresholdRules.module.css frontend/src/pages/Admin/ThresholdRules.test.tsx \
  frontend/src/api/hooks/useThresholdRules.ts frontend/src/api/hooks/useUpdateThresholdRules.ts frontend/src/api/hooks/useAbteilungen.ts \
  frontend/src/api/hooks/useThresholdRules.test.tsx frontend/src/App.tsx
git commit -m "feat: add Schwellwert-Regeln admin page with nested Stufen editor"
```

---

## Task 10: Documentation

**Files:**
- Modify: `ROADMAP.md`
- Modify: `SPECS.md` (§4, per the design doc's note on the `massnahmen_typ_regel` removal)
- Modify: `docs/deployment.md` if it references `betroffene_regel_ids`/measure-type-to-rule linkage (check with `grep -rn "betroffene_regel\|massnahmen_typ_regel" docs/`)

- [ ] **Step 1: Update SPECS.md §4**

Find the sentence in SPECS.md §4 describing the measure catalog's "betroffene Eskalationsstufe/Regel(n)" field (`SPECS.md:48`, per the design doc). Replace it to describe the new unconditional-reset behavior: a zurücksetzender Maßnahmen-Typ setzt bei Erfassung beide Zählerstände (Fehlzeiten und Klassenbuch) des Schülers zurück, ohne Regel-Verknüpfung.

- [ ] **Step 2: Update ROADMAP.md**

Move the "Admin-Bereich, gebündelt" entry from "Geplant" to "Abgeschlossen" as **Plan 12**, following the exact table-row format of the existing "Abgeschlossen" entries (`| **Plan 12** — [...](docs/superpowers/plans/2026-07-30-admin-bereich.md) | ... | ... |`), summarizing what it covers and what's bewusst nicht enthalten (nothing deferred — this plan closes both original roadmap items).

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md SPECS.md docs/deployment.md
git commit -m "docs: sync SPECS.md and ROADMAP.md with the admin-bereich plan"
```
