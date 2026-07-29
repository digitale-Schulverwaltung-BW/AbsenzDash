# WordPress-Plugin — Bereichsdefinition & Rollen-Zuweisung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Plan-8 test-transition role profile fields with a proper WP-admin "Rollen-Zuweisung" listing page, and add a new "Bereichsdefinition" admin page — both backed by new FastAPI admin endpoints — completing Roadmap-Punkt 1.

**Architecture:** Three new/changed backend admin endpoints under the existing `require_schulleitung`-guarded `backend/app/api/routes/admin.py` router, following the established whole-list-replace pattern (`measure_type_service`). Two new plain-PHP + vanilla-JS WordPress admin pages that talk to these endpoints through the existing `Absenzdash_Proxy` reverse proxy (no new WP-side auth mechanism, no build tooling).

**Tech Stack:** FastAPI/SQLAlchemy 2.0 async (backend, unchanged), PHP 7.4+ / vanilla JS (WordPress plugin, unchanged), pytest-asyncio (backend tests).

## Global Constraints

- Commit messages in English (user's global CLAUDE.md).
- German identifiers/comments/UI copy throughout new code (project convention, see `docs/superpowers/specs/2026-07-27-wordpress-plugin-proxy-design.md`).
- No PHPUnit for the WP plugin (YAGNI, established in Plan 8) — PHP tasks verify via `php -l` syntax checks + a manual verification checklist instead of automated tests.
- No new DB tables/columns — `bereich`/`bereich_klasse`/`nutzer_bereich`/`nutzer` schemas are unchanged (see design doc's "kein `quelle`-Flag" decision).
- Design reference: `docs/superpowers/specs/2026-07-29-wordpress-plugin-rollen-bereiche-design.md` (read before starting — has the live WebUntis facts and the rationale for every scope decision below).

---

## Important implementation note not spelled out in the design doc

The design doc's `PUT /admin/bereiche` example payload shows `leiter: [{wp_user_id, email, name}]` (no `rolle`). While turning that into code, a real constraint surfaced: `nutzer.rolle` is `NOT NULL` in the DB (`alembic/versions/ce9c35768e75_...py:25`). A brand-new `nutzer` row created here (get-or-create for a bereichsleiter who never logged in) **must** get a valid `rolle` at creation time — it cannot be left empty as the design text loosely suggested.

**Resolution used throughout this plan:** `leiter` entries carry a `rolle` field (validated against `ROLLEN`). It is used **only when creating** a brand-new `nutzer` row (defaults to `"bereichsleiter"` in the WP-side JS if the person has no `absenzdash_role` yet — see Task 5). For an **existing** `nutzer`, `rolle` from this endpoint is never applied — the design's "keine Rolle wird hier überschrieben" intent is preserved for anyone who already has one, whether that role came from a real login or a previous Bereich assignment.

---

## Task 1: Backend — `GET /admin/webuntis-teachers`

**Files:**
- Create: `backend/app/services/webuntis_teacher_service.py`
- Create: `backend/tests/test_webuntis_teacher_service.py`
- Modify: `backend/app/schemas/admin.py` (append `WebUntisTeacherOut`)
- Modify: `backend/app/api/routes/admin.py` (add imports + route)
- Test: `backend/tests/test_api_admin_webuntis_teachers.py`

**Interfaces:**
- Produces: `webuntis_teacher_service.list_teachers(client: WebUntisClient) -> list[WebUntisTeacherOut]`, `WebUntisTeacherOut(id: int, kuerzel: str)` in `app/schemas/admin.py`. Later tasks do not depend on this, but the WP `class-rollen-seite.php` (Task 4) consumes the route's JSON shape `[{id, kuerzel}]`.

- [ ] **Step 1: Write the failing service test**

Create `backend/tests/test_webuntis_teacher_service.py`:

```python
from unittest.mock import AsyncMock

import pytest

from app.services.webuntis_teacher_service import list_teachers


@pytest.mark.asyncio
async def test_list_teachers_maps_id_and_kuerzel():
    client = AsyncMock()
    client.call.return_value = [{"id": 42, "name": "ABC", "active": True}]

    result = await list_teachers(client)

    assert result == [{"id": 42, "kuerzel": "ABC"}] or (result[0].id == 42 and result[0].kuerzel == "ABC")
    client.call.assert_awaited_once_with("getTeachers", {})


@pytest.mark.asyncio
async def test_list_teachers_sorts_by_kuerzel_and_excludes_inactive():
    client = AsyncMock()
    client.call.return_value = [
        {"id": 2, "name": "MUE", "active": True},
        {"id": 1, "name": "ABC", "active": True},
        {"id": 3, "name": "XYZ", "active": False},
    ]

    result = await list_teachers(client)

    assert [t.kuerzel for t in result] == ["ABC", "MUE"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_webuntis_teacher_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.webuntis_teacher_service'`

- [ ] **Step 3: Add `WebUntisTeacherOut` schema**

In `backend/app/schemas/admin.py`, append at the end of the file:

```python
class WebUntisTeacherOut(BaseModel):
    id: int
    kuerzel: str
```

- [ ] **Step 4: Implement `webuntis_teacher_service.py`**

Create `backend/app/services/webuntis_teacher_service.py`:

```python
from __future__ import annotations

from app.integrations.webuntis_client import WebUntisClient
from app.schemas.admin import WebUntisTeacherOut


async def list_teachers(client: WebUntisClient) -> list[WebUntisTeacherOut]:
    """getTeachers -> {id, kuerzel}[], nur aktive Lehrkraefte, alphabetisch nach Kuerzel.

    `name` ist bei dieser Schule live verifiziert das Lehrerkuerzel (2-9 Buchstaben,
    meist 3), nicht die numerische ID -- siehe Design-Dok Abschnitt "Live-Verifikation".
    """
    rows = await client.call("getTeachers", {})
    teachers = [
        WebUntisTeacherOut(id=row["id"], kuerzel=row["name"]) for row in rows if row.get("active", True)
    ]
    return sorted(teachers, key=lambda t: t.kuerzel)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_webuntis_teacher_service.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Write the failing route test**

Create `backend/tests/test_api_admin_webuntis_teachers.py`:

```python
from httpx import ASGITransport, AsyncClient

import pytest

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisError
from app.main import app

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


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def call(self, method, params):
        assert method == "getTeachers"
        return self._rows


class _FailingClient:
    async def __aenter__(self):
        raise WebUntisError("WebUntis nicht erreichbar")

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_get_webuntis_teachers_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/webuntis-teachers", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_webuntis_teachers_returns_sorted_list(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    monkeypatch.setattr(
        admin_module, "WebUntisClient", lambda settings: _FakeClient([{"id": 1, "name": "ABC", "active": True}])
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/webuntis-teachers", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "kuerzel": "ABC"}]


@pytest.mark.asyncio
async def test_get_webuntis_teachers_returns_502_on_webuntis_error(db_session, monkeypatch):
    import app.api.routes.admin as admin_module

    monkeypatch.setattr(admin_module, "WebUntisClient", lambda settings: _FailingClient())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/webuntis-teachers", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 502
```

- [ ] **Step 7: Run route test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_admin_webuntis_teachers.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 8: Add the route**

In `backend/app/api/routes/admin.py`, add to the imports (after the existing `from app.integrations.webuntis_client import WebUntisError` line, change it to also import `WebUntisClient`, and add the config/service imports):

```python
from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
```

Add near the other schema imports:

```python
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
    WebUntisTeacherOut,
)
```

Add to the services import block:

```python
from app.services import (
    excuse_status_service,
    measure_type_service,
    sync_settings_service,
    threshold_rule_service,
    webuntis_teacher_service,
)
```

Add the route (anywhere after `router = APIRouter(...)`, e.g. directly below the `get_excuse_statuses`/`put_excuse_statuses` pair):

```python
@router.get("/webuntis-teachers")
async def get_webuntis_teachers() -> list[WebUntisTeacherOut]:
    try:
        async with WebUntisClient(settings) as client:
            return await webuntis_teacher_service.list_teachers(client)
    except WebUntisError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"WebUntis nicht erreichbar: {exc}")
