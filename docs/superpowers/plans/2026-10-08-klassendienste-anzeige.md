# Klassendienste (Entschuldigungspflicht / Attestpflicht) aus WebUntis anzeigen

**Ziel:** Schüler, für die in WebUntis ein „Klassendienst" wie *Entschuldigungspflicht* oder *Pflicht zur Vorlage ärztl. Atteste* eingetragen ist, werden in AbsenzDash schreibgeschützt angezeigt (Badge in der Schülerliste, Zeitraum im Schüler-Detail). Die Daten werden einmal täglich aus WebUntis gelesen.

Grundlage ist die Recherche per Sonde (`backend/scripts/probe_webuntis_klassendienste.py`, Ergebnisse siehe ROADMAP.md und `docs/ADMIN.md`).

## Entscheidungen (mit dem Auftraggeber geklärt, 2026-10-08)

1. **Schreibgeschützte Anzeige**, keine Maßnahme (kein `Massnahme`-Datensatz, keine Vermischung mit manuell erfassten Maßnahmen).
2. **Nur anzeigen:** keine Auswirkung auf Zähler, Eskalationsstufen oder Benachrichtigungen (`setzt_zaehler_zurueck` ist nicht betroffen).
3. **Konfigurierbare Dienste:** Die Dienste sind schuleigene WebUntis-Stammdaten (hier: ID 26 *Entschuldigungspflicht*, ID 27 *Pflicht zur Vorlage ärztl. Atteste*; weitere Dienste der Schule: 1 Klassenordner, 2 Klassensprecher, 3 Klassensprecher Stv.). Welche IDs importiert werden, pflegt die Schulleitung in der Admin-Oberfläche. Ohne konfigurierten Dienst passiert nichts (Feature aus).
4. **Rhythmus höchstens einmal täglich.**

## Technische Grundlage (durch Sonde auf der echten Instanz bestätigt)

- Interner, nicht offiziell dokumentierter WebUntis-Dienst: `POST /WebUntis/jsonrpc_web/jsonStudentDutyService`, Methode `getStudentDutySchedulerData`, Params `[webuntisKlassenId, dienstId]`.
- Funktioniert mit der Session des Service-Accounts, wenn der Header `X-CSRF-TOKEN` mitgesendet wird. Der Token steht als Skriptvariable `csrfToken` (Header-Name in `csrfHeader`) in der HTML-Seite `GET /WebUntis/index.do` (Cookie-Session reicht; Bearer-JWT ist nicht nötig). Cookies: `JSESSIONID`, `Tenant-Id`, `schoolname`, `traceId` (kommen aus dem Login des `WebUntisClient`).
- Antwort (`result`): `klasseName`, `dutyName`, `matrix.columns[]` (Wochen: `id` = Montag als YYYYMMDD, `endDate`, `weekType`, `numberOfWorkdays`, `holidays`), `matrix.rows[]` je Schüler mit `studentDTO.id` (numerische WebUntis-Schüler-ID), `relations` (Wochen-IDs, in denen der Schüler den Dienst hat) und `absences` (Wochen mit Fehlzeiten, für uns irrelevant). Beispiel Klasse 2BFE1/2, Dienst 26: 4 von 25 Schülern haben `relations` (44 Wochen, 28.09.2026 bis 26.07.2027, inklusive Ferienwochen). Eine Antwort ist ca. 20–30 KB groß.
- **Schüler-Zuordnung:** `studentDTO.id` = `getStudents[].id` (25/25), und `getStudents[].key` entspricht `Schueler.externe_id` (24/25 Treffer). Ein Matrix-Schüler ließ sich nicht über `key` zuordnen, über (Vorname, Nachname) aber eindeutig (25/25). Ursache unbekannt (vermutlich leerer oder abweichender `key`: bei 5 von 7642 WebUntis-Schülern fehlt `key`).
- Fehlschläge der Sonde, die wir bewusst **nicht** nutzen: REST `/api/classreg/classservices` (liefert leere Rollen-Liste, vermutlich Lehrerrollen), Bearer-Token-Auth, `classserviceslist.do` (HTML), geratene Methodennamen (`getStudentDuties` usw.).
- Offen, nicht blockierend: Die Liste aller Dienste (`dutyOptions`) kommt in einer anderen Antwort-Form (im Browser ein Request mit `id: 0` an denselben Dienst, Methodenname unbekannt). Bis das geklärt ist, tragen Admins Dienst-ID und Bezeichnung von Hand ein.

