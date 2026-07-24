# Backend-Grundgerüst & Datenmodell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein lauffähiges FastAPI-Backend mit vollständigem, per Alembic verwaltetem PostgreSQL-Schema (alle in TECH-SPEC.md Abschnitt 2 dokumentierten Tabellen) und einer funktionierenden WordPress-Proxy-Authentifizierung — ohne WebUntis-Anbindung (folgt in einem separaten Plan "Backend: WebUntis-Sync").

**Architecture:** FastAPI (async) + SQLAlchemy 2.0 (async, `Mapped[]`-Style) + Alembic-Migrationen + PostgreSQL 15, analog zum Referenzprojekt VertretungsFlow, aber mit echten Alembic-Migrationen statt Ad-hoc-SQL-Dateien und einer gemeinsamen `TimestampMixin` (siehe TECH-SPEC.md Abschnitt 2). WordPress-Plugin → Backend-Kommunikation läuft über vertrauenswürdige Header + Shared Secret (TECH-SPEC.md Abschnitt 3).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (asyncpg-Treiber), Alembic, PostgreSQL 15, pytest + pytest-asyncio, httpx (für Tests und später den WebUntis-Client), Docker/docker-compose.

## Global Constraints

- Python-Version: 3.11 (siehe TECH-SPEC.md Abschnitt 2/6).
- Datenbank: PostgreSQL 15 (siehe TECH-SPEC.md Abschnitt 6).
- ORM-Stil: SQLAlchemy 2.0 mit `Mapped[]`-Typannotationen, kein Legacy-`declarative_base()`-Stil (TECH-SPEC.md Abschnitt 2 — bewusste Abweichung von VertretungsFlow).
- Migrationen: ausschließlich über Alembic, keine handgeschriebenen SQL-Dateien (TECH-SPEC.md Abschnitt 2).
- Alle Tabellen außer `audit_log` erhalten `created_at`/`updated_at` über eine gemeinsame `TimestampMixin` (TECH-SPEC.md Abschnitt 2).
- Tabellen-/Feldnamen auf Deutsch, wie in TECH-SPEC.md Abschnitt 2 festgelegt (z.B. `schueler`, `klasse`, `nutzer`).
- Commit-Messages auf Englisch (Nutzer-Vorgabe, globale CLAUDE.md).
- Nach Abschluss dieses Plans: sofort committen; sobald ein Git-Remote existiert, zusätzlich pushen (`CLAUDE.md`).
- User-/Admin-relevante Informationen (Setup, Betrieb) gehören in `docs/`, nicht nur in Commit-Messages (`CLAUDE.md`).
- **Ausführungsumgebung (Nachtrag, ab Task 2):** Auf der Entwicklungsmaschine ist kein Python 3.11 installiert (nur 3.9, kein Homebrew/pyenv). Da ohnehin ein Docker-Deployment geplant ist (TECH-SPEC.md Abschnitt 6), läuft die gesamte Entwicklung ab Task 2 containerisiert. Task 2 richtet dafür `backend/Dockerfile` (Python 3.11-slim) und einen `backend`-Service in `backend/docker-compose.yml` ein. Jeder `Run:`-Befehl in Tasks 2–10, der `python`/`pip`/`pytest`/`alembic`/`uvicorn` aufruft, ist wie folgt zu übersetzen:
  - `cd backend && pytest ...` → `docker compose -f backend/docker-compose.yml run --rm backend pytest ...`
  - `cd backend && alembic ...` → `docker compose -f backend/docker-compose.yml run --rm backend alembic ...`
  - Reine Datei-/Git-Operationen (z.B. `cp .env.example .env`) laufen weiterhin direkt auf dem Host.
  - Vor jedem `run --rm backend ...`-Aufruf muss `docker compose -f backend/docker-compose.yml up -d postgres` gelaufen sein (Postgres muss `healthy` sein).
  - `DATABASE_URL` in `.env`/`.env.example` referenziert deshalb den Docker-Netzwerk-Hostnamen `postgres`, nicht `localhost`.

---

## File Structure

```
backend/
  requirements.txt
  requirements-dev.txt
  pytest.ini
  Dockerfile
  .env.example
  alembic.ini
  alembic/
    env.py
    script.py.mako
    versions/            (von Alembic verwaltet)
  app/
    __init__.py
    main.py
    core/
      __init__.py
      config.py
      database.py
    models/
      __init__.py
      base.py
      klasse.py
      bereich.py
      schueler.py
      excuse_status.py
      fehlzeit.py
      classreg_category.py
      klassenbuch_eintrag.py
      einstellung.py
      audit_log.py
      nutzer.py
      nutzer_klasse.py
      nutzer_bereich.py
    api/
      __init__.py
      deps.py
    services/
      __init__.py
      nutzer_klasse_sync.py
  tests/
    __init__.py
    conftest.py
    test_main.py
    test_database.py
    test_models_klasse.py
    test_models_schueler.py
    test_models_klassenbuch.py
    test_models_einstellung_audit.py
    test_models_nutzer.py
    test_deps_wordpress_proxy.py
    test_nutzer_klasse_sync.py
docker-compose.yml
docs/
  backend-setup.md
```

Jede Modell-Datei hat eine Verantwortung (eine Tabelle bzw. ein eng zusammengehöriges Paar). `app/models/__init__.py` importiert alle Modelle, damit Alembics Autogenerate sie über `Base.metadata` sieht.

---

