# Frontend-Grundgerüst (Navigation & Landing-Dashboard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein WP-Plugin-eingebettetes React/TS-SPA-Grundgerüst mit WP-Nonce-Auth, Routing, rollenabhängiger hierarchischer Bereich-/Klasse-Navigation und einer Landing-Page mit Kennzahlen-Dashboard (Ø Fehltage/-stunden, Klassenbuch-Einträge, Maßnahmen-Anzahl, jeweils mit Vergleichsbalken).

**Architecture:** Neues Backend-Router-Paar (`/dashboard/nav-options`, `/dashboard/stats`) liefert rollenscope-geprüfte Navigationsoptionen und aggregierte Kennzahlen. Ein neues `frontend/`-Vite-Projekt (React/TS, react-router, react-query, recharts) baut direkt nach `wordpress-plugin/absenzdash/assets/spa/`; das WP-Plugin lädt im Dev-Modus den Vite-Dev-Server (HMR), sonst die gebauten Dateien.

**Tech Stack:** Backend: FastAPI, SQLAlchemy 2.0 async, Pydantic (bestehender Stack). Frontend: Vite, React 18, TypeScript, react-router-dom, @tanstack/react-query, recharts, Vitest + React Testing Library.

## Global Constraints

- Design-Referenz: [docs/superpowers/specs/2026-07-28-frontend-grundgeruest-design.md](../specs/2026-07-28-frontend-grundgeruest-design.md) — bei Widersprüchen zwischen Plan und Design gewinnt das Design; im Zweifel dort nachlesen.
- Backend-Code folgt bestehenden Konventionen: `from __future__ import annotations`, SQLAlchemy 2.0 `Mapped[]`-Stil, deutsche Feldnamen in Modellen/Services, englische Request-Schema-Namen (siehe TECH-SPEC.md §2 Fußnote zu `schemas/students.py`).
- Commit-Messages auf Englisch (siehe `~/.claude/CLAUDE.md`).
- Nach Abschluss jeder Aufgabe committen (siehe `CLAUDE.md` Workflow-Vorgabe).
- Kein Gauge-/Zeiger-Widget, keine Schülerliste/-Detail, kein Admin-Bereich, kein PDF-Export in diesem Plan (siehe Design-Dokument Abschnitt 7 "Bewusst nicht enthalten").

---

## Backend: Dashboard-Endpunkte

### Task 1: `resolve_bereich_scope`-Hilfsfunktion

**Files:**
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_api_deps_scope.py`

**Interfaces:**
- Produces: `async def resolve_bereich_scope(db: AsyncSession, nutzer: Nutzer) -> set[int] | None` — `None` = alle Bereiche (schulleitung), `set[int]` = zugeordnete Bereich-IDs (bereichsleiter aus `nutzer_bereich`, leere Menge für klassenlehrkraft, da diese Rolle keine Bereiche hat).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_deps_scope.py` (add `resolve_bereich_scope` to the existing import from `app.api.deps`):

```python
from app.api.deps import get_scoped_schueler, resolve_bereich_scope, resolve_scope
```

```python
@pytest.mark.asyncio
async def test_resolve_bereich_scope_returns_none_for_schulleitung(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    assert await resolve_bereich_scope(db_session, nutzer) is None


@pytest.mark.asyncio
async def test_resolve_bereich_scope_returns_assigned_bereiche_for_bereichsleiter(db_session):
    bereich_a = Bereich(name="Ausbildung")
    bereich_b = Bereich(name="Berufsschule")
    db_session.add_all([bereich_a, bereich_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich_a.id))
    await db_session.commit()

    scope = await resolve_bereich_scope(db_session, nutzer)
    assert scope == {bereich_a.id}


@pytest.mark.asyncio
async def test_resolve_bereich_scope_returns_empty_set_for_klassenlehrkraft(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.commit()

    assert await resolve_bereich_scope(db_session, nutzer) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_api_deps_scope.py -v -k resolve_bereich_scope`
Expected: FAIL with `ImportError: cannot import name 'resolve_bereich_scope'`

- [ ] **Step 3: Implement `resolve_bereich_scope`**

Add to `backend/app/api/deps.py`, directly after the existing `resolve_scope` function:

```python
async def resolve_bereich_scope(db: AsyncSession, nutzer: Nutzer) -> set[int] | None:
    """Ermittelt die fuer den Nutzer sichtbaren bereich_id's (analog resolve_scope fuer Klassen).

    None bedeutet "alle Bereiche" (schulleitung). Klassenlehrkraft hat keinen Bereichs-Bezug,
    liefert also immer eine leere Menge.
    """
    if nutzer.rolle == "schulleitung":
        return None
    if nutzer.rolle == "bereichsleiter":
        result = await db.execute(
            select(nutzer_bereich.c.bereich_id).where(nutzer_bereich.c.nutzer_id == nutzer.id)
        )
        return set(result.scalars().all())
    return set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_api_deps_scope.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps.py backend/tests/test_api_deps_scope.py
git commit -m "feat: add resolve_bereich_scope helper for dashboard scope checks"
```

---

### Task 2: `GET /dashboard/nav-options`

**Files:**
- Create: `backend/app/schemas/dashboard.py`
- Create: `backend/app/services/dashboard_query.py`
- Create: `backend/app/api/routes/dashboard.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_dashboard_query.py`
- Test: `backend/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: `resolve_scope`, `resolve_bereich_scope`, `get_wordpress_proxy_nutzer` from `app.api.deps` (Task 1 and pre-existing).
- Produces: `NavBereichOut`, `NavKlasseOut`, `NavOptionsOut` (Pydantic schemas in `app.schemas.dashboard`); `async def get_nav_options(db: AsyncSession, nutzer: Nutzer) -> NavOptionsOut` in `app.services.dashboard_query`; `GET /dashboard/nav-options` route.

- [ ] **Step 1: Write the schema**

Create `backend/app/schemas/dashboard.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class NavBereichOut(BaseModel):
    id: int
    name: str


class NavKlasseOut(BaseModel):
    id: int
    name: str
    bereich_id: int | None


class NavOptionsOut(BaseModel):
    bereiche: list[NavBereichOut]
    klassen: list[NavKlasseOut]


class StatsOwn(BaseModel):
    anzahl_schueler: int
    avg_fehltage: float
    avg_fehlstunden: float
    avg_klassenbuch: float
    anzahl_klassenbuch: int
    anzahl_massnahmen: int


class StatsVergleichEintrag(StatsOwn):
    id: int
    name: str


class StatsContext(BaseModel):
    bereich_id: int | None
    bereich_name: str | None
    klasse_id: int | None
    klasse_name: str | None


StatsLevel = Literal["schule", "eigene_bereiche", "bereich", "eigene_klassen", "klasse"]


class StatsOut(BaseModel):
    level: StatsLevel
    context: StatsContext
    own: StatsOwn
    vergleich: list[StatsVergleichEintrag]
```

- [ ] **Step 2: Write the failing service test**

Create `backend/tests/test_dashboard_query.py`:

```python
import pytest

from app.api.deps import resolve_bereich_scope, resolve_scope
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.services import dashboard_query


