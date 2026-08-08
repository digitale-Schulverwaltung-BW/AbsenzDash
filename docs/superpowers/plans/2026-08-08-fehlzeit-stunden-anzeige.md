# Fehlzeiten mit Stundenangabe statt Uhrzeit anzeigen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nicht-ganztägige Fehlzeiten zeigen in Schüler-Details und PDF-Export künftig `"15 Minuten (Stunde 1)"` statt einer rohen Uhrzeit-Spanne, basierend auf einem aus WebUntis synchronisierten Stundenraster.

**Architecture:** Ein neuer, low-priority WebUntis-Sync-Schritt (`sync_stundenraster`) cacht den schulweiten Stundenraster (`getTimegridUnits`) in einer neuen Tabelle `stundenraster_periode`. Eine neue Backend-Funktion (`fehlzeit_berechnung.dauer_anzeige`) berechnet pro Fehlzeit ein einziges Anzeige-Label (Minuten + betroffene Stunde(n), oder Fallback auf formatierte Uhrzeit), das im `GET /students/{id}`-Response (`FehlzeitOut.dauer_anzeige`) und im PDF-Export gemeinsam verwendet wird — Frontend und PDF-Template zeigen es nur noch an, ohne eigene Berechnungslogik.

**Tech Stack:** FastAPI/SQLAlchemy 2.0 (async, PostgreSQL, Alembic), Pytest (`pytest-asyncio`), React/TypeScript, Vitest.

**Referenz:** [Design-Dokument](../specs/2026-08-08-fehlzeit-stunden-anzeige-design.md), [TECH-SPEC.md Abschnitt 1.4](../../../TECH-SPEC.md)

## Global Constraints

- Commit-Messages auf Englisch (User-Vorgabe, global).
- Nach Abschluss dieses Plans sofort committen (Projekt-Konvention, `CLAUDE.md`).
- Kein Kommentar, der nur wiederholt was der Code schon sagt — nur "Warum", wenn nicht offensichtlich (Projekt-Konvention).
- `getTimegridUnits` nimmt **ausschließlich einen leeren Parameter-Body (`{}`)** entgegen — live verifiziert 2026-08-08, jeder zusätzliche Parameter (`elementType`/`elementId`, `schoolyearId`) führt zu `Method not found` (TECH-SPEC.md Abschnitt 1.4).
- WebUntis' `day`-Feld in der `getTimegridUnits`-Antwort folgt der Konvention **1=Sonntag…7=Samstag** — muss beim Sync explizit auf ISO-Wochentag (1=Montag…7=Sonntag, wie `date.isoweekday()`) umgerechnet werden, bevor er in `stundenraster_periode.wochentag` geschrieben wird. Intern (DB, Lookup-Logik) wird ausschließlich die ISO-Konvention verwendet.
- Aktueller Alembic-Head zum Zeitpunkt der Planerstellung: `7a2c0d9d6057` (per `alembic/versions/*.py`-Revisionskette ermittelt).
- Lokaler Dev-Stack läuft als Docker-Container: `absenzdash-backend` (Backend, Port 8000), `absenzdash-db` (Postgres). Migrationstests laufen gegen diese Container.

---

## Task 1: Datenmodell — `stundenraster_periode`

**Files:**
- Create: `backend/app/models/stundenraster_periode.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/<generierter_hash>_add_stundenraster_periode_table.py`
- Test: `backend/tests/test_models_stundenraster_periode.py`

**Interfaces:**
- Produces: Model-Klasse `StundenrasterPeriode` mit `id: int`, `wochentag: int` (ISO, 1=Montag…7=Sonntag), `stunde_nr: int`, `start_zeit: int` (HHMM), `end_zeit: int` (HHMM). `UNIQUE(wochentag, stunde_nr)`. Wird von Task 2 (Sync) und Task 4 (Anzeige-Berechnung) importiert.

- [ ] **Step 1: Model schreiben**

```python
from __future__ import annotations

from sqlalchemy import Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class StundenrasterPeriode(Base, TimestampMixin):
    __tablename__ = "stundenraster_periode"
    __table_args__ = (
        UniqueConstraint("wochentag", "stunde_nr", name="uq_stundenraster_periode_wochentag_stunde_nr"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    wochentag: Mapped[int] = mapped_column(Integer)  # ISO-Wochentag: 1=Montag ... 7=Sonntag
    stunde_nr: Mapped[int] = mapped_column(Integer)
    start_zeit: Mapped[int] = mapped_column(Integer)  # HHMM, z.B. 730 fuer 7:30
    end_zeit: Mapped[int] = mapped_column(Integer)
```

Schreibe die Datei nach `backend/app/models/stundenraster_periode.py`.

- [ ] **Step 2: Model registrieren**

In `backend/app/models/__init__.py`, füge den Import alphabetisch nach `from app.models.schwellwert_stufe import SchwellwertStufe` ein:

```python
from app.models.stundenraster_periode import StundenrasterPeriode
```

Und in der `__all__`-Liste alphabetisch nach `"SchwellwertStufe",` ein:

