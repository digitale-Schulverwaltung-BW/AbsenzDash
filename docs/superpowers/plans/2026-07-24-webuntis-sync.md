# Backend: WebUntis-Sync-Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein laufender WebUntis-Sync-Job, der Klassen, Klassenbuch-Kategorien, Fehlzeiten und Klassenbucheinträge aus WebUntis zieht, sowie ein ASV-BW-CSV-Import für Schüler-Stammdaten/Klassenzuordnung — orchestriert, mit Retry und einem konfigurierbaren Scheduler. Baut auf dem fertigen Backend-Grundgerüst (Plan 1) auf.

**Architecture:** Ein eigener async JSON-RPC-Client (`WebUntisClient`) kapselt Auth/Retry gegen WebUntis. Vier unabhängig testbare Sync-Funktionen (Klassen/Kategorien, ASV-BW-CSV, Fehlzeiten, Klassenbuch) werden von einem Orchestrator (`run_full_sync`) in einer Transaktion pro Lauf verkettet; bei Fehlern kompletter Rollback + Retry nach konfigurierbarer Verzögerung. Ein APScheduler-Job im FastAPI-Lifespan-Hook liest das Sync-Intervall live aus der `einstellung`-Tabelle.

**Tech Stack:** Python 3.11 (containerisiert, siehe Plan 1), FastAPI, SQLAlchemy 2.0 (async), Alembic, httpx (WebUntis JSON-RPC), APScheduler, pytest + pytest-asyncio + respx (HTTP-Mocking).

## Global Constraints

