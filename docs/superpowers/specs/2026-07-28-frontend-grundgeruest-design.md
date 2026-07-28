# Design: Frontend-Grundgerüst (React/TS-SPA) — Navigation & Landing-Dashboard

Stand: 2026-07-28

Begleitdokument zu [SPECS.md](../../../SPECS.md) (Abschnitt 2/7) und [TECH-SPEC.md](../../../TECH-SPEC.md) (Abschnitt 3, API-Vertrag). Deckt den ersten Ausbauschritt von Roadmap-Punkt 1 ("Frontend: React/TS-SPA") ab: technisches Grundgerüst inklusive einer ersten echten Seite (rollenabhängiges Kennzahlen-Dashboard mit hierarchischer Navigation). Schülerliste, Schüler-Detail, Admin-Bereich und PDF-Export-Anbindung sind bewusst **nicht** Teil dieses Plans — eigene Folge-Pläne (siehe [ROADMAP.md](../../../ROADMAP.md)).

## 1. Ziel

Ein WP-Plugin-eingebettetes React/TS-SPA-Grundgerüst mit:
- Auth gegen den bestehenden WP-Reverse-Proxy (Nonce-Pflicht, siehe TECH-SPEC.md §3),
- Routing-Grundgerüst (react-router) mit vorbereiteter, noch nicht befüllter Platzhalter-Route für die Schülerliste,
- rollenabhängiger hierarchischer Navigation (Bereich-/Klasse-Dropdowns),
- einer Landing-Page mit Kennzahlen-Dashboard (Ø Fehltage/-stunden, Klassenbuch-Einträge, Maßnahmen-Anzahl, jeweils mit Vergleichsbalken zur nächsttieferen Organisationseinheit).

## 2. Architektur & Tech-Stack

Neues Top-Level-Verzeichnis `frontend/` (eigenes Package, getrennt von `backend/` und `wordpress-plugin/`):

- **Vite + React + TypeScript** als Build-Tooling/Framework.
- **react-router** für URL-basiertes Routing.
- **@tanstack/react-query** für Server-State (Caching, Re-Fetch, Loading/Error-Handling) statt eigenem State-Management dafür.
- **recharts** für die Vergleichsbalken.
- **Reines CSS (CSS-Module)**, kein Component-Framework (Headless-Ansatz, passt zum schlanken Intranet-Charakter, kein zusätzliches Theming-System zu lernen).

**Build-Output:** `vite build` schreibt direkt nach `wordpress-plugin/absenzdash/assets/spa/` (via `build.outDir` in `vite.config.ts`, `manifest: true` für die gehashten Dateinamen) — kein separater Kopier-Schritt.

**Einbindung im Plugin** (`wordpress-plugin/absenzdash/includes/class-shortcode.php`): Der Shortcode rendert nur noch `<div id="absenzdash-root"></div>` statt der bisherigen Smoke-Test-Ansicht. `enqueue_assets()` unterscheidet zwei Modi:
- **Dev:** wenn eine neue Konstante (`ABSENZDASH_VITE_DEV_SERVER`, z.B. in `wp-config.php` auf `http://localhost:5173` gesetzt) definiert ist, wird das Vite-Dev-Server-Skript als ES-Modul plus `@vite/client` eingebunden (`script_loader_tag`-Filter für `type="module"`, da `wp_enqueue_script` das nicht nativ unterstützt) — volles HMR gegen echte WP-Session/Nonce/Backend-Daten.
- **Prod:** die gebauten Dateien aus `assets/spa/` werden anhand des Vite-Manifests (`assets/spa/.vite/manifest.json`) eingebunden.

`wp_localize_script` liefert wie bisher `restUrl` (Proxy-Basis-URL, jetzt `absenzdash/v1/api` ohne fest angehängten `/students`-Pfad) und `nonce`. Die bisherige `assets/smoke-test.js` wird durch die SPA ersetzt (Datei entfernt).

