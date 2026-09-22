# Dashboard-Statistiken schuljahresbewusst + Dropdown-Filter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zwei kleine, zusammenhängende Nachträge zu Plan 17 (`docs/superpowers/plans/2026-09-21-schuljahr-historie-rueckwirkend.md`, bereits deployed), gemeldet nachdem Plan 17 erfolgreich getestet wurde:

1. `GET /dashboard/stats` (Landing-Page-Balkendiagramme: Ø Fehltage/-stunden/Klassenbuch/Maßnahmen) ignoriert den Schuljahr-Selektor komplett — kein `schuljahr_id`-Parameter, `dashboard_query._aggregate()` kennt nur eine untere Datumsgrenze, und die Schülerbasis kommt immer aus der live `schueler`-Tabelle. Fix: `schuljahr_id`-Parameter (analog `GET /students`), `_aggregate()` bekommt ein `(von, bis)`-Zeitraum-Paar statt nur `schuljahr_start`, und im Historie-Modus wird die Schülerbasis aus `schueler_klasse_historie` ermittelt (wie bei `GET /students`, Plan 17) statt aus der live `Schueler.klasse_id`/`aktiv`.
2. Die Vergleichsbalken (`_stats_for_bereich`/`_stats_schulweit`/`_stats_eigene_bereiche`) ermitteln "welche Klassen gehören zu diesem Bereich" über die nicht jahresgebundene `bereich_klasse`-Tabelle — im Historie-Modus falsch, da sie immer die aktuelle Struktur zeigt. Fix: im Historie-Modus stattdessen über `klasse.abteilung_id == bereich.abteilung_id` gruppieren (beide Spalten existieren bereits, Bundle D: Bereiche sind strukturell 1:1 aus WebUntis-Abteilungen abgeleitet — keine neue Historisierung nötig).
3. Das Schuljahr-Dropdown (`GET /dashboard/nav-options`) zeigt auch Schuljahre ohne jede Historie-Daten (zukünftige, in WebUntis schon angelegte Jahre, oder alte, nie importierte Jahre). Fix: `schuljahre`-Liste filtert auf "aktuelles Schuljahr ODER mindestens eine `schueler_klasse_historie`-Zeile vorhanden".

**Referenz:** [Design-Dokument](../specs/2026-09-22-dashboard-stats-schuljahr-design.md) — direkter Nachtrag zu [Plan 16](2026-09-18-schuljahr-historisierung.md) und [Plan 17](2026-09-21-schuljahr-historie-rueckwirkend.md).

**Architecture:** Keine neuen Tabellen/Spalten/Migrationen — alle drei Punkte sind Query-Logik-Fixes auf dem bestehenden Plan-16/17-Schema (`klasse.schuljahr_id`, `klasse.abteilung_id`, `bereich.abteilung_id`, `schueler_klasse_historie`). (1) Die Schuljahr-Modus-Erkennung, die bisher privat als `_resolve_schuljahr_zeitraum` in `backend/app/api/routes/students.py` lebt, wird unverändert in ein neues gemeinsames Modul `backend/app/services/schuljahr_zeitraum.py` verschoben (`resolve_schuljahr_zeitraum`), damit `dashboard_query.py` sie mitbenutzen kann, ohne sie zu duplizieren. (2) `dashboard_query._aggregate()` bekommt `von`/`bis` (statt `schuljahr_start`) plus einen optionalen `historie_schuljahr_id`-Parameter, der die Schülerbasis auf einen `schueler_klasse_historie`-Join umschaltet — analog zum in Plan 17 in `student_query.list_students` eingeführten `historie_schuljahr_id`-Parameter, aber lokal in `_aggregate` nachgebaut (dort werden nur `schueler_id`s gebraucht, keine paginierten/sortierten `Schueler`-Objekte — `list_students` selbst wird nicht wiederverwendet). (3) Ein neuer Helfer `_bereich_klassen(db, bereich, historie_schuljahr_id)` kapselt die Bereich→Klassen-Auflösung für beide Modi und ersetzt drei fast identische `bereich_klasse`-Abfragen in `_stats_for_bereich`/`_stats_schulweit`/`_stats_eigene_bereiche`.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Alembic / pytest (backend, `backend/`); React 18 / TypeScript / Vitest (frontend, `frontend/`).

## Wichtige Abweichungen/Entscheidungen (beim Schreiben dieses Plans festgestellt)

Der Code wurde gegen den tatsächlichen Stand nach Plan 17 verifiziert (nicht nur gegen dessen Plandokument). Folgende Punkte sind beim Schreiben dieses Plans aufgefallen und nicht (oder nicht exakt so) im Design-Dok vorweggenommen:

1. **`_resolve_schuljahr_zeitraum` in `students.py` ist unverändert seit Plan 16/17** (`backend/app/api/routes/students.py:40-51`) — Name und Signatur (`(db, schuljahr_id: int | None) -> tuple[date | None, date | None]`) stimmen exakt mit der Design-Dok-Beschreibung überein. Es gibt daneben eine zweite, verwandte, aber **nicht** zu verschiebende Funktion `_aktuelles_schuljahr_zeitraum(db)` (Zeilen 54-64, kein `schuljahr_id`-Parameter, liest `einstellung.aktuelles_schuljahr_id` und liefert dessen `(start_datum, end_datum)` als **beidseitig begrenztes** Intervall). Das Design-Dok will für den *aktuellen* Modus in `dashboard_query.py` aber ausdrücklich `(schuljahr_start_cache, None)` — **ohne** Obergrenze ("es gibt keine zukünftigen Daten"). `_aktuelles_schuljahr_zeitraum` passt dafür nicht (liefert eine Obergrenze) und wird deshalb **nicht** mitverschoben oder wiederverwendet — nur `_resolve_schuljahr_zeitraum` wird extrahiert, umbenannt in `resolve_schuljahr_zeitraum` (ohne führenden Unterstrich, jetzt öffentliche Modul-Funktion) und nach `app/services/schuljahr_zeitraum.py` verschoben.
2. **Kein bestehender direkter Unit-Test für `_resolve_schuljahr_zeitraum`** (`grep` über `backend/tests/` bestätigt) — sie wird bisher nur indirekt über die Routen-Tests in `test_api_students.py` abgedeckt. Task 1 fügt deshalb eine neue, direkte Testdatei `backend/tests/test_schuljahr_zeitraum.py` hinzu (statt nur bestehende Tests zu verschieben) und verifiziert zusätzlich per vollem `test_api_students.py`-Lauf, dass der Umzug keine Verhaltensänderung hat.
3. **`student_query.list_students`s `historie_schuljahr_id`-Muster (Plan 17) wird NICHT direkt aufgerufen, sondern in `_aggregate` nachgebaut** — `list_students` liefert paginierte, sortierte `Schueler`-ORM-Objekte inkl. aller Filter (`min_stufe`, `nur_auffaellige`, Sortierung); `_aggregate` braucht nur eine Menge `schueler_id`s als Basis für nachfolgende `COUNT`/`SUM`-Aggregationen. Ein Aufruf von `list_students(..., limit=<riesig>)` nur um an `[s.id for s in items]` zu kommen wäre unnötig teuer und semantisch schief (Pagination/Sortierung sind hier irrelevant). `_aggregate` bekommt stattdessen eine eigene, kleinere Variante desselben Joins (`select(SchuelerKlasseHistorie.schueler_id).where(schuljahr_id=..., klasse_id.in_(...))` statt `select(Schueler.id).where(Schueler.aktiv.is_(True), Schueler.klasse_id.in_(...))`) — Prinzip identisch (Roster-Basis umschalten, kein `aktiv`-Filter im Historie-Modus, siehe Plan-17-Design-Dok), Implementierung lokal.
4. **`bereich_klasse`-Abfrage kommt an drei Stellen fast wortgleich vor** (`_stats_for_bereich`, `_stats_schulweit`, `_stats_eigene_bereiche`) — Task 3 führt einen gemeinsamen Helfer `_bereich_klassen(db, bereich, historie_schuljahr_id)` ein, der beide Modi kapselt, statt die Verzweigung dreimal zu duplizieren. Das ist eine über das Design-Dok hinausgehende, aber naheliegende Konsolidierung (das Design-Dok beschreibt nur *was* sich ändern soll, nicht die interne Code-Struktur).
5. **Ein `Bereich` ohne `abteilung_id` liefert im Historie-Modus bewusst eine leere Klassenliste, keinen Fehler** — `Klasse.abteilung_id == bereich.abteilung_id` mit `bereich.abteilung_id is None` würde SQLAlchemy als `IS NULL`-Vergleich übersetzen und fälschlich alle historischen Klassen ohne `abteilung_id`-Zuordnung treffen (die eigentlich "keinem Bereich zugeordnet" bedeuten, nicht "diesem Bereich mit `abteilung_id=NULL` zugeordnet"). `_bereich_klassen` prüft deshalb `bereich.abteilung_id is None` explizit und gibt dann `[]` zurück, bevor die Query überhaupt gebaut wird. Ein solcher Bereich bleibt trotzdem in der `vergleich`-Liste sichtbar (mit `anzahl_schueler=0`/leeren Kennzahlen), da die aufrufenden `_stats_*`-Funktionen weiterhin über *alle* sichtbaren `Bereich`-Zeilen iterieren — nur seine Klassenmenge ist leer. Das ist konsistent mit "stillschweigend ausgeschlossen" aus dem Design-Dok (keine Fehlzeiten/Schüler zählen zu diesem Bereich, aber der Balken existiert mit Wert 0 statt zu verschwinden — identisch zum bestehenden Verhalten eines Bereichs ganz ohne Klassen im Normalmodus).
6. **`get_dashboard_stats` bekommt `schuljahr_id` als 5. Parameter mit Default `None`** (statt eines Pflichtparameters) — alle bestehenden Aufrufe in `test_dashboard_query.py` (`dashboard_query.get_dashboard_stats(db, nutzer, bereich_id, klasse_id)`, 4 positionale Argumente) bleiben dadurch unverändert lauffähig; nur neue, historie-spezifische Tests übergeben das fünfte Argument. Analog zu `GET /students`/`GET /students/{id}` im Route-Layer (`schuljahr_id: int | None = None`).
7. **`GET /dashboard/stats` validiert `klasse_id`/`bereich_id` weiterhin gegen den AKTUELLEN Scope** (`resolve_scope`/`resolve_bereich_scope`, unverändert) — für einen Klassenlehrkraft-Scope, der (laut Plan-17-Abweichung 4) auch historische `klasse.id`-Werte enthalten kann (sofern seit Plan 16 mindestens ein Sync mit dieser Klasse gelaufen ist), funktioniert das bereits korrekt, ohne dass dieser Plan daran etwas ändern muss. Explizit **kein** neuer historie-bewusster Scope-Check — Design-Dok-Nicht-Ziel, identisch zur bestehenden, bewussten Einschränkung aus Plan 16 bei `GET /students`.
8. **Alembic-Head unverändert bei `e3735eedca38`** (verifiziert per `docker exec absenzdash-backend python -m alembic heads`) — keiner der drei Design-Dok-Punkte braucht eine neue Spalte/Tabelle/Index. **Dieser Plan enthält keine Alembic-Migration.**
9. **Frontend-Muster für den `schuljahr`-URL-Parameter bereits etabliert** (`frontend/src/pages/StudentList/StudentList.tsx:42-44`, `frontend/src/api/hooks/useStudents.ts`) — `useStats` folgt exakt demselben Zuschnitt: `schuljahrId: number | null` als zusätzliches Argument, `schuljahr_id`-Query-Param nur gesetzt, wenn nicht `null`. `useStats` hatte bisher **keine eigene Testdatei** (nur `Landing.test.tsx` mockt den Hook) — Task 6 legt `frontend/src/api/hooks/useStats.test.tsx` neu an, analog zu `useStudents.test.tsx`.

## Global Constraints

- **Nicht-Ziele (Design-Dok, hier bewusst wiederholt, damit Implementierer nicht scope-creepen):**
  - Keine Historisierung von `bereich_klasse` selbst — die Abteilungs-basierte Ableitung im Historie-Modus macht das überflüssig.
  - Keine Änderung an Scope/Berechtigungen für vergangene Schuljahre — `resolve_scope`/`resolve_bereich_scope` bleiben unverändert auf der aktuellen Struktur basiert (bestehende, bewusste Einschränkung aus Plan 16).
  - Kein Caching/keine Performance-Arbeit an `_aggregate()` über die beschriebenen Parameter-Änderungen hinaus.
- **Keine neue Alembic-Migration** in diesem Plan (siehe Abweichung 8 oben) — Alembic-Head bleibt `e3735eedca38`.
- Lokaler Dev-Stack läuft als Docker-Container: `absenzdash-backend` (Backend), `absenzdash-db` (Postgres). Migrationsbefehle entfallen in diesem Plan mangels neuer Migration; `docker compose`-Befehle werden nicht gegen eine echte/Prod-Umgebung ausgeführt.
- Commit-Messages auf Englisch (Projekt-Konvention).
- Nach Abschluss jedes Tasks committen (`CLAUDE.md`-Konvention); nach Abschluss des gesamten Plans `ROADMAP.md`/`TECH-SPEC.md`/`SPECS.md` aktualisieren (Task 7).

---

## Task 1: Gemeinsamer `schuljahr_zeitraum`-Helfer — Extraktion aus `students.py` (reiner Refactor)

**Files:**
- Create: `backend/app/services/schuljahr_zeitraum.py`
- Create: `backend/tests/test_schuljahr_zeitraum.py`
- Modify: `backend/app/api/routes/students.py`

**Interfaces:**
- Neu: `schuljahr_zeitraum.resolve_schuljahr_zeitraum(db: AsyncSession, schuljahr_id: int | None) -> tuple[date | None, date | None]` — wortgleiche Verschiebung von `students.py`s bisher privater `_resolve_schuljahr_zeitraum` (siehe Abweichung 1/2 oben). Verhalten unverändert: `schuljahr_id=None` oder `schuljahr_id == einstellung.aktuelles_schuljahr_id` → `(None, None)` ("aktuelles Schuljahr"); ein bekanntes vergangenes/zukünftiges `schuljahr_id` → `(schuljahr.start_datum, schuljahr.end_datum)`; ein unbekanntes `schuljahr_id` → `HTTPException(404)`.

- [x] **Step 1: Fehlschlagende Tests in `test_schuljahr_zeitraum.py` schreiben**

Neue Datei `backend/tests/test_schuljahr_zeitraum.py`:

