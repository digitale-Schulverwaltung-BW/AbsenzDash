# Eskalations-Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementiert die Eskalations-Engine aus SPECS.md §4/5 (Schwellwert-Regeln, mehrstufige Eskalation, Maßnahmen-Reset, Ausnahmen, Benachrichtigungs-Log) als Backend-Service, integriert in den bestehenden WebUntis-Sync-Job — vollständig ohne HTTP-Endpunkte oder E-Mail-Versand (spätere Pläne).

**Architecture:** Neuberechnung statt Inkrement — bei jedem Sync-Lauf wird für jeden Schüler/Regel-Paar der Zählerstand komplett aus den Rohdaten (`fehlzeit`/`klassenbuch_eintrag`) seit dem letzten Reset-Zeitpunkt neu berechnet (kein Drift-Risiko, Schuljahreswechsel fällt automatisch raus). Ein neuer Service `eskalations_pruefung.py` kapselt die komplette Logik und wird als letzter Schritt in `sync_orchestrator._run_once` aufgerufen, vor dem abschließenden Commit.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, PostgreSQL (asyncpg), Alembic, pytest + pytest-asyncio gegen echte Postgres-Testdatenbank (kein Mocking der DB-Schicht, siehe `tests/conftest.py`).

**Design-Dokument:** [docs/superpowers/specs/2026-07-26-eskalations-engine-design.md](../specs/2026-07-26-eskalations-engine-design.md) — enthält die vollständige fachliche Herleitung inkl. Live-Verifikation des WebUntis-`did`/`getDepartments`-Felds. Dieser Plan übersetzt das Design 1:1 in Code; bei Widersprüchen gilt das Design-Dokument.

## Global Constraints

- Commit-Messages auf Englisch (User-Konvention).
- Log-Meldungen, Docstrings und Kommentare in diesem Projekt sind Deutsch — beibehalten.
- Keine SQLAlchemy `relationship()`-Deklarationen verwenden — das Projekt nutzt durchgängig explizite FK-Spalten + manuelle `select()`-Joins in Service-Code (siehe `webuntis_klassen_sync.py`, `nutzer_klasse_sync.py`). Neue Modelle/Services folgen exakt diesem Stil.
- Kein `Base.metadata.create_all`/Migration-Koordinationsproblem: Tests nutzen `tests/conftest.py`s `_reset_database`-Fixture (`Base.metadata.drop_all`/`create_all` gegen die echte Testdatenbank) — Migrationen sind **nicht** testrelevant, werden aber trotzdem pro Task erzeugt (Produktions-Korrektheit, Projektkonvention "Alembic von Anfang an real genutzt").
- Migrationen mit `alembic revision --autogenerate -m "..."` erzeugen (nicht von Hand schreiben), danach das generierte File prüfen/anpassen und `alembic upgrade head` ausführen, um die lokale Test-Postgres auf den neuen Head zu bringen (nötig, damit der nächste Task korrekt gegen den vorherigen Stand diffed).
- **Explizit dokumentierte fachliche Annahmen** (im Design-Dokument nicht abschließend geklärt, hier bewusst entschieden — bei Rückfragen des Users während der Umsetzung gilt das hier Genannte als Startpunkt, nicht als unveränderlich):
  - "Fehltage" = Anzahl `fehlzeit`-Zeilen mit `typ='tag'`; "Fehlstunden" = Anzahl Zeilen mit `typ='stunde'` (direkte Zuordnung zum bestehenden `fehlzeit.typ`-Feld, keine abgeleitete Stunden-zu-Tage-Umrechnung).
  - Fehlzeiten ohne gesetzten `excuse_status_id` (noch nicht geprüft) zählen beim Filter `nur_unentschuldigt` **mit** (wie unentschuldigt behandelt, bis Gegenteil geprüft ist).
  - Default-Maßnahmen-Katalog (SPECS.md §4): "Nachsitzen", "4h Nachsitzen", "Schulverweis", "Bußgeld", "Zwangsgeld" erhalten `setzt_zaehler_zurueck=true`; "Gespräch", "Elterngespräch" erhalten `false`. Alle sieben starten ohne `massnahmen_typ_regel`-Zuordnung (Regeln existieren bei Fresh-Install noch nicht, Zuordnung erfolgt später admin-seitig).
- Kein API-Endpunkt, kein SMTP-Versand in diesem Plan (siehe Design-Dokument Abschnitt 1).

---

### Task 1: WebUntis-Abteilungs-Sync + Klasse-Bereinigung

**Files:**
- Create: `backend/app/models/abteilung.py`
- Modify: `backend/app/models/klasse.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/webuntis_abteilung_sync.py`
- Modify: `backend/app/services/webuntis_klassen_sync.py`
- Modify: `backend/app/services/sync_orchestrator.py`
- Modify: `backend/tests/test_sync_orchestrator.py`
- Modify: `backend/tests/test_models_klasse.py`
- Modify: `backend/tests/test_webuntis_klassen_sync.py`
- Create: `backend/tests/test_webuntis_abteilung_sync.py`
- Create: Alembic-Migration (autogenerate)

**Interfaces:**
- Produces: `Abteilung` Modell (`app.models.abteilung.Abteilung`, Felder `id`, `webuntis_id`, `name`, `long_name`). `Klasse.abteilung_id` (nullable FK → `abteilung.id`). `sync_abteilungen(client: WebUntisClient, db: AsyncSession) -> None` in `app.services.webuntis_abteilung_sync`. Spätere Tasks (2) nutzen `Klasse.abteilung_id` zur Regel-Auflösung.

- [ ] **Step 1: `Abteilung`-Modell schreiben**

`backend/app/models/abteilung.py`:

```python
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Abteilung(Base, TimestampMixin):
    __tablename__ = "abteilung"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    long_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

- [ ] **Step 2: `Klasse` um `abteilung_id` erweitern, `stufe`/`schulart` entfernen**

In `backend/app/models/klasse.py`, ersetze den kompletten Inhalt durch:

```python
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Klasse(Base, TimestampMixin):
    __tablename__ = "klasse"

    id: Mapped[int] = mapped_column(primary_key=True)
    webuntis_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    abteilung_id: Mapped[int | None] = mapped_column(ForeignKey("abteilung.id"), nullable=True)
    webuntis_teacher1_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    webuntis_teacher2_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: `test_models_klasse.py` anpassen (stufe/schulart-Referenz entfernen)**

In `backend/tests/test_models_klasse.py`, ersetze die erste Testzeile:

```python
    klasse = Klasse(webuntis_id=3499, name="10a", stufe="10", schulart="BK", webuntis_teacher1_id=63, webuntis_teacher2_id=434)
```

durch:

```python
    klasse = Klasse(webuntis_id=3499, name="10a", webuntis_teacher1_id=63, webuntis_teacher2_id=434)
```

- [ ] **Step 4: Modelle in `__init__.py` registrieren**

In `backend/app/models/__init__.py`, füge hinzu (alphabetisch einsortiert wie die bestehenden Imports):

```python
from app.models.abteilung import Abteilung
```

und in `__all__` (alphabetisch):

```python
    "Abteilung",
```

- [ ] **Step 5: Failing Test für `sync_abteilungen` schreiben**

`backend/tests/test_webuntis_abteilung_sync.py`:

```python
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.services.webuntis_abteilung_sync import sync_abteilungen


@pytest.mark.asyncio
async def test_sync_abteilungen_creates_new_abteilung(db_session):
    client = AsyncMock()
    client.call.return_value = [{"id": 64, "name": "A-2BFE", "longName": "A-2BFE"}]

    await sync_abteilungen(client, db_session)

    result = await db_session.execute(select(Abteilung).where(Abteilung.webuntis_id == 64))
    abteilung = result.scalar_one()
    assert abteilung.name == "A-2BFE"
    assert abteilung.long_name == "A-2BFE"
    client.call.assert_awaited_once_with("getDepartments", {})


@pytest.mark.asyncio
async def test_sync_abteilungen_updates_existing_abteilung(db_session):
    existing = Abteilung(webuntis_id=64, name="alt", long_name="alt")
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 64, "name": "neu", "longName": "Neuer Name"}]

    await sync_abteilungen(client, db_session)

    result = await db_session.execute(select(Abteilung).where(Abteilung.webuntis_id == 64))
    abteilung = result.scalar_one()
    assert abteilung.name == "neu"
    assert abteilung.long_name == "Neuer Name"
```