- Alle `Run:`-Befehle laufen containerisiert (kein Python auf dem Host) — siehe Plan 1, "Ausführungsumgebung": `docker compose -f backend/docker-compose.yml run --rm backend <cmd>`, vorher `docker compose -f backend/docker-compose.yml up -d postgres`.
- ORM-Stil: SQLAlchemy 2.0 mit `Mapped[]`-Typannotationen, konsistent mit Plan 1.
- Migrationen ausschließlich über Alembic. **Migration vor Testlauf erzeugen** (nicht danach) — sonst findet `autogenerate` keinen Unterschied, weil `tests/conftest.py`s `create_all`-Fixture dieselbe Dev-DB bereits verändert hat (Lehre aus Plan 1, Task 6).
- Tabellen-/Feldnamen auf Deutsch, WebUntis-/CSV-Rohfeldnamen im Code als Kommentar/Docstring vermerkt, wo nicht offensichtlich.
- Commit-Messages auf Englisch (globale CLAUDE.md).
- Nach Abschluss dieses Plans: sofort committen und pushen (`CLAUDE.md`, Remote existiert bereits seit Plan 1).
- Referenzdokumente: [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 1, 2, 2.1, 6; [SPECS.md](../../../SPECS.md) Abschnitt 4, 5.1; Design: [docs/superpowers/specs/2026-07-24-webuntis-sync-design.md](../specs/2026-07-24-webuntis-sync-design.md).
- Dieser Plan ändert bestehende Modelle/Tests aus Plan 1 (`schueler.webuntis_id`/`webuntis_key` → `externe_id`, siehe Task 3) — betroffene Bestandsdateien werden explizit als "Modify" mit vollständigem Diff geführt, nicht nur neue Dateien.

---

## File Structure

```
backend/
  app/
    core/
      config.py           (Modify — WebUntis-/ASV-CSV-/Retry-Settings)
      scheduler.py         (Task 7)
    integrations/
      __init__.py          (Task 1)
      webuntis_client.py   (Task 1)
    models/
      schueler.py          (Modify, Task 3 — externe_id statt webuntis_id/webuntis_key)
      einstellung.py        (Modify, Task 3 + Task 6 — neue Felder)
    services/
      webuntis_klassen_sync.py     (Task 2)
      webuntis_kategorie_sync.py   (Task 2)
      asv_csv_import.py            (Task 3)
      webuntis_fehlzeit_sync.py    (Task 4)
      webuntis_klassenbuch_sync.py (Task 5)
      sync_orchestrator.py         (Task 6)
    main.py                (Modify, Task 7 — Lifespan-Hook)
  tests/
    test_webuntis_client.py        (Task 1)
    test_webuntis_klassen_sync.py  (Task 2)
    test_webuntis_kategorie_sync.py (Task 2)
    test_asv_csv_import.py         (Task 3)
    test_models_schueler.py        (Modify, Task 3)
    test_models_klassenbuch.py     (Modify, Task 3)
    test_webuntis_fehlzeit_sync.py (Task 4)
    test_webuntis_klassenbuch_sync.py (Task 5)
    test_sync_orchestrator.py      (Task 6)
    test_scheduler.py              (Task 7)
  requirements.txt          (Modify — apscheduler)
  requirements-dev.txt      (Modify — respx)
  .env.example               (Modify — neue Env-Vars)
  alembic/versions/          (zwei neue Migrationen: Task 3 einmal — schueler+einstellung kombiniert —, Task 6 einmal)
docs/
  backend-setup.md           (Modify, Task 8)
```

---

### Task 1: WebUntis-JSON-RPC-Client (Auth, Retry)

**Files:**
- Create: `backend/app/integrations/__init__.py`
- Create: `backend/app/integrations/webuntis_client.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`
- Test: `backend/tests/test_webuntis_client.py`

**Interfaces:**
- Consumes: nichts Neues.
- Produces: `app.integrations.webuntis_client.WebUntisClient` (async Context-Manager, `await client.call(method: str, params: dict) -> Any`), `app.integrations.webuntis_client.WebUntisError` (Exception) — von allen `*_sync`-Funktionen ab Task 2 genutzt. `app.core.config.settings` erweitert um `webuntis_server`, `webuntis_school`, `webuntis_username`, `webuntis_password`.

- [ ] **Step 1: Config, .env.example und Requirements erweitern**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str
    webuntis_server: str
    webuntis_school: str
    webuntis_username: str
    webuntis_password: str


settings = Settings()
```

```text
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash
WORDPRESS_PROXY_SECRET=changeme
WEBUNTIS_SERVER=changeme.webuntis.com
WEBUNTIS_SCHOOL=changeme
WEBUNTIS_USERNAME=changeme
WEBUNTIS_PASSWORD=changeme
```

> Falls `backend/.env` bereits existiert (seit Plan 1), fehlen dort jetzt vier Pflichtfelder — `Settings()` schlägt sonst beim Import fehl. Ergänzen (Platzhalterwerte reichen für Tests, da WebUntis-Calls in Tests über `respx` gemockt werden, nie echt aufgerufen):
> Run: `grep -q WEBUNTIS_SERVER backend/.env || cat >> backend/.env <<'EOF'
> WEBUNTIS_SERVER=test.webuntis.com
> WEBUNTIS_SCHOOL=test
> WEBUNTIS_USERNAME=test
> WEBUNTIS_PASSWORD=test
> EOF`

```text
# backend/requirements.txt
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
httpx>=0.27,<1.0
sqlalchemy>=2.0,<3.0
asyncpg>=0.29,<1.0
alembic>=1.13,<2.0
pydantic-settings>=2.4,<3.0
python-dotenv>=1.0,<2.0
apscheduler>=3.10,<4.0
```

```text
# backend/requirements-dev.txt
-r requirements.txt
pytest>=8.2,<9.0
pytest-asyncio>=0.23,<1.0
respx>=0.21,<1.0
```

Run: `docker compose -f backend/docker-compose.yml build backend`
Expected: Image baut ohne Fehler (installiert `apscheduler`, `respx`).

- [ ] **Step 2: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_webuntis_client.py
import httpx
import pytest
import respx

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError

RPC_URL = "https://test.webuntis.com/WebUntis/jsonrpc.do"


@pytest.fixture(autouse=True)
def _set_webuntis_settings(monkeypatch):
    monkeypatch.setattr(settings, "webuntis_server", "test.webuntis.com")
    monkeypatch.setattr(settings, "webuntis_school", "test")
    monkeypatch.setattr(settings, "webuntis_username", "svc")
    monkeypatch.setattr(settings, "webuntis_password", "pw")


def _auth_route(session_id="sess-1"):
    return respx.post(RPC_URL, params={"school": "test"}, json__method="authenticate").mock(
        return_value=httpx.Response(200, json={"id": "auth", "result": {"sessionId": session_id}, "jsonrpc": "2.0"})
    )


@pytest.mark.asyncio
@respx.mock
async def test_call_authenticates_and_returns_result():
    _auth_route()
    respx.post(RPC_URL, params={"school": "test"}, json__method="getKlassen").mock(
        return_value=httpx.Response(200, json={"id": "getKlassen", "result": [{"id": 1}], "jsonrpc": "2.0"})
    )

    async with WebUntisClient(settings) as client:
        result = await client.call("getKlassen", {})

    assert result == [{"id": 1}]


@pytest.mark.asyncio
@respx.mock
async def test_call_reauthenticates_once_on_session_expired():
    _auth_route(session_id="sess-1")
    call_route = respx.post(RPC_URL, params={"school": "test"}, json__method="getKlassen")
    call_route.side_effect = [
        httpx.Response(200, json={"id": "getKlassen", "error": {"code": -8520, "message": "expired"}, "jsonrpc": "2.0"}),
        httpx.Response(200, json={"id": "getKlassen", "result": [{"id": 2}], "jsonrpc": "2.0"}),
    ]

    async with WebUntisClient(settings) as client:
        result = await client.call("getKlassen", {})

    assert result == [{"id": 2}]
    assert call_route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_raises_on_login_failure():
    respx.post(RPC_URL, params={"school": "test"}, json__method="authenticate").mock(
        return_value=httpx.Response(200, json={"id": "auth", "error": {"code": -8504, "message": "bad credentials"}, "jsonrpc": "2.0"})
    )

    with pytest.raises(WebUntisError):
        async with WebUntisClient(settings):
            pass


@pytest.mark.asyncio
@respx.mock
async def test_context_manager_calls_logout_on_exit():
    _auth_route()
    logout_route = respx.post(RPC_URL, params={"school": "test"}, json__method="logout").mock(
        return_value=httpx.Response(200, json={"id": "logout", "result": None, "jsonrpc": "2.0"})
    )

    async with WebUntisClient(settings):
        pass

    assert logout_route.call_count == 1
```

- [ ] **Step 3: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml up -d postgres && docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_client.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.integrations'`

- [ ] **Step 4: Client implementieren**

```python
# backend/app/integrations/__init__.py
```

```python
# backend/app/integrations/webuntis_client.py
from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from app.core.config import Settings

_SESSION_EXPIRED_ERROR_CODE = -8520


class WebUntisError(RuntimeError):
    """Raised when a WebUntis JSON-RPC call returns an error (other than session expiry)."""


class WebUntisClient:
    """Async JSON-RPC-Client für WebUntis (TECH-SPEC.md Abschnitt 1.1).

    Nutzung: `async with WebUntisClient(settings) as client: await client.call("getKlassen", {})`.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=15.0)
        self._session_id: str | None = None

    @property
    def _rpc_url(self) -> str:
        return f"https://{self._settings.webuntis_server}/WebUntis/jsonrpc.do"

    async def __aenter__(self) -> WebUntisClient:
        await self._authenticate()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session_id is not None:
            await self._raw_call("logout", {})
        await self._http.aclose()

    async def _authenticate(self) -> None:
        payload = {
            "id": "auth",
            "method": "authenticate",
            "params": {
                "user": self._settings.webuntis_username,
                "password": self._settings.webuntis_password,
                "client": "AbsenzDash",
            },
            "jsonrpc": "2.0",
        }
        response = await self._http.post(
            self._rpc_url, params={"school": self._settings.webuntis_school}, json=payload
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise WebUntisError(f"WebUntis-Login fehlgeschlagen: {body['error']}")
        self._session_id = body["result"]["sessionId"]

    async def _raw_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {"Cookie": f"JSESSIONID={self._session_id}"} if self._session_id else {}
        payload = {"id": method, "method": method, "params": params, "jsonrpc": "2.0"}
        response = await self._http.post(
            self._rpc_url, params={"school": self._settings.webuntis_school}, json=payload, headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def call(self, method: str, params: dict[str, Any]) -> Any:
        body = await self._raw_call(method, params)
        if "error" in body:
            error = body["error"]
            if error.get("code") == _SESSION_EXPIRED_ERROR_CODE:
                await self._authenticate()
                body = await self._raw_call(method, params)
                if "error" in body:
                    raise WebUntisError(f"WebUntis-Aufruf '{method}' fehlgeschlagen: {body['error']}")
            else:
                raise WebUntisError(f"WebUntis-Aufruf '{method}' fehlgeschlagen: {error}")
        return body.get("result")
```

- [ ] **Step 5: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_client.py -v`
Expected: PASS (4 Tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/integrations backend/app/core/config.py backend/.env.example backend/requirements.txt backend/requirements-dev.txt backend/tests/test_webuntis_client.py
git commit -m "feat: add WebUntis JSON-RPC client with session re-auth"
```

---

### Task 2: Klassen- & Kategorie-Sync

**Files:**
- Create: `backend/app/services/webuntis_klassen_sync.py`
- Create: `backend/app/services/webuntis_kategorie_sync.py`
- Test: `backend/tests/test_webuntis_klassen_sync.py`
- Test: `backend/tests/test_webuntis_kategorie_sync.py`

**Interfaces:**
- Consumes: `WebUntisClient` (Task 1), `Klasse` (Plan 1), `ClassregCategory` (Plan 1), `seed_nutzer_klasse_from_webuntis` (Plan 1, `app.services.nutzer_klasse_sync`).
- Produces: `webuntis_klassen_sync.sync_klassen(client: WebUntisClient, db: AsyncSession) -> None`, `webuntis_kategorie_sync.sync_kategorien(client: WebUntisClient, db: AsyncSession) -> None` — beide ab Task 6 vom Orchestrator aufgerufen.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_webuntis_klassen_sync.py
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.services.webuntis_klassen_sync import sync_klassen


@pytest.mark.asyncio
async def test_sync_klassen_creates_new_klasse(db_session):
    client = AsyncMock()
    client.call.return_value = [
        {"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None},
    ]

    await sync_klassen(client, db_session)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.name == "10a"
    assert klasse.webuntis_teacher1_id == 63
    assert klasse.webuntis_teacher2_id is None
    client.call.assert_awaited_once_with("getKlassen", {})


@pytest.mark.asyncio
async def test_sync_klassen_updates_existing_klasse(db_session):
    existing = Klasse(webuntis_id=1, name="alt", webuntis_teacher1_id=1)
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 1, "name": "neu", "teacher1": 2, "teacher2": None}]

    await sync_klassen(client, db_session)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 1))
    klasse = result.scalar_one()
    assert klasse.name == "neu"
    assert klasse.webuntis_teacher1_id == 2


@pytest.mark.asyncio
async def test_sync_klassen_triggers_nutzer_klasse_seeding(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft", webuntis_teacher_id=63)
    db_session.add(nutzer)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session)

    result = await db_session.execute(select(NutzerKlasse))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].quelle == "webuntis_seed"
```

```python
# backend/tests/test_webuntis_kategorie_sync.py
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.services.webuntis_kategorie_sync import sync_kategorien


@pytest.mark.asyncio
async def test_sync_kategorien_creates_categories_with_group_name(db_session):
    client = AsyncMock()
    client.call.side_effect = [
        [{"id": 1, "name": "stören", "longName": "Störung des Unterrichts", "groupId": 10}],
        [{"id": 10, "name": "Störung"}],
    ]

    await sync_kategorien(client, db_session)

    result = await db_session.execute(select(ClassregCategory).where(ClassregCategory.name == "stören"))
    kategorie = result.scalar_one()
    assert kategorie.long_name == "Störung des Unterrichts"
    assert kategorie.group_name == "Störung"
    assert client.call.await_args_list[0].args == ("getClassregCategories", {})
    assert client.call.await_args_list[1].args == ("getClassregCategoryGroups", {})


