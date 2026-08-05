# Bundle D — "Bereiche"-Abschnitt im WP-Backend entschlacken Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die "Bereiche"-Admin-Seite im WP-Backend verliert die manuelle Klassen-Zuordnung — Bereiche entstehen künftig verbindlich 1:1 aus den WebUntis-Abteilungen, der Admin pflegt nur noch Bereichsleiter und ein "Ausblenden"-Flag für historische/leere Bereiche.

**Architecture:** Neuer Backend-Sync-Schritt (`sync_bereiche`) leitet `bereich`/`bereich_klasse` bei jedem WebUntis-Sync-Lauf aus `abteilung`/`klasse.abteilung_id` ab (neue Spalten `bereich.abteilung_id`, `bereich.ausgeblendet`). Der Admin-Endpunkt `PUT /admin/bereiche` kann nur noch `ausgeblendet` und Bereichsleiter aktualisieren, nicht mehr Name/Klassen anlegen/löschen. Vier bestehende Downstream-Konsumenten (Scope-Auflösung, Schülerliste-Filter, Eskalations-Empfänger) bleiben unverändert, da `bereich_klasse` strukturell gleich bleibt. Das Dashboard-Nav/Diagramm filtert zusätzlich `ausgeblendet`. Das WP-Backend-Formular wird auf reine Anzeige (Name/Klassen) + zwei editierbare Felder (Bereichsleiter, Ausblenden-Checkbox) reduziert.

**Tech Stack:** FastAPI/SQLAlchemy 2.0 (async, PostgreSQL, Alembic), Pytest (`pytest-asyncio`), Vanilla-JS/PHP im WordPress-Plugin (kein Build-Step, kein automatisierter JS/PHP-Test).

**Referenz:** [Design-Dokument](../specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md)

## Global Constraints

- Commit-Messages auf Englisch (User-Vorgabe, global).
- Nach Abschluss dieses Plans sofort committen (Projekt-Konvention, `CLAUDE.md`).
- Kein Kommentar, der nur wiederholt was der Code schon sagt — nur "Warum", wenn nicht offensichtlich (Projekt-Konvention).
- Migration folgt dem bestehenden Alembic-Stil dieses Repos: expliziter `op.create_foreign_key`/`op.create_unique_constraint` mit benannten Constraints (siehe `backend/alembic/versions/bc7ae769066b_add_schuljahr_table.py`).
- Aktueller Alembic-Head zum Zeitpunkt der Planerstellung: `bc7ae769066b` (verifiziert via `docker exec absenzdash-backend python -m alembic heads`).
- Lokaler Dev-Stack läuft bereits als Docker-Container: `absenzdash-backend` (Backend, Port 8000), `absenzdash-db` (Postgres), `wp-test-wordpress-1` (WordPress, Port 8080), `wp-test-db-1` (MySQL). Migrationstests und die manuelle WP-Verifikation laufen gegen diese Container.

---

## Task 1: Migration — `bereich.abteilung_id` + `bereich.ausgeblendet`

**Files:**
- Create: `backend/alembic/versions/<generierter_hash>_add_bereich_abteilung_id_ausgeblendet.py`

**Interfaces:**
- Produces: DB-Spalten `bereich.abteilung_id` (Integer, nullable, FK → `abteilung.id`, unique, Constraint-Name `fk_bereich_abteilung_id`/`uq_bereich_abteilung_id`) und `bereich.ausgeblendet` (Boolean, not null, default `false`). Migration löscht zusätzlich alle bestehenden `bereich`-Zeilen (cascadiert auf `bereich_klasse`/`nutzer_bereich`).

- [ ] **Step 1: Migrationsdatei generieren**

```bash
docker exec absenzdash-backend python -m alembic revision -m "add bereich abteilung_id and ausgeblendet columns"
```

Notiere den erzeugten Dateinamen/Revision-Hash unter `backend/alembic/versions/`.

- [ ] **Step 2: Migration befüllen**

Ersetze den generierten Datei-Inhalt (Docstring/Revision-IDs aus Step 1 übernehmen, `down_revision` muss `'bc7ae769066b'` sein):

```python
"""add bereich abteilung_id and ausgeblendet columns

Bundle D: bereich wird verbindlich 1:1 aus abteilung abgeleitet (statt frei manuell
gepflegt), siehe docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.
Bestehende bereich/bereich_klasse/nutzer_bereich-Zeilen werden verworfen, der naechste
WebUntis-Sync-Lauf baut den Stand aus den aktuellen Abteilungen neu auf.

Revision ID: <HASH>
Revises: bc7ae769066b
Create Date: <DATUM>

"""
from alembic import op
import sqlalchemy as sa


revision = '<HASH>'
down_revision = 'bc7ae769066b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM bereich")
    op.add_column("bereich", sa.Column("abteilung_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_bereich_abteilung_id",
        "bereich",
        "abteilung",
        ["abteilung_id"],
        ["id"],
    )
    op.create_unique_constraint("uq_bereich_abteilung_id", "bereich", ["abteilung_id"])
    op.add_column(
        "bereich",
        sa.Column("ausgeblendet", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("bereich", "ausgeblendet", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_bereich_abteilung_id", "bereich", type_="unique")
    op.drop_constraint("fk_bereich_abteilung_id", "bereich", type_="foreignkey")
    op.drop_column("bereich", "abteilung_id")
    op.drop_column("bereich", "ausgeblendet")
```

(`<HASH>`/`<DATUM>` sind die von Alembic in Step 1 generierten Werte, nicht frei erfinden.)

- [ ] **Step 3: Migration gegen den laufenden Dev-Stack testen**

```bash
docker exec absenzdash-backend python -m alembic upgrade head
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d bereich"
```

Erwartet: `abteilung_id` (integer, FK auf `abteilung`, unique) und `ausgeblendet` (boolean, not null) sind in der Spaltenliste.

- [ ] **Step 4: Downgrade/Upgrade-Zyklus verifizieren**

```bash
docker exec absenzdash-backend python -m alembic downgrade -1
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d bereich"
docker exec absenzdash-backend python -m alembic upgrade head
```

