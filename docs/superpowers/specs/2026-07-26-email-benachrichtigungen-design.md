# E-Mail-Benachrichtigungen — Design

Deckt Roadmap-Punkt "Backend: E-Mail-Benachrichtigungen" ab (SPECS.md §5.1/§6). Baut auf Plan 3 (Eskalations-Engine) auf: dort wird bereits pro neu erreichter Schwellwertstufe ein `Benachrichtigung`-Log-Eintrag geschrieben (`app/services/eskalations_pruefung.py::_schreibe_benachrichtigung`), inkl. Empfänger-Auflösung nach Rolle (Klassenlehrkraft/Bereichsleiter/Schulleitung) und den Sonderfällen `kein_empfaenger`/`initial_import`. Der Status `"gesendet"` wird dort aber aktuell rein aspirational gesetzt — es wird noch keine echte E-Mail verschickt. Dieses Design schließt genau diese Lücke.

## 1. Ausgangslage

- Sync-Job läuft über `AsyncIOScheduler` im selben Event-Loop wie die FastAPI-App (`app/core/scheduler.py`) — ein blockierender SMTP-Call würde die App einfrieren.
- `Benachrichtigung.status` ist `String(20)` ohne Check-Constraint — ein neuer Wert (`"fehler"`) braucht keine Migration.
- `docker-compose.yml` mountet bereits das komplette `backend/`-Verzeichnis in den Container (`- .:/app`) — Dateien im Repo-Checkout sind ohne Rebuild sofort im Container sichtbar.
- Keine neue Python-Dependency für SMTP oder Templating (Projekt-Konvention: möglichst wenige Abhängigkeiten, siehe `requirements.txt`).

## 2. Konfiguration (`app/core/config.py`, `.env.example`)

Neue Pflicht-Felder (kein Default, analog zu `webuntis_server` etc.):

- `smtp_host: str`
- `smtp_from_address: str`
- `dashboard_base_url: str`

Neue optionale Felder:

- `smtp_port: int = 587`
- `smtp_user: str | None = None`
- `smtp_password: str | None = None`
- `smtp_use_starttls: bool = True`

`smtp_user`/`smtp_password` werden nur genutzt, wenn `smtp_user` gesetzt ist (kein Login-Versuch sonst) — deckt sowohl ein internes, unauthentifiziertes Relay (`SMTP_USE_STARTTLS=false`, `SMTP_USER` leer) als auch STARTTLS+Auth auf Port 587 (Default-Werte) ab, ohne Codeänderung.

Env-Var-Namen (Großschreibung, `.env.example` ergänzen):
`SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_ADDRESS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_STARTTLS`, `DASHBOARD_BASE_URL`.

## 3. Mailer (`app/services/mailer.py`, neu)

```
async def send_email(settings: Settings, to_addresses: list[str], subject: str, body: str) -> None
```

- Baut eine `EmailMessage` (stdlib `email.message`), `To` = alle übergebenen Adressen, `From` = `settings.smtp_from_address`.
- Der eigentliche Versand (`smtplib.SMTP(...)`, optional `.starttls()`, optional `.login()`, `.send_message()`) läuft in einer synchronen Hilfsfunktion, die über `asyncio.to_thread(...)` aufgerufen wird — blockiert den Event-Loop nicht.
- Wirft die Exception bei Fehlern unverändert weiter (kein Schlucken) — Fehlerbehandlung/Logging passiert eine Ebene höher, dort wo der fachliche Kontext (Schüler, Regel, Stufe) bekannt ist.

## 4. Mail-Template (Templating für Admin-Anpassung)

