# Backend: REST-API fürs WP-Plugin — Admin-Konfiguration — Design

Stand: 2026-07-27. Aufbauend auf Plan 5 (Kern-Endpunkte, Scope-Check-Mechanismus, `get_wordpress_proxy_nutzer`) und der Eskalations-Engine (Plan 3/3.1) samt Sync-Job (Plan 2). Referenz: [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 3 (API-Vertrag, Gruppe 2), Abschnitt 2 (Datenbank-Schema); [SPECS.md](../../../SPECS.md) Abschnitt 3 (Rollen), 4 (Datenmodell), 7 (Admin-Bereich).

## Ziel

Die fünf in TECH-SPEC.md Abschnitt 3 spezifizierten Admin-Endpunkte umsetzen: Schwellwert-Regeln, Maßnahmen-Katalog und Entschuldigungsstatus pflegen, Sync-Intervall konfigurieren, außerplanmäßigen Sync anstoßen. Alle fünf sind ausschließlich für die Rolle `schulleitung` zugänglich — anders als die Kern-Endpunkte aus Plan 5, die scope-geprüft, aber rollenoffen sind.

## Scope-Einordnung

Deckt Gruppe 2 aus der Scope-Einordnung von Plan 5 ab. PDF-Export (Gruppe 3, `GET /students/{id}/export.pdf`) ist bewusst ein eigener, späterer Plan — andere Bibliotheks-Abhängigkeit, technisch unabhängig, im Brainstorming entschieden.

## Architektur & Modulstruktur

Neue Module in `backend/app/`:

```
app/
  api/
    deps.py                      # + require_schulleitung()
    routes/
      admin.py                   # neu: APIRouter, alle 5 Endpunkte
  schemas/
    admin.py                     # neu: Pydantic-Modelle fuer alle 5 Ressourcen
  services/
    threshold_rule_service.py    # neu: Diff/Upsert fuer schwellwert_regel + schwellwert_stufe
    measure_type_service.py      # neu: Diff/Upsert fuer massnahmen_typ (+ massnahmen_typ_regel)
    excuse_status_service.py     # neu: Diff/Upsert fuer excuse_status
    sync_settings_service.py     # neu: Einstellung lesen/schreiben + Scheduler-Reschedule
    sync_orchestrator.py         # bestehend: _run_once -> run_sync_once() umbenannt/exportiert
```

`main.py`: `app.include_router(admin_router)` ergänzen.

### Neue Dependency: `require_schulleitung`

In `app/api/deps.py`, baut auf `get_wordpress_proxy_nutzer` auf:

```python
async def require_schulleitung(
    nutzer: Annotated[Nutzer, Depends(get_wordpress_proxy_nutzer)],
) -> Nutzer:
    if nutzer.rolle != "schulleitung":
        raise HTTPException(status_code=403, detail="Schulleitung required")
    return nutzer
```

Wird von allen fünf Endpunkten als Dependency verwendet (liefert den `Nutzer` gleich mit, für Audit-Log-Einträge — kein zweites `get_wordpress_proxy_nutzer` nötig).

### Gemeinsames Diff/Upsert-Muster (threshold-rules, measure-types, excuse-statuses)

Alle drei Ressourcen sind Listen mit `PUT`-Vollersatz-Semantik, aber **keine** naive Delete-All-Insert-All-Implementierung (würde IDs unnötig invalidieren und Historie kaputt referenzieren). Stattdessen pro Ressource:

1. Bestehende Zeilen aus der DB laden, nach `id` indizieren.
2. Für jedes Item im Payload: `id` gesetzt und existiert → Update der Felder; `id` fehlt → neue Zeile anlegen.
3. Für jede DB-Zeile, deren `id` **nicht** im Payload vorkommt: Lösch-Versuch.
   - Gelingt (keine Referenz von außen) → Zeile weg.
   - `IntegrityError` (FK-Verletzung, z.B. historisch verwendet) → gesamte Transaktion rollback, Response **409** mit Klartext-Meldung, welches Item betroffen ist und dass stattdessen deaktiviert werden soll. Damit verschwinden versehentlich angelegte, nie genutzte Einträge (Tippfehler-Fall) sauber, während historisch referenzierte Einträge erhalten bleiben.
4. Bei Erfolg: `db.commit()`, Response = aktueller Gesamtzustand (wie `GET`).

Threshold-Rules haben zusätzlich eine verschachtelte Ebene (`stufen` pro `regel`) — gleiches Diff/Upsert/Lösch-Versuch-Muster, eine Ebene tiefer, innerhalb derselben Transaktion.

Vor dem Diff/Upsert: fachliche Validierung pro Ressource (siehe unten) mit **422** bei Verstoß, bevor irgendetwas geschrieben wird.

## Endpunkte

### `GET/PUT /admin/threshold-rules`

Response/Body-Item (`ThresholdRuleOut`/`In`):
```json
{
  "id": 3,
  "typ": "fehlzeiten",
  "geltungsbereich": "klasse",
  "abteilung_id": null,
  "klasse_id": 12,
  "stufen": [
    {"id": 7, "stufe_nr": 1, "einheit": "fehltage", "schwellenwert": 4,
     "fehlzeiten_filter": "nur_unentschuldigt", "empfaenger_rollen": ["klassenlehrkraft"]}
  ]
}
```

Validierung vor Commit:
- `typ` ∈ `{"fehlzeiten", "klassenbuch"}`, `geltungsbereich` ∈ `{"schulweit", "abteilung", "klasse"}`
- `geltungsbereich == "schulweit"` ⇒ `abteilung_id` und `klasse_id` beide `null`; `"abteilung"` ⇒ nur `abteilung_id` gesetzt; `"klasse"` ⇒ nur `klasse_id` gesetzt — sonst 422
- Referenzierte `abteilung_id`/`klasse_id` müssen existieren — sonst 422
- Höchstens eine Regel pro `(typ, geltungsbereich="schulweit")`, pro `(typ, abteilung_id)`, pro `(typ, klasse_id)` — App-seitiger Check für saubere 422-Meldung; die bestehenden partiellen Unique-Indizes greifen als Backstop
- Jede Regel braucht mindestens eine Stufe; `stufe_nr` eindeutig innerhalb der Regel; `einheit` ∈ `{"fehltage","fehlstunden"}` bei `typ="fehlzeiten"` (bei `"klassenbuch"` `null`, da hier nicht unterschieden wird — siehe `_zaehle_fuer_stufe` in `eskalations_pruefung.py`, das für `klassenbuch` keine `einheit` auswertet); `fehlzeiten_filter` ∈ `{"nur_unentschuldigt","alle"}`; `empfaenger_rollen` ⊆ `ROLLEN`, nicht leer

Löschung einer Regel (`id` fehlt im Payload): hart, kein FK-Konflikt möglich (`schueler_zaehlerstand.regel_id`/`benachrichtigung.regel_id` sind `ON DELETE SET NULL`, siehe Migration `fb5871c3593e`) — Historie bleibt erhalten, verliert nur die Regel-Verknüpfung (analog zum bereits bestehenden Verhalten beim manuellen Löschen in der DB).

Audit-Log: `aktion="admin_threshold_rules_updated"`, `details={"anzahl_regeln": N}`.

### `GET/PUT /admin/measure-types`

**Migration:** `massnahmen_typ.aktiv: bool` (NOT NULL, `server_default=true`), Backfill bestehender Zeilen auf `true`.

Response/Body-Item (`MeasureTypeOut`/`In`):
```json
{"id": 2, "name": "Nachsitzen", "setzt_zaehler_zurueck": true, "aktiv": true, "betroffene_regel_ids": [3, 5]}
```

`betroffene_regel_ids` bildet `massnahmen_typ_regel` ab (many-to-many zu `schwellwert_regel`) — beim Update wird die Zuordnungstabelle für diesen Typ komplett neu geschrieben (kleine Tabelle, kein Diff nötig: alle Zeilen für `massnahmen_typ_id` löschen, dann neu einfügen).

Validierung: `name` nicht leer, eindeutig unter den (nach Verarbeitung) verbleibenden Zeilen (App-Check vor Commit für sauberes 422 statt IntegrityError durch den bestehenden Unique-Constraint); `betroffene_regel_ids` müssen existierende `schwellwert_regel.id`s sein.

Löschung (`id` fehlt im Payload): Versuch; `massnahme.massnahmen_typ_id` hat kein `ON DELETE SET NULL` → bei historisch verwendetem Typ **409** ("Maßnahmen-Typ 'X' wurde bereits verwendet, bitte stattdessen deaktivieren"). Nie verwendete Typen lassen sich weiterhin hart löschen.

Audit-Log: `aktion="admin_measure_types_updated"`, `details={"anzahl_typen": N}`.

### `GET/PUT /admin/excuse-statuses`

Response/Body-Item (`ExcuseStatusOut`/`In`):
```json
{"id": 4, "name": "Attest", "long_name": "Ärztliches Attest", "zaehlt_als_entschuldigt": true, "aktiv": true}
```

Validierung: `name` nicht leer und eindeutig (analog measure-types).

Löschung (`id` fehlt im Payload): gleiches Diff/Delete-Versuch-Muster wie bei measure-types — `fehlzeit.excuse_status_id` hat kein `ON DELETE SET NULL`, also bei bereits verknüpften Fehlzeiten-Einträgen **409** ("Entschuldigungsstatus 'X' wird bereits verwendet, bitte stattdessen deaktivieren"). Nie verwendete (z.B. versehentlich angelegte) Status lassen sich hart löschen — schließt die im Review aufgeworfene Lücke (Tippfehler bleibt sonst dauerhaft im System).

Audit-Log: `aktion="admin_excuse_statuses_updated"`, `details={"anzahl_status": N}`.

### `GET/PUT /admin/sync-settings`

`GET` Response:
```json
{"sync_interval_cron": "*/30 * * * *", "schuljahr_start_cache": "2025-09-01", "letzter_sync_am": "2026-07-27T04:30:00Z"}
```

`PUT` Body: nur `{"sync_interval_cron": "..."}` — die anderen beiden Felder sind rein informativ (TECH-SPEC: Schuljahresbeginn automatisch aus WebUntis, nicht editierbar) und werden bei `PUT` ignoriert, falls mitgeschickt.

Ablauf: `Einstellung`-Singleton laden (get-or-create wie in `sync_orchestrator._get_or_create_einstellung`, dieselbe Hilfsfunktion wiederverwenden — dafür aus dem Modul exportieren); `sync_interval_cron` per `CronTrigger.from_crontab(...)` validieren (ungültig ⇒ **422**, kein Schreiben); bei Erfolg `einstellung.sync_interval_cron` setzen, committen, **und sofort** `request.app.state.scheduler.reschedule_job(MAIN_SYNC_JOB_ID, trigger=CronTrigger.from_crontab(neuer_cron))` aufrufen — ohne das würde die Änderung erst nach dem nächsten (noch mit altem Intervall geplanten) Lauf greifen, weil `_run_main_sync_job` den Cron-Wert nur beim eigenen Feuern neu einliest.

Audit-Log: `aktion="admin_sync_settings_updated"`, `details={"sync_interval_cron": neuer_wert}`.

### `POST /admin/sync-now`

Kein Body. Ruft **einen einzelnen** Sync-Versuch synchron auf (TECH-SPEC: "synchron anstoßen") — bewusst **ohne** den Retry-Loop aus `run_full_sync` (der bis zu ~2h blockieren könnte, ungeeignet für einen HTTP-Request).

**Refactor in `sync_orchestrator.py`:** `_run_once` → `run_sync_once` (public), Signatur unverändert (`db: AsyncSession`). `run_full_sync` ruft intern weiterhin `run_sync_once` in seiner Retry-Schleife auf — keine Verhaltensänderung für den geplanten Job.

Route: eigene DB-Session öffnen, `run_sync_once(db)` awaiten.
- Erfolg → `200 {"status": "ok", "abgeschlossen_am": "<UTC-Zeitstempel>"}`
- `WebUntisError`/`OSError` → **502** mit Fehlerdetail (externe Abhängigkeit, kein Server-Bug)

Bekannter, akzeptierter Grenzfall (siehe Roadmap-Sektion "Technical debt" für vergleichbare bewusste Kompromisse): keine Sperre gegen einen zeitgleich laufenden geplanten Sync — unwahrscheinlich (Admin-Button, selten geklickt), im schlimmsten Fall doppelte Verarbeitung eines Laufs, keine Datenkorruption, da beide Läufe idempotent dieselben Zeiträume neu einlesen.

Audit-Log: `aktion="admin_sync_now_triggered"`, `details={"status": "ok"|"fehler"}`.

## Error Handling

- Nicht-`schulleitung` ⇒ **403** (neu, `require_schulleitung`)
- Fachliche Validierungsfehler (Konsistenz-Checks oben) ⇒ **422**, nichts wird geschrieben
- Pydantic-Validierungsfehler (Typen, Pflichtfelder) ⇒ **422** (FastAPI-Standard)
- Löschversuch einer historisch referenzierten Zeile (measure-types, excuse-statuses) ⇒ **409**, gesamte Transaktion rollback
- WebUntis-Fehler bei `sync-now` ⇒ **502**
- 401/400 aus `get_wordpress_proxy_nutzer` unverändert aus Plan 1

## Testing

Neue Testdateien pro Ressource (Diff/Upsert-Logik ist pro Ressource eigenständig genug für Isolation, analog zum bestehenden Ein-Service-pro-Ressource-Muster):
- `test_api_admin_threshold_rules.py` — Upsert/Delete, alle Konsistenz-Validierungen, Unique-Verstoß, verschachtelte Stufen-Diffs
- `test_api_admin_measure_types.py` — Upsert/Delete, `aktiv`-Toggle, 409 bei historisch verwendetem Typ, `betroffene_regel_ids`-Neuzuordnung
- `test_api_admin_excuse_statuses.py` — Upsert/Delete, 409 bei historisch verwendetem Status, erfolgreiche Löschung eines nie verwendeten (Tippfehler-Regressionstest für die im Review aufgeworfene Lücke)
- `test_api_admin_sync_settings.py` — gültiger/ungültiger Cron, sofortiges Reschedule des laufenden Scheduler-Jobs (Assertion auf `scheduler.get_job(...).trigger`)
- `test_api_admin_sync_now.py` — Erfolg, `WebUntisError` ⇒ 502, kein Retry-Loop (Mock zählt Aufrufe von `run_sync_once`)
- Alle fünf: 403 für `klassenlehrkraft`/`bereichsleiter`

Migrationstest analog bestehendem Muster (`test_models_*`) für `massnahmen_typ.aktiv`.

## Nicht-Ziele (bewusst nicht in diesem Plan)

- PDF-Export (`GET /students/{id}/export.pdf`) — eigener späterer Plan
- Frontend/SPA, die diese Endpunkte konsumiert — Roadmap-Punkt 2
- Sperrmechanismus gegen parallele Sync-Läufe (geplant + manuell) — akzeptierter Grenzfall, siehe oben