Erwartet: nach `downgrade -1` fehlen beide Spalten wieder, nach erneutem `upgrade head` sind sie wieder da, kein Fehler in beiden Richtungen.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/
git commit -m "feat: add bereich.abteilung_id and bereich.ausgeblendet columns"
```

---

## Task 2: Model — `Bereich`-Spalten

**Files:**
- Modify: `backend/app/models/bereich.py`

**Interfaces:**
- Consumes: nichts Neues (reine Model-Erweiterung).
- Produces: `Bereich.abteilung_id: int | None`, `Bereich.ausgeblendet: bool` (Python-seitiger Default `False`) — von Task 3 (Sync) und Task 6 (Service) genutzt.

- [ ] **Step 1: Model erweitern**

Ersetze den kompletten Inhalt von `backend/app/models/bereich.py`:

```python
from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, String, Table
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
    abteilung_id: Mapped[int | None] = mapped_column(ForeignKey("abteilung.id"), unique=True, nullable=True)
    ausgeblendet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Import-Zyklus prüfen**

```bash
docker exec absenzdash-backend python -c "from app.models.bereich import Bereich; print(Bereich.__table__.columns.keys())"
```

Expected: `['id', 'name', 'abteilung_id', 'ausgeblendet', 'created_at', 'updated_at']` (Reihenfolge kann abweichen, alle sechs Namen müssen enthalten sein).

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/bereich.py
git commit -m "feat: add abteilung_id and ausgeblendet to Bereich model"
```

---

## Task 3: Sync-Service `sync_bereiche`

**Files:**
- Create: `backend/app/services/webuntis_bereich_sync.py`
- Test: `backend/tests/test_webuntis_bereich_sync.py`

**Interfaces:**
- Consumes: `app.models.abteilung.Abteilung`, `app.models.bereich.Bereich`/`bereich_klasse`, `app.models.klasse.Klasse` (aus Task 2).
- Produces: `async def sync_bereiche(db: AsyncSession) -> None` — konsumiert von Task 4 (Orchestrator).

- [ ] **Step 1: Fehlschlagende Tests schreiben**

```python
import pytest
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.services.webuntis_bereich_sync import sync_bereiche


@pytest.mark.asyncio
async def test_sync_bereiche_creates_bereich_per_abteilung_with_matching_klassen(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    klasse_zugehoerig = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung.id)
    klasse_fremd = Klasse(webuntis_id=2, name="2BFE")
    db_session.add_all([klasse_zugehoerig, klasse_fremd])
    await db_session.commit()

    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "Mechatronik"
    assert bereich.abteilung_id == abteilung.id
    assert bereich.ausgeblendet is False
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == [klasse_zugehoerig.id]


@pytest.mark.asyncio
async def test_sync_bereiche_creates_bereich_with_zero_klassen_for_empty_abteilung(db_session):
    db_session.add(Abteilung(webuntis_id=61, name="B-ALT", long_name="Historisch"))
    await db_session.commit()

    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "Historisch"
    klasse_ids = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
    ).scalars().all()
    assert klasse_ids == []


@pytest.mark.asyncio
async def test_sync_bereiche_falls_back_to_name_without_long_name(db_session):
    db_session.add(Abteilung(webuntis_id=59, name="B-IE", long_name=None))
    await db_session.commit()

    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    assert bereich.name == "B-IE"


@pytest.mark.asyncio
async def test_sync_bereiche_disambiguates_colliding_long_names(db_session):
    db_session.add_all(
        [
            Abteilung(webuntis_id=61, name="BT", long_name="Betriebstechnik"),
            Abteilung(webuntis_id=62, name="B-BT", long_name="Betriebstechnik"),
        ]
    )
    await db_session.commit()

    await sync_bereiche(db_session)

    namen = (await db_session.execute(select(Bereich.name))).scalars().all()
    assert sorted(namen) == ["Betriebstechnik (B-BT)", "Betriebstechnik (BT)"]


@pytest.mark.asyncio
async def test_sync_bereiche_updates_name_on_abteilung_rename(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.commit()
    await sync_bereiche(db_session)

    abteilung.long_name = "Mechatronik neu"
    await db_session.commit()
    await sync_bereiche(db_session)

    bereiche = (await db_session.execute(select(Bereich))).scalars().all()
    assert len(bereiche) == 1
    assert bereiche[0].name == "Mechatronik neu"


@pytest.mark.asyncio
async def test_sync_bereiche_rebuilds_bereich_klasse_when_klasse_moves_abteilung(db_session):
    abteilung_a = Abteilung(webuntis_id=1, name="A", long_name="Abteilung A")
    abteilung_b = Abteilung(webuntis_id=2, name="B", long_name="Abteilung B")
    db_session.add_all([abteilung_a, abteilung_b])
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="1ME", abteilung_id=abteilung_a.id)
    db_session.add(klasse)
    await db_session.commit()
    await sync_bereiche(db_session)

    klasse.abteilung_id = abteilung_b.id
    await db_session.commit()
    await sync_bereiche(db_session)

    bereich_a = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_a.id))).scalar_one()
    bereich_b = (await db_session.execute(select(Bereich).where(Bereich.abteilung_id == abteilung_b.id))).scalar_one()
    klasse_ids_a = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_a.id))
    ).scalars().all()
    klasse_ids_b = (
        await db_session.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_b.id))
    ).scalars().all()
    assert klasse_ids_a == []
    assert klasse_ids_b == [klasse.id]


@pytest.mark.asyncio
async def test_sync_bereiche_never_touches_ausgeblendet_or_leiter(db_session):
    abteilung = Abteilung(webuntis_id=51, name="B-ME", long_name="Mechatronik")
    db_session.add(abteilung)
    await db_session.commit()
    await sync_bereiche(db_session)

    bereich = (await db_session.execute(select(Bereich))).scalar_one()
    bereich.ausgeblendet = True
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")
    db_session.add(nutzer)
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer.id))
    await db_session.commit()

    await sync_bereiche(db_session)

    await db_session.refresh(bereich)
    assert bereich.ausgeblendet is True
    leiter_rows = (
        await db_session.execute(select(nutzer_bereich).where(nutzer_bereich.c.bereich_id == bereich.id))
    ).all()
    assert len(leiter_rows) == 1
```

- [ ] **Step 2: Tests ausführen, um Fehlschlag zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_webuntis_bereich_sync.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.webuntis_bereich_sync'`

