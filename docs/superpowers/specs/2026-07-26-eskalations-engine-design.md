# Eskalations-Engine — Design

**Status:** Design vom User genehmigt, bereit für Umsetzungsplanung (`superpowers:writing-plans`).

## 1. Ziel & Scope

Umsetzung von SPECS.md §4/5 (Schwellwert-Regeln, mehrstufige Eskalation, Maßnahmen-Reset, Ausnahmen) als Backend-Engine, in ROADMAP.md als Punkt 1 der "Geplant"-Liste geführt — in Plan 1 explizit als "bewusst nächster Plan" markiert.

**Scope-Grenze zu späteren Plänen:**
- **Dieser Plan** liefert die komplette fachliche Logik bis einschließlich des `benachrichtigung`-Log-Eintrags (wer/wann/welche Stufe/welcher Status), sowie alle nötigen DB-Modelle und internen Service-Funktionen (Regel-Verwaltung, Maßnahme-Erfassung, Ausnahme-Verwaltung) — vollständig über Python-Funktionstests verifizierbar, ganz ohne HTTP-Endpunkte oder E-Mail-Versand.
- **"E-Mail-Benachrichtigungen"** (ROADMAP Punkt 2) hängt sich nur noch an, um für Log-Einträge mit Status `gesendet` tatsächlich eine E-Mail zu verschicken (SMTP).
- **"REST-API fürs WP-Plugin"** (ROADMAP Punkt 3) exponiert die hier gebauten Services/Modelle über `/admin/threshold-rules`, `/students/{id}/exemptions`, etc. (TECH-SPEC.md §3).

## 2. WebUntis-Live-Verifikation: Abteilung

SPECS.md §4 sah ursprünglich "schulweit oder differenziert nach Klassenstufe/Schulart" als Geltungsbereich-Dimensionen vor. Im Brainstorming wurde das durch eine dreistufige Präzedenzkette ersetzt: **schulweit → abteilungsweit → klassenweit** (Klassenstufe entfällt: laut User in der Praxis über Abteilungen/Unter-Abteilungen oder direkt über Klassen abbildbar; Schulart entfällt ebenso zugunsten von Abteilung).

Da diese Entscheidung auf einem WebUntis-Feld ("Abteilung") beruht, das im bestehenden Code nirgends verwendet wird, wurde es live gegen die echte WebUntis-Instanz der Schule geprüft (siehe Memory `verify_external_api_facts_live`):

- `getKlassen` liefert bereits ein `did`-Feld (Department-ID) pro Klasse — aktuell vom Sync-Code ignoriert. Beispiel: `{"id": 3499, "name": "1BFE", "did": 33, ...}`.
- `getDepartments` liefert 29 Abteilungen für diese Schule, je `{id, name, longName}` — z.B. `{"id": 64, "name": "A-2BFE", "longName": "A-2BFE"}`.
- Alle 105 live geprüften Klassen hatten ein gesetztes `did`. Trotzdem wird `klasse.abteilung_id` nullable modelliert (Sync-Robustheit, falls eine zukünftige Klasse ohne Abteilung angelegt wird).

**Toter Code entfernt:** `klasse.stufe`/`klasse.schulart` existieren bereits als nullable Spalten, werden aber vom aktuellen `sync_klassen`-Code nie befüllt. Sie werden per Migration entfernt (ersetzt durch die neue Abteilung/Klasse-Kette).

## 3. Datenmodell

**Neu — `abteilung`:**
- `id`, `webuntis_id` (= WebUntis `did`, unique, aus `getDepartments`), `name`, `long_name`

**Geändert — `klasse`:**
- `+ abteilung_id` (FK → `abteilung.id`, nullable)
- `− stufe`, `− schulart` (entfernt)

**Neu — `schwellwert_regel`:**
- `typ` (`fehlzeiten` | `klassenbuch`)
- `geltungsbereich` (`schulweit` | `abteilung` | `klasse`)
- `abteilung_id` (FK, nullable), `klasse_id` (FK, nullable) — statt eines generischen `geltungswert`-Felds (TECH-SPEC.md-Entwurf) zwei explizite, referenziell integre FK-Spalten; genau eine ist gesetzt, abhängig von `geltungsbereich` (bei `schulweit` beide `null`)
- Partial-Unique-Index auf (`typ`, `abteilung_id`) bzw. (`typ`, `klasse_id`) — erzwingt "nur eine spezifische Regel pro Abteilung/Klasse und Typ" zusätzlich zur Admin-seitigen Validierung auch auf DB-Ebene

**Neu — `schwellwert_stufe`:**
- `regel_id` (FK), `stufe_nr`, `einheit` (`fehltage` | `fehlstunden`, nullable — nur bei `typ=fehlzeiten`), `schwellenwert`, `fehlzeiten_filter` (`nur_unentschuldigt` | `alle`, nullable — nur bei `typ=fehlzeiten`), `empfaenger_rollen` (Array: `klassenlehrkraft` | `bereichsleiter` | `schulleitung`)