```python
from datetime import date

import pytest
from fastapi import HTTPException

from app.models.einstellung import Einstellung
from app.models.schuljahr import Schuljahr
from app.services.schuljahr_zeitraum import resolve_schuljahr_zeitraum


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_none_when_no_schuljahr_id_given(db_session):
    von, bis = await resolve_schuljahr_zeitraum(db_session, None)
    assert (von, bis) == (None, None)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_none_when_schuljahr_id_matches_aktuelles(db_session, schuljahr):
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr.id))
    await db_session.commit()

    von, bis = await resolve_schuljahr_zeitraum(db_session, schuljahr.id)

    assert (von, bis) == (None, None)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_returns_bounds_for_past_schuljahr(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await db_session.commit()

    von, bis = await resolve_schuljahr_zeitraum(db_session, schuljahr_alt.id)

    assert von == date(2024, 9, 9)
    assert bis == date(2025, 7, 30)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_returns_bounds_when_no_einstellung_row_exists(db_session, schuljahr):
    # Kein Einstellung-Row -> "aktuelles_schuljahr_id" ist unbestimmt, jede uebergebene schuljahr_id
    # zaehlt dann als "vergangenes/anderes Schuljahr" (Historie-Modus).
    von, bis = await resolve_schuljahr_zeitraum(db_session, schuljahr.id)
    assert (von, bis) == (schuljahr.start_datum, schuljahr.end_datum)


@pytest.mark.asyncio
async def test_resolve_schuljahr_zeitraum_404s_for_unknown_schuljahr_id(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await resolve_schuljahr_zeitraum(db_session, 999999)
    assert exc_info.value.status_code == 404
```

- [x] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_schuljahr_zeitraum.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.schuljahr_zeitraum'`.

- [x] **Step 3: Modul anlegen**

Neue Datei `backend/app/services/schuljahr_zeitraum.py`:

```python
from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.einstellung import Einstellung
from app.models.schuljahr import Schuljahr


async def resolve_schuljahr_zeitraum(db: AsyncSession, schuljahr_id: int | None) -> tuple[date | None, date | None]:
    """None, None heisst "aktuelles Schuljahr, unveraendertes Verhalten". Ein konkretes
    (von, bis)-Paar heisst "Historie-Modus fuer dieses vergangene Schuljahr".

    Urspruenglich privat als _resolve_schuljahr_zeitraum in app/api/routes/students.py
    (Plan 16/17); hierher ausgelagert, damit app/services/dashboard_query.py dieselbe
    Schuljahr-Modus-Erkennung nutzen kann, ohne sie zu duplizieren, siehe
    docs/superpowers/specs/2026-09-22-dashboard-stats-schuljahr-design.md. Verhalten
    unveraendert gegenueber der bisherigen students.py-Fassung."""
    if schuljahr_id is None:
        return None, None
    einstellung = (await db.execute(select(Einstellung))).scalars().first()
    if einstellung is not None and schuljahr_id == einstellung.aktuelles_schuljahr_id:
        return None, None
    schuljahr = await db.get(Schuljahr, schuljahr_id)
    if schuljahr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Schuljahr")
    return schuljahr.start_datum, schuljahr.end_datum
```

- [x] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_schuljahr_zeitraum.py -v`
Expected: alle 5 Tests PASS.

- [x] **Step 5: `students.py` auf den gemeinsamen Helfer umstellen**

In `backend/app/api/routes/students.py`:

Entferne die lokale Funktion `_resolve_schuljahr_zeitraum` (Zeilen 40-51) komplett. Ergänze den Import:

```python
from app.services.schuljahr_zeitraum import resolve_schuljahr_zeitraum
```

Ersetze alle drei Aufrufstellen `_resolve_schuljahr_zeitraum(db, schuljahr_id)` durch `resolve_schuljahr_zeitraum(db, schuljahr_id)`:
- `get_students` (Zeile 100)
- `get_student_detail` (Zeile 197)
- `export_student_pdf` (Zeile 335)

`_aktuelles_schuljahr_zeitraum` (Zeilen 54-64) bleibt unverändert in `students.py` stehen (siehe Abweichung 1 — wird bewusst nicht verschoben). Die Imports `Einstellung`/`Schuljahr`/`HTTPException`/`status` bleiben in `students.py` erhalten, da sie von `_aktuelles_schuljahr_zeitraum` bzw. `export_student_pdf` (Zeile 338, `db.get(Schuljahr, schuljahr_id)` für `schuljahr_name`) weiterhin gebraucht werden.

- [x] **Step 6: Vollen Backend-Testlauf verifizieren (reiner Refactor — keine Verhaltensänderung erwartet)**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py tests/test_schuljahr_zeitraum.py -v`
Expected: alle Tests PASS (insbesondere alle bisherigen `schuljahr_id`-bezogenen Tests in `test_api_students.py` unverändert grün — der Umzug ändert keine Semantik).

Run zusätzlich den vollen Testlauf: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/services/schuljahr_zeitraum.py backend/app/api/routes/students.py \
  backend/tests/test_schuljahr_zeitraum.py
git commit -m "refactor: extract resolve_schuljahr_zeitraum into a shared service module"
```

---

## Task 2: `_aggregate()` — `(von, bis)`-Zeitraum + historische Schülerbasis über `schueler_klasse_historie`

**Files:**
- Modify: `backend/app/services/dashboard_query.py`
- Modify: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- Geändert: `_aggregate(db, klasse_ids: list[int] | None, von: date | None, bis: date | None, historie_schuljahr_id: int | None = None) -> StatsOwn` — ersetzt die bisherige `(db, klasse_ids, schuljahr_start: date | None)`-Signatur. `von`/`bis` grenzen `Fehlzeit.datum`/`KlassenbuchEintrag.datum`/`Massnahme.datum` beidseitig ein (`None` = unbegrenzt in diese Richtung). `historie_schuljahr_id` (Default `None`) schaltet die Schülerbasis von `Schueler.id WHERE aktiv` auf `SchuelerKlasseHistorie.schueler_id WHERE schuljahr_id = ...` um (kein `aktiv`-Filter im Historie-Modus, analog Plan 17).
- Neu (privat): `_zeitraum_filter(spalte, von, bis) -> list[Any]` — gemeinsamer Helfer für die drei `*.datum`-Filter, ersetzt die bisherige `datumsfilter`/`schuljahr_start`-Ad-hoc-Logik.
- Alle `_stats_*`-Funktionen und `get_dashboard_stats` geben `von`/`bis`/`historie_schuljahr_id` statt `schuljahr_start` durch (Signaturänderungen, siehe Step 5).

- [x] **Step 1: Fehlschlagende Tests in `test_dashboard_query.py` schreiben**

Füge in `backend/tests/test_dashboard_query.py` nach `_seed_schueler_mit_fehlzeit` (Zeile 181-195) folgende Tests ein (nutzt die bereits vorhandenen Imports `Schuljahr`, plus neu `SchuelerKlasseHistorie`):

```python
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie


@pytest.mark.asyncio
async def test_get_dashboard_stats_historie_mode_uses_schueler_klasse_historie_not_live_klasse_id(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_live = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_live])
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    # Schueler ist heute (live) in klasse_live, war im betrachteten Schuljahr aber in klasse_alt.
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_live.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id)
    )
    db_session.add(
        Fehlzeit(
            schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359
        )
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(
        db_session, nutzer, None, klasse_alt.id, schuljahr_alt.id
    )
    assert stats.own.anzahl_schueler == 1
    assert stats.own.avg_fehltage == 1.0

    # klasse_live ist nur die LIVE-Klasse, nicht die historische fuer schuljahr_alt -> kein Treffer.
    stats_live_klasse = await dashboard_query.get_dashboard_stats(
        db_session, nutzer, None, klasse_live.id, schuljahr_alt.id
    )
    assert stats_live_klasse.own.anzahl_schueler == 0


@pytest.mark.asyncio
async def test_get_dashboard_stats_historie_mode_includes_inactive_students(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    db_session.add(klasse)
    await db_session.flush()
    # inzwischen abgemeldeter Schueler (aktiv=False) -- war im betrachteten Schuljahr eingeschrieben.
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=False)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse.id)
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id, schuljahr_alt.id)

    assert stats.own.anzahl_schueler == 1


@pytest.mark.asyncio
async def test_get_dashboard_stats_historie_mode_excludes_fehlzeiten_after_schuljahr_end(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse.id)
    )
    db_session.add_all(
        [
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359),
            # liegt NACH schuljahr_alt.end_datum (2025-07-30) -- gehoert zum Folgejahr, muss ausgeschlossen werden.
            Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2025, 9, 20), start_zeit=0, end_zeit=2359),
        ]
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id, schuljahr_alt.id)

    assert stats.own.avg_fehltage == 1.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_current_schuljahr_still_has_no_upper_date_bound(db_session, schuljahr):
    # Regressionstest fuer die Design-Dok-Vorgabe "aktuelles Schuljahr weiterhin (schuljahr_start_cache,
    # None) -- keine Obergrenze noetig". Eine (theoretisch verfrueht importierte) Fehlzeit weit in der
    # Zukunft darf im Normalmodus nicht durch eine neu eingefuehrte Obergrenze verschwinden.
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schuljahr_start = date(2025, 9, 15)
    db_session.add(Einstellung(schuljahr_start_cache=schuljahr_start))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2099, 1, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, klasse.id)

    assert stats.own.avg_fehltage == 1.0
```

Ergänze außerdem im Import-Block von `test_dashboard_query.py` `from app.models.schueler_klasse_historie import SchuelerKlasseHistorie` (oben bereits als Inline-Import im ersten neuen Test gezeigt — an den Datei-Kopf verschieben, Konvention der übrigen Imports).

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -k historie_mode -v`
Expected: FAIL — `get_dashboard_stats()` akzeptiert noch kein fünftes Argument (`TypeError: takes from 4 to 4 positional arguments but 5 were given`) bzw. `_aggregate` kennt `historie_schuljahr_id` nicht.

Run zusätzlich: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -k current_schuljahr_still_has_no_upper -v`
Expected: PASS bereits vor der Implementierung (reiner Regressionstest auf bestehendes Verhalten) — dient hier nur als Ausgangs-Baseline, kein TDD-Fehlschlag nötig.

- [x] **Step 3: `_aggregate` und `_zeitraum_filter` umbauen**

In `backend/app/services/dashboard_query.py`, ergänze die Imports:

```python
from typing import Any

from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

Ersetze `_aggregate` (Zeilen 84-151) komplett durch:

```python
def _zeitraum_filter(spalte: Any, von: date | None, bis: date | None) -> list[Any]:
    filters: list[Any] = []
    if von is not None:
        filters.append(spalte >= von)
    if bis is not None:
        filters.append(spalte <= bis)
    return filters


async def _aggregate(
    db: AsyncSession,
    klasse_ids: list[int] | None,
    von: date | None,
    bis: date | None,
    historie_schuljahr_id: int | None = None,
) -> StatsOwn:
    """Aggregiert Rohzahlen ueber alle Schueler der gegebenen Klassen (None = alle Klassen).
    von/bis grenzen den Zeitraum beidseitig ein (None je Seite = unbegrenzt in diese Richtung) --
    aktuelles Schuljahr uebergibt (schuljahr_start_cache, None), vergangenes Schuljahr
    (schuljahr.start_datum, schuljahr.end_datum), siehe get_dashboard_stats.

    historie_schuljahr_id (Default None) schaltet die Schuelerbasis von der live
    Schueler.klasse_id/aktiv auf schueler_klasse_historie fuers gewaehlte Schuljahr um -- exakt
    das Roster-Prinzip aus student_query.list_students' historie_schuljahr_id-Parameter (Plan 17),
    hier lokal nachgebaut, da nur schueler_id's gebraucht werden, keine paginierten/sortierten
    Schueler-Objekte. Kein aktiv-Filter im Historie-Modus -- ein Schueler mit Snapshot fuers
    Schuljahr zaehlt unabhaengig vom heutigen aktiv-Status, siehe
    docs/superpowers/specs/2026-09-22-dashboard-stats-schuljahr-design.md."""
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

    if historie_schuljahr_id is None:
        schueler_query = select(Schueler.id).where(Schueler.aktiv.is_(True))
        if klasse_ids is not None:
            schueler_query = schueler_query.where(Schueler.klasse_id.in_(klasse_ids))
    else:
        schueler_query = select(SchuelerKlasseHistorie.schueler_id).where(
            SchuelerKlasseHistorie.schuljahr_id == historie_schuljahr_id
        )
        if klasse_ids is not None:
            schueler_query = schueler_query.where(SchuelerKlasseHistorie.klasse_id.in_(klasse_ids))
    schueler_ids = (await db.execute(schueler_query)).scalars().all()
    anzahl_schueler = len(schueler_ids)
    if anzahl_schueler == 0:
        return leer

    fehltage = (
        await db.execute(
            select(func.count()).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "tag",
                Fehlzeit.invalid.is_(False),
                *_zeitraum_filter(Fehlzeit.datum, von, bis),
            )
        )
    ).scalar_one()
    fehlstunden_minuten = (
        await db.execute(
            select(func.sum(fehlstunden_minuten_expr())).select_from(Fehlzeit).where(
                Fehlzeit.schueler_id.in_(schueler_ids),
                Fehlzeit.typ == "stunde",
                Fehlzeit.invalid.is_(False),
                *_zeitraum_filter(Fehlzeit.datum, von, bis),
            )
        )
    ).scalar_one()
    fehlstunden = minuten_zu_fehlstunden(fehlstunden_minuten)
    klassenbuch = (
        await db.execute(
            select(func.count()).select_from(KlassenbuchEintrag).where(
                KlassenbuchEintrag.schueler_id.in_(schueler_ids),
                *_zeitraum_filter(KlassenbuchEintrag.datum, von, bis),
            )
        )
    ).scalar_one()
    massnahmen = (
        await db.execute(
            select(func.count()).select_from(Massnahme).where(
                Massnahme.schueler_id.in_(schueler_ids),
                *_zeitraum_filter(Massnahme.datum, von, bis),
            )
        )
    ).scalar_one()

    return StatsOwn(
        anzahl_schueler=anzahl_schueler,
        avg_fehltage=round(fehltage / anzahl_schueler, 2),
        avg_fehlstunden=round(float(fehlstunden) / anzahl_schueler, 2),
        avg_klassenbuch=round(klassenbuch / anzahl_schueler, 2),
        anzahl_klassenbuch=klassenbuch,
        anzahl_massnahmen=massnahmen,
    )
```

- [x] **Step 4: Aufrufer anpassen (`_stats_*`, `get_dashboard_stats`)**