- [ ] **Step 3: `sync_bereiche` implementieren**

```python
from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse


async def sync_bereiche(db: AsyncSession) -> None:
    """Leitet bereich/bereich_klasse verbindlich aus abteilung/klasse.abteilung_id ab (Bundle D).

    Legt fuer jede Abteilung genau einen Bereich an (1:1) und haelt bereich_klasse mit dem
    aktuellen klasse.abteilung_id-Stand synchron. `ausgeblendet` und die Bereichsleiter-
    Zuordnung (nutzer_bereich) sind reine Admin-Domaene und werden hier nie angefasst.
    Bereiche werden nie geloescht -- eine Abteilung mit aktuell 0 Klassen bekommt einfach
    eine leere bereich_klasse-Menge, siehe
    docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.
    """
    abteilungen = (await db.execute(select(Abteilung).order_by(Abteilung.name))).scalars().all()
    klassen = (await db.execute(select(Klasse))).scalars().all()
    existing_bereiche = (await db.execute(select(Bereich))).scalars().all()
    bereich_by_abteilung_id = {b.abteilung_id: b for b in existing_bereiche if b.abteilung_id is not None}

    klassen_by_abteilung: dict[int, list[int]] = {}
    for klasse in klassen:
        if klasse.abteilung_id is not None:
            klassen_by_abteilung.setdefault(klasse.abteilung_id, []).append(klasse.id)

    namen = [abteilung.long_name or abteilung.name for abteilung in abteilungen]
    # zwei Abteilungen koennen denselben long_name tragen (z.B. "BT" und "B-BT" -> beide
    # "Betriebstechnik"); bereich.name ist unique, kollidierende Namen muessen also
    # disambiguiert werden. Nicht-kollidierende Namen bleiben unveraendert.
    namen_anzahl = Counter(namen)

    for abteilung, name in zip(abteilungen, namen):
        if namen_anzahl[name] > 1:
            name = f"{name} ({abteilung.name})"

        bereich = bereich_by_abteilung_id.get(abteilung.id)
        if bereich is None:
            bereich = Bereich(abteilung_id=abteilung.id, name=name)
            db.add(bereich)
            await db.flush()
        else:
            bereich.name = name

        await db.execute(delete(bereich_klasse).where(bereich_klasse.c.bereich_id == bereich.id))
        for klasse_id in klassen_by_abteilung.get(abteilung.id, []):
            await db.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse_id))

    await db.flush()
```

- [ ] **Step 4: Tests ausführen, um Erfolg zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_webuntis_bereich_sync.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/webuntis_bereich_sync.py backend/tests/test_webuntis_bereich_sync.py
git commit -m "feat: derive bereich/bereich_klasse from WebUntis abteilungen"
```

---

## Task 4: Orchestrator-Anbindung

**Files:**
- Modify: `backend/app/services/sync_orchestrator.py:16-19,123-124`
- Test: `backend/tests/test_sync_orchestrator.py:38-47,61-74`

**Interfaces:**
- Consumes: `sync_bereiche(db: AsyncSession) -> None` (aus Task 3).

- [ ] **Step 1: Fehlschlagenden Test anpassen**

In `backend/tests/test_sync_orchestrator.py`, Zeile 43 (`monkeypatch.setattr(sync_orchestrator, "sync_kategorien", AsyncMock())`) direkt davor eine neue Zeile einfügen:

```python
    monkeypatch.setattr(sync_orchestrator, "sync_bereiche", AsyncMock())
```

In derselben Datei, in `test_run_full_sync_calls_phases_in_order` (ab Zeile 62), nach Zeile 65 (`sync_orchestrator.sync_klassen.side_effect = ...`) eine neue Zeile einfügen:

```python
    sync_orchestrator.sync_bereiche.side_effect = lambda *a: calls.append("bereiche")
```

und die Assertion in Zeile 74 anpassen:

```python
    assert calls == [
        "abteilungen", "klassen", "bereiche", "kategorien", "schueler", "fehlzeiten", "klassenbuch", "schwellwerte",
    ]
```

- [ ] **Step 2: Test ausführen, um Fehlschlag zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py::test_run_full_sync_calls_phases_in_order -v`
Expected: FAIL — `AttributeError: <module 'app.services.sync_orchestrator'> does not have the attribute 'sync_bereiche'`

- [ ] **Step 3: Orchestrator anpassen**

In `backend/app/services/sync_orchestrator.py`, Zeile 19 (`from app.services.webuntis_klassen_sync import sync_klassen`) direkt danach eine neue Import-Zeile einfügen:

```python
from app.services.webuntis_bereich_sync import sync_bereiche
```

In `run_sync_once`, Zeile 124 (`await sync_klassen(client, db, schoolyear_id=aktuelles_schuljahr.id)`) direkt danach eine neue Zeile einfügen:

```python
        await sync_bereiche(db)
```

- [ ] **Step 4: Tests ausführen, um Erfolg zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py -v`
Expected: alle Tests in der Datei PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_orchestrator.py backend/tests/test_sync_orchestrator.py
git commit -m "feat: run sync_bereiche after abteilungen/klassen in orchestrator"
```

---

## Task 5: Schemas — `admin.py`

**Files:**
- Modify: `backend/app/schemas/admin.py:105-146`

**Interfaces:**
- Produces: `BereichIn(id: int, ausgeblendet: bool = False, leiter: list[BereichLeiterIn] = [])`, `BereichOut(id: int, name: str, klasse_namen: list[str], ausgeblendet: bool, leiter: list[BereichLeiterOut])` — konsumiert von Task 6 (Service) und Task 7 (Routes).

- [ ] **Step 1: Schemas anpassen**

Ersetze in `backend/app/schemas/admin.py` den Block von Zeile 105 (`class KlasseOut`) bis Zeile 146 (Ende `BereichVorschlagOut`) durch:

```python
class AbteilungOut(BaseModel):
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
    id: int
    ausgeblendet: bool = False
    leiter: list[BereichLeiterIn] = []


class BereichOut(BaseModel):
    id: int
    name: str
    klasse_namen: list[str]
    ausgeblendet: bool
    leiter: list[BereichLeiterOut]
```