@pytest.mark.asyncio
async def test_sync_kategorien_updates_existing_category(db_session):
    existing = ClassregCategory(webuntis_id=1, name="stören", long_name="alt", group_name=None)
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.side_effect = [
        [{"id": 1, "name": "stören", "longName": "neu", "groupId": None}],
        [],
    ]

    await sync_kategorien(client, db_session)

    result = await db_session.execute(select(ClassregCategory).where(ClassregCategory.name == "stören"))
    kategorie = result.scalar_one()
    assert kategorie.long_name == "neu"
    assert kategorie.group_name is None
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_klassen_sync.py tests/test_webuntis_kategorie_sync.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.webuntis_klassen_sync'`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/webuntis_klassen_sync.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.klasse import Klasse
from app.services.nutzer_klasse_sync import seed_nutzer_klasse_from_webuntis


async def sync_klassen(client: WebUntisClient, db: AsyncSession) -> None:
    """getKlassen -> klasse (Upsert nach webuntis_id), danach nutzer_klasse-Seeding (TECH-SPEC.md Abschnitt 1.2)."""
    rows = await client.call("getKlassen", {})

    existing = (await db.execute(select(Klasse))).scalars().all()
    by_webuntis_id = {klasse.webuntis_id: klasse for klasse in existing}

    for row in rows:
        klasse = by_webuntis_id.get(row["id"])
        if klasse is None:
            klasse = Klasse(webuntis_id=row["id"], name=row["name"])
            db.add(klasse)
        else:
            klasse.name = row["name"]
        klasse.webuntis_teacher1_id = row.get("teacher1")
        klasse.webuntis_teacher2_id = row.get("teacher2")

    await db.flush()
    await seed_nutzer_klasse_from_webuntis(db)
```

```python
# backend/app/services/webuntis_kategorie_sync.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.classreg_category import ClassregCategory


async def sync_kategorien(client: WebUntisClient, db: AsyncSession) -> None:
    """getClassregCategories + getClassregCategoryGroups -> classreg_category (TECH-SPEC.md Abschnitt 1.2)."""
    categories = await client.call("getClassregCategories", {})
    groups = await client.call("getClassregCategoryGroups", {})
    group_name_by_id = {group["id"]: group["name"] for group in groups}

    existing = (await db.execute(select(ClassregCategory))).scalars().all()
    by_webuntis_id = {kategorie.webuntis_id: kategorie for kategorie in existing}

    for row in categories:
        kategorie = by_webuntis_id.get(row["id"])
        if kategorie is None:
            kategorie = ClassregCategory(webuntis_id=row["id"], name=row["name"])
            db.add(kategorie)
        else:
            kategorie.name = row["name"]
        kategorie.long_name = row.get("longName")
        kategorie.group_name = group_name_by_id.get(row.get("groupId"))

    await db.commit()
```

> `seed_nutzer_klasse_from_webuntis` committet bereits selbst (Plan 1) — `sync_klassen` flusht davor, damit die neuen/aktualisierten `Klasse`-Zeilen für das Seeding sichtbar sind, verlässt sich aber für den finalen Commit auf den Seeding-Aufruf selbst.

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_klassen_sync.py tests/test_webuntis_kategorie_sync.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/webuntis_klassen_sync.py backend/app/services/webuntis_kategorie_sync.py backend/tests/test_webuntis_klassen_sync.py backend/tests/test_webuntis_kategorie_sync.py
git commit -m "feat: add WebUntis Klasse and ClassregCategory sync"
```

---

### Task 3: ASV-BW-CSV-Import (Schüler-Stammdaten & Klassenzuordnung)

**Files:**
- Modify: `backend/app/models/schueler.py` (`externe_id` statt `webuntis_id`/`webuntis_key`)
- Modify: `backend/app/models/einstellung.py` (neues Feld `asv_csv_zuletzt_importiert_mtime`)
- Modify: `backend/app/core/config.py` (ASV-CSV-Settings)
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_models_schueler.py` (Plan 1 — `webuntis_id`/`webuntis_key` → `externe_id`)
- Modify: `backend/tests/test_models_klassenbuch.py` (Plan 1 — `webuntis_id` → `externe_id`)
- Create: `backend/app/services/asv_csv_import.py`
- Test: `backend/tests/test_asv_csv_import.py`

**Interfaces:**
- Consumes: `Klasse` (Plan 1), `Einstellung` (Plan 1, erweitert).
- Produces: `asv_csv_import.import_schueler(db: AsyncSession) -> None` — ab Task 6 vom Orchestrator aufgerufen. `Schueler.externe_id` — ab Task 4/5 als Join-Key für `fehlzeit`/`klassenbuch_eintrag` genutzt.

- [ ] **Step 1: Modelle & Config anpassen, Config-Test entsprechend anpassen**

```python
# backend/app/models/schueler.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Schueler(Base, TimestampMixin):
    __tablename__ = "schueler"

    id: Mapped[int] = mapped_column(primary_key=True)
    externe_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    vorname: Mapped[str] = mapped_column(String(100))
    nachname: Mapped[str] = mapped_column(String(100))
    klasse_id: Mapped[int | None] = mapped_column(ForeignKey("klasse.id"), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    klassenzuordnung_aktualisiert_am: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

> `externe_id` ist die ASV-BW-`idnumber`-Spalte, identisch mit der `studentId`/`studentid`-UUID in Fehlzeiten/Klassenbuch (TECH-SPEC.md Abschnitt 1.3). `webuntis_id`/`webuntis_key` (aus `getStudents`) entfallen ersatzlos — `getStudents` wird in diesem Plan nicht mehr aufgerufen.

```python
# backend/app/models/einstellung.py
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Einstellung(Base, TimestampMixin):
    __tablename__ = "einstellung"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_interval_cron: Mapped[str] = mapped_column(String(50), default="*/30 * * * *")
    schuljahr_start_cache: Mapped[date | None] = mapped_column(Date, nullable=True)
    initialer_import_abgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)
    asv_csv_zuletzt_importiert_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str
    webuntis_server: str
    webuntis_school: str
    webuntis_username: str
    webuntis_password: str
    asv_csv_path: str
    asv_csv_column_externe_id: str = "idnumber"
    asv_csv_column_vorname: str = "firstname"
    asv_csv_column_nachname: str = "lastname"
    asv_csv_column_klasse: str = "Klasse"
    asv_csv_column_eintrittsdatum: str = "Eintrittsdatum"
    asv_csv_column_austrittsdatum: str = "Austrittsdatum"


settings = Settings()
```

```text
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash
WORDPRESS_PROXY_SECRET=changeme
WEBUNTIS_SERVER=changeme.webuntis.com
WEBUNTIS_SCHOOL=changeme
WEBUNTIS_USERNAME=changeme
WEBUNTIS_PASSWORD=changeme
ASV_CSV_PATH=/data/asv-export/schueler.csv
```

> `ASV_CSV_PATH` ist Pflicht (kein Default) — analog zu Task 1 in `backend/.env` ergänzen:
> Run: `grep -q ASV_CSV_PATH backend/.env || echo "ASV_CSV_PATH=/tmp/schueler.csv" >> backend/.env`
> Die Spalten-Settings (`ASV_CSV_COLUMN_*`) haben Defaults passend zur Referenzschule und müssen nicht gesetzt werden.

- [ ] **Step 2: Bestehende Modell-Tests aus Plan 1 anpassen**

```python
# backend/tests/test_models_schueler.py
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_schueler_roundtrip(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()

    schueler = Schueler(
        externe_id="8a9041a6-95a2b47f-0195-a30963ad-0018",
        vorname="Max",
        nachname="Mustermann",
        klasse_id=klasse.id,
        aktiv=True,
    )
    db_session.add(schueler)
    await db_session.commit()

    result = await db_session.execute(
        select(Schueler).where(Schueler.externe_id == "8a9041a6-95a2b47f-0195-a30963ad-0018")
    )
    loaded = result.scalar_one()
    assert loaded.nachname == "Mustermann"
    assert loaded.aktiv is True
    assert loaded.klasse_id == klasse.id


@pytest.mark.asyncio
async def test_fehlzeit_unique_constraint_prevents_duplicate_sync(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    excuse_status = ExcuseStatus(name="nicht entsch.", long_name="nicht entschuldigt", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, excuse_status])
    await db_session.flush()

    kwargs = dict(
        schueler_id=schueler.id,
        typ="stunde",
        datum=datetime.date(2026, 7, 1),
        start_zeit=730,
        end_zeit=815,
        fach="Deutsch",
        excuse_status_id=excuse_status.id,
    )
    db_session.add(Fehlzeit(**kwargs))
    await db_session.commit()

    db_session.add(Fehlzeit(**kwargs))
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

```python
# backend/tests/test_models_klassenbuch.py
import datetime

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_klassenbuch_eintrag_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    kategorie = ClassregCategory(name="stören", long_name="Störung des Unterrichts", group_name="Störung")
    db_session.add_all([schueler, kategorie])
    await db_session.flush()

    eintrag = KlassenbuchEintrag(
        webuntis_id=19245,
        schueler_id=schueler.id,
        kategorie_id=kategorie.id,
        datum=datetime.date(2026, 6, 23),
        text="Hat gestört",
        lesson_id=152327,
        erstellt_von_teacher_id=51,
        geaendert_von_teacher_id=51,
    )
    db_session.add(eintrag)
    await db_session.commit()

    result = await db_session.execute(select(KlassenbuchEintrag).where(KlassenbuchEintrag.webuntis_id == 19245))
    loaded = result.scalar_one()
    assert loaded.text == "Hat gestört"
    assert loaded.kategorie_id == kategorie.id
```

- [ ] **Step 3: Migration erzeugen und anwenden**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "replace schueler webuntis_id/webuntis_key with externe_id, add einstellung.asv_csv_zuletzt_importiert_mtime"`
Expected: Neue Migrationsdatei mit `drop_column('schueler', 'webuntis_id')`, `drop_column('schueler', 'webuntis_key')`, `add_column('schueler', sa.Column('externe_id', ...))`, `add_column('einstellung', sa.Column('asv_csv_zuletzt_importiert_mtime', ...))`.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration angewendet, keine Fehler.

- [ ] **Step 4: Bestehende Tests ausführen, Fehlschlag durch angepasste Assertions bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_schueler.py tests/test_models_klassenbuch.py -v`
Expected: PASS — bestätigt, dass Modell + angepasste Tests konsistent sind (kein neuer Fehlschlag erwartet, da Step 1+2 zusammen geändert wurden; dies ist die Verifikation nach der Migration).

- [ ] **Step 5: Fehlschlagenden Test für den CSV-Import schreiben**

```python
# backend/tests/test_asv_csv_import.py
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.services.asv_csv_import import import_schueler

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "schueler.csv"
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _set_csv_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asv_csv_path", str(tmp_path / "schueler.csv"))


@pytest.mark.asyncio
async def test_import_creates_schueler_with_matching_klasse(db_session, tmp_path):
    db_session.add(Klasse(webuntis_id=1, name="AME56"))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"abcd-0018";"abcd-0018";"ext-uuid-1";"Mustermann";"Frank";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-1"))
    schueler = result.scalar_one()
    assert schueler.vorname == "Frank"
    assert schueler.nachname == "Mustermann"
    assert schueler.aktiv is True
    klasse_result = await db_session.execute(select(Klasse).where(Klasse.id == schueler.klasse_id))
    assert klasse_result.scalar_one().name == "AME56"


@pytest.mark.asyncio
async def test_import_leaves_klasse_id_null_for_unknown_klasse(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-2";"Nachname";"Vorname";"";"UNBEKANNT";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-2"))
    assert result.scalar_one().klasse_id is None


