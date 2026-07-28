# Design: Schülerliste, Schüler-Detail, Maßnahmen-/Ausnahmen-Formulare

Stand: 2026-07-28

Begleitdokument zu [SPECS.md](../../../SPECS.md) (Abschnitt 7) und [TECH-SPEC.md](../../../TECH-SPEC.md) (Abschnitt 3, API-Vertrag). Deckt Roadmap-Punkt "Schülerliste (`GET /students`-Anbindung), Schüler-Detail, Maßnahmen-/Ausnahmen-Formulare" ab — bewusst als ein zusammenhängender Plan, da Liste und Detail+Formulare fachlich eng verzahnt sind (Liste verlinkt auf Detail). Baut auf dem Frontend-Grundgerüst aus [Plan 9](2026-07-28-frontend-grundgeruest-design.md) auf (Navigation, react-query-Setup, Auth gegen den WP-Proxy).

## 1. Ziel

Rollenabhängige Schülerliste mit Filtern und Status-Badges, eine Schüler-Detailseite mit Fehlzeiten-/Klassenbuch-/Maßnahmen-/Ausnahmen-/Benachrichtigungs-Historie, sowie Formulare zum Erfassen von Maßnahmen und zum Setzen/Aufheben von Ausnahmen (SPECS.md Abschnitt 7, zweiter und dritter Punkt).

## 2. Backend-Erweiterung: Katalog-Endpunkt

Neue Route in `backend/app/api/routes/students.py` (bestehender Router, `prefix="/students"`, normale `get_wordpress_proxy_nutzer`-Auth wie die übrigen Routen — **kein** `require_schulleitung`):

### `GET /students/catalog`

Liefert Stammdaten, die Liste/Detail/Formulare zur Klartext-Anzeige bzw. Formular-Auswahl brauchen, aber bisher nur admin-only (`MassnahmenTyp`) oder gar nicht (`ExcuseStatus`, `ClassregCategory`) exponiert waren:

```jsonc
{
  "massnahmen_typen": [{ "id": 1, "name": "Gespräch" }],
  "excuse_statuses": [{ "id": 1, "name": "E", "long_name": "Entschuldigt" }],
  "classreg_categories": [{ "id": 1, "name": "...", "long_name": "..." }]
}
```

- `massnahmen_typen`: nur `aktiv=true` (analog dem `aktiv`-Flag aus Plan 6), da nur aktive Typen im Formular auswählbar sein sollen.
- `excuse_statuses`/`classreg_categories`: alle Einträge (keine Filterung), reine Klartext-Auflösung für IDs, die in `FehlzeitOut.excuse_status_id`/`KlassenbuchEintragOut.kategorie_id` auftauchen.

Neue Schemas in `app/schemas/students.py`: `MassnahmenTypOut`, `ExcuseStatusCatalogOut`, `ClassregCategoryOut`, `StudentCatalogOut`. Implementierung in `student_query.py`: neue Funktionen `load_all_excuse_statuses`/`load_all_classreg_categories` (ungefiltertes Pendant zu den bestehenden `load_excuse_status_map`/`load_classreg_category_map`, die nur nach IDs filtern) plus ein direktes `select(MassnahmenTyp).where(MassnahmenTyp.aktiv.is_(True))` im Route-Handler (analog zum bestehenden Typ-Lookup in `create_measure`).

Kein sonstiger Backend-Change: `GET /students`, `GET /students/{id}`, `POST .../measures`, `POST`/`DELETE .../exemptions` sind bereits vollständig (siehe TECH-SPEC.md §3, `students.py`).

## 3. Frontend-Struktur & Routing

```
frontend/src/
  api/hooks/useStudentCatalog.ts   # react-query: GET /students/catalog
  api/hooks/useStudents.ts         # react-query: GET /students (Liste, Filter-Params)
  api/hooks/useStudentDetail.ts    # react-query: GET /students/{id}
  api/hooks/useCreateMeasure.ts    # react-query mutation: POST .../measures
  api/hooks/useCreateExemption.ts  # react-query mutation: POST .../exemptions
  api/hooks/useRevokeExemption.ts  # react-query mutation: DELETE .../exemptions/{id}
  components/StatusBadge/          # Zählerstand-/Benachrichtigt-Badge (in Liste UND Detail-Kopfbereich)
  components/NotificationFlyout/   # Hover-Flyout für Benachrichtigt-Badge
  components/StudentDetail/        # Fehlzeiten-Tabelle, Klassenbuch-Tabelle, Maßnahmen-Historie+Formular,
                                    # Ausnahmen-Liste+Formular, Benachrichtigungs-Historie
  pages/StudentList/                # Filterleiste + Tabelle + Pagination
  pages/StudentDetail/              # Detailseite, komponiert aus components/StudentDetail/*
  App.tsx                           # Routen: "/schueler" (Liste), "/schueler/:id" (Detail)
```