```

- [ ] **Step 9: Run route test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api_admin_webuntis_teachers.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass (no regressions in the existing `admin.py` routes)

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/webuntis_teacher_service.py backend/app/api/routes/admin.py backend/tests/test_webuntis_teacher_service.py backend/tests/test_api_admin_webuntis_teachers.py
git commit -m "feat(backend): add GET /admin/webuntis-teachers endpoint"
```

---

## Task 2: Backend — `GET /admin/klassen` + `GET`/`PUT /admin/bereiche`

**Files:**
- Create: `backend/app/services/bereich_service.py`
- Create: `backend/tests/test_bereich_service.py`
- Modify: `backend/app/schemas/admin.py` (append `KlasseOut`, `BereichLeiterIn`, `BereichLeiterOut`, `BereichIn`, `BereichOut`)
- Modify: `backend/app/api/routes/admin.py` (add imports + 3 routes: `GET /klassen`, `GET /bereiche`, `PUT /bereiche`)
- Test: `backend/tests/test_api_admin_bereiche.py`

**Interfaces:**
- Consumes: none from Task 1 (independent slice; both tasks touch `admin.py` but different route groups).
- Produces: `bereich_service.list_klassen(db) -> list[KlasseOut]`, `bereich_service.list_bereiche(db) -> list[BereichOut]`, `bereich_service.replace_bereiche(db, payload: list[BereichIn], admin_nutzer_id: int) -> list[BereichOut]`. Task 3 (`vorschlag-aus-abteilungen`) reuses `KlasseOut`/the `Klasse` query pattern from this file but adds its own function — no direct call dependency.

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/test_bereich_service.py`:

```python
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import BereichIn, BereichLeiterIn
from app.services.bereich_service import list_bereiche, list_klassen, replace_bereiche


@pytest.mark.asyncio
async def test_list_klassen_returns_all_klassen_sorted_by_name(db_session):
    db_session.add_all([Klasse(webuntis_id=2, name="2BFE"), Klasse(webuntis_id=1, name="1BFE")])
    await db_session.commit()

    result = await list_klassen(db_session)

    assert [k.name for k in result] == ["1BFE", "2BFE"]


@pytest.mark.asyncio
async def test_replace_bereiche_creates_bereich_with_klassen(db_session):
    klasse = Klasse(webuntis_id=1, name="1BFE")
    db_session.add(klasse)
    await db_session.commit()

    payload = [BereichIn(name="Mechatronik", klasse_ids=[klasse.id], leiter=[])]
    result = await replace_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].name == "Mechatronik"
    assert result[0].klasse_ids == [klasse.id]

    listed = await list_bereiche(db_session)
    assert listed[0].name == "Mechatronik"


@pytest.mark.asyncio
async def test_replace_bereiche_creates_nutzer_stub_for_new_leiter(db_session):
    payload = [
        BereichIn(
            name="Mechatronik",
            klasse_ids=[],
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]

    result = await replace_bereiche(db_session, payload, admin_nutzer_id=None)

    assert len(result[0].leiter) == 1
    assert result[0].leiter[0].wp_user_id == "99"

    nutzer = (await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "99"))).scalar_one()
    assert nutzer.rolle == "bereichsleiter"
    assert nutzer.email == "a@b.de"


