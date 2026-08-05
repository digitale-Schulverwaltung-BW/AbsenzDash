# Bundle D — "Bereiche"-Abschnitt im WP-Backend entschlacken (Design)

Stand: 2026-08-05

Kontext: [ROADMAP.md](../../../ROADMAP.md) "Bundle D". Ersetzt die in Plan 11 (siehe [Design-Dok](2026-07-29-wordpress-plugin-rollen-bereiche-design.md) Abschnitt "Nachtrag (2026-07-29)") bewusst als reinen, nicht-verbindlichen Einmal-Vorschlag gebaute `vorschlag-aus-abteilungen`-Logik durch eine verbindliche, automatische Ableitung.

## Ausgangslage

Die "Bereiche"-Konfigurationsseite im WP-Backend erlaubt heute die freie manuelle Zuordnung von Klassen zu Bereichen (`bereich_klasse`, m:n) sowie freie Neuanlage/Umbenennung/Löschung von Bereichen. Das ist unübersichtlich (viele Inputs) und redundant: die eigentliche Klasse→Abteilung-Zuordnung liegt bereits zuverlässig synchronisiert in `klasse.abteilung_id` vor (überschrieben bei jedem WebUntis-Sync, `webuntis_klassen_sync.py`). "Bereich" bildet an dieser Schule 1:1 die WebUntis-"Abteilung" ab (organisatorische Abteilungen A/B/C sind nur eine gedankliche Klammer ohne eigene Entität).

Verbleibender echter Pflegebedarf laut Klärung mit dem Auftraggeber (2026-08-05): Bereichsleiter-Zuordnung bleibt Admin-Aufgabe; "historische" Bereiche (Abteilungen, die WebUntis weiterhin synchronisiert, aber aktuell 0 Klassen mehr haben) sollen aus Diagrammen/Listen verschwinden können, ohne dass Datensätze/Zuordnungen tatsächlich gelöscht werden müssen.

## 1. Datenmodell

- `bereich` bekommt zwei neue Spalten:
  - `abteilung_id: int | None` — FK → `abteilung.id`, `UNIQUE`, nullable (erlaubt saubere Migration; im Normalbetrieb nach dem ersten Sync-Lauf immer gesetzt).
  - `ausgeblendet: bool` — `NOT NULL DEFAULT false`. Rein optischer Filter (siehe Abschnitt 4), keine Auswirkung auf Zugriffsrechte/Eskalation.
- `bereich.name` bleibt ein normales Textfeld, wird aber ab sofort ausschließlich vom Sync geschrieben (kein Admin-Schreibzugriff mehr über die API).
- `bereich_klasse` bleibt strukturell unverändert (Tabelle, FKs, `ondelete="CASCADE"`) — wird ab sofort ausschließlich vom neuen Sync-Schritt geschrieben statt vom Admin-`PUT`-Endpoint. Die bisherige m:n-Freiheit (eine Klasse in mehreren Bereichen) tritt durch die 1:1-Abteilungskopplung faktisch nicht mehr auf.
- `nutzer_bereich` (Bereichsleiter-Zuordnung) bleibt unverändert.
- Migration: bestehende `bereich`/`bereich_klasse`/`nutzer_bereich`-Zeilen werden verworfen (`DELETE FROM bereich` reicht dank Cascade), da das Feature noch jung ist und ohne nennenswerte Produktivnutzung. Der erste `sync_bereiche`-Lauf nach dem Deploy baut den Stand aus den aktuellen Abteilungen neu auf. Bereichsleiter-Zuordnungen müssen danach im WP-Backend neu gesetzt werden (einmaliger, expliziter Hinweis in der PR-Beschreibung/Doku, kein automatisches Matching-Skript).

## 2. Sync-Logik