## 3. Backend-Erweiterung: Dashboard-Endpunkte

Neue Dateien: `backend/app/api/routes/dashboard.py` (Router-Prefix `/dashboard`), `backend/app/services/dashboard_query.py`, `backend/app/schemas/dashboard.py`. Beide Endpunkte nutzen `get_wordpress_proxy_nutzer` (bestehende Dependency) zur Authentifizierung.

### `GET /dashboard/nav-options`

Liefert die für den aufrufenden Nutzer wählbaren Navigations-Einheiten, rollenabhängig gefiltert:
- Klassenlehrkraft: `bereiche: []`, `klassen: [{id, name}]` nur die eigenen (aus `nutzer_klasse`).
- Bereichsleiter: `bereiche: [{id, name}]` nur die eigenen (aus `nutzer_bereich`), `klassen: [{id, name, bereich_id}]` alle Klassen dieser Bereiche.
- Schulleitung: `bereiche` = alle, `klassen` = alle (mit `bereich_id`).

Response ist eine flache Struktur; das Frontend leitet die Eltern-Kind-Beziehung (welche Klassen zu welchem Bereich gehören) über `bereich_id` clientseitig ab. Einmalig geladen und per react-query gecacht (ändert sich selten).

### `GET /dashboard/stats?bereich_id=&klasse_id=`

Beide Query-Parameter optional. Server validiert sie serverseitig gegen den Scope des aufrufenden Nutzers (analog zum bestehenden `resolve_scope`-Muster in `app/api/deps.py`; eine neue Hilfsfunktion löst zusätzlich die für die Rolle erlaubten `bereich_id`s auf) — eine fremde oder unbekannte ID führt zu `404`, konsistent mit dem bestehenden Muster in `get_scoped_schueler`.

Aggregation erfolgt **nicht** über `schueler_zaehlerstand` (das ist regel-/eskalationsspezifisch, kein reiner Durchschnittswert), sondern direkt über `fehlzeit`, `klassenbuch_eintrag`, `massnahme`, gefiltert auf:
- aktive Schüler (`schueler.aktiv = true`, konsistent mit dem `nur_aktive`-Default in `GET /students`),
- laufendes Schuljahr (Datum `>= einstellung.schuljahr_start_cache`),
- die durch `bereich_id`/`klasse_id` bestimmte Schülermenge (kein Parameter gesetzt ⇒ höchste dem Nutzer erlaubte Ebene, z.B. „alle Klassen der Schulleitung“).

Response:
```jsonc
{
  "level": "schule" | "bereich" | "klasse",
  "context": { "bereich_id": null, "bereich_name": null, "klasse_id": null, "klasse_name": null },
  "own": {
    "anzahl_schueler": 24,
    "avg_fehltage": 2.3,
    "avg_fehlstunden": 4.1,
    "avg_klassenbuch": 0.8,
    "anzahl_klassenbuch": 120,
    "anzahl_massnahmen": 15
  },
  "vergleich": [
    { "id": 3, "name": "AME56", "avg_fehltage": 1.9, "avg_fehlstunden": 3.2, "avg_klassenbuch": 0.5, "anzahl_klassenbuch": 40, "anzahl_massnahmen": 4 }
    // ein Eintrag pro nächsttieferer Einheit: Bereiche (bei level=schule) bzw. Klassen (bei level=bereich); leer bei level=klasse
  ]
}
```

Kein Gauge-/Zeiger-Widget: „Zeiger“ aus der ursprünglichen Idee wird als einfache Zahl-Karte + Vergleichsbalken umgesetzt (kein zusätzlicher Diagrammtyp, YAGNI).

## 4. Frontend-Struktur & Navigation