@pytest.mark.asyncio
async def test_replace_bereiche_does_not_overwrite_rolle_of_existing_nutzer(db_session):
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    payload = [
        BereichIn(
            name="Mechatronik",
            klasse_ids=[],
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]
    await replace_bereiche(db_session, payload, admin_nutzer_id=None)

    await db_session.refresh(nutzer)
    assert nutzer.rolle == "schulleitung"


@pytest.mark.asyncio
async def test_replace_bereiche_removes_bereich_not_in_payload(db_session):
    bereich = Bereich(name="Alt")
    db_session.add(bereich)
    await db_session.commit()

    await replace_bereiche(db_session, [], admin_nutzer_id=None)

    remaining = (await db_session.execute(select(Bereich))).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_replace_bereiche_cascades_klassen_and_leiter_on_delete(db_session):
    klasse = Klasse(webuntis_id=1, name="1BFE")
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")
    db_session.add_all([klasse, nutzer])
    await db_session.flush()
    bereich = Bereich(name="Alt")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))
    await db_session.commit()

    await replace_bereiche(db_session, [], admin_nutzer_id=None)

    assert (await db_session.execute(select(bereich_klasse))).all() == []
    assert (await db_session.execute(select(nutzer_bereich))).all() == []
    # der nutzer selbst bleibt bestehen, nur die Zuordnung verschwindet
    assert (await db_session.execute(select(Nutzer).where(Nutzer.id == nutzer.id))).scalar_one() is not None


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_empty_name(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, [BereichIn(name="   ", klasse_ids=[], leiter=[])], admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_duplicate_name(db_session):
    payload = [
        BereichIn(name="Mechatronik", klasse_ids=[], leiter=[]),
        BereichIn(name="Mechatronik", klasse_ids=[], leiter=[]),
    ]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_duplicate_id(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(id=bereich.id, name="A", klasse_ids=[], leiter=[]),
        BereichIn(id=bereich.id, name="B", klasse_ids=[], leiter=[]),
    ]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_unknown_id(db_session):
    payload = [BereichIn(id=999999, name="X", klasse_ids=[], leiter=[])]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_unknown_klasse_id(db_session):
    payload = [BereichIn(name="Mechatronik", klasse_ids=[999999], leiter=[])]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_replace_bereiche_rejects_unknown_rolle(db_session):
    payload = [
        BereichIn(
            name="Mechatronik", klasse_ids=[],
            leiter=[BereichLeiterIn(wp_user_id="1", email="a@b.de", name="A", rolle="oberlehrer")],
        )
    ]
    with pytest.raises(HTTPException) as exc_info:
        await replace_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_bereich_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.bereich_service'`

- [ ] **Step 3: Add schemas**

In `backend/app/schemas/admin.py`, append:

```python
class KlasseOut(BaseModel):
    id: int
    name: str


class BereichLeiterIn(BaseModel):
    wp_user_id: str
    email: str
    name: str
    rolle: str


class BereichLeiterOut(BaseModel):
    nutzer_id: int
    wp_user_id: str
    email: str
    name: str


class BereichIn(BaseModel):
    id: int | None = None
    name: str
    klasse_ids: list[int] = []
    leiter: list[BereichLeiterIn] = []


class BereichOut(BaseModel):
    id: int
    name: str
    klasse_ids: list[int]
    leiter: list[BereichLeiterOut]
```

- [ ] **Step 4: Implement `bereich_service.py`**

Create `backend/app/services/bereich_service.py`:

```python
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import ist_unique_violation
from app.models.audit_log import AuditLog
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import ROLLEN, Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import BereichIn, BereichLeiterOut, BereichOut, KlasseOut


async def list_klassen(db: AsyncSession) -> list[KlasseOut]:
    result = await db.execute(select(Klasse).order_by(Klasse.name))
    return [KlasseOut(id=k.id, name=k.name) for k in result.scalars().all()]


async def _bereich_out(db: AsyncSession, bereich: Bereich) -> BereichOut:
    klasse_ids = (
        await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    leiter_rows = (
        await db.execute(
            select(Nutzer)
            .join(nutzer_bereich, nutzer_bereich.c.nutzer_id == Nutzer.id)
            .where(nutzer_bereich.c.bereich_id == bereich.id)
        )
    ).scalars().all()
    return BereichOut(
        id=bereich.id,
        name=bereich.name,
        klasse_ids=sorted(klasse_ids),
        leiter=[
            BereichLeiterOut(nutzer_id=n.id, wp_user_id=n.wp_user_id, email=n.email, name=n.name)
            for n in leiter_rows
        ],
    )


async def list_bereiche(db: AsyncSession) -> list[BereichOut]:
    result = await db.execute(select(Bereich).order_by(Bereich.name))
    return [await _bereich_out(db, b) for b in result.scalars().all()]


def _validate_payload(payload: list[BereichIn]) -> None:
    seen_ids: set[int] = set()
    for bereich in payload:
        if bereich.id is not None:
            if bereich.id in seen_ids:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {bereich.id}")
            seen_ids.add(bereich.id)

    seen_names: set[str] = set()
    for bereich in payload:
        if not bereich.name.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "name must not be empty")
        if bereich.name in seen_names:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate name: {bereich.name}")
        seen_names.add(bereich.name)

    for bereich in payload:
        for leiter in bereich.leiter:
            if leiter.rolle not in ROLLEN:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rolle: {leiter.rolle}")


async def _validate_klasse_ids_exist(db: AsyncSession, payload: list[BereichIn]) -> None:
    klasse_ids = {kid for bereich in payload for kid in bereich.klasse_ids}
    if not klasse_ids:
        return
    result = await db.execute(select(Klasse.id).where(Klasse.id.in_(klasse_ids)))
    missing = klasse_ids - set(result.scalars().all())
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown klasse_id(s): {sorted(missing)}")


async def _get_or_create_nutzer_stub(db: AsyncSession, wp_user_id: str, email: str, name: str, rolle: str) -> Nutzer:
    """Get-or-Create fuer eine als Bereichsleiter zugewiesene Person.

    Setzt `rolle` NUR bei Neuanlage (nutzer.rolle ist NOT NULL, ein frisch
    zugewiesener Bereichsleiter ohne vorherigen Login braucht einen gueltigen
    Startwert). Eine bereits bestehende `nutzer`-Zeile behaelt ihre Rolle --
    die Rollenzuweisung selbst passiert ausschliesslich ueber die
    Rollen-Zuweisungs-Seite, nicht hier (siehe Plan, "Wichtiger Umsetzungshinweis").
    """
    result = await db.execute(select(Nutzer).where(Nutzer.wp_user_id == wp_user_id))
    nutzer = result.scalar_one_or_none()
    if nutzer is None:
        nutzer = Nutzer(wp_user_id=wp_user_id, email=email, name=name, rolle=rolle)
        db.add(nutzer)
        await db.flush()
    else:
        nutzer.email = email
        nutzer.name = name
    return nutzer


async def replace_bereiche(db: AsyncSession, payload: list[BereichIn], admin_nutzer_id: int) -> list[BereichOut]:
    _validate_payload(payload)
    await _validate_klasse_ids_exist(db, payload)

    existing = (await db.execute(select(Bereich))).scalars().all()
    by_id = {b.id: b for b in existing}
    payload_ids = {b.id for b in payload if b.id is not None}

    unknown_ids = payload_ids - set(by_id.keys())
    if unknown_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown id(s): {sorted(unknown_ids)}")

    try:
        for bereich in existing:
            if bereich.id not in payload_ids:
                await db.delete(bereich)
        await db.flush()

        result_bereiche: list[Bereich] = []
        for item in payload:
            if item.id is not None:
                bereich = by_id[item.id]
                bereich.name = item.name
            else:
                bereich = Bereich(name=item.name)
                db.add(bereich)
                await db.flush()
            result_bereiche.append(bereich)

            await db.execute(delete(bereich_klasse).where(bereich_klasse.c.bereich_id == bereich.id))
            for klasse_id in item.klasse_ids:
                await db.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_id))

            await db.execute(delete(nutzer_bereich).where(nutzer_bereich.c.bereich_id == bereich.id))
            for leiter in item.leiter:
                nutzer = await _get_or_create_nutzer_stub(db, leiter.wp_user_id, leiter.email, leiter.name, leiter.rolle)
                await db.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))

        db.add(
            AuditLog(
                user_id=admin_nutzer_id,
                aktion="admin_bereiche_updated",
                resource_typ="bereich",
                details={"anzahl": len(payload)},
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ist_unique_violation(exc):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Name bereits vergeben — bitte einen eindeutigen Namen für den Bereich wählen.",
            )
        raise

    return [await _bereich_out(db, b) for b in result_bereiche]
```

- [ ] **Step 5: Run service tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bereich_service.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Write the failing route tests**

Create `backend/tests/test_api_admin_bereiche.py`:

```python
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from app.models.klasse import Klasse

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
async def test_get_klassen_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/klassen", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_klassen_returns_all_klassen(db_session):
    db_session.add(Klasse(webuntis_id=1, name="1BFE"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/klassen", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json() == [{"id": 1, "name": "1BFE"}] or response.json()[0]["name"] == "1BFE"


@pytest.mark.asyncio
async def test_get_bereiche_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_put_bereiche_creates_and_logs_audit(db_session):
    payload = [{"name": "Mechatronik", "klasse_ids": [], "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Mechatronik"

    audit = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_bereiche_updated"))
    assert audit.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_bereiche_rejects_unknown_klasse_id(db_session):
    payload = [{"name": "Mechatronik", "klasse_ids": [999999], "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422
```

- [ ] **Step 7: Run route tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api_admin_bereiche.py -v`
Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 8: Add the routes**

In `backend/app/api/routes/admin.py`, extend the schema import block from Task 1 to also include:

```python
from app.schemas.admin import (
    BereichIn,
    BereichOut,
    ExcuseStatusIn,
    ExcuseStatusOut,
    KlasseOut,
    MeasureTypeIn,
    MeasureTypeOut,
    SyncNowOut,
    SyncSettingsIn,
    SyncSettingsOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
    WebUntisTeacherOut,
)
```

Extend the services import block to also include `bereich_service`:

```python
from app.services import (
    bereich_service,
    excuse_status_service,
    measure_type_service,
    sync_settings_service,
    threshold_rule_service,
    webuntis_teacher_service,
)
```

Add the three routes (anywhere after `router = APIRouter(...)`):

```python
@router.get("/klassen")
async def get_klassen(db: Annotated[AsyncSession, Depends(get_db)]) -> list[KlasseOut]:
    return await bereich_service.list_klassen(db)


@router.get("/bereiche")
async def get_bereiche(db: Annotated[AsyncSession, Depends(get_db)]) -> list[BereichOut]:
    return await bereich_service.list_bereiche(db)


@router.put("/bereiche")
async def put_bereiche(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[BereichIn],
) -> list[BereichOut]:
    return await bereich_service.replace_bereiche(db, payload, nutzer.id)
```

- [ ] **Step 9: Run route tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api_admin_bereiche.py -v`
Expected: PASS (5 tests)

- [ ] **Step 10: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/bereich_service.py backend/app/api/routes/admin.py backend/tests/test_bereich_service.py backend/tests/test_api_admin_bereiche.py
git commit -m "feat(backend): add GET /admin/klassen and GET/PUT /admin/bereiche endpoints"
```

---

## Task 3: Backend — `GET /admin/bereiche/vorschlag-aus-abteilungen`

**Files:**
- Modify: `backend/app/services/bereich_service.py` (add `vorschlag_aus_abteilungen`)
- Modify: `backend/app/schemas/admin.py` (append `BereichVorschlagOut`)
- Modify: `backend/app/api/routes/admin.py` (add route + import)
- Modify: `backend/tests/test_bereich_service.py` (add tests)
- Test: `backend/tests/test_api_admin_bereiche.py` (add route-level test)

**Interfaces:**
- Consumes: `Abteilung` model (`app/models/abteilung.py`, fields `name`/`long_name`), `Klasse.abteilung_id` (both pre-existing, from Plan 3).
- Produces: `bereich_service.vorschlag_aus_abteilungen(db) -> list[BereichVorschlagOut]`, `BereichVorschlagOut(name: str, klasse_ids: list[int])`. Consumed by `bereiche-seite.js` in Task 5 as `GET /admin/bereiche/vorschlag-aus-abteilungen` → `[{name, klasse_ids}]`.

- [ ] **Step 1: Write the failing service tests**

Append to `backend/tests/test_bereich_service.py`:

```python
from app.models.abteilung import Abteilung
from app.services.bereich_service import vorschlag_aus_abteilungen


@pytest.mark.asyncio
async def test_vorschlag_aus_abteilungen_maps_long_name_and_klassen(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    klasse_zugehoerig = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id)
    klasse_fremd = Klasse(webuntis_id=2, name="2BFE")
    db_session.add_all([klasse_zugehoerig, klasse_fremd])
    await db_session.commit()

    result = await vorschlag_aus_abteilungen(db_session)

    assert len(result) == 1
    assert result[0].name == "Mechatronik"
    assert result[0].klasse_ids == [klasse_zugehoerig.id]


@pytest.mark.asyncio
async def test_vorschlag_aus_abteilungen_falls_back_to_name_without_long_name(db_session):
    db_session.add(Abteilung(webuntis_id=59, name="B-IE", long_name=None))
    await db_session.commit()

    result = await vorschlag_aus_abteilungen(db_session)

    assert result[0].name == "B-IE"
    assert result[0].klasse_ids == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_bereich_service.py -k vorschlag -v`
Expected: FAIL with `ImportError: cannot import name 'vorschlag_aus_abteilungen'`

- [ ] **Step 3: Add `BereichVorschlagOut` schema**

In `backend/app/schemas/admin.py`, append:

```python
class BereichVorschlagOut(BaseModel):
    name: str
    klasse_ids: list[int]
```

- [ ] **Step 4: Implement `vorschlag_aus_abteilungen`**

In `backend/app/services/bereich_service.py`, add to the imports:

```python
from app.models.abteilung import Abteilung
from app.schemas.admin import BereichVorschlagOut
```

(merge into the existing `from app.schemas.admin import ...` line rather than duplicating it)

Append the function:

```python
async def vorschlag_aus_abteilungen(db: AsyncSession) -> list[BereichVorschlagOut]:
    """Einmal-Vorschlag zur Vorbefuellung der Bereichsdefinition (1:1 pro Abteilung).

    Kein Schreibzugriff, kein `quelle`-Flag -- reiner Formular-Vorschlag, siehe Design-Dok
    Abschnitt 'GET /admin/bereiche/vorschlag-aus-abteilungen'.
    """
    abteilungen = (await db.execute(select(Abteilung).order_by(Abteilung.name))).scalars().all()
    klassen = (await db.execute(select(Klasse))).scalars().all()

    klassen_by_abteilung: dict[int, list[int]] = {}
    for klasse in klassen:
        if klasse.abteilung_id is not None:
            klassen_by_abteilung.setdefault(klasse.abteilung_id, []).append(klasse.id)

    return [
        BereichVorschlagOut(
            name=abteilung.long_name or abteilung.name,
            klasse_ids=sorted(klassen_by_abteilung.get(abteilung.id, [])),
        )
        for abteilung in abteilungen
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bereich_service.py -v`
Expected: PASS (13 tests)

- [ ] **Step 6: Write the failing route test**

Append to `backend/tests/test_api_admin_bereiche.py`:

```python
from app.models.abteilung import Abteilung


@pytest.mark.asyncio
async def test_get_vorschlag_aus_abteilungen_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche/vorschlag-aus-abteilungen", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_vorschlag_aus_abteilungen_returns_one_per_abteilung(db_session):
    db_session.add(Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche/vorschlag-aus-abteilungen", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    assert response.json() == [{"name": "Mechatronik", "klasse_ids": []}]
```

- [ ] **Step 7: Run route test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api_admin_bereiche.py -k vorschlag -v`
Expected: FAIL with 404

- [ ] **Step 8: Add the route**

In `backend/app/api/routes/admin.py`, add `BereichVorschlagOut` to the schema import block, then add the route:

```python
@router.get("/bereiche/vorschlag-aus-abteilungen")
async def get_bereiche_vorschlag(db: Annotated[AsyncSession, Depends(get_db)]) -> list[BereichVorschlagOut]:
    return await bereich_service.vorschlag_aus_abteilungen(db)
```

- [ ] **Step 9: Run route test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api_admin_bereiche.py -v`
Expected: PASS (7 tests)

- [ ] **Step 10: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/services/bereich_service.py backend/app/api/routes/admin.py backend/tests/test_bereich_service.py backend/tests/test_api_admin_bereiche.py
git commit -m "feat(backend): add GET /admin/bereiche/vorschlag-aus-abteilungen endpoint"
```

---

## Task 4: WP-Plugin — Rollen-Zuweisungs-Seite (ersetzt `class-benutzerprofil.php`)

**Files:**
- Create: `wordpress-plugin/absenzdash/includes/class-rollen-seite.php`
- Create: `wordpress-plugin/absenzdash/assets/admin/rollen-seite.js`
- Delete: `wordpress-plugin/absenzdash/includes/class-benutzerprofil.php`
- Modify: `wordpress-plugin/absenzdash/absenzdash.php` (swap the require/instantiation)

**Interfaces:**
- Consumes: `GET /admin/webuntis-teachers` (Task 1) → `[{id, kuerzel}]`, via the existing `Absenzdash_Proxy` route `/wp-json/absenzdash/v1/api/admin/webuntis-teachers`.
- Produces: nothing consumed by later tasks (Task 5 is independent).

- [ ] **Step 1: Remove the old profile-fields class**

```bash
git rm wordpress-plugin/absenzdash/includes/class-benutzerprofil.php
```

- [ ] **Step 2: Create the admin page class**

Create `wordpress-plugin/absenzdash/includes/class-rollen-seite.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Rollen_Seite {

	const ROLLEN = array( 'klassenlehrkraft', 'bereichsleiter', 'schulleitung' );

	public function __construct() {
		add_action( 'admin_menu', array( $this, 'registriere_seite' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_assets' ) );
		add_action( 'admin_post_absenzdash_rollen_speichern', array( $this, 'speichere_rollen' ) );
	}

	public function registriere_seite(): void {
		add_options_page(
			'AbsenzDash-Rollen',
			'AbsenzDash-Rollen',
			'manage_options',
			'absenzdash-rollen',
			array( $this, 'render_seite' )
		);
	}

	public function enqueue_assets( string $hook_suffix ): void {
		if ( 'settings_page_absenzdash-rollen' !== $hook_suffix ) {
			return;
		}
		wp_enqueue_script(
			'absenzdash-rollen-seite',
			ABSENZDASH_PLUGIN_URL . 'assets/admin/rollen-seite.js',
			array(),
			ABSENZDASH_VERSION,
			true
		);
		wp_localize_script(
			'absenzdash-rollen-seite',
			'absenzdashRollenConfig',
			array(
				'restUrl' => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'   => wp_create_nonce( 'wp_rest' ),
			)
		);
	}

	private function get_nutzer_zeilen(): array {
		$zeilen = array();
		foreach ( get_users() as $user ) {
			$zeilen[] = array(
				'id'                   => $user->ID,
				'name'                 => $user->display_name,
				'email'                => $user->user_email,
				'rolle'                => get_user_meta( $user->ID, 'absenzdash_role', true ),
				'webuntis_code'        => get_user_meta( $user->ID, 'absenzdash_webuntis_code', true ),
				'absenzflow_vorschlag' => get_user_meta( $user->ID, 'absenzflow_webuntis_code', true ),
			);
		}
		return $zeilen;
	}

	public function render_seite(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1>AbsenzDash — Rollen-Zuweisung</h1>
			<p>Rolle und WebUntis-Kürzel je Nutzer. Die Kürzel-Auswahl wird live aus WebUntis geladen; ein
				bereits bei VertretungsFlow hinterlegtes Kürzel wird als Vorschlag vorausgewählt, muss aber
				hier bestätigt werden.</p>
			<div id="absenzdash-fehler" style="color:#b32d2e;"></div>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<?php wp_nonce_field( 'absenzdash_rollen_speichern' ); ?>
				<input type="hidden" name="action" value="absenzdash_rollen_speichern" />
				<table class="widefat">
					<thead>
						<tr>
							<th>Nutzer</th>
							<th>E-Mail</th>
							<th>Rolle</th>
							<th>WebUntis-Kürzel</th>
						</tr>
					</thead>
					<tbody>
						<?php foreach ( $this->get_nutzer_zeilen() as $zeile ) : ?>
							<tr>
								<td><?php echo esc_html( $zeile['name'] ); ?></td>
								<td><?php echo esc_html( $zeile['email'] ); ?></td>
								<td>
									<select name="rolle[<?php echo esc_attr( $zeile['id'] ); ?>]">
										<option value="">(keine)</option>
										<?php foreach ( self::ROLLEN as $moegliche_rolle ) : ?>
											<option value="<?php echo esc_attr( $moegliche_rolle ); ?>" <?php selected( $zeile['rolle'], $moegliche_rolle ); ?>>
												<?php echo esc_html( $moegliche_rolle ); ?>
											</option>
										<?php endforeach; ?>
									</select>
								</td>
								<td>
									<select name="webuntis_code[<?php echo esc_attr( $zeile['id'] ); ?>]"
										class="absenzdash-kuerzel-auswahl"
										data-vorschlag="<?php echo esc_attr( $zeile['absenzflow_vorschlag'] ); ?>"
										data-aktuell="<?php echo esc_attr( $zeile['webuntis_code'] ); ?>">
										<option value="">(keins)</option>
									</select>
								</td>
							</tr>
						<?php endforeach; ?>
					</tbody>
				</table>
				<?php submit_button( 'Speichern' ); ?>
			</form>
		</div>
		<?php
	}

	public function speichere_rollen(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( 'Keine Berechtigung.' );
		}
		check_admin_referer( 'absenzdash_rollen_speichern' );

		$rollen  = isset( $_POST['rolle'] ) ? wp_unslash( $_POST['rolle'] ) : array();
		$kuerzel = isset( $_POST['webuntis_code'] ) ? wp_unslash( $_POST['webuntis_code'] ) : array();

		foreach ( get_users() as $user ) {
			$user_id = $user->ID;

			$rolle = isset( $rollen[ $user_id ] ) ? sanitize_text_field( $rollen[ $user_id ] ) : '';
			if ( in_array( $rolle, self::ROLLEN, true ) ) {
				update_user_meta( $user_id, 'absenzdash_role', $rolle );
			} else {
				delete_user_meta( $user_id, 'absenzdash_role' );
			}

			$code = isset( $kuerzel[ $user_id ] ) ? sanitize_text_field( $kuerzel[ $user_id ] ) : '';
			if ( '' !== $code && ctype_digit( $code ) ) {
				update_user_meta( $user_id, 'absenzdash_webuntis_code', $code );
			} else {
				delete_user_meta( $user_id, 'absenzdash_webuntis_code' );
			}
		}

		wp_safe_redirect( add_query_arg( 'absenzdash_gespeichert', '1', wp_get_referer() ) );
		exit;
	}
}
```

Note: the `<select>` options' `value` is populated by JS with the **numeric WebUntis-ID** (not the kürzel text) — this keeps `absenzdash_webuntis_code` and the `X-WordPress-WebUntis-Code` header / `int(...)` parsing in `backend/app/api/deps.py:56` completely unchanged. The kürzel is only ever the visible label, never the stored value. `ctype_digit` guards against a hand-crafted POST bypassing the `<select>`.

- [ ] **Step 3: Verify PHP syntax**

Run: `php -l wordpress-plugin/absenzdash/includes/class-rollen-seite.php`
Expected: `No syntax errors detected`

- [ ] **Step 4: Create the admin JS**

Create `wordpress-plugin/absenzdash/assets/admin/rollen-seite.js`:

```js
(function () {
	function ladeUndBefuelle() {
		var fehlerBox = document.getElementById('absenzdash-fehler');
		fetch(absenzdashRollenConfig.restUrl + '/admin/webuntis-teachers', {
			headers: { 'X-WP-Nonce': absenzdashRollenConfig.nonce }
		})
			.then(function (antwort) {
				if (!antwort.ok) {
					throw new Error('HTTP ' + antwort.status);
				}
				return antwort.json();
			})
			.then(function (lehrkraefte) {
				document.querySelectorAll('.absenzdash-kuerzel-auswahl').forEach(function (auswahl) {
					var aktuell = auswahl.dataset.aktuell || '';
					var vorschlagKuerzel = (auswahl.dataset.vorschlag || '').toUpperCase();
					var vorschlagId = '';

					lehrkraefte.forEach(function (lehrkraft) {
						var option = document.createElement('option');
						option.value = String(lehrkraft.id);
						option.textContent = lehrkraft.kuerzel;
						auswahl.appendChild(option);
						if (!vorschlagId && lehrkraft.kuerzel.toUpperCase() === vorschlagKuerzel) {
							vorschlagId = String(lehrkraft.id);
						}
					});

					if (aktuell) {
						auswahl.value = aktuell;
					} else if (vorschlagId) {
						auswahl.value = vorschlagId;
					}
				});
			})
			.catch(function (fehler) {
				fehlerBox.textContent = 'WebUntis-Kürzelliste konnte nicht geladen werden: ' + fehler.message;
			});
	}

	document.addEventListener('DOMContentLoaded', ladeUndBefuelle);
})();
```

- [ ] **Step 5: Wire into plugin bootstrap**

In `wordpress-plugin/absenzdash/absenzdash.php`, replace:

```php
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-benutzerprofil.php';
```

with:

```php
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-rollen-seite.php';
```

and replace:

```php
		new Absenzdash_Benutzerprofil();
```

with:

```php
		new Absenzdash_Rollen_Seite();
```

- [ ] **Step 6: Verify bootstrap PHP syntax**

Run: `php -l wordpress-plugin/absenzdash/absenzdash.php`
Expected: `No syntax errors detected`

- [ ] **Step 7: Manual verification checklist (document in commit message body, run against staging when available)**

- Open "Einstellungen → AbsenzDash-Rollen" as a WP administrator: table lists every WP user.
- Kürzel-Dropdowns populate asynchronously from WebUntis; a user with a pre-existing `absenzflow_webuntis_code` shows that kürzel pre-selected (but unsaved until "Speichern").
- Assign a role + kürzel to a test user, save, reload the page: both persist.
- Stop the backend (or break the shared secret) and reload: `#absenzdash-fehler` shows a readable message instead of a silent blank dropdown.
- Confirm `wordpress-plugin/absenzdash/includes/class-benutzerprofil.php` no longer exists and the old per-user profile fields are gone from `wp-admin/user-edit.php`.

- [ ] **Step 8: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-rollen-seite.php wordpress-plugin/absenzdash/assets/admin/rollen-seite.js wordpress-plugin/absenzdash/absenzdash.php
git commit -m "feat(wp-plugin): replace profile-field role assignment with a listing admin page"
```

---

## Task 5: WP-Plugin — Bereichsdefinition-Seite

**Files:**
- Create: `wordpress-plugin/absenzdash/includes/class-bereiche-seite.php`
- Create: `wordpress-plugin/absenzdash/assets/admin/bereiche-seite.js`
- Modify: `wordpress-plugin/absenzdash/absenzdash.php` (require + instantiate)

**Interfaces:**
- Consumes: `GET/PUT /admin/bereiche` and `GET /admin/klassen` (Task 2), `GET /admin/bereiche/vorschlag-aus-abteilungen` (Task 3) — all via the proxy, plus WP's own `get_users()`/`absenzdash_role` meta (localized directly, no extra fetch needed).

- [ ] **Step 1: Create the admin page class**

Create `wordpress-plugin/absenzdash/includes/class-bereiche-seite.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Bereiche_Seite {

	public function __construct() {
		add_action( 'admin_menu', array( $this, 'registriere_seite' ) );
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_assets' ) );
	}

	public function registriere_seite(): void {
		add_options_page(
			'AbsenzDash-Bereiche',
			'AbsenzDash-Bereiche',
			'manage_options',
			'absenzdash-bereiche',
			array( $this, 'render_seite' )
		);
	}

	private function get_wp_nutzer_liste(): array {
		$liste = array();
		foreach ( get_users() as $user ) {
			$liste[] = array(
				'wp_user_id' => (string) $user->ID,
				'email'      => $user->user_email,
				'name'       => $user->display_name,
				'rolle'      => get_user_meta( $user->ID, 'absenzdash_role', true ),
			);
		}
		return $liste;
	}

	public function enqueue_assets( string $hook_suffix ): void {
		if ( 'settings_page_absenzdash-bereiche' !== $hook_suffix ) {
			return;
		}
		wp_enqueue_script(
			'absenzdash-bereiche-seite',
			ABSENZDASH_PLUGIN_URL . 'assets/admin/bereiche-seite.js',
			array(),
			ABSENZDASH_VERSION,
			true
		);
		wp_localize_script(
			'absenzdash-bereiche-seite',
			'absenzdashBereicheConfig',
			array(
				'restUrl'  => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'    => wp_create_nonce( 'wp_rest' ),
				'wpNutzer' => $this->get_wp_nutzer_liste(),
			)
		);
	}

	public function render_seite(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1>AbsenzDash — Bereichsdefinition</h1>
			<div id="absenzdash-bereiche-fehler" style="color:#b32d2e;"></div>
			<p>
				<button type="button" id="absenzdash-vorbefuellen" class="button">Aus WebUntis-Abteilungen vorbefüllen</button>
				<button type="button" id="absenzdash-bereich-hinzufuegen" class="button">Bereich hinzufügen</button>
			</p>
			<div id="absenzdash-bereiche-liste"></div>
			<p><button type="button" id="absenzdash-bereiche-speichern" class="button button-primary">Speichern</button></p>
		</div>
		<?php
	}
}
```

- [ ] **Step 2: Verify PHP syntax**

Run: `php -l wordpress-plugin/absenzdash/includes/class-bereiche-seite.php`
Expected: `No syntax errors detected`

- [ ] **Step 3: Create the admin JS**

Create `wordpress-plugin/absenzdash/assets/admin/bereiche-seite.js`:

```js
(function () {
	var zustand = { bereiche: [], klassen: [] };

	function element(tag, attrs, kinder) {
		var el = document.createElement(tag);
		Object.keys(attrs || {}).forEach(function (key) {
			if (key === 'text') {
				el.textContent = attrs[key];
			} else {
				el.setAttribute(key, attrs[key]);
			}
		});
		(kinder || []).forEach(function (kind) { el.appendChild(kind); });
		return el;
	}

	function mehrfachauswahl(eintraege, wertFeld, labelFn, ausgewaehlteWerte, cssKlasse) {
		var select = element('select', { multiple: 'multiple', class: cssKlasse, size: '6' });
		eintraege.forEach(function (eintrag) {
			var wert = String(eintrag[wertFeld]);
			var option = element('option', { value: wert, text: labelFn(eintrag) });
			if (ausgewaehlteWerte.indexOf(wert) !== -1) {
				option.selected = true;
			}
			select.appendChild(option);
		});
		return select;
	}

	function ausgewaehlteWerte(select) {
		return Array.prototype.slice.call(select.selectedOptions).map(function (option) { return option.value; });
	}

	function bereichZeileRendern(bereich) {
		var nameInput = element('input', { type: 'text', class: 'absenzdash-bereich-name', value: bereich.name || '' });

		var klassenAuswahl = mehrfachauswahl(
			zustand.klassen, 'id', function (k) { return k.name; },
			(bereich.klasse_ids || []).map(String), 'absenzdash-bereich-klassen'
		);
		var leiterAuswahl = mehrfachauswahl(
			absenzdashBereicheConfig.wpNutzer, 'wp_user_id',
			function (n) { return n.name + ' (' + (n.rolle || 'keine Rolle') + ')'; },
			(bereich.leiter || []).map(function (l) { return l.wp_user_id; }),
			'absenzdash-bereich-leiter'
		);

		var entfernenButton = element('button', { type: 'button', class: 'button absenzdash-bereich-entfernen', text: 'Entfernen' });
		entfernenButton.addEventListener('click', function () { zeile.remove(); });

		var zeile = element('div', { class: 'absenzdash-bereich-zeile', style: 'border:1px solid #ccd0d4; padding:10px; margin-bottom:10px;' }, [
			element('label', { text: 'Name: ' }), nameInput,
			element('br', {}),
			element('label', { text: 'Klassen: ' }), klassenAuswahl,
			element('br', {}),
			element('label', { text: 'Bereichsleiter: ' }), leiterAuswahl,
			element('br', {}),
			entfernenButton
		]);
		zeile.dataset.bereichId = bereich.id != null ? String(bereich.id) : '';

		return zeile;
	}

	function bereicheNeuRendern() {
		var liste = document.getElementById('absenzdash-bereiche-liste');
		liste.innerHTML = '';
		zustand.bereiche.forEach(function (bereich) {
			liste.appendChild(bereichZeileRendern(bereich));
		});
	}

	function fehlerAnzeigen(nachricht) {
		document.getElementById('absenzdash-bereiche-fehler').textContent = nachricht;
	}

	function laden() {
		Promise.all([
			fetch(absenzdashBereicheConfig.restUrl + '/admin/bereiche', {
				headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce }
			}).then(function (r) {
				if (!r.ok) { throw new Error('Bereiche laden fehlgeschlagen (HTTP ' + r.status + ')'); }
				return r.json();
			}),
			fetch(absenzdashBereicheConfig.restUrl + '/admin/klassen', {
				headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce }
			}).then(function (r) {
				if (!r.ok) { throw new Error('Klassenliste laden fehlgeschlagen (HTTP ' + r.status + ')'); }
				return r.json();
			})
		]).then(function (ergebnisse) {
			zustand.bereiche = ergebnisse[0];
			zustand.klassen = ergebnisse[1];
			bereicheNeuRendern();
		}).catch(function (fehler) {
			fehlerAnzeigen(fehler.message);
		});
	}

	function vorbefuellen() {
		fetch(absenzdashBereicheConfig.restUrl + '/admin/bereiche/vorschlag-aus-abteilungen', {
			headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce }
		})
			.then(function (r) {
				if (!r.ok) { throw new Error('Vorschlag laden fehlgeschlagen (HTTP ' + r.status + ')'); }
				return r.json();
			})
			.then(function (vorschlaege) {
				vorschlaege.forEach(function (vorschlag) {
					zustand.bereiche.push({ id: null, name: vorschlag.name, klasse_ids: vorschlag.klasse_ids, leiter: [] });
				});
				bereicheNeuRendern();
			})
			.catch(function (fehler) {
				fehlerAnzeigen(fehler.message);
			});
	}

	function bereichHinzufuegen() {
		zustand.bereiche.push({ id: null, name: '', klasse_ids: [], leiter: [] });
		bereicheNeuRendern();
	}

	function ausZeilenLesen() {
		var zeilen = document.querySelectorAll('.absenzdash-bereich-zeile');
		return Array.prototype.map.call(zeilen, function (zeile) {
			var name = zeile.querySelector('.absenzdash-bereich-name').value;
			var klasseIds = ausgewaehlteWerte(zeile.querySelector('.absenzdash-bereich-klassen')).map(Number);
			var leiterIds = ausgewaehlteWerte(zeile.querySelector('.absenzdash-bereich-leiter'));
			var leiter = leiterIds.map(function (wpUserId) {
				var nutzer = absenzdashBereicheConfig.wpNutzer.filter(function (n) { return n.wp_user_id === wpUserId; })[0];
				return {
					wp_user_id: nutzer.wp_user_id,
					email: nutzer.email,
					name: nutzer.name,
					rolle: nutzer.rolle || 'bereichsleiter'
				};
			});
			var payload = { name: name, klasse_ids: klasseIds, leiter: leiter };
			var id = zeile.dataset.bereichId;
			if (id) { payload.id = Number(id); }
			return payload;
		});
	}

	function speichern() {
		fetch(absenzdashBereicheConfig.restUrl + '/admin/bereiche', {
			method: 'PUT',
			headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce, 'Content-Type': 'application/json' },
			body: JSON.stringify(ausZeilenLesen())
		})
			.then(function (r) {
				return r.json().then(function (body) { return { ok: r.ok, body: body }; });
			})
			.then(function (ergebnis) {
				if (!ergebnis.ok) {
					throw new Error(ergebnis.body.detail || 'Speichern fehlgeschlagen');
				}
				zustand.bereiche = ergebnis.body;
				bereicheNeuRendern();
				fehlerAnzeigen('');
			})
			.catch(function (fehler) {
				fehlerAnzeigen(fehler.message);
			});
	}

	document.addEventListener('DOMContentLoaded', function () {
		laden();
		document.getElementById('absenzdash-vorbefuellen').addEventListener('click', vorbefuellen);
		document.getElementById('absenzdash-bereich-hinzufuegen').addEventListener('click', bereichHinzufuegen);
		document.getElementById('absenzdash-bereiche-speichern').addEventListener('click', speichern);
	});
})();
```

Note on the `rolle: nutzer.rolle || 'bereichsleiter'` fallback: this is the client-side half of the NOT-NULL fix described at the top of this plan. It only affects the value sent to the backend for a brand-new `nutzer` row (see Task 2's `_get_or_create_nutzer_stub`); it does **not** write anything back to WordPress's own `absenzdash_role` meta. A person assigned as Bereichsleiter here before ever visiting the Rollen-Zuweisungs-Seite will resolve correctly in backend scope logic (`resolve_bereich_scope`), but still cannot log into the dashboard themselves until an admin also gives them a WP-side role via Task 4's page — document this in Step 5's checklist.

- [ ] **Step 4: Wire into plugin bootstrap**

In `wordpress-plugin/absenzdash/absenzdash.php`, add after the `class-rollen-seite.php` require:

```php
require_once ABSENZDASH_PLUGIN_DIR . 'includes/class-bereiche-seite.php';
```

and after `new Absenzdash_Rollen_Seite();`:

```php
		new Absenzdash_Bereiche_Seite();
