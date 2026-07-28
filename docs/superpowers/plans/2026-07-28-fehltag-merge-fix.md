# Fehltag-Merge-Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUntis liefert für ganztägige Absenzen mehrere Perioden-Zeilen ohne `subjectId` statt einer einzigen Ganztages-Zeile; der Fehlzeiten-Sync führt diese pro Schüler/Tag zu einer einzigen `typ='tag'`-Zeile zusammen, sodass "ein Fehltag" wieder ein Fehltag ist — überall dort, wo das gezählt wird (Eskalations-Engine, Dashboard), ohne dass diese Stellen selbst geändert werden müssen.

**Architecture:** In `sync_fehlzeiten` werden WebUntis-Einträge ohne `subjectId` vor dem Schreiben nach `(schueler_id, datum)` gruppiert; pro Gruppe entsteht eine zusammengeführte Zeile mit festem Ganztages-Rahmen (`start_zeit=0`, `end_zeit=2359`), die über den bestehenden Unique-Key-Upsert-Mechanismus geschrieben wird — keine Schema-/Migrationsänderung. Einträge mit `subjectId` (`typ='stunde'`) bleiben unverändert, eine Zeile pro Absenz.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 async (bestehender Backend-Stack, keine neuen Abhängigkeiten).

## Global Constraints

- Design-Referenz: [docs/superpowers/specs/2026-07-28-fehltag-merge-fix-design.md](../specs/2026-07-28-fehltag-merge-fix-design.md) — bei Widersprüchen zwischen Plan und Design gewinnt das Design.
- Backend-Code folgt bestehenden Konventionen: `from __future__ import annotations`, SQLAlchemy 2.0 async (`select`/`execute`/`scalars`), deutsche Namensgebung in Services/Kommentaren.
- Commit-Messages auf Englisch.
- Keine Migration, kein Cleanup-Skript für bereits synchronisierte Bestandsdaten (siehe Design-Dokument Abschnitt 6 "Bewusst nicht enthalten") — der Nutzer truncatet die Testdaten selbst und stößt danach einen frischen Sync an.
- Keine Änderung an `eskalations_pruefung.py`, `dashboard_query.py`, `student_query.py`, `export_service.py` oder der Klassenbuch-Synchronisation.

---

### Task 1: Fehltage-Zusammenführung im WebUntis-Sync

**Files:**
- Modify: `backend/app/services/webuntis_fehlzeit_sync.py`
- Test: `backend/tests/test_webuntis_fehlzeit_sync.py`
- Modify: `TECH-SPEC.md` (Abschnitt 1.2, Doku-Ergänzung)