**Neu — `schueler_zaehlerstand`:**
- `schueler_id` (FK), `regel_id` (FK), `aktueller_stand`, `erreichte_stufe_nr` (nullable), `letzter_reset_am` (nullable — nur gesetzt nach einer zurücksetzenden Maßnahme)

**Neu — `massnahmen_typ`:**
- `name`, `setzt_zaehler_zurueck` (bool)
- **Abweichung vom TECH-SPEC.md-Entwurf:** statt `betroffene_regel_ids` (Array) eine echte m:n-Tabelle `massnahmen_typ_regel(massnahmen_typ_id, regel_id)` — referenzielle Integrität statt loser IDs in einem Array-Feld, einfachere Abfragbarkeit ("welche Maßnahmen setzen Regel X zurück").

**Neu — `massnahme`:**
- `schueler_id` (FK), `massnahmen_typ_id` (FK), `datum`, `notiz` (nullable), `erfasst_von_nutzer_id` (FK → `nutzer`)

**Neu — `ausnahme`:**
- `schueler_id` (FK), `kategorie` (`fehlzeiten` | `klassenbuch`), `grund`, `gueltig_bis` (nullable), `aktiv` (bool)

**Neu — `benachrichtigung`:**
- `schueler_id` (FK), `regel_id` (FK), `stufe_nr`, `gesendet_am`, `empfaenger` (JSON-Array `{rolle, nutzer_id}`), `status` (`gesendet` | `kein_empfaenger` | `initial_import`)

Alle neuen Tabellen erhalten `TimestampMixin` wie bestehende Modelle.

## 4. Kernalgorithmus

Läuft als neuer Schritt in `sync_orchestrator._run_once`, direkt nach `sync_fehlzeiten`/`sync_klassenbuch`, in derselben DB-Session/Transaktion vor dem abschließenden `commit`.

### 4.1 Neuberechnung statt Inkrement

Für jede aktive `schwellwert_regel` und jeden betroffenen Schüler wird der Zählerstand bei **jedem Lauf komplett neu aus den Rohdaten berechnet** (nicht schrittweise fortgeschrieben) — folgt demselben Idempotenz-Muster wie der bestehende Fehlzeiten-/Klassenbuch-Sync. Vorteil: robust gegen nachträgliche WebUntis-Korrekturen, kein Drift-Risiko.

```
fenster_start = max(schuljahr_start_cache, schueler_zaehlerstand.letzter_reset_am oder -unendlich)
```

Der Schuljahreswechsel-Reset (SPECS.md §5, "beim Erreichen des Schuljahresbeginn-Datums werden alle Zähler zurückgesetzt") fällt damit automatisch heraus, sobald `schuljahr_start_cache` weiterrückt — kein separater Reset-Schritt nötig.

### 4.2 Regel-Auflösung

Präzedenz von speziell zu allgemein: **klassen-spezifische Regel > abteilungs-spezifische Regel > schulweite Fallback-Regel**, je Regel-`typ` unabhängig aufgelöst. Schüler ohne `klasse_id` (z.B. noch nicht zugeordnet, SPECS.md §4) können nur schulweite Regeln matchen. Schüler mit aktiver `ausnahme` in der jeweiligen `kategorie` werden komplett übersprungen (weder gezählt noch benachrichtigt).

### 4.3 Pro-Stufe-Auswertung

Da `einheit` und `fehlzeiten_filter` pro **Stufe** konfigurierbar sind (nicht pro Regel), wird für jede Stufe unabhängig mit ihrer eigenen Filter-/Einheit-Kombination seit `fenster_start` gezählt, von der höchsten Stufe absteigend geprüft, bis eine Stufe ihren Schwellenwert erreicht. Deren Zählwert wird als `aktueller_stand` gespeichert, ihre Nummer als `erreichte_stufe_nr`. Wird keine Stufe erreicht, bleibt `erreichte_stufe_nr = null`, `aktueller_stand` zeigt trotzdem den Zählwert nach Stufe-1-Definition (Fortschrittsanzeige zum nächsten Meilenstein). Für Klassenbuch-Regeln zählt jeder `klassenbuch_eintrag` unabhängig von der Kategorie — SPECS.md sieht keine Kategorie-Filterung auf Regel-Ebene vor; das wäre eine Erweiterung über die aktuelle Spezifikation hinaus.

Für jedes zutreffende (Schüler, Regel)-Paar wird bei jedem Lauf ein `schueler_zaehlerstand`-Datensatz upserted, auch bei Stand 0.

### 4.4 Neu-erreicht-Erkennung & Benachrichtigungs-Log