- [ ] **Step 6: Test laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_webuntis_abteilung_sync.py -v
```

Erwartet: FAIL — `ModuleNotFoundError: No module named 'app.services.webuntis_abteilung_sync'`.

- [ ] **Step 7: `sync_abteilungen` implementieren**

`backend/app/services/webuntis_abteilung_sync.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.abteilung import Abteilung


async def sync_abteilungen(client: WebUntisClient, db: AsyncSession) -> None:
    """getDepartments -> abteilung (muss vor sync_klassen laufen, da klasse.abteilung_id referenziert)."""
    rows = await client.call("getDepartments", {})

    existing = (await db.execute(select(Abteilung))).scalars().all()
    by_webuntis_id = {abteilung.webuntis_id: abteilung for abteilung in existing}

    for row in rows:
        abteilung = by_webuntis_id.get(row["id"])
        if abteilung is None:
            abteilung = Abteilung(webuntis_id=row["id"], name=row["name"])
            db.add(abteilung)
        else:
            abteilung.name = row["name"]
        abteilung.long_name = row.get("longName")

    await db.commit()
```

- [ ] **Step 8: Test laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_webuntis_abteilung_sync.py -v
```

Erwartet: PASS (2/2).

- [ ] **Step 9: `sync_klassen` um `abteilung_id`-Auflösung erweitern**

In `backend/app/services/webuntis_klassen_sync.py`, ersetze den kompletten Inhalt durch:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient
from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.services.nutzer_klasse_sync import seed_nutzer_klasse_from_webuntis


async def sync_klassen(client: WebUntisClient, db: AsyncSession) -> None:
    """getKlassen -> klasse (Upsert nach webuntis_id), danach nutzer_klasse-Seeding (TECH-SPEC.md Abschnitt 1.2)."""
    rows = await client.call("getKlassen", {})

    existing = (await db.execute(select(Klasse))).scalars().all()
    by_webuntis_id = {klasse.webuntis_id: klasse for klasse in existing}

    abteilung_result = await db.execute(select(Abteilung))
    abteilung_id_by_webuntis_id = {a.webuntis_id: a.id for a in abteilung_result.scalars().all()}

    for row in rows:
        klasse = by_webuntis_id.get(row["id"])
        if klasse is None:
            klasse = Klasse(webuntis_id=row["id"], name=row["name"])
            db.add(klasse)
        else:
            klasse.name = row["name"]
        klasse.abteilung_id = abteilung_id_by_webuntis_id.get(row.get("did"))
        klasse.webuntis_teacher1_id = row.get("teacher1")
        klasse.webuntis_teacher2_id = row.get("teacher2")

    await db.flush()
    await seed_nutzer_klasse_from_webuntis(db)
```

- [ ] **Step 10: Test für `abteilung_id`-Auflösung in `test_webuntis_klassen_sync.py` ergänzen**

In `backend/tests/test_webuntis_klassen_sync.py`, füge den Import `from app.models.abteilung import Abteilung` hinzu und diesen neuen Test:

```python
@pytest.mark.asyncio
async def test_sync_klassen_resolves_abteilung_id_from_did(db_session):
    abteilung = Abteilung(webuntis_id=64, name="A-2BFE")
    db_session.add(abteilung)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "did": 64, "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.abteilung_id == abteilung.id


@pytest.mark.asyncio
async def test_sync_klassen_leaves_abteilung_id_none_when_did_unresolvable(db_session):
    client = AsyncMock()
    client.call.return_value = [{"id": 3499, "name": "10a", "did": 999, "teacher1": 63, "teacher2": None}]

    await sync_klassen(client, db_session)

    result = await db_session.execute(select(Klasse).where(Klasse.webuntis_id == 3499))
    klasse = result.scalar_one()
    assert klasse.abteilung_id is None
```

- [ ] **Step 11: Tests laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_webuntis_klassen_sync.py tests/test_models_klasse.py -v
```

Erwartet: PASS (alle Tests, inkl. der bestehenden ohne `did`-Feld — `abteilung_id` bleibt dort `None`, unverändertes Verhalten).

- [ ] **Step 12: `sync_orchestrator._run_once` um `sync_abteilungen`-Aufruf erweitern**

In `backend/app/services/sync_orchestrator.py`, ändere den Import-Block und `_run_once`:

```python
from app.services.webuntis_abteilung_sync import sync_abteilungen
```

(alphabetisch bei den bestehenden `from app.services...`-Imports einsortieren) und in `_run_once`:

```python
    async with WebUntisClient(settings) as client:
        await sync_abteilungen(client, db)
        await sync_klassen(client, db)
        await sync_kategorien(client, db)
        await import_schueler(db)
```

(nur die neue Zeile `await sync_abteilungen(client, db)` vor `await sync_klassen(client, db)` einfügen, Rest unverändert.)

- [ ] **Step 13: `_patch_phases`-Fixture in `test_sync_orchestrator.py` um `sync_abteilungen` erweitern**

In `backend/tests/test_sync_orchestrator.py`, in der `_patch_phases`-Fixture, füge hinzu:

```python
    monkeypatch.setattr(sync_orchestrator, "sync_abteilungen", AsyncMock())
```

(direkt nach `monkeypatch.setattr(sync_orchestrator, "WebUntisClient", _FakeWebUntisClient)` einfügen — sonst würde der reale `sync_abteilungen` gegen den `_FakeWebUntisClient` laufen, dessen `.call()` immer denselben Dict `{"startDate":..., "endDate":...}` zurückgibt, egal welche Methode aufgerufen wird, was beim Iterieren als Department-Liste crasht.)

Ergänze außerdem in `test_run_full_sync_calls_phases_in_order` die erwartete Reihenfolge — `sync_orchestrator.sync_abteilungen.side_effect = lambda *a: calls.append("abteilungen")` vor der `sync_klassen`-Zeile, und in der `assert calls == [...]`-Zeile `"abteilungen"` als erstes Element ergänzen.

- [ ] **Step 14: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS, alle Tests grün (keine Regression in `test_scheduler.py` o.ä.).

- [ ] **Step 15: Migration erzeugen**

```bash
docker exec absenzdash-test-runner alembic revision --autogenerate -m "add abteilung table, klasse.abteilung_id, drop klasse.stufe/schulart"
docker exec absenzdash-test-runner alembic upgrade head
```

Generierte Datei in `backend/alembic/versions/` öffnen und prüfen: `create_table('abteilung', ...)`, `add_column('klasse', 'abteilung_id', ...)` + `create_foreign_key(...)`, `drop_column('klasse', 'stufe')`, `drop_column('klasse', 'schulart')`. Downgrade-Funktion muss die Spalten symmetrisch wiederherstellen (Alembic generiert das automatisch bei `drop_column`/`add_column`-Paaren — prüfen, dass `downgrade()` tatsächlich `stufe`/`schulart` wieder anlegt und `abteilung_id`/`abteilung`-Tabelle entfernt).

- [ ] **Step 16: Commit**

```bash
git add backend/app/models/abteilung.py backend/app/models/klasse.py backend/app/models/__init__.py \
  backend/app/services/webuntis_abteilung_sync.py backend/app/services/webuntis_klassen_sync.py \
  backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py \
  backend/tests/test_models_klasse.py backend/tests/test_webuntis_klassen_sync.py \
  backend/tests/test_webuntis_abteilung_sync.py backend/alembic/versions/
git commit -m "feat: sync WebUntis Abteilungen, resolve klasse.abteilung_id, drop unused stufe/schulart columns"
```

---

### Task 2: Schwellwert-Regel & Schwellwert-Stufe + Regel-Auflösung

**Files:**
- Create: `backend/app/models/schwellwert_regel.py`
- Create: `backend/app/models/schwellwert_stufe.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/eskalations_pruefung.py`
- Create: `backend/tests/test_models_schwellwert.py`
- Create: `backend/tests/test_eskalations_pruefung_regelaufloesung.py`
- Create: Alembic-Migration

