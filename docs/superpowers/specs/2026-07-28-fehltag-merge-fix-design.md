# Design: Fehltage-Zusammenführung im WebUntis-Sync

Stand: 2026-07-28

Begleitdokument zu [TECH-SPEC.md](../../../TECH-SPEC.md) Abschnitt 1.2/1.3 (WebUntis-Fehlzeiten-Feldmapping). Behebt einen Datenfehler, der beim Testen von Plan 9 (Frontend-Grundgerüst) über die neue Dashboard-Kennzahl "Ø Fehltage" auffiel.

## 1. Problem

`fehlzeit`-Zeilen mit `typ='tag'` sollen laut TECH-SPEC.md Abschnitt 1.2 einen ganztägigen Abwesenheits-Rahmen abbilden (`startTime: 0`, `endTime: 2359`, eine Zeile pro Tag). In der Praxis liefert WebUntis für ganztägige Krankmeldungen an dieser Schule stattdessen **eine Zeile pro betroffener Unterrichtsstunde** (z.B. `730–815`, `815–900`, …), jede ohne `subjectId` — der Sync klassifiziert sie korrekt gemäß der dokumentierten Regel (`subjectId` fehlt ⇒ `typ='tag'`), erzeugt dadurch aber bis zu 11 Zeilen für einen einzigen tatsächlichen Fehltag. Betroffene Zahlen zum Zeitpunkt des Fundes: 370.170 `tag`-Zeilen über 1282 Schüler seit Schuljahresbeginn (2025-09-15) — rechnerisch ~289 "Fehltage" pro Schüler im Schnitt, weit mehr als die im Schuljahr überhaupt möglichen Schultage.

Da sowohl die Eskalations-Engine (`app/services/eskalations_pruefung.py:97`) als auch das neue Dashboard (`app/services/dashboard_query.py`) Fehltage per `COUNT(*)` auf `typ='tag'`-Zeilen zählen, wirkt sich der Fehler auf beide aus: Schwellwert-Regeln für Fehltage lösen viel zu früh aus.

## 2. Fix-Ebene

Zusammenführung erfolgt **beim Sync** (`app/services/webuntis_fehlzeit_sync.py`), nicht erst beim Zählen. Dadurch liegt in der DB pro Schüler und Tag maximal eine `tag`-Zeile, und jede bestehende Zählstelle (Eskalations-Engine, Dashboard, Schüler-Detail, PDF-Export) wird ohne eigene Änderung korrekt — sie zählen bereits `COUNT(*)`/listen Zeilen, was nach dem Fix automatisch stimmt.

Alternative verworfen: ein nachgelagerter SQL-Dedup-Pass nach dem bestehenden Sync-Loop wäre ein zusätzlicher DB-Roundtrip mit zwischenzeitlich zwei Wahrheitsquellen für denselben Tag — kein Vorteil gegenüber der Vorab-Gruppierung.

## 3. Merge-Logik

In `sync_fehlzeiten`: WebUntis-Einträge werden wie bisher nach `invalid` gefiltert, dann nach Vorhandensein von `subjectId` in zwei Gruppen geteilt:

