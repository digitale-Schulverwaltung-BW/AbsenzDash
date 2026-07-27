# Backend: Admin-Konfiguration REST-Endpunkte Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the five `schulleitung`-only admin REST endpoints from TECH-SPEC.md §3 (threshold rules, measure-type catalog, excuse statuses, sync settings, manual sync trigger) to the AbsenzDash FastAPI backend.

**Architecture:** One new role-gated FastAPI router (`app/api/routes/admin.py`) mounted at `/admin`. Three of the five resources (threshold rules, measure types, excuse statuses) share a bulk "replace the whole list" contract implemented as a diff/upsert against existing rows by `id`, with a delete-attempt for rows omitted from the payload (catching FK conflicts as 409 instead of 500). Sync settings and sync-now reuse and lightly refactor the existing `sync_orchestrator`/`scheduler` modules.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, APScheduler, pytest + pytest-asyncio + httpx (existing stack, no new dependencies).

## Global Constraints

- Commit messages in English (user's global convention).
- All five endpoints require the `schulleitung` role — any other role gets `403`.
- Fachliche Validierungsfehler (business-rule violations) → `422`, and nothing is written to the DB.
- Deleting a row still referenced elsewhere (measure type used in a `massnahme`, excuse status used in a `fehlzeit`) → `409`, whole request rolled back, never a raw `500`.
- Threshold-rule deletion is always a hard delete (safe: `schueler_zaehlerstand.regel_id`/`benachrichtigung.regel_id` are `ON DELETE SET NULL`).
- No new library dependencies for this plan (PDF export, which would need one, is a separate later plan).
- Reference design doc: [docs/superpowers/specs/2026-07-27-admin-konfiguration-design.md](../specs/2026-07-27-admin-konfiguration-design.md).
- Python runs only inside Docker on this machine (`docs/backend-setup.md`) — before running any `pytest`/`alembic` command in this plan, ensure Postgres is up: `docker compose -f backend/docker-compose.yml up -d postgres`. All `pytest`/`alembic` commands below already use `docker compose -f backend/docker-compose.yml run --rm backend ...` and must be run from the repo root (the worktree root), not from inside `backend/`.

---

## Task 1: `require_schulleitung` dependency

**Files:**
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_api_deps_admin.py`

**Interfaces:**
- Produces: `require_schulleitung(nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)]) -> Nutzer` in `app.api.deps` — raises `HTTPException(403)` for any role other than `"schulleitung"`, otherwise returns the `Nutzer` unchanged. All later tasks depend on this.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_deps_admin.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_schulleitung
from app.core.config import settings
from app.models.nutzer import Nutzer

admin_test_app = FastAPI()


@admin_test_app.get("/schulleitung-only")
async def schulleitung_only(nutzer: Nutzer = Depends(require_schulleitung)):
    return {"id": nutzer.id}


HEADERS_BASE = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_require_schulleitung_allows_schulleitung(db_session):
    transport = ASGITransport(app=admin_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/schulleitung-only", headers={**HEADERS_BASE, "X-WordPress-Role": "schulleitung"}
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_require_schulleitung_rejects_klassenlehrkraft(db_session):
    transport = ASGITransport(app=admin_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/schulleitung-only", headers={**HEADERS_BASE, "X-WordPress-Role": "klassenlehrkraft"}
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_require_schulleitung_rejects_bereichsleiter(db_session):
    transport = ASGITransport(app=admin_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/schulleitung-only", headers={**HEADERS_BASE, "X-WordPress-Role": "bereichsleiter"}
        )
    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_deps_admin.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_schulleitung'`

- [ ] **Step 3: Implement `require_schulleitung`**

In `backend/app/api/deps.py`, append at the end of the file (after `get_scoped_schueler`):

```python
async def require_schulleitung(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
) -> Nutzer:
    """Admin-Endpunkte (TECH-SPEC.md Abschnitt 3, Gruppe 2) sind ausschliesslich fuer schulleitung."""
    if nutzer.rolle != "schulleitung":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Schulleitung required")
    return nutzer
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_deps_admin.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps.py backend/tests/test_api_deps_admin.py
git commit -m "feat: add require_schulleitung dependency for admin endpoints"
```

---

## Task 2: `GET/PUT /admin/threshold-rules`

**Files:**
- Create: `backend/app/schemas/admin.py`
- Create: `backend/app/services/threshold_rule_service.py`
- Create: `backend/app/api/routes/admin.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_admin_threshold_rules.py`

**Interfaces:**
- Consumes: `require_schulleitung` (Task 1), `app.core.database.get_db`, existing models `SchwellwertRegel`, `SchwellwertStufe`, `Abteilung`, `Klasse`, `Nutzer.ROLLEN`, `AuditLog`.
- Produces:
  - `app.schemas.admin.SchwellwertStufeIn/Out`, `ThresholdRuleIn/Out` (Pydantic models, `id: int | None = None` on the `In` variants).
  - `app.services.threshold_rule_service.list_rules(db: AsyncSession) -> list[ThresholdRuleOut]`
  - `app.services.threshold_rule_service.replace_rules(db: AsyncSession, payload: list[ThresholdRuleIn], nutzer_id: int) -> list[ThresholdRuleOut]`
  - `app.api.routes.admin.router` (`APIRouter`, `prefix="/admin"`, mounted in `main.py`) — later tasks append routes to this same router/file.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_admin_threshold_rules.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe

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


def _stufe_payload(**overrides):
    base = {
        "stufe_nr": 1,
        "einheit": "fehltage",
        "schwellenwert": 4,
        "fehlzeiten_filter": "nur_unentschuldigt",
        "empfaenger_rollen": ["klassenlehrkraft"],
    }
    base.update(overrides)
    return base


