# Design: Bundle B — Schüler-Detail Anbindungen

Stand: 2026-08-04

Deckt ROADMAP.md Bundle B ab: zwei unabhängige, kleine Ergänzungen auf der Schüler-Detail-Seite (`StudentDetail.tsx`), zusammen geplant, weil beide dieselbe Seite betreffen, aber inhaltlich getrennt umsetzbar.

## 1. Fach zeigt Kurzname statt Langname

### Befund (Live-Spike gegen die reale WebUntis-Instanz, 2026-08-04, `scratchpad/webuntis_subjects_spike.py`)

- `getTimetableWithAbsences` liefert **keinen** numerischen Fach-Identifier. Das einzige Fach-Feld im Payload heißt trotz des Namens `subjectId`, enthält aber bereits den vollen Langnamen als String (bestätigtes Beispiel: `"subjectId": "Deutsch"`). Vollständige Feldliste eines Eintrags: `absenceReason`, `absentTime`, `checked`, `date`, `endTime`, `excuseStatus`, `invalid`, `startTime`, `status`, `studentGroup`, `studentId`, `subjectId`, `teacherIds`, `user`.
- `getSubjects()` liefert pro Fach `id`, `name` (Kürzel, z.B. `"D"`), `longName` (z.B. `"Deutsch"`), `alternateName`.
- Ein Abgleich `fehlzeit.fach` (= Langname) → `getSubjects().name` (Kürzel) über den Langnamen ist der einzig mögliche Weg, aber **nicht garantiert eindeutig**: bestätigte Kollision an dieser Schule — sowohl `BK` (id 16) als auch `BKOM` (id 458) tragen exakt denselben Langnamen `"Betriebliche Kommunikation"`. Zusätzlich können Langnamen veralten: `"Bildende Kunst"` (in echten Fehlzeiten-Daten beobachtet) taucht in der aktuellen `getSubjects()`-Liste gar nicht mehr auf (Fach vermutlich umbenannt oder deaktiviert).
- Entscheidung (Rücksprache 2026-08-04): Eindeutigkeit ist kein hartes Ziel. Bei Kollision gewinnt das erste Fach in der von `getSubjects()` gelieferten Reihenfolge; sollte das in der Praxis stören, ist das ein Datenpflege-Thema für den WebUntis-Admin, kein Software-Problem.

### Backend-Änderung

`webuntis_fehlzeit_sync.py`, `sync_fehlzeiten`:

1. Zusätzlicher `client.call("getSubjects", {})` einmal pro Sync-Lauf (analog zum bestehenden `ExcuseStatus`-Cache-Muster, aber ohne eigene DB-Tabelle — Fach ist reine Anzeige, keine Business-Logik hängt daran, siehe TECH-SPEC.md, daher kein FK-Katalog wie bei `excuse_status`/`classreg_category`).
2. Daraus ein `dict[str, str]` bauen: `longName → name` (Kürzel). Bei doppeltem `longName` gewinnt der erste Eintrag in Antwortreihenfolge (kein zusätzliches Sortieren).
3. Überall, wo aktuell `fehlzeit.fach = row.get("subjectId") or None` gesetzt wird (drei Stellen im Modul), stattdessen über das Mapping auflösen: `kurzname_by_longname.get(row.get("subjectId"), row.get("subjectId")) or None` — Kürzel wenn auflösbar, sonst unverändert der Langname als Fallback (nie ein leeres Feld statt vorhandener Information).

### Dokumentation

Neuer Nachtrag in TECH-SPEC.md Abschnitt 1.2 (Nachtrag 5), der den Live-Befund festhält: `subjectId` ist der Langname statt einer ID, `getSubjects()` als Auflösungsquelle, die bestätigte BK/BKOM-Kollision als Beispiel, und die bewusste "erstes Vorkommen gewinnt"-Vereinfachung.

### Backfill für Bestandsdaten