```python
    "StundenrasterPeriode",
```

- [ ] **Step 3: Migrationsdatei generieren**

```bash
docker exec absenzdash-backend python -m alembic revision -m "add stundenraster_periode table"
```

Notiere den erzeugten Dateinamen/Revision-Hash unter `backend/alembic/versions/`.

- [ ] **Step 4: Migration befüllen**

Ersetze den generierten Datei-Inhalt (Docstring/Revision-ID/Create-Date aus Step 3 übernehmen, `down_revision` muss `'7a2c0d9d6057'` sein):

```python
"""add stundenraster_periode table

Revision ID: <HASH>
Revises: 7a2c0d9d6057
Create Date: <DATUM>

"""
from alembic import op
import sqlalchemy as sa


revision = '<HASH>'
down_revision = '7a2c0d9d6057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('stundenraster_periode',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('wochentag', sa.Integer(), nullable=False),
    sa.Column('stunde_nr', sa.Integer(), nullable=False),
    sa.Column('start_zeit', sa.Integer(), nullable=False),
    sa.Column('end_zeit', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wochentag', 'stunde_nr', name='uq_stundenraster_periode_wochentag_stunde_nr')
    )


def downgrade() -> None:
    op.drop_table('stundenraster_periode')
```

(`<HASH>`/`<DATUM>` sind die von Alembic in Step 3 generierten Werte, nicht frei erfinden.)

- [ ] **Step 5: Migration gegen den laufenden Dev-Stack testen**

```bash
docker exec absenzdash-backend python -m alembic upgrade head
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d stundenraster_periode"
```

Erwartet: Spalten `id`, `wochentag`, `stunde_nr`, `start_zeit`, `end_zeit`, `created_at`, `updated_at`, sowie der Unique-Index `uq_stundenraster_periode_wochentag_stunde_nr`.

- [ ] **Step 6: Downgrade/Upgrade-Zyklus verifizieren**

```bash
docker exec absenzdash-backend python -m alembic downgrade -1
docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "\d stundenraster_periode"
docker exec absenzdash-backend python -m alembic upgrade head
```

Erwartet: nach `downgrade -1` existiert die Tabelle nicht mehr (`psql` meldet "Did not find any relation"), nach erneutem `upgrade head` ist sie wieder da, kein Fehler in beiden Richtungen.

- [ ] **Step 7: Fehlschlagenden Test schreiben**

Schreibe `backend/tests/test_models_stundenraster_periode.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.stundenraster_periode import StundenrasterPeriode


@pytest.mark.asyncio
async def test_stundenraster_periode_roundtrip(db_session):
    periode = StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815)
    db_session.add(periode)
    await db_session.commit()

    assert periode.id is not None
    assert periode.wochentag == 1
    assert periode.start_zeit == 730
    assert periode.end_zeit == 815


@pytest.mark.asyncio
async def test_stundenraster_periode_unique_constraint_on_wochentag_stunde_nr(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=800, end_zeit=845))
    with pytest.raises(IntegrityError):
        await db_session.commit()
```

- [ ] **Step 8: Test ausführen**

```bash
docker exec absenzdash-backend python -m pytest tests/test_models_stundenraster_periode.py -v
```

Expected: beide Tests PASS (Tabelle wird von der Test-DB-Fixture per `Base.metadata.create_all` angelegt, keine Alembic-Migration in Tests nötig).

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/stundenraster_periode.py backend/app/models/__init__.py backend/alembic/versions/ backend/tests/test_models_stundenraster_periode.py
git commit -m "feat: add stundenraster_periode table and model"
```

---

## Task 2: WebUntis-Sync `sync_stundenraster`

**Files:**
- Create: `backend/app/services/webuntis_stundenraster_sync.py`
- Modify: `backend/app/services/sync_orchestrator.py`
- Test: `backend/tests/test_webuntis_stundenraster_sync.py`
- Modify: `backend/tests/test_sync_orchestrator.py`

**Interfaces:**
- Consumes: `app.models.stundenraster_periode.StundenrasterPeriode` (Task 1), `app.integrations.webuntis_client.WebUntisClient`/`WebUntisError`.
- Produces: `async def sync_stundenraster(client: WebUntisClient, db: AsyncSession) -> None`, aufgerufen aus `sync_orchestrator.run_sync_once`.

- [ ] **Step 1: Fehlschlagende Tests schreiben**

Schreibe `backend/tests/test_webuntis_stundenraster_sync.py`:

```python
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.integrations.webuntis_client import WebUntisError
from app.models.stundenraster_periode import StundenrasterPeriode
from app.services.webuntis_stundenraster_sync import sync_stundenraster