```
frontend/src/
  api/client.ts              # fetch-Wrapper, hängt X-WP-Nonce an, wirft bei Non-2xx-Antworten
  api/hooks/useNavOptions.ts # react-query: GET /dashboard/nav-options
  api/hooks/useStats.ts      # react-query: GET /dashboard/stats
  components/Navigation/     # Bereich-/Klasse-Dropdowns
  components/StatCard/       # Zahl-Karte (Ø-Wert)
  components/ComparisonChart/# Recharts-Balkenvergleich
  pages/Landing/              # Dashboard-Seite
  App.tsx                     # Router: Layout(Navigation+Outlet), "/" → Landing, "/klasse/:id" → Platzhalter ("Schülerliste folgt")
  main.tsx                    # mountet in #absenzdash-root, liest window.absenzdashConfig
```

**Navigation/Dropdown-Logik** (Datenquelle: `nav-options`, Auswahl in URL-Query-Params `?bereich=&klasse=` für Bookmarkability):

| Rolle | Bereich-Dropdown | Klasse-Dropdown |
|---|---|---|
| Klassenlehrkraft | keins | nur wenn >1 eigene Klasse (sonst fix), Default „alle“ (Aggregat der eigenen Klassen) |
| Bereichsleiter | nur wenn >1 zugeordneter Bereich (sonst fix), inkl. „alle“ (Aggregat der eigenen Bereiche) | Klassen erst sichtbar/aktiv nach Wahl eines konkreten Bereichs; bei „alle“ deaktiviert |
| Schulleitung | „alle“ (schulweit) + jeder Bereich | wie bei Bereichsleiter: erst nach konkreter Bereichswahl aktiv |

Default beim ersten Laden = höchste dem Nutzer verfügbare Ebene („alle“).

**Landing-Page:** vier Stat-Karten (Ø Fehltage, Ø Fehlstunden, Klassenbuch Ø/Anzahl, Maßnahmen-Anzahl), je Karte der `own`-Wert plus darunter der `vergleich`-Balkenvergleich. Balken sind in diesem Plan **nicht klickbar** — die Platzhalter-Route `/klasse/:id` existiert bereits im Router, wird aber erst vom Folge-Plan (Schülerliste/-Detail) verlinkt und befüllt.

## 5. Fehlerbehandlung

React-query-Fehler (Netzwerk, 401/403 — z.B. abgelaufene Nonce —, 404) werden lokal pro Bereich angezeigt („Fehler beim Laden“ statt Absturz), kein globales Error-Boundary-Redesign. Kein automatischer Nonce-Refresh — bei abgelaufener Nonce hilft ein Seiten-Reload; das ist eine bekannte WordPress-Grenze, keine Sonderbehandlung in diesem Plan.

## 6. Testing

- **Backend:** pytest für `/dashboard/nav-options` und `/dashboard/stats` — Rollen-Scope-Fälle (Klassenlehrkraft ohne `bereich_id`-Param, Bereichsleiter mit fremder `bereich_id`/`klasse_id` → 404, Schulleitung beliebig), Aggregations-Korrektheit (Ø-Berechnung, Schuljahres-Datumsfilter, aktive-Schüler-Filter).
- **Frontend:** Vitest + React Testing Library für die Navigation-Dropdown-Logik (alle drei Rollen-Fälle) und die Stat-Karten/Vergleichsdarstellung mit gemockten react-query-Daten. Kein E2E (WP-Abhängigkeit) — manueller Smoke-Test gegen die echte WP-Instanz analog Plan 8.

## 7. Bewusst nicht enthalten

- Schülerliste (`GET /students`-Anbindung), Schüler-Detail, Maßnahmen-/Ausnahmen-Formulare — eigener Folge-Plan.
- Admin-Bereich (Schwellwert-Regeln, Maßnahmen-Katalog, Sync-Einstellungen) — eigener Folge-Plan.
- PDF-Export-Anbindung im Frontend — eigener Folge-Plan.
- Automatischer Nonce-Refresh bei Ablauf (siehe Abschnitt 5).
- Gauge-/Zeiger-Diagrammtyp (durch Zahl-Karte + Balkenvergleich ersetzt, siehe Abschnitt 3).