**Interfaces:**
- Consumes: `Klasse.abteilung_id` (Task 1).
- Produces: `SchwellwertRegel` (`typ`, `geltungsbereich`, `abteilung_id`, `klasse_id`), `SchwellwertStufe` (`regel_id`, `stufe_nr`, `einheit`, `schwellenwert`, `fehlzeiten_filter`, `empfaenger_rollen`). `resolve_schwellwert_regel(db: AsyncSession, klasse_id: int | None, typ: str) -> SchwellwertRegel | None` in `app.services.eskalations_pruefung` — von Task 3+ als Kern-Baustein der Auflösungs-Präzedenz genutzt.

- [ ] **Step 1: Modelle schreiben**

`backend/app/models/schwellwert_regel.py`:

```python
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchwellwertRegel(Base, TimestampMixin):
    __tablename__ = "schwellwert_regel"
    __table_args__ = (
        Index(
            "uq_schwellwert_regel_abteilung",
            "typ",
            "abteilung_id",
            unique=True,
            postgresql_where=text("abteilung_id IS NOT NULL"),
        ),
        Index(
            "uq_schwellwert_regel_klasse",
            "typ",
            "klasse_id",
            unique=True,
            postgresql_where=text("klasse_id IS NOT NULL"),
        ),
        Index(
            "uq_schwellwert_regel_schulweit",
            "typ",
            unique=True,
            postgresql_where=text("geltungsbereich = 'schulweit'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    typ: Mapped[str] = mapped_column(String(20))  # "fehlzeiten" | "klassenbuch"
    geltungsbereich: Mapped[str] = mapped_column(String(20))  # "schulweit" | "abteilung" | "klasse"
    abteilung_id: Mapped[int | None] = mapped_column(ForeignKey("abteilung.id"), nullable=True)
    klasse_id: Mapped[int | None] = mapped_column(ForeignKey("klasse.id"), nullable=True)
```

`backend/app/models/schwellwert_stufe.py`:

```python
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchwellwertStufe(Base, TimestampMixin):
    __tablename__ = "schwellwert_stufe"
    __table_args__ = (UniqueConstraint("regel_id", "stufe_nr", name="uq_schwellwert_stufe_regel_stufe_nr"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    regel_id: Mapped[int] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="CASCADE"))
    stufe_nr: Mapped[int] = mapped_column(Integer)
    einheit: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "fehltage" | "fehlstunden"
    schwellenwert: Mapped[int] = mapped_column(Integer)
    fehlzeiten_filter: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "nur_unentschuldigt" | "alle"
    empfaenger_rollen: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
```

- [ ] **Step 2: Modelle in `__init__.py` registrieren**

In `backend/app/models/__init__.py`, ergänze (alphabetisch):

```python
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
```

und in `__all__`:

```python
    "SchwellwertRegel",
    "SchwellwertStufe",
```

- [ ] **Step 3: Modell-Roundtrip-Test schreiben**

`backend/tests/test_models_schwellwert.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.abteilung import Abteilung
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe


@pytest.mark.asyncio
async def test_schwellwert_regel_stufe_roundtrip(db_session):
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()

    stufe = SchwellwertStufe(
        regel_id=regel.id,
        stufe_nr=1,
        einheit="fehltage",
        schwellenwert=4,
        fehlzeiten_filter="nur_unentschuldigt",
        empfaenger_rollen=["klassenlehrkraft"],
    )
    db_session.add(stufe)
    await db_session.commit()

    result = await db_session.execute(select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id))
    loaded = result.scalar_one()
    assert loaded.schwellenwert == 4
    assert loaded.empfaenger_rollen == ["klassenlehrkraft"]


@pytest.mark.asyncio
async def test_schwellwert_regel_prevents_duplicate_abteilung_regel_same_typ(db_session):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id))
    await db_session.commit()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_schwellwert_regel_prevents_duplicate_schulweit_same_typ(db_session):
    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit"))
    await db_session.commit()

    db_session.add(SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [ ] **Step 4: Tests laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_models_schwellwert.py -v
```

Erwartet: FAIL — `ModuleNotFoundError: No module named 'app.models.schwellwert_regel'`.

Nach Anlage der Modelle (Step 1-2) erneut laufen lassen — erwartet PASS (3/3). (Die Modelle existieren zu diesem Zeitpunkt bereits aus Step 1, dieser Schritt bestätigt lediglich, dass Roundtrip + beide Unique-Indexe funktionieren, bevor mit der Auflösungs-Logik weitergemacht wird.)

- [ ] **Step 5: Failing Test für `resolve_schwellwert_regel` schreiben**

`backend/tests/test_eskalations_pruefung_regelaufloesung.py`:

```python
import pytest

from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import resolve_schwellwert_regel


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_prefers_klasse_specific(db_session):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=abteilung.id)
    db_session.add(klasse)
    await db_session.flush()

    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    abteilungsregel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id)
    klassenregel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="klasse", klasse_id=klasse.id)
    db_session.add_all([schulweit, abteilungsregel, klassenregel])
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, klasse.id, "fehlzeiten")

    assert result.id == klassenregel.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_falls_back_to_abteilung(db_session):
    abteilung = Abteilung(webuntis_id=1, name="A")
    db_session.add(abteilung)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", abteilung_id=abteilung.id)
    db_session.add(klasse)
    await db_session.flush()

    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    abteilungsregel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="abteilung", abteilung_id=abteilung.id)
    db_session.add_all([schulweit, abteilungsregel])
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, klasse.id, "fehlzeiten")

    assert result.id == abteilungsregel.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_falls_back_to_schulweit_without_klasse(db_session):
    schulweit = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(schulweit)
    await db_session.commit()

    result = await resolve_schwellwert_regel(db_session, None, "fehlzeiten")

    assert result.id == schulweit.id


@pytest.mark.asyncio
async def test_resolve_schwellwert_regel_returns_none_when_no_rule_matches(db_session):
    result = await resolve_schwellwert_regel(db_session, None, "fehlzeiten")

    assert result is None
```

- [ ] **Step 6: Test laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung_regelaufloesung.py -v
```

Erwartet: FAIL — `ModuleNotFoundError: No module named 'app.services.eskalations_pruefung'`.

- [ ] **Step 7: `resolve_schwellwert_regel` implementieren**

`backend/app/services/eskalations_pruefung.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.klasse import Klasse
from app.models.schwellwert_regel import SchwellwertRegel


async def resolve_schwellwert_regel(
    db: AsyncSession, klasse_id: int | None, typ: str
) -> SchwellwertRegel | None:
    """Loest die zutreffende Regel nach Praezedenz auf: klassen-spezifisch > abteilungs-spezifisch > schulweit."""
    if klasse_id is not None:
        result = await db.execute(
            select(SchwellwertRegel).where(SchwellwertRegel.typ == typ, SchwellwertRegel.klasse_id == klasse_id)
        )
        regel = result.scalar_one_or_none()
        if regel is not None:
            return regel

        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is not None and klasse.abteilung_id is not None:
            result = await db.execute(
                select(SchwellwertRegel).where(
                    SchwellwertRegel.typ == typ, SchwellwertRegel.abteilung_id == klasse.abteilung_id
                )
            )
            regel = result.scalar_one_or_none()
            if regel is not None:
                return regel

    result = await db.execute(
        select(SchwellwertRegel).where(SchwellwertRegel.typ == typ, SchwellwertRegel.geltungsbereich == "schulweit")
    )
    return result.scalar_one_or_none()
```

- [ ] **Step 8: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung_regelaufloesung.py tests/test_models_schwellwert.py -v
```

Erwartet: PASS (7/7).

- [ ] **Step 9: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS, keine Regressionen.

- [ ] **Step 10: Migration erzeugen**

```bash
docker exec absenzdash-test-runner alembic revision --autogenerate -m "add schwellwert_regel, schwellwert_stufe tables"
docker exec absenzdash-test-runner alembic upgrade head
```

Generiertes File prüfen: beide Tabellen, beide Partial-Unique-Indexe (`postgresql_where`), `UniqueConstraint` auf `schwellwert_stufe`, `ARRAY(String(20))`-Spalte für `empfaenger_rollen`.

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/schwellwert_regel.py backend/app/models/schwellwert_stufe.py backend/app/models/__init__.py \
  backend/app/services/eskalations_pruefung.py backend/tests/test_models_schwellwert.py \
  backend/tests/test_eskalations_pruefung_regelaufloesung.py backend/alembic/versions/