Neuer Service `backend/app/services/webuntis_bereich_sync.py` mit `sync_bereiche(db: AsyncSession) -> None`. Arbeitet ausschließlich auf bereits synchronisierten DB-Daten (kein WebUntis-Client-Aufruf), wird im Orchestrator (`sync_orchestrator.py::run_sync_once`) direkt nach `sync_abteilungen`/`sync_klassen` (nach Zeile 124) aufgerufen.

Ablauf pro Sync-Lauf:

1. Alle `Abteilung`-Zeilen laden. Für jede Abteilung: existiert bereits ein `Bereich` mit `abteilung_id == abteilung.id`?
   - Nein → neuen `Bereich` anlegen. Name = `abteilung.long_name or abteilung.name`; bei Namenskollision zwischen zwei Abteilungen (gleicher `long_name`) wird der Name mit `f"{name} ({abteilung.name})"` disambiguiert — identische Logik zur bisherigen `vorschlag_aus_abteilungen`-Funktion (wird dafür in den neuen Service verschoben).
   - Ja → `bereich.name` nachziehen, falls sich `abteilung.long_name`/`abteilung.name` seit dem letzten Sync geändert hat.
2. `bereich_klasse` je betroffenem Bereich neu aufbauen: bestehende Zeilen für diesen `bereich_id` löschen, dann für jede `Klasse` mit `klasse.abteilung_id == bereich.abteilung_id` eine Zeile einfügen. Kein Diffing nötig (Schulgröße, günstig genug).
3. `ausgeblendet` und `nutzer_bereich` werden vom Sync **nie** angefasst — reine Admin-Domäne, bleiben über Sync-Läufe hinweg stabil.
4. Kein Löschen von `Bereich`-Zeilen: eine Abteilung mit aktuell 0 Klassen bekommt einfach eine leere `bereich_klasse`-Menge. Das ist der Fall, den der Admin über die Ausblenden-Checkbox behandelt — es gibt keinen automatischen "Lösch"-Mechanismus, weil `sync_abteilungen` Abteilungen selbst nie löscht (nur Upsert, siehe Bestandscode) und ein hart gelöschter Bereich beim nächsten Sync ohnehin wieder entstünde.

## 3. Backend-API-Änderungen

- `GET /admin/bereiche` → `BereichOut` um `klasse_namen: list[str]` (read-only Anzeige statt IDs) und `ausgeblendet: bool` erweitert. `abteilung_id` wird mitgeliefert, `name` bleibt drin, ist aber nicht mehr client-editierbar.
- `PUT /admin/bereiche`: Payload-Schema (`BereichIn`) schrumpft auf `{id: int, ausgeblendet: bool, leiter: list[BereichLeiterIn]}[]` — kein `name`, kein `klasse_ids` mehr. Unbekannte `id` weiterhin 422. Der Endpoint kann keine `Bereich`-Zeilen mehr anlegen oder löschen (das übernimmt ausschließlich der Sync); ein Payload mit fehlender bekannter `id` ist schlicht ein Validierungsfehler, kein "Bereich entfernen".
- Entfernt: `GET /admin/klassen`, `GET /admin/bereiche/vorschlag-aus-abteilungen`, Schema `BereichVorschlagOut`, Service-Funktion `vorschlag_aus_abteilungen` (ersetzt durch `sync_bereiche`), `list_klassen`.
- `GET /admin/abteilungen` bleibt unangetastet (außerhalb des Scopes von Bundle D, aktuell ohnehin nicht von der Bereiche-Seite konsumiert).

## 4. Downstream-Konsumenten