Ersetze in `backend/app/services/dashboard_query.py` alle `schuljahr_start: date | None`-Parameter der `_stats_*`-Funktionen durch `von: date | None, bis: date | None, historie_schuljahr_id: int | None` und reiche sie an `_aggregate` durch (die `bereich_klasse`-Klassenauflösung bleibt in diesem Step unverändert — das ist Task 3):

```python
async def _stats_for_bereich(
    db: AsyncSession, bereich: Bereich, von: date | None, bis: date | None, historie_schuljahr_id: int | None
) -> StatsOut:
    klassen = (
        await db.execute(
            select(Klasse)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
    ).scalars().all()
    own = await _aggregate(db, [k.id for k in klassen], von, bis, historie_schuljahr_id)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(
        level="bereich",
        context=StatsContext(bereich_id=bereich.id, bereich_name=bereich.name, klasse_id=None, klasse_name=None),
        own=own,
        vergleich=vergleich,
    )


async def _stats_schulweit(db: AsyncSession, von: date | None, bis: date | None, historie_schuljahr_id: int | None) -> StatsOut:
    own = await _aggregate(db, None, von, bis, historie_schuljahr_id)
    bereiche = (
        await db.execute(select(Bereich).where(Bereich.ausgeblendet.is_(False)).order_by(Bereich.name))
    ).scalars().all()
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        stats = await _aggregate(db, list(klasse_ids), von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    return StatsOut(level="schule", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_bereiche(
    db: AsyncSession, bereich_ids: set[int], von: date | None, bis: date | None, historie_schuljahr_id: int | None
) -> StatsOut:
    bereiche = (
        await db.execute(
            select(Bereich)
            .where(Bereich.id.in_(bereich_ids), Bereich.ausgeblendet.is_(False))
            .order_by(Bereich.name)
        )
    ).scalars().all()
    alle_klasse_ids: list[int] = []
    vergleich = []
    for bereich in bereiche:
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
        alle_klasse_ids.extend(klasse_ids)
        stats = await _aggregate(db, list(klasse_ids), von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=bereich.id, name=bereich.name, **stats.model_dump()))
    own = await _aggregate(db, alle_klasse_ids, von, bis, historie_schuljahr_id)
    return StatsOut(level="eigene_bereiche", context=_leerer_context(), own=own, vergleich=vergleich)


async def _stats_eigene_klassen(
    db: AsyncSession, klasse_ids: set[int], von: date | None, bis: date | None, historie_schuljahr_id: int | None
) -> StatsOut:
    klassen = (
        await db.execute(select(Klasse).where(Klasse.id.in_(klasse_ids)).order_by(Klasse.name))
    ).scalars().all()
    own = await _aggregate(db, list(klasse_ids), von, bis, historie_schuljahr_id)
    vergleich = []
    for klasse in klassen:
        stats = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        vergleich.append(StatsVergleichEintrag(id=klasse.id, name=klasse.name, **stats.model_dump()))
    return StatsOut(level="eigene_klassen", context=_leerer_context(), own=own, vergleich=vergleich)
```

Ersetze `get_dashboard_stats` (Zeilen 228-285):

```python
async def get_dashboard_stats(
    db: AsyncSession,
    nutzer: Nutzer,
    bereich_id: int | None,
    klasse_id: int | None,
    schuljahr_id: int | None = None,
) -> StatsOut:
    if nutzer.rolle == "klassenlehrkraft" and bereich_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="klassenlehrkraft cannot pass bereich_id"
        )

    von, bis = await resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None
    historie_schuljahr_id = schuljahr_id if ist_historie else None
    if not ist_historie:
        von = await _get_schuljahr_start(db)
        bis = None

    if klasse_id is not None:
        klasse_scope = await resolve_scope(db, nutzer)
        if klasse_scope is not None and klasse_id not in klasse_scope:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        klasse = (await db.execute(select(Klasse).where(Klasse.id == klasse_id))).scalar_one_or_none()
        if klasse is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Klasse nicht gefunden")
        own = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
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
        return await _stats_for_bereich(db, bereich, von, bis, historie_schuljahr_id)

    if nutzer.rolle == "schulleitung":
        return await _stats_schulweit(db, von, bis, historie_schuljahr_id)

    if nutzer.rolle == "bereichsleiter":
        bereich_scope = await resolve_bereich_scope(db, nutzer)
        if len(bereich_scope) == 1:
            bereich = (
                await db.execute(select(Bereich).where(Bereich.id == next(iter(bereich_scope))))
            ).scalar_one()
            return await _stats_for_bereich(db, bereich, von, bis, historie_schuljahr_id)
        return await _stats_eigene_bereiche(db, bereich_scope, von, bis, historie_schuljahr_id)

    klasse_scope = await resolve_scope(db, nutzer)
    if len(klasse_scope) == 1:
        klasse = (await db.execute(select(Klasse).where(Klasse.id == next(iter(klasse_scope))))).scalar_one()
        own = await _aggregate(db, [klasse.id], von, bis, historie_schuljahr_id)
        return StatsOut(
            level="klasse",
            context=StatsContext(bereich_id=None, bereich_name=None, klasse_id=klasse.id, klasse_name=klasse.name),
            own=own,
            vergleich=[],
        )
    return await _stats_eigene_klassen(db, klasse_scope, von, bis, historie_schuljahr_id)
```

Ergänze den Import `from app.services.schuljahr_zeitraum import resolve_schuljahr_zeitraum` (statt der bisher nur lokal in `students.py` lebenden Funktion — siehe Task 1).

- [x] **Step 5: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -v`
Expected: alle Tests PASS (auch alle bestehenden — `historie_schuljahr_id=None`/unverändertes `schuljahr_id=None` reproduzieren exakt das alte Verhalten).

- [x] **Step 6: Commit**

```bash
git add backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "feat: give dashboard_query._aggregate a (von, bis) window and a historie_schuljahr_id roster"
```

---

## Task 3: Historische Bereich-Gruppierung über `klasse.abteilung_id`/`bereich.abteilung_id`

**Files:**
- Modify: `backend/app/services/dashboard_query.py`
- Modify: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- Neu (privat): `_bereich_klassen(db, bereich: Bereich, historie_schuljahr_id: int | None) -> list[Klasse]` — kapselt "welche Klassen gehören zu diesem Bereich" für beide Modi. Normalmodus (`historie_schuljahr_id is None`): unverändert über `bereich_klasse`. Historie-Modus: `Klasse.schuljahr_id == historie_schuljahr_id AND Klasse.abteilung_id == bereich.abteilung_id`; `bereich.abteilung_id is None` liefert sofort `[]` (siehe Abweichung 5).
- `_stats_for_bereich`/`_stats_schulweit`/`_stats_eigene_bereiche` nutzen `_bereich_klassen` statt der bisherigen drei separaten `bereich_klasse`-Abfragen.

- [x] **Step 1: Fehlschlagende Tests in `test_dashboard_query.py` schreiben**

```python
@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_historie_mode_groups_by_abteilung_not_bereich_klasse(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    from app.models.abteilung import Abteilung

    abteilung = Abteilung(webuntis_id=1, name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik", abteilung_id=abteilung.id)
    db_session.add(bereich)
    await db_session.flush()
    # historische Klasse ist NICHT in bereich_klasse eingetragen (die Tabelle spiegelt nur die
    # aktuelle Struktur) -- die Zuordnung muss ausschliesslich ueber abteilung_id funktionieren.
    klasse_historisch = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id, abteilung_id=abteilung.id)
    db_session.add(klasse_historisch)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_historisch.id)
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=date(2024, 10, 1), start_zeit=0, end_zeit=2359)
    )
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None, schuljahr_alt.id)

    vergleich_by_name = {v.name: v for v in stats.vergleich}
    assert vergleich_by_name["Mechatronik"].anzahl_schueler == 1
    assert vergleich_by_name["Mechatronik"].avg_fehltage == 1.0


