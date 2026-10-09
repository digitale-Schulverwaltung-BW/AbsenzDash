# Manueller Sync im Hintergrund („Sync jetzt ausführen")

**Ziel:** `POST /admin/sync-now` blockiert nicht mehr, bis der Sync fertig ist. Der Sync läuft im Backend im Hintergrund, die Admin-Oberfläche zeigt Laufzeit und Ergebnis über eine Statusabfrage. Das beseitigt die Abhängigkeit von Proxy-Timeouts (WordPress-Proxy 120 s, nginx-Standard 60 s), auch für Schulen mit mehr Schülern und Klassen.

## Ausgangslage (Code)

- `POST /admin/sync-now` (`backend/app/api/routes/admin.py`) ruft `run_sync_once(db)` **synchron** in der Request-Session auf und antwortet erst danach mit `{status: "ok", abgeschlossen_am}` (200) bzw. 409 (läuft schon) / 502 (Fehler). Kein Retry-Loop.
- Der zeitgesteuerte Sync läuft schon im Hintergrund (`backend/app/core/scheduler.py`: `_run_main_sync_job` → `asyncio.create_task(run_full_sync(...))`, mit Retry-Loop in `run_full_sync`, eigene Session je Versuch).
- `run_sync_once` serialisiert über `_sync_lock` (`asyncio.Lock`, nur innerhalb eines Prozesses) und wirft `SyncAlreadyRunningError`. Der Backend-Container startet uvicorn ohne `--workers` (ein Prozess), das Lock reicht also.
- Frontend: `frontend/src/api/hooks/useTriggerSyncNow.ts` und der Button in `frontend/src/pages/Admin/SyncSettings.tsx` (zeigt „Sync erfolgreich ausgeführt." bzw. „Sync fehlgeschlagen.", „Letzter Sync" aus `GET /admin/sync-settings`).
- Der Sync enthält inzwischen den Klassendienst-Import (höchstens alle 24 h, bis zu ca. 220 Aufrufe) und läuft damit beim ersten Mal und bei großen Schulen länger als die Proxy-Timeouts.

## Entscheidungen (Vorschläge, vom Auftraggeber zu bestätigen)

1. **Verlauf in der Datenbank** (neue Tabelle `sync_lauf`) statt nur im Speicher: Der Status überlebt einen Neustart, und die Oberfläche kann auch zeitgesteuerte Läufe anzeigen (hilft bei Fehlersuche).
2. **Manueller Sync ohne Retry-Loop** wie bisher (ein Versuch, schnelles Feedback); der zeitgesteuerte Sync behält seinen Retry-Loop.
3. **Grobe Phasenanzeige** („WebUntis-Stammdaten", „Fehlzeiten", „Klassenbuch", „Klassendienste", „Eskalationsprüfung") statt eines Fortschrittsbalkens.
4. **API-Bruch akzeptiert:** `POST /admin/sync-now` antwortet künftig `202` mit `{status: "gestartet", lauf_id}` statt `200` mit dem fertigen Ergebnis. Es gibt nur einen Aufrufer (Admin-Oberfläche).

## Datenmodell

Neue Tabelle `sync_lauf` (Alembic-Migration, kein Seeding):

- `id`, `gestartet_am` (DateTime tz), `beendet_am` (DateTime tz, nullable), `status` (`laufend` | `ok` | `fehler` | `abgebrochen`), `ausgeloest_von` (`zeitplan` | `manuell`), `nutzer_id` (FK `nutzer`, nullable, ON DELETE SET NULL), `phase` (String 50, nullable), `fehler_kurz` (String 300, nullable; nur Klasse/Art des Fehlers und gekürzte Meldung, nie Tokens, Cookies, Namen).
- Aufräumen: Beim Start des Backends werden Zeilen mit `status = laufend` auf `abgebrochen` gesetzt (der Prozess, der sie geführt hat, ist weg). Zeilen, die älter als 6 Stunden und noch `laufend` sind, gelten in der Statusabfrage als `abgebrochen`. Alte Zeilen werden beim Anlegen einer neuen auf die letzten 200 gekürzt.

## Phase 1 – Backend

- `run_sync_once` bekommt optional `ausgeloest_von`/`nutzer_id`, legt zu Beginn eine `sync_lauf`-Zeile an (eigene kurze Session über `async_session_factory`, damit der Fortschritt auch bei einem Rollback des Sync-Laufs sichtbar bleibt), aktualisiert `phase` an den Schrittgrenzen und schließt sie mit `ok` bzw. `fehler` (+ `fehler_kurz`) ab. `SyncAlreadyRunningError` legt keine Zeile an.
- `POST /admin/sync-now`: prüft, ob schon ein Lauf aktiv ist (409 wie bisher), startet `run_sync_once` als Hintergrund-Task (Referenz in einem Set halten wie `_background_sync_tasks` im Scheduler, damit der Task nicht vom Garbage Collector entfernt wird; Fehler im Task werden geloggt und im `sync_lauf` vermerkt) und antwortet sofort mit `202 {status: "gestartet", lauf_id}`. Das Audit-Log `admin_sync_now_triggered` bleibt (Details `{"status": "gestartet", "lauf_id": …}`); das Ergebnis steht im `sync_lauf`. Der Task nutzt eine **eigene Session** (die Request-Session ist nach der Antwort geschlossen).
- `GET /admin/sync-status` (nur `schulleitung`): `{laeuft: bool, aktueller_lauf: {id, gestartet_am, phase, ausgeloest_von} | null, letzter_lauf: {id, status, gestartet_am, beendet_am, ausgeloest_von, fehler_kurz} | null}`.
- Start des Backends: Aufräumen verwaister Läufe (siehe oben), im Lifespan neben `warn_if_migrations_pending`.
- Zeitgesteuerter Sync trägt `ausgeloest_von = "zeitplan"` ein, ohne seine sonstige Logik (Retry-Loop) zu ändern.
- Tests: 202 + Hintergrundlauf (Task läuft nach der Antwort weiter), 409 bei laufendem Sync, Fehler wird als `fehler` mit gekürzter, bereinigter Meldung gespeichert (kein Token/Name), Phasenübergänge, Aufräumen beim Start und die 6-Stunden-Regel, Rollen/Scope (nur Schulleitung), Verlauf wird gekürzt, `run_sync_once` bleibt für den Scheduler kompatibel.

## Phase 2 – Frontend

- `useTriggerSyncNow` bekommt das neue Ergebnis (`gestartet`), invalidiert danach die Statusabfrage.
- Neuer Hook `useSyncStatus` (Abfrage `admin/sync-status`, `refetchInterval` 3 s solange `laeuft`, sonst keine Wiederholung; beim Laden der Seite läuft die Abfrage einmal, so zeigt auch ein nach Seitenwechsel noch laufender Sync seinen Status).
- `SyncSettings.tsx`: Button deaktiviert, solange `laeuft`; Anzeige „Sync läuft seit hh:mm (Phase: …)"; nach Ende „Letzter Sync: ok/Fehler (hh:mm, manuell/Zeitplan)" mit `fehler_kurz` bei Fehler und Hinweis auf das Server-Log. 409 beim Start zeigt „Ein Sync läuft bereits".
- Tests: Start, laufender Zustand (Polling), Ende ok/Fehler, 409, Seite lädt bei laufendem Sync, kein Polling im Ruhezustand.

## Phase 3 – Doku und Roadmap

- `docs/ADMIN.md` (Abschnitt manueller Sync): neues Verhalten (läuft im Hintergrund, Status in der Oberfläche, bei Neustart des Backends gilt ein laufender Sync als abgebrochen), Hinweis, dass die Proxy-Timeouts nicht mehr relevant sind; `docs/SL.md` falls der Button dort beschrieben ist; `TECH-SPEC.md` (API-Vertrag `sync-now`, `sync-status`, Tabelle `sync_lauf`).
- `ROADMAP.md`: Technical-Debt-Eintrag zum Proxy-Timeout schließen und den Plan eintragen.
- Der Kommentar zum 120-s-Timeout im WordPress-Plugin (`wordpress-plugin/absenzdash/includes/class-proxy.php`) wird angepasst (Hinweis, dass `sync-now` jetzt sofort antwortet); der Wert bleibt, andere Aufrufe (Import, PDF-Export) profitieren davon.

## Risiken und Nicht-Ziele

- **Ein Prozess:** Lock und Hintergrund-Task sind prozesslokal. Würde das Backend später mit mehreren uvicorn-Workern laufen, bräuchte es zusätzlich eine DB-seitige Sperre (z. B. Advisory Lock). Hier nicht enthalten, aber in der Doku vermerkt.
- Ein Neustart während des Syncs bricht ihn ab; der Verlauf zeigt ihn nach dem Neustart als `abgebrochen`, der nächste Cron-Lauf holt auf.
- Kein Abbruch-Button, keine feingranulare Fortschrittsanzeige, keine Benachrichtigung bei Fertigstellung (E-Mail o. ä.).
