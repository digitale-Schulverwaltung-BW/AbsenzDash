# Backend REST-API fürs WP-Plugin — Kern-Endpunkte — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die fünf Kern-Endpunkte aus TECH-SPEC.md §3 (`GET /students`, `GET /students/{id}`, `POST /students/{id}/measures`, `POST/DELETE /students/{id}/exemptions`) als scope-geprüfte FastAPI-Routen implementieren.

**Architecture:** Neuer Router `app/api/routes/students.py`, dünn gehalten — die eigentliche Query-/Business-Logik liegt in `app/services/student_query.py` (Lesezugriffe) sowie `app/services/massnahme_service.py`/`app/services/ausnahme_service.py` (Schreibzugriffe). Ein neuer Scope-Resolver in `app/api/deps.py` (`resolve_scope`, `get_scoped_schueler`) baut auf der bestehenden WP-Proxy-Auth-Dependency (Plan 1) auf und wird von allen fünf Endpunkten als gemeinsames Autorisierungs-Gate genutzt.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async, PostgreSQL/asyncpg), Pydantic v2, pytest + pytest-asyncio + httpx (`ASGITransport`).

## Global Constraints

- Out-of-scope oder nicht existente Ressourcen (Schüler, Ausnahme) liefern immer **404**, nie 403 — ein Aufrufer soll Existenz außerhalb seines Scopes nicht von echter Nicht-Existenz unterscheiden können.
- Jede schreibende Service-Funktion (`record_massnahme`, `create_ausnahme`, `revoke_ausnahme`) schreibt einen `audit_log`-Eintrag (SPECS.md §4).
- Enum-Werte konsistent mit den bestehenden DB-Modellen: `typ`/`kategorie` sind immer `"fehlzeiten"` oder `"klassenbuch"`.
- Tests laufen mit `docker compose -f backend/docker-compose.yml run --rm backend pytest ...`. Voraussetzung (einmalig, falls noch nicht laufend): `docker compose -f backend/docker-compose.yml up -d postgres`. Alle Befehle unten werden aus dem Repo-Root ausgeführt.
- Referenz für alle Feldnamen/Endpunkte: [TECH-SPEC.md](../../../TECH-SPEC.md) §3; [SPECS.md](../../../SPECS.md) §3/4/7; Design-Dokument [2026-07-27-rest-api-wordpress-kern-design.md](../specs/2026-07-27-rest-api-wordpress-kern-design.md).

---

## Task 1: Scope-Resolver & scope-geprüfte Schüler-Dependency

**Files:**
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_api_deps_scope.py`

**Interfaces:**
- Produces: `async def resolve_scope(db: AsyncSession, nutzer: Nutzer) -> set[int] | None` — `None` = alle Klassen (schulleitung), sonst Menge sichtbarer `klasse_id`s.
- Produces: `async def get_scoped_schueler(schueler_id: int, nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)], db: Annotated[AsyncSession, Depends(get_db)]) -> Schueler` — FastAPI-Dependency, 404 bei nicht existent oder außerhalb des Scopes.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_deps_scope.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_scoped_schueler, resolve_scope
from app.core.config import settings
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler

test_app = FastAPI()


@test_app.get("/scoped/{schueler_id}")
async def scoped(schueler: Schueler = Depends(get_scoped_schueler)):
    return {"id": schueler.id}


HEADERS_BASE = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "klassenlehrkraft",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_resolve_scope_returns_none_for_schulleitung(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.flush()

    assert await resolve_scope(db_session, nutzer) is None


@pytest.mark.asyncio
async def test_resolve_scope_returns_assigned_klassen_for_klassenlehrkraft(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    scope = await resolve_scope(db_session, nutzer)
    assert scope == {klasse_a.id}


@pytest.mark.asyncio
async def test_resolve_scope_returns_no_klassen_for_klassenlehrkraft_without_assignment(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.commit()

    assert await resolve_scope(db_session, nutzer) == set()


@pytest.mark.asyncio
async def test_resolve_scope_returns_bereich_klassen_for_bereichsleiter(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    scope = await resolve_scope(db_session, nutzer)
    assert scope == {klasse_a.id}


@pytest.mark.asyncio
async def test_get_scoped_schueler_returns_student_in_scope(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    nutzer_row = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer_row)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer_row.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/scoped/{schueler.id}", headers=HEADERS_BASE)
    assert response.status_code == 200
    assert response.json() == {"id": schueler.id}


@pytest.mark.asyncio
async def test_get_scoped_schueler_404s_for_student_outside_scope(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    db_session.add(schueler)
    await db_session.flush()
    nutzer_row = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer_row)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer_row.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/scoped/{schueler.id}", headers=HEADERS_BASE)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_scoped_schueler_404s_for_unknown_id(db_session):
    nutzer_row = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer_row)
    await db_session.commit()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scoped/999999", headers=HEADERS_BASE)
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_deps_scope.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_scoped_schueler' from 'app.api.deps'` (or `resolve_scope`).

- [ ] **Step 3: Implement `resolve_scope` and `get_scoped_schueler`**

In `backend/app/api/deps.py`, add these imports near the top (after the existing `app.models.nutzer` import):

```python
from app.models.bereich import bereich_klasse
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
```

Append at the end of the file:

```python
async def resolve_scope(db: AsyncSession, nutzer: Nutzer) -> set[int] | None:
    """Ermittelt die fuer den Nutzer sichtbaren klasse_id's.

    None bedeutet "alle Klassen" (schulleitung), inklusive Schueler ohne
    Klassenzuordnung (klasse_id IS NULL fuer frisch importierte Schueler,
    siehe SPECS.md Abschnitt 4).
    """
    if nutzer.rolle == "schulleitung":
        return None
    if nutzer.rolle == "bereichsleiter":
        result = await db.execute(
            select(bereich_klasse.c.klasse_id)
            .join(nutzer_bereich, nutzer_bereich.c.bereich_id == bereich_klasse.c.bereich_id)
            .where(nutzer_bereich.c.nutzer_id == nutzer.id)
        )
        return set(result.scalars().all())
    result = await db.execute(select(NutzerKlasse.klasse_id).where(NutzerKlasse.nutzer_id == nutzer.id))
    return set(result.scalars().all())


async def get_scoped_schueler(
    schueler_id: int,
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Schueler:
    """Laedt einen Schueler und prueft, dass er im Scope des Nutzers liegt.

    Ausserhalb des Scopes oder nicht existent: 404 in beiden Faellen (nicht
    403), damit ein Aufrufer nicht unterscheiden kann, ob eine ID nicht
    existiert oder ihm nur nicht zugaenglich ist.
    """
    schueler = (await db.execute(select(Schueler).where(Schueler.id == schueler_id))).scalar_one_or_none()
    scope = await resolve_scope(db, nutzer)
    if schueler is None or (scope is not None and schueler.klasse_id not in scope):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return schueler
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_deps_scope.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps.py backend/tests/test_api_deps_scope.py
git commit -m "feat: add role-based scope resolver and scoped-student dependency"
```

