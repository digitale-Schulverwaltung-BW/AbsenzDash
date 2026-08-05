# Bundle A — Schülerliste-Feintuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Schülerliste's single "Zählerstand"-Badge-Spalte durch sortierbare Fehltage-/Fehlstunden-/Einträge-Spalten, bei denen Fehlstunden minutengenau als Dezimalzahl berechnet werden und Fehltage/Fehlstunden einen Entschuldigt/Unentschuldigt-Split mitliefern; die Eskalationsstufe wird als kleiner farbcodierter Mini-Badge separat angezeigt.

**Architecture:** Ein neues Berechnungs-Modul (`fehlzeit_berechnung.py`) kapselt die WebUntis-HHMM-zu-Minuten-Konvertierung und die Minuten→Fehlstunden-Rundung; es wird von der Eskalations-Engine, dem Dashboard und der Schülerlisten-Query gemeinsam genutzt. `schwellwert_stufe.schwellenwert` und `schueler_zaehlerstand.aktueller_stand` wechseln von `Integer` auf `Numeric(6,2)`, damit Fehlstunden-Schwellwerte/Zählerstände Dezimalwerte tragen können. Die Schülerlisten-Query bekommt einen effektiven Zeitraum (aktuelles Schuljahr im Normalmodus, gewähltes Schuljahr im Historie-Modus) und liefert Fehltage/Fehlstunden/Einträge jetzt in beiden Modi einheitlich, inklusive Entschuldigt-Split und DB-seitiger Sortierung. Das Frontend vereinheitlicht die Tabellen-Spalten entsprechend und nutzt die bereits vorhandene `valueToColor`-Farbskala für die Rohzahlen-Spalten.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (async, PostgreSQL/asyncpg), Alembic, pytest/pytest-asyncio; React, TypeScript, TanStack Query, Vitest/Testing Library.

## Global Constraints

- Stundenlänge für die Fehlstunden-Umrechnung ist fix `45` Minuten (keine konfigurierbare Stundenlänge pro Schule/Klasse).
- Fehlstunden-Dezimalwerte werden immer auf 2 Nachkommastellen gerundet (`ROUND_HALF_UP`).
- `typ='tag'`-Zeilen (Fehltage) bleiben ein reiner Integer-Count, keine Minutenberechnung.
- Zeilen ohne `excuse_status_id` zählen im Entschuldigt/Unentschuldigt-Split als **unentschuldigt** (sicherer Default, konsistent mit der bestehenden Eskalations-Engine).
- Commit nach jedem Task (siehe Steps).

---

## Task 1: Zentrales Fehlzeit-Berechnungs-Modul

**Files:**
- Create: `backend/app/services/fehlzeit_berechnung.py`
- Test: `backend/tests/test_fehlzeit_berechnung.py`

**Interfaces:**
- Produces: `STUNDENLAENGE_MINUTEN: int = 45`; `fehlstunden_minuten_expr() -> ColumnElement` (SQL-Ausdruck: Dauer einer einzelnen `Fehlzeit`-Zeile in Minuten, HHMM-korrekt); `minuten_zu_fehlstunden(minuten: int | None) -> Decimal` (rundet eine Minuten-Summe auf 2 Nachkommastellen Fehlstunden, `None`/`0` → `Decimal("0.00")`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_fehlzeit_berechnung.py
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.fehlzeit import Fehlzeit
from app.models.schueler import Schueler
from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden


def test_minuten_zu_fehlstunden_rounds_to_two_decimals():
    assert minuten_zu_fehlstunden(65) == Decimal("1.44")  # 65/45 = 1.4444...


def test_minuten_zu_fehlstunden_handles_none_and_zero():
    assert minuten_zu_fehlstunden(None) == Decimal("0.00")
    assert minuten_zu_fehlstunden(0) == Decimal("0.00")


def test_minuten_zu_fehlstunden_exact_hour():
    assert minuten_zu_fehlstunden(90) == Decimal("2.00")


@pytest.mark.asyncio
async def test_fehlstunden_minuten_expr_is_hhmm_aware_across_hour_boundary(db_session):
    """730 -> 815 im WebUntis-HHMM-Format ist 07:30-08:15, also 45 Minuten - eine
    naive Integer-Subtraktion (815 - 730 = 85) waere falsch."""
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 1, 10), start_zeit=730, end_zeit=815)
    )
    await db_session.commit()

    result = await db_session.execute(
        select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id)
    )
    assert result.scalar_one() == 45


@pytest.mark.asyncio
async def test_fehlstunden_minuten_expr_sums_multiple_rows_within_same_hour(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 1, 10), start_zeit=900, end_zeit=920),
            Fehlzeit(schueler_id=schueler.id, typ="stunde", datum=date(2026, 1, 11), start_zeit=1000, end_zeit=1010),
        ]
    )
    await db_session.commit()

    result = await db_session.execute(
        select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id)
    )
    assert result.scalar_one() == 30  # 20 + 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_fehlzeit_berechnung.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.fehlzeit_berechnung'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/fehlzeit_berechnung.py
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import ColumnElement

from app.models.fehlzeit import Fehlzeit

STUNDENLAENGE_MINUTEN = 45


def _hhmm_zu_minuten(spalte: ColumnElement) -> ColumnElement:
    """Wandelt eine WebUntis-Uhrzeitspalte im HHMM-Format (z.B. 815 fuer 08:15) in Minuten
    seit Mitternacht um. Eine reine Integer-Subtraktion (end_zeit - start_zeit) waere bei
    Perioden, die eine Stundengrenze ueberschreiten (z.B. 730 -> 815), falsch (85 statt 45
    Minuten) - siehe TECH-SPEC.md Abschnitt 1.2 fuer das HHMM-Format-Beispiel."""
    return (spalte / 100) * 60 + (spalte % 100)


def fehlstunden_minuten_expr() -> ColumnElement:
    """SQL-Ausdruck: Dauer in Minuten je Fehlzeit-Zeile. Nur fuer typ='stunde' sinnvoll -
    bei typ='tag' sind start_zeit/end_zeit feste Platzhalter (0/2359), keine echte Zeitspanne."""
    return _hhmm_zu_minuten(Fehlzeit.end_zeit) - _hhmm_zu_minuten(Fehlzeit.start_zeit)