@pytest.mark.asyncio
async def test_get_dashboard_stats_schulweit_historie_mode_bereich_without_abteilung_id_is_empty(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    bereich_ohne_abteilung = Bereich(name="Ohne Abteilung", abteilung_id=None)
    db_session.add(bereich_ohne_abteilung)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, None, None, schuljahr_alt.id)

    vergleich_by_name = {v.name: v for v in stats.vergleich}
    assert vergleich_by_name["Ohne Abteilung"].anzahl_schueler == 0


@pytest.mark.asyncio
async def test_stats_for_bereich_historie_mode_uses_klasse_abteilung_id(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    from app.models.abteilung import Abteilung

    abteilung = Abteilung(webuntis_id=1, name="Mechatronik")
    db_session.add(abteilung)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik", abteilung_id=abteilung.id)
    db_session.add(bereich)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id, abteilung_id=abteilung.id)
    db_session.add(klasse)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    stats = await dashboard_query.get_dashboard_stats(db_session, nutzer, bereich.id, None, schuljahr_alt.id)

    assert stats.level == "bereich"
    assert [v.name for v in stats.vergleich] == ["10a"]
```

Ergänze den Import `from app.models.abteilung import Abteilung` am Datei-Kopf von `test_dashboard_query.py` (statt der Inline-Imports oben — Konvention der Datei, siehe bereits vorhandene Imports).

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -k "historie_mode_groups_by_abteilung or historie_mode_bereich_without_abteilung or historie_mode_uses_klasse_abteilung" -v`
Expected: FAIL — `Mechatronik` fehlt in `vergleich` bzw. hat `anzahl_schueler == 0` (die Klassenauflösung läuft noch über `bereich_klasse`, das für die historische Klasse leer ist).

- [x] **Step 3: `_bereich_klassen`-Helfer einführen, `_stats_*` umstellen**

In `backend/app/services/dashboard_query.py`, füge vor `_stats_for_bereich` ein:

```python
async def _bereich_klassen(db: AsyncSession, bereich: Bereich, historie_schuljahr_id: int | None) -> list[Klasse]:
    """Klassen eines Bereichs fuer die Vergleichsbalken. Im Normalmodus ueber die (nicht
    jahresgebundene) bereich_klasse-Zuordnungstabelle -- unveraendert seit Plan 12. Im
    Historie-Modus stattdessen ueber klasse.abteilung_id == bereich.abteilung_id (Bundle D:
    Bereiche sind strukturell 1:1 aus WebUntis-Abteilungen abgeleitet, diese Zuordnung ist nicht
    jahresabhaengig, bereich_klasse selbst spiegelt dagegen immer nur die aktuelle Struktur), siehe
    docs/superpowers/specs/2026-09-22-dashboard-stats-schuljahr-design.md. Ein Bereich ohne
    abteilung_id liefert bewusst eine leere Liste statt eines IS-NULL-Vergleichs, der faelschlich
    alle Klassen OHNE abteilung_id treffen wuerde (siehe Wichtige Abweichungen im Plan)."""
    if historie_schuljahr_id is None:
        result = await db.execute(
            select(Klasse)
            .join(bereich_klasse, bereich_klasse.c.klasse_id == Klasse.id)
            .where(bereich_klasse.c.bereich_id == bereich.id)
            .order_by(Klasse.name)
        )
        return list(result.scalars().all())
    if bereich.abteilung_id is None:
        return []
    result = await db.execute(
        select(Klasse)
        .where(Klasse.schuljahr_id == historie_schuljahr_id, Klasse.abteilung_id == bereich.abteilung_id)
        .order_by(Klasse.name)
    )
    return list(result.scalars().all())
```

Ersetze in `_stats_for_bereich` den bisherigen `klassen = (await db.execute(select(Klasse).join(bereich_klasse, ...)...)).scalars().all()`-Block durch:

```python
    klassen = await _bereich_klassen(db, bereich, historie_schuljahr_id)
```

Ersetze in `_stats_schulweit` und `_stats_eigene_bereiche` jeweils den Block

```python
        klasse_ids = (
            await db.execute(select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich.id))
        ).scalars().all()
```

durch:

```python
        klassen = await _bereich_klassen(db, bereich, historie_schuljahr_id)
        klasse_ids = [k.id for k in klassen]
```

(in `_stats_eigene_bereiche` bleibt die nachfolgende Zeile `alle_klasse_ids.extend(klasse_ids)` unverändert — `klasse_ids` ist weiterhin eine `list[int]`.)

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -v`
Expected: alle Tests PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "feat: derive historical Bereich->Klassen grouping from abteilung_id instead of bereich_klasse"
```

---

## Task 4: `GET /dashboard/stats` — `schuljahr_id`-Query-Param

**Files:**
- Modify: `backend/app/api/routes/dashboard.py`
- Modify: `backend/tests/test_api_dashboard.py`

**Interfaces:**
- `GET /dashboard/stats` akzeptiert einen zusätzlichen optionalen Query-Param `schuljahr_id: int | None`, durchgereicht an `dashboard_query.get_dashboard_stats(db, nutzer, bereich_id, klasse_id, schuljahr_id)`.

- [x] **Step 1: Fehlschlagenden Route-Test schreiben**

Füge in `backend/tests/test_api_dashboard.py` nach `test_get_stats_returns_klasse_level_for_own_klasse` an:

```python
from datetime import date

from app.models.schueler import Schueler
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.models.schuljahr import Schuljahr


@pytest.mark.asyncio
async def test_get_stats_accepts_schuljahr_id_and_scopes_to_historical_roster(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    klasse_neu = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_neu.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add_all(
        [
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_alt.id, quelle="webuntis_seed"),
            NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse_neu.id, quelle="webuntis_seed"),
        ]
    )
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_neu.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse_alt.id)
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/dashboard/stats", params={"schuljahr_id": schuljahr_alt.id}, headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 200
    body = response.json()
    assert body["context"]["klasse_id"] == klasse_alt.id
    assert body["own"]["anzahl_schueler"] == 1


@pytest.mark.asyncio
async def test_get_stats_schuljahr_id_for_aktuelles_schuljahr_behaves_like_omitted(db_session, schuljahr):
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr.id))
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="klassenlehrkraft")
    db_session.add(nutzer)
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ohne_param = await client.get("/dashboard/stats", headers=HEADERS_KLASSENLEHRKRAFT)
        mit_aktuellem_param = await client.get(
            "/dashboard/stats", params={"schuljahr_id": schuljahr.id}, headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert ohne_param.json() == mit_aktuellem_param.json()
```

