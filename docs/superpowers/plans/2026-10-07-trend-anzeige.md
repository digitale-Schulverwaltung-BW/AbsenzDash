# Trend-Anzeige in der Schülerliste (Fehltage / Fehlstunden)

**Ziel:** In der Schülerliste steht hinter den Zahlen „Fehltage" und „Fehlstunden" je ein Trendpfeil (↗ steigend, → gleich, ↘ fallend), farbcodiert. Er vergleicht die letzten N Tage mit den N Tagen davor. N ist wählbar (7 / 14 / 30).

## Entscheidungen (mit dem Auftraggeber geklärt, 2026-10-07)

1. **Zwei Pfeile, keine eigene Spalte:** je ein Pfeil direkt hinter dem Wert in der Spalte „Fehltage" und in der Spalte „Fehlstunden".
2. **Mindestdifferenz als Konstante:** Default 2 Fehltage bzw. 4 Fehlstunden, als benannte Konstanten im Backend (`TREND_MIN_DIFF_FEHLTAGE`, `TREND_MIN_DIFF_FEHLSTUNDEN`), nicht konfigurierbar. Kleinere Differenzen zählen als „gleich". Später ggf. konfigurierbar machen.
3. **Alle Fehlzeiten** zählen (entschuldigt + unentschuldigt), kein Umschalter.
4. **Ferien/Feiertage werden nicht berücksichtigt.** Es gibt aktuell keinen Kalender; ob WebUntis Ferien liefert, ist offen und wird später recherchiert. Die Lücke wird dokumentiert (siehe Phase 3).
5. **Nur Schülerliste**, nicht Detailansicht und nicht Dashboard-Kacheln.

## Semantik

- Fenster A (aktuell): `[heute-N+1, heute]`, Fenster B (vorher): `[heute-2N+1, heute-N]`. „heute" ist das Kalenderdatum (UTC, wie in `sync_orchestrator`).
- Gezählt wird wie in `load_schueler_rohzahlen`: `invalid = false`; Fehltage = Zeilen mit `typ = 'tag'`; Fehlstunden = Summe `fehlstunden_minuten_expr()` über `typ = 'stunde'`, umgerechnet mit `minuten_zu_fehlstunden`.
- `differenz = aktuell - vorher`. Richtung: `steigend` bei `differenz >= Mindestdifferenz`, `fallend` bei `differenz <= -Mindestdifferenz`, sonst `gleich`.
- Liegt das Vorfenster (teilweise) vor dem Schuljahresbeginn (`einstellung.schuljahr_start_cache`), ist kein fairer Vergleich möglich: `richtung = null`, kein Pfeil. (Der Sync holt Fehlzeiten nur ab Schuljahresbeginn.)
- Ohne Parameter `trend_tage` wird kein Trend berechnet (Liste bleibt so schnell wie bisher).

## Phase 1 – Backend

- `backend/app/services/student_query.py`: neue Funktion `load_trend_map(db, schueler_ids, heute, tage, schuljahr_start)` neben `load_schueler_rohzahlen`. Zwei gruppierte Queries (Fehltage, Fehlstunden-Minuten), je mit bedingter Aggregation für Fenster A und B, keine N+1-Queries. Konstanten für die Mindestdifferenzen im selben Modul oder in `fehlzeit_berechnung.py`.
- `backend/app/schemas/students.py`: `TrendWertOut {aktuell, vorher, richtung: Literal["steigend","gleich","fallend"] | None}` und `TrendOut {fehltage: TrendWertOut, fehlstunden: TrendWertOut}`; `StudentOverviewOut.trend: TrendOut | None`.
- `backend/app/api/routes/students.py` (`get_students`): neuer Query-Parameter `trend_tage: Literal[7, 14, 30] | None = None` (alle anderen Werte → 422); füllt `trend` je Schüler, wenn gesetzt.
- Tests (`backend/tests/test_student_query.py`, `test_api_students.py`): festes „heute"; steigend/gleich/fallend; genau an der Mindestdifferenz (±1 darunter/darauf); `invalid` wird ignoriert; Fehltage vs. Fehlstunden getrennt; leere Fenster; Vorfenster vor Schuljahresbeginn → `richtung = null`; ungültiges `trend_tage` → 422; ohne Parameter kein `trend`-Feld befüllt.

## Phase 2 – Frontend

- `frontend/src/api/types.ts` und der Students-Hook: `trend_tage` als Query-Parameter, `trend` im Typ.
- `frontend/src/pages/StudentList/StudentList.tsx`: Pfeil hinter dem Wert in den Spalten „Fehltage" und „Fehlstunden". Farbe: steigend rot, gleich grau, fallend grün; Pfeilform trägt die Information zusätzlich (nicht nur Farbe). Kein Pfeil bei `richtung = null`. Tooltip: z. B. „Letzte 7 Tage: 3, davor: 1".
- Dropdown „Trend-Zeitraum" (7 / 14 / 30 Tage, plus „aus"), wie die übrigen Filter in der URL gehalten.
- Tests (`StudentList.test.tsx`): Pfeil/Farbe/Tooltip je Richtung, kein Pfeil bei `null`, Dropdown löst Request mit `trend_tage` aus.

## Phase 3 – Doku und Roadmap

- `docs/SL.md` bzw. `docs/KL.md`/`docs/BL.md` (je nach Rolle): Bedienung der Trend-Pfeile.
- Bekannte Grenzen, ausdrücklich dokumentieren: Ferien/Feiertage/Wochenenden verzerren Fenster (z. B. erste Woche nach den Ferien); Nachträge in WebUntis ändern das Vorfenster rückwirkend; zu Schuljahresbeginn kein Trend; Mindestdifferenz ist fest (2 Fehltage / 4 Fehlstunden).
- `ROADMAP.md`: neue Zeile; unter „Geplant"/offen: Recherche, ob WebUntis Ferien/Feiertage liefert (dann Trend auf Unterrichtstage normieren).

## Nicht enthalten

Trend in Detailansicht/Dashboard, Konfigurierbarkeit der Mindestdifferenz, Filter/Sortierung nach Trend, Trend nach Entschuldigungsstatus, Ferien-Normierung.