def minuten_zu_fehlstunden(minuten: int | None) -> Decimal:
    """Rundet eine Minuten-Summe auf Fehlstunden (Dezimalzahl, Basis 45 Minuten/Stunde)."""
    if not minuten:
        return Decimal("0.00")
    return (Decimal(minuten) / Decimal(STUNDENLAENGE_MINUTEN)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_fehlzeit_berechnung.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/fehlzeit_berechnung.py backend/tests/test_fehlzeit_berechnung.py
git commit -m "feat: add centralized Fehlstunden-Minuten calculation module"
```

---

## Task 2: Schwellenwert/Zählerstand auf Numeric(6,2) umstellen

**Files:**
- Modify: `backend/app/models/schwellwert_stufe.py`
- Modify: `backend/app/models/schueler_zaehlerstand.py`
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/schemas/students.py`
- Create: `backend/alembic/versions/<neue_revision>_schwellenwert_aktueller_stand_numeric.py`

**Interfaces:**
- Consumes: nichts aus Task 1.
- Produces: `SchwellwertStufe.schwellenwert: Decimal`, `SchuelerZaehlerstand.aktueller_stand: Decimal` — von Task 3 (Eskalations-Engine) und Task 6 (Sortierung) genutzt. `SchwellwertStufeIn.schwellenwert: float`, `SchwellwertStufeOut.schwellenwert: float`, `ZaehlerstandOut.aktueller_stand: float`.

- [ ] **Step 1: Update the models**

```python
# backend/app/models/schwellwert_stufe.py
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
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
    schwellenwert: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    fehlzeiten_filter: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "nur_unentschuldigt" | "alle"
    empfaenger_rollen: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
```

```python
# backend/app/models/schueler_zaehlerstand.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SchuelerZaehlerstand(Base, TimestampMixin):
    __tablename__ = "schueler_zaehlerstand"
    __table_args__ = (UniqueConstraint("schueler_id", "typ", name="uq_schueler_zaehlerstand_schueler_typ"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schueler_id: Mapped[int] = mapped_column(ForeignKey("schueler.id", ondelete="CASCADE"))
    typ: Mapped[str] = mapped_column(String(20))  # "fehlzeiten" | "klassenbuch"
    regel_id: Mapped[int | None] = mapped_column(ForeignKey("schwellwert_regel.id", ondelete="SET NULL"), nullable=True)
    aktueller_stand: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    erreichte_stufe_nr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    letzter_reset_am: Mapped[date | None] = mapped_column(Date, nullable=True)
```

- [ ] **Step 2: Update the schemas**

In `backend/app/schemas/admin.py`, change both occurrences of `schwellenwert: int` to `schwellenwert: float` (in `SchwellwertStufeIn` and `SchwellwertStufeOut`).

In `backend/app/schemas/students.py`, change `ZaehlerstandOut`:

```python
class ZaehlerstandOut(BaseModel):
    aktueller_stand: float
    erreichte_stufe_nr: int | None
```

- [ ] **Step 3: Generate and write the migration**

Run: `cd backend && alembic revision -m "schwellenwert_aktueller_stand_numeric"`

This prints the new revision id and creates `backend/alembic/versions/<id>_schwellenwert_aktueller_stand_numeric.py` with `down_revision = 'b8e759ca46a8'` pre-filled (current head). Replace its body with:

```python
"""schwellenwert_aktueller_stand_numeric

Revision ID: <id>
Revises: b8e759ca46a8
Create Date: <auto-filled>

"""
from alembic import op
import sqlalchemy as sa


revision = '<id>'
down_revision = 'b8e759ca46a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "schwellwert_stufe",
        "schwellenwert",
        existing_type=sa.INTEGER(),
        type_=sa.Numeric(6, 2),
        postgresql_using="schwellenwert::numeric(6,2)",
    )
    op.alter_column(
        "schueler_zaehlerstand",
        "aktueller_stand",
        existing_type=sa.INTEGER(),
        type_=sa.Numeric(6, 2),
        postgresql_using="aktueller_stand::numeric(6,2)",
    )


def downgrade() -> None:
    op.alter_column(
        "schueler_zaehlerstand",
        "aktueller_stand",
        existing_type=sa.Numeric(6, 2),
        type_=sa.INTEGER(),
        postgresql_using="round(aktueller_stand)::integer",
    )
    op.alter_column(
        "schwellwert_stufe",
        "schwellenwert",
        existing_type=sa.Numeric(6, 2),
        type_=sa.INTEGER(),
        postgresql_using="round(schwellenwert)::integer",
    )
```

(Keep the `<id>` placeholders you got from the `alembic revision` command output — do not invent one.)

- [ ] **Step 4: Apply the migration against the local dev DB**

Run: `cd backend && docker compose up -d postgres && alembic upgrade head`
Expected: no errors; `alembic current` shows the new revision as head.

If no local Postgres is reachable (e.g. `docker compose` unavailable in this environment), skip this step but say so explicitly when reporting task completion — do not claim it was verified.

- [ ] **Step 5: Run the full backend test suite to confirm nothing else broke**

Run: `cd backend && pytest -q`
Expected: PASS (tests use `Base.metadata.create_all` against a fresh schema per `conftest.py`, independent of Alembic, so this validates the model change itself)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schwellwert_stufe.py backend/app/models/schueler_zaehlerstand.py backend/app/schemas/admin.py backend/app/schemas/students.py backend/alembic/versions/
git commit -m "feat: change schwellenwert/aktueller_stand to Numeric(6,2) for decimal Fehlstunden support"
```

---

## Task 3: Eskalations-Engine auf Minuten-basierte Fehlstunden umstellen

**Files:**
- Modify: `backend/app/services/eskalations_pruefung.py`
- Modify: `backend/tests/test_eskalations_pruefung.py`

**Interfaces:**
- Consumes: `fehlstunden_minuten_expr()`, `minuten_zu_fehlstunden()` from Task 1 (`app.services.fehlzeit_berechnung`).
- Produces: `_zaehle_fuer_stufe(...) -> int | Decimal` (unveränderter Name/Aufrufer, aber neuer Rückgabetyp bei `einheit='fehlstunden'`); `_ermittle_erreichte_stufe(...) -> tuple[int | None, int | Decimal]`.

- [ ] **Step 1: Update the failing test's expectation first**

In `backend/tests/test_eskalations_pruefung.py`, add the import at the top:

```python
from decimal import Decimal
```

Then change the assertion in `test_pruefe_schwellwerte_fehlstunden_only_counts_stunde_typ` (currently `assert zaehlerstand.aktueller_stand == 2`) to:

```python
    assert zaehlerstand.aktueller_stand == Decimal("2.00")  # 2 x 45 Min. = 90 Min. / 45 = 2.00 Fehlstunden
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_eskalations_pruefung.py::test_pruefe_schwellwerte_fehlstunden_only_counts_stunde_typ -v`
Expected: FAIL — `aktueller_stand` is still `2` (int, from the old `func.count()` logic), not `Decimal("2.00")`.

- [ ] **Step 3: Update `_zaehle_fuer_stufe` and `_ermittle_erreichte_stufe`**

In `backend/app/services/eskalations_pruefung.py`, add the import:

```python
from decimal import Decimal

from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden
```

Replace the `_zaehle_fuer_stufe` function body:

```python
async def _zaehle_fuer_stufe(
    db: AsyncSession, regel: SchwellwertRegel, stufe: SchwellwertStufe, schueler_id: int, fenster_start: date
) -> int | Decimal:
    if regel.typ == "fehlzeiten":
        ist_fehlstunden = stufe.einheit == "fehlstunden"
        if ist_fehlstunden:
            query = select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id == schueler_id,
                Fehlzeit.datum >= fenster_start,
                Fehlzeit.invalid.is_(False),
                Fehlzeit.typ == "stunde",
            )
        else:
            query = select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id == schueler_id,
                Fehlzeit.datum >= fenster_start,
                Fehlzeit.invalid.is_(False),
                Fehlzeit.typ == "tag",
            )
        if stufe.fehlzeiten_filter == "nur_unentschuldigt":
            query = query.outerjoin(ExcuseStatus, Fehlzeit.excuse_status_id == ExcuseStatus.id).where(
                or_(Fehlzeit.excuse_status_id.is_(None), ExcuseStatus.zaehlt_als_entschuldigt.is_(False))
            )
        result = await db.execute(query)
        rohwert = result.scalar_one()
        return minuten_zu_fehlstunden(rohwert) if ist_fehlstunden else rohwert

    result = await db.execute(
        select(func.count()).select_from(KlassenbuchEintrag).where(
            KlassenbuchEintrag.schueler_id == schueler_id, KlassenbuchEintrag.datum >= fenster_start
        )
    )
    return result.scalar_one()
```

Update the `_ermittle_erreichte_stufe` return type annotation from `-> tuple[int | None, int]` to `-> tuple[int | None, int | Decimal]`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_eskalations_pruefung.py::test_pruefe_schwellwerte_fehlstunden_only_counts_stunde_typ -v`
Expected: PASS

- [ ] **Step 5: Run the full eskalations_pruefung test file to confirm no regressions**

Run: `cd backend && pytest tests/test_eskalations_pruefung.py -v`
Expected: PASS (all other tests use `einheit="fehltage"` by default via `_make_fehlzeiten_regel`/`_make_zweistufige_fehlzeiten_regel`, so they exercise the unchanged `func.count()` branch)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eskalations_pruefung.py backend/tests/test_eskalations_pruefung.py
git commit -m "feat: compute fehlstunden threshold counting from actual minutes, not row count"
```

---

## Task 4: Dashboard-Durchschnitt (`avg_fehlstunden`) auf Minuten umstellen

**Files:**
- Modify: `backend/app/services/dashboard_query.py`
- Modify: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- Consumes: `fehlstunden_minuten_expr()`, `minuten_zu_fehlstunden()` from Task 1.
- Produces: keine neuen Interfaces — `StatsOwn.avg_fehlstunden: float` bleibt unverändert im Typ, nur die Berechnung ändert sich.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_dashboard_query.py` (nach `test_get_dashboard_stats_for_single_klasse_averages_over_active_students_only`):