def _regel_payload(**overrides):
    base = {
        "typ": "fehlzeiten",
        "geltungsbereich": "schulweit",
        "abteilung_id": None,
        "klasse_id": None,
        "stufen": [_stufe_payload()],
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_get_threshold_rules_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/threshold-rules", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_threshold_rules_creates_rule_with_stufen(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=[_regel_payload()]
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["typ"] == "fehlzeiten"
    assert body[0]["geltungsbereich"] == "schulweit"
    assert len(body[0]["stufen"]) == 1
    assert body[0]["stufen"][0]["schwellenwert"] == 4

    audit_result = await db_session.execute(
        select(AuditLog).where(AuditLog.aktion == "admin_threshold_rules_updated")
    )
    assert audit_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_threshold_rules_upserts_by_id_and_deletes_omitted(db_session):
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    stufe = SchwellwertStufe(
        regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=4,
        fehlzeiten_filter="nur_unentschuldigt", empfaenger_rollen=["klassenlehrkraft"],
    )
    other_regel = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    db_session.add_all([stufe, other_regel])
    await db_session.commit()

    payload = [
        _regel_payload(
            id=regel.id,
            stufen=[_stufe_payload(id=stufe.id, schwellenwert=8)],
        )
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == regel.id
    assert body[0]["stufen"][0]["id"] == stufe.id
    assert body[0]["stufen"][0]["schwellenwert"] == 8

    remaining = await db_session.execute(select(SchwellwertRegel))
    assert [r.id for r in remaining.scalars().all()] == [regel.id]


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_duplicate_schulweit_rule(db_session):
    transport = ASGITransport(app=app)
    payload = [_regel_payload(), _regel_payload()]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422

    remaining = await db_session.execute(select(SchwellwertRegel))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_unknown_klasse_id(db_session):
    transport = ASGITransport(app=app)
    payload = [_regel_payload(geltungsbereich="klasse", klasse_id=999999)]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_threshold_rules_rejects_rule_without_stufen(db_session):
    transport = ASGITransport(app=app)
    payload = [_regel_payload(stufen=[])]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_threshold_rules_accepts_klasse_specific_rule(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.commit()

    payload = [_regel_payload(geltungsbereich="klasse", klasse_id=klasse.id)]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/threshold-rules", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    assert response.json()[0]["klasse_id"] == klasse.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_threshold_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.admin'` (or connection error, since `/admin/*` doesn't exist yet)

- [ ] **Step 3: Create `app/schemas/admin.py`**

```python
from __future__ import annotations

from pydantic import BaseModel


class SchwellwertStufeIn(BaseModel):
    id: int | None = None
    stufe_nr: int
    einheit: str | None = None
    schwellenwert: int
    fehlzeiten_filter: str | None = None
    empfaenger_rollen: list[str]


class SchwellwertStufeOut(BaseModel):
    id: int
    stufe_nr: int
    einheit: str | None
    schwellenwert: int
    fehlzeiten_filter: str | None
    empfaenger_rollen: list[str]


class ThresholdRuleIn(BaseModel):
    id: int | None = None
    typ: str
    geltungsbereich: str
    abteilung_id: int | None = None
    klasse_id: int | None = None
    stufen: list[SchwellwertStufeIn]


class ThresholdRuleOut(BaseModel):
    id: int
    typ: str
    geltungsbereich: str
    abteilung_id: int | None
    klasse_id: int | None
    stufen: list[SchwellwertStufeOut]
```

- [ ] **Step 4: Create `app/services/threshold_rule_service.py`**

```python
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse
from app.models.nutzer import ROLLEN
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.schemas.admin import SchwellwertStufeOut, ThresholdRuleIn, ThresholdRuleOut

TYPEN = ("fehlzeiten", "klassenbuch")
GELTUNGSBEREICHE = ("schulweit", "abteilung", "klasse")
EINHEITEN = ("fehltage", "fehlstunden")
FEHLZEITEN_FILTER = ("nur_unentschuldigt", "alle")


def _stufe_out(stufe: SchwellwertStufe) -> SchwellwertStufeOut:
    return SchwellwertStufeOut(
        id=stufe.id,
        stufe_nr=stufe.stufe_nr,
        einheit=stufe.einheit,
        schwellenwert=stufe.schwellenwert,
        fehlzeiten_filter=stufe.fehlzeiten_filter,
        empfaenger_rollen=list(stufe.empfaenger_rollen),
    )


async def _regel_out(db: AsyncSession, regel: SchwellwertRegel) -> ThresholdRuleOut:
    stufen_result = await db.execute(
        select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id).order_by(SchwellwertStufe.stufe_nr)
    )
    return ThresholdRuleOut(
        id=regel.id,
        typ=regel.typ,
        geltungsbereich=regel.geltungsbereich,
        abteilung_id=regel.abteilung_id,
        klasse_id=regel.klasse_id,
        stufen=[_stufe_out(s) for s in stufen_result.scalars().all()],
    )


async def list_rules(db: AsyncSession) -> list[ThresholdRuleOut]:
    result = await db.execute(select(SchwellwertRegel).order_by(SchwellwertRegel.id))
    return [await _regel_out(db, r) for r in result.scalars().all()]


def _validate_payload_shape(payload: list[ThresholdRuleIn]) -> None:
    seen_schulweit: set[str] = set()
    seen_abteilung: set[tuple[str, int]] = set()
    seen_klasse: set[tuple[str, int]] = set()

    for regel in payload:
        if regel.typ not in TYPEN:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown typ: {regel.typ}")
        if regel.geltungsbereich not in GELTUNGSBEREICHE:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown geltungsbereich: {regel.geltungsbereich}")

        if regel.geltungsbereich == "schulweit":
            if regel.abteilung_id is not None or regel.klasse_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "schulweit rule must not set abteilung_id/klasse_id")
            if regel.typ in seen_schulweit:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate schulweit rule for typ={regel.typ}")
            seen_schulweit.add(regel.typ)
        elif regel.geltungsbereich == "abteilung":
            if regel.abteilung_id is None or regel.klasse_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "abteilung rule needs abteilung_id and no klasse_id")
            key = (regel.typ, regel.abteilung_id)
            if key in seen_abteilung:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate rule for typ={regel.typ}, abteilung_id={regel.abteilung_id}")
            seen_abteilung.add(key)
        else:
            if regel.klasse_id is None or regel.abteilung_id is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "klasse rule needs klasse_id and no abteilung_id")
            key = (regel.typ, regel.klasse_id)
            if key in seen_klasse:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate rule for typ={regel.typ}, klasse_id={regel.klasse_id}")
            seen_klasse.add(key)

        if not regel.stufen:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Rule needs at least one Stufe")

        seen_stufe_nr: set[int] = set()
        for stufe in regel.stufen:
            if stufe.stufe_nr in seen_stufe_nr:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate stufe_nr {stufe.stufe_nr} in rule")
            seen_stufe_nr.add(stufe.stufe_nr)
            if regel.typ == "fehlzeiten" and stufe.einheit not in EINHEITEN:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid einheit for fehlzeiten-Regel: {stufe.einheit}")
            if regel.typ == "klassenbuch" and stufe.einheit is not None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "klassenbuch-Regel must not set einheit")
            if stufe.fehlzeiten_filter is not None and stufe.fehlzeiten_filter not in FEHLZEITEN_FILTER:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid fehlzeiten_filter: {stufe.fehlzeiten_filter}")
            if not stufe.empfaenger_rollen:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empfaenger_rollen must not be empty")
            for rolle in stufe.empfaenger_rollen:
                if rolle not in ROLLEN:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rolle: {rolle}")


async def _validate_references_exist(db: AsyncSession, payload: list[ThresholdRuleIn]) -> None:
    abteilung_ids = {r.abteilung_id for r in payload if r.abteilung_id is not None}
    if abteilung_ids:
        result = await db.execute(select(Abteilung.id).where(Abteilung.id.in_(abteilung_ids)))
        missing = abteilung_ids - set(result.scalars().all())
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown abteilung_id(s): {sorted(missing)}")

    klasse_ids = {r.klasse_id for r in payload if r.klasse_id is not None}
    if klasse_ids:
        result = await db.execute(select(Klasse.id).where(Klasse.id.in_(klasse_ids)))
        missing = klasse_ids - set(result.scalars().all())
        if missing:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown klasse_id(s): {sorted(missing)}")


async def replace_rules(db: AsyncSession, payload: list[ThresholdRuleIn], nutzer_id: int) -> list[ThresholdRuleOut]:
    _validate_payload_shape(payload)
    await _validate_references_exist(db, payload)

    existing_result = await db.execute(select(SchwellwertRegel))
    existing_by_id = {r.id: r for r in existing_result.scalars().all()}

    existing_stufen_by_regel: dict[int, dict[int, SchwellwertStufe]] = {}
    for regel_in in payload:
        if regel_in.id is None:
            continue
        if regel_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown threshold rule id: {regel_in.id}")
        stufen_result = await db.execute(select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel_in.id))
        stufen_by_id = {s.id: s for s in stufen_result.scalars().all()}
        for stufe_in in regel_in.stufen:
            if stufe_in.id is not None and stufe_in.id not in stufen_by_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown stufe id {stufe_in.id} for rule {regel_in.id}")
        existing_stufen_by_regel[regel_in.id] = stufen_by_id

    payload_ids = {r.id for r in payload if r.id is not None}
    for regel_id, regel in list(existing_by_id.items()):
        if regel_id not in payload_ids:
            await db.delete(regel)

    for regel_in in payload:
        if regel_in.id is not None:
            regel = existing_by_id[regel_in.id]
            regel.typ = regel_in.typ
            regel.geltungsbereich = regel_in.geltungsbereich
            regel.abteilung_id = regel_in.abteilung_id
            regel.klasse_id = regel_in.klasse_id
            existing_stufen_by_id = existing_stufen_by_regel[regel_in.id]
        else:
            regel = SchwellwertRegel(
                typ=regel_in.typ,
                geltungsbereich=regel_in.geltungsbereich,
                abteilung_id=regel_in.abteilung_id,
                klasse_id=regel_in.klasse_id,
            )
            db.add(regel)
            await db.flush()
            existing_stufen_by_id = {}

        stufen_payload_ids = {s.id for s in regel_in.stufen if s.id is not None}
        for stufe_id, stufe in existing_stufen_by_id.items():
            if stufe_id not in stufen_payload_ids:
                await db.delete(stufe)

        for stufe_in in regel_in.stufen:
            if stufe_in.id is not None:
                stufe = existing_stufen_by_id[stufe_in.id]
                stufe.stufe_nr = stufe_in.stufe_nr
                stufe.einheit = stufe_in.einheit
                stufe.schwellenwert = stufe_in.schwellenwert
                stufe.fehlzeiten_filter = stufe_in.fehlzeiten_filter
                stufe.empfaenger_rollen = stufe_in.empfaenger_rollen
            else:
                db.add(
                    SchwellwertStufe(
                        regel_id=regel.id,
                        stufe_nr=stufe_in.stufe_nr,
                        einheit=stufe_in.einheit,
                        schwellenwert=stufe_in.schwellenwert,
                        fehlzeiten_filter=stufe_in.fehlzeiten_filter,
                        empfaenger_rollen=stufe_in.empfaenger_rollen,
                    )
                )

    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="admin_threshold_rules_updated",
            resource_typ="schwellwert_regel",
            details={"anzahl_regeln": len(payload)},
        )
    )
    await db.commit()
    return await list_rules(db)
```

- [ ] **Step 5: Create `app/api/routes/admin.py`**

```python
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_schulleitung
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.admin import ThresholdRuleIn, ThresholdRuleOut
from app.services import threshold_rule_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_schulleitung)])


@router.get("/threshold-rules")
async def get_threshold_rules(db: Annotated[AsyncSession, Depends(get_db)]) -> list[ThresholdRuleOut]:
    return await threshold_rule_service.list_rules(db)


@router.put("/threshold-rules")
async def put_threshold_rules(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[ThresholdRuleIn],
) -> list[ThresholdRuleOut]:
    return await threshold_rule_service.replace_rules(db, payload, nutzer.id)
```

- [ ] **Step 6: Wire the router into `main.py`**

In `backend/app/main.py`, add the import and registration:

```python
from app.api.routes.students import router as students_router
from app.api.routes.admin import router as admin_router
```

```python
app.include_router(students_router)
app.include_router(admin_router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_threshold_rules.py -v`
Expected: 7 passed

- [ ] **Step 8: Run the full suite to check for regressions**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -q`
Expected: all tests pass (no regressions in `test_api_students.py`, `test_main.py`, etc.)

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/threshold_rule_service.py backend/app/api/routes/admin.py backend/app/main.py backend/tests/test_api_admin_threshold_rules.py
git commit -m "feat: add GET/PUT /admin/threshold-rules endpoint"
```

---

## Task 3: `GET/PUT /admin/measure-types`

**Files:**
- Modify: `backend/app/models/massnahmen_typ.py`
- Create: `backend/alembic/versions/<generated>_add_massnahmen_typ_aktiv.py`
- Modify: `backend/app/schemas/admin.py` (append)
- Create: `backend/app/services/measure_type_service.py`
- Modify: `backend/app/api/routes/admin.py` (append)
- Test: `backend/tests/test_api_admin_measure_types.py`
- Test (extend): `backend/tests/test_models_massnahme.py`

**Interfaces:**
- Consumes: Task 1 (`require_schulleitung`), Task 2's `admin.py` router/file structure.
- Produces:
  - `app.schemas.admin.MeasureTypeIn/Out`
  - `app.services.measure_type_service.list_measure_types(db) -> list[MeasureTypeOut]`
  - `app.services.measure_type_service.replace_measure_types(db, payload: list[MeasureTypeIn], nutzer_id: int) -> list[MeasureTypeOut]`
  - `MassnahmenTyp.aktiv: bool` (new column, default `True`)

- [ ] **Step 1: Write the failing model test**

In `backend/tests/test_models_massnahme.py`, add this test after `test_massnahme_roundtrip`:

```python
@pytest.mark.asyncio
async def test_massnahmen_typ_defaults_to_aktiv(db_session):
    typ = MassnahmenTyp(name="Testtyp", setzt_zaehler_zurueck=False)
    db_session.add(typ)
    await db_session.commit()

    result = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == typ.id))
    assert result.scalar_one().aktiv is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_massnahme.py -v`
Expected: FAIL — `TypeError` or `AttributeError: aktiv` (column doesn't exist on the model yet)

- [ ] **Step 3: Add the `aktiv` column to the model**

In `backend/app/models/massnahmen_typ.py`, modify the class:

```python
from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

massnahmen_typ_regel = Table(
    "massnahmen_typ_regel",
    Base.metadata,
    Column("massnahmen_typ_id", ForeignKey("massnahmen_typ.id", ondelete="CASCADE"), primary_key=True),
    Column("regel_id", ForeignKey("schwellwert_regel.id", ondelete="CASCADE"), primary_key=True),
)


class MassnahmenTyp(Base, TimestampMixin):
    __tablename__ = "massnahmen_typ"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    setzt_zaehler_zurueck: Mapped[bool] = mapped_column(Boolean, default=False)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_massnahme.py -v`
Expected: 3 passed (the existing 2 plus the new one — tests create tables via `Base.metadata.create_all`, so the model change is enough for this test; the Alembic migration in the next step is for real deployments)

- [ ] **Step 5: Generate and fill in the Alembic migration**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision -m "add massnahmen_typ aktiv column"`

This prints the created file path, e.g. `backend/alembic/versions/<hash>_add_massnahmen_typ_aktiv_column.py`. Open it and replace the generated `upgrade`/`downgrade` bodies (keep the auto-generated `revision`/`down_revision` values — `down_revision` must be `'43e3780702ba'`, the current head):

```python
def upgrade() -> None:
    op.add_column(
        "massnahmen_typ",
        sa.Column("aktiv", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("massnahmen_typ", "aktiv", server_default=None)


def downgrade() -> None:
    op.drop_column("massnahmen_typ", "aktiv")
```

This is not run by the test suite (tests use `Base.metadata.create_all`) but must exist for the real Postgres deployment to stay in sync with the model.

- [ ] **Step 6: Write the failing API test**

Create `backend/tests/test_api_admin_measure_types.py`:

```python
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
from app.models.schwellwert_regel import SchwellwertRegel

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
    payload = [{"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True, "betroffene_regel_ids": []}]
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
async def test_put_measure_types_upserts_and_reassigns_betroffene_regeln(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    regel_a = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    regel_b = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    db_session.add_all([typ, regel_a, regel_b])
    await db_session.commit()

    payload = [
        {
            "id": typ.id, "name": "Nachsitzen", "setzt_zaehler_zurueck": True,
            "aktiv": False, "betroffene_regel_ids": [regel_a.id, regel_b.id],
        }
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == typ.id
    assert body[0]["aktiv"] is False
    assert sorted(body[0]["betroffene_regel_ids"]) == sorted([regel_a.id, regel_b.id])


@pytest.mark.asyncio
async def test_put_measure_types_returns_409_when_deleting_used_type(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([typ, schueler, nutzer])
    await db_session.flush()
    db_session.add(
        Massnahme(schueler_id=schueler.id, massnahmen_typ_id=typ.id, datum="2026-01-20", erfasst_von_nutzer_id=nutzer.id)
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 409

    remaining = await db_session.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == typ.id))
    assert remaining.scalar_one() is not None


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
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": True, "aktiv": True, "betroffene_regel_ids": []},
        {"name": "Nachsitzen", "setzt_zaehler_zurueck": False, "aktiv": True, "betroffene_regel_ids": []},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/measure-types", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422
```

- [ ] **Step 7: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_measure_types.py -v`
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 8: Append measure-type schemas to `app/schemas/admin.py`**

Add at the end of `backend/app/schemas/admin.py`:

```python
class MeasureTypeIn(BaseModel):
    id: int | None = None
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool = True
    betroffene_regel_ids: list[int] = []


class MeasureTypeOut(BaseModel):
    id: int
    name: str
    setzt_zaehler_zurueck: bool
    aktiv: bool
    betroffene_regel_ids: list[int]
```

- [ ] **Step 9: Create `app/services/measure_type_service.py`**

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.audit_log import AuditLog
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.schwellwert_regel import SchwellwertRegel
from app.schemas.admin import MeasureTypeIn, MeasureTypeOut


async def _typ_out(db: AsyncSession, typ: MassnahmenTyp) -> MeasureTypeOut:
    result = await db.execute(
        select(massnahmen_typ_regel.c.regel_id).where(massnahmen_typ_regel.c.massnahmen_typ_id == typ.id)
    )
    return MeasureTypeOut(
        id=typ.id,
        name=typ.name,
        setzt_zaehler_zurueck=typ.setzt_zaehler_zurueck,
        aktiv=typ.aktiv,
        betroffene_regel_ids=sorted(result.scalars().all()),
    )


async def list_measure_types(db: AsyncSession) -> list[MeasureTypeOut]:
    result = await db.execute(select(MassnahmenTyp).order_by(MassnahmenTyp.id))
    return [await _typ_out(db, t) for t in result.scalars().all()]


def _validate_payload(payload: list[MeasureTypeIn]) -> None:
    seen_names: set[str] = set()
    for typ in payload:
        if not typ.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if typ.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {typ.name}")
        seen_names.add(typ.name)


async def _validate_regel_ids_exist(db: AsyncSession, payload: list[MeasureTypeIn]) -> None:
    regel_ids = {rid for typ in payload for rid in typ.betroffene_regel_ids}
    if not regel_ids:
        return
    result = await db.execute(select(SchwellwertRegel.id).where(SchwellwertRegel.id.in_(regel_ids)))
    missing = regel_ids - set(result.scalars().all())
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown regel_id(s): {sorted(missing)}")


async def replace_measure_types(
    db: AsyncSession, payload: list[MeasureTypeIn], nutzer_id: int
) -> list[MeasureTypeOut]:
    _validate_payload(payload)
    await _validate_regel_ids_exist(db, payload)

    existing_result = await db.execute(select(MassnahmenTyp))
    existing_by_id = {t.id: t for t in existing_result.scalars().all()}

    for typ_in in payload:
        if typ_in.id is not None and typ_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown measure type id: {typ_in.id}")

    payload_ids = {t.id for t in payload if t.id is not None}
    removed_ids = [tid for tid in existing_by_id if tid not in payload_ids]
    removed_names = [existing_by_id[tid].name for tid in removed_ids]
    for typ_id in removed_ids:
        await db.delete(existing_by_id[typ_id])

    for typ_in in payload:
        if typ_in.id is not None:
            typ = existing_by_id[typ_in.id]
            typ.name = typ_in.name
            typ.setzt_zaehler_zurueck = typ_in.setzt_zaehler_zurueck
            typ.aktiv = typ_in.aktiv
        else:
            typ = MassnahmenTyp(name=typ_in.name, setzt_zaehler_zurueck=typ_in.setzt_zaehler_zurueck, aktiv=typ_in.aktiv)
            db.add(typ)
            await db.flush()

        await db.execute(massnahmen_typ_regel.delete().where(massnahmen_typ_regel.c.massnahmen_typ_id == typ.id))
        for regel_id in typ_in.betroffene_regel_ids:
            await db.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel_id))

    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="admin_measure_types_updated",
            resource_typ="massnahmen_typ",
            details={"anzahl_typen": len(payload)},
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kann folgende(n) Maßnahmen-Typ(en) nicht löschen, da bereits verwendet: "
            f"{', '.join(removed_names)}. Stattdessen deaktivieren (aktiv=false).",
        )

    return await list_measure_types(db)
```

- [ ] **Step 10: Append measure-type routes to `app/api/routes/admin.py`**

Add the import and routes to `backend/app/api/routes/admin.py` (extend the existing `from app.schemas.admin import ...` and `from app.services import ...` lines rather than duplicating them):

```python
from app.schemas.admin import MeasureTypeIn, MeasureTypeOut, ThresholdRuleIn, ThresholdRuleOut
from app.services import measure_type_service, threshold_rule_service
```

```python
@router.get("/measure-types")
async def get_measure_types(db: Annotated[AsyncSession, Depends(get_db)]) -> list[MeasureTypeOut]:
    return await measure_type_service.list_measure_types(db)


@router.put("/measure-types")
async def put_measure_types(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[MeasureTypeIn],
) -> list[MeasureTypeOut]:
    return await measure_type_service.replace_measure_types(db, payload, nutzer.id)
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_measure_types.py tests/test_models_massnahme.py -v`
Expected: all passed

- [ ] **Step 12: Run the full suite**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -q`
Expected: all tests pass

- [ ] **Step 13: Commit**

```bash
git add backend/app/models/massnahmen_typ.py backend/alembic/versions/*_add_massnahmen_typ_aktiv_column.py backend/app/schemas/admin.py backend/app/services/measure_type_service.py backend/app/api/routes/admin.py backend/tests/test_api_admin_measure_types.py backend/tests/test_models_massnahme.py
git commit -m "feat: add GET/PUT /admin/measure-types endpoint with aktiv flag"
```

---

## Task 4: `GET/PUT /admin/excuse-statuses`

**Files:**
- Modify: `backend/app/schemas/admin.py` (append)
- Create: `backend/app/services/excuse_status_service.py`
- Modify: `backend/app/api/routes/admin.py` (append)
- Test: `backend/tests/test_api_admin_excuse_statuses.py`

**Interfaces:**
- Consumes: Task 1, Task 2/3's `admin.py` router.
- Produces:
  - `app.schemas.admin.ExcuseStatusIn/Out`
  - `app.services.excuse_status_service.list_excuse_statuses(db) -> list[ExcuseStatusOut]`
  - `app.services.excuse_status_service.replace_excuse_statuses(db, payload: list[ExcuseStatusIn], nutzer_id: int) -> list[ExcuseStatusOut]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_admin_excuse_statuses.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
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
async def test_get_excuse_statuses_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/excuse-statuses", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_excuse_statuses_creates_status(db_session):
    payload = [{"name": "Attest", "long_name": "Ärztliches Attest", "zaehlt_als_entschuldigt": True, "aktiv": True}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 200
    assert response.json()[0]["name"] == "Attest"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_excuse_statuses_updated"))
    assert audit_result.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_excuse_statuses_deletes_unused_typo_entry(db_session):
    status_row = ExcuseStatus(name="Atest", zaehlt_als_entschuldigt=True, aktiv=True)
    db_session.add(status_row)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 200
    remaining = await db_session.execute(select(ExcuseStatus))
    assert remaining.scalars().all() == []


@pytest.mark.asyncio
async def test_put_excuse_statuses_returns_409_when_deleting_used_status(db_session):
    status_row = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    db_session.add_all([status_row, schueler])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum="2026-01-20", start_zeit=1, end_zeit=6,
            excuse_status_id=status_row.id,
        )
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=[])

    assert response.status_code == 409
    remaining = await db_session.execute(select(ExcuseStatus).where(ExcuseStatus.id == status_row.id))
    assert remaining.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_excuse_statuses_can_deactivate_instead_of_delete(db_session):
    status_row = ExcuseStatus(name="Attest", zaehlt_als_entschuldigt=True, aktiv=True)
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster")
    db_session.add_all([status_row, schueler])
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum="2026-01-20", start_zeit=1, end_zeit=6,
            excuse_status_id=status_row.id,
        )
    )
    await db_session.commit()

    payload = [
        {"id": status_row.id, "name": "Attest", "long_name": None, "zaehlt_als_entschuldigt": True, "aktiv": False}
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    assert response.json()[0]["aktiv"] is False


@pytest.mark.asyncio
async def test_put_excuse_statuses_rejects_duplicate_name(db_session):
    payload = [
        {"name": "Attest", "zaehlt_als_entschuldigt": True, "aktiv": True},
        {"name": "Attest", "zaehlt_als_entschuldigt": False, "aktiv": True},
    ]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/excuse-statuses", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_excuse_statuses.py -v`
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 3: Append excuse-status schemas to `app/schemas/admin.py`**

```python
class ExcuseStatusIn(BaseModel):
    id: int | None = None
    name: str
    long_name: str | None = None
    zaehlt_als_entschuldigt: bool
    aktiv: bool = True


class ExcuseStatusOut(BaseModel):
    id: int
    name: str
    long_name: str | None
    zaehlt_als_entschuldigt: bool
    aktiv: bool
```

- [ ] **Step 4: Create `app/services/excuse_status_service.py`**

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.audit_log import AuditLog
from app.models.excuse_status import ExcuseStatus
from app.schemas.admin import ExcuseStatusIn, ExcuseStatusOut


def _status_out(status_row: ExcuseStatus) -> ExcuseStatusOut:
    return ExcuseStatusOut(
        id=status_row.id,
        name=status_row.name,
        long_name=status_row.long_name,
        zaehlt_als_entschuldigt=status_row.zaehlt_als_entschuldigt,
        aktiv=status_row.aktiv,
    )


async def list_excuse_statuses(db: AsyncSession) -> list[ExcuseStatusOut]:
    result = await db.execute(select(ExcuseStatus).order_by(ExcuseStatus.id))
    return [_status_out(s) for s in result.scalars().all()]


def _validate_payload(payload: list[ExcuseStatusIn]) -> None:
    seen_names: set[str] = set()
    for status_in in payload:
        if not status_in.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if status_in.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {status_in.name}")
        seen_names.add(status_in.name)


async def replace_excuse_statuses(
    db: AsyncSession, payload: list[ExcuseStatusIn], nutzer_id: int
) -> list[ExcuseStatusOut]:
    _validate_payload(payload)

    existing_result = await db.execute(select(ExcuseStatus))
    existing_by_id = {s.id: s for s in existing_result.scalars().all()}

    for status_in in payload:
        if status_in.id is not None and status_in.id not in existing_by_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown excuse status id: {status_in.id}")

    payload_ids = {s.id for s in payload if s.id is not None}
    removed_ids = [sid for sid in existing_by_id if sid not in payload_ids]
    removed_names = [existing_by_id[sid].name for sid in removed_ids]
    for status_id in removed_ids:
        await db.delete(existing_by_id[status_id])

    for status_in in payload:
        if status_in.id is not None:
            status_row = existing_by_id[status_in.id]
            status_row.name = status_in.name
            status_row.long_name = status_in.long_name
            status_row.zaehlt_als_entschuldigt = status_in.zaehlt_als_entschuldigt
            status_row.aktiv = status_in.aktiv
        else:
            db.add(
                ExcuseStatus(
                    name=status_in.name,
                    long_name=status_in.long_name,
                    zaehlt_als_entschuldigt=status_in.zaehlt_als_entschuldigt,
                    aktiv=status_in.aktiv,
                )
            )

    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="admin_excuse_statuses_updated",
            resource_typ="excuse_status",
            details={"anzahl_status": len(payload)},
        )
    )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Kann folgende(n) Entschuldigungsstatus nicht löschen, da bereits verwendet: "
            f"{', '.join(removed_names)}. Stattdessen deaktivieren (aktiv=false).",
        )

    return await list_excuse_statuses(db)
```

- [ ] **Step 5: Append excuse-status routes to `app/api/routes/admin.py`**

Update the schema/service imports at the top of `backend/app/api/routes/admin.py`:

```python
from app.schemas.admin import (
    ExcuseStatusIn,
    ExcuseStatusOut,
    MeasureTypeIn,
    MeasureTypeOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
)
from app.services import excuse_status_service, measure_type_service, threshold_rule_service
```

Add the routes:

```python
@router.get("/excuse-statuses")
async def get_excuse_statuses(db: Annotated[AsyncSession, Depends(get_db)]) -> list[ExcuseStatusOut]:
    return await excuse_status_service.list_excuse_statuses(db)


@router.put("/excuse-statuses")
async def put_excuse_statuses(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[ExcuseStatusIn],
) -> list[ExcuseStatusOut]:
    return await excuse_status_service.replace_excuse_statuses(db, payload, nutzer.id)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_excuse_statuses.py -v`
Expected: 6 passed

- [ ] **Step 7: Run the full suite**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -q`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/excuse_status_service.py backend/app/api/routes/admin.py backend/tests/test_api_admin_excuse_statuses.py
git commit -m "feat: add GET/PUT /admin/excuse-statuses endpoint"
```

---

## Task 5: `GET/PUT /admin/sync-settings`

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py` (rename `_get_or_create_einstellung` → `get_or_create_einstellung`)
- Modify: `backend/app/schemas/admin.py` (append)
- Create: `backend/app/services/sync_settings_service.py`
- Modify: `backend/app/api/routes/admin.py` (append)
- Test: `backend/tests/test_api_admin_sync_settings.py`

**Interfaces:**
- Consumes: Task 1, existing `app.core.scheduler.MAIN_SYNC_JOB_ID`, `app.models.einstellung.Einstellung`, `apscheduler.triggers.cron.CronTrigger`.
- Produces:
  - `app.services.sync_orchestrator.get_or_create_einstellung(db) -> Einstellung` (renamed from private helper, same behavior)
  - `app.schemas.admin.SyncSettingsIn/Out`
  - `app.services.sync_settings_service.get_sync_settings(db) -> SyncSettingsOut`
  - `app.services.sync_settings_service.update_sync_settings(db, scheduler: AsyncIOScheduler, cron_expr: str, nutzer_id: int) -> SyncSettingsOut`

- [ ] **Step 1: Rename the private helper in `sync_orchestrator.py`**

In `backend/app/services/sync_orchestrator.py`, rename `_get_or_create_einstellung` to `get_or_create_einstellung` (drop the leading underscore) at its definition (currently line 24) and at its one call site inside `_run_once` (currently line 50):

```python
async def get_or_create_einstellung(db: AsyncSession) -> Einstellung:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None:
        einstellung = Einstellung()
        db.add(einstellung)
        await db.flush()
    return einstellung
```

```python
        einstellung = await get_or_create_einstellung(db)
```

- [ ] **Step 2: Run the existing sync orchestrator suite to confirm the rename didn't break anything**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_sync_orchestrator.py -v`
Expected: all passed (no test references the old private name directly)

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_api_admin_sync_settings.py`:

```python
import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.scheduler import MAIN_SYNC_JOB_ID, create_scheduler, start_scheduler
from app.main import app
from app.models.audit_log import AuditLog
from app.models.einstellung import Einstellung

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
async def test_get_sync_settings_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/sync-settings", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_sync_settings_returns_defaults_without_existing_einstellung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/sync-settings", headers=HEADERS_SCHULLEITUNG)
    assert response.status_code == 200
    body = response.json()
    assert body["sync_interval_cron"] == "*/30 * * * *"
    assert body["schuljahr_start_cache"] is None
    assert body["letzter_sync_am"] is None


@pytest.mark.asyncio
async def test_put_sync_settings_updates_cron_and_reschedules_live_job(db_session):
    db_session.add(Einstellung(sync_interval_cron="*/30 * * * *"))
    await db_session.commit()

    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/admin/sync-settings", headers=HEADERS_SCHULLEITUNG, json={"sync_interval_cron": "*/15 * * * *"}
            )
        assert response.status_code == 200
        assert response.json()["sync_interval_cron"] == "*/15 * * * *"

        job = scheduler.get_job(MAIN_SYNC_JOB_ID)
        now = datetime.datetime(2026, 1, 1, 10, 3, tzinfo=datetime.timezone.utc)
        assert job.trigger.get_next_fire_time(None, now).minute == 15

        db_result = await db_session.execute(select(Einstellung))
        assert db_result.scalar_one().sync_interval_cron == "*/15 * * * *"

        audit_result = await db_session.execute(
            select(AuditLog).where(AuditLog.aktion == "admin_sync_settings_updated")
        )
        assert audit_result.scalar_one() is not None
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_put_sync_settings_rejects_invalid_cron(db_session):
    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/admin/sync-settings", headers=HEADERS_SCHULLEITUNG, json={"sync_interval_cron": "not-a-cron"}
            )
        assert response.status_code == 422
    finally:
        scheduler.shutdown(wait=False)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_sync_settings.py -v`
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 5: Append sync-settings schemas to `app/schemas/admin.py`**

Add the import at the top of the file and the new classes at the end:

```python
from datetime import date, datetime
```

```python
class SyncSettingsOut(BaseModel):
    sync_interval_cron: str
    schuljahr_start_cache: date | None
    letzter_sync_am: datetime | None


class SyncSettingsIn(BaseModel):
    sync_interval_cron: str
```

- [ ] **Step 6: Create `app/services/sync_settings_service.py`**

```python
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import MAIN_SYNC_JOB_ID
from app.models.audit_log import AuditLog
from app.models.einstellung import Einstellung
from app.schemas.admin import SyncSettingsOut
from app.services.sync_orchestrator import get_or_create_einstellung


def _settings_out(einstellung: Einstellung) -> SyncSettingsOut:
    return SyncSettingsOut(
        sync_interval_cron=einstellung.sync_interval_cron,
        schuljahr_start_cache=einstellung.schuljahr_start_cache,
        letzter_sync_am=einstellung.letzter_sync_am,
    )


async def get_sync_settings(db: AsyncSession) -> SyncSettingsOut:
    einstellung = await get_or_create_einstellung(db)
    await db.commit()
    return _settings_out(einstellung)


async def update_sync_settings(
    db: AsyncSession, scheduler: AsyncIOScheduler, cron_expr: str, nutzer_id: int
) -> SyncSettingsOut:
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid cron expression: {exc}")

    einstellung = await get_or_create_einstellung(db)
    einstellung.sync_interval_cron = cron_expr
    db.add(
        AuditLog(
            user_id=nutzer_id,
            aktion="admin_sync_settings_updated",
            resource_typ="einstellung",
            details={"sync_interval_cron": cron_expr},
        )
    )
    await db.commit()

    scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=trigger)

    return _settings_out(einstellung)