git commit -m "feat: add Schwellwert-Regel/-Stufe models and precedence-based rule resolution"
```

---

### Task 3: Schueler-Zaehlerstand + Pro-Stufe-Zählung

**Files:**
- Create: `backend/app/models/schueler_zaehlerstand.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/eskalations_pruefung.py`
- Create: `backend/tests/test_models_schueler_zaehlerstand.py`
- Create: `backend/tests/test_eskalations_pruefung.py`
- Create: Alembic-Migration

**Interfaces:**
- Consumes: `resolve_schwellwert_regel` (Task 2).
- Produces: `SchuelerZaehlerstand` (`schueler_id`, `regel_id`, `aktueller_stand`, `erreichte_stufe_nr`, `letzter_reset_am`). `get_or_create_zaehlerstand(db, schueler_id, regel_id) -> SchuelerZaehlerstand` (public — Task 5 nutzt sie für den Maßnahmen-Reset). `pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung) -> None` — der Haupteinstiegspunkt, den Task 7 in `sync_orchestrator` verdrahtet. In diesem Task noch **ohne** Ausnahme-Skip (Task 4) und **ohne** Benachrichtigungs-Schreiben (Task 6).

- [ ] **Step 1: `SchuelerZaehlerstand`-Modell schreiben**

`backend/app/models/schueler_zaehlerstand.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerZaehlerstand(Base, TimestampMixin):
    __tablename__ = "schueler_zaehlerstand"
    __table_args__ = (UniqueConstraint("schueler_id", "regel_id", name="uq_schueler_zaehlerstand_paar"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    regel_id: Mapped[int] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="CASCADE"))
    aktueller_stand: Mapped[int] = mapped_column(Integer, default=0)
    erreichte_stufe_nr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    letzter_reset_am: Mapped[date | None] = mapped_column(Date, nullable=True)
```

- [ ] **Step 2: Modell in `__init__.py` registrieren**

In `backend/app/models/__init__.py`, ergänze (alphabetisch):

```python
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
```

und in `__all__`: `"SchuelerZaehlerstand",`

- [ ] **Step 3: Modell-Roundtrip-Test schreiben**

`backend/tests/test_models_schueler_zaehlerstand.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel


@pytest.mark.asyncio
async def test_schueler_zaehlerstand_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([schueler, regel])
    await db_session.flush()

    zaehlerstand = SchuelerZaehlerstand(
        schueler_id=schueler.id,
        regel_id=regel.id,
        aktueller_stand=3,
        erreichte_stufe_nr=1,
        letzter_reset_am=datetime.date(2026, 1, 15),
    )
    db_session.add(zaehlerstand)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    loaded = result.scalar_one()
    assert loaded.aktueller_stand == 3
    assert loaded.erreichte_stufe_nr == 1
```

- [ ] **Step 4: Test laufen lassen, dann Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_models_schueler_zaehlerstand.py -v
```

Erwartet: PASS (1/1) — das Modell existiert bereits aus Step 1.

- [ ] **Step 5: Failing Tests für `pruefe_schwellwerte` schreiben**

`backend/tests/test_eskalations_pruefung.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.classreg_category import ClassregCategory
from app.models.einstellung import Einstellung
from app.models.fehlzeit import Fehlzeit
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
from app.services.eskalations_pruefung import pruefe_schwellwerte


async def _make_schueler(db_session, aktiv: bool = True) -> Schueler:
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=aktiv)
    db_session.add(schueler)
    await db_session.flush()
    return schueler


async def _make_fehlzeiten_regel(db_session, schwellenwert: int = 4) -> SchwellwertRegel:
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id,
            stufe_nr=1,
            einheit="fehltage",
            schwellenwert=schwellenwert,
            fehlzeiten_filter="alle",
            empfaenger_rollen=["klassenlehrkraft"],
        )
    )
    await db_session.commit()
    return regel


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_reaches_stufe_when_threshold_met(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=2)
    for tag in range(2):
        db_session.add(
            Fehlzeit(
                schueler_id=schueler.id,
                typ="tag",
                datum=datetime.date(2026, 1, 10 + tag),
                start_zeit=0,
                end_zeit=0,
            )
        )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1
    assert zaehlerstand.aktueller_stand == 2


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_no_stufe_when_below_threshold(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=4)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr is None
    assert zaehlerstand.aktueller_stand == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_respects_fenster_start_from_letzter_reset(db_session):
    schueler = await _make_schueler(db_session)
    regel = await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        SchuelerZaehlerstand(
            schueler_id=schueler.id, regel_id=regel.id, aktueller_stand=0, letzter_reset_am=datetime.date(2026, 1, 15)
        )
    )
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0
        )
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.aktueller_stand == 0
    assert zaehlerstand.erreichte_stufe_nr is None


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_counts_klassenbuch_eintraege_for_klassenbuch_regel(db_session):
    schueler = await _make_schueler(db_session)
    kategorie = ClassregCategory(name="stören")
    db_session.add(kategorie)
    await db_session.flush()
    regel = SchwellwertRegel(typ="klassenbuch", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(regel_id=regel.id, stufe_nr=1, schwellenwert=2, empfaenger_rollen=["klassenlehrkraft"])
    )
    for i in range(2):
        db_session.add(
            KlassenbuchEintrag(
                webuntis_id=100 + i, schueler_id=schueler.id, kategorie_id=kategorie.id, datum=datetime.date(2026, 1, 10 + i)
            )
        )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    zaehlerstand = result.scalar_one()
    assert zaehlerstand.erreichte_stufe_nr == 1
```

- [ ] **Step 6: Tests laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: FAIL — `ImportError: cannot import name 'pruefe_schwellwerte'`.

- [ ] **Step 7: Zählungs- und Orchestrierungslogik implementieren**

In `backend/app/services/eskalations_pruefung.py`, Imports erweitern und folgende Funktionen ergänzen (nach `resolve_schwellwert_regel`):

```python
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.einstellung import Einstellung
from app.models.excuse_status import ExcuseStatus
from app.models.fehlzeit import Fehlzeit
from app.models.klasse import Klasse
from app.models.klassenbuch_eintrag import KlassenbuchEintrag
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.models.schwellwert_stufe import SchwellwertStufe
```

(diese Imports zu den bestehenden aus Step 7 von Task 2 hinzufügen, nicht ersetzen — `date` ergänzt das bereits vorhandene `datetime`-Modul-Muster im Projekt.)