- **Ordner:** `backend/app/templates/`
- **`email_benachrichtigung.txt.default`** — committed, Default-Inhalt.
- **`email_benachrichtigung.txt`** — in `.gitignore` aufgenommen, optionales Override. Existiert diese Datei, wird sie verwendet, sonst die `.default`-Datei. Kein Caching — jede Sync-Runde liest die Datei neu ein, Änderungen wirken ohne Neustart (gleiches Prinzip wie `einstellung.sync_interval_cron`).
- **Dateiformat:** erste Zeile = Betreff-Template, danach eine Leerzeile, danach Body-Template (restlicher Dateiinhalt).
- **Templating-Engine:** stdlib `string.Template` (`$platzhalter`-Syntax) — keine neue Dependency, kein Code-Ausführungsrisiko (im Gegensatz zu Jinja2) bei einem vom Admin frei editierbaren Text.
- **Platzhalter:** `$schueler_vorname`, `$schueler_nachname`, `$klasse` (Klassenname, oder `"–"` falls `schueler.klasse_id` nicht gesetzt ist — bewusst kein leerer String, damit z.B. `"($klasse)"` im Template nicht zu leeren Klammern `()` wird), `$regel_typ` (Klartext-Label "Fehlzeiten"/"Klassenbucheinträge"), `$stufe_nr`, `$zaehlerstand`, `$einheit` (z.B. "Fehltage", "Fehlstunden", oder Klartext-Fallback für Klassenbuch-Regeln ohne `einheit`-Wert), `$dashboard_link` (zusammengesetzt als `f"{settings.dashboard_base_url}/students/{schueler.id}"`, passend zum in TECH-SPEC.md §3 geplanten `GET /students/{id}`-Endpunkt).

`app/services/mailer.py` bekommt dafür eine zweite Funktion:

```
def render_template(templates_dir: Path, **werte: str) -> tuple[str, str]  # -> (subject, body)
```

Lädt Override-Datei falls vorhanden sonst `.default`, splittet an der ersten Leerzeile in Betreff/Body, füllt beide über `string.Template(...).substitute(**werte)`.

Default-Template-Inhalt (Betreff-Zeile + Body):

```
AbsenzDash: Stufe $stufe_nr erreicht – $schueler_vorname $schueler_nachname

Schüler/in: $schueler_vorname $schueler_nachname ($klasse)
Regel: $regel_typ
Erreichte Stufe: $stufe_nr
Aktueller Zählerstand: $zaehlerstand $einheit

Details im Dashboard: $dashboard_link

Diese E-Mail wurde automatisch von AbsenzDash versendet.
```

## 5. Integration in `eskalations_pruefung.py`

`pruefe_schwellwerte(db, heute, einstellung)` bekommt einen zusätzlichen Parameter `settings: Settings`, durchgereicht bis zu `_schreibe_benachrichtigung`. `sync_orchestrator._run_once` übergibt das bereits importierte `settings`-Objekt.

`_schreibe_benachrichtigung` (bzw. eine neue Hilfsfunktion `_versende_email`, die von dort aufgerufen wird):

1. Empfänger wie bisher über `_resolve_empfaenger` auflösen (unverändert, inkl. Rollen-Logik).
2. Ist `einstellung.initialer_import_abgeschlossen == False` → `status = "initial_import"`, kein Versandversuch (unverändert).
3. Sind keine Empfänger aufgelöst → `status = "kein_empfaenger"`, kein Versandversuch (unverändert).
4. Sonst: Empfänger nach `nutzer_id` deduplizieren (ein Nutzer mit mehreren Rollen bekommt nur eine Mail — siehe TECH-SPEC.md-Hinweis zur `benachrichtigung.empfaenger`-Spalte), `Nutzer.email` für die eindeutigen IDs nachladen, Klassenname nachladen (falls `schueler.klasse_id` gesetzt), Betreff/Body über `render_template` erzeugen, `send_email(...)` aufrufen (**eine** Mail, alle Empfänger im `To`-Feld).
   - Erfolg → `status = "gesendet"`.
   - Exception → mit vollem Kontext geloggt (`logger.exception`, Schüler-/Regel-/Stufe-ID), `status = "fehler"` (**neuer** Statuswert).

`render_template` selbst ist ebenfalls gegen Fehler abgesichert: ein fehlerhaftes Admin-Template-Override (fehlende Leerzeile, unbekannter `$platzhalter`, nicht lesbare Datei) wird dort separat abgefangen (`ValueError`/`KeyError`/`OSError`) und führt ebenfalls nur zu `status = "fehler"` statt den gesamten Sync-Lauf abzubrechen.