## Datenmodell

Neue Tabellen (Alembic-Migration):

- `klassendienst_typ`: `id`, `webuntis_dienst_id` (int, unique), `bezeichnung` (String 100, Klartext aus WebUntis bzw. Admin), `kuerzel` (String 10, für das Badge, z. B. „E", „A"), `aktiv` (bool). **Kein Seeding**, die Schulleitung legt Einträge an.
- `schueler_klassendienst`: `id`, `schueler_id` (FK `schueler`, ON DELETE CASCADE), `klassendienst_typ_id` (FK `klassendienst_typ`, ON DELETE CASCADE), `von` (date, Montag der ersten Woche), `bis` (date, `endDate` der letzten Woche, Sonntag). Unique über (`schueler_id`, `klassendienst_typ_id`, `von`). Zusätzlich `Einstellung.klassendienste_letzter_sync_am` (DateTime, nullable) für den Tages-Takt.

Aus `relations` werden zusammenhängende Wochen zu Zeiträumen verschmolzen (aufeinanderfolgende Montage, 7 Tage Abstand); eine Lücke ergibt einen neuen Zeitraum. Ferienwochen innerhalb eines Zeitraums bleiben drin, so wie WebUntis sie liefert.

## Phase 1 – Backend: Import

- `backend/app/integrations/webuntis_client.py` (oder ein neues Modul `webuntis_duty_client.py`): Methode zum Holen von CSRF-Token und -Headername aus `index.do` und zum Aufruf des Duty-Dienstes. Nur lesende Methode `getStudentDutySchedulerData`; Fehler (403, Login-HTML, JSON-RPC-Fehler) werden als eigene Ausnahme klassifiziert; Token wird pro Lauf einmal geholt und bei 403 genau einmal neu geholt. Token, Cookies und CSRF-Werte werden nie geloggt.
- `backend/app/services/webuntis_klassendienst_sync.py`: `sync_klassendienste(client, db, heute)`. Ablauf:
  1. Ohne aktive `klassendienst_typ` sofort zurück.
  2. `getStudents` einmal holen und `numerische id → key` abbilden.
  3. Für jede `Klasse` des aktuellen Schuljahres (`Klasse.webuntis_id`) und jeden aktiven Typ: Duty-Aufruf, `rows[]` auswerten.
  4. Schüler: `studentDTO.id` → `key` → `Schueler.externe_id`. **Nicht zuordenbare Schüler werden übersprungen und gezählt/geloggt (Warnung mit Anzahl und Klasse, keine Namen)**. Kein Namens-Fallback, weil eine falsch zugeordnete Pflicht fachlich schlimmer ist als eine fehlende.
  5. Pro (Schüler, Typ) die Zeiträume neu schreiben (Delete und Insert innerhalb einer Transaktion pro Klasse und Typ), Schüler ohne `relations` bekommen keine Zeile; entfernte Pflichten verschwinden damit automatisch.
  6. Fehler bei einer Klasse brechen nicht alles ab (Klasse überspringen, zählen, am Ende warnen); die alten Zeilen dieser Klasse bleiben dann unverändert.