```python
async def get_or_create_zaehlerstand(db: AsyncSession, schueler_id: int, regel_id: int) -> SchuelerZaehlerstand:
    result = await db.execute(
        select(SchuelerZaehlerstand).where(
            SchuelerZaehlerstand.schueler_id == schueler_id, SchuelerZaehlerstand.regel_id == regel_id
        )
    )
    zaehlerstand = result.scalar_one_or_none()
    if zaehlerstand is None:
        zaehlerstand = SchuelerZaehlerstand(schueler_id=schueler_id, regel_id=regel_id, aktueller_stand=0)
        db.add(zaehlerstand)
        await db.flush()
    return zaehlerstand


async def _zaehle_fuer_stufe(
    db: AsyncSession, regel: SchwellwertRegel, stufe: SchwellwertStufe, schueler_id: int, fenster_start: date
) -> int:
    if regel.typ == "fehlzeiten":
        query = select(func.count()).select_from(Fehlzeit).where(
            Fehlzeit.schueler_id == schueler_id,
            Fehlzeit.datum >= fenster_start,
            Fehlzeit.invalid.is_(False),
            Fehlzeit.typ == ("tag" if stufe.einheit == "fehltage" else "stunde"),
        )
        if stufe.fehlzeiten_filter == "nur_unentschuldigt":
            query = query.outerjoin(ExcuseStatus, Fehlzeit.excuse_status_id == ExcuseStatus.id).where(
                or_(Fehlzeit.excuse_status_id.is_(None), ExcuseStatus.zaehlt_als_entschuldigt.is_(False))
            )
        result = await db.execute(query)
        return result.scalar_one()

    result = await db.execute(
        select(func.count()).select_from(KlassenbuchEintrag).where(
            KlassenbuchEintrag.schueler_id == schueler_id, KlassenbuchEintrag.datum >= fenster_start
        )
    )
    return result.scalar_one()


async def _ermittle_erreichte_stufe(
    db: AsyncSession, regel: SchwellwertRegel, schueler_id: int, fenster_start: date
) -> tuple[int | None, int]:
    """Prueft Stufen absteigend; gibt (erreichte_stufe_nr, aktueller_stand) zurueck.

    aktueller_stand ist bei keiner erreichten Stufe der Zaehlwert nach Stufe-1-Definition
    (letzte Loop-Iteration, da absteigend sortiert) - fuer Fortschrittsanzeige im Dashboard.
    """
    stufen_result = await db.execute(
        select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id).order_by(SchwellwertStufe.stufe_nr.desc())
    )
    stufen = stufen_result.scalars().all()

    letzter_stand = 0
    for stufe in stufen:
        anzahl = await _zaehle_fuer_stufe(db, regel, stufe, schueler_id, fenster_start)
        letzter_stand = anzahl
        if anzahl >= stufe.schwellenwert:
            return stufe.stufe_nr, anzahl

    return None, letzter_stand


async def pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung) -> None:
    """Kernschleife: fuer jeden aktiven Schueler und Regel-Typ Zaehlerstand neu berechnen (SPECS.md Abschnitt 5)."""
    schueler_result = await db.execute(select(Schueler).where(Schueler.aktiv.is_(True)))
    alle_schueler = schueler_result.scalars().all()

    for typ in ("fehlzeiten", "klassenbuch"):
        for schueler in alle_schueler:
            regel = await resolve_schwellwert_regel(db, schueler.klasse_id, typ)
            if regel is None:
                continue

            zaehlerstand = await get_or_create_zaehlerstand(db, schueler.id, regel.id)
            fenster_kandidaten = [d for d in (einstellung.schuljahr_start_cache, zaehlerstand.letzter_reset_am) if d is not None]
            fenster_start = max(fenster_kandidaten) if fenster_kandidaten else date.min

            neue_stufe_nr, neuer_stand = await _ermittle_erreichte_stufe(db, regel, schueler.id, fenster_start)

            zaehlerstand.erreichte_stufe_nr = neue_stufe_nr
            zaehlerstand.aktueller_stand = neuer_stand
```

- [ ] **Step 8: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: PASS (4/4).

- [ ] **Step 9: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS, keine Regressionen.

- [ ] **Step 10: Migration erzeugen**

```bash
docker exec absenzdash-test-runner alembic revision --autogenerate -m "add schueler_zaehlerstand table"
docker exec absenzdash-test-runner alembic upgrade head
```

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/schueler_zaehlerstand.py backend/app/models/__init__.py \
  backend/app/services/eskalations_pruefung.py backend/tests/test_models_schueler_zaehlerstand.py \
  backend/tests/test_eskalations_pruefung.py backend/alembic/versions/
git commit -m "feat: add Schueler-Zaehlerstand model and per-stage threshold counting"
```

---

### Task 4: Ausnahme-Modell + Skip-Logik

**Files:**
- Create: `backend/app/models/ausnahme.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/eskalations_pruefung.py`
- Create: `backend/tests/test_models_ausnahme.py`
- Modify: `backend/tests/test_eskalations_pruefung.py`
- Create: Alembic-Migration

**Interfaces:**
- Consumes: `pruefe_schwellwerte`-Schleife (Task 3).
- Produces: `Ausnahme` (`schueler_id`, `kategorie`, `grund`, `gueltig_bis`, `aktiv`). `pruefe_schwellwerte` überspringt Schüler mit aktiver Ausnahme in der jeweiligen Kategorie (kein `schueler_zaehlerstand`-Update für dieses (Schüler, Typ)-Paar in diesem Lauf).

- [ ] **Step 1: `Ausnahme`-Modell schreiben**

`backend/app/models/ausnahme.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Ausnahme(Base, TimestampMixin):
    __tablename__ = "ausnahme"

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    kategorie: Mapped[str] = mapped_column(String(20))  # "fehlzeiten" | "klassenbuch"
    grund: Mapped[str] = mapped_column(String(500))
    gueltig_bis: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
```

- [ ] **Step 2: Modell in `__init__.py` registrieren**

In `backend/app/models/__init__.py`, ergänze (alphabetisch): `from app.models.ausnahme import Ausnahme` und in `__all__`: `"Ausnahme",`

- [ ] **Step 3: Roundtrip-Test schreiben**

`backend/tests/test_models_ausnahme.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.ausnahme import Ausnahme
from app.models.schueler import Schueler


@pytest.mark.asyncio
async def test_ausnahme_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()

    ausnahme = Ausnahme(
        schueler_id=schueler.id,
        kategorie="fehlzeiten",
        grund="Chronische Erkrankung",
        gueltig_bis=datetime.date(2026, 12, 31),
    )
    db_session.add(ausnahme)
    await db_session.commit()

    result = await db_session.execute(select(Ausnahme).where(Ausnahme.schueler_id == schueler.id))
    loaded = result.scalar_one()
    assert loaded.grund == "Chronische Erkrankung"
    assert loaded.aktiv is True
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_models_ausnahme.py -v
```

Erwartet: PASS (1/1).

- [ ] **Step 5: Failing Tests für Skip-Logik ergänzen**

In `backend/tests/test_eskalations_pruefung.py`, Import ergänzen: `from app.models.ausnahme import Ausnahme`, und diese Tests anhängen:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_skips_schueler_with_active_ausnahme(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    db_session.add(Ausnahme(schueler_id=schueler.id, kategorie="fehlzeiten", grund="Testgrund", aktiv=True))
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_ignores_expired_ausnahme(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    db_session.add(
        Ausnahme(
            schueler_id=schueler.id,
            kategorie="fehlzeiten",
            grund="Abgelaufen",
            aktiv=True,
            gueltig_bis=datetime.date(2026, 1, 1),
        )
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(
        select(SchuelerZaehlerstand).where(SchuelerZaehlerstand.schueler_id == schueler.id)
    )
    assert result.scalar_one_or_none() is not None
```

- [ ] **Step 6: Tests laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v -k ausnahme
```

Erwartet: FAIL — beide neuen Tests schlagen fehl (Skip-Logik existiert noch nicht, `test_pruefe_schwellwerte_skips_schueler_with_active_ausnahme` findet einen Zählerstand statt `None`).

- [ ] **Step 7: Skip-Logik implementieren**

In `backend/app/services/eskalations_pruefung.py`, Import ergänzen: `from app.models.ausnahme import Ausnahme`, dann eine neue Hilfsfunktion vor `pruefe_schwellwerte` einfügen:

```python
async def _hat_aktive_ausnahme(db: AsyncSession, schueler_id: int, kategorie: str, heute: date) -> bool:
    result = await db.execute(
        select(Ausnahme).where(
            Ausnahme.schueler_id == schueler_id,
            Ausnahme.kategorie == kategorie,
            Ausnahme.aktiv.is_(True),
            or_(Ausnahme.gueltig_bis.is_(None), Ausnahme.gueltig_bis >= heute),
        )
    )
    return result.first() is not None
```

Und in `pruefe_schwellwerte`, direkt nach der `for schueler in alle_schueler:`-Zeile eine Skip-Bedingung einfügen:

```python
        for schueler in alle_schueler:
            if await _hat_aktive_ausnahme(db, schueler.id, typ, heute):
                continue

            regel = await resolve_schwellwert_regel(db, schueler.klasse_id, typ)
```

(Rest der Funktion unverändert.)

- [ ] **Step 8: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: PASS (6/6 — alle bisherigen plus die zwei neuen).

- [ ] **Step 9: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS.

- [ ] **Step 10: Migration erzeugen**

```bash
docker exec absenzdash-test-runner alembic revision --autogenerate -m "add ausnahme table"
docker exec absenzdash-test-runner alembic upgrade head
```

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/ausnahme.py backend/app/models/__init__.py backend/app/services/eskalations_pruefung.py \
  backend/tests/test_models_ausnahme.py backend/tests/test_eskalations_pruefung.py backend/alembic/versions/
git commit -m "feat: add Ausnahme model, skip students with active exemption during threshold check"
```

