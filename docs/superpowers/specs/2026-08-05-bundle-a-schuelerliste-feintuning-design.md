# Bundle A — Schülerliste-Feintuning (Design)

Begleitdokument zu [ROADMAP.md](../../../ROADMAP.md) Abschnitt "Bundle A — Schülerliste-Feintuning". Deckt drei zusammenhängende Themen ab, die alle dieselbe Komponente (`GET /students`, `frontend/src/pages/StudentList/StudentList.tsx`) und denselben Aggregations-Query (`student_query.py`) betreffen:

1. Sortierbare Spalten
2. Spalten-Aufteilung Zählerstand → Fehltage / Fehlstunden / Einträge, inkl. Eskalationsstufe als Mini-Badge
3. Fehlstunden als minutenbasierte Dezimalzahl statt Integer-Count, plus Entschuldigt/Unentschuldigt-Split für Fehltage und Fehlstunden

## Ausgangslage

**Fehlstunden bisher:** `Fehlzeit`-Zeilen mit `typ='stunde'` (echte Uhrzeit `start_zeit`/`end_zeit`) wurden bisher 1:1 gezählt (`func.count()`), unabhängig von der tatsächlichen Dauer der jeweiligen Absenz. WebUntis liefert unter `typ='stunde'` sowohl komplett gefehlte Einzelstunden (≈45 Min.) als auch kurze Verspätungen (z.B. 08:00–08:15, 15 Min.) — beide wurden bisher identisch als "1 Fehlstunde" gezählt. `start_zeit`/`end_zeit` stehen pro Zeile in der DB, wurden aber bisher nicht zur Dauerberechnung genutzt. WebUntis' eigenes `absentTime`-Feld ist laut TECH-SPEC.md Abschnitt 1.2 bewusst verworfen worden (Einheit/Bedeutung unklar, nicht verlässlich).

**Entschuldigt/Unentschuldigt bisher:** `fehlzeit.excuse_status_id` → `excuse_status.zaehlt_als_entschuldigt` existiert bereits und wird von der Eskalations-Engine genutzt (`schwellwert_stufe.fehlzeiten_filter = nur_unentschuldigt | alle`). Die Schülerliste selbst zeigt diesen Split bisher nicht an.

**Ziel:** Beide Kennzahlen genauer und transparenter machen, ohne die Eskalations-Engine strukturell umzubauen — nur ihre Zähl-Logik für `fehlstunden` präzisieren.

## Datenmodell

| Tabelle/Spalte | Bisher | Neu |
|---|---|---|
| `schwellwert_stufe.schwellenwert` | `Integer` | `Numeric(6,2)` |
| `schueler_zaehlerstand.aktueller_stand` | `Integer` | `Numeric(6,2)` |

Beide Spalten werden umgestellt, weil `schwellwert_stufe.einheit = 'fehlstunden'`-Regeln jetzt gegen eine Dezimalzahl (z.B. 5,5 Fehlstunden) statt gegen einen Integer-Count geprüft werden. Reiner Spaltentyp-Wechsel per Migration (`ALTER COLUMN ... TYPE numeric(6,2)`), keine Datenverluste — das System ist noch nicht live, bestehende Werte sind Test-/Dev-Daten. `fehltage`/`klassenbuch`-Einheiten bleiben ganzzahlige Werte, passen aber unverändert in `Numeric(6,2)`.

Kein neues Feld auf `fehlzeit` nötig — `start_zeit`, `end_zeit` und `excuse_status_id` sind bereits vorhanden und ausreichend.

## Fehlstunden-Berechnung

Neue Konstante `STUNDENLAENGE_MINUTEN = 45` (Ablage: neues Modul `app/services/fehlzeit_berechnung.py`, das die Formel zentral kapselt, damit sie nicht an drei Stellen dupliziert wird).

```
fehlstunden = round(SUM(end_zeit - start_zeit) über alle typ='stunde'-Zeilen des Schülers / STUNDENLAENGE_MINUTEN, 2)
```

`typ='tag'`-Zeilen bleiben von dieser Formel unberührt (weiterhin reiner Tage-Count) — ihre `start_zeit`/`end_zeit` sind feste Platzhalter (`0`/`2359`, siehe TECH-SPEC.md Abschnitt 1.2 Nachtrag), keine echte Zeitspanne.

Der Divisor ist fix `45` (keine konfigurierbare Stundenlänge pro Schule/Klasse) — YAGNI, keine bekannte Anforderung für abweichende Stundenlängen an dieser Schule.

**Betroffene Stellen (alle rufen künftig die zentrale Formel aus `fehlzeit_berechnung.py` auf):**

- `student_query.py:210-223` (Schülerliste-Aggregation je Schüler): von `func.count()` auf `func.sum(Fehlzeit.end_zeit - Fehlzeit.start_zeit)` für `typ='stunde'`, danach durch 45 teilen und auf 2 Nachkommastellen runden.
- `dashboard_query.py:112-120` (`avg_fehlstunden` fürs Dashboard): gleiche Umstellung vor der Mittelwertbildung.
- `eskalations_pruefung.py::_zaehle_fuer_stufe` (Zeile 89-104): für `stufe.einheit == "fehlstunden"` ebenfalls Summe/45 statt Count. Der nachgelagerte Vergleich `anzahl >= stufe.schwellenwert` (Zeile 131) funktioniert mit `Decimal`/`Numeric` unverändert, da SQLAlchemy `Numeric` als Python `Decimal` liefert und Pydantic/FastAPI das sauber (de-)serialisiert.

