# Design: WordPress-Plugin — Bereichsdefinition & Rollen-Zuweisung

Stand: 2026-07-29

## Kontext & Motivation

Roadmap-Punkt 1 ("Geplant"): die in Plan 8 bewusst ausgesparten Teile des WordPress-Plugins —
Bereichsdefinition-Admin-Seite und eine vollwertige Rollen-Zuweisungs-Oberfläche. Plan 8 hat dafür
nur eine Test-Übergangslösung gebaut (`class-benutzerprofil.php`: zwei Freitext-/Dropdown-Felder auf
der Standard-WP-Benutzerprofilseite, einzeln pro Nutzer editierbar). Für die Bereichsdefinition
(`bereich`/`bereich_klasse`/`nutzer_bereich`) existiert bislang **gar keine** UI und auch keine
Backend-Endpunkte — TECH-SPEC.md §3 listet sie nicht.

**Scope-Abgrenzung:**
- ✅ Rollen-Zuweisungs-Seite (ersetzt `class-benutzerprofil.php`)
- ✅ Bereichsdefinition-Seite (neu)
- ❌ Manuelle Zusatz-Klassenlehrkraft-Zuordnung (`nutzer_klasse` mit `quelle='manuell'`) — siehe
  "Bewusst nicht enthalten" unten
- ❌ Abteilungsleitungs-Rolle — eigener zukünftiger Roadmap-Punkt, siehe unten
- ❌ Excuse-Status-Admin-Pflege, Admin-Bereich (Schwellwerte/Maßnahmen/Sync) im SPA — bleiben
  Roadmap-Punkte 2/3

## Live-Verifikation (2026-07-29, gegen die reale WebUntis-Instanz)

Vor der Festlegung auf einen automatischen E-Mail-Abgleich wurde live gegen `getTeachers()`
geprüft (siehe [[verify-external-api-facts-live]]-Muster):

- **Kein E-Mail-Feld.** `getTeachers()` liefert `id`, `name`, `foreName`, `longName`, `title`,
  `active`, `dids` — keine E-Mail-Adresse. Ein automatischer WP-Nutzer-↔-WebUntis-Lehrkraft-Abgleich
  über E-Mail ist damit **nicht möglich**.
- **`name` ist das Lehrerkürzel**, nicht die numerische ID: 111 von 163 Einträgen exakt 3 Zeichen,
  Rest 1–9 Zeichen (längere Nachnamen-Kollisionen), durchgehend reine Buchstaben. `id` ist die
  numerische WebUntis-interne ID, identisch mit den `teacher1`/`teacher2`-Werten aus `getKlassen`
  (58/58 Treffer im Test) — das ist der Wert, der in `nutzer.webuntis_teacher_id` gespeichert wird.
- **`getKlassen()` liefert nur `teacher1`/`teacher2`**, kein drittes Feld für eine dritte
  Klassenlehrkraft (0/105 Klassen mit einem hypothetischen `teacher3`).

## Bewusst nicht enthalten: manuelle Klassenlehrkraft-Zuordnung

SPECS.md §2 erwähnt "zusätzliche Klassenlehrkraft-Zuordnungen über die WebUntis-Seed-Daten hinaus"
als Teil der WP-Backend-Oberfläche. WebUntis liefert an dieser Schule bereits zwei Klassenlehrkräfte
pro Klasse (`teacher1`/`teacher2`, automatisch geseedet als `nutzer_klasse` mit
`quelle='webuntis_seed'`, siehe TECH-SPEC.md §2.1) — das deckt den tatsächlichen Bedarf ab. Eine
dritte, manuell im WP-Backend nachgetragene Zuordnung wird daher **nicht** gebaut. SPECS.md §2 wird
entsprechend präzisiert (siehe "Dokumentation" unten).

## Zurückgestellt: Abteilungsleitungs-Rolle

Im Brainstorming kam die Frage auf, ob neben Klassenlehrkraft/Bereichsleiter/Schulleitung auch eine
vierte Rolle "Abteilungsleitung" abgebildet werden soll (WebUntis-Abteilungen sind an dieser Schule
oft zweigeteilt benannt, z.B. `B-ME` = Abteilung B, Bereich ME; `abteilung` existiert bereits als
Stammdaten-Tabelle seit Plan 3, aktuell nur für Schwellwert-Regel-Geltungsbereiche genutzt).