(Ergänze die dafür nötigen Imports `Einstellung` in `test_api_dashboard.py`, falls noch nicht vorhanden.)

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_dashboard.py -k schuljahr_id -v`
Expected: FAIL — `422 Unprocessable Entity` (unbekannter Query-Param `schuljahr_id` wird von FastAPI zwar toleriert, aber `get_dashboard_stats` erhält ihn nicht, Response liefert weiterhin den kompletten Live-Roster statt des historischen).

- [x] **Step 3: Route anpassen**

In `backend/app/api/routes/dashboard.py`, ändere `get_stats`:

```python
@router.get("/stats")
async def get_stats(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    bereich_id: int | None = None,
    klasse_id: int | None = None,
    schuljahr_id: int | None = None,
) -> StatsOut:
    return await dashboard_query.get_dashboard_stats(db, nutzer, bereich_id, klasse_id, schuljahr_id)
```

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_dashboard.py -v`
Expected: alle Tests PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/api/routes/dashboard.py backend/tests/test_api_dashboard.py
git commit -m "feat: accept schuljahr_id on GET /dashboard/stats"
```

---

## Task 5: `get_nav_options` — Schuljahr-Dropdown auf Jahre mit Historie-Daten (plus aktuelles Jahr) filtern

**Files:**
- Modify: `backend/app/services/dashboard_query.py`
- Modify: `backend/tests/test_dashboard_query.py`

**Interfaces:**
- `get_nav_options` filtert `schuljahre` so, dass ein Schuljahr nur enthalten ist, wenn `schuljahr.id == aktuelles_schuljahr_id` **oder** mindestens eine `schueler_klasse_historie`-Zeile mit diesem `schuljahr_id` existiert (per `EXISTS`/`IN`-Subquery).

- [ ] **Step 1: Fehlschlagende Tests in `test_dashboard_query.py` schreiben**

```python
@pytest.mark.asyncio
async def test_get_nav_options_excludes_schuljahr_without_historie_rows(db_session):
    schuljahr_ohne_daten = Schuljahr(id=20, name="2017/2018", start_datum=date(2017, 9, 11), end_datum=date(2018, 7, 27))
    db_session.add(schuljahr_ohne_daten)
    await db_session.commit()
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert schuljahr_ohne_daten.id not in {s.id for s in result.schuljahre}


@pytest.mark.asyncio
async def test_get_nav_options_includes_schuljahr_with_at_least_one_historie_row(db_session):
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr_alt)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr_alt.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_alt.id, klasse_id=klasse.id)
    )
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert schuljahr_alt.id in {s.id for s in result.schuljahre}


@pytest.mark.asyncio
async def test_get_nav_options_always_includes_aktuelles_schuljahr_even_without_historie_rows(db_session):
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add(schuljahr_neu)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    await db_session.commit()
    # keine schueler_klasse_historie-Zeile fuer schuljahr_neu -- z.B. direkt nach einem Rollover.

    result = await dashboard_query.get_nav_options(db_session, nutzer)

    assert schuljahr_neu.id in {s.id for s in result.schuljahre}
```

- [ ] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -k "excludes_schuljahr_without_historie or includes_schuljahr_with_at_least_one_historie" -v`
Expected: FAIL — `test_get_nav_options_excludes_schuljahr_without_historie_rows` schlägt fehl (`schuljahr_ohne_daten.id` ist noch in der Liste, da bisher ungefiltert). Der dritte neue Test (`always_includes_aktuelles_schuljahr`) sollte bereits vor der Implementierung PASS sein (reiner Regressionsschutz).

- [ ] **Step 3: Filter implementieren**

In `backend/app/services/dashboard_query.py`, ergänze den Import `or_`:

```python
from sqlalchemy import func, or_, select
```

Ändere in `get_nav_options` den `schuljahre`-Block:

```python
    historie_schuljahr_ids = select(SchuelerKlasseHistorie.schuljahr_id).distinct()
    schuljahre_query = select(Schuljahr).order_by(Schuljahr.start_datum.desc())
    if aktuelles_schuljahr_id is not None:
        schuljahre_query = schuljahre_query.where(
            or_(Schuljahr.id == aktuelles_schuljahr_id, Schuljahr.id.in_(historie_schuljahr_ids))
        )
    else:
        schuljahre_query = schuljahre_query.where(Schuljahr.id.in_(historie_schuljahr_ids))
    schuljahre_result = await db.execute(schuljahre_query)
    schuljahre = [
        NavSchuljahrOut(id=s.id, name=s.name, start_datum=s.start_datum, end_datum=s.end_datum)
        for s in schuljahre_result.scalars().all()
    ]
```

(ersetzt die bisherige, ungefilterte `schuljahre_result = await db.execute(select(Schuljahr).order_by(Schuljahr.start_datum.desc()))`.)

- [ ] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_dashboard_query.py -v`
Expected: alle Tests PASS. Insbesondere die bestehenden `test_get_nav_options_includes_schuljahre_newest_first` und `test_get_nav_options_includes_aktuelles_schuljahr_id_when_set` bleiben grün — prüfe hier zusätzlich manuell, dass diese beiden bestehenden Tests entweder bereits eine `aktuelles_schuljahr_id`/passende `Einstellung`-Zeile setzen oder (falls nicht) um eine `SchuelerKlasseHistorie`-Zeile ergänzt werden müssen, damit ihre Schuljahre nach dem neuen Filter weiterhin auftauchen — beide Tests seeden aktuell **keine** Einstellung/Historie-Zeile und würden nach diesem Fix mit einer leeren `schuljahre`-Liste fehlschlagen. Ergänze in `test_get_nav_options_includes_schuljahre_newest_first` (Zeile 96-110) für beide Schuljahre je eine `SchuelerKlasseHistorie`-Zeile (mit einem beliebigen Dummy-Schüler), damit der Test weiterhin die Sortierreihenfolge prüft, ohne den neuen Filter zu unterlaufen.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/dashboard_query.py backend/tests/test_dashboard_query.py
git commit -m "fix: exclude schuljahre without any schueler_klasse_historie data from the dropdown"
```

---

## Task 6: Frontend — `schuljahr`-URL-Parameter bis zur Landing-Page durchreichen

**Files:**
- Modify: `frontend/src/api/hooks/useStats.ts`
- Create: `frontend/src/api/hooks/useStats.test.tsx`
- Modify: `frontend/src/pages/Landing/Landing.tsx`
- Modify: `frontend/src/pages/Landing/Landing.test.tsx`

**Interfaces:**
- `useStats(bereichId: number | null, klasseId: number | null, schuljahrId: number | null)` — drittes Argument neu, analog zum bereits bestehenden `schuljahrId`-Feld in `StudentListParams` (`useStudents.ts`). Setzt `schuljahr_id` als Query-Param, wenn nicht `null`.

- [ ] **Step 1: Fehlschlagende Tests schreiben**

Neue Datei `frontend/src/api/hooks/useStats.test.tsx` (Muster: `useStudents.test.tsx`):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import * as client from "../client";
import { useStats } from "./useStats";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useStats", () => {
  it("builds the query string from bereichId/klasseId", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(3, null, null), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats?bereich_id=3");
  });

  it("omits unset filters", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(null, null, null), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats");
  });

  it("includes schuljahr_id in the query string when set", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(null, null, 27), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats?schuljahr_id=27");
  });

  it("combines bereichId, klasseId and schuljahrId", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue({});

    const { result } = renderHook(() => useStats(3, 5, 27), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(spy).toHaveBeenCalledWith("dashboard/stats?bereich_id=3&klasse_id=5&schuljahr_id=27");
  });
});
```

Ergänze in `frontend/src/pages/Landing/Landing.test.tsx` (nach dem letzten bestehenden Test, Muster: `StudentList.test.tsx`s `"reads schuljahr from the URL and passes it to useStudents"`):

```tsx
  it("reads schuljahr from the URL and passes it to useStats", () => {
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

    render(
      <MemoryRouter initialEntries={["/?schuljahr=27"]}>
        <Landing />
      </MemoryRouter>,
    );

    expect(mockUseStats).toHaveBeenLastCalledWith(null, null, 27);
  });
