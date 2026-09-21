# Rückwirkendes Schuljahr-Archiv, Roster-Filterung & CSV-Archivierung — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drei zusammenhängende Nachträge zu Plan 16 (`docs/superpowers/plans/2026-09-18-schuljahr-historisierung.md`, bereits deployed):

1. **Bugfix:** `GET /students`/`GET /students/{id}` im Historie-Modus filtern bisher nur, *welche Klasse* je Schüler angezeigt wird — nicht *welche Schüler* überhaupt gelistet werden bzw. ob der angefragte Schüler in diesem Schuljahr überhaupt eingeschrieben war. Beide Endpunkte werden auf `schueler_klasse_historie`-Mitgliedschaft umgestellt.
2. **Rückwirkendes Backfill:** neuer Admin-Import-Flow (Vorschau + Bestätigung), um archivierte ASV-BW-CSVs vergangener Schuljahre nachträglich in `schueler_klasse_historie` einzuspielen, inkl. automatischem `getKlassen`-Nachzug fehlender jahresgebundener `klasse`-Zeilen.
3. **Vorsorge:** laufende ASV-CSV-Archivierung (ein Stand pro Schuljahr, bei jedem tatsächlich verarbeiteten Live-Import aktualisiert), damit dieselbe Lücke bei künftigen Schuljahreswechseln nicht wieder entsteht.

**Architecture:** Keine neuen Tabellen/Spalten — alle drei Punkte sind Query-Logik-Fixes bzw. neue Endpunkte/Settings auf dem bestehenden Plan-16-Schema (`klasse.schuljahr_id`, `schueler_klasse_historie`). (1) `student_query.list_students` bekommt einen neuen `historie_schuljahr_id`-Parameter, der die Roster-Basis von `schueler` auf einen INNER JOIN mit `schueler_klasse_historie` umschaltet; `GET /students/{id}` bekommt einen neuen Existenz-Check gegen `schueler_klasse_historie`, der bei fehlender Zeile 404 statt eines Klassen-Fallbacks liefert. (2) Ein neuer Service `schuljahr_historie_import_service.py` mit zwei Admin-Endpunkten (`POST /admin/schuljahr-historie-import/preview`, `POST /admin/schuljahr-historie-import`), der eine aus `asv_csv_import.py` extrahierte gemeinsame CSV-Lese-Funktion wiederverwendet und `sync_klassen` (Plan 16) für den WebUntis-Klassen-Nachzug direkt aufruft. (3) `ASV_CSV_ARCHIVE_DIR`-Setting + neues Docker-Volume + eine Kopier-Funktion, die `import_schueler` bei jedem tatsächlich verarbeiteten Lauf aufruft.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Alembic / pytest (backend, `backend/`); React 18 / TypeScript / Vitest (frontend, `frontend/`).

**Referenz:** [Design-Dokument](../specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md) — direkter Nachtrag zu [Plan 16](2026-09-18-schuljahr-historisierung.md) ([Design-Dok](../specs/2026-09-18-schuljahr-historisierung-design.md)).

## Wichtige Abweichungen vom Design-Dok (beim Schreiben dieses Plans festgestellt)

Der Code wurde gegen den tatsächlichen Stand nach Plan 16 verifiziert (nicht nur gegen dessen Plandokument). Folgende Punkte sind beim Schreiben dieses Plans aufgefallen und nicht im Design-Dok explizit vorweggenommen:

