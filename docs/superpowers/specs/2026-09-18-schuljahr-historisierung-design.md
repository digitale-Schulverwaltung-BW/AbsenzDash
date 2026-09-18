# Design: Schuljahr-Historisierung (Klassenzugehörigkeit) & Rollover-Fix

Stand: 2026-09-18

Ausgelöst durch Live-Beobachtung nach dem ersten echten Schuljahreswechsel (25/26 → 26/27) mit Altdaten in der Prod-DB: (1) die Schuljahr-Auswahl (Plan 13) ändert zwar Fehltage/Fehlstunden je Schuljahr, aber nicht Schülerliste, Klassenliste oder Klassenzugehörigkeit — laut Plan-13-Design-Dok ("Keine historische Klassenzuordnung") war das bewusst so gebaut, erweist sich jetzt aber als zu wenig; (2) Eskalationsstufen wirken für Schüler ohne aktuelle Fehlzeiten unerklärlich (Live-Beispiel: Schüler zeigt im aktuellen Schuljahr Stufe 3 bei 0 Fehlstunden, im SJ 25/26 aber 24 Fehltage — stufenerklärend). Beide Punkte gemeinsam in einer Session untersucht und mit dem Nutzer brainstormed (Antworten unten eingearbeitet).

## Root Cause Eskalationsstufe (Problem 2)

`schueler_zaehlerstand.erreichte_stufe_nr` wird bei jedem Sync-Lauf korrekt neu berechnet (auch abwärts, `eskalations_pruefung.py::pruefe_schwellwerte`), aber das Zählfenster beginnt erst bei `einstellung.schuljahr_start_cache`. Dieser Wert kippt erst um, wenn `resolve_aktuelles_schuljahr()` (`sync_orchestrator.py`) beim nächsten Sync-Lauf tatsächlich das neue Schuljahr auflöst — und genau das schlägt in der aus TECH-SPEC.md §1.3a bekannten Übergangslücke fehl, wenn WebUntis zeitweise kein Schuljahr als "aktiv" führt: der Fallback greift dann auf das "jüngste bekannte Schuljahr" zurück, was in der Übergangsphase noch das alte sein kann, obwohl das neue Schuljahr (Datum) längst begonnen hat und in `getSchoolyears` bereits gelistet ist. Solange der Cache nicht umkippt, zählt das Fenster weiterhin Fehlzeiten aus dem Vorjahr mit — daher die scheinbar unerklärliche Stufe.

**Fix:** `resolve_aktuelles_schuljahr()` bestimmt das aktuelle Schuljahr zusätzlich/vorrangig datumsbasiert aus dem bereits aktualisierten `schuljahr`-Cache (`start_datum <= heute <= end_datum`), statt sich allein auf `getCurrentSchoolyear` bzw. dessen "jüngstes bekanntes Schuljahr"-Fallback zu verlassen. `getCurrentSchoolyear` wird nur noch als reiner Fallback gebraucht, falls kein Cache-Eintrag das heutige Datum abdeckt (echte Lücke: neues Schuljahr noch nicht in WebUntis angelegt). Damit kippt `aktuelles_schuljahr_id`/`schuljahr_start_cache` zuverlässig zum Kalenderdatum, unabhängig davon, ob WebUntis das Jahr intern schon als "aktiv" markiert hat.

Bewusst **kein** darüber hinausgehender Umbau von `schueler_zaehlerstand` (siehe Nicht-Ziele) — Nutzer-Entscheidung: nur das Rollover-Timing fixen, der Zählerstand bleibt konzeptionell ein laufender, nicht schuljahresgebundener Wert (SPECS.md §5 unverändert).

## Datenmodell für Klassenzugehörigkeit (Problem 1)

Leitidee: WebUntis behandelt eine Klasse selbst schon als jahresgebundenes Konzept (`getKlassen` verlangt zwingend eine `schoolyearId`) — das Datenmodell zieht das jetzt nach, statt eine Klasse als über Jahre stabile Entität zu behandeln.

**`klasse` bekommt eine neue Spalte `schuljahr_id`** (FK auf `schuljahr`, NOT NULL). Unique-Constraint wechselt von `webuntis_id` auf `(webuntis_id, schuljahr_id)` — pro Schuljahr eigene Klassen-Zeilen statt Überschreiben derselben Zeile. `webuntis_klassen_sync.sync_klassen` sucht/erzeugt Klassen jetzt über `(row["id"], schoolyear_id)` statt nur `row["id"]` (der Aufrufer übergibt `schoolyear_id` bereits heute, siehe Plan 13).

Migration: bestehende `klasse`-Zeilen bekommen `schuljahr_id = einstellung.aktuelles_schuljahr_id` (Best Effort — sie wurden zuletzt unter dem aktuellen Schuljahr synchronisiert, es gibt keine Möglichkeit, frühere Zuordnungen rückwirkend zu rekonstruieren).