**Routing-Änderungen in `App.tsx`:** neue Routen `/schueler` und `/schueler/:id`. Die bisherige, nie verlinkte Platzhalter-Route `/klasse/:id` (`KlassePlatzhalter`) wird entfernt.

**Navigation (`components/Navigation/Navigation.tsx`):** zwei Tabs/Links, „Übersicht" (→ `/`) und „Schülerliste" (→ `/schueler`), beide erhalten die aktuellen `?bereich=&klasse=`-Query-Params beim Wechsel (`useSearchParams` + `Link`, keine neue State-Quelle).

## 4. Schülerliste (`pages/StudentList/`)

**Scope/Filter-State**, alles in Query-Params:
- `bereich`/`klasse` — wie bisher aus der Navigation übernommen, mappen auf `bereich_id`/`klasse_id` bei `GET /students`.
- `min_stufe` — Select (leer / 1 / 2 / 3), mappen auf `min_stufe`.
- `nur_auffaellige` — Checkbox, mappen auf `nur_auffaellige`.
- `offset` — aus der Pagination, `limit` fest 50 (Default des Backends).

Kein zusätzliches Klasse-Dropdown in der Filterleiste selbst — die Klassenauswahl kommt ausschließlich aus der gemeinsamen Navigation, um keine zwei konkurrierenden Klassen-Selects zu haben.

**Tabelle**, eine Zeile pro `StudentOverviewOut`:

| Name | Klasse | Zählerstand je Regel | Benachrichtigt | Ohne Maßnahme |
|---|---|---|---|---|
| Nachname, Vorname (Link → `/schueler/:id`) | `klasse.name` (oder „—") | Ein `StatusBadge` pro `zaehlerstand`-Eintrag (Regel-Typ als Label, `erreichte_stufe_nr` als Farbstufe: grau=`null`, sonst gelb/orange/rot je nach Stufenzahl) | `StatusBadge` (grau=`letzte_benachrichtigung: null`, blau=vorhanden) mit `NotificationFlyout` on hover: pro `empfaenger`-Eintrag Rolle+Person, oder der `status`-Text (`kein_empfaenger`/`initial_import`/...) statt Empfängerliste | Zeile bekommt bei `ohne_massnahme_seit_benachrichtigung=true` eine visuelle Hervorhebung (z.B. `data-highlighted`-Attribut → roter linker Rand per CSS-Modul), für **alle** Rollen sichtbar — kein Rollen-Sonderfall im Frontend, da `nav-options` aktuell keine Rolle liefert und das Flag fachlich für jede Rolle korrekt ist |

**Pagination:** „Zurück"/„Weiter"-Buttons unterhalb der Tabelle, deaktiviert an den Rändern (`offset === 0` bzw. `offset + limit >= total`), Textanzeige „`offset+1`–`min(offset+limit, total)` von `total`".

**Lade-/Fehlerzustand:** analog Landing-Page (lokale Meldung „Lädt…"/„Fehler beim Laden", kein globales Error-Boundary-Redesign).

## 5. Schüler-Detail (`pages/StudentDetail/`)

Lädt `GET /students/{id}` (`useStudentDetail`) und `GET /students/catalog` (`useStudentCatalog`, gecacht analog `nav-options`). Abschnitte:

1. **Kopfbereich**: Name, Klasse, Zählerstände (gleiche `StatusBadge`-Darstellung wie in der Liste).
2. **Fehlzeiten-Tabelle**: Datum, Typ, Zeit (`start_zeit`–`end_zeit`), Fach (oder „—"), Entschuldigungsstatus (`excuse_status_id` → `long_name`/`name` aus dem Katalog, „—" bei `null`), Grund-Text.
3. **Klassenbuch-Tabelle**: Datum, Kategorie (`kategorie_id` → `long_name`/`name` aus dem Katalog), Text.
4. **Maßnahmen-Historie + -Formular**: Tabelle bestehender Einträge (Typ, Datum, Notiz, `erfasst_von_name`) darüber; Formular darunter (Typ-`<select>` aus `massnahmen_typen`, `<input type="date">`, Notiz-`<textarea>`) → `useCreateMeasure`-Mutation (`POST .../measures`), bei Erfolg Invalidierung des Detail-Query-Keys (react-query `invalidateQueries`).
5. **Ausnahmen-Liste + -Formular**: Liste aller Einträge (Kategorie, Grund, `gueltig_bis` oder „unbefristet", `aktiv`); bei `aktiv=true` ein „Aufheben"-Button → `useRevokeExemption` (`DELETE .../exemptions/{id}`, danach Invalidierung). Formular darunter zum Neuanlegen: Kategorie-Radio (`fehlzeiten`/`klassenbuch`), Grund-Text, optionales Enddatum → `useCreateExemption` (`POST .../exemptions`, danach Invalidierung).
6. **Benachrichtigungs-Historie**: Tabelle, Regel/Typ, Stufe, `gesendet_am`, Empfänger (Rolle+Person je Eintrag) oder Status-Text — gleiche Datenquelle/Aufbereitung wie der `NotificationFlyout` in der Liste, hier aber als vollständige Tabelle statt Hover-Ausschnitt.

**Formulare allgemein:** einfache native HTML-Forms (kein Formular-Library-Zusatz, passt zum bisherigen "reines CSS, kein Component-Framework"-Ansatz aus Plan 9). Submit-Button deaktiviert während die Mutation läuft (`isPending`), Fehler werden inline unterhalb des Formulars angezeigt (kein Toast-System). Bei Erfolg wird das Formular zurückgesetzt (kontrollierte Inputs auf Ausgangswerte).

## 6. Fehlerbehandlung

Analog Plan 9 (Abschnitt 5): react-query-Fehler (Netzwerk, 401/403, 404 bei fremder/unbekannter `schueler_id` — `get_scoped_schueler` liefert bereits 404) werden lokal angezeigt, kein Absturz. Mutations-Fehler (z.B. 404 bei bereits gelöschter Ausnahme, 422 bei ungültigem Formular-Input) erscheinen inline im jeweiligen Formular. Kein automatischer Nonce-Refresh (bekannte Grenze, siehe Plan 9).

## 7. Testing

- **Backend**: pytest für `GET /students/catalog` — Zugriff für alle drei Rollen (kein Admin-Check), nur `aktiv=true`-Maßnahmen-Typen, vollständige Excuse-Status-/Kategorie-Listen unabhängig von tatsächlich genutzten IDs.
- **Frontend**: Vitest + React Testing Library für:
  - `StudentList`: Filter-Interaktion (Klasse aus Navigation, `min_stufe`, `nur_auffaellige`), Badge-/Flyout-Rendering, Pagination-Button-Zustände, Hervorhebung bei `ohne_massnahme_seit_benachrichtigung`.
  - `StudentDetail`: Rendering aller Abschnitte mit gemockten Daten, Maßnahmen-Formular-Submit → Mutation aufgerufen → Cache-Invalidierung, Ausnahmen-Formular-Submit und „Aufheben"-Button analog.
- Kein E2E (WP-Abhängigkeit) — manueller Smoke-Test gegen die echte WP-Instanz analog Plan 8/9.

## 8. Bewusst nicht enthalten

- Admin-Bereich (Schwellwert-Regeln, Maßnahmen-Katalog-Pflege, Sync-Einstellungen) — eigener Folge-Plan (Roadmap-Punkt "Excuse-Status-Admin-Pflege" u.a.).
- PDF-Export-Anbindung im Frontend (Button/Link zu `GET /students/{id}/export.pdf`) — eigener Folge-Plan.
- Automatischer Nonce-Refresh bei Ablauf (bestehende Einschränkung aus Plan 9, unverändert).
- Rollenspezifisches Ein-/Ausblenden der „ohne Maßnahme seit Benachrichtigung"-Hervorhebung (SPECS.md nennt es explizit für Bereichsleitung/Schulleitung, wird hier aber bewusst für alle Rollen angezeigt, siehe Abschnitt 4 — keine Rollenauflösung im Frontend nötig, das Flag ist für jede Rolle sachlich korrekt).