```python
@pytest.mark.asyncio
async def test_get_dashboard_stats_computes_avg_fehlstunden_from_minutes_not_row_count(db_session):
    klasse = Klasse(webuntis_id=1, name="AME56")
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = datetime.date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            # 07:30-08:15 (Stundengrenze!) = 45 Min., 09:00-09:20 = 20 Min. -> 65 Min. gesamt
            Fehlzeit(
                schueler_id=schueler.id, typ="stunde",
                datum=schuljahr_start + datetime.timedelta(days=1), start_zeit=730, end_zeit=815,
            ),
            Fehlzeit(
                schueler_id=schueler.id, typ="stunde",
                datum=schuljahr_start + datetime.timedelta(days=2), start_zeit=900, end_zeit=920,
            ),
        ]
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.own.avg_fehlstunden == 1.44  # 65 Min. / 45 = 1.4444... gerundet
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_dashboard_query.py::test_get_dashboard_stats_computes_avg_fehlstunden_from_minutes_not_row_count -v`
Expected: FAIL — old logic counts 2 rows, `avg_fehlstunden` would be `2.0`, not `1.44`.

- [ ] **Step 3: Update `_aggregate` in `dashboard_query.py`**

Add the import:

```python
from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden
```

Replace the `fehlstunden` computation block:

```python
    fehlstunden_minuten = (
        await db.execute(
            select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "stunde",
                Fehlzeit.invalid.is_(False),
                *([Fehlzeit.datum >= schuljahr_start] if datumsfilter else []),
            )
        )
    ).scalar_one()
    fehlstunden = minuten_zu_fehlstunden(fehlstunden_minuten)
```

And update the return statement's `avg_fehlstunden` line:

```python
        avg_fehlstunden=round(float(fehlstunden) / anzahl_schueler, 2),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_dashboard_query.py::test_get_dashboard_stats_computes_avg_fehlstunden_from_minutes_not_row_count -v`
Expected: PASS

- [ ] **Step 5: Run the full dashboard test file to confirm no regressions**

Run: `cd backend && pytest tests/test_dashboard_query.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "feat: compute dashboard avg_fehlstunden from minutes instead of row count"
```

---

## Task 5: Fehltage/Fehlstunden-Split (entschuldigt/unentschuldigt) in `student_query`

**Files:**
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/schemas/students.py`
- Modify: `backend/tests/test_student_query.py`

**Interfaces:**
- Consumes: `fehlstunden_minuten_expr()`, `minuten_zu_fehlstunden()` from Task 1.
- Produces: `load_schueler_rohzahlen(db, schueler_ids, von: date | None, bis: date | None) -> dict[int, dict[str, Any]]` mit Rückgabeform `{schueler_id: {"fehltage": {"gesamt": int, "entschuldigt": int, "unentschuldigt": int}, "fehlstunden": {"gesamt": Decimal, "entschuldigt": Decimal, "unentschuldigt": Decimal}, "klassenbuch_anzahl": int}}` (Signatur-Änderung: `von`/`bis` jetzt optional, Rückgabewert jetzt Split statt einfachem Integer). `FehlzeitSplitOut` (neues Pydantic-Schema) — von Task 7 (Route) konsumiert. `_fehlzeit_datum_filter(von, bis) -> list`, `_klassenbuch_datum_filter(von, bis) -> list` (interne Helper, auch von Task 6 genutzt).

- [ ] **Step 1: Write the failing test**

Replace `test_load_schueler_rohzahlen_counts_within_range` in `backend/tests/test_student_query.py` with:

```python
@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_counts_within_range(db_session):
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    schueler_b = Schueler(externe_id="ext-b", vorname="B", nachname="B")
    kategorie = ClassregCategory(name="stören", long_name="Störung des Unterrichts", group_name="Störung")
    db_session.add_all([schueler_a, schueler_b, kategorie])
    await db_session.flush()

    db_session.add_all(
        [
            # schueler_a: 2 Fehltage, 1 Fehlstunde (730-815 = 45 Min. -> 1.00 Fehlstunde) within range,
            # 1 Fehltag outside range
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2025, 11, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_a.id, typ="stunde", datum=date(2025, 10, 5), start_zeit=730, end_zeit=815),
            Fehlzeit(schueler_id=schueler_a.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            KlassenbuchEintrag(
                schueler_id=schueler_a.id, webuntis_id=1, kategorie_id=kategorie.id, datum=date(2025, 10, 2)
            ),
            # schueler_b: nothing in range
            Fehlzeit(schueler_id=schueler_b.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(
        db_session, [schueler_a.id, schueler_b.id], date(2025, 9, 15), date(2026, 7, 29)
    )

    assert result[schueler_a.id]["fehltage"] == {"gesamt": 2, "entschuldigt": 0, "unentschuldigt": 2}
    assert result[schueler_a.id]["fehlstunden"] == {
        "gesamt": Decimal("1.00"), "entschuldigt": Decimal("0.00"), "unentschuldigt": Decimal("1.00"),
    }
    assert result[schueler_a.id]["klassenbuch_anzahl"] == 1
    assert result[schueler_b.id]["fehltage"] == {"gesamt": 0, "entschuldigt": 0, "unentschuldigt": 0}
    assert result[schueler_b.id]["fehlstunden"] == {
        "gesamt": Decimal("0.00"), "entschuldigt": Decimal("0.00"), "unentschuldigt": Decimal("0.00"),
    }
    assert result[schueler_b.id]["klassenbuch_anzahl"] == 0


@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_splits_by_excuse_status(db_session):
    schueler = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, entschuldigt, nicht_entschuldigt])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(
                schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359,
                excuse_status_id=entschuldigt.id,
            ),
            Fehlzeit(
                schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 2), start_zeit=0, end_zeit=2359,
                excuse_status_id=nicht_entschuldigt.id,
            ),
            # kein excuse_status_id gesetzt -> zaehlt als unentschuldigt
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 3), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(db_session, [schueler.id], date(2025, 9, 15), date(2026, 7, 29))

    assert result[schueler.id]["fehltage"] == {"gesamt": 3, "entschuldigt": 1, "unentschuldigt": 2}


@pytest.mark.asyncio
async def test_load_schueler_rohzahlen_without_date_range_counts_all_time(db_session):
    schueler = Schueler(externe_id="ext-a", vorname="A", nachname="A")
    db_session.add(schueler)
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2020, 1, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2026, 1, 1), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    result = await student_query.load_schueler_rohzahlen(db_session, [schueler.id], None, None)

    assert result[schueler.id]["fehltage"]["gesamt"] == 2
```

Add `from decimal import Decimal` to the top of `backend/tests/test_student_query.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_student_query.py -k rohzahlen -v`
Expected: FAIL — current implementation returns `{"fehltage": int, "fehlstunden": int, "klassenbuch_anzahl": int}`, not the split shape, and does not accept `None`/`None` for `von`/`bis`.

- [ ] **Step 3: Rewrite `load_schueler_rohzahlen`**

In `backend/app/services/student_query.py`, add imports:

```python
from decimal import Decimal

from app.services.fehlzeit_berechnung import fehlstunden_minuten_expr, minuten_zu_fehlstunden
```

Add two module-level helpers (place them right above `load_schueler_rohzahlen`):

```python
def _fehlzeit_datum_filter(von: date | None, bis: date | None) -> list[Any]:
    filters: list[Any] = []
    if von is not None:
        filters.append(Fehlzeit.datum >= von)
    if bis is not None:
        filters.append(Fehlzeit.datum <= bis)
    return filters


def _klassenbuch_datum_filter(von: date | None, bis: date | None) -> list[Any]:
    filters: list[Any] = []
    if von is not None:
        filters.append(KlassenbuchEintrag.datum >= von)
    if bis is not None:
        filters.append(KlassenbuchEintrag.datum <= bis)
    return filters


def _leerer_fehltage_split() -> dict[str, int]:
    return {"gesamt": 0, "entschuldigt": 0, "unentschuldigt": 0}


def _leerer_fehlstunden_split() -> dict[str, Decimal]:
    return {"gesamt": Decimal("0.00"), "entschuldigt": Decimal("0.00"), "unentschuldigt": Decimal("0.00")}