**Bewusst nicht Teil dieses Plans**, da es kein Zusatzfeld, sondern ein eigenständiger struktureller
Umbau wäre: neuer Rollen-Enum-Wert, neue `nutzer_abteilung`-m:n-Tabelle, eine dritte Scope-Ebene in
`resolve_scope`/`resolve_bereich_scope` (`deps.py`), Erweiterung der Empfänger-Auflösung in der
Eskalations-Engine/im Mailer (`schwellwert_stufe.empfaenger_rollen`), und eine Revision von
SPECS.md §3 ("Dreistufige Hierarchie"). Wird als neuer Punkt unter "Geplant" in ROADMAP.md
vorgemerkt, eigenes Brainstorming nötig.

## Neue Backend-Endpunkte

Alle unter `backend/app/api/routes/admin.py`, geschützt durch die bestehende
`require_schulleitung`-Dependency, analog zum bestehenden Whole-List-Replace-Muster
(`measure_type_service`/`threshold_rule_service`).

### `GET /admin/webuntis-teachers`

Live-Passthrough auf `WebUntisClient.call("getTeachers", {})`, liefert `{id: int, kuerzel: str}[]`
(gemappt aus `id`/`name`). Kein DB-Caching — die Seite wird selten geöffnet, ein zusätzlicher
Sync-Mechanismus/eine Cache-Tabelle wäre hier YAGNI. Backend-Fehler (WebUntis nicht erreichbar)
werden als `502` durchgereicht, analog zu `POST /admin/sync-now`.

### `GET /admin/klassen`

Volle, ungefilterte Klassenliste `{id: int, name: str}[]` (aktuell existiert nur die
scope-gefilterte Variante in `GET /dashboard/nav-options`). Wird für die Klassen-Mehrfachauswahl auf
der Bereichsdefinition-Seite gebraucht.

### `GET/PUT /admin/bereiche`

```
GET  -> [{id, name, klasse_ids: [int], leiter: [{nutzer_id, wp_user_id, email, name}]}]
PUT  <- [{id?, name, klasse_ids: [int], leiter: [{wp_user_id, email, name}]}]
     -> wie GET
```

`PUT` ersetzt die komplette Liste (Semantik wie `threshold_rule_service.replace_rules`):
- Validierung: `name` nicht leer, keine doppelten `name`/`id` im Payload (analog
  `measure_type_service._validate_payload`).
- Für jeden `leiter`-Eintrag: Get-or-Create auf `nutzer` über `wp_user_id` (gleiche Logik wie
  `get_wordpress_proxy_nutzer` in `deps.py`, ausgelagert in eine gemeinsam genutzte Hilfsfunktion
  statt Duplizierung) — deckt den Fall ab, dass eine als Bereichsleiter zugewiesene Person sich
  noch nie im Dashboard angemeldet hat. Anders als beim WP-Proxy-Pfad wird hier **keine** `rolle`
  gesetzt/überschrieben (die Rollenzuweisung passiert ausschließlich über die Rollen-Seite unten;
  ein neu angelegter `nutzer` bekommt hier vorerst keine `rolle`, bis der Proxy-Pfad sie beim ersten
  echten Login setzt oder die Rollen-Seite sie explizit zuweist).
- Nicht mehr im Payload enthaltene `bereich`-Zeilen werden gelöscht (Cascade auf `bereich_klasse`/
  `nutzer_bereich` bereits über `ondelete="CASCADE"` in den Modellen abgesichert).
- Audit-Log-Eintrag pro Aufruf (`aktion="admin_bereiche_updated"`), analog zu den bestehenden
  Admin-PUT-Endpunkten.

## WordPress-Plugin

Zwei neue Dateien unter `wordpress-plugin/absenzdash/includes/`, als Untermenüs unter der
bestehenden `Absenzdash_Optionen`-Seite (`add_submenu_page` statt eigenem Top-Level-Menü):

### `class-rollen-seite.php` (ersetzt `class-benutzerprofil.php`)

Listenansicht aller WP-Nutzer (`get_users()`), pro Zeile:
- Rolle-Dropdown (`(keine)`/`klassenlehrkraft`/`bereichsleiter`/`schulleitung`) — schreibt/liest
  weiterhin `absenzdash_role`-User-Meta, gleicher Wire-Contract wie bisher (TECH-SPEC.md §3/§4).