**Interfaces:**
- Produces: `sync_fehlzeiten(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None` — Signatur unverändert, nur das interne Verhalten für `typ='tag'`-Kandidaten ändert sich. Zwei neue private Hilfsfunktionen im selben Modul: `_zaehlt_als_entschuldigt(excuse_status_id: int | None, zaehlt_als_entschuldigt_by_id: dict[int, bool]) -> bool` und `_merge_tag_gruppe(rows: list[dict], excuse_status_id_by_name: dict[str, int], zaehlt_als_entschuldigt_by_id: dict[int, bool]) -> tuple[int | None, str | None]` (liefert `(merged_excuse_status_id, merged_grund_text)`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_webuntis_fehlzeit_sync.py` (the file already imports `datetime`, `AsyncMock`, `pytest`, `select`, `ExcuseStatus`, `Fehlzeit`, `Schueler`, `sync_fehlzeiten` — no new imports needed):

```python
@pytest.mark.asyncio
async def test_sync_fehlzeiten_merges_multiple_tag_rows_into_one_day(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].typ == "tag"
    assert rows[0].start_zeit == 0
    assert rows[0].end_zeit == 2359


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_prefers_unentschuldigt_status(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    nicht_entschuldigt = ExcuseStatus(name="nicht entsch.", zaehlt_als_entschuldigt=False)
    db_session.add_all([schueler, entschuldigt, nicht_entschuldigt])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "nicht entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == nicht_entschuldigt.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_keeps_entschuldigt_when_all_periods_entschuldigt(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    entschuldigt = ExcuseStatus(name="entsch.", zaehlt_als_entschuldigt=True)
    db_session.add_all([schueler, entschuldigt])
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "entsch.", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "excuseStatus": "entsch.", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.excuse_status_id == entschuldigt.id


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_concatenates_distinct_grund_text(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "Krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "Krank", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 925, "endTime": 1010, "studentId": "ext-1",
                "subjectId": "", "absenceReason": "Arzttermin", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    fehlzeit = result.scalar_one()
    assert fehlzeit.grund_text == "Krank; Arzttermin"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_keeps_stunde_rows_separate(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 1425, "endTime": 1510, "studentId": "ext-1",
                "subjectId": "Deutsch", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    rows = {f.typ: f for f in result.scalars().all()}
    assert len(rows) == 2
    assert rows["tag"].start_zeit == 0
    assert rows["stunde"].fach == "Deutsch"


@pytest.mark.asyncio
async def test_sync_fehlzeiten_merge_is_idempotent_across_reruns(db_session):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B")
    db_session.add(schueler)
    await db_session.commit()

    client = AsyncMock()
    client.call.return_value = {
        "periodsWithAbsences": [
            {
                "date": 20260624, "startTime": 730, "endTime": 815, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
            {
                "date": 20260624, "startTime": 815, "endTime": 900, "studentId": "ext-1",
                "subjectId": "", "invalid": False,
            },
        ]
    }

    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    await sync_fehlzeiten(client, db_session, datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))

    result = await db_session.execute(select(Fehlzeit).where(Fehlzeit.schueler_id == schueler.id))
    assert len(result.scalars().all()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && docker compose run --rm backend pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: the 6 new tests FAIL — `test_sync_fehlzeiten_merges_multiple_tag_rows_into_one_day` and `test_sync_fehlzeiten_merge_is_idempotent_across_reruns` fail with `assert 3 == 1` / `assert 2 == 1` (each raw row currently becomes its own `Fehlzeit` row); the excuse-status and grund-text merge tests fail similarly because no merging happens yet. The 5 pre-existing tests in this file still PASS (unchanged behavior for single-row-per-day cases).

- [ ] **Step 3: Implement the merge logic**

Replace the full contents of `backend/app/services/webuntis_fehlzeit_sync.py`:

```python
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


def _zaehlt_als_entschuldigt(excuse_status_id: int | None, zaehlt_als_entschuldigt_by_id: dict[int, bool]) -> bool:
    if excuse_status_id is None:
        return False
    return zaehlt_als_entschuldigt_by_id.get(excuse_status_id, False)


def _merge_tag_gruppe(
    rows: list[dict],
    excuse_status_id_by_name: dict[str, int],
    zaehlt_als_entschuldigt_by_id: dict[int, bool],
) -> tuple[int | None, str | None]:
    """Fasst mehrere WebUntis-Perioden-Zeilen desselben Schuelers/Tages zu den Feldern
    einer einzigen Tages-Zeile zusammen (siehe
    docs/superpowers/specs/2026-07-28-fehltag-merge-fix-design.md).

    excuse_status_id: "unentschuldigt gewinnt" - zaehlt mindestens eine Zeile nicht als
    entschuldigt (aufgeloester Status mit zaehlt_als_entschuldigt=False, oder ein nicht
    aufloesbarer Status), wird deren excuse_status_id uebernommen (bzw. None, falls diese
    Zeile selbst keinen aufgeloesten Status hatte). Nur wenn alle Zeilen entschuldigt sind,
    bleibt ein entschuldigter Status erhalten (die erste in Eintragsreihenfolge).

    grund_text: verschiedene, nicht-leere Freitexte werden mit "; " zusammengefuegt
    (Dopplungen entfernt, Reihenfolge des ersten Vorkommens).
    """
    excused_ids: list[int | None] = []
    unexcused_ids: list[int | None] = []
    gruende: list[str] = []

    for row in rows:
        excuse_status_id = excuse_status_id_by_name.get(row.get("excuseStatus"))
        if _zaehlt_als_entschuldigt(excuse_status_id, zaehlt_als_entschuldigt_by_id):
            excused_ids.append(excuse_status_id)
        else:
            unexcused_ids.append(excuse_status_id)

        grund = row.get("absenceReason") or None
        if grund and grund not in gruende:
            gruende.append(grund)

    if unexcused_ids:
        merged_excuse_status_id = unexcused_ids[0]
    elif excused_ids:
        merged_excuse_status_id = excused_ids[0]
    else:
        merged_excuse_status_id = None

    return merged_excuse_status_id, ("; ".join(gruende) if gruende else None)


async def sync_fehlzeiten(client: WebUntisClient, db: AsyncSession, von: date, bis: date) -> None:
    """getTimetableWithAbsences -> fehlzeit (TECH-SPEC.md Abschnitt 1.2, 1.3).

    schueler_id wird ueber Schueler.externe_id aufgeloest (identisch mit studentId-UUID) -
    kein Namensabgleich noetig, siehe TECH-SPEC.md Abschnitt 1.3.

    WebUntis liefert fuer ganztaegige Absenzen an dieser Schule mehrere Perioden-Zeilen
    ohne subjectId statt einer einzigen Ganztages-Zeile (siehe TECH-SPEC.md Abschnitt 1.2) -
    diese werden pro Schueler/Tag zu einer einzigen typ='tag'-Zeile zusammengefuehrt, bevor
    sie geschrieben werden (siehe
    docs/superpowers/specs/2026-07-28-fehltag-merge-fix-design.md). Zeilen mit subjectId
    (typ='stunde') bleiben unveraendert, eine Zeile pro Absenz.
    """
    result = await client.call(
        "getTimetableWithAbsences",
        {"options": {"startDate": _to_webuntis_date(von), "endDate": _to_webuntis_date(bis)}},
    )
    entries = result.get("periodsWithAbsences", []) if isinstance(result, dict) else result

    schueler_id_by_externe_id = dict((await db.execute(select(Schueler.externe_id, Schueler.id))).all())
    excuse_status_id_by_name = dict((await db.execute(select(ExcuseStatus.name, ExcuseStatus.id))).all())
    zaehlt_als_entschuldigt_by_id = dict(
        (await db.execute(select(ExcuseStatus.id, ExcuseStatus.zaehlt_als_entschuldigt))).all()
    )

    existing = (await db.execute(select(Fehlzeit))).scalars().all()
    by_key = {(f.schueler_id, f.datum, f.start_zeit, f.end_zeit, f.typ): f for f in existing}

    def _upsert(schueler_id: int, datum: date, start_zeit: int, end_zeit: int, typ: str) -> Fehlzeit:
        key = (schueler_id, datum, start_zeit, end_zeit, typ)
        fehlzeit = by_key.get(key)
        if fehlzeit is None:
            fehlzeit = Fehlzeit(
                schueler_id=schueler_id, datum=datum, start_zeit=start_zeit, end_zeit=end_zeit, typ=typ
            )
            db.add(fehlzeit)
            by_key[key] = fehlzeit
        return fehlzeit

    tag_gruppen: dict[tuple[int, date], list[dict]] = {}

    for row in entries or []:
        if row.get("invalid"):
            continue

        schueler_id = schueler_id_by_externe_id.get(row["studentId"])
        if schueler_id is None:
            logger.warning("Fehlzeiten-Sync: unbekannte externe_id=%s, uebersprungen", row["studentId"])
            continue

        if row.get("subjectId"):
            fehlzeit = _upsert(
                schueler_id, _from_webuntis_date(row["date"]), row["startTime"], row["endTime"], "stunde"
            )
            fehlzeit.fach = row.get("subjectId") or None
            fehlzeit.grund_text = row.get("absenceReason") or None
            fehlzeit.excuse_status_id = excuse_status_id_by_name.get(row.get("excuseStatus"))
            fehlzeit.invalid = False
        else:
            datum = _from_webuntis_date(row["date"])
            tag_gruppen.setdefault((schueler_id, datum), []).append(row)

    for (schueler_id, datum), gruppe in tag_gruppen.items():
        merged_excuse_status_id, merged_grund_text = _merge_tag_gruppe(
            gruppe, excuse_status_id_by_name, zaehlt_als_entschuldigt_by_id
        )
        fehlzeit = _upsert(schueler_id, datum, 0, 2359, "tag")
        fehlzeit.fach = None
        fehlzeit.grund_text = merged_grund_text
        fehlzeit.excuse_status_id = merged_excuse_status_id
        fehlzeit.invalid = False

    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && docker compose run --rm backend pytest tests/test_webuntis_fehlzeit_sync.py -v`
Expected: PASS (all 11 tests: 5 pre-existing + 6 new)

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && docker compose run --rm backend pytest -q`
Expected: PASS, no regressions (this touches `eskalations_pruefung.py`'s data source indirectly via `Fehlzeit` rows, but not its code — its existing tests seed `Fehlzeit` rows directly and are unaffected)

- [ ] **Step 6: Document the WebUntis data quirk in TECH-SPEC.md**

In `TECH-SPEC.md`, section 1.2, find the paragraph describing the Tag-Ebene/Stunde-Ebene distinction (the one starting with "Das deckt sich gut mit der Fehltage/Fehlstunden-Unterscheidung..."). Add a new paragraph directly after it:

```markdown
**Nachtrag (2026-07-28, Live-Beobachtung nach Plan 9):** An dieser Schule liefert WebUntis für ganztägige Absenzen keine einzelne Ganztages-Zeile (`startTime: 0`, `endTime: 2359`), sondern **eine Zeile pro betroffener Unterrichtsstunde** (z.B. `startTime: 730, endTime: 815`), jede weiterhin ohne `subjectId` — korrekt als `typ='tag'` klassifiziert, aber ohne Zusammenführung hätte das jeden Fehltag mehrfach gezählt (bis zu 11× an dieser Schule). Der Sync (`app/services/webuntis_fehlzeit_sync.py`) führt seither alle `subjectId`-losen Zeilen desselben Schülers/Tages zu einer einzigen `typ='tag'`-Zeile mit festem `start_zeit=0`/`end_zeit=2359` zusammen, bevor sie geschrieben wird — siehe [Design-Dok](superpowers/specs/2026-07-28-fehltag-merge-fix-design.md). Bei gemischtem Entschuldigungsstatus über die zusammengeführten Perioden gilt "unentschuldigt gewinnt".
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/webuntis_fehlzeit_sync.py backend/tests/test_webuntis_fehlzeit_sync.py TECH-SPEC.md
git commit -m "fix: merge same-day tag-typed Fehlzeit rows in WebUntis sync

WebUntis reports whole-day absences as one row per lesson period
instead of a single day-level row, all correctly typed 'tag' (no
subjectId) but inflating Fehltage counts by up to 11x per day.
Groups subjectId-less rows by (schueler_id, datum) before writing,
merging excuse status (unentschuldigt wins on mixed status) and
absenceReason text. No change needed in escalation engine or
dashboard - they already count Fehlzeit rows directly."
```

---

## Self-Review Notes

- **Spec coverage:** Design doc sections 2 (Fix-Ebene), 3 (Merge-Logik), 4 (Testing), 5 (Dokumentation) are all covered by Task 1's steps. Section 6 ("Bewusst nicht enthalten") is respected — no migration/cleanup script, no changes to other consumers.
- **Type consistency:** `_merge_tag_gruppe`'s return type `tuple[int | None, str | None]` matches how it's unpacked in `sync_fehlzeiten` (`merged_excuse_status_id, merged_grund_text = ...`) and how the tests assert on `fehlzeit.excuse_status_id` / `fehlzeit.grund_text`.
- **No placeholders:** all test code and implementation code is complete and runnable as written.
