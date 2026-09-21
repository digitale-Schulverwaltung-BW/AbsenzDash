# Design: Rückwirkendes Schuljahr-Archiv, Roster-Filterung & CSV-Archivierung

Stand: 2026-09-21

Folgt direkt auf [2026-09-18-schuljahr-historisierung-design.md](2026-09-18-schuljahr-historisierung-design.md) (Plan: `docs/superpowers/plans/2026-09-18-schuljahr-historisierung.md`, bereits deployed). Drei zusammenhängende Nachträge, in derselben Session besprochen:

1. **Bug im gerade deployten Historie-Modus:** Die Schülerliste zeigt für vergangene Schuljahre weiterhin alle Schüler (inkl. solcher, die "damals" noch gar nicht an der Schule waren) — der Historie-Modus filtert bisher nur, *welche Klasse* je Schüler angezeigt wird, nicht *welche Schüler* überhaupt gelistet werden.
2. **Rückwirkendes Backfill:** Der 25/26-Rollover ist schon passiert, bevor die Historisierung live ging — `schueler_klasse_historie` hat für 25/26 (und alle älteren Jahre) keine Daten und kann sie aus der DB heraus auch nicht rekonstruieren (`audit_log` protokolliert nur admin-/nutzergesteuerte Aktionen, nie automatische Sync-Änderungen an `schueler.klasse_id`). Eine archivierte ASV-BW-CSV aus 25/26 ist voraussichtlich beim Sekretariat verfügbar — soll per neuem Admin-Import nachgezogen werden können, perspektivisch für beliebige vergangene Schuljahre.
3. **Vorsorge:** Die aktuell laufend überschriebene ASV-CSV (Live-Mount, fester Dateiname) soll pro Schuljahr archiviert werden, damit diese Lücke bei künftigen Schuljahreswechseln nicht wieder entsteht.

Rohzahlen (Fehltage/-stunden/Klassenbuch) sind von alldem nicht betroffen — die werden bereits rein datumsbasiert direkt aus `fehlzeit`/`klassenbuch_eintrag` berechnet (Plan 13), unabhängig vom Klassen-Snapshot. WebUntis liefert außerdem für vergangene Schuljahre weiterhin Absenzdaten (`getTimetableWithAbsences` mit explizitem Datumsbereich, TECH-SPEC.md §1.3a) — die Zahlen sind also nie das Problem, nur die Klassen-/Schüler-Zuordnung.

## 1. Roster-Filterung im Historie-Modus (Bugfix, keine neue Tabelle nötig)

**`GET /students`** im Historie-Modus (`schuljahr_id` != aktuelles Schuljahr): die Roster-Abfrage wechselt von "alle `schueler`-Zeilen im Scope" (aktuelles Verhalten, `nur_aktive=False`) auf "alle `schueler`-Zeilen, für die eine `schueler_klasse_historie`-Zeile mit `schuljahr_id = <gewähltes Jahr>` existiert" (Inner Join statt der bisherigen Filterung über `Schueler.aktiv`). `klasse_id`/`bereich_id`-Filter-Query-Parameter greifen dann konsequent auf die historische Klasse (`schueler_klasse_historie.klasse_id`, bzw. darüber aufgelöst `klasse.abteilung_id` für den Bereich) statt auf `schueler.klasse_id`. Ein Schuljahr ganz ohne Historie-Zeilen (jedes Jahr vor Einführung dieses Features, solange kein rückwirkender Import gelaufen ist) liefert dadurch automatisch eine leere Liste — kein Sonderfall nötig.

**`GET /students/{id}`**: analog — ist für den angefragten Schüler und das gewählte Schuljahr keine `schueler_klasse_historie`-Zeile vorhanden, liefert die Route `404` ("Schüler war in diesem Schuljahr nicht eingeschrieben") statt stillschweigend die aktuelle Klasse als Fallback zu zeigen oder die volle Historie ungefiltert auszugeben.

Betrifft nur Query-Logik in `student_query.py`/`students.py` — keine Datenmodell-Änderung.

## 2. CSV-Archivierung

Bei jedem tatsächlich verarbeiteten ASV-CSV-Import (`import_schueler`, wenn die mtime-Prüfung *nicht* überspringt) wird zusätzlich eine Kopie der Roh-CSV nach `<ASV_CSV_ARCHIVE_DIR>/<schuljahr.name>.csv` geschrieben (eine Datei je Schuljahr, bei jedem weiteren Import desselben Jahres überschrieben — konsistent mit der bestehenden Entscheidung "ein Stand pro Schuljahr reicht", siehe Ursprungs-Design-Dok). `ASV_CSV_ARCHIVE_DIR` ist ein neuer, konfigurierbarer Pfad (analog zu `ASV_CSV_PATH`), muss auf ein persistentes Volume zeigen (nicht das flüchtige Live-Mount-Verzeichnis) — Docker-Compose-Anpassung nötig (neues benanntes Volume, analog zu `absenzdash-db-data`).

