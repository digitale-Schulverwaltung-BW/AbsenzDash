# Design: Schuljahr-Auswahl/-Historie

Stand: 2026-07-30

Deckt den neuen Roadmap-Punkt "Schuljahr-Auswahl/-Historie" ab (ROADMAP.md, ergänzt im Abschlussreview des Admin-Bereich-Plans). Ausgelöst durch den Live-Fund vom selben Tag: WebUntis führt zwischen den Schuljahren 2025/2026 und 2026/2027 aktuell keins als "aktiv", wodurch der bisherige punktuelle Hotfix in `sync_orchestrator.py` (Commit `47d7e55`) nicht ausreicht — `getKlassen` schlägt serverseitig mit demselben NPE fehl wie `getCurrentSchoolyear`, weil auch dieser Aufruf implizit ein aktuelles Schuljahr voraussetzt, sofern keine `schoolyearId` explizit übergeben wird. Live verifiziert: `getKlassen({"schoolyearId": 28})` funktioniert anstandslos, ebenso `getDepartments`/`getClassregCategories`/`getClassregCategoryGroups`/`getTeachers` (schoulyear-unabhängig) und `getTimetableWithAbsences` mit explizitem Datumsbereich (schoulyear-unabhängig, solange die Daten selbst innerhalb eines vergangenen, aber bekannten Zeitraums liegen).

Eine `schuljahr`-Stammdaten-Cache-Tabelle löst damit drei Dinge auf einmal: den akuten Sync-Ausfall, die im Roadmap-Eintrag gewünschte Historie-Ansicht, und ersetzt den ursprünglich angedachten manuellen Override (der sich als unnötig herausgestellt hat, siehe "Bewusst nicht enthalten").

## 1. Datenmodell

Neue Tabelle `schuljahr`: `id` (= WebUntis-`schoolyearId`, kein eigener Autoincrement), `name` (z.B. `"2025/2026"`), `start_datum`, `end_datum`. Wird bei jedem Sync-Lauf aus `getSchoolyears` per Upsert aktualisiert (kein Löschen — alte Schuljahre bleiben als Referenz für die Historie-Ansicht erhalten, auch wenn WebUntis sie irgendwann aus der Liste nehmen sollte).

**Neue Resolver-Funktion** (ersetzt den bisherigen Hotfix-Try/Except in `sync_orchestrator.py`): `resolve_aktuelles_schuljahr(client, db) -> Schuljahr`
1. `schuljahr`-Cache aus `getSchoolyears` aktualisieren (Upsert aller zurückgegebenen Einträge).
2. `getCurrentSchoolyear` versuchen. Erfolg → das zurückgegebene Schuljahr (per `id` im lokalen Cache nachschlagen oder direkt aus der Antwort übernehmen) ist das Ergebnis.
3. Bei `WebUntisError`: das Schuljahr mit dem größten `end_datum` aus dem lokalen `schuljahr`-Cache zurückgeben (= das zuletzt bekannte, wahrscheinlichste "eigentlich aktuelle" Schuljahr in einer Übergangslücke).

Der Rückgabewert wird an zwei Stellen verwendet:
- `sync_klassen(client, db, schoolyear_id=...)` — `getKlassen`-Aufruf bekommt `{"schoolyearId": schoolyear_id}` statt `{}`. Behebt den akuten Ausfall.
- Bestehende `einstellung.schuljahr_start_cache`-Logik (Zähler-Reset-Erkennung, SPECS.md §5) bleibt unverändert, bekommt aber ihren Wert jetzt aus dieser Resolver-Funktion statt aus dem direkten, ungeschützten `getCurrentSchoolyear`-Aufruf.

Reihenfolge in `run_sync_once`: die Resolver-Funktion muss vor `sync_klassen` laufen — praktisch also ganz am Anfang, vor `sync_abteilungen`/`sync_klassen`/`sync_kategorien`/`import_schueler` (die anderen drei WebUntis-Aufrufe brauchen kein Schuljahr, siehe Live-Test oben, daher keine weitere Umsortierung nötig).

## 2. Backend: Lese-Endpunkte für die Historie

**`GET /dashboard/nav-options`** bekommt ein zusätzliches Feld `schuljahre: list[{id, name, start_datum, end_datum}]` (alle aus dem `schuljahr`-Cache, absteigend nach `start_datum`) — für alle Rollen, analog zu `bereiche`/`klassen`/`rolle`.