---

## Task 2: Audit-Log beim Erfassen einer Maßnahme

**Files:**
- Modify: `backend/app/services/massnahme_service.py`
- Modify: `backend/tests/test_massnahme_service.py`

**Interfaces:**
- Consumes: nichts Neues (bestehende Signatur von `record_massnahme` bleibt unverändert).
- Produces: `record_massnahme(...)` schreibt jetzt zusätzlich einen `AuditLog`-Eintrag (`aktion="massnahme_erfasst"`, `resource_typ="massnahme"`, `resource_id=str(massnahme.id)`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_massnahme_service.py` (add `from app.models.audit_log import AuditLog` to the imports at the top of the file):

```python
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

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_massnahme_service.py::test_record_massnahme_writes_audit_log_entry -v`
Expected: FAIL — `entries` is empty (`len(entries) == 0`).

- [ ] **Step 3: Implement the audit-log write**

In `backend/app/services/massnahme_service.py`, add the import:

```python
from app.models.audit_log import AuditLog
```

Change the start of `record_massnahme` from:

```python
    massnahme = Massnahme(
        schueler_id=schueler_id,
        massnahmen_typ_id=massnahmen_typ_id,
        datum=datum,
        notiz=notiz,
        erfasst_von_nutzer_id=erfasst_von_nutzer_id,
    )
    db.add(massnahme)

    typ_row = (await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == massnahmen_typ_id))).scalar_one()
```

to:

```python
    massnahme = Massnahme(
        schueler_id=schueler_id,
        massnahmen_typ_id=massnahmen_typ_id,
        datum=datum,
        notiz=notiz,
        erfasst_von_nutzer_id=erfasst_von_nutzer_id,
    )
    db.add(massnahme)
    await db.flush()

    db.add(
        AuditLog(
            user_id=erfasst_von_nutzer_id,
            aktion="massnahme_erfasst",
            resource_typ="massnahme",
            resource_id=str(massnahme.id),
            details={"schueler_id": schueler_id, "massnahmen_typ_id": massnahmen_typ_id},
        )
    )

    typ_row = (await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == massnahmen_typ_id))).scalar_one()
```

(the rest of the function is unchanged)

- [ ] **Step 4: Run all massnahme_service tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_massnahme_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/massnahme_service.py backend/tests/test_massnahme_service.py
git commit -m "feat: write audit_log entry when recording a massnahme"
```

---

## Task 3: `ausnahme_service` (Ausnahme erstellen/aufheben)

**Files:**
- Create: `backend/app/services/ausnahme_service.py`
- Test: `backend/tests/test_ausnahme_service.py`

**Interfaces:**
- Produces: `async def create_ausnahme(db, schueler_id: int, kategorie: str, grund: str, gueltig_bis: date | None, nutzer_id: int) -> Ausnahme`
- Produces: `async def revoke_ausnahme(db, ausnahme: Ausnahme, nutzer_id: int) -> None` — setzt `aktiv=False`; der Aufrufer muss vorher geprüft haben, dass `ausnahme` existiert, zum richtigen Schüler gehört und aktuell aktiv ist (das übernimmt die Route in Task 8).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ausnahme_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_ausnahme_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ausnahme_service'`

- [ ] **Step 3: Implement `ausnahme_service.py`**

Create `backend/app/services/ausnahme_service.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.ausnahme import Ausnahme


async def create_ausnahme(
    db: AsyncSession,
    schueler_id: int,
    kategorie: str,
    grund: str,
    gueltig_bis: date | None,
    nutzer_id: int,
) -> Ausnahme:
    ausnahme = Ausnahme(
        schueler_id=schueler_id,
        kategorie=kategorie,
        grund=grund,
        gueltig_bis=gueltig_bis,
        aktiv=True,
    )
    db.add(ausnahme)
    await db.flush()

    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="ausnahme_erstellt",
            resource_typ="ausnahme",
            resource_id=str(ausnahme.id),
            details={"schueler_id": schueler_id, "kategorie": kategorie},
        )
    )
    await db.commit()
    return ausnahme


async def revoke_ausnahme(db: AsyncSession, ausnahme: Ausnahme, nutzer_id: int) -> None:
    """Setzt eine Ausnahme auf aktiv=False. Der Aufrufer ist dafuer verantwortlich, dass
    `ausnahme` bereits als existent, zum richtigen Schueler gehoerig und aktiv geprueft wurde."""
    ausnahme.aktiv = False
    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="ausnahme_aufgehoben",
            resource_typ="ausnahme",
            resource_id=str(ausnahme.id),
            details={"schueler_id": ausnahme.schueler_id, "kategorie": ausnahme.kategorie},
        )
    )
    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_ausnahme_service.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ausnahme_service.py backend/tests/test_ausnahme_service.py
git commit -m "feat: add ausnahme_service (create/revoke exemptions with audit log)"
```

---

## Task 4: `student_query` Lese-Bausteine (Filter, Pagination, Batch-Lookups)

**Files:**
- Create: `backend/app/services/student_query.py`
- Test: `backend/tests/test_student_query.py`