### Task 1: Projekt-Grundgerüst & Health-Endpoint

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/requirements-dev.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/__init__.py`
- Test: `backend/tests/test_main.py`

**Interfaces:**
- Produces: `app.main.app` (FastAPI-Instanz), Endpoint `GET /health` → `{"status": "ok"}`.

- [ ] **Step 1: Projekt-Grundgerüst anlegen**

```text
# backend/requirements.txt
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
httpx>=0.27,<1.0
```

```text
# backend/requirements-dev.txt
-r requirements.txt
pytest>=8.2,<9.0
pytest-asyncio>=0.23,<1.0
```

```ini
# backend/pytest.ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

```python
# backend/app/__init__.py
```

```python
# backend/tests/__init__.py
```

- [ ] **Step 2: Installieren**

Run: `cd backend && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt`
Expected: Installation ohne Fehler.

- [ ] **Step 3: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_main.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_check_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 4: Test ausführen, Fehlschlag bestätigen**

Run: `cd backend && pytest tests/test_main.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 5: Minimale Implementierung**

```python
# backend/app/main.py
from fastapi import FastAPI

app = FastAPI(title="AbsenzDash Backend")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Test ausführen, Erfolg bestätigen**

Run: `cd backend && pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt backend/pytest.ini backend/app/__init__.py backend/app/main.py backend/tests/__init__.py backend/tests/test_main.py
git commit -m "feat: add FastAPI project skeleton with health endpoint"
```

---

### Task 2: DB-Verbindung, TimestampMixin, Alembic-Setup, Docker-Dev-Umgebung

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/docker-compose.yml`
- Create: `backend/.env.example`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/database.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/base.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Test: `backend/tests/conftest.py`
- Test: `backend/tests/test_database.py`

**Interfaces:**
- Consumes: nichts (Fundament).
- Produces: `app.core.config.settings` (mit `database_url`), `app.core.database.engine`, `app.core.database.async_session_factory`, `app.core.database.get_db()` (FastAPI-Dependency), `app.models.base.Base`, `app.models.base.TimestampMixin`. Außerdem die Docker-Dev-Umgebung, in der alle weiteren Tasks dieses Plans laufen (Global Constraints, "Ausführungsumgebung").

- [ ] **Step 1: Requirements erweitern**

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
```

- [ ] **Step 2: Dockerfile + docker-compose (Postgres + Backend) + .env.example**

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# backend/docker-compose.yml
services:
  postgres:
    image: postgres:15-alpine
    container_name: absenzdash-db
    environment:
      POSTGRES_USER: absenzdash
      POSTGRES_PASSWORD: absenzdash
      POSTGRES_DB: absenzdash
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U absenzdash"]
      interval: 5s
      timeout: 5s
      retries: 5
    volumes:
      - absenzdash-db-data:/var/lib/postgresql/data

  backend:
    build: .
    container_name: absenzdash-backend
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - .:/app

volumes:
  absenzdash-db-data:
```

```text
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash
```

> `postgres` (nicht `localhost`) als Hostname — `backend` und `postgres` kommunizieren über das von docker-compose erzeugte interne Netzwerk (Global Constraints, "Ausführungsumgebung").

Run (vom Repo-Root aus): `cp backend/.env.example backend/.env && docker compose -f backend/docker-compose.yml build backend && docker compose -f backend/docker-compose.yml up -d postgres`
Expected: Backend-Image baut ohne Fehler; `docker compose -f backend/docker-compose.yml ps` zeigt `postgres` als `healthy`.

- [ ] **Step 3: Config und DB-Verbindung**

```python
# backend/app/core/__init__.py
```

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str


settings = Settings()
```

```python
# backend/app/core/database.py
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Step 4: Base + TimestampMixin**

```python
# backend/app/models/__init__.py
from app.models.base import Base

__all__ = ["Base"]
```

```python
# backend/app/models/base.py
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 5: Fehlschlagenden DB-Test schreiben**

```python
# backend/tests/conftest.py
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.models.base import Base


@pytest_asyncio.fixture(autouse=True)
async def _reset_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
```

```python
# backend/tests/test_database.py
import pytest
from sqlalchemy import text

from app.core.database import async_session_factory


@pytest.mark.asyncio
async def test_database_connection_executes_simple_query():
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
```

- [ ] **Step 6: Test ausführen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_database.py -v`
Expected: PASS, sofern Postgres aus Step 2 `healthy` ist. Falls FAIL: `docker compose -f backend/docker-compose.yml ps` prüfen.

- [ ] **Step 7: Alembic einrichten**

```ini
# backend/alembic.ini
[alembic]
script_location = alembic
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

```python
# backend/alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401  ensures all models are registered on Base.metadata
from app.core.config import settings
from app.models.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

```mako
# backend/alembic/script.py.mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 8: Baseline-Migration erzeugen und anwenden**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "baseline (no tables yet)"`
Expected: Neue Datei unter `alembic/versions/`, `upgrade()`/`downgrade()` sind leer (`pass`), da noch keine Modelle existieren.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> <revision>, baseline (no tables yet)`

- [ ] **Step 9: Commit**

```bash
git add backend/Dockerfile backend/requirements.txt backend/docker-compose.yml backend/.env.example backend/app/core backend/app/models backend/alembic.ini backend/alembic/env.py backend/alembic/script.py.mako backend/alembic/versions backend/tests/conftest.py backend/tests/test_database.py
git commit -m "feat: add async DB connection, TimestampMixin, and Alembic setup"
```

---

### Task 3: Modelle & Migration — Klasse, Bereich

**Files:**
- Create: `backend/app/models/klasse.py`
- Create: `backend/app/models/bereich.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models_klasse.py`

**Interfaces:**
- Consumes: `app.models.base.Base`, `TimestampMixin` (Task 2).
- Produces: `app.models.klasse.Klasse`, `app.models.bereich.Bereich`, `app.models.bereich.bereich_klasse` (Association-Table) — werden ab Task 4 per `ForeignKey("klasse.id")` referenziert.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_models_klasse.py
import pytest
from sqlalchemy import select

from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse


@pytest.mark.asyncio
async def test_klasse_roundtrip(db_session):
    klasse = Klasse(webuntis_id=3499, name="10a", stufe="10", schulart="BK", webuntis_teacher1_id=63, webuntis_teacher2_id=434)
    db_session.add(klasse)
    await db_session.commit()

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    loaded = result.scalar_one()
    assert loaded.name == "10a"
    assert loaded.webuntis_teacher1_id == 63


@pytest.mark.asyncio
async def test_bereich_klasse_association(db_session):
    klasse = Klasse(webuntis_id=1, name="11b")
    bereich = Bereich(name="Kaufmännischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()

    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    result = await db_session.execute(select(bereich_klasse))
    row = result.first()
    assert row.bereich_id == bereich.id
    assert row.klasse_id == klasse.id
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_klasse.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.models.klasse'`