Dieser Ordner dient zugleich als naheliegende Ablage für Admin-seitig hochgeladene Alt-CSVs (Abschnitt 3) — beide Zwecke teilen sich damit dieselbe Verzeichnisstruktur, ohne dass das eine Voraussetzung fürs andere wird (ein Admin kann jederzeit auch eine CSV aus einer ganz anderen Quelle hochladen).

## 3. Historischer Admin-Import

**Neuer Abschnitt/Tab im Dashboard-Admin-Bereich** ("Schuljahr-Import"), neben den bestehenden vier Seiten aus Plan 12 (Sync-Einstellungen, Entschuldigungsstatus, Maßnahmen-Katalog, Schwellwert-Regeln) — nur `schulleitung`, wie die anderen Admin-Seiten.

**Ablauf:**
1. Schuljahr-Dropdown, gespeist aus dem lokalen `schuljahr`-Cache (bereits über `nav-options.schuljahre` verfügbar) — keine Beschränkung auf "Jahre ohne Daten", ein erneuter Import für ein bereits befülltes Jahr ist ein bewusst unterstützter Update-Fall (siehe unten).
2. CSV-Datei-Upload (dieselbe Spalten-Validierung wie der laufende Import: `externe_id`/Vorname/Nachname/Klasse/Eintritts-/Austrittsdatum-Spalten müssen vorhanden sein).
3. **Vorschau vor dem Bestätigen** (zweistufiger Ablauf, kein Sofort-Schreiben): Backend parst die Datei, matched Klassennamen gegen `klasse`-Zeilen mit `schuljahr_id = <gewähltes Jahr>` (fehlen diese komplett, werden sie im selben Zug per `getKlassen({schoolyearId: ...})` von WebUntis nachgezogen — die Funktion aus dem letzten Plan wird dafür direkt wiederverwendet), und liefert eine Zusammenfassung zurück: Zeilenanzahl, davon bereits bekannte `schueler` (Treffer über `externe_id`) vs. komplett neue, sowie Klassennamen ohne Treffer selbst nach dem WebUntis-Nachzug. Erst ein expliziter zweiter Request schreibt tatsächlich.
4. **Schreiben:** ausschließlich `schueler_klasse_historie` für das gewählte Schuljahr (Upsert je `schueler_id`) — rührt `schueler.klasse_id`/`aktiv`/`vorname`/`nachname` (die "aktuellen" Live-Felder) nicht an. Bei komplett unbekannter `externe_id` wird ein neuer, minimaler `schueler`-Stammsatz angelegt (nur `externe_id`/Name — kein `klasse_id`, kein `aktiv`-Wert, da diese Felder nur die *aktuelle* Wahrheit repräsentieren und für einen möglicherweise längst ausgeschiedenen Schüler nicht sinnvoll befüllbar sind).
5. Ergebnis-Zusammenfassung inkl. übersprungener Zeilen (analog zum bestehenden Fehlerhandling in `import_schueler`).
6. Erneuter Upload fürs selbe Schuljahr aktualisiert/überschreibt (idempotent, wie der laufende Import auch) — Anwendungsfall: eine bessere/vollständigere Archiv-CSV taucht später auf.

**Audit:** wie jede andere schreibende Admin-Aktion wird ein `audit_log`-Eintrag angelegt (`aktion="admin_schuljahr_historie_import"`, `details` mit Schuljahr-ID und Zeilenzahl).

## Nicht-Ziele

- Keine unterjährige Granularität beim historischen Import (weiterhin ein Snapshot pro Schuljahr, wie im Ursprungs-Design festgelegt).
- Keine automatische Erkennung/Vorschlagsliste verfügbarer Archiv-CSVs — der Admin lädt die Datei jedes Mal explizit hoch.
- Kein automatisches Backfill ohne Nutzerinteraktion — auch wenn eine archivierte CSV im Archiv-Ordner (Abschnitt 2) liegt, wird sie nicht automatisch für die Historie verarbeitet, nur wenn ein Admin den Import-Flow bewusst durchläuft.
- Keine Änderung an der Berechnung der Rohzahlen (Fehltage/-stunden/Klassenbuch) — die sind schon heute für beliebige vergangene Schuljahre korrekt, unabhängig vom Klassen-Snapshot.
- Keine rückwirkende Korrektur von `schueler.klasse_id`/`aktiv` für vergangene Zustände — diese Felder bleiben ausschließlich "aktueller Stand".