```

- [ ] **Step 7: Append sync-settings routes to `app/api/routes/admin.py`**

Update imports at the top of `backend/app/api/routes/admin.py`:

```python
from fastapi import APIRouter, Depends, Request
```

```python
from app.schemas.admin import (
    ExcuseStatusIn,
    ExcuseStatusOut,
    MeasureTypeIn,
    MeasureTypeOut,
    SyncSettingsIn,
    SyncSettingsOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
)
from app.services import (
    excuse_status_service,
    measure_type_service,
    sync_settings_service,
    threshold_rule_service,
)
```

Add the routes:

```python
@router.get("/sync-settings")
async def get_sync_settings(db: Annotated[AsyncSession, Depends(get_db)]) -> SyncSettingsOut:
    return await sync_settings_service.get_sync_settings(db)


@router.put("/sync-settings")
async def put_sync_settings(
    request: Request,
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: SyncSettingsIn,
) -> SyncSettingsOut:
    scheduler = request.app.state.scheduler
    return await sync_settings_service.update_sync_settings(db, scheduler, payload.sync_interval_cron, nutzer.id)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_sync_settings.py -v`
Expected: 4 passed

- [ ] **Step 9: Run the full suite**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -q`
Expected: all tests pass

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/app/schemas/admin.py backend/app/services/sync_settings_service.py backend/app/api/routes/admin.py backend/tests/test_api_admin_sync_settings.py
git commit -m "feat: add GET/PUT /admin/sync-settings endpoint with live scheduler reschedule"
```

---

## Task 6: `POST /admin/sync-now`

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py` (rename `_run_once` → `run_sync_once`)
- Modify: `backend/app/schemas/admin.py` (append)
- Modify: `backend/app/api/routes/admin.py` (append)
- Test: `backend/tests/test_api_admin_sync_now.py`