1. **Aktueller Stand von `GET /students`/`GET /students/{id}` (Plan 16, Tasks 8/9) ist bestätigt wie im Design-Dok beschrieben** (`backend/app/api/routes/students.py`): `_resolve_schuljahr_zeitraum`/`ist_historie` bestimmen den Modus; im Historie-Modus ruft `get_students` `student_query.list_students(..., nur_aktive=False, ...)` auf — das swappt nur `nur_aktive`, filtert aber weiterhin über `Schueler.klasse_id`/Scope auf der LIVE-Klasse, nicht über `schueler_klasse_historie`. `get_student_detail` liest die Klasse im Historie-Modus zwar bereits aus `student_query.load_historische_klasse_map`, hat aber keinerlei Existenz-Check — fehlt die Zeile, liefert die Route `klasse=None` mit Status 200 statt 404.
2. **`load_historische_klasse_map` kann "keine Zeile" nicht von "Zeile mit `klasse_id=NULL`" unterscheiden** (`backend/app/services/student_query.py:135-160`, absichtlich so gebaut in Plan 16 — beides soll "unbekannt" anzeigen). Für den neuen 404-Fix in `GET /students/{id}` reicht diese Funktion nicht: es braucht einen separaten Existenz-Check (`SchuelerKlasseHistorie`-Zeile vorhanden ja/nein), unabhängig vom `klasse_id`-Wert. Task 2 führt dafür eine neue Funktion `student_hat_historie_eintrag` ein, statt die bestehende Funktion umzubauen (die für `GET /students`' Klassen-Anzeige weiterhin unverändert gebraucht wird).
3. **Der Roster-Fix lässt sich nicht allein in `students.py` erledigen** — `klasse_id`/`bereich_id`-Query-Parameter und der `scope`-Klassenfilter werden aktuell in `student_query.list_students` gegen `Schueler.klasse_id` aufgelöst (Zeilen 57-66). Der Fix braucht einen neuen `historie_schuljahr_id`-Parameter direkt in `list_students`, der diese drei Filter (und den `sort_by="klasse"`-Join) auf `SchuelerKlasseHistorie.klasse_id` statt `Schueler.klasse_id` umschaltet, plus den neuen INNER JOIN als Basis von `count_query`/`query`. Task 1 baut das direkt in `list_students`, nicht als Wrapper-Funktion daneben.
4. **`resolve_scope` liefert bereits jahresübergreifend gültige `klasse_id`-Werte** — wichtig für die Korrektheit des Fixes: `NutzerKlasse.klasse_id` wird laut Plan-16-"Wichtige Abweichungen" Punkt 5 von `seed_nutzer_klasse_from_webuntis` bei **jedem** Sync-Lauf für **alle** (auch alte, nie gelöschte) `klasse`-Zeilen mit passender `webuntis_teacher_id` neu geseedet — der `scope`-Set einer Klassenlehrkraft enthält also (sofern seit Plan 16 mindestens ein Sync mit dieser Klasse gelaufen ist) auch historische `klasse.id`-Werte. Der neue `historie_schuljahr_id`-Filter kann den `scope`-Set deshalb unverändert direkt gegen `SchuelerKlasseHistorie.klasse_id` matchen, ohne eine gesonderte "historische Scope-Auflösung" zu bauen — das ist kein Bug, sondern der Grund, warum dieser einfache Ansatz überhaupt korrekt ist.
5. **Drei bestehende Tests widersprechen nach diesem Fix der neuen Spezifikation und müssen ersetzt/erweitert werden, nicht nur ergänzt** (`backend/tests/test_api_students.py`):
   - `test_get_students_history_mode_returns_rohzahlen_and_includes_inactive` (Zeile 551) legt für seine zwei Schüler **keine** `SchuelerKlasseHistorie`-Zeile an und erwartet trotzdem, dass beide in der Liste erscheinen — nach dem Fix muss der Test zwei `SchuelerKlasseHistorie`-Zeilen für das betrachtete Schuljahr ergänzen, sonst schlägt er (korrekterweise) fehl.
   - `test_get_student_detail_history_mode_filters_four_sections_not_massnahmen` (Zeile 675) legt für seinen Schüler ebenfalls keine `SchuelerKlasseHistorie`-Zeile für `schuljahr` (id 27) an — nach dem 404-Fix (Task 2) würde dieser Test von 200 auf 404 kippen, obwohl er eigentlich das Rohzahlen-Filtering testen will. Braucht eine ergänzte `SchuelerKlasseHistorie`-Zeile.
   - `test_get_student_detail_history_mode_klasse_is_none_without_historie_snapshot` (Zeile 782) testet explizit die ALTE, jetzt bewusst geänderte Spezifikation ("kein Snapshot → `klasse=None`, Status 200"). Dieser Test wird durch einen neuen Test ersetzt, der 404 erwartet (siehe Design-Dok Abschnitt 1: "liefert die Route `404`... statt stillschweigend die aktuelle Klasse als Fallback zu zeigen").
6. **`Schuljahr.name` enthält ein `/`** (z.B. `"2025/2026"`, siehe `backend/app/models/schuljahr.py`) — die Design-Dok-Formulierung "`<ASV_CSV_ARCHIVE_DIR>/<schuljahr.name>.csv`" wörtlich umgesetzt würde auf Linux einen Pfad `<...>/2025/2026.csv` erzeugen (Unterverzeichnis `2025/` statt einer Datei `2025-2026.csv`) — ein durch das Design-Dok nicht bedachter Stolperstein. Task 3 sanitiert den Dateinamen (`schuljahr.name.replace("/", "-")` → `2025-2026.csv`), funktional identisch zur Design-Dok-Absicht ("eine Datei pro Schuljahr").
7. **Kein bestehendes Datei-Upload-Muster im Frontend** — `frontend/src/api/client.ts` hat `apiGet`/`apiPost`/`apiPut`/`apiDelete`/`apiDownload` (Downloads, kein Upload); der PDF-Export (`GET /students/{id}/export.pdf`) ist ein reiner Download, kein Vorbild für Multipart-Upload. Task 6 ergänzt `client.ts` um eine neue `apiPostFormData`-Funktion (kein `Content-Type`-Header setzen — der Browser generiert die Multipart-Boundary selbst).
8. **Alembic-Head unverändert bei `e3735eedca38`** (`backend/alembic/versions/e3735eedca38_add_schueler_klasse_historie_table.py`, letzte Migration aus Plan 16) — verifiziert per `python -m alembic heads` und Abgleich aller in diesem Plan berührten Modelle (`Klasse`, `Schueler`, `SchuelerKlasseHistorie`, `Schuljahr`, `Einstellung`): keiner der drei Design-Dok-Punkte braucht eine neue Spalte/Tabelle/Index. **Dieser Plan enthält keine Alembic-Migration.**
9. **Zwei-Schritt-Vorschau/Bestätigung ohne Server-seitige Datei-Staging:** das Design-Dok legt nicht fest, ob der Bestätigen-Request die Datei erneut mitschickt oder einen serverseitig zwischengespeicherten Upload referenziert. Dieser Plan entscheidet sich für **zustandslose, unabhängige Requests** (Datei wird bei Vorschau UND Bestätigung jeweils mitgeschickt, im Frontend als dieselbe `File`-Objekt-Referenz im Component-State gehalten) — vermeidet Session-/Temp-Datei-Aufräum-Komplexität auf dem Server, der Design-Dok-Ablauf ("Vorschau vor dem Bestätigen") bleibt für die Nutzerin unverändert erlebbar.

## Global Constraints

- **Nicht-Ziele (Design-Dok, hier bewusst wiederholt, damit Implementierer nicht scope-creepen):**
  - Keine automatische Erkennung/Vorschlagsliste verfügbarer Archiv-CSVs — der Admin lädt die Datei jedes Mal explizit hoch.
  - Keine unterjährige Granularität beim historischen Import — weiterhin ein Snapshot pro Schuljahr.
  - Kein automatisches Backfill ohne Nutzerinteraktion — auch wenn eine archivierte CSV im Archiv-Ordner liegt, wird sie nicht automatisch verarbeitet.
  - Keine Änderung an der Berechnung der Rohzahlen (Fehltage/-stunden/Klassenbuch) — bleiben rein datumsbasiert, unabhängig vom Klassen-Snapshot.
  - Keine rückwirkende Korrektur von `schueler.klasse_id`/`aktiv`/`vorname`/`nachname` für vergangene Zustände — diese Felder bleiben ausschließlich "aktueller Stand". Der historische Import darf für **bestehende** `schueler`-Zeilen ausschließlich `schueler_klasse_historie` schreiben. Nur für eine komplett unbekannte `externe_id` wird ein neuer, minimaler `Schueler`-Stammsatz angelegt (nur `externe_id`+Name; `klasse_id`/`aktiv` bleiben Spalten-Default, werden nicht gesetzt).
  - `massnahmen` bleiben in jedem Modus ungefiltert (unverändertes Verhalten seit Plan 13).
- **Keine neue Alembic-Migration** in diesem Plan (siehe Abweichung 8 oben) — Alembic-Head bleibt `e3735eedca38`.
- **Nur `schulleitung`** darf die neuen Admin-Import-Endpunkte aufrufen — via des bestehenden `dependencies=[Depends(require_schulleitung)]` auf dem `/admin`-Router (`backend/app/api/routes/admin.py:45`), identisch zu allen anderen Admin-Routen.
- Lokaler Dev-Stack läuft als Docker-Container: `absenzdash-backend` (Backend), `absenzdash-db` (Postgres). Migrationsbefehle entfallen in diesem Plan mangels neuer Migration; `docker compose`-Befehle werden nicht gegen eine echte/Prod-Umgebung ausgeführt.
- Commit-Messages auf Englisch (Projekt-Konvention).
- Nach Abschluss jedes Tasks committen; nach Abschluss des gesamten Plans `ROADMAP.md`/`TECH-SPEC.md`/`SPECS.md` aktualisieren (`CLAUDE.md`-Konvention, siehe Task 7).

---

## Task 1: `GET /students` — Roster-Filterung im Historie-Modus über `schueler_klasse_historie`

**Files:**
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/tests/test_student_query.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- `student_query.list_students(..., historie_schuljahr_id: int | None = None)` — neuer optionaler Parameter (Default `None` = unverändertes Normalmodus-Verhalten). Ist er gesetzt, wird die Roster-Basis ein INNER JOIN mit `schueler_klasse_historie` für dieses Schuljahr; `scope`/`klasse_id`/`bereich_id`-Filter (inkl. `sort_by="klasse"`) matchen dann gegen `SchuelerKlasseHistorie.klasse_id` statt `Schueler.klasse_id`.

- [x] **Step 1: Fehlschlagende Tests in `test_student_query.py` schreiben**

Füge in `backend/tests/test_student_query.py` nach `test_list_students_scopes_by_klasse_ids` (Zeile 28-40) folgende Tests ein:

```python
@pytest.mark.asyncio
async def test_list_students_historie_mode_includes_only_students_with_historie_row(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler_mit_historie = Schueler(externe_id="ext-mit", vorname="Mit", nachname="A", aktiv=False)
    schueler_ohne_historie = Schueler(externe_id="ext-ohne", vorname="Ohne", nachname="B", aktiv=True)
    db_session.add_all([schueler_mit_historie, schueler_ohne_historie])
    await db_session.flush()
    db_session.add(
        SchuelerKlasseHistorie(schueler_id=schueler_mit_historie.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id)
    )
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, historie_schuljahr_id=schuljahr.id)

    assert total == 1
    assert [s.id for s in items] == [schueler_mit_historie.id]  # inaktiv, erscheint trotzdem (Historie-Snapshot)


@pytest.mark.asyncio
async def test_list_students_historie_mode_empty_schuljahr_returns_empty(db_session, schuljahr):
    db_session.add(Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True))
    await db_session.commit()

    items, total = await student_query.list_students(db_session, scope=None, historie_schuljahr_id=999999)

    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_students_historie_mode_filters_by_klasse_id_via_historie_not_live_klasse_id(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse_a = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_b = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_a, klasse_b])
    await db_session.flush()
    # schueler ist LIVE in klasse_b, war historisch aber in klasse_a
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_b.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse_a.id))
    await db_session.commit()

    items, total = await student_query.list_students(
        db_session, scope=None, klasse_id=klasse_a.id, historie_schuljahr_id=schuljahr.id
    )
    assert total == 1
    assert [s.id for s in items] == [schueler.id]

    items_b, total_b = await student_query.list_students(
        db_session, scope=None, klasse_id=klasse_b.id, historie_schuljahr_id=schuljahr.id
    )
    assert total_b == 0  # klasse_b ist nur die LIVE-Klasse, nicht die historische -> kein Treffer


@pytest.mark.asyncio
async def test_list_students_historie_mode_filters_by_bereich_id_via_historie(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    bereich = Bereich(name="Mechatronik")
    db_session.add(bereich)
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id))
    await db_session.commit()

    items, total = await student_query.list_students(
        db_session, scope=None, bereich_id=bereich.id, historie_schuljahr_id=schuljahr.id
    )
    assert total == 1
    assert [s.id for s in items] == [schueler.id]


@pytest.mark.asyncio
async def test_list_students_historie_mode_scope_matches_historische_klasse_id(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse_im_scope = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_ausserhalb = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_im_scope, klasse_ausserhalb])
    await db_session.flush()
    schueler_im_scope = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    schueler_ausserhalb = Schueler(externe_id="ext-2", vorname="B", nachname="B", aktiv=True)
    db_session.add_all([schueler_im_scope, schueler_ausserhalb])
    await db_session.flush()
    db_session.add_all(
        [
            SchuelerKlasseHistorie(schueler_id=schueler_im_scope.id, schuljahr_id=schuljahr.id, klasse_id=klasse_im_scope.id),
            SchuelerKlasseHistorie(schueler_id=schueler_ausserhalb.id, schuljahr_id=schuljahr.id, klasse_id=klasse_ausserhalb.id),
        ]
    )
    await db_session.commit()

    items, total = await student_query.list_students(
        db_session, scope={klasse_im_scope.id}, historie_schuljahr_id=schuljahr.id
    )
    assert total == 1
    assert [s.id for s in items] == [schueler_im_scope.id]
```

Ergänze in `backend/tests/test_student_query.py` den Import `SchuelerKlasseHistorie` (bereits vorhanden, Zeile 20) — keine weiteren neuen Imports nötig (`Schuljahr`, `Bereich`, `bereich_klasse`, `Klasse` sind bereits importiert).

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_student_query.py -k historie_mode -v`
Expected: FAIL — `list_students()` akzeptiert `historie_schuljahr_id` noch nicht (`TypeError: unexpected keyword argument`).

- [x] **Step 3: `list_students` umbauen**

In `backend/app/services/student_query.py`, ändere die Signatur (Zeilen 33-48):

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
    historie_schuljahr_id: int | None = None,
) -> tuple[list[Schueler], int]:
    """Liefert die fuer den Scope sichtbaren Schueler (gefiltert, sortiert, paginiert) sowie
    die Gesamtzahl (nach Filtern, vor Pagination). von/bis grenzen den Zeitraum fuer die
    Fehltage/Fehlstunden/Einträge-Sortierung ein (None/None = unbegrenzt).

    historie_schuljahr_id (Default None) schaltet den Historie-Modus ein (siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md): die
    Roster-Basis wird dann ein INNER JOIN auf schueler_klasse_historie fuer dieses Schuljahr
    statt einer unscoped schueler-Abfrage mit nur_aktive=False -- nur Schueler MIT Snapshot fuer
    dieses Jahr erscheinen (ein Schuljahr ganz ohne Zeilen liefert dadurch automatisch eine leere
    Liste, kein Sonderfall noetig). scope/klasse_id/bereich_id filtern in diesem Modus konsequent
    gegen schueler_klasse_historie.klasse_id statt schueler.klasse_id. Der Aufrufer (students.py)
    neutralisiert weiterhin typ/min_stufe/nur_auffaellige/nur_aktive auf None/False, wenn
    historie_schuljahr_id gesetzt ist (Zaehlerstand/Benachrichtigungs-Filter sind im Historie-
    Modus nicht aussagekraeftig, siehe Plan 16)."""
```

Ändere den Filter-Aufbau (Zeilen 57-76):

```python
    klasse_id_col = SchuelerKlasseHistorie.klasse_id if historie_schuljahr_id is not None else Schueler.klasse_id

    conditions = []
    if nur_aktive:
        conditions.append(Schueler.aktiv.is_(True))
    if scope is not None:
        conditions.append(klasse_id_col.in_(scope))
    if klasse_id is not None:
        conditions.append(klasse_id_col == klasse_id)
    if bereich_id is not None:
        bereich_klassen = select(bereich_klasse.c.klasse_id).where(bereich_klasse.c.bereich_id == bereich_id)
        conditions.append(klasse_id_col.in_(bereich_klassen))

    if min_stufe is not None or nur_auffaellige:
        typen = [typ] if typ is not None else list(ZAEHLERSTAND_TYPEN)
        zaehlerstand_conditions = [SchuelerZaehlerstand.typ.in_(typen)]
        if min_stufe is not None:
            zaehlerstand_conditions.append(SchuelerZaehlerstand.erreichte_stufe_nr >= min_stufe)
        else:
            zaehlerstand_conditions.append(SchuelerZaehlerstand.erreichte_stufe_nr.is_not(None))
        matching_ids = select(SchuelerZaehlerstand.schueler_id).where(*zaehlerstand_conditions)
        conditions.append(Schueler.id.in_(matching_ids))

    def _mit_historie_join(stmt):
        if historie_schuljahr_id is None:
            return stmt
        return stmt.join(
            SchuelerKlasseHistorie,
            (SchuelerKlasseHistorie.schueler_id == Schueler.id)
            & (SchuelerKlasseHistorie.schuljahr_id == historie_schuljahr_id),
        )

    count_query = _mit_historie_join(select(func.count()).select_from(Schueler))
    query = _mit_historie_join(select(Schueler))
    for condition in conditions:
        count_query = count_query.where(condition)
        query = query.where(condition)

    total = (await db.execute(count_query)).scalar_one()
```

Ändere im `sort_by == "klasse"`-Zweig (Zeile 89-92) `Klasse.id == Schueler.klasse_id` zu `Klasse.id == klasse_id_col`:

```python
    elif sort_by == "klasse":
        query = query.outerjoin(Klasse, Klasse.id == klasse_id_col).order_by(
            richtung(Klasse.name), Schueler.nachname, Schueler.id
        )
```

(Die restlichen `sort_by`-Zweige — `klassenbuch_anzahl`/`fehltage`/`fehlstunden` — bleiben unverändert, sie sortieren bereits datumsbasiert über `Fehlzeit`/`KlassenbuchEintrag`, unabhängig von `klasse_id`.)

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_student_query.py -v`
Expected: alle Tests PASS (auch die bestehenden — `historie_schuljahr_id=None` reproduziert exakt das alte Verhalten, da `_mit_historie_join` dann ein No-Op ist und `klasse_id_col` auf `Schueler.klasse_id` zeigt).

- [x] **Step 5: `students.py` verdrahten + fehlschlagende Route-Tests schreiben/anpassen**

In `backend/app/api/routes/students.py`, ändere in `get_students` den `student_query.list_students`-Aufruf (Zeilen 104-119):

```python
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
        historie_schuljahr_id=schuljahr_id if ist_historie else None,
    )
```

In `backend/tests/test_api_students.py`:

**5a.** Ändere `test_get_students_history_mode_returns_rohzahlen_and_includes_inactive` (Zeile 551-581) — ergänze nach dem Anlegen von `schueler_aktiv`/`schueler_inaktiv` (nach Zeile 563, vor der `Fehlzeit`-Zeile) zwei `SchuelerKlasseHistorie`-Zeilen:

```python
    db_session.add_all(
        [
            SchuelerKlasseHistorie(schueler_id=schueler_aktiv.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id),
            SchuelerKlasseHistorie(schueler_id=schueler_inaktiv.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id),
        ]
    )