Da der reguläre Sync inkrementell läuft (nur seit `letzter_sync_am`, siehe `sync_orchestrator._fehlzeiten_zeitraum`), würden bereits gespeicherte historische `fehlzeit.fach`-Werte ohne Zusatzmaßnahme dauerhaft ihren Langnamen behalten. Einmaliges Backfill-Skript, das dieselbe Resolver-Logik (extrahiert als eigene, testbare Funktion, z.B. `resolve_fach_kurzname(langname, kurzname_by_longname)`) auf alle bestehenden `fehlzeit`-Zeilen anwendet. Ablagepfad und genaue Ausführungsform (eigenständiges Skript vs. Data-Migration) wird im Umsetzungsplan anhand bestehender Projektkonventionen entschieden.

## 2. PDF-Export-Anbindung im Frontend

Der Endpunkt `GET /students/{id}/export.pdf?sections=...` existiert bereits vollständig (Plan 7), hat aber keine Anbindung im Frontend. Kein Backend-Change nötig.

### `client.ts`

Neue Funktion `apiDownload(path: string): Promise<{ blob: Blob; filename: string }>`, analog zu `apiGet`, aber:
- Response wird als `Blob` gelesen statt als JSON.
- Dateiname wird aus dem `Content-Disposition`-Header geparst (Backend setzt ihn immer, siehe `export_service.build_export_filename`); Fallback auf einen generischen Namen (`export.pdf`), falls der Header unerwartet fehlt oder nicht parsbar ist.
- Gleiche Fehlerbehandlung wie die bestehenden `api*`-Funktionen (`ApiError` bei `!response.ok`).

Auslösen des Downloads: kurzlebiges `<a>`-Element mit `URL.createObjectURL(blob)` und `download`-Attribut, per Klick ausgelöst und danach entfernt (kein neuer Tab, kein Popup-Blocker-Risiko, funktioniert innerhalb des WP-iframe-Kontexts).

### Schuljahr-Filter (Korrektur ggü. erstem Entwurf)

Der Export filtert bisher **gar nicht** nach Zeitraum — `render_student_export_html` ruft `student_query.load_student_detail(db, schueler.id)` ohne `von`/`bis` auf und liefert damit immer die komplette Historie über alle Schuljahre. Das ist nicht das gewünschte Verhalten: gerade außerhalb eines laufenden Schuljahres (z.B. jetzt, in den Sommerferien) soll ein gezielter Export "nur letztes Schuljahr" möglich sein. Die dafür nötige Filterung existiert im Backend bereits fertig (Schuljahr-Historie-Feature, `_resolve_schuljahr_zeitraum` + `load_student_detail(db, id, von, bis)`), wird vom Export nur noch nicht genutzt.

- `export_student_pdf` (`students.py`, gleiche Datei wie `_resolve_schuljahr_zeitraum`) bekommt einen zusätzlichen optionalen Query-Parameter `schuljahr_id: int | None = None`, aufgelöst über die bereits vorhandene `_resolve_schuljahr_zeitraum(db, schuljahr_id)` — identisches Muster wie bei `GET /students` und `GET /students/{id}`.
- `render_student_export_html` bekommt zwei zusätzliche optionale Parameter `von`/`bis`, durchgereicht an `load_student_detail(db, schueler.id, von, bis)`. Maßnahmen bleiben bewusst ungefiltert (konsistent mit der bereits getroffenen Entscheidung für die Detail-Ansicht, siehe `docs/superpowers/specs/2026-07-30-schuljahr-auswahl-design.md` Abschnitt 2).
- `export_pdf.html`: Meta-Zeile ergänzt um den betrachteten Zeitraum (`{{ schuljahr_name }}` falls gesetzt, sonst z.B. "gesamte Historie") — ohne das wäre auf dem gedruckten Blatt nicht erkennbar, für welchen Zeitraum es gilt.

### Neue Komponente `PdfExportSection.tsx`