---

### Task 5: Maßnahmen-Typ/Maßnahme + Default-Katalog-Seed + Reset-Service

**Files:**
- Create: `backend/app/models/massnahmen_typ.py`
- Create: `backend/app/models/massnahme.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/massnahme_service.py`
- Create: `backend/tests/test_models_massnahme.py`
- Create: `backend/tests/test_massnahme_service.py`
- Create: Alembic-Migration (Schema + Seed-Daten)

**Interfaces:**
- Consumes: `get_or_create_zaehlerstand` (Task 3).
- Produces: `MassnahmenTyp`, `massnahmen_typ_regel` (Assoziationstabelle), `Massnahme`. `record_massnahme(db, schueler_id, massnahmen_typ_id, datum, notiz, erfasst_von_nutzer_id) -> Massnahme` in `app.services.massnahme_service`.

- [ ] **Step 1: Modelle schreiben**

`backend/app/models/massnahmen_typ.py`:

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
```

`backend/app/models/massnahme.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Massnahme(Base, TimestampMixin):
    __tablename__ = "massnahme"

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    massnahmen_typ_id: Mapped[int] = mapped_column(ForeignKey("massnahmen_typ.id"))
    datum: Mapped[date] = mapped_column(Date)
    notiz: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    erfasst_von_nutzer_id: Mapped[int] = mapped_column(ForeignKey("nutzer.id"))
```

- [ ] **Step 2: Modelle in `__init__.py` registrieren**

In `backend/app/models/__init__.py`, ergänze (alphabetisch):

```python
from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
```

und in `__all__`: `"Massnahme", "MassnahmenTyp", "massnahmen_typ_regel",`

- [ ] **Step 3: Roundtrip-Tests schreiben**

`backend/tests/test_models_massnahme.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schwellwert_regel import SchwellwertRegel


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
async def test_massnahmen_typ_regel_association(db_session):
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([typ, regel])
    await db_session.flush()

    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel.id))
    await db_session.commit()

    result = await db_session.execute(select(massnahmen_typ_regel))
    row = result.first()
    assert row.massnahmen_typ_id == typ.id
    assert row.regel_id == regel.id
```

- [ ] **Step 4: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_models_massnahme.py -v
```

Erwartet: PASS (2/2).

- [ ] **Step 5: Failing Test für `record_massnahme` schreiben**

`backend/tests/test_massnahme_service.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.models.nutzer import Nutzer
from app.models.schueler import Schueler
from app.models.schueler_zaehlerstand import SchuelerZaehlerstand
from app.models.schwellwert_regel import SchwellwertRegel
from app.services.eskalations_pruefung import get_or_create_zaehlerstand
from app.services.massnahme_service import record_massnahme


@pytest.mark.asyncio
async def test_record_massnahme_resets_linked_zaehlerstand(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    typ = MassnahmenTyp(name="Nachsitzen", setzt_zaehler_zurueck=True)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add_all([schueler, regel, typ, nutzer])
    await db_session.flush()

    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel.id))
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, regel.id)
    zaehlerstand.aktueller_stand = 5
    zaehlerstand.erreichte_stufe_nr = 1
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
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.regel_id == regel.id
        )
    )
    reloaded = result.scalar_one()
    assert reloaded.aktueller_stand == 0
    assert reloaded.erreichte_stufe_nr is None
    assert reloaded.letzter_reset_am == datetime.date(2026, 1, 20)

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

    await db_session.execute(massnahmen_typ_regel.insert().values(massnahmen_typ_id=typ.id, regel_id=regel.id))
    zaehlerstand = await get_or_create_zaehlerstand(db_session, schueler.id, regel.id)
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
            SchuelerZaehlerstand.schueler_id == schueler.id, SchuelerZaehlerstand.regel_id == regel.id
        )
    )
    assert result.scalar_one().aktueller_stand == 5
```

- [ ] **Step 6: Test laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_massnahme_service.py -v
```

Erwartet: FAIL — `ModuleNotFoundError: No module named 'app.services.massnahme_service'`.

- [ ] **Step 7: `record_massnahme` implementieren**

`backend/app/services/massnahme_service.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.massnahme import Massnahme
from app.models.massnahmen_typ import MassnahmenTyp, massnahmen_typ_regel
from app.services.eskalations_pruefung import get_or_create_zaehlerstand


async def record_massnahme(
    db: AsyncSession,
    schueler_id: int,
    massnahmen_typ_id: int,
    datum: date,
    notiz: str | None,
    erfasst_von_nutzer_id: int,
) -> Massnahme:
    """Erfasst eine Massnahme; setzt bei setzt_zaehler_zurueck=True die verknuepften Zaehlerstaende zurueck."""
    massnahme = Massnahme(
        schueler_id=schueler_id,
        massnahmen_typ_id=massnahmen_typ_id,
        datum=datum,
        notiz=notiz,
        erfasst_von_nutzer_id=erfasst_von_nutzer_id,
    )
    db.add(massnahme)

    typ = (await db.execute(select(MassnahmenTyp).where(MassnahmenTyp.id == massnahmen_typ_id))).scalar_one()
    if typ.setzt_zaehler_zurueck:
        regel_ids_result = await db.execute(
            select(massnahmen_typ_regel.c.regel_id).where(massnahmen_typ_regel.c.massnahmen_typ_id == massnahmen_typ_id)
        )
        for regel_id in regel_ids_result.scalars().all():
            zaehlerstand = await get_or_create_zaehlerstand(db, schueler_id, regel_id)
            zaehlerstand.letzter_reset_am = datum
            zaehlerstand.aktueller_stand = 0
            zaehlerstand.erreichte_stufe_nr = None

    await db.commit()
    return massnahme
```

- [ ] **Step 8: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_massnahme_service.py -v
```

Erwartet: PASS (2/2).

- [ ] **Step 9: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS.

- [ ] **Step 10: Migration mit Schema + Seed-Daten erzeugen**

```bash
docker exec absenzdash-test-runner alembic revision --autogenerate -m "add massnahmen_typ, massnahme tables, seed default Massnahmen-Katalog"
docker exec absenzdash-test-runner alembic upgrade head
```

Generiertes File öffnen und die `upgrade()`-Funktion **nach** den auto-generierten `create_table`-Aufrufen um die Seed-Daten aus SPECS.md §4 erweitern (Bulk-Insert der 7 Default-Typen mit den in den Global Constraints festgelegten `setzt_zaehler_zurueck`-Werten):

```python
    massnahmen_typ_table = sa.table(
        "massnahmen_typ",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("setzt_zaehler_zurueck", sa.Boolean),
    )
    op.bulk_insert(
        massnahmen_typ_table,
        [
            {"name": "Gespräch", "setzt_zaehler_zurueck": False},
            {"name": "Elterngespräch", "setzt_zaehler_zurueck": False},
            {"name": "Nachsitzen", "setzt_zaehler_zurueck": True},
            {"name": "4h Nachsitzen", "setzt_zaehler_zurueck": True},
            {"name": "Schulverweis", "setzt_zaehler_zurueck": True},
            {"name": "Bußgeld", "setzt_zaehler_zurueck": True},
            {"name": "Zwangsgeld", "setzt_zaehler_zurueck": True},
        ],
    )
```

Und die `downgrade()`-Funktion um ein entsprechendes Löschen **vor** den auto-generierten `drop_table`-Aufrufen ergänzen: `op.execute("DELETE FROM massnahmen_typ")`.

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/massnahmen_typ.py backend/app/models/massnahme.py backend/app/models/__init__.py \
  backend/app/services/massnahme_service.py backend/tests/test_models_massnahme.py \
  backend/tests/test_massnahme_service.py backend/alembic/versions/