## Entschuldigt/Unentschuldigt-Split (Fehltage + Fehlstunden)

- Schülerliste-Spalten zeigen weiterhin nur die **Gesamtzahl** (Fehltage, Fehlstunden) — kompakte Liste, keine zusätzliche visuelle Dichte.
- Der Split wird zusätzlich pro Schüler mitgeliefert und bei Hover (Tooltip) bzw. auf der Schüler-Detailseite angezeigt, z.B. "5 Fehltage (3 entschuldigt, 2 unentschuldigt)" / "3,4 Fehlstunden (2,1 entschuldigt, 1,3 unentschuldigt)".
- Berechnung: gleiche Aggregation wie oben, zusätzlich gefiltert über `ExcuseStatus.zaehlt_als_entschuldigt` (analog zum bestehenden `nur_unentschuldigt`-Join in `eskalations_pruefung.py:99-102`). Zeilen ohne `excuse_status_id` (noch nicht geprüft) zählen als **unentschuldigt** — sicherer Default, konsistent mit der bestehenden Eskalationslogik (`OR excuse_status_id IS NULL`).
- Reine Anzeige-Erweiterung. Die Eskalations-Engine selbst wird **nicht** verändert — sie nutzt schon heute `fehlzeiten_filter` unabhängig von dieser Anzeige.

## API-Schema (`app/schemas/students.py`)

```python
class FehlzeitSplitOut(BaseModel):
    gesamt: float
    entschuldigt: float
    unentschuldigt: float

class StudentOverviewOut(BaseModel):
    ...
    fehltage: FehlzeitSplitOut | None = None       # bisher: int | None
    fehlstunden: FehlzeitSplitOut | None = None     # bisher: int | None
    klassenbuch_anzahl: int | None = None            # unverändert, kein Split
```

`fehltage`/`fehlstunden` wechseln von `int | None` auf `FehlzeitSplitOut | None` — Breaking Change am bestehenden Feld, aber unkritisch, da noch nicht live und Frontend im selben Bundle mitgezogen wird. Für Fehltage bleiben `entschuldigt`/`unentschuldigt`/`gesamt` ganzzahlige Werte (aber `float`-typisiert im Schema, damit ein einheitlicher Typ für beide Kennzahlen gilt — vereinfacht das Frontend).

## Frontend (`StudentList.tsx`)

- Bisherige "Zählerstand"-Spalte wird zu drei sortierbaren Spalten: **Fehltage**, **Fehlstunden**, **Einträge** (Klassenbuch). Sortier-Parameter im Backend-Query (`student_query.list_students`), klickbare Spaltenköpfe, Persistenz als URL-Parameter (analog zu `bereich`/`klasse`/`schuljahr`). Sortierung nutzt jeweils `gesamt` (nicht den Split).
- Farb-Codierung der Fehltage-/Fehlstunden-Werte zwischen den Extremwerten der aktuell sichtbaren Liste (grün→rot).
- Eskalationsstufe als kleiner runder farbiger Mini-Badge (nur die Stufen-Zahl, Spektrum grün (Stufe 0) bis dunkelrot (höchste Stufe)) — separat von den Rohzahlen-Spalten.
- Split-Tooltip bei Hover über die Fehltage-/Fehlstunden-Zahl (Inhalt s.o.).
- Historie-Modus (gefiltert nach `schuljahr_id`): Sortierung nach den Rohzahlen-Spalten bleibt wie im bisherigen Bundle-A-Scope vorgesehen nutzbar — keine Sonderbehandlung nötig, da die neuen Felder genauso wie die bisherigen `fehltage`/`fehlstunden`-Zahlen aus demselben zeitraumgefilterten Query kommen.

## Nicht im Scope

- Keine konfigurierbare Stundenlänge pro Schule/Klasse (fix 45 Min.).
- Kein separates rohes Minutenfeld (`verspaetung_minuten`) — die Dezimalzahl der Fehlstunden deckt den ursprünglichen Wunsch ("Verspätungen sichtbar machen") ab.
- Keine Änderung an `fehltage`-Berechnung (bleibt Integer-Count pro Tag, kein Minuten-Bezug — Tage haben keine sinnvolle "Dauer").
- Keine Änderung an der Eskalations-Engine-Struktur (Precedence, Empfänger-Auflösung) — nur die Zähl-Formel für `einheit='fehlstunden'` wird präzisiert.
- Kein Rekalibrieren bestehender `schwellwert_regel`-Schwellwerte durch dieses Bundle — falls nach der Umstellung bestehende Schwellwerte (die bisher gegen Integer-Counts kalibriert waren) fachlich nicht mehr passen, ist das manuelle Nacharbeit im Dashboard-Admin-Bereich, kein Code-Thema.

## Testing

- Backend: Unit-Tests für `fehlzeit_berechnung.py` (Rundung, Ausschluss von `typ='tag'`, Umgang mit `invalid=True`-Zeilen).
- Backend: bestehende Tests in `test_student_query.py`, `test_eskalations_pruefung.py` müssen auf die neue Formel angepasst werden (Fixtures mit `start_zeit`/`end_zeit` statt reiner Zeilenanzahl).
- Backend: Migrationstest — Spaltentyp-Wechsel auf Test-DB, Bestandsdaten bleiben lesbar.
- Frontend: Sortier-Interaktion, Tooltip-Split-Anzeige, Farb-Codierung bei Rand-/Extremwerten (z.B. alle Schüler mit 0 Fehlstunden).