**Neue Tabelle `schueler_klasse_historie`**: `id`, `schueler_id` (FK), `schuljahr_id` (FK), `klasse_id` (FK, nullable — Schüler kann zum Zeitpunkt ohne Klasse gewesen sein), unique auf `(schueler_id, schuljahr_id)`. Ein Snapshot pro Schüler und Schuljahr (wie ein Zeugnis-Eintrag), keine unterjährige Wechsel-Historie (Nutzer-Entscheidung: reicht für den Anwendungsfall, deutlich weniger Aufwand als echte von/bis-Historisierung).

Geschrieben/aktualisiert an zwei Stellen:
1. **ASV-CSV-Import** (`asv_csv_import.py`), zusätzlich zum bestehenden Schreiben von `schueler.klasse_id`: Upsert `schueler_klasse_historie(schueler_id, schuljahr_id=aktuelles_schuljahr_id, klasse_id=<neu ermittelte klasse_id>)`. Dadurch wird die laufende Zeile des aktuellen Schuljahres bei jedem Import nachgezogen (unterjährige Wechsel landen einfach als letzter Stand in derselben Zeile).
2. **Rollover-Erkennung** (siehe oben, `sync_orchestrator.py`): sobald ein echter Schuljahreswechsel erkannt wird, wird einmalig für **alle** Schüler (nicht nur aktive — Altdaten für ausgeschiedene Schüler bleiben sonst permanent auf dem alten Stand eingefroren) aus dem bis dahin aktuellen `schueler.klasse_id` ein Snapshot fürs neue Schuljahr geschrieben. Ab da übernimmt der reguläre ASV-CSV-Import-Pfad die laufende Pflege dieser neuen Zeile.

**Für Schuljahre vor Einführung dieses Features** existieren keine `schueler_klasse_historie`-Zeilen und auch keine jahresgebundenen `klasse`-Zeilen (außer dem Backfill-Wert fürs aktuelle Jahr). Nutzer-Entscheidung: Historie-Ansicht zeigt für solche Jahre explizit "unbekannt"/keine Klasse statt der aktuellen Klasse als (potenziell falscher) Fallback anzuzeigen.

## Backend: Lese-Endpunkte

`GET /students`, `GET /students/{id}`, `GET /dashboard/nav-options` (Klassenliste fürs Dropdown): im Historie-Modus (`schuljahr_id` != `aktuelles_schuljahr_id`) wird die Klasse je Schüler aus `schueler_klasse_historie` gelesen statt aus `schueler.klasse_id`; fehlt eine Zeile für das gewählte Schuljahr, liefert die API `klasse=null` (Frontend zeigt "unbekannt", analog zum bestehenden Verhalten bei schon heute klassenlosen Schülern). Die Klassenliste selbst (`nav-options`) wird im Historie-Modus aus `klasse`-Zeilen mit passendem `schuljahr_id` gebildet statt aus allen aktuellen Klassen.

Im Normalmodus bleibt alles wie heute: `schueler.klasse_id`, aktuelle `klasse`-Tabelle (jetzt zusätzlich implizit auf `schuljahr_id=aktuelles_schuljahr_id` eingegrenzt, da es für die aktuelle `webuntis_id` durch die Migration ohnehin nur eine aktuelle Zeile gibt).

## Frontend

Schülerliste/Schüler-Detail im Historie-Modus zeigen bei fehlendem Snapshot "unbekannt" statt einer Klasse — kein neuer UI-Zustand nötig, deckt sich mit der bestehenden Behandlung von `klasse_id=None`.

## Nicht-Ziele

- Unterjährige Klassenwechsel-Historie (nur ein Snapshot pro Schuljahr, siehe oben).
- Rückwirkende Befüllung der Historie für Schuljahre vor Einführung dieses Features — Historie-Ansicht zeigt dafür bewusst "unbekannt" statt eines Fallback-Werts.
- Schuljahresgebundene Historisierung des Eskalations-Zählerstands (`schueler_zaehlerstand`) — bleibt ein laufender, nicht historisierter Wert (SPECS.md §5 unverändert); nur das Rollover-Timing (wann das Zählfenster umschaltet) wird gefixt. Explizite Nutzer-Entscheidung, siehe Diskussion oben — bei Bedarf später als eigener Punkt aufgreifbar, da dieselbe Rollover-Erkennung als Trigger schon vorhanden wäre.
- Historisierung von `nutzer_klasse`/Scope (wer welche Klasse in einem vergangenen Jahr sehen durfte) — Scope-Auflösung (`resolve_scope`) bleibt unverändert auf der aktuellen Zuordnung basierend, unabhängig vom betrachteten Schuljahr. Vorbestehende Einschränkung, durch dieses Design weder verschlechtert noch behoben (eine Lehrkraft, die eine Klasse nicht mehr unterrichtet, sieht deren Historie schon heute nicht).