- **`stunde`-Kandidaten** (mit `subjectId`): unverändertes Verhalten, eine Zeile pro Eintrag.
- **`tag`-Kandidaten** (ohne `subjectId`): werden vor dem Upsert nach `(schueler_id, datum)` gruppiert. Pro Gruppe entsteht eine zusammengeführte Zeile:
  - `start_zeit=0`, `end_zeit=2359` — fester Ganztages-Rahmen (wie ursprünglich in TECH-SPEC vorgesehen). Der bestehende Unique-Constraint `(schueler_id, datum, start_zeit, end_zeit, typ)` bleibt dadurch unverändert gültig und erzwingt jetzt automatisch "eine Zeile pro Tag" — **keine Migration nötig**.
  - `excuse_status_id`: "Unentschuldigt gewinnt" — zählt mindestens eine Perioden-Zeile der Gruppe nicht als entschuldigt (aufgelöster Status mit `zaehlt_als_entschuldigt=False`, oder ein nicht auflösbarer/unbekannter Status), übernimmt die zusammengeführte Zeile deren `excuse_status_id` (bzw. `NULL`, falls diese Zeile selbst keinen aufgelösten Status hatte). Nur wenn *alle* Perioden der Gruppe als entschuldigt gelten, bleibt ein entschuldigter Status erhalten (deterministisch: der erste in Eintragsreihenfolge).
  - `grund_text`: verschiedene, nicht-leere Freitexte aus der Gruppe werden mit `"; "` zusammengefügt (Dopplungen entfernt, Reihenfolge des ersten Vorkommens); rein informativ, kein Zählkriterium.
  - `fach`: bleibt `NULL` (war für `tag`-Zeilen schon immer so, da `subjectId` per Definition fehlt).
  - `invalid`: bleibt `False` (ungültige Rohzeilen werden wie bisher vorher per `continue` übersprungen, fließen nie in eine Gruppe ein).

Idempotenz bei wiederholten Sync-Läufen bleibt erhalten: jeder Lauf holt sein Zeitfenster komplett neu von WebUntis und gruppiert/führt zusammen, bevor der bestehende `by_key`-Upsert-Mechanismus greift — keine kumulierenden Duplikate.

## 4. Testing

Erweiterung von `backend/tests/test_webuntis_fehlzeit_sync.py`:
- mehrere `tag`-Kandidaten desselben Schülers/Tages werden zu einer Zeile mit `start_zeit=0`/`end_zeit=2359` zusammengeführt.
- gemischter Entschuldigungsstatus innerhalb einer Gruppe → die zusammengeführte Zeile trägt den nicht-entschuldigten Status ("unentschuldigt gewinnt").
- unterschiedliche `grund_text`-Werte innerhalb einer Gruppe werden dedupliziert zusammengefügt.
- `stunde`-Zeilen bleiben unverändert, eine Zeile pro Eintrag, auch wenn im selben Sync-Lauf `tag`-Kandidaten für denselben Tag vorkommen.
- wiederholter Sync-Lauf mit identischem Input bleibt idempotent (keine zusätzlichen Zeilen).
- bestehender Einzeilen-Fall (nur ein `tag`-Kandidat pro Tag, bereits `start_zeit=0`/`end_zeit=2359`) bleibt als Regression abgedeckt (vorhandener Test `test_sync_fehlzeiten_creates_tag_and_stunde_entries` deckt das ab, unverändert lauffähig).

Keine Änderung an `eskalations_pruefung.py`, `dashboard_query.py`, `student_query.py` oder `export_service.py` nötig — sie zählen/listen bereits `Fehlzeit`-Zeilen direkt und werden durch die korrigierten Sync-Daten automatisch richtig.

## 5. Dokumentation

Kurzer Zusatz in TECH-SPEC.md Abschnitt 1.2 bei der Tag-/Stunde-Unterscheidung: WebUntis kann für Ganztages-Absenzen mehrere Perioden-Zeilen ohne `subjectId` liefern; der Sync führt sie zu einer Tages-Zeile zusammen (inkl. "unentschuldigt gewinnt"-Regel bei gemischtem Status).

## 6. Bewusst nicht enthalten

- Kein Migrations-/Cleanup-Skript für bereits synchronisierte Bestandsdaten — auf dem Dev-System werden die betroffenen Daten manuell getruncatet und per Sync neu gezogen (außerhalb dieses Plans).
- Keine Änderung an Eskalations-Engine, Dashboard, Schüler-Detail oder PDF-Export (siehe Abschnitt 3, automatisch korrekt durch den Sync-Fix).
- Keine Änderung an der Klassenbuch-Synchronisation (eigenständiger Mechanismus mit `eventId`-basierter Idempotenz, nicht betroffen).