- Einbindung in `sync_orchestrator._run_sync_once_impl`, **isoliert** in try/except: Ein Fehler des internen Dienstes darf den normalen Sync nicht scheitern lassen. Lauf nur, wenn `klassendienste_letzter_sync_am` älter als 24 Stunden ist (oder leer); danach setzen.
- Tests (test-first, gemockter Client): Token-Extraktion aus HTML, 403 mit einmaligem Re-Fetch, Wochen → Zeiträume (zusammenhängend, mit Lücke, Jahreswechsel, Einzelwoche), Schüler-Zuordnung (Treffer, fehlender `key`, nicht in der DB), Neuschreiben/Entfernen, Klassenfehler isoliert, Tages-Takt, Feature aus ohne konfigurierte Typen, kein Namen-/Token-Logging.

## Phase 2 – Backend: Admin-API und Anzeige-API

- `GET/PUT /admin/klassendienst-typen` (nur `schulleitung`, analog `measure-types` in `backend/app/api/routes/admin.py` und `measure_type_service.py`, inkl. Audit-Log). Validierung: `webuntis_dienst_id` eindeutig, Kürzel nicht leer.
- `GET /students` (Übersicht): pro Schüler `klassendienste: [{typ_id, kuerzel, bezeichnung, von, bis, aktiv_heute}]` (ohne Mehraufwand durch eine gesammelte Abfrage über alle Schüler der Seite, keine N+1-Queries). `GET /students/{id}`: vollständige Liste.
- Tests: Rollen-/Scope-Prüfung wie bei den bestehenden Endpunkten, Query-Anzahl, Archivmodus (`schuljahr`) ohne Klassendienste.

## Phase 3 – Frontend

- Admin-Seite „Klassendienste" (analog `MeasureTypes.tsx`): Dienst-ID, Bezeichnung, Kürzel, aktiv; Hinweis, dass IDs aus den WebUntis-Stammdaten stammen.
- Schülerliste: kleines Badge je aktivem Dienst (Kürzel, Tooltip „Entschuldigungspflicht seit 28.09.2026"), nur wenn der Zeitraum heute gilt; zukünftige oder beendete Zeiträume nur im Detail.
- Schüler-Detail: Abschnitt „Klassendienste (aus WebUntis, schreibgeschützt)" mit Zeiträumen.
- Tests für Badge, Tooltip, leeren Zustand, Admin-Formular.

## Phase 4 – Doku und Roadmap

- `docs/ADMIN.md`: Einrichtung (Dienst-IDs eintragen), Tages-Takt, Verhalten bei Fehlern, dass der Dienst intern und nicht offiziell dokumentiert ist und sich bei WebUntis-Updates ändern kann, Hinweis auf nicht zuordenbare Schüler im Log.
- `docs/KL.md`/`BL.md`/`SL.md`: Bedeutung der Badges.
- `ROADMAP.md`: Punkt „Klassendienste als Maßnahmen" abschließen, Folgepunkte: Methodenname für die Dienst-Liste (`dutyOptions`), Namensfallback (bewusst nicht gebaut), Ferien-Normierung der Trend-Anzeige per `getHolidays`.

## Risiken

- **Interner Dienst:** kann sich bei WebUntis-Updates ändern; der Import ist isoliert und meldet Fehler im Log, bricht den Sync aber nicht.
- **Zuordnung:** nur über `key`; einzelne Schüler ohne passenden `key` fehlen in der Anzeige (Warnung im Log).
- **Datenmenge:** ca. 111 Klassen × Anzahl Dienste Aufrufe pro Lauf (ca. 220 bei zwei Diensten), einmal täglich; Aufrufe nacheinander, keine Parallelität.
- **Datenschutz:** Namen aus `studentDTO` werden nicht gespeichert und nicht geloggt; gespeichert werden nur Zuordnung, Typ und Zeitraum.

## Nicht enthalten

Einfluss auf Zähler/Eskalation, Benachrichtigungen, Schreiben nach WebUntis, Namens-Fallback bei der Zuordnung, automatische Ermittlung der Dienst-Liste.