@pytest.mark.asyncio
async def test_import_marks_schueler_inactive_after_austrittsdatum(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-3";"Nachname";"Vorname";"";"AME56";"01.01.1990";"26.09.2025";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-3"))
    assert result.scalar_one().aktiv is False


@pytest.mark.asyncio
async def test_import_updates_existing_schueler_by_externe_id(db_session, tmp_path):
    db_session.add(Schueler(externe_id="ext-uuid-4", vorname="Alt", nachname="Name", aktiv=False))
    await db_session.commit()

    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-4";"Name";"Neu";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-4"))
    assert result.scalar_one().vorname == "Neu"


@pytest.mark.asyncio
async def test_import_skips_reprocessing_when_file_unchanged(db_session, tmp_path):
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-uuid-5";"Nachname";"Vorname";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)
    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-5"))
    schueler = result.scalar_one()
    schueler.vorname = "ManuellGeaendert"
    await db_session.commit()

    await import_schueler(db_session)

    result = await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-uuid-5"))
    assert result.scalar_one().vorname == "ManuellGeaendert"
```

- [ ] **Step 6: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_asv_csv_import.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.asv_csv_import'`

- [ ] **Step 7: Implementieren**

```python
# backend/app/services/asv_csv_import.py
from __future__ import annotations

import csv
import logging
import os
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.einstellung import Einstellung
from app.models.klasse import Klasse
from app.models.schueler import Schueler

logger = logging.getLogger(__name__)


def _parse_datum(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%d.%m.%Y").date()


async def import_schueler(db: AsyncSession) -> None:
    """ASV-BW-CSV -> schueler (Upsert nach externe_id), TECH-SPEC.md Abschnitt 1.3.

    Überspringt Parsen+Upsert, wenn die Datei-mtime seit dem letzten Lauf unverändert ist.
    """
    mtime = datetime.fromtimestamp(os.path.getmtime(settings.asv_csv_path), tz=timezone.utc)

    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None:
        einstellung = Einstellung()
        db.add(einstellung)
        await db.flush()

    if einstellung.asv_csv_zuletzt_importiert_mtime is not None and mtime <= einstellung.asv_csv_zuletzt_importiert_mtime:
        return

    klasse_id_by_name = dict((await db.execute(select(Klasse.name, Klasse.id))).all())
    existing = (await db.execute(select(Schueler))).scalars().all()
    by_externe_id = {schueler.externe_id: schueler for schueler in existing}

    heute = datetime.now(timezone.utc).date()

    with open(settings.asv_csv_path, encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";")
        for row in reader:
            externe_id = row[settings.asv_csv_column_externe_id]
            klasse_name = row[settings.asv_csv_column_klasse]
            eintrittsdatum = _parse_datum(row[settings.asv_csv_column_eintrittsdatum])
            austrittsdatum = _parse_datum(row[settings.asv_csv_column_austrittsdatum])

            klasse_id = klasse_id_by_name.get(klasse_name)
            if klasse_id is None:
                logger.warning("ASV-CSV: unbekannte Klasse %r für externe_id=%s", klasse_name, externe_id)

            schueler = by_externe_id.get(externe_id)
            if schueler is None:
                schueler = Schueler(externe_id=externe_id)
                db.add(schueler)
                by_externe_id[externe_id] = schueler

            schueler.vorname = row[settings.asv_csv_column_vorname]
            schueler.nachname = row[settings.asv_csv_column_nachname]
            schueler.klasse_id = klasse_id
            schueler.aktiv = bool(
                eintrittsdatum is not None
                and eintrittsdatum <= heute
                and (austrittsdatum is None or austrittsdatum >= heute)
            )
            schueler.klassenzuordnung_aktualisiert_am = datetime.now(timezone.utc)

    einstellung.asv_csv_zuletzt_importiert_mtime = mtime
    await db.commit()
```