**Interfaces:**
- Produces: `async def list_students(db, scope: set[int] | None, klasse_id: int | None = None, bereich_id: int | None = None, typ: str | None = None, min_stufe: int | None = None, nur_auffaellige: bool = False, limit: int = 50, offset: int = 0) -> tuple[list[Schueler], int]`
- Produces: `async def load_klasse_map(db, klasse_ids: list[int]) -> dict[int, Klasse]`
- Produces: `async def load_zaehlerstand_map(db, schueler_ids: list[int]) -> dict[int, dict[str, dict]]` — pro Schüler `{"fehlzeiten": {"aktueller_stand": int, "erreichte_stufe_nr": int|None}, "klassenbuch": {...}}`, fehlende Typen mit `{"aktueller_stand": 0, "erreichte_stufe_nr": None}` synthetisiert.
- Produces: `async def load_letzte_benachrichtigung_map(db, schueler_ids: list[int]) -> dict[int, Benachrichtigung]`
- Produces: `async def load_ohne_massnahme_map(db, schueler_ids: list[int], letzte_benachrichtigung: dict[int, Benachrichtigung]) -> dict[int, bool]`
- Produces: `async def load_overview_extras(db, schueler_ids: list[int]) -> dict[int, dict]` — pro Schüler `{"zaehlerstand": ..., "letzte_benachrichtigung": Benachrichtigung|None, "ohne_massnahme_seit_benachrichtigung": bool}` (bündelt die drei Funktionen oben).
- Produces: `async def load_student_detail(db, schueler_id: int) -> dict` — `{"fehlzeiten": list[Fehlzeit], "klassenbuch": list[KlassenbuchEintrag], "massnahmen": list[tuple[Massnahme, str, str]], "ausnahmen": list[Ausnahme], "benachrichtigungen": list[Benachrichtigung], "zaehlerstand": dict}`. `massnahmen` ist eine Liste von `(Massnahme, massnahmen_typ_name, erfasst_von_name)`-Tupeln.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_student_query.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.bereich import Bereich, bereich_klasse
from app.models.benachrichtigung import Benachrichtigung
from app.models.klasse import Klasse
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.services import student_query


@pytest.mark.asyncio
async def test_list_students_scopes_by_klasse_ids(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope={klasse_a.id})
    assert total == 1
    assert [s.id for s in items] == [schueler_a.id]


@pytest.mark.asyncio
async def test_list_students_returns_empty_for_empty_scope(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=set())
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_students_filters_by_bereich_id(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A", klasse_id=klasse_a.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B", klasse_id=klasse_b.id)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, bereich_id=bereich.id)
    assert total == 1
    assert [s.id for s in items] == [schueler_a.id]


@pytest.mark.asyncio
async def test_list_students_filters_by_min_stufe_and_typ(db_session):
    schueler_hoch = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    schueler_niedrig = Schueler(externe_id="ext-2", vorname="B", nachname="B")
    db_session.add_all([schueler_hoch, schueler_niedrig])
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerZaehlerstand(schueler_id=schueler_hoch.id, typ="fehlzeiten", aktueller_stand=8, erreichte_stufe_nr=2),
            SchuelerZaehlerstand(schueler_id=schueler_niedrig.id, typ="fehlzeiten", aktueller_stand=2, erreichte_stufe_nr=1),
        ]
    )
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, typ="fehlzeiten", min_stufe=2)
    assert total == 1
    assert [s.id for s in items] == [schueler_hoch.id]


@pytest.mark.asyncio
async def test_list_students_nur_auffaellige_excludes_students_without_reached_stufe(db_session):
    schueler_auffaellig = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    schueler_unauffaellig = Schueler(externe_id="ext-2", vorname="B", nachname="B")
    db_session.add_all([schueler_auffaellig, schueler_unauffaellig])
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerZaehlerstand(schueler_id=schueler_auffaellig.id, typ="klassenbuch", aktueller_stand=5, erreichte_stufe_nr=1),
            SchuelerZaehlerstand(schueler_id=schueler_unauffaellig.id, typ="klassenbuch", aktueller_stand=1, erreichte_stufe_nr=None),
        ]
    )
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, nur_auffaellige=True)
    assert total == 1
    assert [s.id for s in items] == [schueler_auffaellig.id]


@pytest.mark.asyncio
async def test_list_students_pagination(db_session):
    schueler_list = [
        Schueler(externe_id=f"ext-{i}", vorname="A", nachname=f"{i:02d}") for i in range(5)
    ]
    db_session.add_all(schueler_list)
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, limit=2, offset=1)
    assert total == 5
    assert len(items) == 2
    assert [s.nachname for s in items] == ["01", "02"]


