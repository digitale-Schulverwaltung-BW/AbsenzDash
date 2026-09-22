# Design: Dashboard-Statistiken schuljahresbewusst + Dropdown-Filter

Stand: 2026-09-22

Zwei kleinere Nachträge, gemeldet nachdem der rückwirkende Import (Plan 17) erfolgreich getestet wurde:

1. Die Landing-Page-Statistiken (Balkendiagramme, Ø Fehltage/-stunden/Klassenbuch/Maßnahmen) ignorieren den Schuljahr-Selektor komplett — `GET /dashboard/stats` hat keinen `schuljahr_id`-Parameter.
2. Das Schuljahr-Dropdown zeigt auch Schuljahre, für die keine Daten existieren (z.B. zukünftige, in WebUntis schon angelegte Jahre, oder alte Jahre ohne Historie-Import).

## 1. Statistiken

**Datumsfilter:** `_aggregate()` (`dashboard_query.py`) bekommt statt nur `schuljahr_start: date | None` ein `(von, bis)`-Paar, analog zum bereits bestehenden `_resolve_schuljahr_zeitraum`-Muster aus `students.py` (wird dafür in ein gemeinsames Modul verschoben, z.B. `app/services/schuljahr_zeitraum.py`, damit `dashboard_query.py` es nicht dupliziert). Aktuelles Schuljahr weiterhin `(schuljahr_start_cache, None)` — keine Obergrenze nötig, es gibt keine zukünftigen Daten. Vergangenes Schuljahr: `(schuljahr.start_datum, schuljahr.end_datum)`.

**Schüler-Basis:** Im Historie-Modus wird die Schülermenge für `_aggregate()` nicht mehr aus der live `schueler.klasse_id` ermittelt, sondern aus `schueler_klasse_historie` fürs gewählte Schuljahr (`WHERE schuljahr_id = X AND klasse_id IN (...)`), konsistent mit der Schülerliste (Plan 17).

**Bereichs-Zuordnung für die Vergleichsbalken:** `_stats_for_bereich`/`_stats_schulweit`/`_stats_eigene_bereiche` ermitteln die Klassen eines Bereichs aktuell über die (nicht jahresgebundene) `bereich_klasse`-Tabelle. Im Historie-Modus wird stattdessen über `klasse.abteilung_id = bereich.abteilung_id` gruppiert — beide Spalten existieren bereits (Bundle D: Bereiche sind strukturell 1:1 aus WebUntis-Abteilungen abgeleitet), diese Zuordnung ist nicht jahresabhängig und muss nicht separat historisiert werden. Historische `klasse`-Zeilen ohne passenden Bereich (kein `abteilung_id`-Treffer, z.B. bei einer nur teilweise nachimportierten CSV) werden wie heute stillschweigend aus der Vergleichsliste ausgeschlossen.

**Scope/Berechtigungen bleiben unverändert:** wie bei der Schülerliste basiert die Sichtbarkeit (`resolve_scope`/`resolve_bereich_scope`) weiterhin auf der aktuellen Zuordnung, unabhängig vom betrachteten Schuljahr (bestehende, bewusste Einschränkung aus Plan 16, hier nicht erweitert).

**API/Frontend:** `GET /dashboard/stats` bekommt einen optionalen `schuljahr_id`-Parameter (wie `GET /students`). `Landing.tsx`/der Stats-Hook reichen den bereits vorhandenen `schuljahr`-URL-Parameter durch (derselbe Parameter, der schon Schülerliste/Detail steuert).

## 2. Dropdown-Filter

`get_nav_options` filtert die `schuljahre`-Liste: ein Schuljahr wird nur aufgenommen, wenn `schuljahr.id == aktuelles_schuljahr_id` (immer anzeigen, auch direkt nach einem Rollover ohne bisherigen Snapshot) **oder** mindestens eine `schueler_klasse_historie`-Zeile mit diesem `schuljahr_id` existiert. Blendet damit zuverlässig sowohl zukünftige, in WebUntis schon gelistete Jahre als auch alte, nie importierte Jahre aus.

## Nicht-Ziele

- Keine Historisierung von `bereich_klasse` selbst — die Abteilungs-basierte Ableitung macht das überflüssig.
- Keine Änderung an Scope/Berechtigungen für vergangene Schuljahre (siehe oben).
- Kein Caching/Performance-Arbeit an `_aggregate()` über das Bestehende hinaus — reine Funktionserweiterung um den Zeitraum-/Roster-Parameter.