```

Replace `load_schueler_rohzahlen`:

```python
async def load_schueler_rohzahlen(
    db: AsyncSession, schueler_ids: list[int], von: date | None, bis: date | None
) -> dict[int, dict[str, Any]]:
    """Fehltage/Fehlstunden (je als {gesamt, entschuldigt, unentschuldigt}) plus
    klassenbuch_anzahl fuer den angegebenen Zeitraum. von=None/bis=None heisst
    unbegrenzt (all-time) - genutzt sowohl im Historie-Modus (vergangenes Schuljahr)
    als auch im Normalmodus (aktuelles Schuljahr, oder all-time falls noch keines
    konfiguriert ist). Entschuldigt/unentschuldigt-Split: Zeilen ohne excuse_status_id
    zaehlen als unentschuldigt (sicherer Default, konsistent mit der Eskalations-Engine,
    siehe eskalations_pruefung.py)."""
    ergebnis: dict[int, dict[str, Any]] = {
        sid: {
            "fehltage": _leerer_fehltage_split(),
            "fehlstunden": _leerer_fehlstunden_split(),
            "klassenbuch_anzahl": 0,
        }
        for sid in schueler_ids
    }
    if not schueler_ids:
        return ergebnis

    fehlzeit_result = await db.execute(
        select(
            Fehlzeit.schueler_id,
            Fehlzeit.typ,
            func.coalesce(ExcuseStatus.zaehlt_als_entschuldigt, False).label("entschuldigt"),
            func.count().label("anzahl"),
            func.sum(fehlstunden_minuten_expr()).label("minuten"),
        )
        .outerjoin(ExcuseStatus, Fehlzeit.excuse_status_id == ExcuseStatus.id)
        .where(
            Fehlzeit.schueler_id.in_(schueler_ids),
            Fehlzeit.invalid.is_(False),
            *_fehlzeit_datum_filter(von, bis),
        )
        .group_by(Fehlzeit.schueler_id, Fehlzeit.typ, func.coalesce(ExcuseStatus.zaehlt_als_entschuldigt, False))
    )
    for schueler_id, typ, entschuldigt, anzahl, minuten in fehlzeit_result.all():
        split_key = "entschuldigt" if entschuldigt else "unentschuldigt"
        if typ == "tag":
            ergebnis[schueler_id]["fehltage"]["gesamt"] += anzahl
            ergebnis[schueler_id]["fehltage"][split_key] += anzahl
        elif typ == "stunde":
            stunden = minuten_zu_fehlstunden(minuten)
            ergebnis[schueler_id]["fehlstunden"]["gesamt"] += stunden
            ergebnis[schueler_id]["fehlstunden"][split_key] += stunden

    klassenbuch_result = await db.execute(
        select(KlassenbuchEintrag.schueler_id, func.count())
        .where(KlassenbuchEintrag.schueler_id.in_(schueler_ids), *_klassenbuch_datum_filter(von, bis))
        .group_by(KlassenbuchEintrag.schueler_id)
    )
    for schueler_id, anzahl in klassenbuch_result.all():
        ergebnis[schueler_id]["klassenbuch_anzahl"] = anzahl

    return ergebnis
```

- [ ] **Step 4: Add the `FehlzeitSplitOut` schema and update `StudentOverviewOut`**

In `backend/app/schemas/students.py`, add (near `ZaehlerstandOut`):

```python
class FehlzeitSplitOut(BaseModel):
    gesamt: float
    entschuldigt: float
    unentschuldigt: float
```

Change `StudentOverviewOut`:

```python
class StudentOverviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vorname: str
    nachname: str
    klasse: KlasseOut | None
    zaehlerstand: dict[str, ZaehlerstandOut] | None = None
    letzte_benachrichtigung: BenachrichtigungOut | None = None
    ohne_massnahme_seit_benachrichtigung: bool | None = None
    fehltage: FehlzeitSplitOut | None = None
    fehlstunden: FehlzeitSplitOut | None = None
    klassenbuch_anzahl: int | None = None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_student_query.py -k rohzahlen -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full student_query test file to confirm no regressions**

Run: `cd backend && pytest tests/test_student_query.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/student_query.py backend/app/schemas/students.py backend/tests/test_student_query.py
git commit -m "feat: add entschuldigt/unentschuldigt split to Fehltage/Fehlstunden rohzahlen"
```

---

## Task 6: Sortierbare Spalten in `list_students`

**Files:**
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/tests/test_student_query.py`

**Interfaces:**
- Consumes: `fehlstunden_minuten_expr()` from Task 1; `_fehlzeit_datum_filter`/`_klassenbuch_datum_filter` from Task 5.
- Produces: `list_students(db, scope, ..., von: date | None = None, bis: date | None = None, sort_by: str | None = None, sort_dir: str = "asc", limit=50, offset=0) -> tuple[list[Schueler], int]` (Signatur-Erweiterung, rückwärtskompatibel da alle neuen Parameter Defaults haben). `SORTIERBARE_FELDER: tuple[str, ...] = ("nachname", "klasse", "fehltage", "fehlstunden", "klassenbuch_anzahl")` — von Task 7 (Route) für die Query-Param-Validierung referenziert.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_student_query.py`:

```python
@pytest.mark.asyncio
async def test_list_students_sorts_by_fehlstunden_descending(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler_wenig = Schueler(externe_id="ext-wenig", vorname="Wenig", nachname="Fehlstunden", klasse_id=klasse.id, aktiv=True)
    schueler_viel = Schueler(externe_id="ext-viel", vorname="Viel", nachname="Fehlstunden", klasse_id=klasse.id, aktiv=True)
    db_session.add_all([schueler_wenig, schueler_viel])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler_wenig.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=800, end_zeit=815),
            Fehlzeit(schueler_id=schueler_viel.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=730, end_zeit=815),
            Fehlzeit(schueler_id=schueler_viel.id, typ="stunde", datum=date(2025, 10, 2), start_zeit=730, end_zeit=815),
        ]
    )
    await db_session.commit()

    items, _ = await student_query.list_students(
        db_session, scope=None, von=date(2025, 9, 1), bis=date(2026, 7, 30), sort_by="fehlstunden", sort_dir="desc"
    )

    assert [s.id for s in items] == [schueler_viel.id, schueler_wenig.id]


@pytest.mark.asyncio
async def test_list_students_sorts_by_fehltage_ascending(db_session):
    schueler_null = Schueler(externe_id="ext-0", vorname="Null", nachname="A", aktiv=True)
    schueler_zwei = Schueler(externe_id="ext-2", vorname="Zwei", nachname="B", aktiv=True)
    db_session.add_all([schueler_null, schueler_zwei])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler_zwei.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359),
            Fehlzeit(schueler_id=schueler_zwei.id, typ="tag", datum=date(2025, 10, 2), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()

    items, _ = await student_query.list_students(
        db_session, scope=None, von=date(2025, 9, 1), bis=date(2026, 7, 30), sort_by="fehltage", sort_dir="asc"
    )

    assert [s.id for s in items] == [schueler_null.id, schueler_zwei.id]


@pytest.mark.asyncio
async def test_list_students_default_sort_is_unchanged_name_order(db_session):
    schueler_z = Schueler(externe_id="ext-z", vorname="A", nachname="Zeta", aktiv=True)
    schueler_a = Schueler(externe_id="ext-a", vorname="A", nachname="Anton", aktiv=True)
    db_session.add_all([schueler_z, schueler_a])
    await db_session.commit()

    items, _ = await student_query.list_students(db_session, scope=None)

    assert [s.id for s in items] == [schueler_a.id, schueler_z.id]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_student_query.py -k "sorts_by or default_sort" -v`