(`KlasseOut` und `BereichVorschlagOut` entfallen ersatzlos — nicht mehr referenziert nach Task 6/7.)

- [ ] **Step 2: Import-Zyklus prüfen**

```bash
docker exec absenzdash-backend python -c "from app.schemas.admin import BereichIn, BereichOut; print(BereichIn.model_fields.keys()); print(BereichOut.model_fields.keys())"
```

Expected: kein Fehler; `BereichIn` zeigt `dict_keys(['id', 'ausgeblendet', 'leiter'])`, `BereichOut` zeigt `dict_keys(['id', 'name', 'klasse_namen', 'ausgeblendet', 'leiter'])`.

- [ ] **Step 3: Commit**

Noch nicht committen — `bereich_service.py`/`admin.py`-Routen importieren in Task 6/7 noch die alten Namen (`KlasseOut`, `BereichVorschlagOut`), der Import würde brechen. Weiter mit Task 6.

---

## Task 6: Service — `bereich_service.py` neu schreiben

**Files:**
- Modify: `backend/app/services/bereich_service.py` (kompletter Neuschrieb)
- Modify: `backend/tests/test_bereich_service.py` (kompletter Neuschrieb)

**Interfaces:**
- Consumes: `BereichIn`/`BereichOut` (Task 5), `Bereich`/`bereich_klasse` (Task 2).
- Produces: `async def list_bereiche(db) -> list[BereichOut]`, `async def update_bereiche(db, payload: list[BereichIn], admin_nutzer_id: int) -> list[BereichOut]`, `async def list_abteilungen(db) -> list[AbteilungOut]` (unverändert) — konsumiert von Task 7 (Routes).

- [ ] **Step 1: Tests komplett neu schreiben**

Ersetze den kompletten Inhalt von `backend/tests/test_bereich_service.py`:

```python
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import BereichIn, BereichLeiterIn
from app.services.bereich_service import list_abteilungen, list_bereiche, update_bereiche


@pytest.mark.asyncio
async def test_list_abteilungen_returns_all_sorted_by_name(db_session):
    db_session.add_all([Abteilung(webuntis_id=2, name="B"), Abteilung(webuntis_id=1, name="A")])
    await db_session.commit()

    result = await list_abteilungen(db_session)

    assert [a.name for a in result] == ["A", "B"]


@pytest.mark.asyncio
async def test_list_bereiche_includes_klasse_namen_and_ausgeblendet(db_session):
    klasse = Klasse(webuntis_id=1, name="1BFE")
    db_session.add(klasse)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik", ausgeblendet=True)
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    result = await list_bereiche(db_session)

    assert result[0].name == "Mechatronik"
    assert result[0].klasse_namen == ["1BFE"]
    assert result[0].ausgeblendet is True


@pytest.mark.asyncio
async def test_update_bereiche_sets_ausgeblendet(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [BereichIn(id=bereich.id, ausgeblendet=True, leiter=[])]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].ausgeblendet is True
    await db_session.refresh(bereich)
    assert bereich.ausgeblendet is True


@pytest.mark.asyncio
async def test_update_bereiche_does_not_change_name_or_klassen(db_session):
    klasse = Klasse(webuntis_id=1, name="1BFE")
    db_session.add(klasse)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    await db_session.commit()

    payload = [BereichIn(id=bereich.id, ausgeblendet=False, leiter=[])]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].name == "Mechatronik"
    assert result[0].klasse_namen == ["1BFE"]


@pytest.mark.asyncio
async def test_update_bereiche_creates_nutzer_stub_for_new_leiter(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(
            id=bereich.id,
            ausgeblendet=False,
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert len(result[0].leiter) == 1
    assert result[0].leiter[0].wp_user_id == "99"
    nutzer = (await db_session.execute(select(Nutzer).where(Nutzer.wp_user_id == "99"))).scalar_one()
    assert nutzer.rolle == "bereichsleiter"


@pytest.mark.asyncio
async def test_update_bereiche_does_not_overwrite_rolle_of_existing_nutzer(db_session):
    nutzer = Nutzer(wp_user_id="99", email="a@b.de", name="A B", rolle="schulleitung")
    bereich = Bereich(name="Mechatronik")
    db_session.add_all([nutzer, bereich])
    await db_session.commit()

    payload = [
        BereichIn(
            id=bereich.id,
            ausgeblendet=False,
            leiter=[BereichLeiterIn(wp_user_id="99", email="a@b.de", name="A B", rolle="bereichsleiter")],
        )
    ]
    await update_bereiche(db_session, payload, admin_nutzer_id=None)

    await db_session.refresh(nutzer)
    assert nutzer.rolle == "schulleitung"


@pytest.mark.asyncio
async def test_update_bereiche_replaces_leiter_set(db_session):
    bereich = Bereich(name="Mechatronik")
    nutzer_alt = Nutzer(wp_user_id="1", email="a@b.de", name="Alt", rolle="bereichsleiter")
    db_session.add_all([bereich, nutzer_alt])
    await db_session.flush()
    await db_session.execute(nutzer_bereich.insert().values(bereich_id=bereich.id, nutzer_id=nutzer_alt.id))
    await db_session.commit()

    payload = [BereichIn(id=bereich.id, ausgeblendet=False, leiter=[])]
    result = await update_bereiche(db_session, payload, admin_nutzer_id=None)

    assert result[0].leiter == []
    remaining = (await db_session.execute(select(nutzer_bereich))).all()
    assert remaining == []
    # der Nutzer selbst bleibt bestehen, nur die Zuordnung verschwindet
    assert (await db_session.execute(select(Nutzer).where(Nutzer.id == nutzer_alt.id))).scalar_one() is not None


@pytest.mark.asyncio
async def test_update_bereiche_rejects_duplicate_id(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(id=bereich.id, ausgeblendet=False, leiter=[]),
        BereichIn(id=bereich.id, ausgeblendet=True, leiter=[]),
    ]
    with pytest.raises(HTTPException) as exc_info:
        await update_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_bereiche_rejects_unknown_id(db_session):
    payload = [BereichIn(id=999999, ausgeblendet=False, leiter=[])]
    with pytest.raises(HTTPException) as exc_info:
        await update_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_bereiche_rejects_unknown_rolle(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [
        BereichIn(
            id=bereich.id, ausgeblendet=False,
            leiter=[BereichLeiterIn(wp_user_id="1", email="a@b.de", name="A", rolle="oberlehrer")],
        )
    ]
    with pytest.raises(HTTPException) as exc_info:
        await update_bereiche(db_session, payload, admin_nutzer_id=None)
    assert exc_info.value.status_code == 422
```