@pytest.mark.asyncio
async def test_sync_stundenraster_converts_webuntis_weekday_to_iso_and_sorts_stunde_nr(db_session):
    client = AsyncMock()
    client.call.return_value = [
        {
            "day": 2,  # WebUntis: 2 = Montag
            "timeUnits": [
                {"name": "2", "startTime": 815, "endTime": 900},
                {"name": "1", "startTime": 730, "endTime": 815},
            ],
        },
    ]

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode).order_by(StundenrasterPeriode.stunde_nr))
    perioden = result.scalars().all()
    assert [(p.wochentag, p.stunde_nr, p.start_zeit, p.end_zeit) for p in perioden] == [
        (1, 1, 730, 815),
        (1, 2, 815, 900),
    ]
    assert client.call.await_args.args == ("getTimegridUnits", {})


@pytest.mark.asyncio
async def test_sync_stundenraster_replaces_existing_periods(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=1, end_zeit=2))
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = [
        {"day": 2, "timeUnits": [{"name": "1", "startTime": 730, "endTime": 815}]},
    ]

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    perioden = result.scalars().all()
    assert len(perioden) == 1
    assert perioden[0].start_zeit == 730


@pytest.mark.asyncio
async def test_sync_stundenraster_keeps_old_data_when_call_fails(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    client = AsyncMock()
    client.call.side_effect = WebUntisError("boom")

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    perioden = result.scalars().all()
    assert len(perioden) == 1
    assert perioden[0].start_zeit == 730


@pytest.mark.asyncio
async def test_sync_stundenraster_keeps_old_data_when_response_is_empty(db_session):
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = None

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_sync_stundenraster_skips_unknown_weekday_value(db_session):
    client = AsyncMock()
    client.call.return_value = [
        {"day": 99, "timeUnits": [{"name": "1", "startTime": 730, "endTime": 815}]},
    ]

    await sync_stundenraster(client, db_session)

    result = await db_session.execute(select(StundenrasterPeriode))
    assert result.scalars().all() == []
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_webuntis_stundenraster_sync.py -v
```

Expected: FAIL mit `ModuleNotFoundError: No module named 'app.services.webuntis_stundenraster_sync'`.

- [ ] **Step 3: Sync-Service implementieren**

Schreibe `backend/app/services/webuntis_stundenraster_sync.py`:

```python
from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.stundenraster_periode import StundenrasterPeriode

logger = logging.getLogger(__name__)

# WebUntis' eigene Wochentag-Konvention (1=Sonntag...7=Samstag, siehe TECH-SPEC.md
# Abschnitt 1.4) auf ISO-Wochentag (1=Montag...7=Sonntag, wie date.isoweekday())
# umgerechnet - intern wird ausschliesslich ISO verwendet.
_WEBUNTIS_TAG_ZU_ISO = {1: 7, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}


async def sync_stundenraster(client: WebUntisClient, db: AsyncSession) -> None:
    """getTimegridUnits -> stundenraster_periode (TECH-SPEC.md Abschnitt 1.4).

    getTimegridUnits nimmt ausschliesslich einen leeren Parameter-Body entgegen (live
    verifiziert, jeder zusaetzliche Parameter fuehrt zu 'Method not found') und liefert
    den schulweiten Stundenraster. Schlaegt der Aufruf fehl (z.B. waehrend der
    Schuljahres-Uebergangsluecke, TECH-SPEC.md Abschnitt 1.3a/1.4) oder liefert eine
    leere/None-Antwort, bleibt die Tabelle unveraendert - kein kritischer Sync-Schritt,
    der Uhrzeit-Fallback in fehlzeit_berechnung.dauer_anzeige greift automatisch.
    """
    try:
        tage = await client.call("getTimegridUnits", {})
    except WebUntisError as exc:
        logger.warning("getTimegridUnits fehlgeschlagen, stundenraster_periode bleibt unveraendert: %s", exc)
        return

    if not tage:
        logger.warning("getTimegridUnits lieferte keine Daten, stundenraster_periode bleibt unveraendert")
        return

    await db.execute(delete(StundenrasterPeriode))

    for tag in tage:
        wochentag = _WEBUNTIS_TAG_ZU_ISO.get(tag.get("day"))
        if wochentag is None:
            logger.warning("getTimegridUnits: unbekannter Wochentag-Wert %s, uebersprungen", tag.get("day"))
            continue

        time_units = sorted(tag.get("timeUnits", []), key=lambda unit: unit["startTime"])
        for stunde_nr, unit in enumerate(time_units, start=1):
            db.add(
                StundenrasterPeriode(
                    wochentag=wochentag,
                    stunde_nr=stunde_nr,
                    start_zeit=unit["startTime"],
                    end_zeit=unit["endTime"],
                )
            )

    await db.commit()
```

- [ ] **Step 4: Tests ausführen, Erfolg verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_webuntis_stundenraster_sync.py -v
```

Expected: alle 5 Tests PASS.

- [ ] **Step 5: In Orchestrator verdrahten**

In `backend/app/services/sync_orchestrator.py`, füge den Import nach `from app.services.webuntis_klassenbuch_sync import sync_klassenbuch` ein (alphabetisch letzter Import in diesem Block):

```python
from app.services.webuntis_stundenraster_sync import sync_stundenraster
```

Füge in `run_sync_once` nach `await sync_kategorien(client, db)` (vor `await import_schueler(db)`) ein:

```python
        await sync_stundenraster(client, db)
```

Der Block sieht danach so aus:

```python
        await sync_abteilungen(client, db)
        await sync_klassen(client, db, schoolyear_id=aktuelles_schuljahr.id)
        await sync_bereiche(db)
        await sync_kategorien(client, db)
        await sync_stundenraster(client, db)
        await import_schueler(db)
```

- [ ] **Step 6: Orchestrator-Tests anpassen**

In `backend/tests/test_sync_orchestrator.py`, füge in der `_patch_phases`-Fixture nach `monkeypatch.setattr(sync_orchestrator, "sync_kategorien", AsyncMock())` ein:

```python
    monkeypatch.setattr(sync_orchestrator, "sync_stundenraster", AsyncMock())
```

In `test_run_full_sync_calls_phases_in_order`, füge nach der `sync_kategorien`-Zeile ein:

```python
    sync_orchestrator.sync_stundenraster.side_effect = lambda *a: calls.append("stundenraster")
```

Und aktualisiere die Assertion:

```python
    assert calls == [
        "abteilungen", "klassen", "bereiche", "kategorien", "stundenraster",
        "schueler", "fehlzeiten", "klassenbuch", "schwellwerte",
    ]
```

- [ ] **Step 7: Orchestrator-Tests ausführen**

```bash
docker exec absenzdash-backend python -m pytest tests/test_sync_orchestrator.py -v
```

Expected: alle Tests PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/webuntis_stundenraster_sync.py backend/app/services/sync_orchestrator.py backend/tests/test_webuntis_stundenraster_sync.py backend/tests/test_sync_orchestrator.py
git commit -m "feat: sync school-wide timegrid from WebUntis into stundenraster_periode"
```

---

## Task 3: Anzeige-Berechnung `dauer_anzeige`

**Files:**
- Modify: `backend/app/services/fehlzeit_berechnung.py`
- Test: `backend/tests/test_fehlzeit_berechnung.py`

**Interfaces:**
- Consumes: `app.models.fehlzeit.Fehlzeit`, `app.models.stundenraster_periode.StundenrasterPeriode` (Task 1).
- Produces: `def dauer_anzeige(fehlzeit: Fehlzeit, perioden_by_wochentag: dict[int, list[StundenrasterPeriode]]) -> str`, konsumiert von Task 4 (`student_query.load_student_detail`).

- [ ] **Step 1: Fehlschlagende Tests schreiben**

Ändere die Import-Zeilen am Anfang von `backend/tests/test_fehlzeit_berechnung.py`: füge `from app.models.stundenraster_periode import StundenrasterPeriode` hinzu (nach `from app.models.schueler import Schueler`) und ersetze

```python
from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden
```

durch

```python
from app.services.fehlzeit_berechnung import dauer_anzeige, fehlstunden_minuten_expr, minuten_zu_fehlstunden
```

Dann füge an das Ende der Datei an:

```python
def test_dauer_anzeige_gibt_ganztaegig_zurueck_fuer_typ_tag():
    fehlzeit = Fehlzeit(typ="tag", datum=date(2026, 2, 2), start_zeit=0, end_zeit=2359)
    assert dauer_anzeige(fehlzeit, {}) == "ganztägig"


def test_dauer_anzeige_matches_single_periode():
    # 2026-02-02 ist ein Montag (isoweekday() == 1)
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745)
    perioden_by_wochentag = {
        1: [StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815)],
    }
    assert dauer_anzeige(fehlzeit, perioden_by_wochentag) == "15 Minuten (Stunde 1)"