git commit -m "feat: add Massnahmen-Typ/Massnahme models, default catalog seed, counter reset service"
```

---

### Task 6: Benachrichtigung-Modell + Neu-erreicht-Erkennung + Empfänger-Auflösung

**Files:**
- Create: `backend/app/models/benachrichtigung.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/services/eskalations_pruefung.py`
- Create: `backend/tests/test_models_benachrichtigung.py`
- Modify: `backend/tests/test_eskalations_pruefung.py`
- Create: Alembic-Migration

**Interfaces:**
- Consumes: `pruefe_schwellwerte`-Schleife (Task 3/4), `Nutzer`/`NutzerKlasse`/`bereich_klasse`/`nutzer_bereich` (bestehend aus Plan 1).
- Produces: `Benachrichtigung` (`schueler_id`, `regel_id`, `stufe_nr`, `gesendet_am`, `empfaenger`, `status`). `pruefe_schwellwerte` schreibt ab jetzt bei jeder neu erreichten Stufe einen Eintrag.

- [ ] **Step 1: `Benachrichtigung`-Modell schreiben**

`backend/app/models/benachrichtigung.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Benachrichtigung(Base, TimestampMixin):
    __tablename__ = "benachrichtigung"

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    regel_id: Mapped[int] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="CASCADE"))
    stufe_nr: Mapped[int] = mapped_column(Integer)
    gesendet_am: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    empfaenger: Mapped[list[dict]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))  # "gesendet" | "kein_empfaenger" | "initial_import"
```

- [ ] **Step 2: Modell in `__init__.py` registrieren**

In `backend/app/models/__init__.py`, ergänze (alphabetisch): `from app.models.benachrichtigung import Benachrichtigung` und in `__all__`: `"Benachrichtigung",`

- [ ] **Step 3: Roundtrip-Test schreiben**

`backend/tests/test_models_benachrichtigung.py`:

```python
import datetime

import pytest
from sqlalchemy import select

from app.models.benachrichtigung import Benachrichtigung
from app.models.schueler import Schueler
from app.models.schwellwert_regel import SchwellwertRegel


@pytest.mark.asyncio
async def test_benachrichtigung_roundtrip(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add_all([schueler, regel])
    await db_session.flush()

    benachrichtigung = Benachrichtigung(
        schueler_id=schueler.id,
        regel_id=regel.id,
        stufe_nr=1,
        gesendet_am=datetime.datetime(2026, 1, 20, 8, 0, tzinfo=datetime.timezone.utc),
        empfaenger=[{"rolle": "klassenlehrkraft", "nutzer_id": 1}],
        status="gesendet",
    )
    db_session.add(benachrichtigung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    loaded = result.scalar_one()
    assert loaded.status == "gesendet"
    assert loaded.empfaenger == [{"rolle": "klassenlehrkraft", "nutzer_id": 1}]
```

- [ ] **Step 4: Test laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_models_benachrichtigung.py -v
```

Erwartet: PASS (1/1).

- [ ] **Step 5: Failing Tests für Benachrichtigungs-Logik ergänzen**

In `backend/tests/test_eskalations_pruefung.py`, Import ergänzen:

```python
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
```

und diese Tests anhängen:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_writes_benachrichtigung_on_newly_reached_stufe(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "gesendet"
    assert benachrichtigung.empfaenger == [{"rolle": "klassenlehrkraft", "nutzer_id": nutzer.id}]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_no_repeat_benachrichtigung_on_unchanged_stufe(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 21), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_kein_empfaenger_when_no_klassenlehrkraft_registered(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    db_session.add(schueler)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "kein_empfaenger"
    assert benachrichtigung.empfaenger == []


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_initial_import_status_before_first_full_sync(db_session):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.status == "initial_import"


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_resolves_bereichsleiter_empfaenger(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    bereich = Bereich(name="Kaufmaennischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    bereichsleiter = Nutzer(wp_user_id="u2", email="b@b.de", name="Leiter", rolle="bereichsleiter")
    db_session.add_all([schueler, bereichsleiter])
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=bereichsleiter.id, bereich_id=bereich.id))

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["bereichsleiter"],
        )
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung)
    await db_session.commit()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    benachrichtigung = result.scalar_one()
    assert benachrichtigung.empfaenger == [{"rolle": "bereichsleiter", "nutzer_id": bereichsleiter.id}]
```

- [ ] **Step 6: Tests laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: FAIL — die 5 neuen Tests schlagen fehl (`Benachrichtigung`-Zeilen werden noch nicht geschrieben).

- [ ] **Step 7: Empfänger-Auflösung und Benachrichtigungs-Schreiben implementieren**

In `backend/app/services/eskalations_pruefung.py`, Imports ergänzen:

```python
from app.models.benachrichtigung import Benachrichtigung
from app.models.bereich import bereich_klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.models.nutzer_klasse import NutzerKlasse
```

Neue Funktionen vor `pruefe_schwellwerte` einfügen:

```python
async def _resolve_empfaenger(db: AsyncSession, klasse_id: int | None, rollen: list[str]) -> list[dict]:
    empfaenger: list[dict] = []
    for rolle in rollen:
        if rolle == "klassenlehrkraft" and klasse_id is not None:
            result = await db.execute(
                select(Nutzer.id).join(NutzerKlasse, NutzerKlasse.nutzer_id == Nutzer.id).where(
                    NutzerKlasse.klasse_id == klasse_id
                )
            )
            empfaenger.extend({"rolle": rolle, "nutzer_id": nutzer_id} for nutzer_id in result.scalars().all())
        elif rolle == "bereichsleiter" and klasse_id is not None:
            result = await db.execute(
                select(Nutzer.id)
                .join(nutzer_bereich, nutzer_bereich.c.nutzer_id == Nutzer.id)
                .join(bereich_klasse, bereich_klasse.c.bereich_id == nutzer_bereich.c.bereich_id)
                .where(bereich_klasse.c.klasse_id == klasse_id)
            )
            empfaenger.extend({"rolle": rolle, "nutzer_id": nutzer_id} for nutzer_id in result.scalars().all())
        elif rolle == "schulleitung":
            result = await db.execute(select(Nutzer.id).where(Nutzer.rolle == "schulleitung"))
            empfaenger.extend({"rolle": rolle, "nutzer_id": nutzer_id} for nutzer_id in result.scalars().all())
    return empfaenger


async def _schreibe_benachrichtigung(
    db: AsyncSession, schueler: Schueler, regel: SchwellwertRegel, stufe_nr: int, einstellung: Einstellung
) -> None:
    stufe = (
        await db.execute(
            select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id, SchwellwertStufe.stufe_nr == stufe_nr)
        )
    ).scalar_one()

    if not einstellung.initialer_import_abgeschlossen:
        status = "initial_import"
        empfaenger: list[dict] = []
    else:
        empfaenger = await _resolve_empfaenger(db, schueler.klasse_id, stufe.empfaenger_rollen)
        status = "gesendet" if empfaenger else "kein_empfaenger"

    db.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            regel_id=regel.id,
            stufe_nr=stufe_nr,
            gesendet_am=datetime.now(timezone.utc),
            empfaenger=empfaenger,
            status=status,
        )
    )
```

Und in `pruefe_schwellwerte`, nach den beiden Zeilen `zaehlerstand.erreichte_stufe_nr = neue_stufe_nr` / `zaehlerstand.aktueller_stand = neuer_stand`, die Neu-erreicht-Erkennung ergänzen — dafür den alten Wert **vor** der Zuweisung zwischenspeichern:

```python
            alte_stufe_nr = zaehlerstand.erreichte_stufe_nr
            zaehlerstand.erreichte_stufe_nr = neue_stufe_nr
            zaehlerstand.aktueller_stand = neuer_stand

            if neue_stufe_nr is not None and (alte_stufe_nr is None or neue_stufe_nr > alte_stufe_nr):
                await _schreibe_benachrichtigung(db, schueler, regel, neue_stufe_nr, einstellung)
```

- [ ] **Step 8: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: PASS (11/11 — alle bisherigen plus die 5 neuen).

- [ ] **Step 9: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS.

- [ ] **Step 10: Migration erzeugen**

```bash
docker exec absenzdash-test-runner alembic revision --autogenerate -m "add benachrichtigung table"
docker exec absenzdash-test-runner alembic upgrade head
```

- [ ] **Step 11: Commit**

```bash
git add backend/app/models/benachrichtigung.py backend/app/models/__init__.py backend/app/services/eskalations_pruefung.py \
  backend/tests/test_models_benachrichtigung.py backend/tests/test_eskalations_pruefung.py backend/alembic/versions/
git commit -m "feat: add Benachrichtigung model, newly-reached-stage detection and recipient resolution"
```

---

### Task 7: Integration in sync_orchestrator + Ende-zu-Ende-Test

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py`
- Modify: `backend/tests/test_sync_orchestrator.py`