Vergleich der neu berechneten `erreichte_stufe_nr` gegen den zuvor gespeicherten Wert. Nur bei tatsächlichem Anstieg wird ein `benachrichtigung`-Eintrag geschrieben (SPECS.md §6: keine wiederholte Benachrichtigung bei unverändertem Stand).

**Empfänger-Auflösung** (löst die uneindeutige Formulierung in SPECS.md §4 zugunsten der bereits in TECH-SPEC.md festgelegten expliziten Variante auf): `empfaenger_rollen` pro Stufe ist eine vollständig explizite Rollen-Liste, **keine** implizite "Klassenlehrkraft immer zusätzlich dabei"-Sonderlogik in der Engine (das wäre höchstens ein UI-Komfort im späteren Admin-Bereich beim Anlegen einer Stufe).

- `klassenlehrkraft` → `schueler.klasse_id` → `nutzer_klasse` → `nutzer`
- `bereichsleiter` → `klasse_id` → `bereich_klasse` → `bereich` → `nutzer_bereich` → `nutzer`
- `schulleitung` → alle `nutzer` mit `rolle='schulleitung'`

**Status-Bestimmung:**
1. `einstellung.initialer_import_abgeschlossen = false` → immer `initial_import`, unabhängig von Empfänger-Auflösung (SPECS.md §5.1)
2. sonst: keine einzige Rolle auflösbar → `kein_empfaenger` (keine Ersatz-Benachrichtigung an Schulleitung, SPECS.md §6)
3. sonst: `gesendet`

### 4.5 Maßnahmen-Reset

Interner Service `massnahme_service.record_massnahme(...)` (kein API-Endpunkt in diesem Plan) erfasst eine Maßnahme und setzt bei `setzt_zaehler_zurueck=true` `schueler_zaehlerstand.letzter_reset_am` auf das Maßnahme-Datum — nur für die über `massnahmen_typ_regel` verknüpften Regeln.

## 5. Datei-Struktur

**Modelle** (`backend/app/models/`): `abteilung.py`, `schwellwert_regel.py`, `schwellwert_stufe.py`, `schueler_zaehlerstand.py`, `massnahmen_typ.py` (inkl. `massnahmen_typ_regel`-Assoziationstabelle), `massnahme.py`, `ausnahme.py`, `benachrichtigung.py`. Geändert: `klasse.py` (+`abteilung_id`, −`stufe`/`schulart`).

**Services** (`backend/app/services/`):
- `webuntis_abteilung_sync.py` — neu, `getDepartments` → `abteilung`; muss vor `sync_klassen` laufen (FK-Abhängigkeit)
- `webuntis_klassen_sync.py` — geändert, befüllt zusätzlich `abteilung_id` aus `did`
- `eskalations_pruefung.py` — neu, Kernlogik aus Abschnitt 4
- `massnahme_service.py` — neu, Maßnahme-Erfassung inkl. Zähler-Reset
- `sync_orchestrator.py` — geändert: ruft `webuntis_abteilung_sync` vor `sync_klassen`, `eskalations_pruefung` nach `sync_fehlzeiten`/`sync_klassenbuch`

**Migration:** eine neue Alembic-Revision für alle obigen Tabellen/Spalten in einem Schritt.

## 6. Testing

Wie bei Plan 1/2: echte Postgres-Testdatenbank (kein Mocking der DB-Schicht). Isolierte Tests pro Baustein:
- Regel-Präzedenz (klassen- vs. abteilungs- vs. schulweit, inkl. Schüler ohne `klasse_id`)
- Pro-Stufe-Zählung mit unterschiedlichen Filtern/Einheiten je Stufe
- Schuljahreswechsel-Reset über `schuljahr_start_cache`-Änderung
- Maßnahmen-Reset über `massnahmen_typ_regel`
- Ausnahme-Skip
- `kein_empfaenger`-Erkennung (keine Ersatz-Benachrichtigung an Schulleitung)
- `initial_import`-Status vor erstem vollständigem Sync-Lauf

Plus ein Integrationstest über `sync_orchestrator._run_once`, der den neuen Schritt end-to-end mit den bestehenden Sync-Schritten zusammen prüft.

## 7. Offene Punkte für den Umsetzungsplan (bewusst nicht Teil dieses Designs)

- Admin-seitige Bedienung der Schwellwert-Regeln/Maßnahmen-Katalog-Pflege (ROADMAP Punkt 3)
- Tatsächlicher E-Mail-Versand für Status `gesendet` (ROADMAP Punkt 2)
- Default-Maßnahmen-Katalog-Seeding (SPECS.md §4 nennt ein Standard-Set: Gespräch, Elterngespräch, Nachsitzen, 4h Nachsitzen, Schulverweis, Bußgeld, Zwangsgeld) — gehört vermutlich in eine Alembic-Data-Migration oder ein Seed-Script; wird im Umsetzungsplan konkretisiert.