```

- [ ] **Step 5: Verify bootstrap PHP syntax and manual verification checklist**

Run: `php -l wordpress-plugin/absenzdash/includes/class-bereiche-seite.php && php -l wordpress-plugin/absenzdash/absenzdash.php`
Expected: `No syntax errors detected` for both

Manual checklist (document in commit message body, run against staging when available):
- Open "Einstellungen → AbsenzDash-Bereiche": page loads with an empty list (fresh install) or existing bereiche.
- Click "Aus WebUntis-Abteilungen vorbefüllen": one draft row per WebUntis-Abteilung appears (not saved yet).
- Edit a draft's name, remove a class, add a Bereichsleiter, click "Speichern": reload the page, changes persisted.
- Click "Bereich hinzufügen", fill in a brand-new person (not yet in `nutzer`) as leiter, save: confirm in the backend DB that a `nutzer` row was created with `rolle='bereichsleiter'`.
- Click "Entfernen" on a row, save: the bereich and its class/leiter associations are gone after reload.
- Stop the backend and click "Speichern": `#absenzdash-bereiche-fehler` shows a readable message.

- [ ] **Step 6: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-bereiche-seite.php wordpress-plugin/absenzdash/assets/admin/bereiche-seite.js wordpress-plugin/absenzdash/absenzdash.php
git commit -m "feat(wp-plugin): add Bereichsdefinition admin page with WebUntis-Abteilungen prefill"
```

---

## Task 6: Documentation updates

**Files:**
- Modify: `SPECS.md` (§2, precision about class-teacher assignment)
- Modify: `ROADMAP.md` (move Punkt 1 to "Abgeschlossen"; add the deferred Abteilungsleitungs-Rolle backlog item)
- Modify: `docs/deployment.md` (replace the profile-fields setup instructions with the new admin pages)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Precise SPECS.md §2**

In `SPECS.md`, find the line in section 2 ("Architektur") reading:

```
- **Frontend-Admin (WP-Backend):** Im Admin-Backend von WordPress werden ausschließlich organisatorische Grundeinstellungen gepflegt: Zuordnung Nutzer → Rolle (Klassenlehrkraft/Bereichsleiter/Schulleitung), zusätzliche Klassenlehrkraft-Zuordnungen über die WebUntis-Seed-Daten hinaus, sowie die Bereichsdefinition (welche Klassen gehören zu welchem Bereich, wer ist Bereichsleiter). Keine fachliche Konfiguration (Schwellwerte etc.) hier.
```

Replace with:

```
- **Frontend-Admin (WP-Backend):** Im Admin-Backend von WordPress werden ausschließlich organisatorische Grundeinstellungen gepflegt: Zuordnung Nutzer → Rolle (Klassenlehrkraft/Bereichsleiter/Schulleitung) samt WebUntis-Kürzel, sowie die Bereichsdefinition (welche Klassen gehören zu welchem Bereich, wer ist Bereichsleiter). Die Klassenlehrkraft-Zuordnung selbst kommt vollständig aus WebUntis (bis zu zwei Klassenlehrkräfte je Klasse, `teacher1`/`teacher2`, siehe TECH-SPEC.md Abschnitt 1.2) — eine manuelle Zusatz-Zuordnung darüber hinaus wird bewusst nicht angeboten (Umsetzungsentscheidung Roadmap-Punkt 1, siehe dortiges Design-Dok). Keine fachliche Konfiguration (Schwellwerte etc.) hier.
```

- [ ] **Step 2: Update ROADMAP.md**

In `ROADMAP.md`, move the Plan-11 row into the "Abgeschlossen" table (append as the last row before the table ends), matching the existing row format:

```
| **Plan 11** — [WordPress-Plugin — Bereichsdefinition & Rollen-Zuweisung](docs/superpowers/plans/2026-07-29-wordpress-plugin-rollen-bereiche.md) | Rollen-Zuweisungs-Listenseite (ersetzt Plan-8-Profilfelder) inkl. live geladener WebUntis-Kürzelliste und VertretungsFlow-Vorschlagsübernahme; Bereichsdefinition-Admin-Seite (`bereich`/`bereich_klasse`/`nutzer_bereich`) mit Get-or-Create für noch nie eingeloggte Bereichsleiter; Backend-Endpunkte `GET /admin/webuntis-teachers`, `GET /admin/klassen`, `GET`/`PUT /admin/bereiche`, `GET /admin/bereiche/vorschlag-aus-abteilungen` (TECH-SPEC.md §3 erweitert) | manuelle Zusatz-Klassenlehrkraft-Zuordnung (bewusst nicht gebaut, siehe Design-Dok), Abteilungsleitungs-Rolle (zurückgestellt, siehe "Geplant") |
```

Remove the now-completed "1. **WordPress-Plugin (Verbleibende Teile)**" bullet from the "Geplant" list and renumber the remaining bullets (old 2 → 1, old 3 → 2). Add a new bullet at the end of "Geplant":

```
3. **Abteilungsleitungs-Rolle** — vierte Rolle neben Klassenlehrkraft/Bereichsleiter/Schulleitung, angelehnt an die WebUntis-Abteilungen (`abteilung`-Tabelle, seit Plan 3 für Schwellwert-Regel-Geltungsbereiche genutzt). Kein Zusatzfeld, sondern struktureller Umbau: neuer Rollen-Enum-Wert, neue `nutzer_abteilung`-Zuordnungstabelle, dritte Scope-Ebene in `resolve_scope`/`resolve_bereich_scope`, Erweiterung der Eskalations-Engine/Mailer-Empfänger-Auflösung (`schwellwert_stufe.empfaenger_rollen`), Revision von SPECS.md §3 ("Dreistufige Hierarchie"). Eigenes Brainstorming nötig, zurückgestellt während Plan 11 (siehe [Design-Dok](docs/superpowers/specs/2026-07-29-wordpress-plugin-rollen-bereiche-design.md) Abschnitt "Zurückgestellt: Abteilungsleitungs-Rolle").
```

- [ ] **Step 3: Update docs/deployment.md**

Read `docs/deployment.md` in full first (its Plan-8 section documents the old profile-fields workflow) and replace the "Setzen der minimalen Profilfelder pro Test-Nutzer" instructions with a short section describing the two new admin pages:

```
### Rollen-Zuweisung & Bereichsdefinition