- [ ] **Step 3: Modelle implementieren**

```python
# backend/app/models/klasse.py
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Klasse(Base, TimestampMixin):
    __tablename__ = "klasse"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    stufe: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schulart: Mapped[str | None] = mapped_column(String(50), nullable=True)
    webuntis_teacher1_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webuntis_teacher2_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

```python
# backend/app/models/bereich.py
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

bereich_klasse = Table(
    "bereich_klasse",
    Base.metadata,
    Column("bereich_id", ForeignKey("bereich.id", ondelete="CASCADE"), primary_key=True),
    Column("klasse_id", ForeignKey("klasse.id", ondelete="CASCADE"), primary_key=True),
)


class Bereich(Base, TimestampMixin):
    __tablename__ = "bereich"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
```

```python
# backend/app/models/__init__.py
from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse

__all__ = ["Base", "Bereich", "bereich_klasse", "Klasse"]
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_klasse.py -v`
Expected: PASS

- [ ] **Step 5: Migration erzeugen und anwenden**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add klasse, bereich tables"`
Expected: Neue Migrationsdatei mit `create_table('klasse', ...)`, `create_table('bereich', ...)`, `create_table('bereich_klasse', ...)`.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration wird angewendet, keine Fehler.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/klasse.py backend/app/models/bereich.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_models_klasse.py
git commit -m "feat: add Klasse and Bereich models with migration"
```

---

### Task 4: Modelle & Migration — ExcuseStatus, Schueler, Fehlzeit

**Files:**
- Create: `backend/app/models/excuse_status.py`
- Create: `backend/app/models/schueler.py`
- Create: `backend/app/models/fehlzeit.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models_schueler.py`

**Interfaces:**
- Consumes: `Klasse` (Task 3) für `Schueler.klasse_id`.
- Produces: `ExcuseStatus`, `Schueler`, `Fehlzeit` — `Schueler` wird ab Task 5 von `KlassenbuchEintrag.schueler_id` referenziert.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

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
        webuntis_id=49845,
        webuntis_key="fuch_9464",
        vorname="Max",
        nachname="Mustermann",
        klasse_id=klasse.id,
        aktiv=True,
    )
    db_session.add(schueler)
    await db_session.commit()

    result = await db_session.execute(select(Schueler).where(Schueler.webuntis_id == 49845))
    loaded = result.scalar_one()
    assert loaded.nachname == "Mustermann"
    assert loaded.aktiv is True
    assert loaded.klasse_id == klasse.id


@pytest.mark.asyncio
async def test_fehlzeit_unique_constraint_prevents_duplicate_sync(db_session):
    schueler = Schueler(webuntis_id=1, vorname="A", nachname="B")
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

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_schueler.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.models.schueler'`

- [ ] **Step 3: Modelle implementieren**

```python
# backend/app/models/excuse_status.py
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ExcuseStatus(Base, TimestampMixin):
    __tablename__ = "excuse_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20), unique=True)
    long_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zaehlt_als_entschuldigt: Mapped[bool] = mapped_column(Boolean)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
```