**Interfaces:**
- Consumes: `pruefe_schwellwerte(db, heute, einstellung)` (Task 3/4/6, vollständig).
- Produces: nichts Neues — reine Verdrahtung. Letzter Task des Plans.

- [ ] **Step 1: Import und Aufruf in `sync_orchestrator.py` ergänzen**

In `backend/app/services/sync_orchestrator.py`, Import ergänzen (alphabetisch bei den `app.services`-Imports):

```python
from app.services.eskalations_pruefung import pruefe_schwellwerte
```

Und in `_run_once`, direkt nach `await sync_klassenbuch(client, db, von, bis)` und **vor** `einstellung.letzter_sync_am = datetime.now(timezone.utc)` einfügen:

```python
        await sync_fehlzeiten(client, db, von, bis)
        await sync_klassenbuch(client, db, von, bis)

        await pruefe_schwellwerte(db, heute, einstellung)

        einstellung.letzter_sync_am = datetime.now(timezone.utc)
```

(Die Reihenfolge ist wichtig: `pruefe_schwellwerte` muss **vor** dem `initialer_import_abgeschlossen`-Flag-Flip laufen, damit der allererste Lauf korrekt als `initial_import` erkannt wird, SPECS.md §5.1.)

- [ ] **Step 2: `_patch_phases`-Fixture um `pruefe_schwellwerte` erweitern**

In `backend/tests/test_sync_orchestrator.py`, in der `_patch_phases`-Fixture:

```python
    monkeypatch.setattr(sync_orchestrator, "pruefe_schwellwerte", AsyncMock())
```

(neben den bestehenden `monkeypatch.setattr`-Zeilen ergänzen — ohne diesen Mock würde `pruefe_schwellwerte` in den bestehenden `test_run_full_sync_*`-Tests gegen eine leere DB ohne Schwellwert-Regeln laufen, was zwar nicht crasht [`resolve_schwellwert_regel` gibt `None` zurück, Schleife überspringt], aber unnötige DB-Queries in Tests einführt, die eigentlich nur `sync_orchestrator`-Verhalten testen sollen — sauberer isoliert.)

- [ ] **Step 3: Reihenfolge-Test aktualisieren**

In `test_run_full_sync_calls_phases_in_order`, `sync_orchestrator.pruefe_schwellwerte.side_effect = lambda *a: calls.append("schwellwerte")` vor der `await sync_orchestrator.run_full_sync(...)`-Zeile ergänzen und in der finalen `assert calls == [...]`-Liste `"schwellwerte"` als letztes Element (nach `"klassenbuch"`) hinzufügen.

- [ ] **Step 4: Tests laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_sync_orchestrator.py -v
```

Erwartet: PASS, alle Tests grün.

- [ ] **Step 5: Ende-zu-Ende-Integrationstest schreiben (ohne Mock von `pruefe_schwellwerte`)**

An `backend/tests/test_sync_orchestrator.py` anhängen. Die Datei importiert bereits `date`, `async_session_factory` und `select` (siehe Dateianfang: `from datetime import date, datetime, timezone`, `from app.core.database import async_session_factory`, `from sqlalchemy import select`) — **wichtig:** `run_full_sync` erwartet seit der Sync-Retry-Robustheit-Fix (siehe `docs/superpowers/plans/2026-07-26-sync-retry-robustness.md`) eine `session_factory`, keine einzelne Session mehr — alle bestehenden Tests in dieser Datei rufen bereits `sync_orchestrator.run_full_sync(async_session_factory)` auf, nicht `run_full_sync(db_session)`. Der neue Test unten folgt demselben Muster: Fixture-Daten werden über die `db_session`-Fixture angelegt und committed, `run_full_sync` läuft aber über `async_session_factory` in seiner eigenen, separaten Session (sichtbar für `db_session`, da dieselbe Postgres-Instanz/Connection-Pool, READ COMMITTED).

Weitere Imports ergänzen: `from app.models.einstellung import Einstellung`, `from app.models.benachrichtigung import Benachrichtigung`, `from app.models.fehlzeit import Fehlzeit`, `from app.models.schueler import Schueler`, `from app.models.schwellwert_regel import SchwellwertRegel`, `from app.models.schwellwert_stufe import SchwellwertStufe`, sowie **wichtig** `from app.services.eskalations_pruefung import pruefe_schwellwerte as real_pruefe_schwellwerte` — ein direkter Import der echten Funktion, unabhängig vom später gemockten `sync_orchestrator.pruefe_schwellwerte`-Attribut:

```python
@pytest.mark.asyncio
async def test_run_full_sync_end_to_end_triggers_benachrichtigung(db_session, monkeypatch):
    """Einziger Test in dieser Datei, der pruefe_schwellwerte NICHT mockt - prueft die reale Verdrahtung."""
    monkeypatch.setattr(sync_orchestrator, "pruefe_schwellwerte", real_pruefe_schwellwerte)

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["schulleitung"],
        )
    )
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=date(2025, 9, 1))
    db_session.add(einstellung)
    await db_session.commit()

    await sync_orchestrator.run_full_sync(async_session_factory)

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler.id))
    assert result.scalar_one().status == "kein_empfaenger"
```

Hinweis: Die autouse-`_patch_phases`-Fixture (Step 2) ersetzt `sync_orchestrator.pruefe_schwellwerte` bereits **bevor** der Testkörper läuft (Fixtures laufen vor dem Testkörper) — `sync_orchestrator.pruefe_schwellwerte` würde an dieser Stelle also bereits den Mock zurückgeben, nicht die echte Funktion. Deshalb importiert dieser Test die echte Funktion separat und direkt aus `app.services.eskalations_pruefung` (als `real_pruefe_schwellwerte`) und setzt sie explizit zurück — dadurch bleiben alle anderen `_patch_phases`-Mocks (für `sync_klassen` etc.) aktiv, nur `pruefe_schwellwerte` läuft real. `status == "kein_empfaenger"` statt `"gesendet"`, weil kein `Nutzer` mit `rolle='schulleitung'` angelegt wurde — das ist hier bewusst so, um zu zeigen, dass der Pfad bis zum Schreiben eines `Benachrichtigung`-Eintrags tatsächlich durchläuft, ohne die komplette Empfänger-Fixture-Konstruktion (bereits in `test_eskalations_pruefung.py` abgedeckt) hier zu wiederholen.

- [ ] **Step 6: Test laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_sync_orchestrator.py -v
```

Erwartet: PASS, alle Tests inkl. des neuen Ende-zu-Ende-Tests.

- [ ] **Step 7: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS, komplette Suite grün, keine Regressionen.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py
git commit -m "feat: wire Eskalations-Pruefung into the sync orchestrator after Klassenbuch/Fehlzeiten sync"
```

---

### Task 8: ROADMAP.md aktualisieren

**Files:**
- Modify: `ROADMAP.md`

**Interfaces:**
- Keine — reine Dokumentationsänderung.

- [ ] **Step 1: Eskalations-Engine von "Geplant" nach "Abgeschlossen" verschieben**

In `ROADMAP.md`, Punkt 1 aus der "Geplant"-Liste entfernen (Zeile beginnend mit "1. **Backend: Eskalations-Engine**") und die verbleibenden Punkte 2-6 zu 1-5 umnummerieren. In der "Abgeschlossen"-Tabelle eine neue Zeile ergänzen:

```markdown
| **Plan 3** — [Eskalations-Engine](docs/superpowers/plans/2026-07-26-eskalations-engine.md) | Schwellwert-Regeln (schulweit/abteilungsweit/klassenweit-Präzedenz), mehrstufige Eskalation, Maßnahmen-Katalog inkl. Default-Set und Zähler-Reset, Ausnahmen, Benachrichtigungs-Log (inkl. Empfänger-Auflösung und initial_import/kein_empfaenger-Sonderfälle) | Admin-UI/API für Regel-/Maßnahmen-Pflege, tatsächlicher E-Mail-Versand |
```

`Stand:`-Datum am Dateianfang auf das Datum des Merges aktualisieren.

- [ ] **Step 2: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: mark Eskalations-Engine plan complete in ROADMAP"
```