- [ ] **Step 2: Tests ausführen, um Fehlschlag zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_bereich_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_bereiche' from 'app.services.bereich_service'`

- [ ] **Step 3: `bereich_service.py` neu schreiben**

Ersetze den kompletten Inhalt von `backend/app/services/bereich_service.py`:

```python
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.bereich import Bereich, bereich_klasse
from app.models.klasse import Klasse
from app.models.nutzer import ROLLEN, Nutzer
from app.models.nutzer_bereich import nutzer_bereich
from app.schemas.admin import AbteilungOut, BereichIn, BereichLeiterOut, BereichOut


async def list_abteilungen(db: AsyncSession) -> list[AbteilungOut]:
    result = await db.execute(select(Abteilung).order_by(Abteilung.name))
    return [AbteilungOut(id=a.id, name=a.name) for a in result.scalars().all()]


async def _bereich_out(db: AsyncSession, bereich: Bereich) -> BereichOut:
    klasse_namen = (
        await db.execute(
            select(Klasse.name)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
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
        klasse_namen=list(klasse_namen),
        ausgeblendet=bereich.ausgeblendet,
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
        if bereich.id in seen_ids:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Duplicate id in payload: {bereich.id}")
        seen_ids.add(bereich.id)
    for bereich in payload:
        for leiter in bereich.leiter:
            if leiter.rolle not in ROLLEN:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown rolle: {leiter.rolle}")


async def _get_or_create_nutzer_stub(db: AsyncSession, wp_user_id: str, email: str, name: str, rolle: str) -> Nutzer:
    """Get-or-Create fuer eine als Bereichsleiter zugewiesene Person.

    Setzt `rolle` NUR bei Neuanlage (nutzer.rolle ist NOT NULL, ein frisch
    zugewiesener Bereichsleiter ohne vorherigen Login braucht einen gueltigen
    Startwert). Eine bereits bestehende `nutzer`-Zeile behaelt ihre Rolle --
    die Rollenzuweisung selbst passiert ausschliesslich ueber die
    Rollen-Zuweisungs-Seite, nicht hier.
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


async def update_bereiche(db: AsyncSession, payload: list[BereichIn], admin_nutzer_id: int) -> list[BereichOut]:
    """Aktualisiert `ausgeblendet` und die Bereichsleiter-Zuordnung fuer bestehende,
    sync-abgeleitete Bereiche.

    Kann keine Bereiche anlegen oder loeschen -- das uebernimmt ausschliesslich
    webuntis_bereich_sync.sync_bereiche bei jedem WebUntis-Sync-Lauf, siehe
    docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md.
    """
    _validate_payload(payload)

    existing = (await db.execute(select(Bereich))).scalars().all()
    by_id = {b.id: b for b in existing}

    unknown_ids = {item.id for item in payload} - set(by_id.keys())
    if unknown_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown id(s): {sorted(unknown_ids)}")

    result_bereiche: list[Bereich] = []
    for item in payload:
        bereich = by_id[item.id]
        bereich.ausgeblendet = item.ausgeblendet
        result_bereiche.append(bereich)

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

    return [await _bereich_out(db, b) for b in result_bereiche]
```

- [ ] **Step 4: Tests ausführen, um Erfolg zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_bereich_service.py -v`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/bereich_service.py backend/tests/test_bereich_service.py
git commit -m "refactor: bereich_service only updates ausgeblendet/leiter, no longer klassen/name"
```

---

## Task 7: Routen — `admin.py`

**Files:**
- Modify: `backend/app/api/routes/admin.py:14-73`
- Modify: `backend/tests/test_api_admin_bereiche.py` (kompletter Neuschrieb)

**Interfaces:**
- Consumes: `bereich_service.list_bereiche`, `bereich_service.update_bereiche`, `bereich_service.list_abteilungen` (Task 6).

- [ ] **Step 1: Tests komplett neu schreiben**

Ersetze den kompletten Inhalt von `backend/tests/test_api_admin_bereiche.py`:

```python
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.main import app
from app.models.abteilung import Abteilung
from app.models.audit_log import AuditLog
from app.models.bereich import Bereich

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
async def test_get_bereiche_rejects_non_schulleitung(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche", headers=HEADERS_KLASSENLEHRKRAFT)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_bereiche_returns_klasse_namen_and_ausgeblendet(db_session):
    db_session.add(Bereich(name="Mechatronik", ausgeblendet=True))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/bereiche", headers=HEADERS_SCHULLEITUNG)

    assert response.status_code == 200
    body = response.json()[0]
    assert body["name"] == "Mechatronik"
    assert body["klasse_namen"] == []
    assert body["ausgeblendet"] is True


@pytest.mark.asyncio
async def test_put_bereiche_updates_ausgeblendet_and_logs_audit(db_session):
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.commit()

    payload = [{"id": bereich.id, "ausgeblendet": True, "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)

    assert response.status_code == 200
    assert response.json()[0]["ausgeblendet"] is True

    audit = await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_bereiche_updated"))
    assert audit.scalar_one() is not None


@pytest.mark.asyncio
async def test_put_bereiche_rejects_unknown_id(db_session):
    payload = [{"id": 999999, "ausgeblendet": False, "leiter": []}]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/admin/bereiche", headers=HEADERS_SCHULLEITUNG, json=payload)
    assert response.status_code == 422


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

- [ ] **Step 2: Tests ausführen, um Fehlschlag zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_admin_bereiche.py -v`
Expected: FAIL (Route liefert noch alte `BereichOut`-Form ohne `klasse_namen`, `PUT`-Schema erwartet noch `name`/`klasse_ids`)

- [ ] **Step 3: Routen anpassen**

In `backend/app/api/routes/admin.py`:

Ersetze den Import-Block (Zeile 14-29, `from app.schemas.admin import (...)`) durch:

```python
from app.schemas.admin import (
    AbteilungOut,
    BereichIn,
    BereichOut,
    ExcuseStatusIn,
    ExcuseStatusOut,
    MeasureTypeIn,
    MeasureTypeOut,
    SyncNowOut,
    SyncSettingsIn,
    SyncSettingsOut,
    TestEmailOut,
    ThresholdRuleIn,
    ThresholdRuleOut,
    WebUntisTeacherOut,
)
```

Ersetze den Routen-Block von Zeile 46 (`@router.get("/klassen")`) bis Zeile 73 (`return await bereich_service.vorschlag_aus_abteilungen(db)`) durch:

```python
@router.get("/abteilungen")
async def get_abteilungen(db: Annotated[AsyncSession, Depends(get_db)]) -> list[AbteilungOut]:
    return await bereich_service.list_abteilungen(db)


@router.get("/bereiche")
async def get_bereiche(db: Annotated[AsyncSession, Depends(get_db)]) -> list[BereichOut]:
    return await bereich_service.list_bereiche(db)


@router.put("/bereiche")
async def put_bereiche(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: list[BereichIn],
) -> list[BereichOut]:
    return await bereich_service.update_bereiche(db, payload, nutzer.id)
```

- [ ] **Step 4: Tests ausführen, um Erfolg zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_admin_bereiche.py -v`
Expected: alle Tests PASS

- [ ] **Step 5: Komplette Backend-Testsuite laufen lassen**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS (bestätigt, dass die vier unveränderten Downstream-Konsumenten — `deps.py`, `student_query.py`, `eskalations_pruefung.py` — weiter funktionieren)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/admin.py backend/tests/test_api_admin_bereiche.py
git commit -m "refactor: remove GET /admin/klassen and vorschlag-aus-abteilungen endpoints"
```

---

## Task 8: Dashboard — `ausgeblendet`-Filter, Aufräumen des `func.min()`-Workarounds

**Files:**
- Modify: `backend/app/services/dashboard_query.py:38-67,189-199`
- Test: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- Consumes: `Bereich.ausgeblendet` (Task 2).

- [ ] **Step 1: Fehlschlagende Tests hinzufügen**

Füge in `backend/tests/test_dashboard_query.py` folgende zwei Tests an das Dateiende an:

```python
@pytest.mark.asyncio
async def test_get_nav_options_excludes_ausgeblendete_bereiche(db_session):
    bereich_sichtbar = Bereich(name="Ausbildung")
    bereich_versteckt = Bereich(name="Historisch", ausgeblendet=True)
    db_session.add_all([bereich_sichtbar, bereich_versteckt])
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    options = await dashboard_query.get_nav_options(db_session, nutzer)

    assert {b.name for b in options.bereiche} == {"Ausbildung"}


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_excludes_ausgeblendete_bereiche(db_session):
    bereich_sichtbar = Bereich(name="Ausbildung")
    bereich_versteckt = Bereich(name="Historisch", ausgeblendet=True)
    db_session.add_all([bereich_sichtbar, bereich_versteckt])
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None)

    namen = {v.name for v in stats.vergleich}
    assert namen == {"Ausbildung"}
```

- [ ] **Step 2: Tests ausführen, um Fehlschlag zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -k ausgeblendet -v`
Expected: FAIL (beide neuen Tests, `bereich_versteckt` taucht noch auf)

- [ ] **Step 3: `get_nav_options` und `_stats_schulweit` anpassen**

In `backend/app/services/dashboard_query.py`, ersetze Zeile 38 (`query = select(Bereich).order_by(Bereich.name)`) durch:

```python
        query = select(Bereich).where(Bereich.ausgeblendet.is_(False)).order_by(Bereich.name)
```

Ersetze den kommentierten `func.min()`-Block (Zeile 51-67) durch:

```python
    klasse_bereich_map = dict(
        (await db.execute(select(bereich_klasse.c.klasse_id, bereich_klasse.c.bereich_id))).all()
    )
```

In `_stats_schulweit`, ersetze Zeile 191 (`bereiche = (await db.execute(select(Bereich).order_by(Bereich.name))).scalars().all()`) durch:

```python
    bereiche = (
        await db.execute(select(Bereich).where(Bereich.ausgeblendet.is_(False)).order_by(Bereich.name))
    ).scalars().all()
```

- [ ] **Step 4: Tests ausführen, um Erfolg zu bestätigen**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -v`
Expected: alle Tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "feat: hide ausgeblendet bereiche from dashboard nav/comparisons"
```

---

## Task 9: WordPress-Backend-UI vereinfachen

**Files:**
- Modify: `wordpress-plugin/absenzdash/includes/class-bereiche-seite.php:66-78`
- Modify: `wordpress-plugin/absenzdash/assets/admin/bereiche-seite.js` (kompletter Neuschrieb)

**Interfaces:**
- Consumes: `GET/PUT /admin/bereiche` (Task 7), neue Response-/Payload-Form `{id, name, klasse_namen, ausgeblendet, leiter}` / `{id, ausgeblendet, leiter}`.

- [ ] **Step 1: PHP-Seite anpassen**

Ersetze in `wordpress-plugin/absenzdash/includes/class-bereiche-seite.php` die Methode `render_seite()` (Zeile 62-78):

```php
	public function render_seite(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		?>
		<div class="wrap">
			<h1>AbsenzDash — Bereichsdefinition</h1>
			<p>Bereiche werden automatisch aus den WebUntis-Abteilungen übernommen. Hier können Bereichsleiter zugewiesen und historische/leere Bereiche ausgeblendet werden.</p>
			<div id="absenzdash-bereiche-fehler" style="color:#b32d2e;"></div>
			<div id="absenzdash-bereiche-liste"></div>
			<p><button type="button" id="absenzdash-bereiche-speichern" class="button button-primary">Speichern</button></p>
		</div>
		<?php
	}