```python
# backend/app/models/schueler.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Schueler(Base, TimestampMixin):
    __tablename__ = "schueler"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    webuntis_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vorname: Mapped[str] = mapped_column(String(100))
    nachname: Mapped[str] = mapped_column(String(100))
    klasse_id: Mapped[int | None] = mapped_column(ForeignKey("klasse.id"), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=False)
    klassenzuordnung_aktualisiert_am: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

```python
# backend/app/models/fehlzeit.py
from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Fehlzeit(Base, TimestampMixin):
    __tablename__ = "fehlzeit"
    __table_args__ = (
        UniqueConstraint(
            "schueler_id", "datum", "start_zeit", "end_zeit", "typ", name="uq_fehlzeit_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    typ: Mapped[str] = mapped_column(String(10))  # "tag" | "stunde"
    datum: Mapped[date] = mapped_column(Date)
    start_zeit: Mapped[int] = mapped_column(Integer)
    end_zeit: Mapped[int] = mapped_column(Integer)
    fach: Mapped[str | None] = mapped_column(String(50), nullable=True)
    excuse_status_id: Mapped[int | None] = mapped_column(ForeignKey("excuse_status.id"), nullable=True)
    grund_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invalid: Mapped[bool] = mapped_column(Boolean, default=False)
```

```python
# backend/app/models/__init__.py
from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.schueler import Schueler

__all__ = ["Base", "Bereich", "bereich_klasse", "ExcuseStatus", "Fehlzeit", "Klasse", "Schueler"]
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_schueler.py -v`
Expected: PASS (2 Tests)

- [ ] **Step 5: Migration erzeugen und anwenden**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add excuse_status, schueler, fehlzeit tables"`
Expected: Neue Migrationsdatei mit den drei `create_table(...)`-Aufrufen und dem Unique-Constraint auf `fehlzeit`.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration angewendet, keine Fehler.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/excuse_status.py backend/app/models/schueler.py backend/app/models/fehlzeit.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_models_schueler.py
git commit -m "feat: add ExcuseStatus, Schueler, and Fehlzeit models with migration"
```

---

### Task 5: Modelle & Migration — ClassregCategory, KlassenbuchEintrag

**Files:**
- Create: `backend/app/models/classreg_category.py`
- Create: `backend/app/models/klassenbuch_eintrag.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models_klassenbuch.py`

**Interfaces:**
- Consumes: `Schueler` (Task 4).
- Produces: `ClassregCategory`, `KlassenbuchEintrag`.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

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
    schueler = Schueler(webuntis_id=1, vorname="A", nachname="B")
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

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_klassenbuch.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.models.classreg_category'`

- [ ] **Step 3: Modelle implementieren**

```python
# backend/app/models/classreg_category.py
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ClassregCategory(Base, TimestampMixin):
    __tablename__ = "classreg_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    long_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

```python
# backend/app/models/klassenbuch_eintrag.py
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class KlassenbuchEintrag(Base, TimestampMixin):
    __tablename__ = "klassenbuch_eintrag"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    kategorie_id: Mapped[int] = mapped_column(ForeignKey("classreg_category.id"))
    datum: Mapped[date] = mapped_column(Date)
    text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    lesson_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erstellt_von_teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geaendert_von_teacher_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

```python
# backend/app/models/__init__.py
from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler

__all__ = [
    "Base",
    "Bereich",
    "bereich_klasse",
    "ClassregCategory",
    "ExcuseStatus",
    "Fehlzeit",
    "Klasse",
    "KlassenbuchEintrag",
    "Schueler",
]
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_klassenbuch.py -v`
Expected: PASS

- [ ] **Step 5: Migration erzeugen und anwenden**

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add classreg_category, klassenbuch_eintrag tables"`
Expected: Neue Migrationsdatei mit beiden `create_table(...)`-Aufrufen.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration angewendet, keine Fehler.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/classreg_category.py backend/app/models/klassenbuch_eintrag.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_models_klassenbuch.py
git commit -m "feat: add ClassregCategory and KlassenbuchEintrag models with migration"
```

---

### Task 6: Modelle & Migration — Einstellung, AuditLog

**Files:**
- Create: `backend/app/models/einstellung.py`
- Create: `backend/app/models/audit_log.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models_einstellung_audit.py`

**Interfaces:**
- Consumes: nichts Neues (AuditLog referenziert `nutzer.id`, aber als loses `Integer`-FK ohne Python-Objektbeziehung, damit die Reihenfolge Task 6 vor Task 7 keine zirkuläre Abhängigkeit erzeugt).
- Produces: `Einstellung`, `AuditLog`.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_models_einstellung_audit.py
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
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_einstellung_audit.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.models.einstellung'`

- [ ] **Step 3: Modelle implementieren**

```python
# backend/app/models/einstellung.py
from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Einstellung(Base, TimestampMixin):
    __tablename__ = "einstellung"

    id: Mapped[int] = mapped_column(primary_key=True)
    sync_interval_cron: Mapped[str] = mapped_column(String(50), default="*/30 * * * *")
    schuljahr_start_cache: Mapped[date | None] = mapped_column(Date, nullable=True)
    initialer_import_abgeschlossen: Mapped[bool] = mapped_column(Boolean, default=False)
```

```python
# backend/app/models/audit_log.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aktion: Mapped[str] = mapped_column(String(100))
    resource_typ: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

> `AuditLog.user_id` ist bewusst ein loses `Integer`-Feld ohne `ForeignKey`/Beziehung zu `Nutzer` (das erst in Task 7 entsteht) — Referentielle Integrität ist hier zweitrangig gegenüber einer robusten Audit-Historie (ein Log-Eintrag soll auch dann lesbar bleiben, wenn ein `Nutzer`-Datensatz später gelöscht würde).

```python
# backend/app/models/__init__.py
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler

__all__ = [
    "AuditLog",
    "Base",
    "Bereich",
    "bereich_klasse",
    "ClassregCategory",
    "Einstellung",
    "ExcuseStatus",
    "Fehlzeit",
    "Klasse",
    "KlassenbuchEintrag",
    "Schueler",
]
```

- [ ] **Step 4: Migration erzeugen und anwenden (vor dem Testlauf!)**

> Reihenfolge bewusst so: `conftest.py`s `_reset_database`-Fixture (Task 2) räumt bei jedem Testlauf per `create_all` alle aktuellen Modelle in dieselbe Dev-Datenbank, die auch Alembic verwaltet. Liefe der Testlauf zuerst, existierten die neuen Tabellen schon, bevor Alembic sie sieht — `autogenerate` fände dann keinen Unterschied und die Migration bliebe leer bzw. würde bei `upgrade` mit "already exists" fehlschlagen (siehe Task 5, wo das erst nachträglich per Downgrade/Upgrade-Zyklus aufgefallen ist). Migration deshalb erzeugen, solange die DB noch den Stand des vorherigen Tasks hat.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add einstellung, audit_log tables"`
Expected: Neue Migrationsdatei mit beiden `create_table(...)`-Aufrufen (nicht leer).

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration angewendet, keine Fehler.

- [ ] **Step 5: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_einstellung_audit.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/einstellung.py backend/app/models/audit_log.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_models_einstellung_audit.py
git commit -m "feat: add Einstellung and AuditLog models with migration"
```

---

### Task 7: Modelle & Migration — Nutzer, NutzerKlasse, NutzerBereich

**Files:**
- Create: `backend/app/models/nutzer.py`
- Create: `backend/app/models/nutzer_klasse.py`
- Create: `backend/app/models/nutzer_bereich.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models_nutzer.py`

**Interfaces:**
- Consumes: `Klasse` (Task 3), `Bereich` (Task 3).
- Produces: `Nutzer` (mit `ROLLEN`-Konstante), `NutzerKlasse` (mit `quelle`-Feld: `"webuntis_seed"` | `"manuell"`), `nutzer_bereich`-Association-Table — werden ab Task 8 (WP-Proxy-Auth) und Task 9 (Seeding) verwendet.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_models_nutzer.py
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.bereich import Bereich
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse


@pytest.mark.asyncio
async def test_nutzer_roundtrip(db_session):
    nutzer = Nutzer(
        wp_user_id="jseyfried",
        email="joerg.seyfried@hhs.karlsruhe.de",
        name="Jörg Seyfried",
        rolle="klassenlehrkraft",
        webuntis_teacher_id=63,
    )
    db_session.add(nutzer)
    await db_session.commit()

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    loaded = result.scalar_one()
    assert loaded.rolle == "klassenlehrkraft"
    assert loaded.webuntis_teacher_id == 63


@pytest.mark.asyncio
async def test_nutzer_klasse_unique_per_quelle(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add_all([nutzer, klasse])
    await db_session.flush()

    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_nutzer_bereich_association(db_session):
    nutzer = Nutzer(wp_user_id="u2", email="c@d.de", name="C", rolle="bereichsleiter")
    bereich = Bereich(name="Gewerblicher Bereich")
    db_session.add_all([nutzer, bereich])
    await db_session.flush()

    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))
    await db_session.commit()

    result = await db_session.execute(select(nutzer_bereich))
    row = result.first()
    assert row.nutzer_id == nutzer.id
    assert row.bereich_id == bereich.id
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_nutzer.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.models.nutzer'`

- [ ] **Step 3: Modelle implementieren**

```python
# backend/app/models/nutzer.py
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

ROLLEN = ("klassenlehrkraft", "bereichsleiter", "schulleitung")


class Nutzer(Base, TimestampMixin):
    __tablename__ = "nutzer"

    id: Mapped[int] = mapped_column(primary_key=True)
    wp_user_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    rolle: Mapped[str] = mapped_column(String(20))
    webuntis_teacher_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
```

> `wp_user_id` ist ein `String`, kein `Integer` — der WordPress-Header `X-WordPress-User` trägt laut VertretungsFlow-Vorbild den WP-Benutzernamen (z.B. `"jseyfried"`), keine numerische ID (TECH-SPEC.md Abschnitt 3).

```python
# backend/app/models/nutzer_klasse.py
from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NutzerKlasse(Base, TimestampMixin):
    __tablename__ = "nutzer_klasse"
    __table_args__ = (
        UniqueConstraint("nutzer_id", "klasse_id", "quelle", name="uq_nutzer_klasse_quelle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nutzer_id: Mapped[int] = mapped_column(ForeignKey("nutzer.id", ondelete="CASCADE"))
    klasse_id: Mapped[int] = mapped_column(ForeignKey("klasse.id", ondelete="CASCADE"))
    quelle: Mapped[str] = mapped_column(String(20))  # "webuntis_seed" | "manuell"
```

```python
# backend/app/models/nutzer_bereich.py
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Table

from app.models.base import Base

nutzer_bereich = Table(
    "nutzer_bereich",
    Base.metadata,
    Column("nutzer_id", ForeignKey("nutzer.id", ondelete="CASCADE"), primary_key=True),
    Column("bereich_id", ForeignKey("bereich.id", ondelete="CASCADE"), primary_key=True),
)
```

```python
# backend/app/models/__init__.py
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.bereich import Bereich, bereich_klasse
from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.nutzer import ROLLEN, Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
from app.models.schueler import Schueler

__all__ = [
    "AuditLog",
    "Base",
    "Bereich",
    "bereich_klasse",
    "ClassregCategory",
    "Einstellung",
    "ExcuseStatus",
    "Fehlzeit",
    "Klasse",
    "KlassenbuchEintrag",
    "Nutzer",
    "nutzer_bereich",
    "NutzerKlasse",
    "ROLLEN",
    "Schueler",
]
```

- [ ] **Step 4: Migration erzeugen und anwenden (vor dem Testlauf!)**

> Reihenfolge bewusst so (siehe Begründung in Task 6, Step 4): Migration erzeugen, solange die DB noch den Stand des vorherigen Tasks hat, bevor `conftest.py`s `create_all`-Fixture beim Testlauf die neuen Tabellen schon anlegt.

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "add nutzer, nutzer_klasse, nutzer_bereich tables"`
Expected: Neue Migrationsdatei mit den drei `create_table(...)`-Aufrufen inkl. Unique-Constraints (nicht leer).

Run: `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`
Expected: Migration angewendet, keine Fehler.

- [ ] **Step 5: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_models_nutzer.py -v`
Expected: PASS (3 Tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/nutzer.py backend/app/models/nutzer_klasse.py backend/app/models/nutzer_bereich.py backend/app/models/__init__.py backend/alembic/versions backend/tests/test_models_nutzer.py
git commit -m "feat: add Nutzer, NutzerKlasse, and NutzerBereich models with migration"
```

---

### Task 8: WordPress-Proxy-Auth-Dependency

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/deps.py`
- Test: `backend/tests/test_deps_wordpress_proxy.py`

**Interfaces:**
- Consumes: `Nutzer`, `ROLLEN` (Task 7), `AuditLog` (Task 6), `get_db` (Task 2).
- Produces: `app.api.deps.get_wordpress_proxy_nutzer` — FastAPI-Dependency, gibt einen `Nutzer` zurück; wird ab dem nächsten Plan ("Backend: REST-Endpunkte") in geschützten Routen als `Depends(...)` verwendet.

- [ ] **Step 1: Config um Secret erweitern**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str


settings = Settings()
```

```text
# backend/.env.example
DATABASE_URL=postgresql+asyncpg://absenzdash:absenzdash@postgres:5432/absenzdash
WORDPRESS_PROXY_SECRET=changeme
```

- [ ] **Step 2: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_deps_wordpress_proxy.py
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_wordpress_proxy_nutzer
from app.core.config import settings
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.nutzer import Nutzer

test_app = FastAPI()


@test_app.get("/whoami")
async def whoami(nutzer: Nutzer = Depends(get_wordpress_proxy_nutzer)):
    return {"id": nutzer.id, "rolle": nutzer.rolle}


HEADERS_BASE = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Jörg Seyfried",
    "X-WordPress-Role": "klassenlehrkraft",
    "X-WordPress-WebUntis-Code": "63",
}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


@pytest.mark.asyncio
async def test_rejects_wrong_secret():
    transport = ASGITransport(app=test_app)
    headers = {**HEADERS_BASE, "X-WordPress-Secret": "wrong"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rejects_unknown_role():
    transport = ASGITransport(app=test_app)
    headers = {**HEADERS_BASE, "X-WordPress-Role": "hausmeister"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_creates_nutzer_on_first_proxy_request(db_session):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/whoami", headers=HEADERS_BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["rolle"] == "klassenlehrkraft"

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    nutzer = result.scalar_one()
    assert nutzer.webuntis_teacher_id == 63

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.resource_typ == "nutzer"))
    audit_entries = audit_result.scalars().all()
    assert len(audit_entries) == 1
    assert audit_entries[0].aktion == "wordpress_proxy_created"


@pytest.mark.asyncio
async def test_updates_existing_nutzer_on_repeat_request(db_session):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/whoami", headers=HEADERS_BASE)
        headers_updated_role = {**HEADERS_BASE, "X-WordPress-Role": "bereichsleiter"}
        response = await client.get("/whoami", headers=headers_updated_role)

    assert response.status_code == 200
    assert response.json()["rolle"] == "bereichsleiter"

    result = await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "jseyfried"))
    assert len(result.scalars().all()) == 1  # kein Duplikat
```

Hinweis: `test_app` überschreibt `get_db` nicht — er nutzt in diesem Test bewusst dieselbe DB-Session-Factory wie die App (über `app.core.database.get_db`), da `conftest.py`s `_reset_database`-Fixture ohnehin dieselbe Engine zurücksetzt. Für spätere Pläne mit vielen Endpunkten kann dies durch eine explizite Dependency-Override ersetzt werden.

- [ ] **Step 3: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_deps_wordpress_proxy.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 4: Dependency implementieren**

```python
# backend/app/api/__init__.py
```

```python
# backend/app/api/deps.py
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.nutzer import ROLLEN, Nutzer


async def get_wordpress_proxy_nutzer(
    x_wordpress_secret: Annotated[str, Header(alias="X-WordPress-Secret")],
    x_wordpress_user: Annotated[str, Header(alias="X-WordPress-User")],
    x_wordpress_email: Annotated[str, Header(alias="X-WordPress-Email")],
    x_wordpress_name: Annotated[str, Header(alias="X-WordPress-Name")],
    x_wordpress_role: Annotated[str, Header(alias="X-WordPress-Role")],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_wordpress_webuntis_code: Annotated[str | None, Header(alias="X-WordPress-WebUntis-Code")] = None,
) -> Nutzer:
    if not hmac.compare_digest(x_wordpress_secret, settings.wordpress_proxy_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid WordPress proxy secret")

    if x_wordpress_role not in ROLLEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role: {x_wordpress_role}")

    webuntis_teacher_id = int(x_wordpress_webuntis_code) if x_wordpress_webuntis_code else None

    result = await db.execute(select(Nutzer).where(Nutzer.wp_user_id == x_wordpress_user))
    nutzer = result.scalar_one_or_none()

    if nutzer is None:
        nutzer = Nutzer(
            wp_user_id=x_wordpress_user,
            email=x_wordpress_email,
            name=x_wordpress_name,
            rolle=x_wordpress_role,
            webuntis_teacher_id=webuntis_teacher_id,
        )
        db.add(nutzer)
        aktion = "wordpress_proxy_created"
    else:
        nutzer.email = x_wordpress_email
        nutzer.name = x_wordpress_name
        nutzer.rolle = x_wordpress_role
        nutzer.webuntis_teacher_id = webuntis_teacher_id
        aktion = "wordpress_proxy_updated"

    await db.flush()

    db.add(
        AuditLog(
            user_id=nutzer.id,
            aktion=aktion,
            resource_typ="nutzer",
            resource_id=str(nutzer.id),
            details={"quelle": "wordpress_proxy"},
        )
    )
    await db.commit()
    await db.refresh(nutzer)
    return nutzer
```

- [ ] **Step 5: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_deps_wordpress_proxy.py -v`
Expected: PASS (4 Tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/.env.example backend/app/api backend/tests/test_deps_wordpress_proxy.py
git commit -m "feat: add WordPress proxy authentication dependency"
```

---

### Task 9: Nutzer↔Klasse-Seeding (TECH-SPEC.md Abschnitt 2.1)

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/nutzer_klasse_sync.py`
- Test: `backend/tests/test_nutzer_klasse_sync.py`

**Interfaces:**
- Consumes: `Klasse`, `Nutzer`, `NutzerKlasse` (Tasks 3, 7).
- Produces: `seed_nutzer_klasse_from_webuntis(db: AsyncSession) -> None` — wird im nächsten Plan ("Backend: WebUntis-Sync") nach jedem `getKlassen`-Sync aufgerufen.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

```python
# backend/tests/test_nutzer_klasse_sync.py
import pytest
from sqlalchemy import select

from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse
from app.services.nutzer_klasse_sync import seed_nutzer_klasse_from_webuntis


@pytest.mark.asyncio
async def test_seeds_nutzer_klasse_for_matching_teacher(db_session):
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft", webuntis_teacher_id=63)
    klasse = Klasse(webuntis_id=3499, name="10a", webuntis_teacher1_id=63)
    db_session.add_all([nutzer, klasse])
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].nutzer_id == nutzer.id
    assert rows[0].klasse_id == klasse.id
    assert rows[0].quelle == "webuntis_seed"


@pytest.mark.asyncio
async def test_skips_teacher_without_matching_nutzer(db_session):
    klasse = Klasse(webuntis_id=1, name="11b", webuntis_teacher1_id=999)
    db_session.add(klasse)
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_preserves_manual_assignments_and_refreshes_seeded_ones(db_session):
    nutzer_alt = Nutzer(wp_user_id="alt", email="alt@b.de", name="Alt", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    nutzer_neu = Nutzer(wp_user_id="neu", email="neu@b.de", name="Neu", rolle="klassenlehrkraft", webuntis_teacher_id=2)
    nutzer_co = Nutzer(wp_user_id="co", email="co@b.de", name="Co", rolle="klassenlehrkraft")
    klasse = Klasse(webuntis_id=1, name="10a", webuntis_teacher1_id=1)
    db_session.add_all([nutzer_alt, nutzer_neu, nutzer_co, klasse])
    await db_session.commit()

    await seed_nutzer_klasse_from_webuntis(db_session)
    db_session.add(NutzerKlasse(nutzer_id=nutzer_co.id, klasse_id=klasse.id, quelle="manuell"))
    await db_session.commit()

    klasse.webuntis_teacher1_id = 2
    await db_session.commit()
    await seed_nutzer_klasse_from_webuntis(db_session)

    result = await db_session.execute(select(NutzerKlasse))
    rows = {(row.nutzer_id, row.quelle) for row in result.scalars().all()}
    assert (nutzer_neu.id, "webuntis_seed") in rows
    assert (nutzer_co.id, "manuell") in rows
    assert (nutzer_alt.id, "webuntis_seed") not in rows
```

- [ ] **Step 2: Test ausführen, Fehlschlag bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_nutzer_klasse_sync.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Implementieren**

```python
# backend/app/services/__init__.py
```

```python
# backend/app/services/nutzer_klasse_sync.py
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_klasse import NutzerKlasse


async def seed_nutzer_klasse_from_webuntis(db: AsyncSession) -> None:
    """Setzt alle 'webuntis_seed'-Zuordnungen aus Klasse.webuntis_teacher1_id/2 neu auf.

    Manuell gepflegte Zuordnungen (quelle='manuell') bleiben unangetastet
    (TECH-SPEC.md Abschnitt 2.1).
    """
    await db.execute(delete(NutzerKlasse).where(NutzerKlasse.quelle == "webuntis_seed"))

    klassen = (await db.execute(select(Klasse))).scalars().all()
    nutzer_result = await db.execute(select(Nutzer).where(Nutzer.webuntis_teacher_id.is_not(None)))
    nutzer_by_teacher_id = {nutzer.webuntis_teacher_id: nutzer for nutzer in nutzer_result.scalars()}

    for klasse in klassen:
        for teacher_id in (klasse.webuntis_teacher1_id, klasse.webuntis_teacher2_id):
            if teacher_id is None:
                continue
            nutzer = nutzer_by_teacher_id.get(teacher_id)
            if nutzer is None:
                continue
            db.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))

    await db.commit()
```

- [ ] **Step 4: Test ausführen, Erfolg bestätigen**

Run: `docker compose -f backend/docker-compose.yml run --rm backend pytest tests/test_nutzer_klasse_sync.py -v`
Expected: PASS (3 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services backend/tests/test_nutzer_klasse_sync.py
git commit -m "feat: add nutzer_klasse seeding service from WebUntis teacher assignments"
```

---

### Task 10: Vollständiger Stack-Check & Dokumentation

**Files:**
- Create: `docs/backend-setup.md`
- Test: manuell (kein pytest-Test — Infrastruktur-Task)

**Interfaces:**
- Consumes: alle vorherigen Tasks (komplettes Backend, inkl. `backend/Dockerfile`/`backend/docker-compose.yml` aus Task 2).
- Produces: `docs/backend-setup.md` dokumentiert Setup/Betrieb für Admins/Entwickler (CLAUDE.md-Konvention: user-/admin-relevante Infos sofort in `docs/`).

> Dockerfile und der `backend`-Service in `docker-compose.yml` existieren bereits seit Task 2 (Docker-Dev-Umgebung) — dieser Task baut nichts davon neu, sondern verifiziert den kompletten Stack (Backend als eigener, laufender Service statt nur `run --rm` für Einzelbefehle) und dokumentiert ihn.

- [ ] **Step 1: Vollständigen Stack starten und verifizieren**

Run: `docker compose -f backend/docker-compose.yml up -d --build`
Expected: Beide Container laufen (`docker compose -f backend/docker-compose.yml ps` zeigt `postgres` als `healthy`, `backend` als `running`).

Run: `curl http://localhost:8000/health`
Expected: `{"status":"ok"}`

Run: `docker compose -f backend/docker-compose.yml down`
Expected: Container werden sauber gestoppt (Aufräumen nach der Verifikation).

- [ ] **Step 2: Setup-Dokumentation**

```markdown
# docs/backend-setup.md

# Backend-Setup

## Voraussetzungen

- Docker (Python 3.11 läuft ausschließlich containerisiert — auf der Entwicklungsmaschine muss kein Python installiert sein)

## Setup

1. `cp backend/.env.example backend/.env` und `WORDPRESS_PROXY_SECRET` auf einen echten Wert setzen.
2. `docker compose -f backend/docker-compose.yml up -d --build`
3. `docker compose -f backend/docker-compose.yml run --rm backend alembic upgrade head`

Das Backend läuft danach unter `http://localhost:8000`, Health-Check unter `GET /health`.

## Tests

`docker compose -f backend/docker-compose.yml run --rm backend pytest` (benötigt laufende PostgreSQL-Instanz: `docker compose -f backend/docker-compose.yml up -d postgres`). Jeder Test läuft in einer frisch aufgesetzten Datenbank (`tests/conftest.py` erstellt/verwirft alle Tabellen automatisch pro Test).

## Migrationen

Nach jeder Modelländerung: `docker compose -f backend/docker-compose.yml run --rm backend alembic revision --autogenerate -m "<beschreibung>"`, danach `... alembic upgrade head`. Handgeschriebene SQL-Migrationsdateien sind für dieses Projekt bewusst nicht vorgesehen (siehe TECH-SPEC.md Abschnitt 2).

## Aktueller Stand

Dieser Plan (`docs/superpowers/plans/2026-07-24-backend-grundgeruest.md`) deckt das komplette Datenschema (TECH-SPEC.md Abschnitt 2) und die WordPress-Proxy-Authentifizierung ab — noch **keine** WebUntis-Anbindung und noch keine fachlichen REST-Endpunkte (`/students`, `/admin/...`). Beides folgt in separaten Plänen.
```

- [ ] **Step 3: Commit**

```bash
git add docs/backend-setup.md
git commit -m "docs: add backend setup and operations guide"
```

---

## Self-Review-Notizen (bereits durchgeführt)

- **Spec-Abdeckung:** Alle Tabellen aus TECH-SPEC.md Abschnitt 2, die nicht von der Eskalations-Engine/Maßnahmen-Verwaltung (Schwellwert-Regeln, Zählerstände, Benachrichtigungen, Maßnahmen, Ausnahmen — bewusst nächster Plan) abhängen, sind abgedeckt: `klasse`, `bereich`, `bereich_klasse`, `schueler`, `excuse_status`, `fehlzeit`, `classreg_category`, `klassenbuch_eintrag`, `einstellung`, `audit_log`, `nutzer`, `nutzer_klasse`, `nutzer_bereich`. Der WP-Proxy-Auth-Vertrag aus TECH-SPEC.md Abschnitt 3 (Header, Get-or-Create, Audit-Log) ist über Task 8 vollständig abgebildet. Die Seeding-Logik aus Abschnitt 2.1 ist Task 9.
- **Bewusst außerhalb dieses Plans:** WebUntis-Client/-Sync (TECH-SPEC.md Abschnitt 1), `SchuelerRosterProvider`-Abstraktion, Schwellwert-/Eskalations-Tabellen, REST-Endpunkte aus Abschnitt 3 (`/students`, `/admin/...`) — folgen in eigenen Plänen, damit dieser Plan überschaubar bleibt und für sich lauffähige, testbare Software liefert.
- **Typkonsistenz geprüft:** `Nutzer.wp_user_id` als `String` (nicht `Integer`) durchgängig in Modell, Test und `deps.py` konsistent. `Fehlzeit`/`Schueler` referenzieren `excuse_status_id`/`klasse_id` korrekt auf die in früheren Tasks definierten Tabellen. `AuditLog.user_id` bewusst ohne FK-Constraint (dokumentiert).
- **Platzhalter-Scan:** keine TBD/TODO, jeder Code-Schritt enthält vollständigen, lauffähigen Code.
- **Nachtrag nach Task 5 (Migration-vs-Test-Reihenfolge):** Task-Review deckte auf, dass `conftest.py`s `create_all`-Fixture (Task 2) dieselbe Dev-DB wie Alembic verwaltet — lief der Testlauf vor der Migrationserzeugung, fand `autogenerate` keinen Unterschied mehr (Tabellen existierten schon), was den Implementer zu einem `stamp`-Workaround statt eines echten `upgrade` verleitete. Durch einen manuellen Downgrade-auf-`base`/Upgrade-auf-`head`-Zyklus direkt gegen die echte DB verifiziert: alle vier bis dahin existierenden Migrationen (Tasks 2–5) wenden sich tatsächlich fehlerfrei an und erzeugen exakt die erwarteten 9 Tabellen — der Code war korrekt, nur der ursprüngliche Verifikationsweg unzureichend. Für Task 6/7 wurde die Schrittreihenfolge angepasst (Migration jetzt vor dem Testlauf), um das für die verbleibenden Tasks zu vermeiden.
- **Nachtrag nach Task 1 (Ausführungsumgebung):** Die Entwicklungsmaschine hat kein Python 3.11 (nur 3.9, kein Homebrew/pyenv) — `X | None`-Syntax in den Modellen (ab Task 3) würde dort zur Laufzeit crashen. Da ohnehin Docker-Deployment geplant ist, wurde auf Nutzerentscheidung hin die Docker-Dev-Umgebung von Task 10 nach Task 2 vorgezogen; alle `Run:`-Befehle ab Task 2 laufen über `docker compose -f backend/docker-compose.yml run --rm backend ...` statt über einen Host-venv (siehe Global Constraints, "Ausführungsumgebung"). Task 1 selbst ist davon nicht betroffen (kein 3.10+-Syntax) und bleibt wie bereits ausgeführt.