```

**5b.** Füge nach diesem Test zwei neue Tests ein:

```python
@pytest.mark.asyncio
async def test_get_students_history_mode_excludes_students_without_historie_row(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse.id])
    # Schueler ist heute (live) aktiv in dieser Klasse, war es aber im betrachteten Schuljahr
    # nachweislich nicht (keine schueler_klasse_historie-Zeile) -- z.B. erst spaeter eingeschult.
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse.id, aktiv=True)
    db_session.add(schueler)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/students?schuljahr_id={schuljahr.id}", headers=HEADERS_KLASSENLEHRKRAFT)

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_get_students_history_mode_returns_empty_for_schuljahr_without_any_historie(db_session):
    """Ein Schuljahr vor Einfuehrung dieses Features (oder vor einem rueckwirkenden Import)
    hat ueberhaupt keine schueler_klasse_historie-Zeilen -- liefert dadurch automatisch eine
    leere Liste, kein Sonderfall noetig (Design-Dok Abschnitt 1)."""
    schuljahr = Schuljahr(id=20, name="2017/2018", start_datum=date(2017, 9, 11), end_datum=date(2018, 7, 27))
    db_session.add(schuljahr)
    await db_session.flush()
    nutzer = Nutzer(wp_user_id="jseyfried", email="a@b.de", name="A", rolle="schulleitung")
    db_session.add(nutzer)
    db_session.add(Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students?schuljahr_id={schuljahr.id}",
            headers={**HEADERS_KLASSENLEHRKRAFT, "X-WordPress-Role": "schulleitung"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_get_students_history_mode_klasse_id_filter_uses_historische_klasse(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    klasse_alt = Klasse(webuntis_id=1, name="10a", schuljahr_id=schuljahr.id)
    klasse_live = Klasse(webuntis_id=2, name="10b", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_alt, klasse_live])
    await db_session.flush()
    await _seed_klassenlehrkraft(db_session, [klasse_alt.id, klasse_live.id])
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", klasse_id=klasse_live.id, aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse_alt.id))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        treffer = await client.get(
            f"/students?schuljahr_id={schuljahr.id}&klasse_id={klasse_alt.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )
        kein_treffer = await client.get(
            f"/students?schuljahr_id={schuljahr.id}&klasse_id={klasse_live.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert [item["id"] for item in treffer.json()["items"]] == [schueler.id]
    assert kein_treffer.json()["items"] == []
```

Ergänze im Import-Block von `test_api_students.py` (Zeile 20-27, falls noch nicht vorhanden) `from app.models.bereich import Bereich, bereich_klasse` — bereits vorhanden (Zeile 13), keine Änderung nötig.

- [x] **Step 6: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -k "history_mode and (excludes_students or returns_empty_for_schuljahr or klasse_id_filter_uses_historische)" -v`
Expected: FAIL — die Route filtert noch über die live `Schueler.klasse_id` (kein `historie_schuljahr_id` durchgereicht), alle drei neuen Tests scheitern.

Run zusätzlich: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -k history_mode_returns_rohzahlen -v`
Expected (vor Step 5a): PASS zufällig weiterhin (der Test prüfte bisher nicht das Historie-Join-Verhalten) — nach Ergänzung der beiden `SchuelerKlasseHistorie`-Zeilen (Step 5a) bleibt er grün, ist jetzt aber tatsächlich aussagekräftig für den Fix.

- [x] **Step 7: `students.py`-Änderung anwenden (siehe Step 5, Code-Block oben), Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py tests/test_student_query.py -v`
Expected: alle Tests PASS.

- [x] **Step 8: Commit**

```bash
git add backend/app/services/student_query.py backend/app/api/routes/students.py \
  backend/tests/test_student_query.py backend/tests/test_api_students.py
git commit -m "fix: scope GET /students roster to schueler_klasse_historie membership in history mode"
```

---

## Task 2: `GET /students/{id}` — 404 bei fehlender Historie-Zeile

**Files:**
- Modify: `backend/app/services/student_query.py`
- Modify: `backend/app/api/routes/students.py`
- Modify: `backend/tests/test_student_query.py`
- Modify: `backend/tests/test_api_students.py`

**Interfaces:**
- Neu: `student_query.student_hat_historie_eintrag(db, schueler_id: int, schuljahr_id: int) -> bool` — True nur, wenn eine `schueler_klasse_historie`-Zeile existiert (unabhängig vom `klasse_id`-Wert, auch `klasse_id=NULL` zählt als "eingeschrieben, Klasse unbekannt").

- [x] **Step 1: Fehlschlagenden Test in `test_student_query.py` schreiben**

Füge nach `test_load_historische_klasse_map_none_when_historie_klasse_id_is_null` (letzter Test der Datei, Zeile 600) an:

```python
@pytest.mark.asyncio
async def test_student_hat_historie_eintrag_true_when_row_exists_even_with_null_klasse(db_session, schuljahr):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=None))
    await db_session.commit()

    assert await student_query.student_hat_historie_eintrag(db_session, schueler.id, schuljahr.id) is True


@pytest.mark.asyncio
async def test_student_hat_historie_eintrag_false_when_no_row(db_session, schuljahr):
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.commit()

    assert await student_query.student_hat_historie_eintrag(db_session, schueler.id, schuljahr.id) is False


@pytest.mark.asyncio
async def test_student_hat_historie_eintrag_false_for_other_schuljahr(db_session):
    schuljahr_a = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_b = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_a, schuljahr_b])
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="A", aktiv=True)
    db_session.add(schueler)
    await db_session.flush()
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_a.id, klasse_id=None))
    await db_session.commit()

    assert await student_query.student_hat_historie_eintrag(db_session, schueler.id, schuljahr_b.id) is False
```

- [x] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_student_query.py -k student_hat_historie_eintrag -v`
Expected: FAIL — `AttributeError: module 'app.services.student_query' has no attribute 'student_hat_historie_eintrag'`.

- [x] **Step 3: Funktion implementieren**

In `backend/app/services/student_query.py`, füge nach `load_historische_klasse_map` (nach Zeile 160) ein:

```python
async def student_hat_historie_eintrag(db: AsyncSession, schueler_id: int, schuljahr_id: int) -> bool:
    """True, wenn fuer diesen Schueler ein schueler_klasse_historie-Snapshot fuer schuljahr_id
    existiert -- AUCH wenn dessen klasse_id NULL ist (das heisst "eingeschrieben, Klasse zum
    Importzeitpunkt unbekannt", nicht "nicht eingeschrieben"). False heisst "im gewaehlten
    Schuljahr nicht eingeschrieben" -- GET /students/{id} liefert dann 404 statt eines
    Klassen-Fallbacks, siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md. Bewusst separat
    von load_historische_klasse_map, die "keine Zeile" und "Zeile mit klasse_id=NULL" fuer die
    Klassen-ANZEIGE absichtlich gleichbehandelt (beides "unbekannt")."""
    result = await db.execute(
        select(SchuelerKlasseHistorie.id).where(
            SchuelerKlasseHistorie.schueler_id == schueler_id,
            SchuelerKlasseHistorie.schuljahr_id == schuljahr_id,
        )
    )
    return result.scalar_one_or_none() is not None
```

- [x] **Step 4: Test ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_student_query.py -v`
Expected: alle Tests PASS.

- [x] **Step 5: Route-Tests in `test_api_students.py` anpassen**

**5a.** Ändere `test_get_student_detail_history_mode_filters_four_sections_not_massnahmen` (Zeile 675-708) — ergänze nach dem `db_session.add_all([schueler, typ, nutzer])`/`await db_session.flush()`-Block (nach Zeile 688) eine `SchuelerKlasseHistorie`-Zeile:

```python
    db_session.add(SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr.id, klasse_id=klasse.id))
```

(direkt vor dem bestehenden `db_session.add_all([Fehlzeit(...), Fehlzeit(...), Massnahme(...)])`-Block, Zeile 689 — beide `db.add`/`db.add_all`-Aufrufe landen vor demselben `await db_session.commit()`.)

**5b.** Ersetze `test_get_student_detail_history_mode_klasse_is_none_without_historie_snapshot` (Zeile 782-807) komplett durch:

```python
@pytest.mark.asyncio
async def test_get_student_detail_history_mode_returns_404_without_historie_snapshot(db_session):
    """Schuljahre vor Einfuehrung dieses Features (oder ohne rueckwirkenden Import) haben keine
    schueler_klasse_historie-Zeilen -- die API liefert dann 404 ('nicht eingeschrieben') statt
    stillschweigend klasse=None mit Status 200 (bewusste Verhaltensaenderung gegenueber Plan 16,
    siehe docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md Abschnitt 1)."""
    schuljahr_alt = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    schuljahr_neu = Schuljahr(id=28, name="2025/2026", start_datum=date(2025, 9, 15), end_datum=date(2026, 7, 29))
    db_session.add_all([schuljahr_alt, schuljahr_neu])
    await db_session.flush()
    klasse_neu = Klasse(webuntis_id=1, name="10b", schuljahr_id=schuljahr_neu.id)
    db_session.add(klasse_neu)
    await db_session.flush()
    db_session.add(Einstellung(aktuelles_schuljahr_id=schuljahr_neu.id))
    await _seed_klassenlehrkraft(db_session, [klasse_neu.id])
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", klasse_id=klasse_neu.id)
    db_session.add(schueler)
    await db_session.commit()
    # keine SchuelerKlasseHistorie-Zeile fuer schuljahr_alt angelegt

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/students/{schueler.id}?schuljahr_id={schuljahr_alt.id}", headers=HEADERS_KLASSENLEHRKRAFT
        )

    assert response.status_code == 404
```

- [x] **Step 6: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -k "history_mode_returns_404 or history_mode_filters_four_sections" -v`
Expected: FAIL — die Route liefert für `test_get_student_detail_history_mode_returns_404_without_historie_snapshot` noch 200 (kein Existenz-Check); `test_get_student_detail_history_mode_filters_four_sections_not_massnahmen` sollte an dieser Stelle bereits wieder PASS sein (reine Testdaten-Ergänzung, kein Route-Fix nötig), da noch kein 404-Check existiert, der ihn brechen könnte.

- [x] **Step 7: Route fixen**

In `backend/app/api/routes/students.py`, ändere in `get_student_detail` (Zeilen 190-201):

```python
@router.get("/{schueler_id}")
async def get_student_detail(
    schueler: Annotated[Schueler, Depends(get_scoped_schueler)],
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: int | None = None,
) -> StudentDetailOut:
    von, bis = await _resolve_schuljahr_zeitraum(db, schuljahr_id)
    ist_historie = von is not None
    if ist_historie and not await student_query.student_hat_historie_eintrag(db, schueler.id, schuljahr_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Schüler war in diesem Schuljahr nicht eingeschrieben"
        )
    effektiv_von, effektiv_bis = (von, bis) if ist_historie else await _aktuelles_schuljahr_zeitraum(db)
    detail = await student_query.load_student_detail(
        db, schueler.id, von=effektiv_von, bis=effektiv_bis, ist_historie=ist_historie
    )
```

(Rest der Funktion unverändert — der bestehende `if ist_historie: klasse_map_historie = ...`-Block danach bleibt exakt wie er ist, da ab hier garantiert eine Historie-Zeile existiert.)

- [x] **Step 8: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_students.py -v`
Expected: alle Tests PASS.

- [x] **Step 9: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [x] **Step 10: Commit**

```bash
git add backend/app/services/student_query.py backend/app/api/routes/students.py \
  backend/tests/test_student_query.py backend/tests/test_api_students.py
git commit -m "fix: return 404 from GET /students/{id} when student has no historie row for the requested schuljahr"
```

---

## Task 3: `ASV_CSV_ARCHIVE_DIR` — Setting, Docker-Volume, Archivierung bei jedem Live-Import

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/asv_csv_import.py`
- Modify: `backend/docker-compose.yml`
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_asv_csv_import.py`

**Interfaces:**
- Neu: `Settings.asv_csv_archive_dir: str` (Pflichtfeld, analog `asv_csv_path`).
- `import_schueler(db)` — Signatur unverändert. Kopiert bei jedem tatsächlich verarbeiteten Lauf (mtime-Check nicht übersprungen) zusätzlich `settings.asv_csv_path` nach `<asv_csv_archive_dir>/<schuljahr.name mit "/" -> "-">.csv`, sofern `einstellung.aktuelles_schuljahr_id` gesetzt ist (sonst wie beim Historie-Snapshot: übersprungen, siehe Abweichung 6).

- [x] **Step 1: Fehlschlagende Tests schreiben**

Füge in `backend/tests/test_asv_csv_import.py` nach dem `_set_csv_path`-Fixture (Zeile 1159-1161) ein zweites autouse-Fixture ein:

```python
@pytest.fixture(autouse=True)
def _set_csv_archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asv_csv_archive_dir", str(tmp_path / "archiv"))
```

Füge am Ende der Datei folgende Tests an:

```python
@pytest.mark.asyncio
async def test_import_archives_csv_under_schuljahr_name(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    _write_csv(
        tmp_path,
        ['"x";"x";"ext-archiv-1";"Name";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'],
    )

    await import_schueler(db_session)

    archiv_datei = Path(settings.asv_csv_archive_dir) / "2025-2026.csv"
    assert archiv_datei.exists()
    assert archiv_datei.read_text(encoding="utf-8") == Path(settings.asv_csv_path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_import_overwrites_archive_on_reimport_of_same_schuljahr(db_session, tmp_path):
    schuljahr = await _seed_aktuelles_schuljahr(db_session)
    _write_csv(tmp_path, ['"x";"x";"ext-archiv-2";"Alt";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'])
    await import_schueler(db_session)

    # neue mtime erzwingen, damit der zweite Lauf nicht per mtime-Check uebersprungen wird
    neue_zeit = datetime.now().timestamp() + 5
    _write_csv(tmp_path, ['"x";"x";"ext-archiv-2";"Neu";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'])
    os.utime(settings.asv_csv_path, (neue_zeit, neue_zeit))

    await import_schueler(db_session)

    archiv_datei = Path(settings.asv_csv_archive_dir) / "2025-2026.csv"
    inhalt = archiv_datei.read_text(encoding="utf-8")
    assert '"Neu"' in inhalt
    assert '"Alt"' not in inhalt
    # genau eine Datei pro Schuljahr, kein "eine Datei pro Import"
    assert len(list(Path(settings.asv_csv_archive_dir).iterdir())) == 1


@pytest.mark.asyncio
async def test_import_skips_archiving_when_no_aktuelles_schuljahr(db_session, tmp_path):
    _write_csv(tmp_path, ['"x";"x";"ext-archiv-3";"Name";"Vor";"";"";"01.01.1990";"";"17.03.2020";"ja"'])

    await import_schueler(db_session)

    assert not Path(settings.asv_csv_archive_dir).exists() or list(Path(settings.asv_csv_archive_dir).iterdir()) == []
```

Ergänze am Dateianfang die Imports `import os` (für `os.utime`) — bereits über `from pathlib import Path` hinaus nötig, `datetime` ist bereits importiert (Zeile 1).

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_asv_csv_import.py -k archiv -v`
Expected: FAIL — `Settings`-Objekt hat noch kein `asv_csv_archive_dir`-Attribut (`AttributeError` beim `monkeypatch.setattr`, da `Settings` mit `extra="ignore"` zwar kein neues Attribut per `setattr` verhindert, `import_schueler` aber niemals danach liest — die Datei wird schlicht nie archiviert, `archiv_datei.exists()` ist `False`).

- [x] **Step 3: `Settings` erweitern**

In `backend/app/core/config.py`, füge nach `asv_csv_path: str` (Zeile 15) ein:

```python
    asv_csv_path: str
    asv_csv_archive_dir: str
```

In `backend/.env.example`, ergänze nach `ASV_CSV_PATH=...` (Zeile 11):

```
ASV_CSV_ARCHIVE_DIR=/data/asv-csv-archiv
```

- [x] **Step 4: `import_schueler` erweitern**

In `backend/app/services/asv_csv_import.py`, füge die Imports hinzu:

```python
import shutil
```

(nach `import os`, Zeile 5). Füge eine neue Hilfsfunktion nach `_parse_datum` (nach Zeile 24) ein:

```python
def _archiviere_csv(quelle: str, archiv_verzeichnis: str, schuljahr_name: str) -> None:
    """Kopiert die soeben verarbeitete ASV-CSV nach <archiv_verzeichnis>/<schuljahr_name>.csv
    (ein Stand pro Schuljahr, bei jedem weiteren Import desselben Jahres ueberschrieben) -- siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md. schuljahr_name
    enthaelt ein "/" (z.B. "2025/2026", siehe app/models/schuljahr.py) -- wird durch "-" ersetzt,
    da ein woertliches "/" im Dateinamen auf Linux ein Unterverzeichnis erzeugen wuerde statt
    einer einzelnen Datei. archiv_verzeichnis muss auf ein persistentes Volume zeigen
    (ASV_CSV_ARCHIVE_DIR), nicht das fluechtige Live-Mount-Verzeichnis von asv_csv_path."""
    os.makedirs(archiv_verzeichnis, exist_ok=True)
    ziel_dateiname = f"{schuljahr_name.replace('/', '-')}.csv"
    shutil.copyfile(quelle, os.path.join(archiv_verzeichnis, ziel_dateiname))
```

Ergänze am Ende von `import_schueler`, direkt vor `einstellung.asv_csv_zuletzt_importiert_mtime = mtime` (Zeile 141):

```python
    if einstellung.aktuelles_schuljahr_id is not None:
        aktuelles_schuljahr = await db.get(Schuljahr, einstellung.aktuelles_schuljahr_id)
        if aktuelles_schuljahr is not None:
            _archiviere_csv(settings.asv_csv_path, settings.asv_csv_archive_dir, aktuelles_schuljahr.name)

    einstellung.asv_csv_zuletzt_importiert_mtime = mtime
```

Füge den fehlenden Import hinzu:

```python
from app.models.schuljahr import Schuljahr
```

(alphabetisch nach `from app.models.klasse import Klasse`, vor `from app.models.schueler import Schueler`.)

Ergänze im Docstring von `import_schueler` (Zeile 28-34) einen Satz zur Archivierung.

- [x] **Step 5: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_asv_csv_import.py -v`
Expected: alle Tests PASS.

- [x] **Step 6: `docker-compose.yml` — neues Volume**

In `backend/docker-compose.yml`, ergänze im `backend`-Service die `volumes`-Liste (Zeile 34-35):

```yaml
    volumes:
      - ./data/schueler.csv:/tmp/schueler.csv:ro
      - absenzdash-asv-csv-archiv-data:/data/asv-csv-archiv
```

Ergänze den `volumes:`-Top-Level-Block (Zeile 41-42):

```yaml
volumes:
  absenzdash-db-data:
  absenzdash-asv-csv-archiv-data:
```

Ergänze in der lokalen `backend/.env` (nicht versioniert, manuell) `ASV_CSV_ARCHIVE_DIR=/data/asv-csv-archiv`, passend zum neuen Mount-Ziel — analog zu `.env.example`.

- [x] **Step 7: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS. (Docker-Compose-Änderung selbst wird nicht gegen den Dev-Stack ausgerollt/getestet, siehe Global Constraints — reines Konfigurations-Review reicht, `docker compose config` kann optional zur Syntax-Prüfung laufen: `cd backend && docker compose config --quiet`.)

- [x] **Step 8: Commit**

```bash
git add backend/app/core/config.py backend/app/services/asv_csv_import.py \
  backend/docker-compose.yml backend/.env.example backend/tests/test_asv_csv_import.py
git commit -m "feat: archive the raw ASV-CSV per schuljahr on every processed live import"
```

---

## Task 4: Gemeinsame CSV-Lese-Funktion + historischer Import — Vorschau-Endpunkt

**Files:**
- Modify: `backend/app/services/asv_csv_import.py`
- Modify: `backend/tests/test_asv_csv_import.py`
- Create: `backend/app/services/schuljahr_historie_import_service.py`
- Modify: `backend/app/schemas/admin.py`
- Modify: `backend/app/api/routes/admin.py`
- Create: `backend/tests/test_schuljahr_historie_import_service.py`
- Create: `backend/tests/test_api_admin_schuljahr_historie_import.py`

**Interfaces:**
- Neu (extrahiert aus `import_schueler`): `asv_csv_import.lese_asv_csv_zeilen(pfad: str) -> list[dict[str, str]]` — öffnet+validiert+parst eine ASV-CSV-Datei (Spalten-Validierung, UTF-8, Delimiter `;`), wirft `ValueError` bei fehlenden Header-Spalten, `OSError` bei ungültiger Kodierung. Gemeinsame Grundlage für Live-Import und historischen Admin-Import.
- Neu: `schuljahr_historie_import_service.preview_import(db, schuljahr_id: int, file: UploadFile) -> HistorieImportPreviewOut` — schreibt nichts (außer dem per `sync_klassen` ausgelösten Klassen-Nachzug).
- Neu: `POST /admin/schuljahr-historie-import/preview` (multipart: `schuljahr_id`, `file`) → `HistorieImportPreviewOut`.

- [x] **Step 1: Fehlschlagenden Test für `lese_asv_csv_zeilen` schreiben**

Füge in `backend/tests/test_asv_csv_import.py` an:

```python
def test_lese_asv_csv_zeilen_returns_parsed_rows(tmp_path):
    from app.services.asv_csv_import import lese_asv_csv_zeilen

    path = _write_csv(tmp_path, ['"a";"a";"ext-1";"Nachname";"Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'])

    rows = lese_asv_csv_zeilen(str(path))

    assert len(rows) == 1
    assert rows[0]["idnumber"] == "ext-1"


def test_lese_asv_csv_zeilen_raises_value_error_on_missing_header_column(tmp_path):
    from app.services.asv_csv_import import lese_asv_csv_zeilen

    header_ohne_idnumber = "login;shortname;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"
    path = tmp_path / "schueler.csv"
    path.write_text(header_ohne_idnumber + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        lese_asv_csv_zeilen(str(path))


def test_lese_asv_csv_zeilen_raises_os_error_on_invalid_encoding(tmp_path):
    from app.services.asv_csv_import import lese_asv_csv_zeilen

    path = tmp_path / "schueler.csv"
    zeilen = [HEADER.encode("utf-8"), b'"x";"x";"ext-1";"M\xfcller";"Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"']
    path.write_bytes(b"\n".join(zeilen) + b"\n")

    with pytest.raises(OSError):
        lese_asv_csv_zeilen(str(path))
```

- [x] **Step 2: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_asv_csv_import.py -k lese_asv_csv_zeilen -v`
Expected: FAIL — `ImportError: cannot import name 'lese_asv_csv_zeilen'`.

- [x] **Step 3: `lese_asv_csv_zeilen` extrahieren, `import_schueler` darauf umstellen**

In `backend/app/services/asv_csv_import.py`, füge nach `_parse_datum`/`_archiviere_csv` (nach Task 3) eine neue Funktion ein:

```python
def _erwartete_spalten() -> list[str]:
    return [
        settings.asv_csv_column_externe_id,
        settings.asv_csv_column_vorname,
        settings.asv_csv_column_nachname,
        settings.asv_csv_column_klasse,
        settings.asv_csv_column_eintrittsdatum,
        settings.asv_csv_column_austrittsdatum,
    ]


def lese_asv_csv_zeilen(pfad: str) -> list[dict[str, str]]:
    """Oeffnet+parst eine ASV-CSV-Datei (Spalten-Validierung, UTF-8, Delimiter ';') und liefert
    die Rohzeilen als Liste von dicts (Spaltenname -> Wert), OHNE sie zu verarbeiten -- gemeinsame
    Grundlage fuer den laufenden Live-Import (import_schueler) und den rueckwirkenden
    Admin-Import (schuljahr_historie_import_service.py), siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md. Wirft ValueError
    bei fehlenden Header-Spalten, OSError bei ungueltiger Kodierung -- identische
    Fehlerbehandlung wie zuvor inline in import_schueler."""
    try:
        with open(pfad, encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file, delimiter=";")
            fehlende_spalten = [s for s in _erwartete_spalten() if s not in (reader.fieldnames or [])]
            if fehlende_spalten:
                raise ValueError(f"ASV-CSV: fehlende Spalten im Header: {fehlende_spalten}")
            return list(reader)
    except UnicodeDecodeError as exc:
        raise OSError(f"ASV-CSV: Datei {pfad} ist nicht UTF-8-kodiert: {exc}") from exc
```

Ändere `import_schueler`: ersetze den `erwartete_spalten = [...]`-Block und den `with open(...) as csv_file: reader = csv.DictReader(...)`-Header-Check (Zeilen 70-85) durch einen Aufruf von `lese_asv_csv_zeilen`, und iteriere über die zurückgegebene Liste statt über den `DictReader` direkt:

```python
    try:
        rows = lese_asv_csv_zeilen(settings.asv_csv_path)
    except UnicodeDecodeError:  # pragma: no cover - lese_asv_csv_zeilen wandelt das bereits in OSError um
        raise

    uebersprungene_zeilen = 0
    for zeilen_nr, row in enumerate(rows, start=2):
        try:
            externe_id = row[settings.asv_csv_column_externe_id]
            ...
```

**Wichtig:** der bestehende `try/except UnicodeDecodeError`-Block außen um den `with open(...)`-Block entfällt komplett (die Umwandlung passiert jetzt innerhalb von `lese_asv_csv_zeilen`); `ValueError`/`OSError` aus `lese_asv_csv_zeilen` propagieren unverändert nach oben (identisch zum bisherigen Verhalten, keine neue `except`-Klausel in `import_schueler` nötig). Die restliche Zeilen-Verarbeitungslogik (Try/Except pro Zeile, Historie-Snapshot, `uebersprungene_zeilen`-Zähler und -Logging) bleibt unverändert, nur um eine Einrückungsebene reduziert (kein `with`-Block mehr).

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_asv_csv_import.py -v`
Expected: alle Tests PASS (insbesondere bleiben `test_import_raises_value_error_on_missing_header_column`, `test_import_raises_os_error_on_invalid_encoding`, `test_import_skips_broken_row_but_keeps_valid_rows` unverändert grün — reiner Refactor, kein Verhaltensunterschied für `import_schueler`).

- [x] **Step 5: Commit (Zwischenstand, reiner Refactor)**

```bash
git add backend/app/services/asv_csv_import.py backend/tests/test_asv_csv_import.py
git commit -m "refactor: extract lese_asv_csv_zeilen for reuse by the historical import"
```

- [x] **Step 6: Schemas ergänzen**

In `backend/app/schemas/admin.py`, füge am Ende der Datei an:

```python
class HistorieImportPreviewOut(BaseModel):
    zeilen_gesamt: int
    schueler_bekannt: int
    schueler_neu: int
    unbekannte_klassen: list[str]
    uebersprungene_zeilen: int


class HistorieImportResultOut(BaseModel):
    zeilen_verarbeitet: int
    neu_angelegte_schueler: int
    uebersprungene_zeilen: int
```

- [x] **Step 7: Fehlschlagenden Service-Test schreiben**

Erstelle `backend/tests/test_schuljahr_historie_import_service.py`:

```python
from datetime import date
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from app.models.abteilung import Abteilung
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr
from app.services import schuljahr_historie_import_service

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


def _upload(rows: list[str]) -> UploadFile:
    inhalt = ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")
    return UploadFile(filename="archiv.csv", file=BytesIO(inhalt))


async def _seed_schuljahr(db_session, schuljahr_id: int = 27) -> Schuljahr:
    schuljahr = Schuljahr(id=schuljahr_id, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.commit()
    return schuljahr


@pytest.mark.asyncio
async def test_preview_import_counts_known_and_new_schueler(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    db_session.add(Schueler(externe_id="ext-bekannt", vorname="Alt", nachname="Bekannt"))
    await db_session.commit()

    upload = _upload(
        [
            '"a";"a";"ext-bekannt";"Bekannt";"Alt";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
            '"b";"b";"ext-neu";"Neu";"Person";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"',
        ]
    )

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.zeilen_gesamt == 2
    assert preview.schueler_bekannt == 1
    assert preview.schueler_neu == 1
    assert preview.unbekannte_klassen == []
    assert preview.uebersprungene_zeilen == 0


@pytest.mark.asyncio
async def test_preview_import_reports_unknown_klasse_names(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    upload = _upload(['"a";"a";"ext-1";"N";"V";"";"UNBEKANNT";"01.01.1990";"";"17.03.2020";"ja"'])

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.unbekannte_klassen == ["UNBEKANNT"]


@pytest.mark.asyncio
async def test_preview_import_fetches_missing_klassen_from_webuntis(db_session, monkeypatch):
    """Fehlt eine per Klassenname referenzierte klasse-Zeile fuers gewaehlte Schuljahr komplett,
    wird sync_klassen (Plan 16) automatisch mit schoolyear_id=<gewaehltes Jahr> nachgezogen,
    bevor der endgueltige unbekannte_klassen-Abgleich passiert -- siehe Design-Dok Abschnitt 3."""
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    async def _fake_sync_klassen(client, db, schoolyear_id):
        db.add(Klasse(webuntis_id=1, name="NACHGEZOGEN", schuljahr_id=schoolyear_id))
        await db.flush()

    monkeypatch.setattr(schuljahr_historie_import_service, "sync_klassen", _fake_sync_klassen)
    monkeypatch.setattr(
        schuljahr_historie_import_service.WebUntisClient, "__aenter__", lambda self: self
    )
    monkeypatch.setattr(schuljahr_historie_import_service.WebUntisClient, "__aexit__", lambda self, *a: None)

    upload = _upload(['"a";"a";"ext-1";"N";"V";"";"NACHGEZOGEN";"01.01.1990";"";"17.03.2020";"ja"'])

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.unbekannte_klassen == []


@pytest.mark.asyncio
async def test_preview_import_raises_404_for_unknown_schuljahr(db_session):
    from fastapi import HTTPException

    upload = _upload(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"'])

    with pytest.raises(HTTPException) as exc_info:
        await schuljahr_historie_import_service.preview_import(db_session, 999999, upload)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_preview_import_counts_skipped_rows_with_broken_dates(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    upload = _upload(
        [
            '"a";"a";"ext-ok";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"',
            '"b";"b";"ext-broken";"N";"V";"";"";"01.01.1990";"";"NICHT-EIN-DATUM";"ja"',
        ]
    )

    preview = await schuljahr_historie_import_service.preview_import(db_session, schuljahr.id, upload)

    assert preview.zeilen_gesamt == 1
    assert preview.uebersprungene_zeilen == 1
```

- [x] **Step 8: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_schuljahr_historie_import_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.schuljahr_historie_import_service'`.

- [x] **Step 9: Service implementieren (Vorschau-Teil)**

Erstelle `backend/app/services/schuljahr_historie_import_service.py`:

```python
from __future__ import annotations

import os
import tempfile

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.webuntis_client import WebUntisClient, WebUntisError
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr
from app.schemas.admin import HistorieImportPreviewOut
from app.services.asv_csv_import import _parse_datum, lese_asv_csv_zeilen
from app.services.webuntis_klassen_sync import sync_klassen


async def _schuljahr_oder_404(db: AsyncSession, schuljahr_id: int) -> Schuljahr:
    schuljahr = await db.get(Schuljahr, schuljahr_id)
    if schuljahr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unbekanntes Schuljahr")
    return schuljahr


async def _speichere_upload_temporaer(file: UploadFile) -> str:
    inhalt = await file.read()
    fd, pfad = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "wb") as tmp:
        tmp.write(inhalt)
    return pfad


def _parse_zeilen(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    """Parst externe_id/klasse_name/vorname/nachname aus den Rohzeilen (identisches
    Fehlerhandling wie import_schueler: KeyError/ValueError -> Zeile ueberspringen). Eintritts-/
    Austrittsdatum werden nur validiert, nicht weiterverwendet -- der historische Import ruehrt
    schueler.aktiv nicht an (Design-Dok Nicht-Ziel)."""
    geparste: list[dict[str, str]] = []
    uebersprungen = 0
    for row in rows:
        try:
            externe_id = row[settings.asv_csv_column_externe_id]
            klasse_name = row[settings.asv_csv_column_klasse]
            vorname = row[settings.asv_csv_column_vorname]
            nachname = row[settings.asv_csv_column_nachname]
            _parse_datum(row[settings.asv_csv_column_eintrittsdatum])
            _parse_datum(row[settings.asv_csv_column_austrittsdatum])
        except (KeyError, ValueError):
            uebersprungen += 1
            continue
        if not externe_id:
            uebersprungen += 1
            continue
        geparste.append(
            {"externe_id": externe_id, "klasse_name": klasse_name, "vorname": vorname, "nachname": nachname}
        )
    return geparste, uebersprungen


async def _klasse_id_by_name(db: AsyncSession, schuljahr_id: int) -> dict[str, int]:
    return dict(
        (await db.execute(select(Klasse.name, Klasse.id).where(Klasse.schuljahr_id == schuljahr_id))).all()
    )


async def _bekannte_externe_ids(db: AsyncSession, externe_ids: set[str]) -> set[str]:
    if not externe_ids:
        return set()
    result = await db.execute(select(Schueler.externe_id).where(Schueler.externe_id.in_(externe_ids)))
    return set(result.scalars().all())


async def _klassen_von_webuntis_nachziehen(db: AsyncSession, schuljahr_id: int) -> None:
    try:
        async with WebUntisClient(settings) as client:
            await sync_klassen(client, db, schoolyear_id=schuljahr_id)
    except WebUntisError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"WebUntis nicht erreichbar: {exc}")


async def _lese_und_parse_upload(file: UploadFile) -> tuple[list[dict[str, str]], int]:
    tmp_pfad = await _speichere_upload_temporaer(file)
    try:
        rows = lese_asv_csv_zeilen(tmp_pfad)
    except (ValueError, OSError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    finally:
        os.unlink(tmp_pfad)
    return _parse_zeilen(rows)


async def preview_import(db: AsyncSession, schuljahr_id: int, file: UploadFile) -> HistorieImportPreviewOut:
    """Vorschau vor dem eigentlichen Schreiben (siehe
    docs/superpowers/specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md, Abschnitt 3):
    parst die hochgeladene CSV, matched Klassennamen gegen klasse-Zeilen des gewaehlten
    Schuljahres (fehlen sie komplett, wird per WebUntis getKlassen via sync_klassen
    nachgezogen), matched externe_id gegen bestehende schueler. Schreibt selbst NICHTS in die DB
    (der Klassen-Nachzug via sync_klassen ist ein Seiteneffekt von WebUntis-Daten, kein
    Schreiben rueckwirkend erfundener Daten -- bewusst in Kauf genommen, siehe Design-Dok)."""
    await _schuljahr_oder_404(db, schuljahr_id)
    geparste_zeilen, uebersprungen = await _lese_und_parse_upload(file)

    klasse_namen = {z["klasse_name"] for z in geparste_zeilen if z["klasse_name"]}
    klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)
    fehlende_namen = klasse_namen - set(klasse_id_by_name.keys())
    if fehlende_namen:
        await _klassen_von_webuntis_nachziehen(db, schuljahr_id)
        klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)
        fehlende_namen = klasse_namen - set(klasse_id_by_name.keys())

    externe_ids = {z["externe_id"] for z in geparste_zeilen}
    bekannte_externe_ids = await _bekannte_externe_ids(db, externe_ids)

    return HistorieImportPreviewOut(
        zeilen_gesamt=len(geparste_zeilen),
        schueler_bekannt=len(externe_ids & bekannte_externe_ids),
        schueler_neu=len(externe_ids - bekannte_externe_ids),
        unbekannte_klassen=sorted(fehlende_namen),
        uebersprungene_zeilen=uebersprungen,
    )
```

- [x] **Step 10: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_schuljahr_historie_import_service.py -v`
Expected: alle Tests PASS.

- [x] **Step 11: Fehlschlagenden Route-Test schreiben**

Erstelle `backend/tests/test_api_admin_schuljahr_historie_import.py`:

```python
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.models.klasse import Klasse
from app.models.schueler import Schueler
from app.models.schuljahr import Schuljahr

HEADERS_SCHULLEITUNG = {
    "X-WordPress-Secret": "test-secret",
    "X-WordPress-User": "jseyfried",
    "X-WordPress-Email": "joerg.seyfried@hhs.karlsruhe.de",
    "X-WordPress-Name": "Joerg Seyfried",
    "X-WordPress-Role": "schulleitung",
}
HEADERS_KLASSENLEHRKRAFT = {**HEADERS_SCHULLEITUNG, "X-WordPress-Role": "klassenlehrkraft"}

HEADER = "login;shortname;idnumber;lastname;firstname;email;Klasse;birthday;Austrittsdatum;Eintrittsdatum;volljaehrig"


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "wordpress_proxy_secret", "test-secret")


def _csv_bytes(rows: list[str]) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_post_preview_rejects_non_schulleitung(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import/preview",
            headers=HEADERS_KLASSENLEHRKRAFT,
            data={"schuljahr_id": str(schuljahr.id)},
            files={"file": ("archiv.csv", _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"']), "text/csv")},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_preview_returns_summary(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import/preview",
            headers=HEADERS_SCHULLEITUNG,
            data={"schuljahr_id": str(schuljahr.id)},
            files={
                "file": (
                    "archiv.csv",
                    _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"']),
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["zeilen_gesamt"] == 1
    assert body["schueler_neu"] == 1
    assert body["schueler_bekannt"] == 0
    assert body["unbekannte_klassen"] == []


@pytest.mark.asyncio
async def test_post_preview_returns_404_for_unknown_schuljahr(db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import/preview",
            headers=HEADERS_SCHULLEITUNG,
            data={"schuljahr_id": "999999"},
            files={"file": ("archiv.csv", _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"']), "text/csv")},
        )
    assert response.status_code == 404
```

- [x] **Step 12: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_admin_schuljahr_historie_import.py -v`
Expected: FAIL — Route existiert noch nicht (404 "Not Found" statt der erwarteten Status-Codes, bzw. sogar der 403-Test schlägt fehl, da FastAPI eine unbekannte Route generisch mit 404 statt 403 beantwortet).

- [x] **Step 13: Route verdrahten**

In `backend/app/api/routes/admin.py`, ergänze die Imports:

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
```

```python
from app.schemas.admin import (
    ...
    HistorieImportPreviewOut,
    ...
)
```

```python
from app.services import (
    ...
    schuljahr_historie_import_service,
    ...
)
```

(alphabetisch einsortieren.) Füge am Ende der Datei die neue Route ein:

```python
@router.post("/schuljahr-historie-import/preview")
async def post_schuljahr_historie_import_preview(
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
) -> HistorieImportPreviewOut:
    return await schuljahr_historie_import_service.preview_import(db, schuljahr_id, file)
```

(Die `schulleitung`-Pflicht kommt bereits über `dependencies=[Depends(require_schulleitung)]` auf dem Router, Zeile 45 — kein zusätzlicher Parameter nötig, da diese Route `nutzer.id` nicht braucht, siehe `get_bereiche`/`get_threshold_rules` als Vorbild für reine GET/Lese-Endpunkte ohne `nutzer`-Parameter trotz Schreibschutz durch den Router.)

- [x] **Step 14: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_admin_schuljahr_historie_import.py -v`
Expected: alle Tests PASS.

- [x] **Step 15: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [x] **Step 16: Commit**

```bash
git add backend/app/schemas/admin.py backend/app/api/routes/admin.py \
  backend/app/services/schuljahr_historie_import_service.py \
  backend/tests/test_schuljahr_historie_import_service.py backend/tests/test_api_admin_schuljahr_historie_import.py
git commit -m "feat: add preview endpoint for retroactive schuljahr historie import"
```

---

## Task 5: Historischer Import — Bestätigen/Schreiben + Audit-Log

**Files:**
- Modify: `backend/app/services/schuljahr_historie_import_service.py`
- Modify: `backend/app/api/routes/admin.py`
- Modify: `backend/tests/test_schuljahr_historie_import_service.py`
- Modify: `backend/tests/test_api_admin_schuljahr_historie_import.py`

**Interfaces:**
- Neu: `schuljahr_historie_import_service.commit_import(db, schuljahr_id: int, file: UploadFile, admin_nutzer_id: int) -> HistorieImportResultOut` — schreibt `schueler_klasse_historie` (Upsert je `schueler_id`), legt für unbekannte `externe_id` einen minimalen `Schueler` an, schreibt einen `AuditLog`-Eintrag (`aktion="admin_schuljahr_historie_import"`).
- Neu: `POST /admin/schuljahr-historie-import` (multipart: `schuljahr_id`, `file`) → `HistorieImportResultOut`.

- [x] **Step 1: Fehlschlagende Service-Tests schreiben**

Füge in `backend/tests/test_schuljahr_historie_import_service.py` folgende Imports/Tests hinzu:

```python
from app.models.audit_log import AuditLog
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
```

```python
@pytest.mark.asyncio
async def test_commit_import_creates_historie_row_for_existing_schueler_without_touching_live_fields(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    klasse = Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id)
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(
        externe_id="ext-1", vorname="Aktuell", nachname="Name", klasse_id=None, aktiv=True
    )
    db_session.add(schueler)
    await db_session.commit()

    upload = _upload(['"a";"a";"ext-1";"Archiv-Nachname";"Archiv-Vorname";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"'])

    result = await schuljahr_historie_import_service.commit_import(db_session, schuljahr.id, upload, admin_nutzer_id=1)

    assert result.zeilen_verarbeitet == 1
    assert result.neu_angelegte_schueler == 0

    await db_session.refresh(schueler)
    # LIVE-Felder bleiben unangetastet -- das ist der Kern des Nicht-Ziels
    assert schueler.vorname == "Aktuell"
    assert schueler.nachname == "Name"
    assert schueler.klasse_id is None
    assert schueler.aktiv is True

    historie = (
        await db_session.execute(select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id))
    ).scalar_one()
    assert historie.schuljahr_id == schuljahr.id
    assert historie.klasse_id == klasse.id


@pytest.mark.asyncio
async def test_commit_import_creates_minimal_schueler_for_unknown_externe_id(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    upload = _upload(['"a";"a";"ext-neu";"Neu";"Person";"";"";"01.01.1990";"";"17.03.2020";"ja"'])

    result = await schuljahr_historie_import_service.commit_import(db_session, schuljahr.id, upload, admin_nutzer_id=1)

    assert result.neu_angelegte_schueler == 1
    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-neu"))).scalar_one()
    assert schueler.vorname == "Person"
    assert schueler.nachname == "Neu"
    assert schueler.klasse_id is None
    assert schueler.aktiv is False  # Spalten-Default, nicht explizit gesetzt


@pytest.mark.asyncio
async def test_commit_import_is_idempotent_on_reimport(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    klasse_alt = Klasse(webuntis_id=1, name="ALT", schuljahr_id=schuljahr.id)
    klasse_neu = Klasse(webuntis_id=2, name="NEU", schuljahr_id=schuljahr.id)
    db_session.add_all([klasse_alt, klasse_neu])
    await db_session.commit()

    await schuljahr_historie_import_service.commit_import(
        db_session, schuljahr.id, _upload(['"a";"a";"ext-1";"N";"V";"";"ALT";"01.01.1990";"";"17.03.2020";"ja"']), admin_nutzer_id=1
    )
    await schuljahr_historie_import_service.commit_import(
        db_session, schuljahr.id, _upload(['"a";"a";"ext-1";"N";"V";"";"NEU";"01.01.1990";"";"17.03.2020";"ja"']), admin_nutzer_id=1
    )

    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-1"))).scalar_one()
    historie_rows = (
        await db_session.execute(select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id))
    ).scalars().all()
    assert len(historie_rows) == 1  # kein Duplikat, sondern aktualisiert
    assert historie_rows[0].klasse_id == klasse_neu.id


@pytest.mark.asyncio
async def test_commit_import_writes_audit_log_with_schuljahr_and_counts(db_session):
    schuljahr = await _seed_schuljahr(db_session)
    await db_session.commit()

    await schuljahr_historie_import_service.commit_import(
        db_session,
        schuljahr.id,
        _upload(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"']),
        admin_nutzer_id=42,
    )

    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_schuljahr_historie_import"))
    ).scalar_one()
    assert audit.user_id == 42
    assert audit.resource_id == str(schuljahr.id)
    assert audit.details["schuljahr_id"] == schuljahr.id
    assert audit.details["zeilen_gesamt"] == 1
    assert audit.details["neu_angelegte_schueler"] == 1
```

- [x] **Step 2: Tests ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_schuljahr_historie_import_service.py -k commit_import -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'commit_import'`.

- [x] **Step 3: `commit_import` implementieren**

Ergänze in `backend/app/services/schuljahr_historie_import_service.py` die Imports:

```python
from app.models.audit_log import AuditLog
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie
from app.schemas.admin import HistorieImportPreviewOut, HistorieImportResultOut
```

Füge am Ende der Datei an:

```python
async def commit_import(
    db: AsyncSession, schuljahr_id: int, file: UploadFile, admin_nutzer_id: int
) -> HistorieImportResultOut:
    """Schreibt schueler_klasse_historie fuer schuljahr_id (Upsert je schueler_id) -- ruehrt
    schueler.klasse_id/aktiv/vorname/nachname fuer BESTEHENDE Schueler nicht an (das sind
    "aktuelle Wahrheit", siehe Design-Dok Nicht-Ziele). Fuer eine komplett unbekannte externe_id
    wird ein minimaler Schueler-Stammsatz angelegt (nur externe_id+Name; klasse_id/aktiv bleiben
    Spalten-Default, da fuer einen moeglicherweise laengst ausgeschiedenen Schueler nicht sinnvoll
    befuellbar). Idempotent: ein erneuter Import fuers selbe Schuljahr aktualisiert bestehende
    schueler_klasse_historie-Zeilen statt sie zu duplizieren (Update-Fall, z.B. eine spaeter
    aufgetauchte vollstaendigere Archiv-CSV)."""
    await _schuljahr_oder_404(db, schuljahr_id)
    geparste_zeilen, uebersprungen = await _lese_und_parse_upload(file)

    klasse_namen = {z["klasse_name"] for z in geparste_zeilen if z["klasse_name"]}
    klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)
    if klasse_namen - set(klasse_id_by_name.keys()):
        await _klassen_von_webuntis_nachziehen(db, schuljahr_id)
        klasse_id_by_name = await _klasse_id_by_name(db, schuljahr_id)

    externe_ids = {z["externe_id"] for z in geparste_zeilen}
    existing_schueler = (
        await db.execute(select(Schueler).where(Schueler.externe_id.in_(externe_ids)))
    ).scalars().all()
    by_externe_id = {s.externe_id: s for s in existing_schueler}

    existing_historie = (
        await db.execute(select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schuljahr_id == schuljahr_id))
    ).scalars().all()
    historie_by_schueler_id = {h.schueler_id: h for h in existing_historie}

    neu_angelegte_schueler = 0
    zeilen_verarbeitet = 0
    for zeile in geparste_zeilen:
        klasse_id = klasse_id_by_name.get(zeile["klasse_name"])
        schueler = by_externe_id.get(zeile["externe_id"])
        if schueler is None:
            schueler = Schueler(externe_id=zeile["externe_id"], vorname=zeile["vorname"], nachname=zeile["nachname"])
            db.add(schueler)
            await db.flush()
            by_externe_id[zeile["externe_id"]] = schueler
            neu_angelegte_schueler += 1

        historie = historie_by_schueler_id.get(schueler.id)
        if historie is None:
            historie = SchuelerKlasseHistorie(schueler_id=schueler.id, schuljahr_id=schuljahr_id, klasse_id=klasse_id)
            db.add(historie)
            historie_by_schueler_id[schueler.id] = historie
        else:
            historie.klasse_id = klasse_id
        zeilen_verarbeitet += 1

    db.add(
        AuditLog(
            user_id=admin_nutzer_id,
            aktion="admin_schuljahr_historie_import",
            resource_typ="schuljahr",
            resource_id=str(schuljahr_id),
            details={
                "schuljahr_id": schuljahr_id,
                "zeilen_gesamt": zeilen_verarbeitet,
                "neu_angelegte_schueler": neu_angelegte_schueler,
                "uebersprungene_zeilen": uebersprungen,
            },
        )
    )
    await db.commit()

    return HistorieImportResultOut(
        zeilen_verarbeitet=zeilen_verarbeitet,
        neu_angelegte_schueler=neu_angelegte_schueler,
        uebersprungene_zeilen=uebersprungen,
    )
```

- [x] **Step 4: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_schuljahr_historie_import_service.py -v`
Expected: alle Tests PASS.

- [x] **Step 5: Fehlschlagenden Route-Test schreiben**

Füge in `backend/tests/test_api_admin_schuljahr_historie_import.py` an:

```python
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.schueler_klasse_historie import SchuelerKlasseHistorie


@pytest.mark.asyncio
async def test_post_import_rejects_non_schulleitung(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import",
            headers=HEADERS_KLASSENLEHRKRAFT,
            data={"schuljahr_id": str(schuljahr.id)},
            files={"file": ("archiv.csv", _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"";"01.01.1990";"";"17.03.2020";"ja"']), "text/csv")},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_post_import_writes_historie_and_audit_log(db_session):
    schuljahr = Schuljahr(id=27, name="2024/2025", start_datum=date(2024, 9, 9), end_datum=date(2025, 7, 30))
    db_session.add(schuljahr)
    await db_session.flush()
    db_session.add(Klasse(webuntis_id=1, name="AME56", schuljahr_id=schuljahr.id))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/admin/schuljahr-historie-import",
            headers=HEADERS_SCHULLEITUNG,
            data={"schuljahr_id": str(schuljahr.id)},
            files={
                "file": (
                    "archiv.csv",
                    _csv_bytes(['"a";"a";"ext-1";"N";"V";"";"AME56";"01.01.1990";"";"17.03.2020";"ja"']),
                    "text/csv",
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["zeilen_verarbeitet"] == 1
    assert body["neu_angelegte_schueler"] == 1

    schueler = (await db_session.execute(select(Schueler).where(Schueler.externe_id == "ext-1"))).scalar_one()
    historie = (
        await db_session.execute(select(SchuelerKlasseHistorie).where(SchuelerKlasseHistorie.schueler_id == schueler.id))
    ).scalar_one()
    assert historie.schuljahr_id == schuljahr.id

    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.aktion == "admin_schuljahr_historie_import"))
    ).scalar_one()
    assert audit.details["schuljahr_id"] == schuljahr.id
```

- [x] **Step 6: Test ausführen, Fehlschlag verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_admin_schuljahr_historie_import.py -k post_import -v`
Expected: FAIL — Route `POST /admin/schuljahr-historie-import` existiert noch nicht.

- [x] **Step 7: Route verdrahten**

In `backend/app/api/routes/admin.py`, füge nach `post_schuljahr_historie_import_preview` an:

```python
@router.post("/schuljahr-historie-import")
async def post_schuljahr_historie_import(
    nutzer: Annotated[Nutzer, Depends(require_schulleitung)],
    db: Annotated[AsyncSession, Depends(get_db)],
    schuljahr_id: Annotated[int, Form()],
    file: Annotated[UploadFile, File()],
) -> HistorieImportResultOut:
    return await schuljahr_historie_import_service.commit_import(db, schuljahr_id, file, nutzer.id)
```

Ergänze `HistorieImportResultOut` im `from app.schemas.admin import (...)`-Block.

- [x] **Step 8: Tests ausführen, Erfolg verifizieren**

Run: `docker exec absenzdash-backend python -m pytest tests/test_api_admin_schuljahr_historie_import.py -v`
Expected: alle Tests PASS.

- [x] **Step 9: Vollen Backend-Testlauf verifizieren**

Run: `docker exec absenzdash-backend python -m pytest -v`
Expected: alle Tests PASS.

- [x] **Step 10: Commit**

```bash
git add backend/app/services/schuljahr_historie_import_service.py backend/app/api/routes/admin.py \
  backend/tests/test_schuljahr_historie_import_service.py backend/tests/test_api_admin_schuljahr_historie_import.py
git commit -m "feat: add commit endpoint for retroactive schuljahr historie import with audit logging"
```

---

## Task 6: Frontend — Admin-Seite "Schuljahr-Import"

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/hooks/useSchuljahrHistorieImportPreview.ts`
- Create: `frontend/src/api/hooks/useSchuljahrHistorieImport.ts`
- Create: `frontend/src/pages/Admin/SchuljahrImport.tsx`
- Create: `frontend/src/pages/Admin/SchuljahrImport.test.tsx`
- Modify: `frontend/src/pages/Admin/AdminLayout.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Neu: `apiPostFormData<T>(path: string, formData: FormData): Promise<T>` in `client.ts` (kein bestehendes Upload-Muster wiederverwendbar, siehe Abweichung 7).
- Neue Route `/admin/schuljahr-import` → `SchuljahrImport`-Seite, neuer Tab in `AdminLayout`.

- [ ] **Step 1: Fehlschlagenden Test für `apiPostFormData` schreiben**

Füge in `frontend/src/api/client.test.ts` (Struktur/Mock-Muster wie die bestehenden `apiPost`-Tests dort) einen Test hinzu, der `apiPostFormData` mit einer `FormData`-Instanz aufruft und prüft, dass `fetch` mit `method: "POST"`, dem `X-WP-Nonce`-Header (aber explizit OHNE `Content-Type`-Header) und der `FormData` als `body` aufgerufen wird, sowie dass ein Non-OK-Response einen `ApiError` wirft (identisches Fehlerverhalten zu `apiPost`). Orientiere dich am exakten Aufbau der bestehenden `apiPost`-Tests in dieser Datei (`window.absenzdashConfig`-Mock, `global.fetch = vi.fn(...)`).

Run: `cd frontend && npm test -- client.test.ts`
Expected: FAIL — `apiPostFormData` existiert noch nicht.

- [ ] **Step 2: `apiPostFormData` implementieren**

In `frontend/src/api/client.ts`, füge nach `apiPut` (nach Zeile 54) ein:

```typescript
export async function apiPostFormData<T>(path: string, formData: FormData): Promise<T> {
  const config = getConfig();
  const response = await fetch(`${config.restUrl}/${path}`, {
    method: "POST",
    headers: { "X-WP-Nonce": config.nonce },
    body: formData,
  });
  if (!response.ok) {
    throw new ApiError(response.status, `POST ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}
```

(Bewusst kein `Content-Type`-Header — der Browser generiert die Multipart-Boundary selbst; ein manuell gesetzter `Content-Type: multipart/form-data` ohne Boundary würde den Request kaputt machen.)

Run: `cd frontend && npm test -- client.test.ts`
Expected: PASS.

- [ ] **Step 3: Types ergänzen**

In `frontend/src/api/types.ts`, füge am Ende an:

```typescript
export interface HistorieImportPreview {
  zeilen_gesamt: number;
  schueler_bekannt: number;
  schueler_neu: number;
  unbekannte_klassen: string[];
  uebersprungene_zeilen: number;
}

export interface HistorieImportResult {
  zeilen_verarbeitet: number;
  neu_angelegte_schueler: number;
  uebersprungene_zeilen: number;
}
```

- [ ] **Step 4: Hooks erstellen**

Erstelle `frontend/src/api/hooks/useSchuljahrHistorieImportPreview.ts`:

```typescript
import { useMutation } from "@tanstack/react-query";
import { apiPostFormData } from "../client";
import type { HistorieImportPreview } from "../types";

interface PreviewArgs {
  schuljahrId: number;
  file: File;
}

export function useSchuljahrHistorieImportPreview() {
  return useMutation({
    mutationFn: ({ schuljahrId, file }: PreviewArgs) => {
      const formData = new FormData();
      formData.append("schuljahr_id", String(schuljahrId));
      formData.append("file", file);
      return apiPostFormData<HistorieImportPreview>("admin/schuljahr-historie-import/preview", formData);
    },
  });
}
```

Erstelle `frontend/src/api/hooks/useSchuljahrHistorieImport.ts`:

```typescript
import { useMutation } from "@tanstack/react-query";
import { apiPostFormData } from "../client";
import type { HistorieImportResult } from "../types";

interface ImportArgs {
  schuljahrId: number;
  file: File;
}

export function useSchuljahrHistorieImport() {
  return useMutation({
    mutationFn: ({ schuljahrId, file }: ImportArgs) => {
      const formData = new FormData();
      formData.append("schuljahr_id", String(schuljahrId));
      formData.append("file", file);
      return apiPostFormData<HistorieImportResult>("admin/schuljahr-historie-import", formData);
    },
  });
}
```

- [ ] **Step 5: Fehlschlagenden Komponenten-Test schreiben**

Erstelle `frontend/src/pages/Admin/SchuljahrImport.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { useSchuljahrHistorieImportPreview } from "../../api/hooks/useSchuljahrHistorieImportPreview";
import { useSchuljahrHistorieImport } from "../../api/hooks/useSchuljahrHistorieImport";
import { SchuljahrImport } from "./SchuljahrImport";

vi.mock("../../api/hooks/useNavOptions");
vi.mock("../../api/hooks/useSchuljahrHistorieImportPreview");
vi.mock("../../api/hooks/useSchuljahrHistorieImport");

const NAV_OPTIONS = {
  bereiche: [],
  klassen: [],
  rolle: "schulleitung",
  schuljahre: [
    { id: 28, name: "2025/2026", start_datum: "2025-09-15", end_datum: "2026-07-29" },
    { id: 27, name: "2024/2025", start_datum: "2024-09-09", end_datum: "2025-07-30" },
  ],
  aktuelles_schuljahr_id: 28,
};

describe("SchuljahrImport", () => {
  it("renders a schuljahr dropdown populated from nav-options", () => {
    vi.mocked(useNavOptions).mockReturnValue({ data: NAV_OPTIONS } as any);
    vi.mocked(useSchuljahrHistorieImportPreview).mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
      reset: vi.fn(),
    } as any);
    vi.mocked(useSchuljahrHistorieImport).mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
    } as any);

    render(<SchuljahrImport />);
    expect(screen.getByText("2025/2026")).toBeInTheDocument();
    expect(screen.getByText("2024/2025")).toBeInTheDocument();
  });

  it("submits schuljahr_id and file to the preview mutation", async () => {
    const previewMutate = vi.fn();
    vi.mocked(useNavOptions).mockReturnValue({ data: NAV_OPTIONS } as any);
    vi.mocked(useSchuljahrHistorieImportPreview).mockReturnValue({
      mutate: previewMutate,
      data: undefined,
      isPending: false,
      error: null,
      reset: vi.fn(),
    } as any);
    vi.mocked(useSchuljahrHistorieImport).mockReturnValue({
      mutate: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
    } as any);

    render(<SchuljahrImport />);
    await userEvent.selectOptions(screen.getByLabelText("Schuljahr"), "27");
    const file = new File(["inhalt"], "archiv.csv", { type: "text/csv" });
    await userEvent.upload(screen.getByLabelText("ASV-CSV-Datei"), file);
    await userEvent.click(screen.getByText("Vorschau laden"));

    expect(previewMutate).toHaveBeenCalledWith({ schuljahrId: 27, file });
  });

  it("shows the preview summary and a confirm button once preview data is available", async () => {
    const confirmMutate = vi.fn();
    vi.mocked(useNavOptions).mockReturnValue({ data: NAV_OPTIONS } as any);
    vi.mocked(useSchuljahrHistorieImportPreview).mockReturnValue({
      mutate: vi.fn(),
      data: {
        zeilen_gesamt: 10,
        schueler_bekannt: 7,
        schueler_neu: 3,
        unbekannte_klassen: ["XYZ"],
        uebersprungene_zeilen: 1,
      },
      isPending: false,
      error: null,
      reset: vi.fn(),
    } as any);
    vi.mocked(useSchuljahrHistorieImport).mockReturnValue({
      mutate: confirmMutate,
      data: undefined,
      isPending: false,
      error: null,
    } as any);

    render(<SchuljahrImport />);
    expect(screen.getByText(/Zeilen gesamt: 10/)).toBeInTheDocument();
    expect(screen.getByText(/XYZ/)).toBeInTheDocument();

    await userEvent.click(screen.getByText("Import bestätigen"));
    expect(confirmMutate).toHaveBeenCalled();
  });
});
```

- [ ] **Step 6: Test ausführen, Fehlschlag verifizieren**

Run: `cd frontend && npm test -- SchuljahrImport`
Expected: FAIL — `SchuljahrImport.tsx` existiert noch nicht (Import-Fehler).

- [ ] **Step 7: Seite implementieren**

Erstelle `frontend/src/pages/Admin/SchuljahrImport.tsx`:

```tsx
import { useState } from "react";
import { useNavOptions } from "../../api/hooks/useNavOptions";
import { useSchuljahrHistorieImportPreview } from "../../api/hooks/useSchuljahrHistorieImportPreview";
import { useSchuljahrHistorieImport } from "../../api/hooks/useSchuljahrHistorieImport";
import styles from "../../components/StudentDetail/StudentDetail.module.css";

export function SchuljahrImport() {
  const { data: navOptions } = useNavOptions();
  const [schuljahrId, setSchuljahrId] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const {
    mutate: preview,
    data: previewResult,
    isPending: isPreviewing,
    error: previewError,
    reset: resetPreview,
  } = useSchuljahrHistorieImportPreview();
  const {
    mutate: confirmImport,
    data: importResult,
    isPending: isImporting,
    error: importError,
  } = useSchuljahrHistorieImport();

  const handlePreview = (event: React.FormEvent) => {
    event.preventDefault();
    if (schuljahrId === null || !file) {
      return;
    }
    preview({ schuljahrId, file });
  };

  const handleConfirm = () => {
    if (schuljahrId === null || !file) {
      return;
    }
    confirmImport({ schuljahrId, file });
  };

  return (
    <section className={styles.section}>
      <h3>Schuljahr-Import (rückwirkend)</h3>
      <p>
        Lädt eine archivierte ASV-BW-CSV für ein vergangenes Schuljahr hoch und ergänzt daraus die
        Klassenzugehörigkeits-Historie. Ändert nie die aktuellen Stammdaten (Name, aktive Klasse) bestehender
        Schüler.
      </p>
      <form
        className={styles.form}
        onSubmit={handlePreview}
        onChange={() => {
          resetPreview();
        }}
      >
        <label>
          Schuljahr
          <select
            aria-label="Schuljahr"
            value={schuljahrId ?? ""}
            onChange={(event) => setSchuljahrId(event.target.value ? Number(event.target.value) : null)}
            required
          >
            <option value="">Bitte wählen</option>
            {navOptions?.schuljahre.map((sj) => (
              <option key={sj.id} value={sj.id}>
                {sj.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          ASV-CSV-Datei
          <input
            aria-label="ASV-CSV-Datei"
            type="file"
            accept=".csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
        </label>
        <button type="submit" disabled={isPreviewing || schuljahrId === null || !file}>
          Vorschau laden
        </button>
        {previewError && <p className={styles.formError}>Vorschau fehlgeschlagen.</p>}
      </form>

      {previewResult && (
        <div>
          <h4>Vorschau</h4>
          <ul>
            <li>Zeilen gesamt: {previewResult.zeilen_gesamt}</li>
            <li>Bereits bekannte Schüler: {previewResult.schueler_bekannt}</li>
            <li>Neue Schüler: {previewResult.schueler_neu}</li>
            <li>Übersprungene Zeilen: {previewResult.uebersprungene_zeilen}</li>
            <li>
              Unbekannte Klassen:{" "}
              {previewResult.unbekannte_klassen.length > 0 ? previewResult.unbekannte_klassen.join(", ") : "keine"}
            </li>
          </ul>
          <button type="button" onClick={handleConfirm} disabled={isImporting}>
            Import bestätigen
          </button>
          {importError && <p className={styles.formError}>Import fehlgeschlagen.</p>}
        </div>
      )}

      {importResult && (
        <div>
          <h4>Ergebnis</h4>
          <ul>
            <li>Zeilen verarbeitet: {importResult.zeilen_verarbeitet}</li>
            <li>Neu angelegte Schüler: {importResult.neu_angelegte_schueler}</li>
            <li>Übersprungene Zeilen: {importResult.uebersprungene_zeilen}</li>
          </ul>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 8: Test ausführen, Erfolg verifizieren**

Run: `cd frontend && npm test -- SchuljahrImport`
Expected: alle Tests PASS.

- [ ] **Step 9: Admin-Navigation ergänzen**

In `frontend/src/pages/Admin/AdminLayout.tsx`, ergänze `TABS` (Zeile 4-9):

```typescript
const TABS = [
  { path: "/admin/schwellwerte", label: "Schwellwert-Regeln" },
  { path: "/admin/massnahmen", label: "Maßnahmen-Katalog" },
  { path: "/admin/entschuldigungsstatus", label: "Entschuldigungsstatus" },
  { path: "/admin/sync", label: "Sync-Einstellungen" },
  { path: "/admin/schuljahr-import", label: "Schuljahr-Import" },
];
```

In `frontend/src/App.tsx`, ergänze den Import (nach Zeile 7):

```typescript
import { SchuljahrImport } from "./pages/Admin/SchuljahrImport";
```

Ergänze die Route (nach Zeile 51):

```tsx
          <Route path="sync" element={<SyncSettings />} />
          <Route path="schuljahr-import" element={<SchuljahrImport />} />
```

- [ ] **Step 10: Vollen Frontend-Testlauf verifizieren**

Run: `cd frontend && npm test`
Expected: alle Tests PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/api/types.ts \
  frontend/src/api/hooks/useSchuljahrHistorieImportPreview.ts frontend/src/api/hooks/useSchuljahrHistorieImport.ts \
  frontend/src/pages/Admin/SchuljahrImport.tsx frontend/src/pages/Admin/SchuljahrImport.test.tsx \
  frontend/src/pages/Admin/AdminLayout.tsx frontend/src/App.tsx
git commit -m "feat: add Schuljahr-Import admin page for retroactive historie backfill"
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

- `GET /students?schuljahr_id=<ein_Jahr_ohne_Historie-Daten>` gegen den Dev-Stack aufrufen und prüfen, dass `items: []`/`total: 0` zurückkommt (statt weiterhin aller Schüler).
- Eine kleine Test-CSV über die neue Admin-Seite hochladen (Vorschau, dann Bestätigen) und per `docker exec absenzdash-db psql -U absenzdash -d absenzdash -c "SELECT * FROM schueler_klasse_historie WHERE schuljahr_id = <id>;"` prüfen, dass die erwarteten Zeilen entstanden sind.
- Nach einem echten Sync-Lauf prüfen, dass `<ASV_CSV_ARCHIVE_DIR>/<schuljahr-name-mit-bindestrich>.csv` existiert und dem Inhalt der zuletzt verarbeiteten Live-CSV entspricht.

- [ ] **Step 4: Commit (falls Step 1-3 Anpassungen erfordern)**

```bash
git add -A
git commit -m "fix: address issues found during full-suite/manual verification"
```

- [ ] **Step 5: TECH-SPEC.md aktualisieren**

- §1.3 (Schüler-Stammdaten & Schüler↔Klasse-Zuordnung): ergänze einen Absatz zur CSV-Archivierung (`ASV_CSV_ARCHIVE_DIR`, ein Stand pro Schuljahr, Dateiname mit `/` → `-` sanitiert, bei jedem tatsächlich verarbeiteten Import überschrieben) und zum rückwirkenden Admin-Import (zweistufig: Vorschau ohne Schreiben, dann Bestätigen; schreibt ausschließlich `schueler_klasse_historie`, legt für unbekannte `externe_id` einen minimalen `Schueler`-Stammsatz an, rührt live `schueler`-Felder bestehender Schüler nie an).
- §2 (Datenbank-Schema): kein neues Feld/keine neue Tabelle (keine Schema-Änderung durch diesen Plan) — ggf. nur einen Verweis auf die Query-Semantik-Änderung von `GET /students`/`GET /students/{id}` (Roster-Basis im Historie-Modus ist jetzt ein INNER JOIN auf `schueler_klasse_historie`, nicht mehr `schueler` mit `nur_aktive=False`; `GET /students/{id}` liefert 404 statt eines Klassen-Fallbacks, wenn keine Historie-Zeile existiert).
- §3 (API-Vertrag): ergänze die zwei neuen Endpunkte `POST /admin/schuljahr-historie-import/preview` und `POST /admin/schuljahr-historie-import` (Multipart, `schulleitung`-only, Request-/Response-Felder wie in `HistorieImportPreviewOut`/`HistorieImportResultOut`).

- [ ] **Step 6: SPECS.md aktualisieren**

- §4/§7 (Datenmodell/Dashboard-Funktionen): ergänze bei der Schülerliste/-Detail-Beschreibung, dass ein vergangenes Schuljahr ohne (rückwirkenden) Datenimport eine leere Liste liefert bzw. Schüler-Detail mit 404 antwortet — nicht mehr die (fälschlich vollständige) Live-Schülerliste bzw. einen Klassen-Fallback. Ergänze einen Hinweis auf den neuen Admin-Import-Flow für rückwirkende Datenpflege.

- [ ] **Step 7: ROADMAP.md aktualisieren**

Trage den Eintrag "Rückwirkendes Schuljahr-Archiv, Roster-Filterung & CSV-Archivierung" als **Plan 17** unter "Abgeschlossen" ein (nächste freie Nummer nach Plan 16, in der Datei nachschauen), mit Link auf diesen Plan (`docs/superpowers/plans/2026-09-21-schuljahr-historie-rueckwirkend.md`) und dessen [Design-Dok](../specs/2026-09-21-schuljahr-historie-rueckwirkend-design.md). Entferne/ersetze den bisherigen "Design-Dok fertig, Umsetzungsplan offen"-Eintrag unter "Geplant" (aktuell Zeile 61 in `ROADMAP.md`) durch einen Verweis auf den jetzt abgeschlossenen Plan 17. Erwähne explizit die in "Wichtige Abweichungen" Punkt 6 gefundene Notwendigkeit, den Schuljahr-Namen im Archiv-Dateinamen zu sanitieren (`/` → `-`) — kein im Design-Dok vorgesehener, aber notwendiger Korrektur-Fund, analog zu Plan 16s `sync_bereiche`-Fund.

- [ ] **Step 8: Commit**

```bash
git add ROADMAP.md SPECS.md TECH-SPEC.md
git commit -m "docs: sync SPECS.md, TECH-SPEC.md and ROADMAP.md with the schuljahr-historie-rueckwirkend plan"
```