**Interfaces:**
- Consumes: Task 1, `app.integrations.webuntis_client.WebUntisError`.
- Produces:
  - `app.services.sync_orchestrator.run_sync_once(db: AsyncSession) -> None` (renamed from private helper, same behavior; `run_full_sync`'s retry loop keeps calling it)
  - `app.schemas.admin.SyncNowOut`

- [ ] **Step 1: Rename `_run_once` to `run_sync_once` in `sync_orchestrator.py`**

In `backend/app/services/sync_orchestrator.py`, rename `_run_once` to `run_sync_once` at its definition (currently line 43) and at its one call site inside `run_full_sync` (currently line 82):

```python
async def run_sync_once(db: AsyncSession) -> None:
```

```python
                await run_sync_once(db)
```

- [ ] **Step 2: Run the existing sync orchestrator suite to confirm the rename didn't break anything**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_sync_orchestrator.py -v`
Expected: all passed

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_api_admin_sync_now.py`:

```python
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisError
from app.main import app
from app.models.audit_log import AuditLog

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
async def test_post_sync_now_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_sync_now_returns_ok_and_logs_audit_entry(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    monkeypatch.setattr(admin_module, "run_sync_once", AsyncMock())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    admin_module.run_sync_once.assert_awaited_once()
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_sync_now_triggered"))
    audit_row = audit_result.scalar_one()
    assert audit_row.details == {"status": "ok"}


@pytest.mark.asyncio
async def test_post_sync_now_returns_502_on_webuntis_error_without_retry(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    mock_run_once = AsyncMock(side_effect=WebUntisError("boom"))
    monkeypatch.setattr(admin_module, "run_sync_once", mock_run_once)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/admin/sync-now", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 502
    mock_run_once.assert_awaited_once()

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_sync_now_triggered"))
    audit_row = audit_result.scalar_one()
    assert audit_row.details == {"status": "fehler"}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_sync_now.py -v`
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 5: Append `SyncNowOut` to `app/schemas/admin.py`**

```python
class SyncNowOut(BaseModel):
    status: str
    abgeschlossen_am: datetime
```

- [ ] **Step 6: Append the sync-now route to `app/api/routes/admin.py`**

Update imports at the top of `backend/app/api/routes/admin.py`:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
```

```python
from app.integrations.webuntis_client import WebUntisError
from app.models.audit_log import AuditLog
from app.schemas.admin import (
    ExcuseStatusIn,
    ExcuseStatusOut,
    MeasureTypeIn,
    MeasureTypeOut,
    SyncNowOut,
    SyncSettingsIn,
    SyncSettingsOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
)
from app.services.sync_orchestrator import run_sync_once
```

Add the route:

```python
@router.post("/sync-now")
async def post_sync_now(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SyncNowOut:
    try:
        await run_sync_once(db)
    except (WebUntisError, OSError) as exc:
        await db.rollback()
        db.add(
            AuditLog(
                user_id=nutzer.id,
                aktion="admin_sync_now_triggered",
                resource_typ="einstellung",
                details={"status": "fehler"},
            )
        )
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Sync fehlgeschlagen: {exc}")

    abgeschlossen_am = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            user_id=nutzer.id,
            aktion="admin_sync_now_triggered",
            resource_typ="einstellung",
            details={"status": "ok"},
        )
    )
    await db.commit()
    return SyncNowOut(status="ok", abgeschlossen_am=abgeschlossen_am)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_api_admin_sync_now.py -v`
Expected: 3 passed

- [ ] **Step 8: Run the full suite**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -q`
Expected: all tests pass, no regressions anywhere in the suite

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/app/schemas/admin.py backend/app/api/routes/admin.py backend/tests/test_api_admin_sync_now.py
git commit -m "feat: add POST /admin/sync-now endpoint for synchronous manual sync trigger"
```

---

## Task 7: Roadmap update and final verification

**Files:**
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: nothing new — this is documentation + a final regression check across everything built in Tasks 1–6.

- [ ] **Step 1: Run the complete backend test suite one more time**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest -q`
Expected: all tests pass (this is the pre-merge gate — if anything fails, fix it before touching `ROADMAP.md`)

- [ ] **Step 2: Update `ROADMAP.md`**

Move the "Backend: REST-API fürs WP-Plugin — Admin-Konfiguration & PDF-Export" line from the "Geplant" table item 1 into a new row in the "Abgeschlossen" table (matching the existing table's style, e.g. the Plan 5 row), noting PDF-Export is still open. In `ROADMAP.md`:

Replace this row content structure — remove the completed part from list item 1 under "## Geplant" and add a new row to the "## Abgeschlossen" table, directly after the Plan 5 row:

```markdown
| **Plan 6** — [Backend REST-API fürs WP-Plugin — Admin-Konfiguration](docs/superpowers/plans/2026-07-27-admin-konfiguration.md) | `GET/PUT /admin/threshold-rules`, `GET/PUT /admin/measure-types` (inkl. neuem `aktiv`-Flag), `GET/PUT /admin/excuse-statuses`, `GET/PUT /admin/sync-settings` (inkl. sofortigem Scheduler-Reschedule), `POST /admin/sync-now` (synchroner Einzel-Sync-Versuch ohne Retry-Loop) — alle nur `schulleitung` (TECH-SPEC.md §3) | PDF-Export |
```

And update the "## Geplant" list so item 1 only mentions PDF-Export:

```markdown
1. **Backend: REST-API fürs WP-Plugin — PDF-Export** — `GET /students/{id}/export.pdf` (TECH-SPEC.md §3). Admin-Konfiguration ist mit Plan 6 fertig.
```

Renumber the remaining list items (Frontend becomes 2, WordPress-Plugin becomes 3, Excuse-Status-Admin-Pflege becomes 4 — unchanged content, since Excuse-Status now has a real admin API from Plan 6, but its dashboard-side data entry UI is still open and depends on the frontend, so it stays as its own roadmap bullet unless already covered by item 2/3, matching the note already on that line).

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: mark Plan 6 (Admin-Konfiguration) as completed in ROADMAP"
```

---

## Self-Review Notes

- **Spec coverage:** All 5 endpoints from the design doc are covered (Task 2: threshold-rules, Task 3: measure-types, Task 4: excuse-statuses, Task 5: sync-settings, Task 6: sync-now). `require_schulleitung` (Task 1) is the shared foundation. Roadmap update (Task 7) closes out the plan per CLAUDE.md's "commit after each plan, update ROADMAP.md" convention.
- **Type/name consistency checked:** `replace_rules`/`replace_measure_types`/`replace_excuse_statuses` all take `(db, payload, nutzer_id)` and return the resource's `Out` list, matching how `app/api/routes/admin.py` calls them across Tasks 2–4. `get_or_create_einstellung` and `run_sync_once` (Tasks 5–6) are consistently referenced by their new public names in both `sync_orchestrator.py`'s own retry loop and the new service/route code — no lingering references to the old private names outside `sync_orchestrator.py` itself (verified via repo-wide grep before writing this plan).
- **No placeholders:** every step above contains complete, runnable code — no "add validation here"-style stubs.