def test_dauer_anzeige_matches_multiple_aufeinanderfolgende_perioden():
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=900)
    perioden_by_wochentag = {
        1: [
            StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815),
            StundenrasterPeriode(wochentag=1, stunde_nr=2, start_zeit=820, end_zeit=905),
        ],
    }
    assert dauer_anzeige(fehlzeit, perioden_by_wochentag) == "90 Minuten (Stunde 1-2)"


def test_dauer_anzeige_falls_back_to_formatted_time_when_no_periode_matches():
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745)
    assert dauer_anzeige(fehlzeit, {}) == "15 Minuten (7:30–7:45)"


def test_dauer_anzeige_ignores_perioden_of_other_weekdays():
    # Fehlzeit ist Montag (isoweekday 1), Perioden nur fuer Dienstag (2) hinterlegt.
    fehlzeit = Fehlzeit(typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745)
    perioden_by_wochentag = {
        2: [StundenrasterPeriode(wochentag=2, stunde_nr=1, start_zeit=730, end_zeit=815)],
    }
    assert dauer_anzeige(fehlzeit, perioden_by_wochentag) == "15 Minuten (7:30–7:45)"
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_fehlzeit_berechnung.py -v
```

Expected: die 5 neuen Tests FAILEN mit `ImportError`/`NameError` (`dauer_anzeige` existiert noch nicht).

- [ ] **Step 3: `dauer_anzeige` implementieren**

Ersetze den kompletten Inhalt von `backend/app/services/fehlzeit_berechnung.py`:

```python
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import ColumnElement