Expected: FAIL — `list_students()` does not accept `von`/`bis`/`sort_by`/`sort_dir` yet (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Extend `list_students`**

In `backend/app/services/student_query.py`, update the import line to add `asc, desc`:

```python
from sqlalchemy import asc, desc, func, or_, select
```

Add the constant near the top (after `ZAEHLERSTAND_TYPEN`):

```python
SORTIERBARE_FELDER = ("nachname", "klasse", "fehltage", "fehlstunden", "klassenbuch_anzahl")
```

Replace the `list_students` function:

```python
async def list_students(
    db: AsyncSession,
    scope: set[int] | None,
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: str | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    nur_aktive: bool = True,
    von: date | None = None,
    bis: date | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Schueler], int]:
    """Liefert die fuer den Scope sichtbaren Schueler (gefiltert, sortiert, paginiert) sowie
    die Gesamtzahl (nach Filtern, vor Pagination). von/bis grenzen den Zeitraum fuer die
    Fehltage/Fehlstunden/Einträge-Sortierung ein (None/None = unbegrenzt)."""
    if scope is not None and not scope:
        return [], 0
    if sort_by is not None and sort_by not in SORTIERBARE_FELDER:
        raise ValueError(f"Unbekanntes sort_by: {sort_by}")

    conditions = []
    if nur_aktive:
        conditions.append(Schueler.aktiv.is_(True))
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

    richtung = desc if sort_dir == "desc" else asc
    if sort_by is None or sort_by == "nachname":
        query = query.order_by(Schueler.nachname, Schueler.vorname, Schueler.id)
    elif sort_by == "klasse":
        query = query.outerjoin(Klasse, Klasse.id == Schueler.klasse_id).order_by(
            richtung(Klasse.name), Schueler.nachname, Schueler.id
        )
    elif sort_by == "klassenbuch_anzahl":
        subq = (
            select(KlassenbuchEintrag.schueler_id, func.count().label("anzahl"))
            .where(*_klassenbuch_datum_filter(von, bis))
            .group_by(KlassenbuchEintrag.schueler_id)
            .subquery()
        )
        query = query.outerjoin(subq, subq.c.schueler_id == Schueler.id).order_by(
            richtung(func.coalesce(subq.c.anzahl, 0)), Schueler.nachname, Schueler.id
        )
    elif sort_by == "fehltage":
        subq = (
            select(Fehlzeit.schueler_id, func.count().label("anzahl"))
            .where(Fehlzeit.typ == "tag", Fehlzeit.invalid.is_(False), *_fehlzeit_datum_filter(von, bis))
            .group_by(Fehlzeit.schueler_id)
            .subquery()
        )
        query = query.outerjoin(subq, subq.c.schueler_id == Schueler.id).order_by(
            richtung(func.coalesce(subq.c.anzahl, 0)), Schueler.nachname, Schueler.id
        )
    else:  # sort_by == "fehlstunden"
        subq = (
            select(Fehlzeit.schueler_id, func.sum(fehlstunden_minuten_expr()).label("minuten"))
            .where(Fehlzeit.typ == "stunde", Fehlzeit.invalid.is_(False), *_fehlzeit_datum_filter(von, bis))
            .group_by(Fehlzeit.schueler_id)
            .subquery()
        )
        query = query.outerjoin(subq, subq.c.schueler_id == Schueler.id).order_by(
            richtung(func.coalesce(subq.c.minuten, 0)), Schueler.nachname, Schueler.id
        )

    result = await db.execute(query.offset(offset).limit(limit))
    return list(result.scalars().all()), total
```

Note: this replaces the previous unconditional `.order_by(Schueler.nachname, Schueler.vorname, Schueler.id).offset(offset).limit(limit)` call — the offset/limit now apply to the query built above instead.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_student_query.py -k "sorts_by or default_sort" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full student_query test file to confirm no regressions**

Run: `cd backend && pytest tests/test_student_query.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/student_query.py backend/tests/test_student_query.py
git commit -m "feat: add sortable columns (name, klasse, fehltage, fehlstunden, eintraege) to list_students"
```

---

## Task 7: `GET /students` — Rohzahlen in beiden Modi, Sortier-Query-Params

**Files:**
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- Consumes: `student_query.list_students(..., von, bis, sort_by, sort_dir)` (Task 6), `student_query.load_schueler_rohzahlen(db, ids, von, bis)` (Task 5), `FehlzeitSplitOut` (Task 5), `student_query.SORTIERBARE_FELDER` (Task 6).
- Produces: `GET /students` liefert `fehltage`/`fehlstunden`/`klassenbuch_anzahl` jetzt **immer** (nicht mehr nur im Historie-Modus), zusätzlich neue optionale Query-Params `sort_by`, `sort_dir`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_students.py`:

```python
@pytest.mark.asyncio
async def test_get_students_normal_mode_also_returns_fehltage_fehlstunden_split(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    schuljahr = Schuljahr(id=30, name="2025/2026", start_datum=date(2025, 9, 8), end_datum=date(2026, 7, 30))
    db_session.add_all([klasse, schuljahr])
    await db_session.flush()
    einstellung = Einstellung(aktuelles_schuljahr_id=schuljahr.id)
    db_session.add(einstellung)
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/students", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["id"] == schueler.id)
    assert item["fehltage"] == {"gesamt": 1.0, "entschuldigt": 0.0, "unentschuldigt": 1.0}
    assert item["fehlstunden"] == {"gesamt": 0.0, "entschuldigt": 0.0, "unentschuldigt": 0.0}
    assert item["zaehlerstand"] is not None  # normaler Modus behaelt Zaehlerstand/Benachrichtigung


@pytest.mark.asyncio
async def test_get_students_sort_by_fehlstunden_desc(db_session):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse.id])

    schueler_wenig = Schueler(externe_id="ext-wenig", vorname="Wenig", nachname="A", klasse_id=klasse.id, aktiv=True)
    schueler_viel = Schueler(externe_id="ext-viel", vorname="Viel", nachname="B", klasse_id=klasse.id, aktiv=True)
    db_session.add_all([schueler_wenig, schueler_viel])
    await db_session.flush()
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler_wenig.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=800, end_zeit=815),
            Fehlzeit(schueler_id=schueler_viel.id, typ="stunde", datum=date(2025, 10, 1), start_zeit=730, end_zeit=815),
            Fehlzeit(schueler_id=schueler_viel.id, typ="stunde", datum=date(2025, 10, 2), start_zeit=730, end_zeit=815),
        ]
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/students?sort_by=fehlstunden&sort_dir=desc", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids.index(schueler_viel.id) < ids.index(schueler_wenig.id)
```

`_seed_klassenlehrkraft`, `date`, and `Schuljahr` are already imported/defined in this file (reused by `test_get_students_history_mode_returns_rohzahlen_and_includes_inactive`). `Einstellung` is **not** yet imported — add it:

```python
from app.models.einstellung import Einstellung
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_api_students.py -k "fehltage_fehlstunden_split or sort_by_fehlstunden" -v`
Expected: FAIL — `item["fehltage"]` is currently `None` in normal mode, and `sort_by`/`sort_dir` are unknown query params (ignored, no effect on order).

- [ ] **Step 3: Update the `get_students` route**

In `backend/app/api/routes/students.py`, `Einstellung` and `Schuljahr` are already imported (used by `_resolve_schuljahr_zeitraum`) — no new model imports needed. Add `FehlzeitSplitOut` to the existing `from app.schemas.students import (...)` block.

Add a new helper function right after `_resolve_schuljahr_zeitraum`:

```python
async def _aktuelles_schuljahr_zeitraum(db: AsyncSession) -> tuple[date | None, date | None]:
    """Zeitraum des aktuellen Schuljahres fuer die Fehltage/Fehlstunden/Eintraege-Rohzahlen
    im Normalmodus (kein schuljahr_id-Query-Param). None/None (unbegrenzt) falls noch kein
    aktuelles Schuljahr konfiguriert ist (z.B. vor dem ersten WebUntis-Sync)."""
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is None or einstellung.aktuelles_schuljahr_id is None:
        return None, None
    schuljahr = await db.get(Schuljahr, einstellung.aktuelles_schuljahr_id)
    if schuljahr is None:
        return None, None
    return schuljahr.start_datum, schuljahr.end_datum
