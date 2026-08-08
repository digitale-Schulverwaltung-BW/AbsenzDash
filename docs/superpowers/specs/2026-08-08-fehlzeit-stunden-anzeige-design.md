# Fehlzeiten mit Stundenangabe statt Uhrzeit anzeigen (Design)

Stand: 2026-08-08

Kontext: In Schüler-Details und PDF-Export zeigen nicht-ganztägige Fehlzeiten (`typ='stunde'`) heute eine Uhrzeit-Spanne. Für Lehrkräfte ist die betroffene Unterrichtsstunde ("Stunde 1") aussagekräftiger als eine reine Uhrzeit — insbesondere um Muster wie chronisches Zuspätkommen oder zu lange Pausen zu erkennen.

## Ausgangslage

- **Frontend**: [FehlzeitenTable.tsx:30](../../../frontend/src/components/StudentDetail/FehlzeitenTable.tsx) zeigt für `typ='stunde'` aktuell `${fehlzeit.start_zeit}–${fehlzeit.end_zeit}` — die rohen HHMM-Integer werden **ohne Formatierung** interpoliert (z.B. `730–815` statt `7:30–8:15`). Es existiert aktuell keine Uhrzeit-Formatierungs-Hilfsfunktion.
- **PDF-Export**: `backend/app/templates/export_pdf.html` (Fehlzeiten-Tabelle, Zeilen 31-49) hat **keine Zeit-Spalte** — `backend/app/services/export_service.py:52-66` liefert `start_zeit`/`end_zeit` gar nicht in den Template-Kontext. Nicht-ganztägige Fehlzeiten zeigen im PDF aktuell also gar keine Zeitangabe.
- **Datenmodell**: `fehlzeit.start_zeit`/`end_zeit` (HHMM-Int, z.B. `730`) — bei `typ='tag'` feste Platzhalter `0`/`2359`, bei `typ='stunde'` echte Uhrzeiten (siehe TECH-SPEC.md §2 und Nachtrag 4, wonach auch zusammengeführte Kurzabwesenheiten <90 Minuten als `typ='stunde'` mit echter Uhrzeit geschrieben werden).
- **WebUntis-Integration**: Kein Stundenraster (`getTimegridUnits`) wird bisher abgerufen oder gecacht.

## 1. Datenmodell: Stundenraster-Cache

Neue Tabelle `stundenraster_periode`:

| Spalte | Typ | Bemerkung |
|---|---|---|
| `id` | PK | |
| `wochentag` | `int` | 1 (Montag) – 7 (Sonntag), WebUntis-Konvention aus `getTimegridUnits` |
| `stunde_nr` | `int` | Fortlaufende Periodennummer laut Raster |
| `start_zeit` | `int` | HHMM, z.B. `730` |
| `end_zeit` | `int` | HHMM, z.B. `815` |

`UNIQUE (wochentag, stunde_nr)`. Reiner WebUntis-Stammdaten-Cache, analog `klasse`/`classreg_category`. Kein Klassenbezug (Zwischenantwort des Auftraggebers: ein schulweites Raster reicht).

## 2. Sync

Neuer Service `backend/app/services/webuntis_stundenraster_sync.py`, Funktion `sync_stundenraster(db, client) -> None`:

- Ruft `client.call("getTimegridUnits", {})` auf — **live verifiziert (2026-08-08, siehe TECH-SPEC.md Abschnitt 1.4): akzeptiert ausschließlich einen leeren Parameter-Body**, jeder zusätzliche Parameter (auch `schoolyearId`) führt zu `Method not found`. Es gibt kein klassenspezifisches Raster über JSON-RPC.
- Antwortformat (bestätigt über `python-webuntis`-Quellcode, siehe TECH-SPEC.md Abschnitt 1.4): Liste pro Wochentag mit `day` (Integer, **WebUntis-Konvention 1=Sonntag…7=Samstag**, nicht Pythons `isoweekday()`) und `timeUnits[]` (`{name, startTime, endTime}`, Reihenfolge im Array = Periodenreihenfolge — kein explizites Nummernfeld, `stunde_nr` wird daher als 1-basierter Index innerhalb des sortierten `timeUnits`-Arrays vergeben, nicht aus `name` geparst, da `name` frei konfigurierbarer Text ohne garantiertes Zahlenformat ist).
- Schreibt die Tabelle komplett neu (`DELETE FROM stundenraster_periode` + Bulk-Insert), da die Tabelle klein ist (Größenordnung: Wochentage × Perioden pro Tag) und Diffing keinen Mehrwert bringt — gleiches Muster wie `sync_bereiche` in [Bundle-D-Design](2026-08-05-bundle-d-bereiche-entschlacken-design.md) Abschnitt 2, Schritt 2.
- Wird im Orchestrator (`sync_orchestrator.py::run_sync_once`) bei jedem regulären Sync-Lauf aufgerufen, vor `sync_fehlzeiten` (das Anzeige-Label wird beim Lesen berechnet, siehe unten — die Reihenfolge ist daher nicht hart erforderlich, aber folgt der bestehenden "Stammdaten vor Bewegungsdaten"-Konvention).
- Schlägt `getTimegridUnits` fehl oder liefert eine leere/null Antwort: Sync-Lauf bricht **nicht** ab (kein kritischer Pfad), Tabelle bleibt beim alten Stand, Warnung geloggt. Nachgelagert greift ohnehin der Uhrzeit-Fallback aus Abschnitt 3. **Bekannter aktueller Zustand (2026-08-08):** an der Live-Instanz liefert der Aufruf gerade `-8998`/"getTimegrid() is null", vermutlich weil WebUntis sich in der bekannten Schuljahres-Übergangslücke befindet (TECH-SPEC.md Abschnitt 1.3a) — `getCurrentSchoolyear` schlägt zeitgleich mit demselben Fehlercode fehl. Erwartung: löst sich von selbst, sobald die Schule das nächste Schuljahr aktiviert; bis dahin zeigt das Feature durchgängig den Uhrzeit-Fallback.