Seit Plan 11 (`docs/superpowers/plans/2026-07-29-wordpress-plugin-rollen-bereiche.md`) ersetzen zwei
dedizierte Admin-Seiten die vorherigen Profilfelder:

- **Einstellungen → AbsenzDash-Rollen**: Rolle (Klassenlehrkraft/Bereichsleiter/Schulleitung) und
  WebUntis-Kürzel je Nutzer, als Listenansicht statt Einzel-Profilbearbeitung. Die Kürzelliste wird
  live aus WebUntis geladen (`GET /admin/webuntis-teachers`) — Backend muss dafür erreichbar sein.
- **Einstellungen → AbsenzDash-Bereiche**: Bereiche anlegen, Klassen zuordnen, Bereichsleiter
  zuweisen. Der Button "Aus WebUntis-Abteilungen vorbefüllen" schlägt einen Bereich pro
  WebUntis-Abteilung vor (reiner Formular-Vorschlag, keine laufende Synchronisation).

Beide Seiten sind nur für WP-Administratoren (`manage_options`) sichtbar und benötigen eine
funktionierende Backend-Verbindung (Options-Seite, siehe oben).
```

- [ ] **Step 4: Commit**

```bash
git add SPECS.md ROADMAP.md docs/deployment.md
git commit -m "docs: update SPECS/ROADMAP/deployment for Plan 11 (Bereiche & Rollen)"
```

---

## Self-Review

**Spec coverage:**
- Rollen-Zuweisungs-Listenseite (ersetzt Profilfelder) → Task 4. ✅
- WebUntis-Kürzel-Autocomplete + VertretungsFlow-Vorschlag → Task 4 (`rollen-seite.js`). ✅
- Bereichsdefinition-Seite (CRUD Bereich/Klassen/Leiter) → Task 5. ✅
- `GET /admin/webuntis-teachers` → Task 1. ✅
- `GET /admin/klassen` → Task 2. ✅
- `GET`/`PUT /admin/bereiche` inkl. Get-or-Create für neue Bereichsleiter → Task 2. ✅
- `GET /admin/bereiche/vorschlag-aus-abteilungen` → Task 3. ✅
- Bewusster Verzicht auf manuelle Klassenlehrkraft-Zuordnung, SPECS.md-Präzisierung → Task 6. ✅
- ROADMAP.md-Pflege (Abschluss + neuer Abteilungsleitungs-Punkt) → Task 6. ✅
- `docs/deployment.md`-Pflege → Task 6. ✅

**Placeholder scan:** no TBD/TODO; every step has runnable code or an exact shell command.

**Type consistency:** `WebUntisTeacherOut(id, kuerzel)`, `KlasseOut(id, name)`, `BereichLeiterIn(wp_user_id, email, name, rolle)`, `BereichLeiterOut(nutzer_id, wp_user_id, email, name)`, `BereichIn(id, name, klasse_ids, leiter)`, `BereichOut(id, name, klasse_ids, leiter)`, `BereichVorschlagOut(name, klasse_ids)` are used identically across Tasks 1–3 and in the WP JS payload shapes in Tasks 4–5.

---

Plan complete and saved to `docs/superpowers/plans/2026-07-29-wordpress-plugin-rollen-bereiche.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