@pytest.mark.asyncio
async def test_load_zaehlerstand_map_synthesizes_default_for_missing_typ(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", aktueller_stand=3, erreichte_stufe_nr=1))
    await db_session.commit()

    result = await student_query.load_zaehlerstand_map(db_session, [schueler.id])
    assert result[schueler.id]["fehlzeiten"] == {"aktueller_stand": 3, "erreichte_stufe_nr": 1}
    assert result[schueler.id]["klassenbuch"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}


@pytest.mark.asyncio
async def test_load_letzte_benachrichtigung_map_returns_latest_per_schueler(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    aelter = Benachrichtigung(
        schueler_id=schueler.id,
        stufe_nr=1,
        gesendet_am=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        empfaenger=[],
        status="gesendet",
    )
    neuer = Benachrichtigung(
        schueler_id=schueler.id,
        stufe_nr=2,
        gesendet_am=datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc),
        empfaenger=[],
        status="gesendet",
    )
    db_session.add_all([aelter, neuer])
    await db_session.commit()

    result = await student_query.load_letzte_benachrichtigung_map(db_session, [schueler.id])
    assert result[schueler.id].stufe_nr == 2


@pytest.mark.asyncio
async def test_load_ohne_massnahme_map_flags_missing_followup(db_session):
    schueler_ohne = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    schueler_mit = Schueler(externe_id="ext-2", vorname="B", nachname="B")
    db_session.add_all([schueler_ohne, schueler_mit])
    await db_session.flush()
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([typ, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler_mit.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 5),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    benachrichtigung_zeitpunkt = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    letzte_benachrichtigung = {
        schueler_ohne.id: Benachrichtigung(
            schueler_id=schueler_ohne.id, stufe_nr=1, gesendet_am=benachrichtigung_zeitpunkt, empfaenger=[], status="gesendet"
        ),
        schueler_mit.id: Benachrichtigung(
            schueler_id=schueler_mit.id, stufe_nr=1, gesendet_am=benachrichtigung_zeitpunkt, empfaenger=[], status="gesendet"
        ),
    }

    result = await student_query.load_ohne_massnahme_map(
        db_session, [schueler_ohne.id, schueler_mit.id], letzte_benachrichtigung
    )
    assert result[schueler_ohne.id] is True
    assert result[schueler_mit.id] is False


@pytest.mark.asyncio
async def test_load_student_detail_aggregates_all_sublists(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer A", rolle="klassenlehrkraft")
    db_session.add_all([typ, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 5),
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)
    assert detail["fehlzeiten"] == []
    assert detail["klassenbuch"] == []
    assert detail["ausnahmen"] == []
    assert detail["benachrichtigungen"] == []
    assert len(detail["massnahmen"]) == 1
    massnahme, typ_name, nutzer_name = detail["massnahmen"][0]
    assert typ_name == "Gespräch"
    assert nutzer_name == "Lehrer A"
    assert detail["zaehlerstand"]["fehlzeiten"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_student_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.student_query'`

- [ ] **Step 3: Implement `student_query.py`**

Create `backend/app/services/student_query.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ausnahme import Ausnahme
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import bereich_klasse
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand

ZAEHLERSTAND_TYPEN = ("fehlzeiten", "klassenbuch")


async def list_students(
    db: AsyncSession,
    scope: set[int] | None,
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: str | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Schueler], int]:
    """Liefert die fuer den Scope sichtbaren Schueler (gefiltert, paginiert) sowie die
    Gesamtzahl (nach Filtern, vor Pagination)."""
    if scope is not None and not scope:
        return [], 0

    conditions = []
    if scope is not None:
        conditions.append(Schueler.klasse_id.in_(scope))
    if klasse_id is not None:
        conditions.append(Schueler.klasse_id == klasse_id)
    if bereich_id is not None:
        bereich_klassen = select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_id)
        conditions.append(Schueler.klasse_id.in_(bereich_klassen))

    if min_stufe is not None or nur_auffaellige:
        typen = [typ] if typ is not None else list(ZAEHLERSTAND_TYPEN)
        zaehlerstand_conditions = [SchuelerZaehlerstand.typ.in_(typen)]
        if min_stufe is not None:
            zaehlerstand_conditions.append(SchuelerZaehlerstand.erreichte_stufe_nr >= min_stufe)
        else:
            zaehlerstand_conditions.append(SchuelerZaehlerstand.erreichte_stufe_nr.is_not(None))
        matching_ids = select(SchuelerZaehlerstand.schueler_id).where(*zaehlerstand_conditions)
        conditions.append(Schueler.id.in_(matching_ids))

    count_query = select(func.count()).select_from(Schueler)
    query = select(Schueler)
    for condition in conditions:
        count_query = count_query.where(condition)
        query = query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
    result = await db.execute(query.order_by(Schueler.nachname, Schueler.vorname).offset(offset).limit(limit))
    return list(result.scalars().all()), total


async def load_klasse_map(db: AsyncSession, klasse_ids: list[int]) -> dict[int, Klasse]:
    if not klasse_ids:
        return {}
    result = await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)))
    return {klasse.id: klasse for klasse in result.scalars().all()}


async def load_zaehlerstand_map(db: AsyncSession, schueler_ids: list[int]) -> dict[int, dict[str, dict[str, Any]]]:
    """Pro schueler_id ein dict {typ: {aktueller_stand, erreichte_stufe_nr}}, mit
    {aktueller_stand: 0, erreichte_stufe_nr: None} synthetisiert fuer fehlende Typen."""
    result: dict[int, dict[str, dict[str, Any]]] = {
        schueler_id: {typ: {"aktueller_stand": 0, "erreichte_stufe_nr": None} for typ in ZAEHLERSTAND_TYPEN}
        for schueler_id in schueler_ids
    }
    if not schueler_ids:
        return result

    rows = (
        await db.execute(select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id.in_(schueler_ids)))
    ).scalars().all()
    for row in rows:
        result[row.schueler_id][row.typ] = {
            "aktueller_stand": row.aktueller_stand,
            "erreichte_stufe_nr": row.erreichte_stufe_nr,
        }
    return result


async def load_letzte_benachrichtigung_map(db: AsyncSession, schueler_ids: list[int]) -> dict[int, Benachrichtigung]:
    """Pro schueler_id die zeitlich juengste Benachrichtigung (falls vorhanden)."""
    if not schueler_ids:
        return {}
    result = await db.execute(
        select(Benachrichtigung)
        .where(Benachrichtigung.schueler_id.in_(schueler_ids))
        .order_by(Benachrichtigung.schueler_id, Benachrichtigung.gesendet_am.desc())
    )
    letzte: dict[int, Benachrichtigung] = {}
    for row in result.scalars().all():
        letzte.setdefault(row.schueler_id, row)
    return letzte


async def load_ohne_massnahme_map(
    db: AsyncSession, schueler_ids: list[int], letzte_benachrichtigung: dict[int, Benachrichtigung]
) -> dict[int, bool]:
    """True, wenn eine letzte Benachrichtigung existiert und seitdem keine Massnahme erfasst wurde."""
    if not schueler_ids:
        return {}
    result = await db.execute(
        select(Massnahme.schueler_id, func.max(Massnahme.datum))
        .where(Massnahme.schueler_id.in_(schueler_ids))
        .group_by(Massnahme.schueler_id)
    )
    letzte_massnahme_datum: dict[int, date] = dict(result.all())

    ohne_massnahme: dict[int, bool] = {}
    for schueler_id in schueler_ids:
        benachrichtigung = letzte_benachrichtigung.get(schueler_id)
        if benachrichtigung is None:
            ohne_massnahme[schueler_id] = False
            continue
        massnahme_datum = letzte_massnahme_datum.get(schueler_id)
        ohne_massnahme[schueler_id] = (
            massnahme_datum is None or massnahme_datum < benachrichtigung.gesendet_am.date()
        )
    return ohne_massnahme


async def load_overview_extras(db: AsyncSession, schueler_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Buendelt die Batch-Queries oben zu einem dict pro schueler_id fuer die Uebersicht."""
    zaehlerstand_map = await load_zaehlerstand_map(db, schueler_ids)
    letzte_benachrichtigung_map = await load_letzte_benachrichtigung_map(db, schueler_ids)
    ohne_massnahme_map = await load_ohne_massnahme_map(db, schueler_ids, letzte_benachrichtigung_map)
    return {
        schueler_id: {
            "zaehlerstand": zaehlerstand_map[schueler_id],
            "letzte_benachrichtigung": letzte_benachrichtigung_map.get(schueler_id),
            "ohne_massnahme_seit_benachrichtigung": ohne_massnahme_map.get(schueler_id, False),
        }
        for schueler_id in schueler_ids
    }


async def load_student_detail(db: AsyncSession, schueler_id: int) -> dict[str, Any]:
    """Laedt alle Unterlisten fuer die Detailansicht eines Schuelers."""
    fehlzeiten = (
        await db.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler_id).order_by(Fehlzeit.datum.desc()))
    ).scalars().all()
    klassenbuch = (
        await db.execute(
            select(KlassenbuchEintrag)
            .where(KlassenbuchEintrag.schueler_id == schueler_id)
            .order_by(KlassenbuchEintrag.datum.desc())
        )
    ).scalars().all()
    massnahmen_rows = (
        await db.execute(
            select(Massnahme, MassnahmenTyp.name, Nutzer.name)
            .join(MassnahmenTyp, MassnahmenTyp.id == Massnahme.massnahmen_typ_id)
            .join(Nutzer, Nutzer.id == Massnahme.erfasst_von_nutzer_id)
            .where(Massnahme.schueler_id == schueler_id)
            .order_by(Massnahme.datum.desc())
        )
    ).all()
    ausnahmen = (
        await db.execute(
            select(Ausnahme).where(Ausnahme.schueler_id == schueler_id, Ausnahme.aktiv.is_(True))
        )
    ).scalars().all()
    benachrichtigungen = (
        await db.execute(
            select(Benachrichtigung)
            .where(Benachrichtigung.schueler_id == schueler_id)
            .order_by(Benachrichtigung.gesendet_am.desc())
        )
    ).scalars().all()
    zaehlerstand_map = await load_zaehlerstand_map(db, [schueler_id])

    return {
        "fehlzeiten": list(fehlzeiten),
        "klassenbuch": list(klassenbuch),
        "massnahmen": list(massnahmen_rows),
        "ausnahmen": list(ausnahmen),
        "benachrichtigungen": list(benachrichtigungen),
        "zaehlerstand": zaehlerstand_map[schueler_id],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_student_query.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/student_query.py backend/tests/test_student_query.py
git commit -m "feat: add student_query service (filtered list + batched overview/detail lookups)"
```

---

## Task 5: `GET /students` — Übersicht (Router-Grundgerüst)

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/students.py`
- Create: `backend/app/api/routes/__init__.py`
- Create: `backend/app/api/routes/students.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `resolve_scope`, `get_wordpress_proxy_nutzer` (Task 1/Plan 1), `student_query.list_students`, `student_query.load_overview_extras`, `student_query.load_klasse_map` (Task 4).
- Produces: Pydantic-Schemas `KlasseOut`, `ZaehlerstandOut`, `BenachrichtigungOut`, `StudentOverviewOut`, `StudentListOut` in `app.schemas.students` (von Task 6 weiterverwendet).
- Produces: `router` (`APIRouter`, `prefix="/students"`) in `app.api.routes.students`, in `app.main.app` registriert.

- [ ] **Step 1: Write the failing test**

Create `backend/app/schemas/__init__.py` (leer) und `backend/app/api/routes/__init__.py` (leer).

Create `backend/tests/test_api_students.py`:

```python
import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.bereich import Bereich, bereich_klasse
from app.models.benachrichtigung import Benachrichtigung
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand

HEADERS_KLASSENLEHRKRAFT = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "klassenlehrkraft",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


async def _seed_klassenlehrkraft(db_session, klasse_ids):
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    for klasse_id in klasse_ids:
        db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_id, quelle="webuntis_seed"))
    await db_session.commit()
    return nutzer


@pytest.mark.asyncio
async def test_get_students_rejects_missing_wordpress_secret():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-Secret": "wrong"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_students_returns_only_students_in_callers_scope(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="Max", nachname="Muster", klasse_id=klasse_a.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="Erika", nachname="Beispiel", klasse_id=klasse_b.id)
    db_session.add_all([schueler_a, schueler_b])
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [schueler_a.id]
    assert body["items"][0]["klasse"] == {"id": klasse_a.id, "name": "10a"}


@pytest.mark.asyncio
async def test_get_students_response_includes_zaehlerstand_and_letzte_benachrichtigung(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerZaehlerstand(schueler_id=schueler.id, typ="fehlzeiten", aktueller_stand=4, erreichte_stufe_nr=1))
    db_session.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            stufe_nr=1,
            gesendet_am=datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc),
            empfaenger=[{"rolle": "klassenlehrkraft", "nutzer_id": 1}],
            status="gesendet",
        )
    )
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["zaehlerstand"]["fehlzeiten"] == {"aktueller_stand": 4, "erreichte_stufe_nr": 1}
    assert item["zaehlerstand"]["klassenbuch"] == {"aktueller_stand": 0, "erreichte_stufe_nr": None}
    assert item["letzte_benachrichtigung"]["stufe_nr"] == 1
    assert item["ohne_massnahme_seit_benachrichtigung"] is True


@pytest.mark.asyncio
async def test_get_students_pagination_and_bereich_filter(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    bereich = Bereich(name="Oberstufe")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_b.id))
    db_session.add_all(
        [
            Schueler(externe_id="ext-1", vorname="A", nachname="01", klasse_id=klasse_a.id),
            Schueler(externe_id="ext-2", vorname="B", nachname="02", klasse_id=klasse_b.id),
        ]
    )
    nutzer = Nutzer(wp_user_id="bereichsleiter1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    headers = {**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-User": "bereichsleiter1", "X-WordPress-Role": "bereichsleiter"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=headers, params={"limit": 1, "offset": 0, "bereich_id": bereich.id})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    assert body["items"][0]["nachname"] == "01"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: FAIL with 404 (route `/students` does not exist yet) or import errors.

- [ ] **Step 3: Implement schemas and route**

Create `backend/app/schemas/students.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class KlasseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ZaehlerstandOut(BaseModel):
    aktueller_stand: int
    erreichte_stufe_nr: int | None


class BenachrichtigungOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    regel_id: int | None
    stufe_nr: int
    gesendet_am: datetime
    empfaenger: list[dict[str, Any]]
    status: str


class StudentOverviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vorname: str
    nachname: str
    klasse: KlasseOut | None
    zaehlerstand: dict[str, ZaehlerstandOut]
    letzte_benachrichtigung: BenachrichtigungOut | None
    ohne_massnahme_seit_benachrichtigung: bool


class StudentListOut(BaseModel):
    items: list[StudentOverviewOut]
    total: int
    limit: int
    offset: int
```

Create `backend/app/api/routes/students.py`:

```python
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_wordpress_proxy_nutzer, resolve_scope
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.students import StudentListOut, StudentOverviewOut
from app.services import student_query

router = APIRouter(prefix="/students", tags=["students"])


@router.get("")
async def get_students(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: Literal["fehlzeiten", "klassenbuch"] | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StudentListOut:
    scope = await resolve_scope(db, nutzer)
    schueler_list, total = await student_query.list_students(
        db,
        scope=scope,
        klasse_id=klasse_id,
        bereich_id=bereich_id,
        typ=typ,
        min_stufe=min_stufe,
        nur_auffaellige=nur_auffaellige,
        limit=limit,
        offset=offset,
    )
    schueler_ids = [schueler.id for schueler in schueler_list]
    extras = await student_query.load_overview_extras(db, schueler_ids)
    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)

    items = [
        StudentOverviewOut(
            id=schueler.id,
            vorname=schueler.vorname,
            nachname=schueler.nachname,
            klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
            zaehlerstand=extras[schueler.id]["zaehlerstand"],
            letzte_benachrichtigung=extras[schueler.id]["letzte_benachrichtigung"],
            ohne_massnahme_seit_benachrichtigung=extras[schueler.id]["ohne_massnahme_seit_benachrichtigung"],
        )
        for schueler in schueler_list
    ]
    return StudentListOut(items=items, total=total, limit=limit, offset=offset)
```

In `backend/app/main.py`, add the import at the top:

```python
from app.api.routes.students import router as students_router
```

and register the router right after `app = FastAPI(title="AbsenzDash Backend", lifespan=lifespan)`:

```python
app = FastAPI(title="AbsenzDash Backend", lifespan=lifespan)
app.include_router(students_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas backend/app/api/routes backend/app/main.py backend/tests/test_api_students.py
git commit -m "feat: add GET /students overview endpoint"
```

---

## Task 6: `GET /students/{id}` — Detailansicht

**Files:**
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `get_scoped_schueler` (Task 1), `student_query.load_student_detail`, `student_query.load_klasse_map` (Task 4).
- Produces: schemas `FehlzeitOut`, `KlassenbuchEintragOut`, `MassnahmeOut`, `AusnahmeOut`, `StudentDetailOut` (von Task 7/8 weiterverwendet).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api_students.py` (add `from app.models.massnahme import Massnahme` and `from app.models.massnahmen_typ import MassnahmenTyp` to the imports):

```python
@pytest.mark.asyncio
async def test_get_student_detail_returns_all_sublists(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    typ = MassnahmenTyp(name="Gespräch", setzt_zaehler_zurueck=False)
    nutzer = Nutzer(wp_user_id="lehrkraft1", email="l@b.de", name="Lehrer A", rolle="klassenlehrkraft")
    db_session.add_all([typ, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=typ.id,
            datum=datetime.date(2026, 2, 5),
            notiz="Elterngespräch geführt",
            erfasst_von_nutzer_id=nutzer.id,
        )
    )
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}",
            headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-User": "lehrkraft1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["klasse"] == {"id": klasse.id, "name": "10a"}
    assert len(body["massnahmen"]) == 1
    assert body["massnahmen"][0]["massnahmen_typ_name"] == "Gespräch"
    assert body["massnahmen"][0]["erfasst_von_name"] == "Lehrer A"
    assert body["fehlzeiten"] == []
    assert body["ausnahmen"] == []


@pytest.mark.asyncio
async def test_get_student_detail_404s_for_out_of_scope_student(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students/{schueler.id}", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: FAIL with 404 (route `/students/{id}` does not exist yet).

- [ ] **Step 3: Implement schemas and route**

In `backend/app/schemas/students.py`, change the top import line from:

```python
from datetime import datetime
```

to:

```python
from datetime import date, datetime
```

Then append at the end of the file:

```python
class FehlzeitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    typ: str
    datum: date
    start_zeit: int
    end_zeit: int
    fach: str | None
    excuse_status_id: int | None
    grund_text: str | None


class KlassenbuchEintragOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kategorie_id: int
    datum: date
    text: str | None
    lesson_id: int | None


class MassnahmeOut(BaseModel):
    id: int
    massnahmen_typ_id: int
    massnahmen_typ_name: str
    datum: date
    notiz: str | None
    erfasst_von_nutzer_id: int
    erfasst_von_name: str


class AusnahmeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kategorie: str
    grund: str
    gueltig_bis: date | None
    aktiv: bool


class StudentDetailOut(BaseModel):
    id: int
    vorname: str
    nachname: str
    klasse: KlasseOut | None
    zaehlerstand: dict[str, ZaehlerstandOut]
    fehlzeiten: list[FehlzeitOut]
    klassenbuch: list[KlassenbuchEintragOut]
    massnahmen: list[MassnahmeOut]
    ausnahmen: list[AusnahmeOut]
    benachrichtigungen: list[BenachrichtigungOut]
```

In `backend/app/api/routes/students.py`, change these two lines:

```python
from app.api.deps import get_wordpress_proxy_nutzer, resolve_scope
from app.schemas.students import StudentListOut, StudentOverviewOut
```

to:

```python
from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.models.schueler import Schueler
from app.schemas.students import MassnahmeOut, StudentDetailOut, StudentListOut, StudentOverviewOut
```

(the `from app.models.schueler import Schueler` line goes right after the `app.api.deps` import line, keeping the existing `app.core.database`/`app.models.nutzer`/`app.services` import lines unchanged)

Append the new route at the end of the file:

```python
@router.get("/{schueler_id}")
async def get_student_detail(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudentDetailOut:
    detail = await student_query.load_student_detail(db, schueler.id)
    klasse = None
    if schueler.klasse_id is not None:
        klasse_map = await student_query.load_klasse_map(db, [schueler.klasse_id])
        klasse = klasse_map.get(schueler.klasse_id)

    massnahmen = [
        MassnahmeOut(
            id=massnahme.id,
            massnahmen_typ_id=massnahme.massnahmen_typ_id,
            massnahmen_typ_name=typ_name,
            datum=massnahme.datum,
            notiz=massnahme.notiz,
            erfasst_von_nutzer_id=massnahme.erfasst_von_nutzer_id,
            erfasst_von_name=nutzer_name,
        )
        for massnahme, typ_name, nutzer_name in detail["massnahmen"]
    ]

    return StudentDetailOut(
        id=schueler.id,
        vorname=schueler.vorname,
        nachname=schueler.nachname,
        klasse=klasse,
        zaehlerstand=detail["zaehlerstand"],
        fehlzeiten=detail["fehlzeiten"],
        klassenbuch=detail["klassenbuch"],
        massnahmen=massnahmen,
        ausnahmen=detail["ausnahmen"],
        benachrichtigungen=detail["benachrichtigungen"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/students.py backend/app/api/routes/students.py backend/tests/test_api_students.py
git commit -m "feat: add GET /students/{id} detail endpoint"
```

---

## Task 7: `POST /students/{id}/measures`

**Files:**
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `massnahme_service.record_massnahme` (Task 2), `MassnahmeOut` (Task 6).
- Produces: schema `MeasureCreateIn`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_students.py`:

```python
@pytest.mark.asyncio
async def test_create_measure_returns_created_measure_and_writes_audit_log(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    db_session.add_all([schueler, typ])
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/measures",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"massnahmen_typ_id": typ.id, "datum": "2026-02-10", "notiz": "Testnotiz"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["massnahmen_typ_name"] == "Nachsitzen"
    assert body["notiz"] == "Testnotiz"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "massnahme_erfasst"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_create_measure_404s_for_unknown_measure_type(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/measures",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"massnahmen_typ_id": 999999, "datum": "2026-02-10"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_measure_404s_for_out_of_scope_student(db_session):
    klasse_a = Klasse(webuntis_id=1, name="10a")
    klasse_b = Klasse(webuntis_id=2, name="10b")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse_b.id)
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    db_session.add_all([schueler, typ])
    await _seed_klassenlehrkraft(db_session, [klasse_a.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/measures",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"massnahmen_typ_id": typ.id, "datum": "2026-02-10"},
        )
    assert response.status_code == 404
```

Add `from app.models.audit_log import AuditLog` and `from sqlalchemy import select` to the imports at the top of `backend/tests/test_api_students.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: FAIL with 404 (route `POST /students/{id}/measures` does not exist yet).

- [ ] **Step 3: Implement schema and route**

Append to `backend/app/schemas/students.py`:

```python
class MeasureCreateIn(BaseModel):
    massnahmen_typ_id: int
    datum: date
    notiz: str | None = None
```

In `backend/app/api/routes/students.py`, change these lines:

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.students import MassnahmeOut, StudentDetailOut, StudentListOut, StudentOverviewOut
from app.services import student_query
```

to:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scoped_schueler, get_wordpress_proxy_nutzer, resolve_scope
from app.core.database import get_db
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.students import (
    MassnahmeOut,
    MeasureCreateIn,
    StudentDetailOut,
    StudentListOut,
    StudentOverviewOut,
)
from app.services import massnahme_service, student_query
```

Append the new route at the end of the file:

```python
@router.post("/{schueler_id}/measures", status_code=status.HTTP_201_CREATED)
async def create_measure(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: MeasureCreateIn,
) -> MassnahmeOut:
    typ = (
        await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == body.massnahmen_typ_id))
    ).scalar_one_or_none()
    if typ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Measure type not found")

    massnahme = await massnahme_service.record_massnahme(
        db,
        schueler_id=schueler.id,
        massnahmen_typ_id=body.massnahmen_typ_id,
        datum=body.datum,
        notiz=body.notiz,
        erfasst_von_nutzer_id=nutzer.id,
    )
    return MassnahmeOut(
        id=massnahme.id,
        massnahmen_typ_id=massnahme.massnahmen_typ_id,
        massnahmen_typ_name=typ.name,
        datum=massnahme.datum,
        notiz=massnahme.notiz,
        erfasst_von_nutzer_id=massnahme.erfasst_von_nutzer_id,
        erfasst_von_name=nutzer.name,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/students.py backend/app/api/routes/students.py backend/tests/test_api_students.py
git commit -m "feat: add POST /students/{id}/measures endpoint"
```

---

## Task 8: `POST /students/{id}/exemptions` & `DELETE /students/{id}/exemptions/{exemption_id}`

**Files:**
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `ausnahme_service.create_ausnahme`, `ausnahme_service.revoke_ausnahme` (Task 3), `AusnahmeOut` (Task 6).
- Produces: schema `ExemptionCreateIn`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_students.py` (add `from app.models.ausnahme import Ausnahme` to the imports):

```python
@pytest.mark.asyncio
async def test_create_exemption_returns_created_exemption_and_writes_audit_log(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/students/{schueler.id}/exemptions",
            headers=HEADERS_KLASSENLEHRKRAFT,
            json={"kategorie": "fehlzeiten", "grund": "Ärztliches Attest", "gueltig_bis": "2026-12-31"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["kategorie"] == "fehlzeiten"
    assert body["aktiv"] is True

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "ausnahme_erstellt"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_revoke_exemption_sets_inactive_and_writes_audit_log(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Test", aktiv=True)
    db_session.add(ausnahme)
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/students/{schueler.id}/exemptions/{ausnahme.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 204

    reloaded = (await db_session.execute(select(Ausnahme).where(Ausnahme.id == ausnahme.id))).scalar_one()
    assert reloaded.aktiv is False

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "ausnahme_aufgehoben"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_revoke_exemption_404s_when_already_revoked(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    db_session.add(schueler)
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler.id, kategorie="klassenbuch", grund="Test", aktiv=False)
    db_session.add(ausnahme)
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/students/{schueler.id}/exemptions/{ausnahme.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_exemption_404s_for_exemption_belonging_to_different_student(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler_a = Schueler(externe_id="ext-a", vorname="Max", nachname="Muster", klasse_id=klasse.id)
    schueler_b = Schueler(externe_id="ext-b", vorname="Erika", nachname="Beispiel", klasse_id=klasse.id)
    db_session.add_all([schueler_a, schueler_b])
    await db_session.flush()
    ausnahme = Ausnahme(schueler_id=schueler_b.id, kategorie="klassenbuch", grund="Test", aktiv=True)
    db_session.add(ausnahme)
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete(
            f"/students/{schueler_a.id}/exemptions/{ausnahme.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: FAIL with 404 (routes for exemptions do not exist yet).

- [ ] **Step 3: Implement schema and routes**

In `backend/app/schemas/students.py`, change the top import line from:

```python
from typing import Any
```

to:

```python
from typing import Any, Literal
```

Then append at the end of the file:

```python
class ExemptionCreateIn(BaseModel):
    kategorie: Literal["fehlzeiten", "klassenbuch"]
    grund: str
    gueltig_bis: date | None = None
```

In `backend/app/api/routes/students.py`, change these lines:

```python
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.students import (
    MassnahmeOut,
    MeasureCreateIn,
    StudentDetailOut,
    StudentListOut,
    StudentOverviewOut,
)
from app.services import massnahme_service, student_query
```

to:

```python
from app.models.ausnahme import Ausnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.students import (
    AusnahmeOut,
    ExemptionCreateIn,
    MassnahmeOut,
    MeasureCreateIn,
    StudentDetailOut,
    StudentListOut,
    StudentOverviewOut,
)
from app.services import ausnahme_service, massnahme_service, student_query
```

Append the new routes at the end of the file:

```python
@router.post("/{schueler_id}/exemptions", status_code=status.HTTP_201_CREATED)
async def create_exemption(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    body: ExemptionCreateIn,
) -> AusnahmeOut:
    ausnahme = await ausnahme_service.create_ausnahme(
        db,
        schueler_id=schueler.id,
        kategorie=body.kategorie,
        grund=body.grund,
        gueltig_bis=body.gueltig_bis,
        nutzer_id=nutzer.id,
    )
    return AusnahmeOut.model_validate(ausnahme)


@router.delete("/{schueler_id}/exemptions/{exemption_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_exemption(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    exemption_id: int,
) -> None:
    ausnahme = (await db.execute(select(Ausnahme).where(Ausnahme.id == exemption_id))).scalar_one_or_none()
    if ausnahme is None or ausnahme.schueler_id != schueler.id or not ausnahme.aktiv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exemption not found")
    await ausnahme_service.revoke_ausnahme(db, ausnahme, nutzer.id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_students.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Run the full backend test suite**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -v`
Expected: PASS (all tests, no regressions)

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/students.py backend/app/api/routes/students.py backend/tests/test_api_students.py
git commit -m "feat: add POST/DELETE /students/{id}/exemptions endpoints"
```

---

## Task 9: ROADMAP.md aktualisieren

**Files:**
- Modify: `ROADMAP.md`

**Interfaces:** keine (reine Dokumentationsänderung).

- [ ] **Step 1: Plan-5-Zeile in die "Abgeschlossen"-Tabelle einfügen**

In `ROADMAP.md`, nach der Plan-4-Zeile der Tabelle im Abschnitt "Abgeschlossen" folgende Zeile ergänzen:

```markdown
| **Plan 5** — [Backend REST-API fürs WP-Plugin — Kern-Endpunkte](docs/superpowers/plans/2026-07-27-rest-api-wordpress-kern.md) | Scope-Check (`nutzer_klasse`/`nutzer_bereich`), `GET /students` (paginiert, gefiltert), `GET /students/{id}`, `POST /students/{id}/measures`, `POST/DELETE /students/{id}/exemptions`, Audit-Log für Maßnahmen/Ausnahmen (TECH-SPEC.md §3, SPECS.md §3/4/7) | Admin-Konfigurationsendpunkte (`/admin/*`), PDF-Export |
```

- [ ] **Step 2: Punkt 1 der "Geplant"-Liste auf den verbleibenden Scope reduzieren**

Ersetze in `ROADMAP.md` im Abschnitt "Geplant (noch nicht als Plan ausgearbeitet)":

```markdown
1. **Backend: REST-API fürs WP-Plugin** — `/students`, `/students/{id}`, Maßnahmen-/Ausnahmen-Endpunkte, `/admin/*`-Konfigurationsendpunkte inkl. `/admin/sync-now` (TECH-SPEC.md §3). Setzt die bereits vorhandene WP-Proxy-Auth-Dependency (Plan 1) tatsächlich in Routen ein.
```

durch:

```markdown
1. **Backend: REST-API fürs WP-Plugin — Admin-Konfiguration & PDF-Export** — `/admin/*`-Konfigurationsendpunkte inkl. `/admin/sync-now`, `GET /students/{id}/export.pdf` (TECH-SPEC.md §3). Kern-Endpunkte (Übersicht/Detail/Maßnahmen/Ausnahmen) sind mit Plan 5 fertig.
```

- [ ] **Step 3: Stand-Datum aktualisieren**

Ändere die erste Zeile von `ROADMAP.md` von `Stand: 2026-07-26` auf `Stand: 2026-07-27`.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: mark Plan 5 (REST-API core endpoints) as completed in ROADMAP"
```