```

Replace the `get_students` function:

```python
@router.get("")
async def get_students(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    klasse_id: int | None = None,
    bereich_id: int | None = None,
    typ: Literal["fehlzeiten", "klassenbuch"] | None = None,
    min_stufe: int | None = None,
    nur_auffaellige: bool = False,
    nur_aktive: bool = True,
    schuljahr_id: int | None = None,
    sort_by: Literal["nachname", "klasse", "fehltage", "fehlstunden", "klassenbuch_anzahl"] | None = None,
    sort_dir: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> StudentListOut:
    scope = await resolve_scope(db, nutzer)
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None
    effektiv_von, effektiv_bis = (von, bis) if ist_historie else await _aktuelles_schuljahr_zeitraum(db)

    schueler_list, total = await student_query.list_students(
        db,
        scope=scope,
        klasse_id=klasse_id,
        bereich_id=bereich_id,
        typ=None if ist_historie else typ,
        min_stufe=None if ist_historie else min_stufe,
        nur_auffaellige=False if ist_historie else nur_auffaellige,
        nur_aktive=False if ist_historie else nur_aktive,
        von=effektiv_von,
        bis=effektiv_bis,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    schueler_ids = [schueler.id for schueler in schueler_list]
    klasse_ids = [schueler.klasse_id for schueler in schueler_list if schueler.klasse_id is not None]
    klasse_map = await student_query.load_klasse_map(db, klasse_ids)
    rohzahlen = await student_query.load_schueler_rohzahlen(db, schueler_ids, effektiv_von, effektiv_bis)

    if ist_historie:
        items = [
            StudentOverviewOut(
                id=schueler.id,
                vorname=schueler.vorname,
                nachname=schueler.nachname,
                klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
                fehltage=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehltage"]),
                fehlstunden=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehlstunden"]),
                klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
            )
            for schueler in schueler_list
        ]
        return StudentListOut(items=items, total=total, limit=limit, offset=offset)

    extras = await student_query.load_overview_extras(db, schueler_ids)
    regel_ids = [
        extras[schueler.id]["letzte_benachrichtigung"].regel_id
        for schueler in schueler_list
        if extras[schueler.id]["letzte_benachrichtigung"] is not None
        and extras[schueler.id]["letzte_benachrichtigung"].regel_id is not None
    ]
    regel_typ_map = await student_query.load_regel_typ_map(db, regel_ids)

    items = [
        StudentOverviewOut(
            id=schueler.id,
            vorname=schueler.vorname,
            nachname=schueler.nachname,
            klasse=klasse_map.get(schueler.klasse_id) if schueler.klasse_id is not None else None,
            zaehlerstand=extras[schueler.id]["zaehlerstand"],
            letzte_benachrichtigung=_benachrichtigung_out(extras[schueler.id]["letzte_benachrichtigung"], regel_typ_map),
            ohne_massnahme_seit_benachrichtigung=extras[schueler.id]["ohne_massnahme_seit_benachrichtigung"],
            fehltage=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehltage"]),
            fehlstunden=FehlzeitSplitOut(**rohzahlen[schueler.id]["fehlstunden"]),
            klassenbuch_anzahl=rohzahlen[schueler.id]["klassenbuch_anzahl"],
        )
        for schueler in schueler_list
    ]
    return StudentListOut(items=items, total=total, limit=limit, offset=offset)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_api_students.py -k "fehltage_fehlstunden_split or sort_by_fehlstunden" -v`
Expected: PASS

- [ ] **Step 5: Update the existing history-mode test for the new split shape**

In `backend/tests/test_api_students.py`, in `test_get_students_history_mode_returns_rohzahlen_and_includes_inactive`, change:

```python
    assert inaktiv_item["fehltage"] == 1
```

to:

```python
    assert inaktiv_item["fehltage"] == {"gesamt": 1.0, "entschuldigt": 0.0, "unentschuldigt": 1.0}
```

- [ ] **Step 6: Run the full students API test file to confirm no regressions**

Run: `cd backend && pytest tests/test_api_students.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/students.py backend/tests/test_api_students.py
git commit -m "feat: always return fehltage/fehlstunden split from GET /students, add sort_by/sort_dir"
```

---

## Task 8: Frontend-Typen und `useStudents`-Hook

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/hooks/useStudents.ts`
- Modify: `frontend/src/api/hooks/useStudents.test.tsx` (existing file — extend, do not replace)

**Interfaces:**
- Produces: `FehlzeitSplit` (TS-Interface), `StudentOverview.fehltage: FehlzeitSplit | null`, `StudentOverview.fehlstunden: FehlzeitSplit | null`, `StudentListParams.sortBy`/`sortDir` (neue optionale Felder) — von Task 10 (`StudentList.tsx`) konsumiert.

`frontend/src/api/hooks/useStudents.test.tsx` already exists with three tests using the `vi.spyOn(client, "apiGet")` pattern and exact query-string assertions (e.g. `"students?bereich_id=3&min_stufe=2&nur_auffaellige=true&offset=50"`). Add two new tests to it in the same style rather than replacing the file.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/api/hooks/useStudents.test.tsx`, inside the existing `describe("useStudents", () => { ... })` block, after the `"includes schuljahr_id in the query string when set"` test:

```typescript
  it("includes sort_by and sort_dir in the query string when sortBy is set", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () =>
        useStudents({
          bereichId: null,
          klasseId: null,
          minStufe: null,
          nurAuffaellige: false,
          offset: 0,
          schuljahrId: null,
          sortBy: "fehlstunden",
          sortDir: "desc",
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?sort_by=fehlstunden&sort_dir=desc&offset=0");
  });

  it("omits sort_by/sort_dir from the query string when sortBy is null", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const { result } = renderHook(
      () =>
        useStudents({
          bereichId: null,
          klasseId: null,
          minStufe: null,
          nurAuffaellige: false,
          offset: 0,
          schuljahrId: null,
          sortBy: null,
          sortDir: "asc",
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("students?offset=0");
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/hooks/useStudents.test.tsx`
Expected: FAIL — TypeScript error, `StudentListParams` has no `sortBy`/`sortDir` properties yet.

- [ ] **Step 3: Update `types.ts`**

In `frontend/src/api/types.ts`, add after `export interface Zaehlerstand { ... }`:

```typescript
export interface FehlzeitSplit {
  gesamt: number;
  entschuldigt: number;
  unentschuldigt: number;
}
```

Change `StudentOverview`:

```typescript
export interface StudentOverview {
  id: number;
  vorname: string;
  nachname: string;
  klasse: Klasse | null;
  zaehlerstand: Record<string, Zaehlerstand> | null;
  letzte_benachrichtigung: Benachrichtigung | null;
  ohne_massnahme_seit_benachrichtigung: boolean | null;
  fehltage: FehlzeitSplit | null;
  fehlstunden: FehlzeitSplit | null;
  klassenbuch_anzahl: number | null;
}
```

- [ ] **Step 4: Update `useStudents.ts`**

```typescript
// frontend/src/api/hooks/useStudents.ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { StudentList } from "../types";

export const STUDENT_LIST_LIMIT = 50;

export type StudentSortField = "nachname" | "klasse" | "fehltage" | "fehlstunden" | "klassenbuch_anzahl";
export type StudentSortDir = "asc" | "desc";

export interface StudentListParams {
  bereichId: number | null;
  klasseId: number | null;
  minStufe: number | null;
  nurAuffaellige: boolean;
  offset: number;
  schuljahrId: number | null;
  sortBy?: StudentSortField | null;
  sortDir?: StudentSortDir;
}

function buildQuery(params: StudentListParams): string {
  const query = new URLSearchParams();
  if (params.bereichId !== null) query.set("bereich_id", String(params.bereichId));
  if (params.klasseId !== null) query.set("klasse_id", String(params.klasseId));
  if (params.minStufe !== null) query.set("min_stufe", String(params.minStufe));
  if (params.nurAuffaellige) query.set("nur_auffaellige", "true");
  if (params.schuljahrId !== null) query.set("schuljahr_id", String(params.schuljahrId));
  if (params.sortBy) {
    query.set("sort_by", params.sortBy);
    query.set("sort_dir", params.sortDir ?? "asc");
  }
  query.set("offset", String(params.offset));
  return query.toString();
}

export function useStudents(params: StudentListParams) {
  return useQuery({
    queryKey: ["students", params],
    queryFn: () => apiGet<StudentList>(`students?${buildQuery(params)}`),
  });
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/hooks/useStudents.test.tsx`
Expected: PASS (5 tests: the existing 3 plus the 2 new ones)

- [ ] **Step 6: Run the full frontend test suite and typecheck to confirm no regressions**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: FAIL at this point — `StudentList.tsx` and `StudentList.test.tsx` still use the old `fehltage: number | null` shape (fixed in Task 10). Confirm the *only* failures are in those two files before proceeding.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/hooks/useStudents.ts frontend/src/api/hooks/useStudents.test.tsx
git commit -m "feat: add FehlzeitSplit type and sortBy/sortDir params to useStudents"
```

---

## Task 9: `EskalationsBadge`-Komponente

**Files:**
- Create: `frontend/src/components/EskalationsBadge/EskalationsBadge.tsx`
- Create: `frontend/src/components/EskalationsBadge/EskalationsBadge.module.css`
- Create: `frontend/src/components/EskalationsBadge/EskalationsBadge.test.tsx`

**Interfaces:**
- Consumes: `valueToColor` from `frontend/src/utils/colorScale.ts` (bereits vorhanden, Bundle E).
- Produces: `<EskalationsBadge stufeNr={number | null} maxStufeNr={number} />` — von Task 10 (`StudentList.tsx`) genutzt.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/components/EskalationsBadge/EskalationsBadge.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EskalationsBadge } from "./EskalationsBadge";

describe("EskalationsBadge", () => {
  it("renders the stufe number", () => {
    render(<EskalationsBadge stufeNr={2} maxStufeNr={3} />);
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders a dash for null (keine Stufe erreicht)", () => {
    render(<EskalationsBadge stufeNr={null} maxStufeNr={3} />);
    expect(screen.getByText("–")).toBeInTheDocument();
  });

  it("colors stufe 0/null green and the max stufe dark red", () => {
    const { container: gruen } = render(<EskalationsBadge stufeNr={null} maxStufeNr={3} />);
    const { container: rot } = render(<EskalationsBadge stufeNr={3} maxStufeNr={3} />);

    const gruenStyle = (gruen.firstChild as HTMLElement).style.backgroundColor;
    const rotStyle = (rot.firstChild as HTMLElement).style.backgroundColor;

    expect(gruenStyle).not.toBe(rotStyle);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/EskalationsBadge/EskalationsBadge.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the implementation**

```typescript
// frontend/src/components/EskalationsBadge/EskalationsBadge.tsx
import { valueToColor } from "../../utils/colorScale";
import styles from "./EskalationsBadge.module.css";

interface EskalationsBadgeProps {
  stufeNr: number | null;
  maxStufeNr: number;
}

export function EskalationsBadge({ stufeNr, maxStufeNr }: EskalationsBadgeProps) {
  const wert = stufeNr ?? 0;
  const farbe = valueToColor(wert, 0, Math.max(maxStufeNr, 1));
  return (
    <span className={styles.badge} style={{ backgroundColor: farbe }}>
      {stufeNr ?? "–"}
    </span>
  );
}
```

```css
/* frontend/src/components/EskalationsBadge/EskalationsBadge.module.css */
.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  color: white;
  font-size: 0.75rem;
  font-weight: 700;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/EskalationsBadge/EskalationsBadge.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EskalationsBadge/
git commit -m "feat: add EskalationsBadge component (color-coded mini stufe indicator)"
```

---

## Task 10: `StudentList.tsx` — vereinheitlichte, sortierbare, farbcodierte Spalten

**Files:**
- Modify: `frontend/src/pages/StudentList/StudentList.tsx`
- Modify: `frontend/src/pages/StudentList/StudentList.module.css`
- Modify: `frontend/src/pages/StudentList/StudentList.test.tsx`

**Interfaces:**
- Consumes: `useStudents` mit `sortBy`/`sortDir` (Task 8), `FehlzeitSplit` (Task 8), `EskalationsBadge` (Task 9), `valueToColor` (bestehend).

- [ ] **Step 1: Rewrite the test file's fixtures and expectations**

Replace `frontend/src/pages/StudentList/StudentList.test.tsx` in full:

```typescript
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { useStudents } from "../../api/hooks/useStudents";
import { StudentList } from "./StudentList";

vi.mock("../../api/hooks/useStudents");

const mockUseStudents = vi.mocked(useStudents);

function renderList(initialEntries: string[] = ["/schueler"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <StudentList />
    </MemoryRouter>,
  );
}

const BASE_STUDENT = {
  id: 1,
  vorname: "Max",
  nachname: "Muster",
  klasse: { id: 1, name: "10a" },
  zaehlerstand: {
    fehlzeiten: { aktueller_stand: 4, erreichte_stufe_nr: 1 },
    klassenbuch: { aktueller_stand: 0, erreichte_stufe_nr: null },
  },
  letzte_benachrichtigung: null,
  ohne_massnahme_seit_benachrichtigung: false,
  fehltage: { gesamt: 3, entschuldigt: 2, unentschuldigt: 1 },
  fehlstunden: { gesamt: 1.5, entschuldigt: 1.0, unentschuldigt: 0.5 },
  klassenbuch_anzahl: 2,
};

function mockData(items: unknown[], overrides: Record<string, unknown> = {}) {
  mockUseStudents.mockReturnValue({
    data: { items, total: items.length, limit: 50, offset: 0 },
    isLoading: false,
    isError: false,
    ...overrides,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any);
}

describe("StudentList", () => {
  it("renders a row per student with a link to the detail page", () => {
    mockData([BASE_STUDENT]);

    renderList();

    expect(screen.getByRole("link", { name: /Muster, Max/ })).toHaveAttribute("href", "/schueler/1");
    expect(screen.getByText("10a")).toBeInTheDocument();
  });

  it("shows Fehltage/Fehlstunden/Eintraege as their gesamt values, always (both modes)", () => {
    mockData([BASE_STUDENT]);

    renderList();

    const row = screen.getByRole("row", { name: /Muster, Max/ });
    expect(within(row).getByText("3")).toBeInTheDocument(); // Fehltage gesamt
    expect(within(row).getByText("1.5")).toBeInTheDocument(); // Fehlstunden gesamt
    expect(within(row).getByText("2")).toBeInTheDocument(); // Eintraege
  });

  it("shows the entschuldigt/unentschuldigt split as a title tooltip on the Fehltage cell", () => {
    mockData([BASE_STUDENT]);

    renderList();

    const row = screen.getByRole("row", { name: /Muster, Max/ });
    const fehltageCell = within(row).getByText("3");
    expect(fehltageCell).toHaveAttribute("title", expect.stringContaining("2 entschuldigt"));
    expect(fehltageCell).toHaveAttribute("title", expect.stringContaining("1 unentschuldigt"));
  });

  it("highlights a row without a measure since the last notification", () => {
    mockData([{ ...BASE_STUDENT, ohne_massnahme_seit_benachrichtigung: true }]);

    renderList();

    expect(screen.getByRole("row", { name: /Muster, Max/ })).toHaveAttribute("data-highlighted", "true");
  });

  it("toggles the nur_auffaellige filter via the URL params", () => {
    mockData([]);

    renderList();
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ nurAuffaellige: true }));
  });

  it("sets the min_stufe filter via the Mindeststufe select", () => {
    mockData([]);

    renderList();
    fireEvent.change(screen.getByLabelText("Mindeststufe"), { target: { value: "2" } });

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ minStufe: 2 }));
  });

  it("resets offset back to 0 when a filter changes while paginated", () => {
    mockData([]);

    renderList(["/schueler?offset=50"]);
    fireEvent.click(screen.getByLabelText("Nur auffällige"));

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it("disables the Weiter button on the last page", () => {
    mockData([BASE_STUDENT]);

    renderList();

    expect(screen.getByRole("button", { name: "Weiter" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Zurück" })).toBeDisabled();
  });

  it("shows an error message when the request fails", () => {
    mockData([], { data: undefined, isError: true });

    renderList();

    expect(screen.getByText("Fehler beim Laden der Schülerliste.")).toBeInTheDocument();
  });

  it("reads schuljahr from the URL and passes it to useStudents", () => {
    mockData([]);

    renderList(["/schueler?schuljahr=27"]);

    expect(mockUseStudents).toHaveBeenLastCalledWith(expect.objectContaining({ schuljahrId: 27 }));
  });

  it("hides zaehlerstand-based columns (Eskalationsstufe, Benachrichtigt) in history mode", () => {
    mockData([{ ...BASE_STUDENT, zaehlerstand: null, letzte_benachrichtigung: null }]);

    renderList(["/schueler?schuljahr=27"]);

    expect(screen.queryByText("Benachrichtigt")).not.toBeInTheDocument();
  });

  it("sorts by clicking a column header, toggling asc/desc, and persists it in the URL", () => {
    mockData([]);

    renderList();
    fireEvent.click(screen.getByRole("columnheader", { name: /Fehlstunden/ }));

    expect(mockUseStudents).toHaveBeenLastCalledWith(
      expect.objectContaining({ sortBy: "fehlstunden", sortDir: "asc" }),
    );

    fireEvent.click(screen.getByRole("columnheader", { name: /Fehlstunden/ }));

    expect(mockUseStudents).toHaveBeenLastCalledWith(
      expect.objectContaining({ sortBy: "fehlstunden", sortDir: "desc" }),
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/StudentList/StudentList.test.tsx`
Expected: FAIL — component still branches on `isHistoryMode` for column structure and has no sortable headers.

- [ ] **Step 3: Rewrite `StudentList.tsx`**

```typescript
// frontend/src/pages/StudentList/StudentList.tsx
import { Link, useSearchParams } from "react-router-dom";
import type { StudentSortField } from "../../api/hooks/useStudents";
import { useStudents } from "../../api/hooks/useStudents";
import type { FehlzeitSplit, StudentOverview } from "../../api/types";
import { EskalationsBadge } from "../../components/EskalationsBadge/EskalationsBadge";
import { NotificationFlyout } from "../../components/NotificationFlyout/NotificationFlyout";
import { valueToColor } from "../../utils/colorScale";
import styles from "./StudentList.module.css";

interface SpalteConfig {
  feld: StudentSortField;
  label: string;
}

const SORTIERBARE_SPALTEN: SpalteConfig[] = [
  { feld: "nachname", label: "Name" },
  { feld: "klasse", label: "Klasse" },
  { feld: "fehltage", label: "Fehltage" },
  { feld: "fehlstunden", label: "Fehlstunden" },
  { feld: "klassenbuch_anzahl", label: "Einträge" },
];

function splitTitle(split: FehlzeitSplit): string {
  return `${split.entschuldigt} entschuldigt, ${split.unentschuldigt} unentschuldigt`;
}

function extremwerte(items: StudentOverview[], feld: "fehltage" | "fehlstunden"): [number, number] {
  const werte = items.map((item) => item[feld]?.gesamt ?? 0);
  if (werte.length === 0) return [0, 0];
  return [Math.min(...werte), Math.max(...werte)];
}

export function StudentList() {
  const [searchParams, setSearchParams] = useSearchParams();

  const bereichParam = searchParams.get("bereich");
  const klasseParam = searchParams.get("klasse");
  const minStufeParam = searchParams.get("min_stufe");
  const nurAuffaellige = searchParams.get("nur_auffaellige") === "true";
  const offset = Number(searchParams.get("offset") ?? "0");
  const schuljahrParam = searchParams.get("schuljahr");
  const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;
  const isHistoryMode = schuljahrId !== null;
  const sortByParam = searchParams.get("sort_by") as StudentSortField | null;
  const sortDirParam = searchParams.get("sort_dir") === "desc" ? "desc" : "asc";

  const { data, isLoading, isError } = useStudents({
    bereichId: bereichParam ? Number(bereichParam) : null,
    klasseId: klasseParam ? Number(klasseParam) : null,
    minStufe: minStufeParam ? Number(minStufeParam) : null,
    nurAuffaellige,
    offset,
    schuljahrId,
    sortBy: sortByParam,
    sortDir: sortDirParam,
  });

  function updateParam(name: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete(name);
    } else {
      next.set(name, value);
    }
    next.delete("offset");
    setSearchParams(next);
  }

  function goToOffset(newOffset: number) {
    const next = new URLSearchParams(searchParams);
    next.set("offset", String(newOffset));
    setSearchParams(next);
  }

  function handleSort(feld: StudentSortField) {
    const next = new URLSearchParams(searchParams);
    if (sortByParam === feld) {
      next.set("sort_dir", sortDirParam === "asc" ? "desc" : "asc");
    } else {
      next.set("sort_by", feld);
      next.set("sort_dir", "asc");
    }
    next.delete("offset");
    setSearchParams(next);
  }

  if (isLoading) {
    return <p>Lädt Schülerliste…</p>;
  }
  if (isError || !data) {
    return <p>Fehler beim Laden der Schülerliste.</p>;
  }

  const hasPrevious = offset > 0;
  const hasNext = offset + data.limit < data.total;
  const rangeStart = data.total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + data.limit, data.total);

  const [fehltageMin, fehltageMax] = extremwerte(data.items, "fehltage");
  const [fehlstundenMin, fehlstundenMax] = extremwerte(data.items, "fehlstunden");
  const maxStufeNr = Math.max(
    1,
    ...data.items.flatMap((item) =>
      Object.values(item.zaehlerstand ?? {}).map((stand) => stand.erreichte_stufe_nr ?? 0),
    ),
  );

  return (
    <div>
      <div className={styles.filters}>
        <label>
          Mindeststufe{" "}
          <select value={minStufeParam ?? ""} onChange={(event) => updateParam("min_stufe", event.target.value)}>
            <option value="">Alle</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            aria-label="Nur auffällige"
            checked={nurAuffaellige}
            onChange={(event) => updateParam("nur_auffaellige", event.target.checked ? "true" : "")}
          />{" "}
          Nur auffällige
        </label>
      </div>
      <table className={styles.table}>
        <thead>
          <tr>
            {SORTIERBARE_SPALTEN.map((spalte) => (
              <th key={spalte.feld}>
                <button type="button" className={styles.sortButton} onClick={() => handleSort(spalte.feld)}>
                  {spalte.label}
                  {sortByParam === spalte.feld ? (sortDirParam === "asc" ? " ▲" : " ▼") : ""}
                </button>
              </th>
            ))}
            {isHistoryMode ? null : (
              <>
                <th>Eskalationsstufe</th>
                <th>Benachrichtigt</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {data.items.map((student) => (
            <tr
              key={student.id}
              data-highlighted={student.ohne_massnahme_seit_benachrichtigung}
              className={student.ohne_massnahme_seit_benachrichtigung ? styles.highlighted : undefined}
            >
              <td>
                <Link to={`/schueler/${student.id}`}>
                  {student.nachname}, {student.vorname}
                </Link>
              </td>
              <td>{student.klasse?.name ?? "—"}</td>
              <td
                title={student.fehltage ? splitTitle(student.fehltage) : undefined}
                style={{ color: student.fehltage ? valueToColor(student.fehltage.gesamt, fehltageMin, fehltageMax) : undefined }}
              >
                {student.fehltage?.gesamt ?? "—"}
              </td>
              <td
                title={student.fehlstunden ? splitTitle(student.fehlstunden) : undefined}
                style={{
                  color: student.fehlstunden
                    ? valueToColor(student.fehlstunden.gesamt, fehlstundenMin, fehlstundenMax)
                    : undefined,
                }}
              >
                {student.fehlstunden?.gesamt ?? "—"}
              </td>
              <td>{student.klassenbuch_anzahl ?? "—"}</td>
              {isHistoryMode ? null : (
                <>
                  <td>
                    <div className={styles.badges}>
                      {Object.entries(student.zaehlerstand ?? {}).map(([typ, stand]) => (
                        <EskalationsBadge key={typ} stufeNr={stand.erreichte_stufe_nr} maxStufeNr={maxStufeNr} />
                      ))}
                    </div>
                  </td>
                  <td>
                    <NotificationFlyout benachrichtigung={student.letzte_benachrichtigung} />
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <div className={styles.pagination}>
        <button type="button" disabled={!hasPrevious} onClick={() => goToOffset(Math.max(0, offset - data.limit))}>
          Zurück
        </button>
        <span>
          {rangeStart}–{rangeEnd} von {data.total}
        </span>
        <button type="button" disabled={!hasNext} onClick={() => goToOffset(offset + data.limit)}>
          Weiter
        </button>
      </div>
    </div>
  );
}
```

Add to `frontend/src/pages/StudentList/StudentList.module.css`:

```css
.sortButton {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/StudentList/StudentList.test.tsx`
Expected: PASS (13 tests)

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, no TypeScript errors

- [ ] **Step 6: Manually verify in the browser**

Run: `cd frontend && npm run dev` (or use the project's existing dev-server workflow), open the Schülerliste, and confirm:
- Fehltage/Fehlstunden/Einträge columns show in both normal and history (`?schuljahr=<id>`) mode
- Clicking a column header sorts and toggles direction, persisted in the URL
- Hovering the Fehltage/Fehlstunden cell shows the entschuldigt/unentschuldigt split as a native tooltip
- The Eskalationsstufe badges are small colored circles, not the old text badges

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/StudentList/StudentList.tsx frontend/src/pages/StudentList/StudentList.module.css frontend/src/pages/StudentList/StudentList.test.tsx
git commit -m "feat: unify Schuelerliste columns with sortable headers, color coding, and split tooltips"
```

---

## Final Verification

- [ ] Run the full backend suite: `cd backend && pytest -q` — expect PASS.
- [ ] Run the full frontend suite: `cd frontend && npx vitest run && npx tsc --noEmit` — expect PASS.
- [ ] Update `ROADMAP.md`: mark Bundle A as ✅ erledigt with today's date, commits, and a short summary (following the pattern of the other completed bundles in that file), and reference this plan + the design doc.
- [ ] Commit the ROADMAP update separately: `git commit -m "docs: mark Bundle A as complete"`.