```

- [ ] **Step 2: JS komplett neu schreiben**

Ersetze den kompletten Inhalt von `wordpress-plugin/absenzdash/assets/admin/bereiche-seite.js`:

```javascript
(function () {
	var zustand = { bereiche: [] };

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
		var leiterAuswahl = mehrfachauswahl(
			absenzdashBereicheConfig.wpNutzer, 'wp_user_id',
			function (n) { return n.name + ' (' + (n.rolle || 'keine Rolle') + ')'; },
			(bereich.leiter || []).map(function (l) { return l.wp_user_id; }),
			'absenzdash-bereich-leiter'
		);
		var ausblendenCheckbox = element('input', { type: 'checkbox', class: 'absenzdash-bereich-ausblenden' });
		ausblendenCheckbox.checked = !!bereich.ausgeblendet;

		var zeile = element('div', { class: 'absenzdash-bereich-zeile', style: 'border:1px solid #ccd0d4; padding:10px; margin-bottom:10px;' }, [
			element('strong', { text: bereich.name || '' }),
			element('br', {}),
			element('span', { text: 'Klassen: ' + ((bereich.klasse_namen || []).join(', ') || '(keine)') }),
			element('br', {}),
			element('label', { text: 'Bereichsleiter: ' }), leiterAuswahl,
			element('br', {}),
			element('label', {}, [ausblendenCheckbox, document.createTextNode(' Ausblenden (aus Dashboard/Diagrammen)')])
		]);
		zeile.dataset.bereichId = String(bereich.id);

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
		var element = document.getElementById('absenzdash-bereiche-fehler');
		element.textContent = nachricht;
		if (nachricht) {
			element.style.background = '#fbeaea';
			element.style.border = '1px solid #b32d2e';
			element.style.padding = '8px 12px';
			element.scrollIntoView({ behavior: 'smooth', block: 'start' });
		} else {
			element.style.background = '';
			element.style.border = '';
			element.style.padding = '';
		}
	}

	function laden() {
		fetch(absenzdashBereicheConfig.restUrl + '/admin/bereiche', {
			headers: { 'X-WP-Nonce': absenzdashBereicheConfig.nonce }
		}).then(function (r) {
			if (!r.ok) { throw new Error('Bereiche laden fehlgeschlagen (HTTP ' + r.status + ')'); }
			return r.json();
		}).then(function (bereiche) {
			zustand.bereiche = bereiche;
			bereicheNeuRendern();
		}).catch(function (fehler) {
			fehlerAnzeigen(fehler.message);
		});
	}

	function ausZeilenLesen() {
		var zeilen = document.querySelectorAll('.absenzdash-bereich-zeile');
		return Array.prototype.map.call(zeilen, function (zeile) {
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
			return {
				id: Number(zeile.dataset.bereichId),
				ausgeblendet: zeile.querySelector('.absenzdash-bereich-ausblenden').checked,
				leiter: leiter
			};
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
		document.getElementById('absenzdash-bereiche-speichern').addEventListener('click', speichern);
	});
})();
```

- [ ] **Step 3: Manuelle Verifikation gegen den laufenden Dev-Stack**

Der Dev-Stack läuft bereits (`wp-test-wordpress-1` auf Port 8080, `absenzdash-backend` auf Port 8000, verbunden über das `absenzflow-shared`-Docker-Netzwerk). Da es weder JS- noch PHP-Tests in diesem Repo gibt, ist dies die einzige Verifikation dieses Tasks:

1. Im Browser `http://localhost:8080/wp-admin/admin.php?page=absenzdash-bereiche` öffnen.
2. Prüfen: Seite lädt ohne Konsolenfehler, zeigt pro WebUntis-Abteilung eine Zeile mit Name (fett, nicht editierbar), "Klassen: ..." (Text, nicht editierbar), Bereichsleiter-Mehrfachauswahl, Ausblenden-Checkbox. Kein "Aus WebUntis-Abteilungen vorbefüllen"-, "Bereich hinzufügen"- oder "Entfernen"-Button mehr sichtbar.
3. Bei einem Bereich einen Bereichsleiter auswählen, "Speichern" klicken — Seite zeigt danach die gespeicherte Auswahl weiterhin an (kein Datenverlust nach Reload).
4. Bei einem anderen Bereich "Ausblenden" anhaken, speichern, dann im Dashboard-Frontend (SPA, Landing-Page) prüfen, dass dieser Bereich nicht mehr im Bereich-Dropdown/Diagramm auftaucht.
5. Browser-Konsole (Netzwerk-Tab) prüfen: `PUT /admin/bereiche`-Request-Body enthält nur `id`/`ausgeblendet`/`leiter`, keine `name`/`klasse_ids`-Felder mehr.

Wenn ein Schritt fehlschlägt: root cause fixen (nicht den Test überspringen), dann Schritt 3 erneut komplett durchlaufen.

- [ ] **Step 4: Commit**

```bash
git add wordpress-plugin/absenzdash/includes/class-bereiche-seite.php wordpress-plugin/absenzdash/assets/admin/bereiche-seite.js
git commit -m "refactor: Bereiche admin page shows only bereichsleiter/ausblenden as editable"
```

---

## Task 10: Dokumentation

**Files:**
- Modify: `TECH-SPEC.md:102,158,161,178,~163`
- Modify: `ROADMAP.md:26,42`

**Interfaces:**
- Keine (reine Doku).

- [ ] **Step 1: TECH-SPEC.md — Datenbank-Schema-Tabelle**

In der Tabelle (Abschnitt "2. Datenbank-Schema"), Zeile 102-103, ersetze die `bereich`/`bereich_klasse`-Zeilen:

```
| `bereich`               | `name`, `abteilung_id` (nullable FK auf `abteilung`, unique), `ausgeblendet` (bool, default `false`)                                                                                                                                                                    | 1:1 aus `abteilung` abgeleitet, verbindlich vom Sync geschrieben (nicht mehr manuell editierbar), siehe Bundle D. `ausgeblendet` blendet historische/leere Bereiche aus Dashboard-Nav/-Diagrammen aus |
| `bereich_klasse` (m:n)  | `bereich_id`, `klasse_id`                                                                                                                                                                                                                                                 | Wird bei jedem WebUntis-Sync aus `klasse.abteilung_id` neu aufgebaut (`webuntis_bereich_sync.sync_bereiche`), kein Admin-Schreibzugriff mehr                                                       |
```

- [ ] **Step 2: TECH-SPEC.md — API-Vertrag-Tabelle**

Entferne Zeile 158 (`GET /admin/klassen`) und Zeile 161 (`GET /admin/bereiche/vorschlag-aus-abteilungen`) komplett aus der Endpunkt-Tabelle.