```

- [ ] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `cd frontend && npx vitest run src/api/hooks/useStats.test.tsx src/pages/Landing/Landing.test.tsx`
Expected: FAIL — `useStats` akzeptiert noch kein drittes Argument (TypeScript-Kompilierfehler bzw. der neue Landing-Test scheitert, weil `mockUseStats` weiterhin nur mit zwei Argumenten aufgerufen wird).

- [ ] **Step 3: `useStats` und `Landing.tsx` anpassen**

`frontend/src/api/hooks/useStats.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../client";
import type { Stats } from "../types";

export function useStats(bereichId: number | null, klasseId: number | null, schuljahrId: number | null) {
  const params = new URLSearchParams();
  if (bereichId !== null) params.set("bereich_id", String(bereichId));
  if (klasseId !== null) params.set("klasse_id", String(klasseId));
  if (schuljahrId !== null) params.set("schuljahr_id", String(schuljahrId));
  const query = params.toString();

  return useQuery({
    queryKey: ["dashboard-stats", bereichId, klasseId, schuljahrId],
    queryFn: () => apiGet<Stats>(`dashboard/stats${query ? `?${query}` : ""}`),
  });
}
```

`frontend/src/pages/Landing/Landing.tsx`, ergänze nach `const klasseId = ...`:

```tsx
  const schuljahrParam = searchParams.get("schuljahr");
  const schuljahrId = schuljahrParam ? Number(schuljahrParam) : null;

  const { data, isLoading, isError } = useStats(bereichId, klasseId, schuljahrId);
```

(ersetzt die bisherige `useStats(bereichId, klasseId)`-Zeile.)

- [ ] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `cd frontend && npx vitest run src/api/hooks/useStats.test.tsx src/pages/Landing/Landing.test.tsx`
Expected: alle Tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/hooks/useStats.ts frontend/src/api/hooks/useStats.test.tsx \
  frontend/src/pages/Landing/Landing.tsx frontend/src/pages/Landing/Landing.test.tsx
git commit -m "feat: pass the schuljahr URL param through to GET /dashboard/stats"
```

---

## Task 7: Vollständiger Testlauf + Dokumentation

**Files:**
- Modify: `ROADMAP.md`
- Modify: `TECH-SPEC.md`
- Modify: `SPECS.md`

- [ ] **Step 1: Vollen Backend-Testlauf**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [ ] **Step 2: Vollen Frontend-Testlauf**

Run: `cd frontend && npm test`
Expected: alle Tests PASS.

- [ ] **Step 3: Manuelle Verifikation im Dev-Stack (optional, empfohlen)**

- Landing-Page mit einem vergangenen Schuljahr im Dropdown aufrufen und prüfen, dass sich die Ø-Werte/Balken tatsächlich ändern (nicht mehr identisch zum aktuellen Schuljahr).
- Ein Schuljahr ganz ohne `schueler_klasse_historie`-Daten aus WebUntis anlegen (lassen) und prüfen, dass es NICHT im Schuljahr-Dropdown erscheint, das aktuelle Schuljahr aber immer.
- Für einen Bereich mit historischen Klassen (per rückwirkendem Import aus Plan 17 befüllt) prüfen, dass die Vergleichsbalken im Historie-Modus sinnvolle, von 0 verschiedene Werte zeigen.

- [ ] **Step 4: Commit (falls Step 1-3 Anpassungen erfordern)**

```bash
git add -A
git commit -m "fix: address issues found during full-suite/manual verification"
```

- [ ] **Step 5: TECH-SPEC.md aktualisieren**

- §1.3a oder §3 (API-Vertrag): ergänze einen Absatz analog zu den bestehenden "Ergänzung (Plan 16/...)"-Blöcken (Zeilen 181-185): `GET /dashboard/stats` akzeptiert seit diesem Plan zusätzlich einen optionalen Query-Param `schuljahr_id` (wie `GET /students`) — im Historie-Modus wird die Schülerbasis für die Ø-Werte aus `schueler_klasse_historie` ermittelt (statt der live `schueler`-Tabelle) und die Vergleichsbalken je Bereich gruppieren historische Klassen über `klasse.abteilung_id == bereich.abteilung_id` statt der (nicht jahresgebundenen) `bereich_klasse`-Tabelle. Erwähne, dass `GET /dashboard/nav-options`s `schuljahre`-Liste seither zusätzlich Schuljahre ohne jede `schueler_klasse_historie`-Zeile ausblendet (außer dem aktuellen Schuljahr).
- §2 (Datenbank-Schema): kein neues Feld/keine neue Tabelle (keine Schema-Änderung durch diesen Plan).

- [ ] **Step 6: SPECS.md aktualisieren**

- §7 (Dashboard-Funktionen): ergänze bei der Beschreibung des Schuljahr-Dropdowns/Historie-Modus (nach dem bestehenden Absatz zu "Wer im Historie-Modus überhaupt erscheint", Zeile 81), dass seit diesem Plan auch die Landing-Page-Kennzahlen (Ø Fehltage/-stunden/Klassenbuch, Maßnahmen-Anzahl, Vergleichsbalken) dem gewählten Schuljahr folgen — inkl. der Vergleichsbalken je Bereich, deren Klassenzuordnung im Historie-Modus über die WebUntis-Abteilung statt der aktuellen Bereichs-Struktur ermittelt wird. Ergänze, dass das Schuljahr-Dropdown nur Jahre mit tatsächlichen Historie-Daten (plus das aktuelle Schuljahr) zeigt.

- [ ] **Step 7: ROADMAP.md aktualisieren**

Trage den Eintrag "Dashboard-Statistiken schuljahresbewusst + Dropdown-Filter" als **Plan 18** unter "Abgeschlossen" ein (nächste freie Nummer nach Plan 17), mit Link auf diesen Plan (`docs/superpowers/plans/2026-09-22-dashboard-stats-schuljahr.md`) und dessen [Design-Dok](../specs/2026-09-22-dashboard-stats-schuljahr-design.md). Ersetze den bisherigen "Design-Dok fertig, Umsetzungsplan offen"-Eintrag unter "Geplant" (aktuell Zeile 64 in `ROADMAP.md`) durch einen Verweis auf den jetzt abgeschlossenen Plan 18. Erwähne die während der Planung entdeckte Konsolidierung des `bereich_klasse`-Lookups in den gemeinsamen `_bereich_klassen`-Helfer (nicht im Design-Dok vorgesehen, aber eine naheliegende, risikoarme Code-Struktur-Verbesserung, analog zu Plan 16/17s jeweiligen "zusätzlich entdeckt"-Funden).

- [ ] **Step 8: Commit**

```bash
git add ROADMAP.md SPECS.md TECH-SPEC.md
git commit -m "docs: sync SPECS.md, TECH-SPEC.md and ROADMAP.md with the dashboard-stats-schuljahr plan"
```