**`GET /students`** (Schülerliste) bekommt einen optionalen `schuljahr_id`-Query-Parameter:
- Fehlt der Parameter (oder entspricht dem aktuellen Schuljahr): unverändertes Verhalten (Ampel-Badges aus `schueler_zaehlerstand`, Standard-Filter auf `aktiv=true`).
- Ist ein anderes (vergangenes) Schuljahr angegeben: Response wechselt auf Rohzahlen pro Schüler (`fehltage`, `fehlstunden`, `klassenbuch_anzahl`, direkt aus `fehlzeit`/`klassenbuch_eintrag` im Zeitraum `schuljahr.start_datum`–`schuljahr.end_datum` aggregiert) statt Ampel-Badge/Zählerstand-Feldern. Der `aktiv=true`-Standardfilter entfällt in diesem Modus — inaktive/ehemalige Schüler werden mit angezeigt (Anwendungsfall: nachträgliche Anfragen, z.B. BAföG, zu bereits ausgeschiedenen Schülern).

**`GET /students/{id}`** (Detail) bekommt denselben optionalen `schuljahr_id`-Parameter:
- Fehlt er: unverändertes Verhalten (komplette Historie in allen fünf Abschnitten).
- Ist er gesetzt: `fehlzeiten`, `klassenbuch`, `ausnahmen` und `benachrichtigungen` werden auf den Zeitraum des gewählten Schuljahres gefiltert (Fehlzeiten/Klassenbuch/Benachrichtigungen über ihr jeweiliges Datumsfeld, Ausnahmen über Überlappung: `gueltig_von <= schuljahr.end_datum AND (gueltig_bis IS NULL OR gueltig_bis >= schuljahr.start_datum)`). **`massnahmen` bleibt in jedem Fall ungefiltert** — fachliche Entscheidung (siehe Diskussion): eine protokollierte Maßnahme ist an ein Gespräch mit klarer pädagogischer Ansage gekoppelt, das schuljahresübergreifend relevant bleibt, nicht an einen Kalenderzeitraum.

## 3. Frontend

Neuer Schuljahr-Dropdown in der Navigation, **rechtsbündig** neben den bestehenden Tabs (Übersicht/Schülerliste/Admin), gespeist aus `nav-options.schuljahre`. Wie Bereich/Klasse als URL-Suchparameter (`schuljahr`) geführt, dadurch über Schülerliste und Schüler-Detail hinweg konsistent (Anwendungsfall: Liste nach vergangenem Jahr filtern → Schüler anklicken → Detail zeigt automatisch dasselbe Jahr). Fehlt der Parameter, gilt das aktuelle Schuljahr (Default, unverändertes Verhalten).

**Schülerliste** im Historie-Modus: Rohzahlen-Spalten statt Ampel-Badges, inklusive inaktiver Schüler (keine gesonderte Kennzeichnung als "ehemalig" vorgesehen — bewusst einfach gehalten, siehe Nicht-Ziele).

**Schüler-Detail** im Historie-Modus: die vier gefilterten Abschnitte zeigen nur Einträge aus dem gewählten Schuljahr, der Maßnahmen-Abschnitt bleibt vollständig sichtbar (evtl. mit visuellem Hinweis, dass er nicht gefiltert ist — Detail dem Umsetzungsplan überlassen).

**Sync-Einstellungen-Seite**: zusätzliche rein informative Anzeige, welches Schuljahr der letzte/nächste Sync-Lauf tatsächlich verwendet (Ergebnis der Resolver-Funktion) — kein Eingabefeld, kein Override-Mechanismus.

## Nicht-Ziele dieses Plans

- Kein manueller Admin-Override für das "aktuelle" Schuljahr — die automatische Fallback-Heuristik (aktuellstes bekanntes Schuljahr) deckt den einzigen bekannten Ausfallgrund bereits vollständig ab.
- Keine historische Klassenzuordnung — ein ehemaliger/historischer Schüler wird mit seiner aktuellen/letzten bekannten `klasse_id` angezeigt (oder ohne Klasse, falls keine vorhanden), nicht mit der Klasse, die zum gewählten Schuljahr tatsächlich zutraf.
- Keine Schuljahr-Anbindung im PDF-Export (der Export hat ohnehin schon bewusst keinen Zeitraum-Filter, siehe Plan 7).
- Keine gesonderte visuelle Kennzeichnung ehemaliger Schüler in der Historie-Liste (z.B. "ausgeschieden"-Badge) — reine Datenanzeige.
- Keine rückwirkende Neuberechnung von Eskalationsstufen/Zählerständen für vergangene Schuljahre — `schueler_zaehlerstand` bleibt ein laufender, nicht historisierter Wert; die Historie-Ansicht zeigt ausschließlich Rohdaten.