## 3. Label-Berechnung

Neue Funktion in `backend/app/services/fehlzeit_berechnung.py` (liegt bereits bei der bestehenden Minuten-/Stunden-Berechnung), z.B. `dauer_anzeige(fehlzeit: Fehlzeit, stundenraster: list[StundenrasterPeriode]) -> str`:

1. `typ == 'tag'` → `"ganztägig"` (unverändert).
2. `typ == 'stunde'`:
   - Minuten wie bisher: `end_zeit - start_zeit` (in HHMM-Minuten-Differenz-Logik von `_hhmm_zu_minuten`).
   - Wochentag aus `fehlzeit.datum` ableiten (`.isoweekday()`).
   - Alle `stundenraster_periode`-Zeilen dieses Wochentags filtern, deren `[start_zeit, end_zeit)` sich mit `[fehlzeit.start_zeit, fehlzeit.end_zeit)` überschneidet.
   - **Treffer gefunden**: `stunde_nr`-Werte der Treffer nehmen. Eine Periode → `"{minuten} Minuten (Stunde {n})"`; mehrere aufeinanderfolgende → `"{minuten} Minuten (Stunde {min}-{max})"`.
   - **Kein Treffer** (Lücke im Raster, Rasterdaten fehlen/leer): Fallback auf korrekt formatierte Uhrzeit-Spanne, `"{minuten} Minuten ({start:%-H:%M}–{end:%-H:%M})"` — behebt dabei den bestehenden Formatierungs-Bug (Abschnitt "Ausgangslage").

Wird pro Fehlzeit-Zeile einmalig im Backend berechnet und in beiden Konsumenten (API-Response, PDF) verwendet — keine doppelte Logik in Frontend und PDF-Template.

## 4. API- und Anzeige-Änderungen

- **Schema** (`backend/app/schemas/students.py`, `FehlzeitOut` o.ä.): neues Feld `dauer_anzeige: str`. `start_zeit`/`end_zeit` bleiben im Schema erhalten (weiterhin intern für Fehlstunden-Aggregation gebraucht, `fehlzeit_berechnung.fehlstunden_minuten_expr()` bleibt unverändert), werden aber nicht mehr für die Anzeige verwendet.
- **Frontend** ([FehlzeitenTable.tsx](../../../frontend/src/components/StudentDetail/FehlzeitenTable.tsx)): Zeile 30 ersetzt `${fehlzeit.start_zeit}–${fehlzeit.end_zeit}` durch `fehlzeit.dauer_anzeige`.
- **PDF** (`export_pdf.html` + `export_service.py:52-66`): Fehlzeiten-Tabelle bekommt eine neue Spalte "Dauer" mit `dauer_anzeige` (ersetzt die fehlende Zeit-Spalte).

## Testing

- Unit-Tests für `dauer_anzeige`: Einzelperiode-Treffer, Mehrperioden-Treffer (Bereich-Format), kein Treffer (Uhrzeit-Fallback, inkl. korrekter Formatierung), `typ='tag'`.
- Unit-Test für `sync_stundenraster`: Vollsync-Verhalten (alte Zeilen werden ersetzt), Fehlerfall (WebUntis-Aufruf schlägt fehl → Tabelle bleibt unverändert, Sync-Lauf läuft weiter).
- Angepasster [FehlzeitenTable.test.tsx](../../../frontend/src/components/StudentDetail/FehlzeitenTable.test.tsx) auf `dauer_anzeige` statt Rohzeit.
- Backend-Test für den PDF-Export-Kontext (`export_service.py`): `dauer_anzeige` landet im Template-Kontext.

## Nicht enthalten (bewusst außerhalb des Scopes)

- Kein klassen- oder tagspezifisches Raster (schulweites Raster laut Rücksprache ausreichend).
- Keine Änderung an der Fehlstunden-Aggregation/-Berechnung (`STUNDENLAENGE_MINUTEN`, Schwellwert-Regeln) — nur die Anzeige ändert sich.
- Keine rückwirkende Migration/Neuberechnung bestehender Fehlzeiten-Anzeigen — das Label wird zur Laufzeit aus vorhandenen `start_zeit`/`end_zeit` berechnet, kein Backfill nötig.
