# Backend: REST-API fürs WP-Plugin — Kern-Endpunkte — Design

Stand: 2026-07-27. Aufbauend auf dem Backend-Grundgerüst (Plan 1, WP-Proxy-Auth-Dependency `get_wordpress_proxy_nutzer`), dem Sync-Job (Plan 2) und der Eskalations-Engine inkl. E-Mail-Versand (Plan 3/3.1/4). Dies ist "Plan 5". Referenz: [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 3 (API-Vertrag); [SPECS.md](../../../SPECS.md) Abschnitt 3 (Rollen), 4 (Datenmodell), 7 (Dashboard-Funktionen).

## Ziel

Die in TECH-SPEC.md Abschnitt 3 spezifizierten Kern-Endpunkte (Übersicht, Detail, Maßnahmen erfassen, Ausnahmen setzen/aufheben) als tatsächliche FastAPI-Routen, scope-geprüft nach Rolle (`nutzer_klasse`/`nutzer_bereich`, nicht nur der Rollen-Header). Setzt die bereits vorhandene WP-Proxy-Auth-Dependency erstmals in echten Routen ein.

## Scope-Einordnung

TECH-SPEC Abschnitt 3 listet neun Endpunkte in drei fachlich unabhängigen Gruppen. Im Brainstorming entschieden, nur Gruppe 1 in diesem Plan umzusetzen — die anderen beiden werden eigene, spätere Roadmap-Punkte:

1. **Kern-Endpunkte** (dieser Plan): `GET /students`, `GET /students/{id}`, `POST /students/{id}/measures`, `POST /students/{id}/exemptions`, `DELETE /students/{id}/exemptions/{exemption_id}`. Braucht als Fundament den Scope-Check-Mechanismus.
2. **Admin-Konfiguration** (späterer Plan): `GET/PUT /admin/threshold-rules`, `GET/PUT /admin/measure-types`, `GET/PUT /admin/sync-settings`, `POST /admin/sync-now`, `GET/PUT /admin/excuse-statuses`.
3. **PDF-Export** (späterer Plan): `GET /students/{id}/export.pdf` — eigene Bibliotheks-Abhängigkeit, technisch unabhängig.

## Architektur & Modulstruktur

Neue Module in `backend/app/`:

```
app/
  api/
    deps.py                # bestehend (WP-Proxy-Auth) + neu: resolve_scope(), get_scoped_schueler()
    routes/
      __init__.py
      students.py           # APIRouter, alle 5 Endpunkte
  schemas/
    __init__.py
    students.py              # Pydantic-Response-/Request-Modelle
  services/
    massnahme_service.py     # bestehend, erweitert um audit_log-Eintrag
    ausnahme_service.py       # neu: create_ausnahme(), revoke_ausnahme()
```

`main.py`: `app.include_router(students_router)` in der Lifespan-Konfiguration ergänzen.

### Scope-Check (Kernstück, von allen Endpunkten genutzt)

`resolve_scope(db, nutzer: Nutzer) -> set[int] | None` in `app/api/deps.py`:
- `schulleitung` → `None` (Sentinel für „alle Klassen", inkl. Schüler mit `klasse_id IS NULL` — z.B. frisch importierte, noch nicht zugeordnete Schüler, SPECS.md Abschnitt 4)
- `bereichsleiter` → Menge der `klasse_id`s aus `bereich_klasse` für alle `bereich_id`s aus `nutzer_bereich` des Nutzers
- `klassenlehrkraft` → Menge der `klasse_id`s aus `nutzer_klasse` des Nutzers

Neue Dependency `get_scoped_schueler(schueler_id: int, ...) -> Schueler`: lädt den Schüler, prüft `schueler.klasse_id in scope` (bzw. `scope is None`). Nicht gefunden **oder** außerhalb des Scopes ⇒ **404** (nicht 403) — ein Aufrufer soll nicht unterscheiden können, ob eine ID nicht existiert oder ihm nur nicht zugänglich ist. Wird von allen fünf Endpunkten als Pfad-Parameter-Dependency verwendet.

## Endpunkte

### `GET /students`

Query-Parameter:
- `limit: int = 50`, `offset: int = 0` (Pagination von Anfang an, Brainstorming-Entscheidung)
- `klasse_id: int | None` — muss innerhalb des Scopes liegen, sonst leeres Ergebnis (kein Fehler)
- `bereich_id: int | None` — filtert auf die Klassen dieses Bereichs, geschnitten mit dem Scope
- `typ: Literal["fehlzeiten", "klassenbuch"] | None` — auf welchen Zählerstand sich `min_stufe`/`nur_auffaellige` beziehen; ohne Angabe gelten beide Typen (Treffer wenn *irgendein* Typ passt)
- `min_stufe: int | None` — nur Schüler mit `erreichte_stufe_nr >= min_stufe` (für den/die gewählten Typ(en))
- `nur_auffaellige: bool = False` — nur Schüler mit mindestens einer erreichten Stufe

Response: `{items: [...], total: int, limit: int, offset: int}`. Pro Zeile (`StudentOverviewOut`):
- Stammdaten: `id`, `vorname`, `nachname`, `klasse` (`{id, name}` oder `null`)
- `zaehlerstand`: pro Typ (`fehlzeiten`, `klassenbuch`) `{aktueller_stand, erreichte_stufe_nr}` — fehlt ein `SchuelerZaehlerstand`-Datensatz für einen Typ, wird `{aktueller_stand: 0, erreichte_stufe_nr: null}` synthetisiert (noch nie eine Regel ausgewertet)
- `letzte_benachrichtigung`: jüngste `Benachrichtigung` (`{stufe_nr, typ, gesendet_am, status, empfaenger}`) oder `null` — Basis fürs „Benachrichtigt"-Badge samt Flyout-Kurzinfo in der Übersicht (SPECS.md Abschnitt 7); die volle Historie liefert `GET /students/{id}`
- `ohne_massnahme_seit_benachrichtigung: bool` — `true`, wenn `letzte_benachrichtigung` existiert und danach keine `Massnahme` für diesen Schüler erfasst wurde. Wird immer berechnet und mitgeliefert; dass dies laut SPECS.md Abschnitt 7 nur für Bereichsleiter/Schulleitung hervorgehoben angezeigt wird, ist reine Frontend-Darstellungsentscheidung (späterer Plan), kein Backend-Rollen-Branch

### `GET /students/{id}`

Nutzt `get_scoped_schueler`. Response (`StudentDetailOut`):
- Stammdaten + `zaehlerstand` wie oben
- `fehlzeiten`: Liste aller `Fehlzeit`-Einträge (chronologisch)
- `klassenbuch`: Liste aller `KlassenbuchEintrag`-Einträge
- `massnahmen`: Liste aller `Massnahme`-Einträge, mit aufgelöstem Typ-Namen und Namen der erfassenden Person
- `ausnahmen`: nur **aktive** Ausnahmen (`aktiv=true`) — SPECS.md Abschnitt 7 nennt explizit „aktive Ausnahmen", keine Historie
- `benachrichtigungen`: volle `Benachrichtigung`-Historie (chronologisch)

### `POST /students/{id}/measures`

Body: `massnahmen_typ_id: int`, `datum: date`, `notiz: str | None`. Nutzt `get_scoped_schueler`, ruft `record_massnahme(db, schueler_id, massnahmen_typ_id, datum, notiz, erfasst_von_nutzer_id=nutzer.id)`.

**Änderung an `massnahme_service.record_massnahme`:** schreibt neu einen `audit_log`-Eintrag (`aktion="massnahme_erfasst"`, `resource_typ="massnahme"`, `user_id=erfasst_von_nutzer_id`). Fehlt aktuell — SPECS.md Abschnitt 4 fordert Audit-Log für Maßnahmen, wurde in Plan 3 nicht mit umgesetzt (Lücke, im Rahmen dieses Plans mit geschlossen, da jetzt erstmals ein Aufrufer/`nutzer_id` zur Verfügung steht).

Unbekannte `massnahmen_typ_id` ⇒ 404.

Response: 201, erfasste `Massnahme` (mit aufgelöstem Typ-Namen).

### `POST /students/{id}/exemptions`

Body: `kategorie: Literal["fehlzeiten", "klassenbuch"]`, `grund: str`, `gueltig_bis: date | None`. Neue Funktion `ausnahme_service.create_ausnahme(db, schueler_id, kategorie, grund, gueltig_bis, nutzer_id)`: legt `Ausnahme` an (`aktiv=True`), schreibt `audit_log`-Eintrag (`aktion="ausnahme_erstellt"`), committet.

Response: 201, erstellte `Ausnahme`.

### `DELETE /students/{id}/exemptions/{exemption_id}`

Kein Hard-Delete — TECH-SPEC nennt es „Ausnahme aufheben". Neue Funktion `ausnahme_service.revoke_ausnahme(db, exemption_id, nutzer_id)`: setzt `aktiv=False`, schreibt `audit_log`-Eintrag (`aktion="ausnahme_aufgehoben"`), committet.

Validierung in der Route: `exemption.schueler_id == schueler.id` (aus `get_scoped_schueler`) und `exemption.aktiv == True`, sonst **404** — sowohl für „existiert nicht", „gehört zu anderem Schüler" als auch „bereits aufgehoben" (idempotent im Sinne von: ein zweiter Aufruf für dieselbe ID liefert nach dem ersten Erfolg konsistent 404, kein Duplikat-Audit-Log-Eintrag).

Response: 204.

## Error Handling

- Out-of-scope oder nicht existent (Schüler, Ausnahme) ⇒ **404** einheitlich, nie 403 (kein Leaken von Existenz außerhalb des Scopes)
- Unbekannte `massnahmen_typ_id` ⇒ 404
- Pydantic-Validierungsfehler (fehlendes Pflichtfeld, falscher Typ, ungültiger `kategorie`-Wert) ⇒ 422 (FastAPI-Standard)
- Alle Routen hängen an der bestehenden `get_wordpress_proxy_nutzer`-Dependency (401 bei falschem/fehlendem Secret, 400 bei unbekannter Rolle — unverändert aus Plan 1)

## Testing

Neue `backend/tests/test_api_students.py`, Muster wie `test_main.py` (`httpx.ASGITransport` + `AsyncClient`, WP-Proxy-Header pro Request gesetzt). Schwerpunkte:
- Scope-Filterung pro Rolle (Klassenlehrkraft sieht nur eigene Klasse(n), Bereichsleiter nur Klassen des eigenen Bereichs, Schulleitung alles inkl. `klasse_id IS NULL`)
- Pagination (`limit`/`offset`/`total`) und alle Filter-Kombinationen von `GET /students`
- `GET /students/{id}` liefert alle referenzierten Unterlisten korrekt zusammengesetzt
- Maßnahme erfassen schreibt `audit_log`-Eintrag und setzt bei zurücksetzendem Typ den Zählerstand zurück (bestehendes Verhalten von `record_massnahme`, Regressionstest)
- Ausnahme erstellen/aufheben schreibt jeweils `audit_log`-Eintrag; aufheben ist idempotent (zweiter Aufruf ⇒ 404)
- 404 bei Scope-Verletzung (fremde Klasse) für alle fünf Endpunkte
- 422 bei ungültigem Request-Body

## Nicht-Ziele (bewusst nicht in diesem Plan)

- Admin-Konfigurationsendpunkte (`/admin/*`) — eigener späterer Roadmap-Punkt
- PDF-Export (`GET /students/{id}/export.pdf`) — eigener späterer Roadmap-Punkt
- Frontend/SPA, die diese Endpunkte konsumiert — Roadmap-Punkt 2