**Kein automatischer Retry für `status = "fehler"`.** Durch die "Neuberechnung statt Inkrement"-Architektur (Zählerstand wird bei jedem Lauf aus den Rohdaten neu berechnet) würde ein späterer, an sich erfolgreicher Sync-Lauf `neue_stufe_nr > alte_stufe_nr` nicht erneut feststellen, wenn die Stufe unverändert bleibt — ein einmal fehlgeschlagener Versand wird also nicht von selbst nachgeholt. Das ist eine bewusst in Kauf genommene Einschränkung (siehe Diskussion), um den Scope klein zu halten; sichtbar für den Admin über `status = "fehler"` im Benachrichtigungs-Log. Als potenzieller Folge-Punkt dokumentieren (analog `docs/superpowers/plans/*-followups.md`-Pattern aus Plan 3), falls sich das im Betrieb als Problem erweist.

## 6. Tests

- `mailer.py`: eigene Testdatei. `send_email` mit gemocktem `smtplib.SMTP` (Context-Manager-Mock, wie die bestehenden WebUntis-Client-Mocks) — prüft `starttls()`/`login()`-Aufruf abhängig von Settings, `send_message()`-Inhalt. `render_template` mit Test-Override-Datei in `tmp_path` und ohne (Fallback auf `.default`).
- `eskalations_pruefung.py`: bestehende Tests unverändert (Signaturänderung von `pruefe_schwellwerte`/`_schreibe_benachrichtigung` nachziehen, `settings`-Fixture ergänzen). Neue Tests: `send_email` gemockt (`AsyncMock`) →
  - Erfolg → `Benachrichtigung.status == "gesendet"`.
  - `send_email` wirft Exception → `status == "fehler"`, kein Re-raise (Sync-Lauf darf für andere Schüler weiterlaufen).
  - Ein Nutzer mit zwei Rollen (z.B. Klassenlehrkraft *und* Bereichsleiter derselben Klasse) → `send_email` wird mit nur einer (deduplizierten) Adresse aufgerufen.
  - `kein_empfaenger`/`initial_import` → `send_email` wird **nicht** aufgerufen (Regressionsschutz für bestehendes Verhalten).

## 7. Dokumentation

- `.env.example`: neue Variablen ergänzen.
- `docs/backend-setup.md`: neuer Abschnitt "E-Mail-Benachrichtigungen" — Config-Variablen, Template-Override-Pfad (`backend/app/templates/email_benachrichtigung.txt`, nicht versioniert), Hinweis auf fehlenden Auto-Retry bei `status = "fehler"`. "Noch nicht abgedeckt"-Zeile entsprechend kürzen.
- `TECH-SPEC.md`: `SMTP_*`/`DASHBOARD_BASE_URL` in der docker-compose-Env-Var-Liste (aktuell nur `SMTP_*` als Platzhalter erwähnt) konkretisieren; `benachrichtigung.status`-Beschreibung um `"fehler"` ergänzen.
- `ROADMAP.md`: Punkt 1 ("Backend: E-Mail-Benachrichtigungen") nach Abschluss von "Geplant" nach "Abgeschlossen" verschieben, mit Verweis auf Plan-Dokument und den Hinweis zum fehlenden Auto-Retry als "bewusst nicht enthalten".

## 8. Bewusst nicht enthalten (YAGNI)

- Kein Retry-Mechanismus für fehlgeschlagene Sends (siehe Abschnitt 5).
- Kein HTML-Mailformat (reiner Text).
- Kein Digest/Batching mehrerer Benachrichtigungen in eine Mail — weiterhin eine Mail pro Event, wie im bestehenden Log-Modell (`Benachrichtigung` pro Stufe) angelegt.
- Keine Mehrsprachigkeit/Internationalisierung des Templates.
- Kein Volume-Mount-Änderung in `docker-compose.yml` nötig, da das komplette `backend/`-Verzeichnis bereits gemountet ist.