Ersetze die `GET/PUT /admin/bereiche`-Zeile (Zeile 160, direkt vor der zu entfernenden `vorschlag-aus-abteilungen`-Zeile):

```
| `GET/PUT /admin/bereiche` | Bereiche lesen (inkl. `klasse_namen`, aus `abteilung` abgeleitet) bzw. nur `ausgeblendet`/Bereichsleiter aktualisieren — Name/Klassen-Zuordnung sind nicht editierbar (siehe Bundle D, ROADMAP.md) | nur `schulleitung` |
```

- [ ] **Step 3: TECH-SPEC.md — Prosa-Absatz zur Bereichsdefinition**

In Zeile 178, ersetze den Satz beginnend mit "Bereichsdefinition (Klassen ↔ Bereich, Bereich ↔ Bereichsleiter)..." bis zum Ende des Absatzes durch:

```
- Bereichsdefinition (Bereich ↔ Bereichsleiter, Bereich-Sichtbarkeit) und manuelle Zusatz-Klassenlehrkraft-Zuordnungen: administrative Oberfläche ist gemäß SPECS.md Abschnitt 2 das **WP-Backend**, umgesetzt als eigene Options-Unterseite `class-bereiche-seite.php` (`wordpress-plugin/absenzdash/includes/`, Menü „AbsenzDash-Bereiche“, ebenfalls gated auf `manage_options`). Die Klassen-Zuordnung selbst ist seit Bundle D nicht mehr admin-editierbar — sie wird verbindlich 1:1 aus der WebUntis-Abteilung abgeleitet (`webuntis_bereich_sync.sync_bereiche`, läuft bei jedem WebUntis-Sync). Die Daten werden weiterhin **abweichend von VertretungsFlows Options-API/User-Meta-Pattern** nicht in WordPress, sondern direkt in der AbsenzDash-Datenbank gehalten (Tabellen `bereich`, `bereich_klasse`, `nutzer_klasse` mit `quelle='manuell'`, siehe Abschnitt 2): Diese WP-Admin-Seite ruft dafür lesend/schreibend die AbsenzDash-Backend-API auf (Abschnitt 3), statt eigene WP-Optionen/-Postmeta zu pflegen. Fachliche Konfiguration (Schwellwerte, Maßnahmen-Katalog, Sync-Intervall) bleibt wie in SPECS.md Abschnitt 2/3 festgelegt ausschließlich im Dashboard-Admin-Bereich (SPA), nicht im WP-Backend.
```

- [ ] **Step 4: ROADMAP.md aktualisieren**

Markiere Bundle D (Zeile 42) als erledigt — ersetze den kompletten Absatz beginnend mit `**Bundle D — "Bereiche"-Abschnitt im WP-Backend entschlacken**` durch:

```
✅ **Bundle D — "Bereiche"-Abschnitt im WP-Backend entschlacken — erledigt 2026-08-05:** Bereiche werden jetzt verbindlich 1:1 aus den WebUntis-Abteilungen abgeleitet (`webuntis_bereich_sync.sync_bereiche`, läuft bei jedem WebUntis-Sync nach `sync_abteilungen`/`sync_klassen`), statt manuell im WP-Backend gepflegt zu werden. Neue Spalten `bereich.abteilung_id` (unique FK) und `bereich.ausgeblendet` (bool). `PUT /admin/bereiche` kann nur noch `ausgeblendet` und Bereichsleiter setzen, nicht mehr Name/Klassen. Entfernt: `GET /admin/klassen`, `GET /admin/bereiche/vorschlag-aus-abteilungen`. Die WP-Backend-Seite zeigt Name/Klassen nur noch read-only, editierbar bleiben Bereichsleiter-Zuordnung und die neue Ausblenden-Checkbox (blendet historische/leere Bereiche aus Dashboard-Nav/-Diagrammen aus, ohne Daten zu löschen). Löst zugleich den Technical-Debt-Eintrag zum `func.min()`-Workaround in `dashboard_query.py::get_nav_options` (Klasse-in-mehreren-Bereichen-Mehrdeutigkeit ist durch die 1:1-Abteilungskopplung strukturell nicht mehr möglich). Siehe [Design-Dok](docs/superpowers/specs/2026-08-05-bundle-d-bereiche-entschlacken-design.md) und [Plan](docs/superpowers/plans/2026-08-05-bundle-d-bereiche-entschlacken.md).
```

Im Abschnitt "Technical debt", entferne den kompletten Eintrag `**\`klasse_bereich_map\` in \`get_nav_options\` wählt bei Mehrfachzuordnung nur einen Bereich pro Klasse** (...)`.

- [ ] **Step 5: Commit**

```bash
git add TECH-SPEC.md ROADMAP.md
git commit -m "docs: mark Bundle D as complete, update TECH-SPEC bereich section"
```

---

## Self-Review (durchgeführt beim Schreiben dieses Plans)

**Spec-Abdeckung:** Datenmodell (Task 1-2) ✓, Sync-Logik (Task 3-4) ✓, Backend-API (Task 5-7) ✓, Downstream-Konsumenten inkl. `ausgeblendet`-Filter und `func.min()`-Aufräumen (Task 8, die drei unveränderten Konsumenten werden in Task 7 Step 5 durch die volle Testsuite mitverifiziert) ✓, WP-Backend-UI (Task 9) ✓, Testing-Abschnitt des Designs (Migration-Verifikation, WP-Live-Test) ✓, Doku-Pflicht aus `CLAUDE.md` (Task 10) ✓.

**Placeholder-Scan:** keine TBD/TODO, alle Code-Blöcke vollständig, kein "siehe Task N" ohne Code-Wiederholung.

**Typ-Konsistenz:** `BereichIn`/`BereichOut` (Task 5) exakt wie in Task 6 (`bereich_service.py`) und Task 7 (Routen) sowie Task 9 (JS-Payload-Form) verwendet — `id`/`ausgeblendet`/`leiter` durchgängig, kein `name`/`klasse_ids` mehr in `BereichIn`. `sync_bereiche(db: AsyncSession) -> None` identisch in Task 3 (Definition) und Task 4 (Aufruf im Orchestrator).