Liegt unter `components/StudentDetail/`, eingebunden in `StudentDetail.tsx` als letzter `<section>` (unterhalb von Benachrichtigungen), sichtbar für alle Rollen (keine Frontend-Rollenprüfung nötig — der Endpunkt scoped bereits über `get_scoped_schueler`).

- 5 Checkboxen, eine pro `sections`-Wert (Fehlzeiten, Klassenbuch, Maßnahmen, Ausnahmen, Benachrichtigungen), alle standardmäßig angehakt.
- Übernimmt den aktuell gewählten Schuljahr-Kontext: `StudentDetail.tsx` liest `schuljahr` bereits aus den URL-Suchparametern (bestehender Code, `useStudentDetail(studentId, schuljahrId)`) und reicht `schuljahrId` als Prop durch. Ist ein Schuljahr gewählt, wird es als `schuljahr_id` an den Export-Request angehängt und im UI kurz benannt (z.B. "Export für Schuljahr 2024/2025"); ohne Auswahl (aktuelles Schuljahr/Default) läuft der Export wie gewohnt ungefiltert über die komplette Historie — keine eigene Auswahl-UI in dieser Sektion, der bestehende Schuljahr-Dropdown in der Navigation bleibt die einzige Bedienstelle dafür.
- Button "PDF exportieren". Baut den `sections`-Query-Param aus den angehakten Boxen; sind alle angehakt (Normalfall), wird der Parameter ganz weggelassen (entspricht dem Backend-Default, kürzere URL).
- Lokaler `useState` für Pending/Error (kein `useMutation`/React-Query nötig — kein JSON-Response, kein Cache-Invalidieren, kein Wiederverwendungsbedarf an anderer Stelle).
- Fehleranzeige im bestehenden Stil (`sectionStyles.formError`, wie in `ThresholdRules.tsx`/`MassnahmenSection.tsx`).
- Kein Verhalten für "keine Checkbox angehakt" spezifiziert außer der offensichtlichen Konsequenz (leerer `sections`-Query-Param → Backend-422, siehe `_EXPORT_SECTIONS`-Validierung) — Umsetzungsplan entscheidet, ob das clientseitig verhindert wird (Button disabled o.ä.) oder der Backend-Fehler einfach durchgereicht wird; angesichts des frischen Lessons-Learned aus dem Schwellwert-Regel-422-Fix (ROADMAP Bundle E) sollte hier dieselbe clientseitige Vorprüfung angewendet werden.

## Performance: zusätzlicher `getSubjects()`-Call pro Sync

Live gemessen (`scratchpad/webuntis_subjects_spike.py`, 2026-08-04): `getSubjects()` liefert an dieser Schule 466 Fächer; der Call ist ein kleiner Bruchteil der Gesamtlaufzeit eines Testlaufs, der zusätzlich 46.503 Fehlzeiten-Einträge lädt. Der reguläre Sync läuft alle 30 Minuten (Default `einstellung.sync_interval_cron`) und holt bereits deutlich größere Datenmengen (z.B. 7.006 Schüler komplett bei jedem Lauf) — eine zusätzliche kleine RPC für 466 Fach-Stammdaten fällt performance-mäßig nicht ins Gewicht, kein gesondertes Caching/Throttling nötig.

## Nicht-Ziele dieses Plans

- Keine neue DB-Tabelle für Fach-Stammdaten — reine String-Auflösung zur Anzeigezeit des Sync, kein FK-Katalog wie bei `excuse_status`/`classreg_category`.
- Keine Garantie für global eindeutige Kurznamen — bewusst in Kauf genommene Einschränkung bei Namenskollisionen in den WebUntis-Fach-Stammdaten (siehe oben).
- Kein eigener Schuljahr-Auswahl-UI-Baustein innerhalb der PDF-Export-Sektion — der bestehende Schuljahr-Dropdown in der Navigation ist die einzige Bedienstelle, die Export-Sektion übernimmt den Kontext nur passiv.