- WebUntis-Kürzel als Text-Input mit `<datalist>`, befüllt per JS-Fetch gegen
  `GET /admin/webuntis-teachers` (über den bestehenden Proxy) — Texteingabe bleibt möglich (schnelle
  Zuweisung per Tippen), Datalist nur als Vorschlagsliste, kein Zwangs-Dropdown. Speichert
  weiterhin `absenzdash_webuntis_code`-User-Meta.
- **Vorbelegung:** falls `absenzdash_webuntis_code` noch leer ist, aber VertretungsFlows
  `absenzflow_webuntis_code`-Meta für denselben Nutzer existiert (gleiche WP-Instanz, siehe
  TECH-SPEC.md §4/§6 — `get_user_meta()` ist ein lokaler Aufruf, kein Cross-System-Zugriff), wird
  dessen Wert als Platzhalter/Vorschlag im Feld angezeigt, nicht automatisch übernommen — das Feld
  bleibt vom Admin explizit zu bestätigen (Freitext dort, keine Garantie auf Kürzel-Format).
- Speichern weiterhin über `personal_options_update`/`edit_user_profile_update`-Äquivalent, hier als
  eigener Formular-Submit-Handler für die Listenseite (ein POST für alle Zeilen).

`class-benutzerprofil.php` wird entfernt (kein Parallelbetrieb zweier Pflegewege für dieselben
Meta-Keys).

### `class-bereiche-seite.php` (neu)

- Lädt beim Rendern `GET /admin/bereiche` und `GET /admin/klassen` über den Proxy.
- Pro Bereich: Name-Feld, Mehrfachauswahl der zugehörigen Klassen (`<select multiple>` aus der
  Klassenliste), Mehrfachauswahl der Bereichsleiter (`<select multiple>` aus `get_users()`,
  gefiltert auf Nutzer mit `absenzdash_role = 'bereichsleiter'` als Vorauswahl-Hilfe, aber nicht
  hart eingeschränkt — SPECS.md §3 trennt Rollenzuweisung und Bereichsleiter-Zuordnung nicht zwingend
  1:1).
  Bereich hinzufügen/entfernen über einfache Buttons (JS, kein Reload nötig).
- Speichern per JS-`fetch` `PUT /admin/bereiche` mit dem kompletten aktuellen Zustand, Antwort
  (inkl. Validierungsfehlern) sichtbar im Formular statt Silent-Fail (analog Plan-8-Fehleranzeige-
  Konvention).

Beide Seiten: reines PHP + Vanilla-JS/`fetch`, kein zusätzliches Build-Tooling (konsistent mit
Plan 8), Zugriff nur für `manage_options`-Capability (wie die bestehende Optionsseite — enger als
das bisherige `edit_users` der Profilfelder, da es sich jetzt um eine dedizierte Admin-Seite statt
Teil des Standard-Profilbildschirms handelt).

## Testing

- Backend: reguläre Pytest-Abdeckung für die drei neuen Endpunkte (analog `test_admin_*.py`) —
  Scope-Check (`require_schulleitung`), Whole-List-Replace-Semantik von `/admin/bereiche`
  (Hinzufügen/Entfernen/Umbenennen), Get-or-Create-Verhalten für neue Bereichsleiter,
  Validierungsfehler (leerer Name, doppelte Namen), `/admin/webuntis-teachers`-Fehlerpfad
  (WebUntis nicht erreichbar → 502).
- WP-Plugin: manuell gegen Staging (wie Plan 8), kein PHPUnit (YAGNI, gleiche Begründung wie
  bisher — reine Transport-/Admin-UI-Schicht ohne eigene Fachlogik).

## Dokumentation (gemäß CLAUDE.md)

- SPECS.md §2 wird präzisiert: der Satz zu "im WP-Backend um weitere Personen ergänzbar" wird
  gestrichen/auf die tatsächlich gebaute WebUntis-`teacher1`/`teacher2`-Zuordnung reduziert, mit
  kurzer Begründung (analog zum ASV-BW-CSV-Pivot-Muster in ROADMAP.md).
- ROADMAP.md: nach Abschluss Punkt 1 von "Geplant" nach "Abgeschlossen" verschieben; neuer Punkt
  unter "Geplant" für die zurückgestellte Abteilungsleitungs-Rolle.
- `docs/deployment.md`: Hinweis auf die neue Bereichsdefinition-/Rollen-Seite (Ablösung der
  Profilfelder-Anleitung aus Plan 8).