- [ ] **Step 8: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_asv_csv_import.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/schueler.py backend/app/models/einstellung.py backend/app/core/config.py backend/.env.example backend/tests/test_models_schueler.py backend/tests/test_models_klassenbuch.py backend/app/services/asv_csv_import.py backend/tests/test_asv_csv_import.py backend/alembic/versions
git commit -m "feat: replace WebUntis student roster with ASV-BW CSV import"
```

---

### Task 4: Fehlzeiten-Sync

**Files:**
- Create: `backend/app/services/webuntis_fehlzeit_sync.py`
- Test: `backend/tests/test_webuntis_fehlzeit_sync.py`

**Interfaces:**
- Consumes: `WebUntisClient` (Task 1), `Schueler.externe_id` (Task 3), `ExcuseStatus` (Plan 1), `Fehlzeit` (Plan 1).
- Produces: `webuntis_fehlzeit_sync.sync_fehlzeiten(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None` — ab Task 6 vom Orchestrator aufgerufen.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_webuntis_fehlzeit_sync.py
import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.services.webuntis_fehlzeit_sync import sync_fehlzeiten


@pytest.mark.asyncio
async def test_sync_fehlzeiten_creates_tag_and_stunde_entries(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1",
                "subjectId": "", "checked": False, "invalid": False,
            },
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "absenceReason": "", "excuseStatus": None, "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = {f.typ: f for f in result.scalars().all()}
    assert rows["tag"].start_zeit == 0
    assert rows["stunde"].fach == "Deutsch"
    client.call.assert_awaited_once_with(
        "getTimetableWithAbsences", {"options": {"startDate": 20260601, "endDate": 20260630}}
    )


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_invalid_entries(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {"date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1", "subjectId": "", "invalid": True},
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_skips_unknown_externe_id(db_session):
    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {"date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "unbekannt", "subjectId": "", "invalid": False},
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_fehlzeiten_resolves_excuse_status_by_name(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    excuse_status = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, excuse_status])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "Deutsch", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == excuse_status.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_upserts_existing_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    existing = Fehlzeit(
        schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 6, 24), start_zeit=0, end_zeit=2359
    )
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 0, "endTime": 2359, "studentId": "ext-1",
                "subjectId": "", "status": "irregular", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit))
    assert len(result.scalars().all()) == 1
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.webuntis_fehlzeit_sync'`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/webuntis_fehlzeit_sync.py
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler

logger = logging.getLogger(__name__)


def _to_webuntis_date(value: date) -> int:
    return int(value.strftime("%Y%m%d"))


def _from_webuntis_date(value: int) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


async def sync_fehlzeiten(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None:
    """getTimetableWithAbsences -> fehlzeit (TECH-SPEC.md Abschnitt 1.2, 1.3).

    schueler_id wird über Schueler.externe_id aufgelöst (identisch mit studentId-UUID) -
    kein Namensabgleich noetig, siehe TECH-SPEC.md Abschnitt 1.3.
    """
    result = await client.call(
        "getTimetableWithAbsences",
        {"options": {"startDate": _to_webuntis_date(von), "endDate": _to_webuntis_date(bis)}},
    )
    entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result

    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())

    existing = (await db.execute(select(Fehlzeit))).scalars().all()
    by_key = {(f.schueler_id, f.datum, f.start_zeit, f.end_zeit, f.typ): f for f in existing}

    for row in entries or []:
        if row.get("invalid"):
            continue

        schueler_id = schueler_id_by_externe_id.get(row["studentId"])
        if schueler_id is None:
            logger.warning("Fehlzeiten-Sync: unbekannte externe_id=%s, uebersprungen", row["studentId"])
            continue

        typ = "stunde" if row.get("subjectId") else "tag"
        datum = _from_webuntis_date(row["date"])
        start_zeit = row["startTime"]
        end_zeit = row["endTime"]

        key = (schueler_id, datum, start_zeit, end_zeit, typ)
        fehlzeit = by_key.get(key)
        if fehlzeit is None:
            fehlzeit = Fehlzeit(
                schueler_id=schueler_id, datum=datum, start_zeit=start_zeit, end_zeit=end_zeit, typ=typ
            )
            db.add(fehlzeit)
            by_key[key] = fehlzeit

        fehlzeit.fach = row.get("subjectId") or None
        fehlzeit.grund_text = row.get("absenceReason") or None
        fehlzeit.excuse_status_id = excuse_status_id_by_name.get(row.get("excuseStatus"))
        fehlzeit.invalid = False

    await db.commit()
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/webuntis_fehlzeit_sync.py backend/tests/test_webuntis_fehlzeit_sync.py
git commit -m "feat: add WebUntis Fehlzeit sync resolved via externe_id"
```

---

### Task 5: Klassenbuch-Sync

**Files:**
- Create: `backend/app/services/webuntis_klassenbuch_sync.py`
- Test: `backend/tests/test_webuntis_klassenbuch_sync.py`

**Interfaces:**
- Consumes: `WebUntisClient` (Task 1), `Schueler.externe_id` (Task 3), `ClassregCategory` (Plan 1, Task 2), `KlassenbuchEintrag` (Plan 1).
- Produces: `webuntis_klassenbuch_sync.sync_klassenbuch(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None` — ab Task 6 vom Orchestrator aufgerufen.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_webuntis_klassenbuch_sync.py
import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler
from app.services.webuntis_klassenbuch_sync import sync_klassenbuch


@pytest.mark.asyncio
async def test_sync_klassenbuch_creates_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    kategorie = ClassregCategory(name="stören")
    db_session.add_all([schueler, kategorie])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {
            "eventId": 19245, "studentid": "ext-1", "subject": "stören", "date": 20260623,
            "text": "Hat gestört", "lessonId": 152327,
            "createTeacher": {"id": 51, "name": "X"}, "updateTeacher": {"id": 51, "name": "X"},
        }
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag).where(KlassenbuchEintrag.webuntis_id == 19245))
    eintrag = result.scalar_one()
    assert eintrag.schueler_id == schueler.id
    assert eintrag.kategorie_id == kategorie.id
    assert eintrag.text == "Hat gestört"
    assert eintrag.erstellt_von_teacher_id == 51
    client.call.assert_awaited_once_with("getClassregEvents", {"startDate": 20260601, "endDate": 20260630})


@pytest.mark.asyncio
async def test_sync_klassenbuch_skips_unknown_externe_id(db_session):
    kategorie = ClassregCategory(name="stören")
    db_session.add(kategorie)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"eventId": 1, "studentid": "unbekannt", "subject": "stören", "date": 20260623, "text": ""}
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_klassenbuch_skips_unknown_kategorie(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"eventId": 1, "studentid": "ext-1", "subject": "unbekannt", "date": 20260623, "text": ""}
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_sync_klassenbuch_upserts_existing_entry(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    kategorie = ClassregCategory(name="stören")
    db_session.add_all([schueler, kategorie])
    await db_session.commit()

    existing = KlassenbuchEintrag(
        webuntis_id=1, schueler_id=schueler.id, kategorie_id=kategorie.id,
        datum=datetime.date(2026, 6, 23), text="alt",
    )
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"eventId": 1, "studentid": "ext-1", "subject": "stören", "date": 20260623, "text": "neu"}
    ]

    await sync_klassenbuch(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(KlassenbuchEintrag))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].text == "neu"
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_klassenbuch_sync.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.webuntis_klassenbuch_sync'`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/webuntis_klassenbuch_sync.py
from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.classreg_category import ClassregCategory
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler

logger = logging.getLogger(__name__)


def _to_webuntis_date(value: date) -> int:
    return int(value.strftime("%Y%m%d"))


def _from_webuntis_date(value: int) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


async def sync_klassenbuch(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None:
    """getClassregEvents -> klassenbuch_eintrag (TECH-SPEC.md Abschnitt 1.2, 1.3)."""
    rows = await client.call(
        "getClassregEvents", {"startDate": _to_webuntis_date(von), "endDate": _to_webuntis_date(bis)}
    )

    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    kategorie_id_by_name = dict((await db.execute(select(ClassregCategory.name, ClassregCategory.id))).all())

    existing = (await db.execute(select(KlassenbuchEintrag))).scalars().all()
    by_webuntis_id = {e.webuntis_id: e for e in existing}

    for row in rows or []:
        schueler_id = schueler_id_by_externe_id.get(row["studentid"])
        if schueler_id is None:
            logger.warning("Klassenbuch-Sync: unbekannte externe_id=%s, uebersprungen", row["studentid"])
            continue

        kategorie_id = kategorie_id_by_name.get(row["subject"])
        if kategorie_id is None:
            logger.warning("Klassenbuch-Sync: unbekannte Kategorie %r, uebersprungen", row["subject"])
            continue

        eintrag = by_webuntis_id.get(row["eventId"])
        if eintrag is None:
            eintrag = KlassenbuchEintrag(
                webuntis_id=row["eventId"], schueler_id=schueler_id, kategorie_id=kategorie_id
            )
            db.add(eintrag)
            by_webuntis_id[row["eventId"]] = eintrag
        else:
            eintrag.schueler_id = schueler_id
            eintrag.kategorie_id = kategorie_id

        eintrag.datum = _from_webuntis_date(row["date"])
        eintrag.text = row.get("text") or None
        eintrag.lesson_id = row.get("lessonId")
        eintrag.erstellt_von_teacher_id = (row.get("createTeacher") or {}).get("id")
        eintrag.geaendert_von_teacher_id = (row.get("updateTeacher") or {}).get("id")

    await db.commit()
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_webuntis_klassenbuch_sync.py -v`
Expected: PASS (4 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/webuntis_klassenbuch_sync.py backend/tests/test_webuntis_klassenbuch_sync.py
git commit -m "feat: add WebUntis Klassenbuch sync resolved via externe_id"
```

---

### Task 6: Orchestrierung (Retry, Schuljahr-Erkennung)

**Files:**
- Modify: `backend/app/models/einstellung.py` (neues Feld `letzter_sync_am`)
- Modify: `backend/app/core/config.py` (Retry-Settings)
- Create: `backend/app/services/sync_orchestrator.py`
- Test: `backend/tests/test_sync_orchestrator.py`

**Interfaces:**
- Consumes: alle Sync-Funktionen aus Task 2, 3, 4, 5; `WebUntisClient`/`WebUntisError` (Task 1).
- Produces: `sync_orchestrator.run_full_sync(db: AsyncSession) -> None` — ab Task 7 vom Scheduler aufgerufen.

**Wichtiger Hinweis zur Fehlerbehandlung:** `sync_klassen` (via `seed_nutzer_klasse_from_webuntis`, Plan 1), `sync_kategorien` und `import_schueler` committen bereits einzeln innerhalb ihrer eigenen Funktion (Tasks 2/3). Ein Retry auf Orchestrator-Ebene rollt frühere, bereits committete Phasen eines fehlgeschlagenen Versuchs daher **nicht** zurück — das ist unkritisch, weil jede Phase über einen stabilen externen Key upsert (idempotent): ein Retry wiederholt einfach den gesamten Ablauf, ohne Duplikate oder inkonsistente Daten zu erzeugen. `db.rollback()` im Fehlerfall räumt nur noch nicht committete Änderungen der zuletzt fehlgeschlagenen Phase auf.

- [ ] **Step 1: Modell & Config erweitern**

```python
# backend/app/models/einstellung.py
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Einstellung(Base, TimestampMixin):
    __tablename__ = "einstellung"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_interval_cron: Mapped[str] = mapped_column(String(50), default="*/30 * * * *")
    schuljahr_start_cache: Mapped[date | None] = mapped_column(Date, nullable=True)
    initialer_import_abgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)
    asv_csv_zuletzt_importiert_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    letzter_sync_am: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str
    webuntis_server: str
    webuntis_school: str
    webuntis_username: str
    webuntis_password: str
    asv_csv_path: str
    asv_csv_column_externe_id: str = "idnumber"
    asv_csv_column_vorname: str = "firstname"
    asv_csv_column_nachname: str = "lastname"
    asv_csv_column_klasse: str = "Klasse"
    asv_csv_column_eintrittsdatum: str = "Eintrittsdatum"
    asv_csv_column_austrittsdatum: str = "Austrittsdatum"
    webuntis_sync_retry_delay_minutes: int = 30
    webuntis_sync_retry_max_attempts: int = 4


settings = Settings()
```

- [ ] **Step 2: Migration erzeugen und anwenden**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add einstellung.letzter_sync_am"`
Expected: Neue Migrationsdatei mit `add_column('einstellung', sa.Column('letzter_sync_am', ...))`.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration angewendet, keine Fehler.

- [ ] **Step 3: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_sync_orchestrator.py
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisError
from app.models.einstellung import Einstellung
from app.services import sync_orchestrator


class _FakeWebUntisClient:
    def __init__(self, _settings):
        self.call = AsyncMock(return_value={"startDate": 20250915, "endDate": 20260729})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


@pytest.fixture(autouse=True)
def _patch_phases(monkeypatch):
    monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClient)
    monkeypatch.setattr(sync_orchestrator, "sync_klassen", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_kategorien", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "import_schueler", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_fehlzeiten", AsyncMock())
    monkeypatch.setattr(sync_orchestrator, "sync_klassenbuch", AsyncMock())


@pytest.mark.asyncio
async def test_run_full_sync_sets_letzter_sync_am_and_initial_import_flag(db_session):
    await sync_orchestrator.run_full_sync(db_session)

    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalar_one()
    assert einstellung.letzter_sync_am is not None
    assert einstellung.initialer_import_abgeschlossen is True
    assert einstellung.schuljahr_start_cache is not None


@pytest.mark.asyncio
async def test_run_full_sync_calls_phases_in_order(db_session):
    calls = []
    sync_orchestrator.sync_klassen.side_effect = lambda *a: calls.append("klassen")
    sync_orchestrator.sync_kategorien.side_effect = lambda *a: calls.append("kategorien")
    sync_orchestrator.import_schueler.side_effect = lambda *a: calls.append("schueler")
    sync_orchestrator.sync_fehlzeiten.side_effect = lambda *a: calls.append("fehlzeiten")
    sync_orchestrator.sync_klassenbuch.side_effect = lambda *a: calls.append("klassenbuch")

    await sync_orchestrator.run_full_sync(db_session)

    assert calls == ["klassen", "kategorien", "schueler", "fehlzeiten", "klassenbuch"]


@pytest.mark.asyncio
async def test_run_full_sync_retries_on_failure_and_succeeds(db_session, monkeypatch):
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 3)
    sync_orchestrator.sync_fehlzeiten.side_effect = [WebUntisError("boom"), None]

    await sync_orchestrator.run_full_sync(db_session)

    assert sync_orchestrator.sync_fehlzeiten.await_count == 2
    result = await db_session.execute(select(Einstellung))
    assert result.scalar_one().letzter_sync_am is not None


@pytest.mark.asyncio
async def test_run_full_sync_gives_up_after_max_attempts(db_session, monkeypatch):
    sleep_mock = AsyncMock()
    monkeypatch.setattr(sync_orchestrator.asyncio, "sleep", sleep_mock)
    monkeypatch.setattr(settings, "webuntis_sync_retry_delay_minutes", 30)
    monkeypatch.setattr(settings, "webuntis_sync_retry_max_attempts", 2)
    sync_orchestrator.sync_fehlzeiten.side_effect = WebUntisError("boom")

    await sync_orchestrator.run_full_sync(db_session)

    assert sync_orchestrator.sync_fehlzeiten.await_count == 2
    assert sleep_mock.await_count == 1
    result = await db_session.execute(select(Einstellung))
    einstellung = result.scalars().first()
    assert einstellung is None or einstellung.letzter_sync_am is None
```

- [ ] **Step 4: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_sync_orchestrator.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.sync_orchestrator'`

- [ ] **Step 5: Implementieren**

```python
# backend/app/services/sync_orchestrator.py
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.einstellung import Einstellung
from app.services.asv_csv_import import import_schueler
from app.services.webuntis_fehlzeit_sync import sync_fehlzeiten
from app.services.webuntis_kategorie_sync import sync_kategorien
from app.services.webuntis_klassen_sync import sync_klassen
from app.services.webuntis_klassenbuch_sync import sync_klassenbuch

logger = logging.getLogger(__name__)


async def _get_or_create_einstellung(db: AsyncSession) -> Einstellung:
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None:
        einstellung = Einstellung()
        db.add(einstellung)
        await db.flush()
    return einstellung


def _fehlzeiten_zeitraum(einstellung: Einstellung, heute: date) -> tuple[date, date]:
    if einstellung.letzter_sync_am is not None:
        von = einstellung.letzter_sync_am.date() - timedelta(days=1)
    elif einstellung.schuljahr_start_cache is not None:
        von = einstellung.schuljahr_start_cache
    else:
        von = heute
    return von, heute


async def _run_once(db: AsyncSession) -> None:
    async with WebUntisClient(settings) as client:
        await sync_klassen(client, db)
        await sync_kategorien(client, db)
        await import_schueler(db)

        einstellung = await _get_or_create_einstellung(db)

        schuljahr = await client.call("getCurrentSchoolyear", {})
        schuljahr_start = datetime.strptime(str(schuljahr["startDate"]), "%Y%m%d").date()
        if schuljahr_start != einstellung.schuljahr_start_cache:
            einstellung.schuljahr_start_cache = schuljahr_start

        heute = datetime.now(timezone.utc).date()
        von, bis = _fehlzeiten_zeitraum(einstellung, heute)
        await sync_fehlzeiten(client, db, von, bis)
        await sync_klassenbuch(client, db, von, bis)

        einstellung.letzter_sync_am = datetime.now(timezone.utc)
        if not einstellung.initialer_import_abgeschlossen:
            einstellung.initialer_import_abgeschlossen = True
        await db.commit()


async def run_full_sync(db: AsyncSession) -> None:
    """Orchestriert einen vollstaendigen WebUntis-Sync-Lauf mit Retry (TECH-SPEC.md Abschnitt 1.3b)."""
    max_attempts = settings.webuntis_sync_retry_max_attempts
    delay_seconds = settings.webuntis_sync_retry_delay_minutes * 60

    for attempt in range(1, max_attempts + 1):
        try:
            await _run_once(db)
            return
        except (WebUntisError, OSError) as exc:
            await db.rollback()
            logger.warning("Sync-Lauf fehlgeschlagen (Versuch %d/%d): %s", attempt, max_attempts, exc)
            if attempt == max_attempts:
                logger.error("Sync-Lauf endgueltig abgebrochen nach %d Versuchen", max_attempts)
                return
            await asyncio.sleep(delay_seconds)
```

- [ ] **Step 6: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_sync_orchestrator.py -v`
Expected: PASS (4 Tests)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/einstellung.py backend/app/core/config.py backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py backend/alembic/versions
git commit -m "feat: add sync orchestrator with retry and schoolyear detection"
```

---

### Task 7: Scheduler (APScheduler, FastAPI-Lifespan)

**Files:**
- Create: `backend/app/core/scheduler.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `run_full_sync` (Task 6), `Einstellung.sync_interval_cron` (Plan 1).
- Produces: `scheduler.create_scheduler() -> AsyncIOScheduler`, `scheduler.start_scheduler(scheduler: AsyncIOScheduler) -> None`, `scheduler.MAIN_SYNC_JOB_ID` — von `app.main`s Lifespan-Hook genutzt.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_scheduler.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import scheduler as scheduler_module
from app.models.einstellung import Einstellung


@pytest.mark.asyncio
async def test_start_scheduler_registers_job_with_configured_cron(db_session):
    db_session.add(Einstellung(sync_interval_cron="*/15 * * * *"))
    await db_session.commit()

    scheduler = scheduler_module.create_scheduler()
    try:
        await scheduler_module.start_scheduler(scheduler)
        job = scheduler.get_job(scheduler_module.MAIN_SYNC_JOB_ID)
        assert job is not None

        now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
        next_fire = job.trigger.get_next_fire_time(None, now)
        assert next_fire.minute == 15
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_start_scheduler_falls_back_to_default_cron_without_einstellung(db_session):
    scheduler = scheduler_module.create_scheduler()
    try:
        await scheduler_module.start_scheduler(scheduler)
        job = scheduler.get_job(scheduler_module.MAIN_SYNC_JOB_ID)
        assert job is not None

        now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
        next_fire = job.trigger.get_next_fire_time(None, now)
        assert next_fire.minute == 30
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_run_main_sync_job_runs_sync_and_reschedules(monkeypatch, db_session):
    db_session.add(Einstellung(sync_interval_cron="*/20 * * * *"))
    await db_session.commit()

    run_full_sync_mock = AsyncMock()
    monkeypatch.setattr(scheduler_module, "run_full_sync", run_full_sync_mock)

    fake_scheduler = Mock()
    await scheduler_module._run_main_sync_job(fake_scheduler)

    run_full_sync_mock.assert_awaited_once()
    fake_scheduler.reschedule_job.assert_called_once()
    args, kwargs = fake_scheduler.reschedule_job.call_args
    assert args[0] == scheduler_module.MAIN_SYNC_JOB_ID
    now = datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)
    next_fire = kwargs["trigger"].get_next_fire_time(None, now)
    assert next_fire.minute == 20
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_scheduler.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.core.scheduler'`

- [ ] **Step 3: Implementieren**

```python
# backend/app/core/scheduler.py
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.einstellung import Einstellung
from app.services.sync_orchestrator import run_full_sync

MAIN_SYNC_JOB_ID = "webuntis_main_sync"


async def _read_sync_interval_cron() -> str:
    async with async_session_factory() as db:
        result = await db.execute(select(Einstellung))
        einstellung = result.scalars().first()
        return einstellung.sync_interval_cron if einstellung else "*/30 * * * *"


async def _run_main_sync_job(scheduler: AsyncIOScheduler) -> None:
    async with async_session_factory() as db:
        await run_full_sync(db)
    cron_expr = await _read_sync_interval_cron()
    scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=CronTrigger.from_crontab(cron_expr))


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


async def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    cron_expr = await _read_sync_interval_cron()
    scheduler.add_job(
        _run_main_sync_job,
        trigger=CronTrigger.from_crontab(cron_expr),
        id=MAIN_SYNC_JOB_ID,
        args=[scheduler],
        replace_existing=True,
    )
    scheduler.start()
```

> Nur **ein** Job (Haupt-Sync) — die frühere separate nächtliche Klassenzuordnungs-Refresh-Batch entfällt (siehe Design-Dokument, Phase 2/4). `_run_main_sync_job` liest `sync_interval_cron` nach jedem Lauf frisch und reschedult sich selbst — Admin-Änderungen an `einstellung.sync_interval_cron` (späterer REST-Endpunkte-Plan) wirken so ab dem nächsten Lauf, ohne Neustart.

```python
# backend/app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.scheduler import create_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    await start_scheduler(scheduler)
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="AbsenzDash Backend", lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

> `backend/tests/test_main.py` (Plan 1) nutzt `httpx.ASGITransport(app=app)` ohne Lifespan-Aufruf — der Scheduler startet dadurch in diesem Test nicht, `test_health_check_returns_ok` bleibt unverändert grün.

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_scheduler.py tests/test_main.py -v`
Expected: PASS (4 Tests aus `test_scheduler.py`, 1 Test aus `test_main.py` weiterhin grün)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/scheduler.py backend/app/main.py backend/tests/test_scheduler.py
git commit -m "feat: add APScheduler-driven sync scheduling with live cron reload"
```

---

### Task 8: Vollständiger Stack-Check & Dokumentation

**Files:**
- Modify: `docs/backend-setup.md`
- Test: manuell (kein pytest-Test — Infrastruktur-Task)

**Interfaces:**
- Consumes: alle vorherigen Tasks.
- Produces: aktualisierte `docs/backend-setup.md` (CLAUDE.md-Konvention: user-/admin-relevante Infos sofort in `docs/`).

- [ ] **Step 1: Vollständige Testsuite gegen den kompletten Stack**

Run: `docker compose -f backend/docker-compose.yml up -d postgres && docker compose -f backend/docker-compose.yml run --rm backend pytest -v`
Expected: Alle Tests aus Plan 1 und Plan 2 PASS (keine Regression durch die `schueler`-Modelländerung aus Task 3).

- [ ] **Step 2: Vollständigen Stack starten und Scheduler-Start verifizieren**

Run: `docker compose -f backend/docker-compose.yml up -d --build`
Expected: Beide Container laufen (`docker compose -f backend/docker-compose.yml ps` zeigt `postgres` als `healthy`, `backend` als `running`).

Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

Run: `docker compose -f backend/docker-compose.yml logs backend | grep -i apscheduler`
Expected: Log-Zeile, die den gestarteten `webuntis_main_sync`-Job bestätigt (APScheduler loggt Job-Hinzufügung beim Start standardmäßig auf INFO-Level).

Run: `docker compose -f backend/docker-compose.yml down`
Expected: Container werden sauber gestoppt.

- [ ] **Step 3: Setup-Dokumentation ergänzen**

```markdown
# docs/backend-setup.md

# Backend-Setup

## Voraussetzungen

- Docker (Python 3.11 läuft ausschließlich containerisiert — auf der Entwicklungsmaschine muss kein Python installiert sein)
- Für den WebUntis-Sync: WebUntis-Service-Account-Zugangsdaten, sowie ein lesbar gemountetes Verzeichnis mit der aktuellen ASV-BW-CSV-Exportdatei (siehe unten)

## Setup

1. `cp backend/.env.example backend/.env` und `WORDPRESS_PROXY_SECRET`, `WEBUNTIS_SERVER`/`_SCHOOL`/`_USERNAME`/`_PASSWORD`, `ASV_CSV_PATH` auf echte Werte setzen.
2. `docker compose -f backend/docker-compose.yml up -d --build`
3. `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`

Das Backend läuft danach unter `http://localhost:8000`, Health-Check unter `GET /health`. Der WebUntis-Sync-Job startet automatisch beim Backend-Start (APScheduler, siehe unten) und läuft nach dem in `einstellung.sync_interval_cron` konfigurierten Intervall (Default: alle 30 Minuten).

## Tests

`docker compose -f backend/docker-compose.yml run --rm backend pytest` (benötigt laufende PostgreSQL-Instanz: `docker compose -f backend/docker-compose.yml up -d postgres`). Jeder Test läuft in einer frisch aufgesetzten Datenbank (`tests/conftest.py` erstellt/verwirft alle Tabellen automatisch pro Test). WebUntis-Calls sind in Tests über `respx`/Mocks abgedeckt — keine echte WebUntis-Instanz nötig.

## Migrationen

Nach jeder Modelländerung: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "<beschreibung>"`, danach `... alembic upgrade head`.

## WebUntis-Sync (ab Plan 2)

- **Ablauf:** Klassen/Kategorien-Sync → ASV-BW-CSV-Import (Schüler-Stammdaten/Klassenzuordnung) → Fehlzeiten-/Klassenbuch-Sync, orchestriert in `app/services/sync_orchestrator.py`. Läuft automatisch nach `einstellung.sync_interval_cron` (APScheduler, `app/core/scheduler.py`), Änderungen an diesem Cron-Wert wirken ab dem nächsten Lauf ohne Neustart.
- **ASV-BW-CSV:** `ASV_CSV_PATH` muss auf ein live-gemountetes Verzeichnis zeigen, in das ein externes System die aktuelle Export-Datei unter festem Dateinamen ablegt (TECH-SPEC.md Abschnitt 1.3). Spaltennamen sind über `ASV_CSV_COLUMN_*`-Env-Vars konfigurierbar, falls sie von der Referenzschule abweichen. Der Import überspringt unveränderte Dateien (mtime-Vergleich) — bei einer neuen Datei mit identischem Namen und späterer mtime wird beim nächsten Sync-Lauf automatisch neu importiert.
- **Retry:** Schlägt ein Sync-Lauf fehl (WebUntis nicht erreichbar, CSV nicht lesbar), wird er bis zu `WEBUNTIS_SYNC_RETRY_MAX_ATTEMPTS`-mal (Default 4) im Abstand von `WEBUNTIS_SYNC_RETRY_DELAY_MINUTES` (Default 30) erneut versucht, bevor er endgültig abgebrochen und geloggt wird.
- **Noch nicht abgedeckt:** manueller "Sync jetzt"-Endpunkt, Eskalations-Engine/Benachrichtigungen (beides spätere Pläne).

## Aktueller Stand

Plan 1 (`docs/superpowers/plans/2026-07-24-backend-grundgeruest.md`) deckt das Datenschema und die WordPress-Proxy-Authentifizierung ab. Plan 2 (dieser Plan, `docs/superpowers/plans/2026-07-24-webuntis-sync.md`) ergänzt den vollständigen WebUntis-Sync inkl. ASV-BW-CSV-Import. Noch **keine** fachlichen REST-Endpunkte (`/students`, `/admin/...`) und keine Eskalations-Engine (Schwellwerte, Benachrichtigungen, Maßnahmen) — beides folgt in separaten Plänen.
```

- [ ] **Step 4: Commit**

```bash
git add docs/backend-setup.md
git commit -m "docs: document WebUntis sync job setup and operation"
```

---

## Self-Review-Notizen

- **Spec-Abdeckung:** TECH-SPEC.md Abschnitt 1.1 (Auth/Retry) → Task 1. Abschnitt 1.2 (Klassen/Kategorien-Feldmapping, Fehlzeiten-Typen, Klassenbuch) → Task 2, 4, 5. Abschnitt 1.3 (ASV-BW-CSV) → Task 3. Abschnitt 1.3a (Schuljahr) → Task 6. Abschnitt 1.3b (Retry, initialer Import) → Task 6. Abschnitt 2.1 (nutzer_klasse-Sync-Verhalten) → Task 2 (ruft bestehende Plan-1-Funktion unverändert auf). SPECS.md Abschnitt 5.1 (initialer Import, keine E-Mails) → Task 6 setzt `initialer_import_abgeschlossen`; der E-Mail-Unterdrückungs-Teil selbst ist Konsument dieses Flags und liegt in Plan 3 (Eskalations-Engine, existiert noch nicht) — korrekt außerhalb dieses Plans.
- **Platzhalter-Scan:** keine TBD/TODO, jeder Code-Schritt enthält vollständigen, lauffähigen Code.
- **Typkonsistenz geprüft:** `Schueler.externe_id` (String) durchgängig in Modell (Task 3), Fehlzeiten-/Klassenbuch-Sync (Task 4/5) und Tests konsistent verwendet — kein `webuntis_id`-Rückstand außerhalb der bewusst dokumentierten Änderung. `WebUntisClient`/`WebUntisError` (Task 1) werden in Task 2, 4, 5, 6 mit identischer Signatur (`call(method: str, params: dict) -> Any`) konsumiert. `sync_klassen`/`sync_kategorien`/`import_schueler`/`sync_fehlzeiten`/`sync_klassenbuch`-Funktionsnamen in Task 6 (Orchestrator-Imports) stimmen exakt mit den in Task 2–5 produzierten Namen überein.
- **Bewusst außerhalb dieses Plans:** `POST /admin/sync-now`-REST-Endpunkt, Eskalations-Engine (Schwellwerte, Zähler, Benachrichtigungen), `excuse_status`-Admin-Pflege, alternative Schüler-Datenquellen (Untis Platform API — laut WebUntis-Support aktuell ohnehin nicht für einzelne Schulen vergeben) — siehe Design-Dokument "Nicht-Ziele".