@pytest.mark.asyncio
async def test_get_nav_options_for_schulleitung_returns_all_bereiche_and_klassen(db_session):
    bereich = Bereich(name="Ausbildung")
    klasse_a = Klasse(webuntis_id=1, name="AME56")
    klasse_b = Klasse(webuntis_id=2, name="BME12")
    db_session.add_all([bereich, klasse_a, klasse_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert {b.name for b in options.bereiche} == {"Ausbildung"}
    assert {k.name for k in options.klassen} == {"AME56", "BME12"}
    klasse_map = {k.id: k.bereich_id for k in options.klassen}
    assert klasse_map[klasse_a.id] == bereich.id
    assert klasse_map[klasse_b.id] is None


@pytest.mark.asyncio
async def test_get_nav_options_for_klassenlehrkraft_returns_only_own_klassen_and_no_bereiche(db_session):
    klasse_a = Klasse(webuntis_id=1, name="AME56")
    klasse_b = Klasse(webuntis_id=2, name="BME12")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert options.bereiche == []
    assert [k.id for k in options.klassen] == [klasse_a.id]


@pytest.mark.asyncio
async def test_get_nav_options_for_bereichsleiter_returns_own_bereiche_and_their_klassen(db_session):
    bereich = Bereich(name="Ausbildung")
    andere_bereich = Bereich(name="Berufsschule")
    klasse_a = Klasse(webuntis_id=1, name="AME56")
    klasse_b = Klasse(webuntis_id=2, name="BME12")
    db_session.add_all([bereich, andere_bereich, klasse_a, klasse_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_a.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=andere_bereich.id, klasse_id=klasse_b.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert [b.id for b in options.bereiche] == [bereich.id]
    assert [k.id for k in options.klassen] == [klasse_a.id]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_dashboard_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.dashboard_query'`

- [ ] **Step 4: Implement `get_nav_options`**

Create `backend/app/services/dashboard_query.py`:

```python
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import resolve_bereich_scope, resolve_scope
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.schemas.dashboard import NavBereichOut, NavKlasseOut, NavOptionsOut


async def get_nav_options(db: AsyncSession, nutzer: Nutzer) -> NavOptionsOut:
    bereich_scope = await resolve_bereich_scope(db, nutzer)
    klasse_scope = await resolve_scope(db, nutzer)

    if bereich_scope is not None and not bereich_scope:
        bereiche = []
    else:
        query = select(Bereich).order_by(Bereich.name)
        if bereich_scope is not None:
            query = query.where(Bereich.id.in_(bereich_scope))
        bereiche = (await db.execute(query)).scalars().all()

    if klasse_scope is not None and not klasse_scope:
        klassen = []
    else:
        query = select(Klasse).order_by(Klasse.name)
        if klasse_scope is not None:
            query = query.where(Klasse.id.in_(klasse_scope))
        klassen = (await db.execute(query)).scalars().all()

    klasse_bereich_map = dict(
        (
            await db.execute(
                select(bereich_klasse.c.klasse_id, func.min(bereich_klasse.c.bereich_id)).group_by(
                    bereich_klasse.c.klasse_id
                )
            )
        ).all()
    )

    return NavOptionsOut(
        bereiche=[NavBereichOut(id=b.id, name=b.name) for b in bereiche],
        klassen=[
            NavKlasseOut(id=k.id, name=k.name, bereich_id=klasse_bereich_map.get(k.id)) for k in klassen
        ],
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_dashboard_query.py -v`
Expected: PASS

- [ ] **Step 6: Write the failing endpoint test**

Create `backend/tests/test_api_dashboard.py`:

```python
from httpx import ASGITransport, AsyncClient
import pytest

from app.core.config import settings
from app.main import app
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse

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


@pytest.mark.asyncio
async def test_get_nav_options_returns_only_scoped_klassen(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard/nav-options", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["bereiche"] == []
    assert [k["id"] for k in body["klassen"]] == [klasse.id]
```

- [ ] **Step 7: Run the endpoint test to verify it fails**

Run: `cd backend && pytest tests/test_api_dashboard.py -v`
Expected: FAIL with `404 Not Found` (route not registered yet), assertion error on status code

- [ ] **Step 8: Implement the route and wire it up**

Create `backend/app/api/routes/dashboard.py`:

```python
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_wordpress_proxy_nutzer
from app.core.database import get_db
from app.models.nutzer import Nutzer
from app.schemas.dashboard import NavOptionsOut, StatsOut
from app.services import dashboard_query

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/nav-options")
async def get_nav_options(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NavOptionsOut:
    return await dashboard_query.get_nav_options(db, nutzer)


@router.get("/stats")
async def get_stats(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    bereich_id: int | None = None,
    klasse_id: int | None = None,
) -> StatsOut:
    return await dashboard_query.get_dashboard_stats(db, nutzer, bereich_id, klasse_id)
```

Note: `get_dashboard_stats` does not exist yet — it is implemented in Task 3. This file will not import successfully until Task 3 is done; that is expected and resolved within this same working session before moving on.

Modify `backend/app/main.py` — add the import and `include_router` call:

```python
from app.api.routes.students import router as students_router
from app.api.routes.admin import router as admin_router
from app.api.routes.dashboard import router as dashboard_router
```

```python
app.include_router(students_router)
app.include_router(admin_router)
app.include_router(dashboard_router)
```

- [ ] **Step 9: Placeholder for `get_dashboard_stats` so the app can import**

To keep this task's test runnable before Task 3 lands, add a minimal placeholder to `backend/app/services/dashboard_query.py` (Task 3 will replace this function body entirely):

```python
from app.models.nutzer import Nutzer
from app.schemas.dashboard import StatsContext, StatsOut, StatsOwn


async def get_dashboard_stats(
    db, nutzer: Nutzer, bereich_id: int | None, klasse_id: int | None
) -> StatsOut:
    raise NotImplementedError("implemented in Task 3")
```

Add `AsyncSession` typing to the `db` parameter and the necessary imports at the top of the file (merge with the existing imports from Step 4 rather than duplicating them).

- [ ] **Step 10: Run the endpoint test to verify it passes**

Run: `cd backend && pytest tests/test_api_dashboard.py -v`
Expected: PASS (this test only exercises `/dashboard/nav-options`, not `/dashboard/stats`)

- [ ] **Step 11: Commit**

```bash
git add backend/app/schemas/dashboard.py backend/app/services/dashboard_query.py backend/app/api/routes/dashboard.py backend/app/main.py backend/tests/test_dashboard_query.py backend/tests/test_api_dashboard.py
git commit -m "feat: add GET /dashboard/nav-options endpoint"
```

---

### Task 3: `GET /dashboard/stats` aggregation and endpoint

**Files:**
- Modify: `backend/app/services/dashboard_query.py`
- Modify: `backend/tests/test_dashboard_query.py`
- Modify: `backend/tests/test_api_dashboard.py`

**Interfaces:**
- Consumes: `StatsOut`, `StatsOwn`, `StatsVergleichEintrag`, `StatsContext` (Task 2); `resolve_scope`, `resolve_bereich_scope` (Task 1); `Fehlzeit`, `KlassenbuchEintrag`, `Massnahme`, `Schueler`, `Einstellung`, `Klasse`, `Bereich`, `bereich_klasse` models.
- Produces: `async def get_dashboard_stats(db: AsyncSession, nutzer: Nutzer, bereich_id: int | None, klasse_id: int | None) -> StatsOut` — replaces the Task 2 placeholder.

**Level resolution rules** (see design doc §3 and the confirmed navigation table):
- `klasse_id` given → validate against `resolve_scope`, level = `"klasse"`.
- else `bereich_id` given → validate against `resolve_bereich_scope`, level = `"bereich"`.
- else (neither given), by role:
  - `schulleitung` → level = `"schule"` (all klassen, `vergleich` = one entry per Bereich).
  - `bereichsleiter` with exactly 1 assigned Bereich → level = `"bereich"` for that Bereich (implicit default, mirrors the frontend's "dropdown hidden when only one option" rule).
  - `bereichsleiter` with 0 or >1 assigned Bereiche → level = `"eigene_bereiche"` (`vergleich` = one entry per own Bereich).
  - `klassenlehrkraft` with exactly 1 assigned Klasse → level = `"klasse"` for that Klasse.
  - `klassenlehrkraft` with 0 or >1 assigned Klassen → level = `"eigene_klassen"` (`vergleich` = one entry per own Klasse).

- [ ] **Step 1: Write the failing tests**

Replace the placeholder-adjacent content in `backend/tests/test_dashboard_query.py` by adding these imports and tests (append to the existing file; keep the Task 2 tests and imports):

```python
import datetime

from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp
from app.models.schueler import Schueler
```

```python
async def _seed_schueler_mit_fehlzeit(db_session, klasse, schuljahr_start):
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=schuljahr_start + datetime.timedelta(days=1),
            start_zeit=0,
            end_zeit=2359,
        )
    )
    await db_session.commit()
    return schueler


@pytest.mark.asyncio
async def test_get_dashboard_stats_for_single_klasse_averages_over_active_students_only(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    await _seed_schueler_mit_fehlzeit(db_session, klasse, schuljahr_start)
    inaktiver_schueler = Schueler(
        externe_id="ext-2", vorname="Erika", nachname="Beispiel", klasse_id=klasse.id, aktiv=False
    )
    db_session.add(inaktiver_schueler)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.level == "klasse"
    assert stats.context.klasse_id == klasse.id
    assert stats.context.klasse_name == "AME56"
    assert stats.own.anzahl_schueler == 1
    assert stats.own.avg_fehltage == 1.0
    assert stats.vergleich == []


@pytest.mark.asyncio
async def test_get_dashboard_stats_excludes_fehlzeiten_before_schuljahr_start(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id,
            typ="tag",
            datum=schuljahr_start - datetime.timedelta(days=1),
            start_zeit=0,
            end_zeit=2359,
        )
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.own.avg_fehltage == 0.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_counts_klassenbuch_and_massnahmen(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    kategorie = ClassregCategory(name="stören")
    massnahmen_typ = MassnahmenTyp(name="Gespräch")
    erfasser = Nutzer(wp_user_id="lehrer1", email="l@b.de", name="Lehrkraft", rolle="klassenlehrkraft")
    db_session.add_all([schueler, kategorie, massnahmen_typ, erfasser])
    await db_session.flush()
    db_session.add(
        KlassenbuchEintrag(
            webuntis_id=1,
            schueler_id=schueler.id,
            kategorie_id=kategorie.id,
            datum=schuljahr_start + datetime.timedelta(days=1),
        )
    )
    db_session.add(
        Massnahme(
            schueler_id=schueler.id,
            massnahmen_typ_id=massnahmen_typ.id,
            datum=schuljahr_start + datetime.timedelta(days=1),
            erfasst_von_nutzer_id=erfasser.id,
        )
    )
    await db_session.commit()
    schulleitung = Nutzer(wp_user_id="admin1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(schulleitung)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, schulleitung, None, klasse.id)

    assert stats.own.anzahl_klassenbuch == 1
    assert stats.own.avg_klassenbuch == 1.0
    assert stats.own.anzahl_massnahmen == 1


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_compares_bereiche(db_session):
    bereich_a = Bereich(name="Ausbildung")
    bereich_b = Bereich(name="Berufsschule")
    klasse_a = Klasse(webuntis_id=1, name="AME56")
    klasse_b = Klasse(webuntis_id=2, name="BME12")
    db_session.add_all([bereich_a, bereich_b, klasse_a, klasse_b])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_a.id, klasse_id=klasse_a.id))
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich_b.id, klasse_id=klasse_b.id))
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    await _seed_schueler_mit_fehlzeit(db_session, klasse_a, schuljahr_start)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "schule"
    vergleich_by_name = {v.name: v for v in stats.vergleich}
    assert vergleich_by_name["Ausbildung"].avg_fehltage == 1.0
    assert vergleich_by_name["Berufsschule"].avg_fehltage == 0.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_defaults_bereichsleiter_with_single_bereich_to_that_bereich(db_session):
    bereich = Bereich(name="Ausbildung")
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add_all([bereich, klasse])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "bereich"
    assert stats.context.bereich_id == bereich.id


@pytest.mark.asyncio
async def test_get_dashboard_stats_klassenlehrkraft_with_multiple_klassen_compares_own_klassen(db_session):
    klasse_a = Klasse(webuntis_id=1, name="AME56")
    klasse_b = Klasse(webuntis_id=2, name="AME57")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add_all(
        [
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"),
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_b.id, quelle="webuntis_seed"),
        ]
    )
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    assert stats.level == "eigene_klassen"
    assert {v.name for v in stats.vergleich} == {"AME56", "AME57"}


@pytest.mark.asyncio
async def test_get_dashboard_stats_rejects_bereich_id_for_klassenlehrkraft(db_session):
    from fastapi import HTTPException

    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_query.get_dashboard_stats(db_session, nutzer, 1, None)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_dashboard_stats_404s_for_klasse_outside_scope(db_session):
    from fastapi import HTTPException

    klasse_a = Klasse(webuntis_id=1, name="AME56")
    klasse_b = Klasse(webuntis_id=2, name="AME57")
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_a.id, quelle="webuntis_seed"))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse_b.id)
    assert exc_info.value.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_dashboard_query.py -v`
Expected: FAIL with `NotImplementedError: implemented in Task 3` (from the Task 2 placeholder)

- [ ] **Step 3: Implement `get_dashboard_stats`**

Replace the placeholder in `backend/app/services/dashboard_query.py` — the file's final content:

```python
from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import resolve_bereich_scope, resolve_scope
from app.models.bereich import Bereich, bereich_klasse
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.massnahme import Massnahme
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.schemas.dashboard import (
    NavBereichOut,
    NavKlasseOut,
    NavOptionsOut,
    StatsContext,
    StatsOut,
    StatsOwn,
    StatsVergleichEintrag,
)


async def get_nav_options(db: AsyncSession, nutzer: Nutzer) -> NavOptionsOut:
    bereich_scope = await resolve_bereich_scope(db, nutzer)
    klasse_scope = await resolve_scope(db, nutzer)

    if bereich_scope is not None and not bereich_scope:
        bereiche = []
    else:
        query = select(Bereich).order_by(Bereich.name)
        if bereich_scope is not None:
            query = query.where(Bereich.id.in_(bereich_scope))
        bereiche = (await db.execute(query)).scalars().all()

    if klasse_scope is not None and not klasse_scope:
        klassen = []
    else:
        query = select(Klasse).order_by(Klasse.name)
        if klasse_scope is not None:
            query = query.where(Klasse.id.in_(klasse_scope))
        klassen = (await db.execute(query)).scalars().all()

    klasse_bereich_map = dict(
        (
            await db.execute(
                select(bereich_klasse.c.klasse_id, func.min(bereich_klasse.c.bereich_id)).group_by(
                    bereich_klasse.c.klasse_id
                )
            )
        ).all()
    )

    return NavOptionsOut(
        bereiche=[NavBereichOut(id=b.id, name=b.name) for b in bereiche],
        klassen=[
            NavKlasseOut(id=k.id, name=k.name, bereich_id=klasse_bereich_map.get(k.id)) for k in klassen
        ],
    )


async def _get_schuljahr_start(db: AsyncSession) -> date | None:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    return einstellung.schuljahr_start_cache if einstellung else None


async def _aggregate(db: AsyncSession, klasse_ids: list[int] | None, schuljahr_start: date | None) -> StatsOwn:
    leer = StatsOwn(
        anzahl_schueler=0,
        avg_fehltage=0.0,
        avg_fehlstunden=0.0,
        avg_klassenbuch=0.0,
        anzahl_klassenbuch=0,
        anzahl_massnahmen=0,
    )
    if klasse_ids is not None and not klasse_ids:
        return leer

    schueler_query = select(Schueler.id).where(Schueler.aktiv.is_(True))
    if klasse_ids is not None:
        schueler_query = schueler_query.where(Schueler.klasse_id.in_(klasse_ids))
    schueler_ids = (await db.execute(schueler_query)).scalars().all()
    anzahl_schueler = len(schueler_ids)
    if anzahl_schueler == 0:
        return leer

    datumsfilter = [] if schuljahr_start is None else [schuljahr_start]

    fehltage = (
        await db.execute(
            select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "tag",
                Fehlzeit.invalid.is_(False),
                *([Fehlzeit.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    fehlstunden = (
        await db.execute(
            select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "stunde",
                Fehlzeit.invalid.is_(False),
                *([Fehlzeit.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    klassenbuch = (
        await db.execute(
            select(func.count()).select_from(KlassenbuchEintrag).where(
                KlassenbuchEintrag.schueler_id.in_(schueler_ids),
                *([KlassenbuchEintrag.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    massnahmen = (
        await db.execute(
            select(func.count()).select_from(Massnahme).where(
                Massnahme.schueler_id.in_(schueler_ids),
                *([Massnahme.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()

    return StatsOwn(
        anzahl_schueler=anzahl_schueler,
        avg_fehltage=round(fehltage / anzahl_schueler, 2),
        avg_fehlstunden=round(fehlstunden / anzahl_schueler, 2),
        avg_klassenbuch=round(klassenbuch / anzahl_schueler, 2),
        anzahl_klassenbuch=klassenbuch,
        anzahl_massnahmen=massnahmen,
    )


def _leerer_context() -> StatsContext:
    return StatsContext(bereich_id=None, bereich_name=None, klasse_id=None, klasse_name=None)


async def _stats_for_bereich(db: AsyncSession, bereich: Bereich, schuljahr_start: date | None) -> StatsOut:
    klassen = (
        await db.execute(
            select(Klasse)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
    ).scalars().all()
    own = await _aggregate(db, [k.id for k in klassen], schuljahr_start)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(
        level="bereich",
        context=StatsContext(bereich_id=bereich.id, bereich_name=bereich.name, klasse_id=None, klasse_name=None),
        own=own,
        vergleich=vergleich,
    )


async def _stats_schulweit(db: AsyncSession, schuljahr_start: date | None) -> StatsOut:
    own = await _aggregate(db, None, schuljahr_start)
    bereiche = (await db.execute(select(Bereich).order_by(Bereich.name))).scalars().all()
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        stats = await _aggregate(db, list(klasse_ids), schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    return StatsOut(level="schule", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_bereiche(db: AsyncSession, bereich_ids: set[int], schuljahr_start: date | None) -> StatsOut:
    bereiche = (
        await db.execute(select(Bereich).where(Bereich.id.in_(bereich_ids)).order_by(Bereich.name))
    ).scalars().all()
    alle_klasse_ids: list[int] = []
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        alle_klasse_ids.extend(klasse_ids)
        stats = await _aggregate(db, list(klasse_ids), schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    own = await _aggregate(db, alle_klasse_ids, schuljahr_start)
    return StatsOut(level="eigene_bereiche", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_klassen(db: AsyncSession, klasse_ids: set[int], schuljahr_start: date | None) -> StatsOut:
    klassen = (
        await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)).order_by(Klasse.name))
    ).scalars().all()
    own = await _aggregate(db, list(klasse_ids), schuljahr_start)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], schuljahr_start)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(level="eigene_klassen", context=_leerer_context(), own=own, vergleich=vergleich)


async def get_dashboard_stats(
    db: AsyncSession, nutzer: Nutzer, bereich_id: int | None, klasse_id: int | None
) -> StatsOut:
    if nutzer.rolle == "klassenlehrkraft" and bereich_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="klassenlehrkraft cannot pass bereich_id"
        )

    schuljahr_start = await _get_schuljahr_start(db)

    if klasse_id is not None:
        klasse_scope = await resolve_scope(db, nutzer)
        if klasse_scope is not None and klasse_id not in klasse_scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        own = await _aggregate(db, [klasse.id], schuljahr_start)
        return StatsOut(
            level="klasse",
            context=StatsContext(bereich_id=None, bereich_name=None, klasse_id=klasse.id, klasse_name=klasse.name),
            own=own,
            vergleich=[],
        )

    if bereich_id is not None:
        bereich_scope = await resolve_bereich_scope(db, nutzer)
        if bereich_scope is not None and bereich_id not in bereich_scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bereich nicht gefunden")
        bereich = (await db.execute(select(Bereich).where(Bereich.id == bereich_id))).scalar_one_or_none()
        if bereich is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bereich nicht gefunden")
        return await _stats_for_bereich(db, bereich, schuljahr_start)

    if nutzer.rolle == "schulleitung":
        return await _stats_schulweit(db, schuljahr_start)

    if nutzer.rolle == "bereichsleiter":
        bereich_scope = await resolve_bereich_scope(db, nutzer)
        if len(bereich_scope) == 1:
            bereich = (
                await db.execute(select(Bereich).where(Bereich.id == next(iter(bereich_scope))))
            ).scalar_one()
            return await _stats_for_bereich(db, bereich, schuljahr_start)
        return await _stats_eigene_bereiche(db, bereich_scope, schuljahr_start)

    klasse_scope = await resolve_scope(db, nutzer)
    if len(klasse_scope) == 1:
        klasse = (await db.execute(select(Klasse).where(Klasse.id == next(iter(klasse_scope))))).scalar_one()
        own = await _aggregate(db, [klasse.id], schuljahr_start)
        return StatsOut(
            level="klasse",
            context=StatsContext(bereich_id=None, bereich_name=None, klasse_id=klasse.id, klasse_name=klasse.name),
            own=own,
            vergleich=[],
        )
    return await _stats_eigene_klassen(db, klasse_scope, schuljahr_start)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_dashboard_query.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Add an endpoint-level test for the stats route**

Append to `backend/tests/test_api_dashboard.py`:

```python
@pytest.mark.asyncio
async def test_get_stats_rejects_bereich_id_for_klassenlehrkraft():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/dashboard/stats", params={"bereich_id": 1}, headers=HEADERS_KLASSENLEHRKRAFT
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_stats_returns_klasse_level_for_own_klasse(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/dashboard/stats", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "klasse"
    assert body["context"]["klasse_id"] == klasse.id
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: PASS (all tests, no regressions)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py backend/tests/test_api_dashboard.py
git commit -m "feat: add GET /dashboard/stats endpoint with role-scoped aggregation"
```

---

## Frontend: Project Scaffold

### Task 4: Vite/React/TS project scaffold with Vitest wired up

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/.gitignore`

**Interfaces:**
- Produces: a working `npm run build` (writes to `wordpress-plugin/absenzdash/assets/spa/`) and `npm test` (Vitest) in `frontend/`. `App` component (placeholder, replaced in Task 10) mounted from `main.tsx` into `#absenzdash-root`.

- [ ] **Step 1: Create `package.json`**

Create `frontend/package.json`:

```json
{
  "name": "absenzdash-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "@tanstack/react-query": "^5.56.0",
    "recharts": "^2.12.7"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^25.0.0",
    "typescript": "^5.5.4",
    "vite": "^5.4.2",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 2: Create `tsconfig.json`**

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create `vite.config.ts`**

Create `frontend/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../wordpress-plugin/absenzdash/assets/spa", import.meta.url)),
    emptyOutDir: true,
    manifest: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

- [ ] **Step 4: Create the Vitest setup file**

Create `frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!("ResizeObserver" in globalThis)) {
  // jsdom does not implement ResizeObserver, required by recharts' ResponsiveContainer
  (globalThis as unknown as { ResizeObserver: typeof ResizeObserverMock }).ResizeObserver =
    ResizeObserverMock;
}
```

- [ ] **Step 5: Create `index.html` (standalone dev convenience, bypassed by the WP plugin)**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="de">
  <head>
    <meta charset="UTF-8" />
    <title>AbsenzDash SPA (Dev)</title>
  </head>
  <body>
    <div id="absenzdash-root"></div>
    <script>
      window.absenzdashConfig = {
        restUrl: "/wp-json/absenzdash/v1/api",
        nonce: "dev-standalone-nonce",
      };
    </script>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Write the failing scaffold test**

Create `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the placeholder root", () => {
    render(<App />);
    expect(screen.getByText("AbsenzDash")).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Install dependencies and run the test to verify it fails**

Run: `cd frontend && npm install && npm test`
Expected: FAIL — `src/App.tsx` does not exist yet

- [ ] **Step 8: Create the placeholder `App.tsx` and `main.tsx`**

Create `frontend/src/App.tsx`:

```tsx
export default function App() {
  return <p>AbsenzDash</p>;
}
```

Create `frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

declare global {
  interface Window {
    absenzdashConfig?: { restUrl: string; nonce: string };
  }
}

const container = document.getElementById("absenzdash-root");
if (container) {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 10: Verify the production build works**

Run: `cd frontend && npm run build`
Expected: Exits 0 and creates `wordpress-plugin/absenzdash/assets/spa/.vite/manifest.json` plus a hashed JS bundle.

- [ ] **Step 11: Add `.gitignore` for build/dependency artifacts**

Create `frontend/.gitignore`:

```
node_modules/
dist/
```

Also add to the repo-root `.gitignore` (create it if it does not already ignore this path) an entry for the frontend's build output landing in the plugin folder:

```
wordpress-plugin/absenzdash/assets/spa/
```

- [ ] **Step 12: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html frontend/src/main.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/test/setup.ts frontend/.gitignore .gitignore
git commit -m "feat: scaffold Vite/React/TS frontend project with Vitest"
```

---

### Task 5: API client with WP-Nonce auth

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.test.ts`
- Create: `frontend/src/api/types.ts`

**Interfaces:**
- Produces: `class ApiError extends Error { status: number }`; `async function apiGet<T>(path: string): Promise<T>` in `frontend/src/api/client.ts`. Shared types `NavBereich`, `NavKlasse`, `NavOptions`, `StatsOwn`, `StatsVergleichEintrag`, `StatsContext`, `StatsLevel`, `Stats` in `frontend/src/api/types.ts`, mirroring the backend Pydantic schemas from Task 2/3.

- [ ] **Step 1: Write the shared types**

Create `frontend/src/api/types.ts`:

```ts
export interface NavBereich {
  id: number;
  name: string;
}

export interface NavKlasse {
  id: number;
  name: string;
  bereich_id: number | null;
}

export interface NavOptions {
  bereiche: NavBereich[];
  klassen: NavKlasse[];
}

export interface StatsOwn {
  anzahl_schueler: number;
  avg_fehltage: number;
  avg_fehlstunden: number;
  avg_klassenbuch: number;
  anzahl_klassenbuch: number;
  anzahl_massnahmen: number;
}

export interface StatsVergleichEintrag extends StatsOwn {
  id: number;
  name: string;
}

export interface StatsContext {
  bereich_id: number | null;
  bereich_name: string | null;
  klasse_id: number | null;
  klasse_name: string | null;
}

export type StatsLevel = "schule" | "eigene_bereiche" | "bereich" | "eigene_klassen" | "klasse";

export interface Stats {
  level: StatsLevel;
  context: StatsContext;
  own: StatsOwn;
  vergleich: StatsVergleichEintrag[];
}
```

- [ ] **Step 2: Write the failing client test**

Create `frontend/src/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "./client";

afterEach(() => {
  window.absenzdashConfig = undefined;
  vi.unstubAllGlobals();
});

describe("apiGet", () => {
  it("throws when absenzdashConfig is missing", async () => {
    await expect(apiGet("dashboard/nav-options")).rejects.toThrow("absenzdashConfig fehlt");
  });

  it("sends the nonce header and returns the parsed JSON body", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiGet<{ ok: boolean }>("dashboard/nav-options");

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/wp-json/absenzdash/v1/api/dashboard/nav-options",
      { headers: { "X-WP-Nonce": "abc123" } },
    );
  });

  it("throws an ApiError when the response is not ok", async () => {
    window.absenzdashConfig = {
      restUrl: "https://example.test/wp-json/absenzdash/v1/api",
      nonce: "abc123",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 403 })));

    await expect(apiGet("dashboard/stats")).rejects.toBeInstanceOf(ApiError);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `src/api/client.ts` does not exist yet

- [ ] **Step 4: Implement the API client**

Create `frontend/src/api/client.ts`:

```ts
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getConfig(): { restUrl: string; nonce: string } {
  if (typeof window === "undefined" || !window.absenzdashConfig) {
    throw new Error(
      "absenzdashConfig fehlt - die SPA muss ueber den [absenzdash]-Shortcode eingebunden sein",
    );
  }
  return window.absenzdashConfig;
}

export async function apiGet<T>(path: string): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    headers: { "X-WP-Nonce": config.nonce },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/api/types.ts
git commit -m "feat: add API client with WP-Nonce auth and shared types"
```

---

### Task 6: react-query hooks for nav-options and stats

**Files:**
- Create: `frontend/src/main.tsx` (modify — add `QueryClientProvider`)
- Create: `frontend/src/api/hooks/useNavOptions.ts`
- Create: `frontend/src/api/hooks/useStats.ts`

**Interfaces:**
- Consumes: `apiGet`, `NavOptions`, `Stats` (Task 5).
- Produces: `useNavOptions(): UseQueryResult<NavOptions>` and `useStats(bereichId: number | null, klasseId: number | null): UseQueryResult<Stats>`.

- [ ] **Step 1: Implement `useNavOptions`**

Create `frontend/src/api/hooks/useNavOptions.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { NavOptions } from "../types";

export function useNavOptions() {
  return useQuery({
    queryKey: ["nav-options"],
    queryFn: () => apiGet<NavOptions>("dashboard/nav-options"),
    staleTime: 5 * 60 * 1000,
  });
}
```

- [ ] **Step 2: Implement `useStats`**

Create `frontend/src/api/hooks/useStats.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { Stats } from "../types";

export function useStats(bereichId: number | null, klasseId: number | null) {
  const params = new URLSearchParams();
  if (bereichId !== null) params.set("bereich_id", String(bereichId));
  if (klasseId !== null) params.set("klasse_id", String(klasseId));
  const query = params.toString();

  return useQuery({
    queryKey: ["dashboard-stats", bereichId, klasseId],
    queryFn: () => apiGet<Stats>(`dashboard/stats${query ? `?${query}` : ""}`),
  });
}
```

- [ ] **Step 3: Wire `QueryClientProvider` into `main.tsx`**

Replace the contents of `frontend/src/main.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";

declare global {
  interface Window {
    absenzdashConfig?: { restUrl: string; nonce: string };
  }
}

const container = document.getElementById("absenzdash-root");
if (container) {
  const queryClient = new QueryClient();
  createRoot(container).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
```

- [ ] **Step 4: Run the existing test suite to verify no regressions**

Run: `cd frontend && npm test`
Expected: PASS (the `App.test.tsx` from Task 4 renders `<App />` directly without a router/query wrapper, which still works since `App` doesn't use router/query features yet)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/main.tsx frontend/src/api/hooks/useNavOptions.ts frontend/src/api/hooks/useStats.ts
git commit -m "feat: add react-query hooks for nav-options and dashboard stats"
```

---

### Task 7: Navigation component (hierarchical Bereich/Klasse dropdowns)

**Files:**
- Create: `frontend/src/components/Navigation/Navigation.tsx`
- Create: `frontend/src/components/Navigation/Navigation.module.css`
- Create: `frontend/src/components/Navigation/Navigation.test.tsx`

**Interfaces:**
- Consumes: `useNavOptions` (Task 6).
- Produces: `Navigation` component (default export not used — named export `Navigation`), reads/writes `bereich`/`klasse` from the URL query string via `useSearchParams`.

**Behavior** (data-driven, no explicit role needed — see design doc §4):
- 0 Bereiche → no Bereich dropdown; Klasse dropdown lists all `klassen` from nav-options.
- Exactly 1 Bereich → no Bereich dropdown; Klasse dropdown lists only `klassen` whose `bereich_id` matches that one Bereich.
- >1 Bereiche → Bereich dropdown shown (with an "Alle Bereiche" option); Klasse dropdown hidden until a specific Bereich is selected, then lists only that Bereich's `klassen`.
- A Klasse dropdown is only rendered if there is more than one visible Klasse to choose from.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Navigation/Navigation.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { Navigation } from "./Navigation";

vi.mock("../../api/hooks/useNavOptions");

const mockUseNavOptions = vi.mocked(useNavOptions);

function renderNavigation(initialEntries: string[] = ["/"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Navigation />
    </MemoryRouter>,
  );
}

describe("Navigation", () => {
  it("shows no dropdowns for a single own Klasse and no Bereiche", () => {
    mockUseNavOptions.mockReturnValue({
      data: { bereiche: [], klassen: [{ id: 1, name: "10a", bereich_id: null }] },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.queryByLabelText("Bereich")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Klasse")).not.toBeInTheDocument();
  });

  it("shows only a Klasse dropdown for multiple own Klassen and no Bereiche", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [],
        klassen: [
          { id: 1, name: "10a", bereich_id: null },
          { id: 2, name: "10b", bereich_id: null },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.queryByLabelText("Bereich")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Klasse")).toBeInTheDocument();
  });

  it("shows only a Klasse dropdown, filtered to the single assigned Bereich", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [{ id: 1, name: "Ausbildung" }],
        klassen: [
          { id: 10, name: "AME56", bereich_id: 1 },
          { id: 11, name: "AME57", bereich_id: 1 },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.queryByLabelText("Bereich")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Klasse")).toBeInTheDocument();
    expect(screen.getByText("AME56")).toBeInTheDocument();
    expect(screen.getByText("AME57")).toBeInTheDocument();
  });

  it("hides the Klasse dropdown until a Bereich is chosen when there are multiple Bereiche", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [
          { id: 1, name: "Ausbildung" },
          { id: 2, name: "Berufsschule" },
        ],
        klassen: [
          { id: 10, name: "AME56", bereich_id: 1 },
          { id: 12, name: "AME57", bereich_id: 1 },
          { id: 11, name: "BME12", bereich_id: 2 },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation();

    expect(screen.getByLabelText("Bereich")).toBeInTheDocument();
    expect(screen.queryByLabelText("Klasse")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Bereich"), { target: { value: "1" } });

    expect(screen.getByLabelText("Klasse")).toBeInTheDocument();
    expect(screen.getByText("AME56")).toBeInTheDocument();
    expect(screen.getByText("AME57")).toBeInTheDocument();
    expect(screen.queryByText("BME12")).not.toBeInTheDocument();
  });

  it("clears the klasse URL param when the Bereich selection changes", () => {
    mockUseNavOptions.mockReturnValue({
      data: {
        bereiche: [
          { id: 1, name: "Ausbildung" },
          { id: 2, name: "Berufsschule" },
        ],
        klassen: [
          { id: 10, name: "AME56", bereich_id: 1 },
          { id: 12, name: "AME57", bereich_id: 1 },
          { id: 11, name: "BME12", bereich_id: 2 },
          { id: 13, name: "BME13", bereich_id: 2 },
        ],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    renderNavigation(["/?bereich=1&klasse=10"]);

    expect(screen.getByLabelText("Klasse")).toHaveValue("10");

    fireEvent.change(screen.getByLabelText("Bereich"), { target: { value: "2" } });

    expect(screen.getByLabelText("Klasse")).toHaveValue("");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — `src/components/Navigation/Navigation.tsx` does not exist yet

- [ ] **Step 3: Implement the Navigation component**

Create `frontend/src/components/Navigation/Navigation.module.css`:

```css
.nav {
  display: flex;
  gap: 1rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #ddd;
}
```

Create `frontend/src/components/Navigation/Navigation.tsx`:

```tsx
import { useSearchParams } from "react-router-dom";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import styles from "./Navigation.module.css";

export function Navigation() {
  const { data, isLoading, isError } = useNavOptions();
  const [searchParams, setSearchParams] = useSearchParams();

  if (isLoading) {
    return <nav className={styles.nav}>Lädt Navigation…</nav>;
  }
  if (isError || !data) {
    return <nav className={styles.nav}>Fehler beim Laden der Navigation</nav>;
  }

  const bereichParam = searchParams.get("bereich");
  const selectedBereichId = bereichParam ? Number(bereichParam) : null;

  const showBereichDropdown = data.bereiche.length > 1;
  const visibleKlassen =
    data.bereiche.length === 0
      ? data.klassen
      : data.bereiche.length === 1
        ? data.klassen.filter((k) => k.bereich_id === data.bereiche[0].id)
        : selectedBereichId === null
          ? []
          : data.klassen.filter((k) => k.bereich_id === selectedBereichId);
  const showKlasseDropdown = visibleKlassen.length > 1;

  function handleBereichChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete("bereich");
    } else {
      next.set("bereich", value);
    }
    next.delete("klasse");
    setSearchParams(next);
  }

  function handleKlasseChange(value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete("klasse");
    } else {
      next.set("klasse", value);
    }
    setSearchParams(next);
  }

  return (
    <nav className={styles.nav}>
      {showBereichDropdown && (
        <select
          aria-label="Bereich"
          value={bereichParam ?? ""}
          onChange={(event) => handleBereichChange(event.target.value)}
        >
          <option value="">Alle Bereiche</option>
          {data.bereiche.map((bereich) => (
            <option key={bereich.id} value={bereich.id}>
              {bereich.name}
            </option>
          ))}
        </select>
      )}
      {showKlasseDropdown && (
        <select
          aria-label="Klasse"
          value={searchParams.get("klasse") ?? ""}
          onChange={(event) => handleKlasseChange(event.target.value)}
        >
          <option value="">Alle Klassen</option>
          {visibleKlassen.map((klasse) => (
            <option key={klasse.id} value={klasse.id}>
              {klasse.name}
            </option>
          ))}
        </select>
      )}
    </nav>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Navigation
git commit -m "feat: add hierarchical Bereich/Klasse Navigation component"
```

---

### Task 8: StatCard and ComparisonChart components

**Files:**
- Create: `frontend/src/components/StatCard/StatCard.tsx`
- Create: `frontend/src/components/StatCard/StatCard.module.css`
- Create: `frontend/src/components/StatCard/StatCard.test.tsx`
- Create: `frontend/src/components/ComparisonChart/ComparisonChart.tsx`
- Create: `frontend/src/components/ComparisonChart/ComparisonChart.test.tsx`

**Interfaces:**
- Consumes: `StatsVergleichEintrag` (Task 5).
- Produces: `StatCard({ label, value, secondaryValue? })`; `ComparisonChart({ data, metric })` where `metric` is one of `"avg_fehltage" | "avg_fehlstunden" | "avg_klassenbuch" | "anzahl_massnahmen"`.

- [ ] **Step 1: Write the failing StatCard test**

Create `frontend/src/components/StatCard/StatCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("shows the label and value", () => {
    render(<StatCard label="Ø Fehltage" value="2.3" />);
    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
    expect(screen.getByText("2.3")).toBeInTheDocument();
  });

  it("shows the secondary value in parentheses when provided", () => {
    render(<StatCard label="Klassenbuch-Einträge" value="0.8" secondaryValue="120 gesamt" />);
    expect(screen.getByText("(120 gesamt)")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `src/components/StatCard/StatCard.tsx` does not exist yet

- [ ] **Step 3: Implement StatCard**

Create `frontend/src/components/StatCard/StatCard.module.css`:

```css
.card {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 1rem;
  border: 1px solid #ddd;
  border-radius: 4px;
  min-width: 10rem;
}

.label {
  font-size: 0.85rem;
  color: #555;
}

.value {
  font-size: 1.75rem;
  font-weight: 600;
}

.secondary {
  font-size: 0.85rem;
  color: #777;
}
```

Create `frontend/src/components/StatCard/StatCard.tsx`:

```tsx
import styles from "./StatCard.module.css";

interface StatCardProps {
  label: string;
  value: string;
  secondaryValue?: string;
}

export function StatCard({ label, value, secondaryValue }: StatCardProps) {
  return (
    <div className={styles.card}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
      {secondaryValue !== undefined && <span className={styles.secondary}>({secondaryValue})</span>}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Write the failing ComparisonChart test**

Create `frontend/src/components/ComparisonChart/ComparisonChart.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StatsVergleichEintrag } from "../../api/types";
import { ComparisonChart } from "./ComparisonChart";

const beispielEintrag: StatsVergleichEintrag = {
  id: 1,
  name: "AME56",
  anzahl_schueler: 20,
  avg_fehltage: 2,
  avg_fehlstunden: 3,
  avg_klassenbuch: 1,
  anzahl_klassenbuch: 20,
  anzahl_massnahmen: 2,
};

describe("ComparisonChart", () => {
  it("renders nothing when there is no comparison data", () => {
    const { container } = render(<ComparisonChart data={[]} metric="avg_fehltage" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a chart container when comparison data is present", () => {
    const { container } = render(<ComparisonChart data={[beispielEintrag]} metric="avg_fehltage" />);
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
  });
});
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `src/components/ComparisonChart/ComparisonChart.tsx` does not exist yet

- [ ] **Step 7: Implement ComparisonChart**

Create `frontend/src/components/ComparisonChart/ComparisonChart.tsx`:

```tsx
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { StatsVergleichEintrag } from "../../api/types";

interface ComparisonChartProps {
  data: StatsVergleichEintrag[];
  metric: "avg_fehltage" | "avg_fehlstunden" | "avg_klassenbuch" | "anzahl_massnahmen";
}

export function ComparisonChart({ data, metric }: ComparisonChartProps) {
  if (data.length === 0) {
    return null;
  }
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey={metric} />
      </BarChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/StatCard frontend/src/components/ComparisonChart
git commit -m "feat: add StatCard and ComparisonChart components"
```

---

### Task 9: Landing page, routing, and WP plugin integration

**Files:**
- Create: `frontend/src/pages/Landing/Landing.tsx`
- Create: `frontend/src/pages/Landing/Landing.test.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx` (replace the Task 4 placeholder version)
- Modify: `wordpress-plugin/absenzdash/includes/class-shortcode.php`
- Delete: `wordpress-plugin/absenzdash/assets/smoke-test.js`

**Interfaces:**
- Consumes: `useStats` (Task 6), `StatCard`, `ComparisonChart` (Task 8), `Navigation` (Task 7).
- Produces: `Landing` page component; `App` with routes `/` → `Landing`, `/klasse/:id` → placeholder text.

- [ ] **Step 1: Write the failing Landing test**

Create `frontend/src/pages/Landing/Landing.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStats } from "../../api/hooks/useStats";
import { Landing } from "./Landing";

vi.mock("../../api/hooks/useStats");

const mockUseStats = vi.mocked(useStats);

describe("Landing", () => {
  it("renders the stat cards from the stats response", () => {
    mockUseStats.mockReturnValue({
      data: {
        level: "schule",
        context: { bereich_id: null, bereich_name: null, klasse_id: null, klasse_name: null },
        own: {
          anzahl_schueler: 100,
          avg_fehltage: 2.5,
          avg_fehlstunden: 1.2,
          avg_klassenbuch: 0.4,
          anzahl_klassenbuch: 40,
          anzahl_massnahmen: 10,
        },
        vergleich: [],
      },
      isLoading: false,
      isError: false,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    );

    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
    expect(screen.getByText("2.5")).toBeInTheDocument();
    expect(screen.getByText("Maßnahmen")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("shows an error message when the stats request fails", () => {
    mockUseStats.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <MemoryRouter>
        <Landing />
      </MemoryRouter>,
    );

    expect(screen.getByText("Fehler beim Laden der Kennzahlen.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `src/pages/Landing/Landing.tsx` does not exist yet

- [ ] **Step 3: Implement the Landing page**

Create `frontend/src/pages/Landing/Landing.tsx`:

```tsx
import { useSearchParams } from "react-router-dom";
import { useStats } from "../../api/hooks/useStats";
import { ComparisonChart } from "../../components/ComparisonChart/ComparisonChart";
import { StatCard } from "../../components/StatCard/StatCard";

export function Landing() {
  const [searchParams] = useSearchParams();
  const bereichParam = searchParams.get("bereich");
  const klasseParam = searchParams.get("klasse");
  const bereichId = bereichParam ? Number(bereichParam) : null;
  const klasseId = klasseParam ? Number(klasseParam) : null;

  const { data, isLoading, isError } = useStats(bereichId, klasseId);

  if (isLoading) {
    return <p>Lädt Kennzahlen…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Kennzahlen.</p>;
  }

  return (
    <div>
      <StatCard label="Ø Fehltage" value={data.own.avg_fehltage.toFixed(1)} />
      <StatCard label="Ø Fehlstunden" value={data.own.avg_fehlstunden.toFixed(1)} />
      <StatCard
        label="Klassenbuch-Einträge"
        value={data.own.avg_klassenbuch.toFixed(1)}
        secondaryValue={`${data.own.anzahl_klassenbuch} gesamt`}
      />
      <StatCard label="Maßnahmen" value={String(data.own.anzahl_massnahmen)} />
      <ComparisonChart data={data.vergleich} metric="avg_fehltage" />
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Replace `App.test.tsx` with the routing test**

Replace `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "./api/hooks/useNavOptions";
import { useStats } from "./api/hooks/useStats";
import App from "./App";

vi.mock("./api/hooks/useNavOptions");
vi.mock("./api/hooks/useStats");

const mockUseNavOptions = vi.mocked(useNavOptions);
const mockUseStats = vi.mocked(useStats);

function setupMocks() {
  mockUseNavOptions.mockReturnValue({
    data: { bereiche: [], klassen: [] },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
  mockUseStats.mockReturnValue({
    data: {
      level: "schule",
      context: { bereich_id: null, bereich_name: null, klasse_id: null, klasse_name: null },
      own: {
        anzahl_schueler: 0,
        avg_fehltage: 0,
        avg_fehlstunden: 0,
        avg_klassenbuch: 0,
        anzahl_klassenbuch: 0,
        anzahl_massnahmen: 0,
      },
      vergleich: [],
    },
    isLoading: false,
    isError: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

describe("App", () => {
  it("renders the Landing page at the root route", () => {
    setupMocks();
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Ø Fehltage")).toBeInTheDocument();
  });

  it("renders the Klasse placeholder route", () => {
    setupMocks();
    render(
      <MemoryRouter initialEntries={["/klasse/5"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Schülerliste folgt in einem späteren Ausbauschritt.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `App.tsx` still renders the Task 4 placeholder, no routes defined

- [ ] **Step 7: Implement the real `App.tsx`**

Replace `frontend/src/App.tsx`:

```tsx
import { Outlet, Route, Routes } from "react-router-dom";
import { Navigation } from "./components/Navigation/Navigation";
import { Landing } from "./pages/Landing/Landing";

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

function KlassePlatzhalter() {
  return <p>Schülerliste folgt in einem späteren Ausbauschritt.</p>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/klasse/:id" element={<KlassePlatzhalter />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 8: Run the full frontend test suite to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 9: Update the WordPress plugin shortcode to mount the SPA**

Replace `wordpress-plugin/absenzdash/includes/class-shortcode.php`:

```php
<?php

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

class Absenzdash_Shortcode {

	public function __construct() {
		add_shortcode( 'absenzdash', array( $this, 'render' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_assets' ) );
		add_filter( 'script_loader_tag', array( $this, 'add_module_type' ), 10, 3 );
	}

	private function get_manifest_entry(): ?array {
		$manifest_path = ABSENZDASH_PLUGIN_DIR . 'assets/spa/.vite/manifest.json';
		if ( ! file_exists( $manifest_path ) ) {
			return null;
		}
		$manifest = json_decode( file_get_contents( $manifest_path ), true );
		return $manifest['src/main.tsx'] ?? null;
	}

	public function enqueue_assets(): void {
		if ( defined( 'ABSENZDASH_VITE_DEV_SERVER' ) && ABSENZDASH_VITE_DEV_SERVER ) {
			$dev_server = rtrim( ABSENZDASH_VITE_DEV_SERVER, '/' );
			wp_enqueue_script( 'absenzdash-vite-client', $dev_server . '/@vite/client', array(), null, true );
			wp_enqueue_script(
				'absenzdash-spa',
				$dev_server . '/src/main.tsx',
				array( 'absenzdash-vite-client' ),
				null,
				true
			);
		} else {
			$entry = $this->get_manifest_entry();
			if ( null === $entry ) {
				return;
			}
			foreach ( $entry['css'] ?? array() as $index => $css_file ) {
				wp_enqueue_style(
					'absenzdash-spa-' . $index,
					ABSENZDASH_PLUGIN_URL . 'assets/spa/' . $css_file,
					array(),
					ABSENZDASH_VERSION
				);
			}
			wp_enqueue_script(
				'absenzdash-spa',
				ABSENZDASH_PLUGIN_URL . 'assets/spa/' . $entry['file'],
				array(),
				ABSENZDASH_VERSION,
				true
			);
		}

		wp_localize_script(
			'absenzdash-spa',
			'absenzdashConfig',
			array(
				'restUrl' => esc_url_raw( rest_url( 'absenzdash/v1/api' ) ),
				'nonce'   => wp_create_nonce( 'wp_rest' ),
			)
		);
	}

	public function add_module_type( string $tag, string $handle, string $src ): string {
		if ( in_array( $handle, array( 'absenzdash-vite-client', 'absenzdash-spa' ), true ) ) {
			return str_replace( ' src=', ' type="module" src=', $tag );
		}
		return $tag;
	}

	public function render(): string {
		if ( ! is_user_logged_in() ) {
			return '<p>AbsenzDash: Bitte einloggen.</p>';
		}
		return '<div id="absenzdash-root"></div>';
	}
}
```

- [ ] **Step 10: Remove the now-obsolete smoke-test asset**

```bash
git rm wordpress-plugin/absenzdash/assets/smoke-test.js
```

- [ ] **Step 11: Commit**

```bash
git add frontend/src/pages/Landing frontend/src/App.tsx frontend/src/App.test.tsx wordpress-plugin/absenzdash/includes/class-shortcode.php
git commit -m "feat: add Landing dashboard page, routing, and WP plugin SPA mount"
```

---

### Task 10: Documentation updates

**Files:**
- Modify: `docs/deployment.md`
- Modify: `ROADMAP.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Document the frontend dev workflow**

Add a new section to `docs/deployment.md`, after the existing "## WordPress-Plugin (Mini-Proxy & Shortcode)" section and before "## Netzwerk":

```markdown
## Frontend (React/TS-SPA)

Voraussetzung: Node.js (getestet mit v24) und npm.

**Produktions-Build** (schreibt direkt nach `wordpress-plugin/absenzdash/assets/spa/`):

```bash
cd frontend
npm install
npm run build
```

**Lokale Entwicklung mit Hot-Module-Reload** gegen die echte WordPress-Instanz (Nonce/Session/Backend-Daten
sind sonst nicht nutzbar, siehe TECH-SPEC.md §3):

1. In `wp-config.php` der WordPress-Instanz eine Konstante setzen, die auf den laufenden Vite-Dev-Server zeigt:
   ```php
   define( 'ABSENZDASH_VITE_DEV_SERVER', 'http://localhost:5173' );
   ```
2. Den Vite-Dev-Server starten: `cd frontend && npm run dev`
3. Die Seite mit dem `[absenzdash]`-Shortcode im Browser öffnen — das Plugin lädt jetzt das Vite-Dev-Server-Skript
   statt der gebauten Dateien; Änderungen am Code werden per HMR live übernommen.
4. Die Konstante vor jedem Produktions-Deployment wieder entfernen bzw. auskommentieren.

Ohne WordPress-Einbindung kann `npm run dev` auch standalone geöffnet werden (`http://localhost:5173`) für
schnelle UI-Iteration ohne echte Backend-Daten (siehe `frontend/index.html`).
```

- [ ] **Step 2: Move the roadmap item from "Geplant" to "Abgeschlossen"**

In `ROADMAP.md`, remove item 1 from the "## Geplant (noch nicht als Plan ausgearbeitet)" list and renumber the remaining items (old 2 → 1, old 3 → 2). Add a new row to the "## Abgeschlossen" table, after the Plan 8 row:

```markdown
| **Plan 9** — [Frontend-Grundgerüst (Navigation & Landing-Dashboard)](docs/superpowers/plans/2026-07-28-frontend-grundgeruest.md) | Vite/React/TS-SPA-Grundgerüst, WP-Nonce-Auth, Routing-Grundgerüst, rollenabhängige hierarchische Bereich-/Klasse-Navigation, neue Backend-Kennzahlen-Endpunkte (`GET /dashboard/nav-options`, `GET /dashboard/stats`), Landing-Page-Dashboard (Ø Fehltage/-stunden, Klassenbuch-Einträge, Maßnahmen-Anzahl, je mit Vergleichsbalken) (SPECS.md §2/§7). Bewusste Aufteilung von Roadmap-Punkt 1: Schülerliste/-Detail, Admin-Bereich und PDF-Export-Anbindung folgen als eigene Pläne, siehe [Design-Dok](docs/superpowers/specs/2026-07-28-frontend-grundgeruest-design.md) | Schülerliste/-Detail, Admin-Bereich, PDF-Export-Anbindung, automatischer Nonce-Refresh |
```

- [ ] **Step 3: Commit**

```bash
git add docs/deployment.md ROADMAP.md
git commit -m "docs: document frontend dev workflow and update roadmap for Plan 9"
```

---

## Self-Review Notes

- **Spec coverage:** All five design-doc sections (architecture/tech-stack, backend endpoints, frontend structure/navigation, error handling, testing) map to tasks 1–10. The "bewusst nicht enthalten" list (Schülerliste, Admin, PDF-Export, Gauge, auto nonce-refresh) is intentionally out of scope and not implemented here.
- **Type consistency:** `NavOptionsOut`/`NavBereichOut`/`NavKlasseOut` and `StatsOut`/`StatsOwn`/`StatsVergleichEintrag`/`StatsContext` field names match exactly between the Task 2/3 Pydantic schemas and the Task 5 TypeScript types (`anzahl_schueler`, `avg_fehltage`, `avg_fehlstunden`, `avg_klassenbuch`, `anzahl_klassenbuch`, `anzahl_massnahmen`, `bereich_id`, `bereich_name`, `klasse_id`, `klasse_name`, `level`, `context`, `own`, `vergleich`).
- **No placeholders:** Task 2's `get_dashboard_stats` placeholder is explicitly called out as temporary and is fully replaced within Task 3, in the same work session — this is the one intentional exception, needed only so Task 2's own endpoint test can run before Task 3 exists; it does not survive past Task 3.