from app.models.fehlzeit import Fehlzeit
from app.models.stundenraster_periode import StundenrasterPeriode

STUNDENLAENGE_MINUTEN = 45


def _hhmm_zu_minuten(spalte: ColumnElement) -> ColumnElement:
    """Wandelt eine WebUntis-Uhrzeitspalte im HHMM-Format (z.B. 815 fuer 08:15) in Minuten
    seit Mitternacht um. Eine reine Integer-Subtraktion (end_zeit - start_zeit) waere bei
    Perioden, die eine Stundengrenze ueberschreiten (z.B. 730 -> 815), falsch (85 statt 45
    Minuten) - siehe TECH-SPEC.md Abschnitt 1.2 fuer das HHMM-Format-Beispiel."""
    return (spalte // 100) * 60 + (spalte % 100)


def _hhmm_zu_minuten_wert(value: int) -> int:
    """Wie _hhmm_zu_minuten, aber fuer einen einzelnen Python-Integer statt eine SQL-Spalte
    (fuer die Anzeige-Berechnung ausserhalb einer Query, siehe dauer_anzeige)."""
    return (value // 100) * 60 + (value % 100)


def _hhmm_formatiert(value: int) -> str:
    """Formatiert einen WebUntis-HHMM-Integer (z.B. 730) als Uhrzeit-String ('7:30')."""
    return f"{value // 100}:{value % 100:02d}"


def fehlstunden_minuten_expr() -> ColumnElement:
    """SQL-Ausdruck: Dauer in Minuten je Fehlzeit-Zeile. Nur fuer typ='stunde' sinnvoll -
    bei typ='tag' sind start_zeit/end_zeit feste Platzhalter (0/2359), keine echte Zeitspanne."""
    return _hhmm_zu_minuten(Fehlzeit.end_zeit) - _hhmm_zu_minuten(Fehlzeit.start_zeit)


def minuten_zu_fehlstunden(minuten: int | None) -> Decimal:
    """Rundet eine Minuten-Summe auf Fehlstunden (Dezimalzahl, Basis 45 Minuten/Stunde)."""
    if not minuten:
        return Decimal("0.00")
    return (Decimal(minuten) / Decimal(STUNDENLAENGE_MINUTEN)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dauer_anzeige(fehlzeit: Fehlzeit, perioden_by_wochentag: dict[int, list[StundenrasterPeriode]]) -> str:
    """Anzeige-Label fuer eine Fehlzeit (Schueler-Detail + PDF-Export, siehe
    docs/superpowers/specs/2026-08-08-fehlzeit-stunden-anzeige-design.md):

    - typ='tag' -> 'ganztägig'.
    - typ='stunde' mit Rastertreffer -> '{minuten} Minuten (Stunde {n})' bzw. bei mehreren
      aufeinanderfolgenden Perioden '{minuten} Minuten (Stunde {min}-{max})'.
    - typ='stunde' ohne Rastertreffer (Luecke im Raster, kein Raster synchronisiert) ->
      Fallback auf die formatierte Uhrzeitspanne, '{minuten} Minuten ({start}–{end})'.

    perioden_by_wochentag ist nach ISO-Wochentag (date.isoweekday(), 1=Montag) gruppiert -
    siehe student_query.load_stundenraster_by_wochentag.
    """
    if fehlzeit.typ == "tag":
        return "ganztägig"

    minuten = _hhmm_zu_minuten_wert(fehlzeit.end_zeit) - _hhmm_zu_minuten_wert(fehlzeit.start_zeit)
    perioden = perioden_by_wochentag.get(fehlzeit.datum.isoweekday(), [])
    treffer = [p for p in perioden if p.start_zeit < fehlzeit.end_zeit and p.end_zeit > fehlzeit.start_zeit]

    if treffer:
        stunden_nrs = sorted(p.stunde_nr for p in treffer)
        if stunden_nrs[0] == stunden_nrs[-1]:
            stunde_text = f"Stunde {stunden_nrs[0]}"
        else:
            stunde_text = f"Stunde {stunden_nrs[0]}-{stunden_nrs[-1]}"
        return f"{minuten} Minuten ({stunde_text})"

    return f"{minuten} Minuten ({_hhmm_formatiert(fehlzeit.start_zeit)}–{_hhmm_formatiert(fehlzeit.end_zeit)})"
```

- [ ] **Step 4: Tests ausführen, Erfolg verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_fehlzeit_berechnung.py -v
```

Expected: alle Tests (bestehende + 5 neue) PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/fehlzeit_berechnung.py backend/tests/test_fehlzeit_berechnung.py
git commit -m "feat: compute period-based duration label for non-full-day absences"
```

---

## Task 4: Backend-Verdrahtung — `student_query` + API-Schema

**Files:**
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/schemas/students.py`
- Test: `backend/tests/test_student_query.py`

**Interfaces:**
- Consumes: `fehlzeit_berechnung.dauer_anzeige` (Task 3), `StundenrasterPeriode` (Task 1).
- Produces: `student_query.load_stundenraster_by_wochentag(db) -> dict[int, list[StundenrasterPeriode]]`; jedes `Fehlzeit`-Objekt in `load_student_detail(...)["fehlzeiten"]` trägt danach ein transientes (nicht persistiertes) Attribut `.dauer_anzeige: str`; `FehlzeitOut.dauer_anzeige: str` im API-Schema.

- [ ] **Step 1: Fehlschlagenden Test schreiben**

Füge in `backend/tests/test_student_query.py` einen neuen Test hinzu (am Ende der Datei; `date` und `Fehlzeit` sind dort bereits importiert):

```python
@pytest.mark.asyncio
async def test_load_student_detail_computes_dauer_anzeige_for_fehlzeiten(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 2, 2), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745),
        ]
    )
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)

    by_typ = {f.typ: f for f in detail["fehlzeiten"]}
    assert by_typ["tag"].dauer_anzeige == "ganztägig"
    assert by_typ["stunde"].dauer_anzeige == "15 Minuten (7:30–7:45)"


@pytest.mark.asyncio
async def test_load_student_detail_uses_stundenraster_when_available(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 2, 2), start_zeit=730, end_zeit=745))
    db_session.add(StundenrasterPeriode(wochentag=1, stunde_nr=1, start_zeit=730, end_zeit=815))
    await db_session.commit()

    detail = await student_query.load_student_detail(db_session, schueler.id)

    assert detail["fehlzeiten"][0].dauer_anzeige == "15 Minuten (Stunde 1)"
```

Ergänze den Import am Dateianfang von `backend/tests/test_student_query.py`:

```python
from app.models.stundenraster_periode import StundenrasterPeriode
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_student_query.py::test_load_student_detail_computes_dauer_anzeige_for_fehlzeiten tests/test_student_query.py::test_load_student_detail_uses_stundenraster_when_available -v
```

Expected: FAIL mit `AttributeError: 'Fehlzeit' object has no attribute 'dauer_anzeige'`.

- [ ] **Step 3: `load_stundenraster_by_wochentag` ergänzen**

In `backend/app/services/student_query.py`, ergänze die Imports (nach `from app.models.schwellwert_regel import SchwellwertRegel`):

```python
from app.models.stundenraster_periode import StundenrasterPeriode
from app.services.fehlzeit_berechnung import dauer_anzeige, fehlstunden_minuten_expr, minuten_zu_fehlstunden
```

(ersetzt die bisherige Zeile `from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden`).

Füge nach `load_classreg_category_map` (vor `async def load_all_excuse_statuses`) eine neue Funktion ein:

```python
async def load_stundenraster_by_wochentag(db: AsyncSession) -> dict[int, list[StundenrasterPeriode]]:
    """Alle Stundenraster-Perioden, gruppiert nach ISO-Wochentag (1=Montag...7=Sonntag) -
    fuer fehlzeit_berechnung.dauer_anzeige, siehe load_student_detail."""
    result = await db.execute(select(StundenrasterPeriode))
    perioden_by_wochentag: dict[int, list[StundenrasterPeriode]] = {}
    for periode in result.scalars().all():
        perioden_by_wochentag.setdefault(periode.wochentag, []).append(periode)
    return perioden_by_wochentag
```

- [ ] **Step 4: `load_student_detail` erweitern**

In `backend/app/services/student_query.py`, finde die Zeile

```python
    fehlzeiten = (await db.execute(fehlzeiten_query.order_by(Fehlzeit.datum.desc()))).scalars().all()
```

und füge direkt danach ein:

```python
    perioden_by_wochentag = await load_stundenraster_by_wochentag(db)
    for f in fehlzeiten:
        f.dauer_anzeige = dauer_anzeige(f, perioden_by_wochentag)
```

- [ ] **Step 5: `FehlzeitOut`-Schema erweitern**

In `backend/app/schemas/students.py`, füge in `FehlzeitOut` (nach `grund_text: str | None`) ein:

```python
    dauer_anzeige: str
```

Die Klasse sieht danach so aus:

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
    dauer_anzeige: str
```

- [ ] **Step 6: Tests ausführen, Erfolg verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_student_query.py -v
```

Expected: alle Tests (bestehende + 2 neue) PASS.

- [ ] **Step 7: API-Test ausführen (Regressionscheck für `GET /students/{id}`)**

```bash
docker exec absenzdash-backend python -m pytest tests/test_api_students.py -v
```

Expected: alle bestehenden Tests weiterhin PASS (kein Test prüft bisher fehlende `start_zeit`/`end_zeit`-Felder im JSON-Body direkt, `FehlzeitOut` validiert das neue Pflichtfeld transparent über das in Step 4 gesetzte Attribut).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/student_query.py backend/app/schemas/students.py backend/tests/test_student_query.py
git commit -m "feat: expose dauer_anzeige on FehlzeitOut via student_query"
```

---

## Task 5: Frontend — Schüler-Detail-Tabelle

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/StudentDetail/FehlzeitenTable.tsx`
- Modify: `frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx`

**Interfaces:**
- Consumes: `dauer_anzeige` Feld aus dem `GET /students/{id}`-Response (Task 4).
- Produces: `Fehlzeit`-TS-Interface mit `dauer_anzeige: string`.

- [ ] **Step 1: TS-Interface erweitern**

In `frontend/src/api/types.ts`, füge in `Fehlzeit` (nach `end_zeit: number;`) ein:

```typescript
  dauer_anzeige: string;
```

Das Interface sieht danach so aus:

```typescript
export interface Fehlzeit {
  id: number;
  typ: string;
  datum: string;
  start_zeit: number;
  end_zeit: number;
  dauer_anzeige: string;
  fach: string | null;
  excuse_status_id: number | null;
  grund_text: string | null;
}
```

- [ ] **Step 2: Fehlschlagenden Test schreiben**

Ersetze den kompletten Inhalt von `frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FehlzeitenTable } from "./FehlzeitenTable";

describe("FehlzeitenTable", () => {
  it("resolves excuse_status_id to its long_name", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "stunde",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
            dauer_anzeige: "15 Minuten (Stunde 1)",
            fach: "Mathe",
            excuse_status_id: 5,
            grund_text: null,
          },
        ]}
        excuseStatuses={[{ id: 5, name: "E", long_name: "Entschuldigt" }]}
      />,
    );

    expect(screen.getByText("Entschuldigt")).toBeInTheDocument();
    expect(screen.getByText("Mathe")).toBeInTheDocument();
    expect(screen.getByText("15 Minuten (Stunde 1)")).toBeInTheDocument();
  });

  it("shows the backend-provided dauer_anzeige label as-is", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "tag",
            datum: "2026-02-01",
            start_zeit: 0,
            end_zeit: 2359,
            dauer_anzeige: "ganztägig",
            fach: null,
            excuse_status_id: null,
            grund_text: null,
          },
        ]}
        excuseStatuses={[]}
      />,
    );

    expect(screen.getByText("ganztägig")).toBeInTheDocument();
    expect(screen.queryByText("0–2359")).not.toBeInTheDocument();
  });

  it("shows a dash when excuse_status_id is null", () => {
    render(
      <FehlzeitenTable
        fehlzeiten={[
          {
            id: 1,
            typ: "stunde",
            datum: "2026-02-01",
            start_zeit: 1,
            end_zeit: 1,
            dauer_anzeige: "0 Minuten (Stunde 1)",
            fach: null,
            excuse_status_id: null,
            grund_text: null,
          },
        ]}
        excuseStatuses={[]}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 3: Test ausführen, Fehlschlag verifizieren**

```bash
cd frontend && npx vitest run src/components/StudentDetail/FehlzeitenTable.test.tsx
```

Expected: FAIL — `getByText("15 Minuten (Stunde 1)")` findet nichts, da die Komponente noch `${start_zeit}–${end_zeit}` rendert.

- [ ] **Step 4: Komponente anpassen**

Ersetze den kompletten Inhalt von `frontend/src/components/StudentDetail/FehlzeitenTable.tsx`:

```tsx
import type { ExcuseStatusCatalogEntry, Fehlzeit } from "../../api/types";
import styles from "./StudentDetail.module.css";

interface FehlzeitenTableProps {
  fehlzeiten: Fehlzeit[];
  excuseStatuses: ExcuseStatusCatalogEntry[];
}

export function FehlzeitenTable({ fehlzeiten, excuseStatuses }: FehlzeitenTableProps) {
  const statusMap = new Map(excuseStatuses.map((status) => [status.id, status.long_name ?? status.name]));

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Datum</th>
          <th>Typ</th>
          <th>Dauer</th>
          <th>Fach</th>
          <th>Entschuldigungsstatus</th>
          <th>Grund</th>
        </tr>
      </thead>
      <tbody>
        {fehlzeiten.map((fehlzeit) => (
          <tr key={fehlzeit.id}>
            <td>{fehlzeit.datum}</td>
            <td>{fehlzeit.typ}</td>
            <td>{fehlzeit.dauer_anzeige}</td>
            <td>{fehlzeit.fach ?? "—"}</td>
            <td>{fehlzeit.excuse_status_id !== null ? statusMap.get(fehlzeit.excuse_status_id) ?? "—" : "—"}</td>
            <td>{fehlzeit.grund_text ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 5: Tests ausführen, Erfolg verifizieren**

```bash
cd frontend && npx vitest run src/components/StudentDetail/FehlzeitenTable.test.tsx && npx tsc --noEmit
```

Expected: alle 3 Tests PASS, `tsc --noEmit` ohne Fehler.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/components/StudentDetail/FehlzeitenTable.tsx frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx
git commit -m "feat: show dauer_anzeige instead of raw time range in FehlzeitenTable"
```

---

## Task 6: PDF-Export

**Files:**
- Modify: `backend/app/services/export_service.py`
- Modify: `backend/app/templates/export_pdf.html`
- Test: `backend/tests/test_export_service.py`

**Interfaces:**
- Consumes: `.dauer_anzeige`-Attribut auf `Fehlzeit`-Objekten aus `detail["fehlzeiten"]` (Task 4, wird von `student_query.load_student_detail` gesetzt — `export_service.render_student_export_html` ruft dieselbe Funktion auf).

- [ ] **Step 1: Fehlschlagenden Test schreiben**

Füge in `backend/tests/test_export_service.py` einen neuen Test hinzu (am Ende der Datei):

```python
@pytest.mark.asyncio
async def test_render_student_export_html_shows_dauer_anzeige_for_fehlzeiten(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=datetime.date(2026, 2, 2), start_zeit=730, end_zeit=745)
    )
    await db_session.commit()

    html = await export_service.render_student_export_html(db_session, schueler, klasse, sections={"fehlzeiten"})

    assert "15 Minuten (7:30–7:45)" in html
```

- [ ] **Step 2: Test ausführen, Fehlschlag verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_export_service.py::test_render_student_export_html_shows_dauer_anzeige_for_fehlzeiten -v
```

Expected: FAIL — `"15 Minuten (7:30–7:45)"` ist nicht im gerenderten HTML enthalten (keine Zeit-Spalte, kein `dauer_anzeige` im Template-Kontext).

- [ ] **Step 3: `export_service.py` erweitern**

In `backend/app/services/export_service.py`, finde den Block:

```python
        for f in detail["fehlzeiten"]:
            status = excuse_status_map.get(f.excuse_status_id) if f.excuse_status_id is not None else None
            fehlzeiten.append(
                {
                    "datum": f.datum.strftime("%d.%m.%Y"),
                    "typ": f.typ,
                    "fach": f.fach,
                    "excuse_status_name": (status.long_name or status.name) if status else None,
                    "grund_text": f.grund_text,
                }
            )
```

und ersetze ihn durch:

```python
        for f in detail["fehlzeiten"]:
            status = excuse_status_map.get(f.excuse_status_id) if f.excuse_status_id is not None else None
            fehlzeiten.append(
                {
                    "datum": f.datum.strftime("%d.%m.%Y"),
                    "typ": f.typ,
                    "dauer_anzeige": f.dauer_anzeige,
                    "fach": f.fach,
                    "excuse_status_name": (status.long_name or status.name) if status else None,
                    "grund_text": f.grund_text,
                }
            )
```

- [ ] **Step 4: PDF-Template erweitern**

In `backend/app/templates/export_pdf.html`, ersetze die Fehlzeiten-Tabelle (Zeilen im `{% if "fehlzeiten" in sections %}`-Block):

```html
  {% if "fehlzeiten" in sections %}
  <h2>Fehlzeiten</h2>
  <table>
    <thead>
      <tr><th>Datum</th><th>Typ</th><th>Dauer</th><th>Fach</th><th>Entschuldigungsstatus</th><th>Grund</th></tr>
    </thead>
    <tbody>
      {% for f in fehlzeiten %}
      <tr>
        <td>{{ f.datum }}</td>
        <td>{{ f.typ }}</td>
        <td>{{ f.dauer_anzeige }}</td>
        <td>{{ f.fach or "" }}</td>
        <td>{{ f.excuse_status_name or "" }}</td>
        <td>{{ f.grund_text or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
```

- [ ] **Step 5: Tests ausführen, Erfolg verifizieren**

```bash
docker exec absenzdash-backend python -m pytest tests/test_export_service.py -v
```

Expected: alle Tests (bestehende + 1 neuer) PASS.

- [ ] **Step 6: Vollen Backend-Testlauf verifizieren**

```bash
docker exec absenzdash-backend python -m pytest -v
```

Expected: alle Tests im Projekt PASS (keine Regression in anderen Modulen, die `Fehlzeit`/`FehlzeitOut` konsumieren).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/export_service.py backend/app/templates/export_pdf.html backend/tests/test_export_service.py
git commit -m "feat: show dauer_anzeige column in PDF absence export"
```

---

## Nach Abschluss

- `ROADMAP.md` aktualisieren (Projekt-Konvention, `CLAUDE.md`): Feature als abgeschlossen eintragen, Hinweis ergänzen, dass "Stunde N" erst nach Konfiguration eines Stundenrasters in WebUntis (Stammdaten → Stundenraster) erscheint — bis dahin zeigt das Feature durchgängig den Uhrzeit-Fallback (siehe TECH-SPEC.md Abschnitt 1.4).
- Manuelle Verifikation im laufenden Dev-Stack: `GET /students/{id}` liefert `dauer_anzeige` je Fehlzeit; Schüler-Detail-Seite zeigt die neue "Dauer"-Spalte; PDF-Export (`GET /students/{id}/export.pdf`) zeigt dieselbe Spalte.