- `app/api/deps.py::resolve_bereich_scope`, `app/services/student_query.py` (Bereich-Filter), `app/services/eskalations_pruefung.py` (Empfänger-Auflösung): **unverändert**. Sie lesen weiterhin `bereich_klasse`/`nutzer_bereich` — nur die Quelle der `bereich_klasse`-Zeilen ändert sich (Sync statt Admin-PUT), die Query-Shapes bleiben identisch.
- `app/services/dashboard_query.py::get_nav_options`:
  - Der `Bereich`-Query bekommt zusätzlich `.where(Bereich.ausgeblendet.is_(False))`, damit ausgeblendete Bereiche aus Nav-Dropdown und darauf aufbauenden Diagrammen verschwinden.
  - Der dokumentierte `func.min()`-Workaround für "Klasse kann in mehreren Bereichen sein" (aktuelle Zeilen 51-58) entfällt und wird durch einen einfachen `dict`-Aufbau ersetzt — die zugrundeliegende Mehrdeutigkeit ist durch die 1:1-Abteilungskopplung strukturell nicht mehr möglich. Der zugehörige Eintrag in ROADMAP.md → "Technical debt" (`klasse_bereich_map` in `get_nav_options`) wird als erledigt markiert.
- Übrige `bereich_klasse`-Joins in `dashboard_query.py` (Stats-Aggregation): unverändert, iterieren ohnehin nur über die bereits sichtbaren/gefilterten Bereiche.

## 5. WordPress-Backend-UI

`class-bereiche-seite.php` / `bereiche-seite.js` werden deutlich vereinfacht:

- Entfernt: "Aus WebUntis-Abteilungen vorbefüllen"-Button, "Bereich hinzufügen"-Button, "Entfernen"-Button pro Zeile.
- Pro Zeile (eine pro vom Sync geliefertem Bereich):
  - **Name** — read-only Label statt Text-Input.
  - **Klassen** — read-only Anzeige (z.B. kommagetrennte Liste aus `klasse_namen`) statt Multiselect.
  - **Bereichsleiter** — bleibt editierbares Multiselect wie heute (`leiter`-Payload unverändert).
  - **Ausblenden** — neue Checkbox, gebunden an `ausgeblendet`.
- "Speichern"-Button bleibt, sendet je Zeile nur noch `{id, ausgeblendet, leiter}` an `PUT /admin/bereiche`.
- `laden()` ruft `GET /admin/klassen` nicht mehr auf (Klassennamen kommen direkt aus `GET /admin/bereiche`); `vorbefuellen()` entfällt komplett.

## Testing

- Backend: neue Tests für `sync_bereiche` (Neuanlage, Namens-Update bei Abteilungsumbenennung, `bereich_klasse`-Neuaufbau, Namenskollision-Disambiguierung, `ausgeblendet`/`nutzer_bereich` bleiben bei wiederholtem Sync unangetastet). Angepasste Tests für `bereich_service.replace_bereiche` (jetzt nur noch `ausgeblendet`/`leiter`-Update) und `dashboard_query.get_nav_options` (Ausblenden-Filter, entfernter `func.min()`-Pfad). Bestehende Tests, die auf `klasse_ids`/`name` im `PUT`-Payload aufbauen, müssen angepasst werden (`test_bereich_service.py`, `test_api_deps_scope.py`, `test_student_query.py`, `test_eskalations_pruefung.py`, `test_dashboard_query.py` — letztere vier ggf. nur an Fixture-Aufbau, nicht an Assertions, da die Konsumenten-Query-Shape gleich bleibt).
- Migration: verifizieren, dass ein frischer Sync-Lauf nach der Migration `bereich`/`bereich_klasse` korrekt aus dem Abteilungs-/Klassenbestand aufbaut.
- WP-Plugin: manueller Test im WP-Backend (Seite lädt, Bereichsleiter-Zuordnung speichern, Ausblenden-Checkbox togglen, ausgeblendeter Bereich verschwindet aus dem Dashboard-Dropdown).

## Nicht enthalten (bewusst außerhalb des Scopes)

- Kein automatisches Matching/Migrations-Skript für bestehende Bereichsleiter-Zuordnungen — werden nach dem Deploy einmalig neu gesetzt.
- Keine Änderung an `GET /admin/abteilungen`.
- Keine Abteilungsleitungs-Rolle (siehe ROADMAP.md "Für spätere Version, falls nötig" — bewusst getrennt gehaltenes Thema).
