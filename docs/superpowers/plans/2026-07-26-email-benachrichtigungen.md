# E-Mail-Benachrichtigungen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der bestehende `Benachrichtigung`-Log-Eintrag in `eskalations_pruefung.py` (Plan 3) verschickt beim Status `"gesendet"` jetzt eine echte E-Mail über SMTP, statt den Status nur aspirational zu setzen. Mailinhalt ist über eine gitignorete Override-Datei admin-anpassbar.

**Architecture:** Neues, eigenständiges Modul `app/services/mailer.py` kapselt SMTP-Versand (stdlib `smtplib` in `asyncio.to_thread`, kein blockierender Call im Event-Loop) und ein einfaches Text-Templating (stdlib `string.Template`, `$platzhalter`-Syntax). `eskalations_pruefung.py` ruft dieses Modul in `_schreibe_benachrichtigung` auf, sobald Empfänger aufgelöst wurden: Erfolg → `status="gesendet"`, Exception beim Versand → `status="fehler"` (neuer Wert, keine Migration nötig, `status` ist `String(20)` ohne Check-Constraint). Kein Retry-Mechanismus für `"fehler"` (siehe Design-Dokument Abschnitt 5) — bewusste Einschränkung, dokumentiert statt automatisiert.

**Tech Stack:** Python 3.11, stdlib `smtplib`/`email.message`/`string.Template` (keine neue Dependency), FastAPI, SQLAlchemy 2.0 async, pytest + pytest-asyncio gegen echte Postgres-Testdatenbank (SMTP-Grenze in Tests gemockt, kein echter Mailserver nötig).

**Design-Dokument:** [docs/superpowers/specs/2026-07-26-email-benachrichtigungen-design.md](../specs/2026-07-26-email-benachrichtigungen-design.md) — enthält die vollständige Herleitung. Dieser Plan übersetzt das Design 1:1 in Code; bei Widersprüchen gilt das Design-Dokument.

## Global Constraints

- Commit-Messages auf Englisch (User-Konvention).
- Log-Meldungen, Docstrings und Kommentare in diesem Projekt sind Deutsch — beibehalten.
- Keine SQLAlchemy `relationship()`-Deklarationen — explizite FK-Spalten + manuelle `select()`-Joins (Projekt-Konvention, siehe `eskalations_pruefung.py`).
- Keine neue Python-Dependency (`requirements.txt` bleibt unverändert) — SMTP und Templating laufen komplett über die Standardbibliothek.
- Kein Retry-Mechanismus für fehlgeschlagene E-Mail-Sends (bewusste Design-Entscheidung, siehe Design-Dokument Abschnitt 5) — nicht nachträglich ergänzen, ohne das mit dem User abzustimmen.
- `docker exec absenzdash-test-runner python -m pytest ...` für alle Testläufe (persistenter, bereits an die Test-Postgres angebundener Container, Workdir `/app` = `backend/`-Verzeichnis des jeweiligen Worktrees, siehe Plan 3-Konvention). Falls dieser Container im Arbeits-Worktree nicht existiert: `docker compose -f backend/docker-compose.yml run --rm backend pytest` als Fallback (siehe `docs/backend-setup.md`).
- Keine DB-Migration in diesem Plan nötig (keine neuen Spalten/Tabellen — `Benachrichtigung.status` ist bereits ein unconstrainter `String(20)`).

---

### Task 1: SMTP-Config, Mailer-Modul (Versand + Templating)

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `.gitignore` (Repo-Root)
- Create: `backend/app/templates/email_benachrichtigung.txt.default`
- Create: `backend/app/services/mailer.py`
- Create: `backend/tests/test_mailer.py`

**Interfaces:**
- Produces: `Settings.smtp_host: str`, `.smtp_port: int`, `.smtp_from_address: str`, `.smtp_user: str | None`, `.smtp_password: str | None`, `.smtp_use_starttls: bool`, `.dashboard_base_url: str` (in `app.core.config`). `app.services.mailer.TEMPLATES_DIR: Path`. `async def send_email(settings: Settings, to_addresses: list[str], subject: str, body: str) -> None`. `def render_template(templates_dir: Path, **werte: str) -> tuple[str, str]` (gibt `(subject, body)` zurück). Task 2 importiert und nutzt alle vier.

- [ ] **Step 1: Neue Pflicht-/Optional-Felder in `Settings` ergänzen**

In `backend/app/core/config.py`, ersetze den kompletten Inhalt durch:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    wordpress_proxy_secret: str
    webuntis_server: str
    webuntis_school: str
    webuntis_username: str
    webuntis_password: str
    asv_csv_path: str
    asv_csv_column_externe_id: str = "idnumber"
    asv_csv_column_vorname: str = "firstname"
    asv_csv_column_nachname: str = "lastname"
    asv_csv_column_klasse: str = "Klasse"
    asv_csv_column_eintrittsdatum: str = "Eintrittsdatum"
    asv_csv_column_austrittsdatum: str = "Austrittsdatum"
    webuntis_sync_retry_delay_minutes: int = 30
    webuntis_sync_retry_max_attempts: int = 4
    smtp_host: str
    smtp_from_address: str
    dashboard_base_url: str
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_starttls: bool = True


settings = Settings()
```

- [ ] **Step 2: `.env.example` um die neuen Variablen ergänzen**

An `backend/.env.example` anhängen:

```
SMTP_HOST=changeme
SMTP_PORT=587
SMTP_FROM_ADDRESS=absenzdash@changeme.de
SMTP_USER=
SMTP_PASSWORD=
SMTP_USE_STARTTLS=true
DASHBOARD_BASE_URL=http://localhost:3000
```

- [ ] **Step 3: Lokale `backend/.env` um Test-Dummy-Werte ergänzen**

Die neuen Felder sind Pflichtfelder ohne Default — `Settings()` (Modul-Level-Instanziierung in `config.py`) schlägt sonst beim Import fehl und reißt die komplette Test-Suite mit. Lokale `backend/.env` (gitignored, nicht committen) ergänzen:

```bash
cat >> backend/.env <<'EOF'
SMTP_HOST=localhost
SMTP_PORT=25
SMTP_FROM_ADDRESS=absenzdash@localhost.test
SMTP_USER=
SMTP_PASSWORD=
SMTP_USE_STARTTLS=false
DASHBOARD_BASE_URL=http://localhost:3000
EOF
```

Falls der Test-Runner-Container eine eigene, unabhängige `.env`/Env-Konfiguration verwendet (statt der bind-gemounteten `backend/.env`), dieselben Variablen dort ergänzen, bevor Tests laufen.

- [ ] **Step 4: Default-Mail-Template anlegen**

`backend/app/templates/email_benachrichtigung.txt.default`:

```
AbsenzDash: Stufe $stufe_nr erreicht – $schueler_vorname $schueler_nachname

Schüler/in: $schueler_vorname $schueler_nachname ($klasse)
Regel: $regel_typ
Erreichte Stufe: $stufe_nr
Aktueller Zählerstand: $zaehlerstand $einheit

Details im Dashboard: $dashboard_link

Diese E-Mail wurde automatisch von AbsenzDash versendet.
```

- [ ] **Step 5: `.gitignore` um die Override-Template-Datei ergänzen**

In `.gitignore` (Repo-Root) anhängen:

```
backend/app/templates/email_benachrichtigung.txt
```

(Nur die Override-Datei ohne `.default`-Suffix ist gitignored — die `.default`-Datei aus Step 4 bleibt committed.)

- [ ] **Step 6: Failing Tests für `mailer.py` schreiben**

`backend/tests/test_mailer.py`:

```python
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services import mailer


@pytest.mark.asyncio
async def test_send_email_uses_starttls_and_login_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from_address", "absenzdash@example.test")
    monkeypatch.setattr(settings, "smtp_user", "user")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_use_starttls", True)

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False
    smtp_cls = MagicMock(return_value=smtp_instance)
    monkeypatch.setattr(mailer.smtplib, "SMTP", smtp_cls)

    await mailer.send_email(settings, ["a@b.de", "c@d.de"], "Betreff", "Text")

    smtp_cls.assert_called_once_with("smtp.example.test", 587, timeout=30)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("user", "secret")
    sent_message = smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == "a@b.de, c@d.de"
    assert sent_message["Subject"] == "Betreff"
    assert sent_message.get_content().strip() == "Text"


@pytest.mark.asyncio
async def test_send_email_skips_starttls_and_login_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "relay.internal")
    monkeypatch.setattr(settings, "smtp_port", 25)
    monkeypatch.setattr(settings, "smtp_from_address", "absenzdash@example.test")
    monkeypatch.setattr(settings, "smtp_user", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    monkeypatch.setattr(settings, "smtp_use_starttls", False)

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False
    smtp_cls = MagicMock(return_value=smtp_instance)
    monkeypatch.setattr(mailer.smtplib, "SMTP", smtp_cls)

    await mailer.send_email(settings, ["a@b.de"], "Betreff", "Text")

    smtp_instance.starttls.assert_not_called()
    smtp_instance.login.assert_not_called()
    smtp_instance.send_message.assert_called_once()


def test_render_template_uses_default_when_no_override(tmp_path):
    (tmp_path / "email_benachrichtigung.txt.default").write_text(
        "AbsenzDash: Stufe $stufe_nr erreicht\n\nHallo $schueler_vorname, Klasse $klasse.",
        encoding="utf-8",
    )

    subject, body = mailer.render_template(tmp_path, stufe_nr="1", schueler_vorname="Max", klasse="10a")

    assert subject == "AbsenzDash: Stufe 1 erreicht"
    assert body == "Hallo Max, Klasse 10a."


def test_render_template_prefers_override_when_present(tmp_path):
    (tmp_path / "email_benachrichtigung.txt.default").write_text(
        "Default-Betreff\n\nDefault-Text $schueler_vorname", encoding="utf-8"
    )
    (tmp_path / "email_benachrichtigung.txt").write_text(
        "Custom-Betreff\n\nCustom-Text $schueler_vorname", encoding="utf-8"
    )

    subject, body = mailer.render_template(tmp_path, schueler_vorname="Max")

    assert subject == "Custom-Betreff"
    assert body == "Custom-Text Max"
```

- [ ] **Step 7: Tests laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_mailer.py -v
```

Erwartet: FAIL — `ModuleNotFoundError: No module named 'app.services.mailer'`.

- [ ] **Step 8: `mailer.py` implementieren**

`backend/app/services/mailer.py`:

```python
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from string import Template

from app.core.config import Settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _send_sync(settings: Settings, to_addresses: list[str], subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = ", ".join(to_addresses)
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(message)


async def send_email(settings: Settings, to_addresses: list[str], subject: str, body: str) -> None:
    """Blockierender SMTP-Versand in Thread-Pool-Executor (Sync-Job laeuft im selben Event-Loop wie die API)."""
    await asyncio.to_thread(_send_sync, settings, to_addresses, subject, body)


def render_template(templates_dir: Path, **werte: str) -> tuple[str, str]:
    """Laedt email_benachrichtigung.txt (Admin-Override) falls vorhanden, sonst die .default-Datei.

    Erste Zeile der Datei ist das Betreff-Template, nach einer Leerzeile folgt das Body-Template.
    """
    override_path = templates_dir / "email_benachrichtigung.txt"
    default_path = templates_dir / "email_benachrichtigung.txt.default"
    path = override_path if override_path.exists() else default_path

    content = path.read_text(encoding="utf-8")
    subject_template, body_template = content.split("\n\n", 1)

    subject = Template(subject_template).substitute(**werte)
    body = Template(body_template).substitute(**werte)
    return subject, body
```

- [ ] **Step 9: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_mailer.py -v
```

Erwartet: PASS (4/4).

- [ ] **Step 10: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS, keine Regressionen (Config-Änderung darf keine anderen Tests brechen, da alle neuen Felder entweder einen Default haben oder in Step 3 lokal gesetzt wurden).

- [ ] **Step 11: Commit**

```bash
git add backend/app/core/config.py backend/.env.example backend/app/templates/email_benachrichtigung.txt.default \
  backend/app/services/mailer.py backend/tests/test_mailer.py .gitignore
git commit -m "feat: add SMTP mailer module with admin-overridable text templating"
```

---

### Task 2: E-Mail-Versand in die Eskalations-Prüfung integrieren

**Files:**
- Modify: `backend/app/services/eskalations_pruefung.py`
- Modify: `backend/app/services/sync_orchestrator.py`
- Modify: `backend/tests/test_eskalations_pruefung.py`

**Interfaces:**
- Consumes: `send_email`, `render_template`, `TEMPLATES_DIR` aus `app.services.mailer` (Task 1).
- Produces: `pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung, settings: Settings) -> None` — **Signaturänderung** (neuer `settings`-Parameter). `Benachrichtigung.status` kann jetzt zusätzlich den Wert `"fehler"` annehmen.

- [ ] **Step 1: Failing Tests für den neuen Versand-Pfad schreiben**

In `backend/tests/test_eskalations_pruefung.py`, Imports am Dateianfang ergänzen (nach der bestehenden `from app.services.eskalations_pruefung import pruefe_schwellwerte`-Zeile):

```python
from unittest.mock import AsyncMock

from app.core.config import settings
from app.services import eskalations_pruefung
```

Direkt danach, vor der ersten `async def _make_schueler(...)`-Funktion, folgende autouse-Fixture einfügen — sie mockt `send_email` standardmäßig als Erfolg, damit alle bestehenden Tests (die den Versand nicht explizit prüfen) unverändert laufen, ohne echte SMTP-Calls zu machen:

```python
@pytest.fixture(autouse=True)
def mock_send_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(eskalations_pruefung, "send_email", mock)
    return mock
```

Alle bestehenden Aufrufe von `pruefe_schwellwerte(db_session, <datum>, einstellung)` in dieser Datei bekommen den neuen `settings`-Parameter. Führe dafür aus:

```bash
sed -i '' 's/, einstellung)$/, einstellung, settings)/' backend/tests/test_eskalations_pruefung.py
```

(Ersetzt alle 20 Vorkommen von `, einstellung)` am Zeilenende durch `, einstellung, settings)` — betrifft ausschließlich die `pruefe_schwellwerte(...)`-Aufrufe, keine anderen Stellen der Datei. Auf Linux ohne BSD-sed: `sed -i 's/, einstellung)$/, einstellung, settings)/' backend/tests/test_eskalations_pruefung.py`.)

Am Ende der Datei folgende neue Tests ergänzen:

```python
@pytest.mark.asyncio
async def test_pruefe_schwellwerte_status_fehler_when_send_email_raises(db_session, mock_send_email):
    mock_send_email.side_effect = OSError("Connection refused")
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()
    db_session.expunge_all()

    result = await db_session.execute(select(Benachrichtigung).where(Benachrichtigung.schueler_id == schueler_id))
    assert result.scalar_one().status == "fehler"


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_dedupes_recipient_addresses_for_send(db_session, mock_send_email):
    """Ein Nutzer, der fuer dieselbe Klasse sowohl Klassenlehrkraft als auch Bereichsleiter ist,
    darf beim tatsaechlichen Versand nur EINMAL im To-Feld auftauchen (Log-Eintrag behaelt beide Rollen)."""
    klasse = Klasse(webuntis_id=1, name="10a")
    bereich = Bereich(name="Kaufmaennischer Bereich")
    db_session.add_all([klasse, bereich])
    await db_session.flush()
    await db_session.execute(bereich_klasse.insert().values(bereich_id=bereich.id, klasse_id=klasse.id))
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await db_session.execute(nutzer_bereich.insert().values(nutzer_id=nutzer.id, bereich_id=bereich.id))

    regel = SchwellwertRegel(typ="fehlzeiten", geltungsbereich="schulweit")
    db_session.add(regel)
    await db_session.flush()
    db_session.add(
        SchwellwertStufe(
            regel_id=regel.id, stufe_nr=1, einheit="fehltage", schwellenwert=1, fehlzeiten_filter="alle",
            empfaenger_rollen=["klassenlehrkraft", "bereichsleiter"],
        )
    )
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_awaited_once()
    call_args = mock_send_email.await_args
    assert call_args.args[1] == ["a@b.de"]


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_renders_expected_mail_content(db_session, mock_send_email):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="Max", nachname="Muster", aktiv=True, klasse_id=klasse.id)
    nutzer = Nutzer(wp_user_id="u1", email="a@b.de", name="Lehrer", rolle="klassenlehrkraft", webuntis_teacher_id=1)
    db_session.add_all([schueler, nutzer])
    await db_session.flush()
    db_session.add(NutzerKlasse(nutzer_id=nutzer.id, klasse_id=klasse.id, quelle="webuntis_seed"))
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    schueler_id = schueler.id
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_awaited_once()
    call_args = mock_send_email.await_args
    subject, body = call_args.args[2], call_args.args[3]
    assert "Max Muster" in subject
    assert "10a" in body
    assert f"{settings.dashboard_base_url}/students/{schueler_id}" in body


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_kein_empfaenger_does_not_call_send_email(db_session, mock_send_email):
    klasse = Klasse(webuntis_id=1, name="10a")
    db_session.add(klasse)
    await db_session.flush()
    schueler = Schueler(externe_id="ext-1", vorname="A", nachname="B", aktiv=True, klasse_id=klasse.id)
    db_session.add(schueler)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=True, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_pruefe_schwellwerte_initial_import_does_not_call_send_email(db_session, mock_send_email):
    schueler = await _make_schueler(db_session)
    await _make_fehlzeiten_regel(db_session, schwellenwert=1)
    db_session.add(
        Fehlzeit(schueler_id=schueler.id, typ="tag", datum=datetime.date(2026, 1, 10), start_zeit=0, end_zeit=0)
    )
    await db_session.commit()

    einstellung = Einstellung(initialer_import_abgeschlossen=False, schuljahr_start_cache=datetime.date(2025, 9, 1))
    await pruefe_schwellwerte(db_session, datetime.date(2026, 1, 20), einstellung, settings)
    await db_session.commit()

    mock_send_email.assert_not_awaited()
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: FAIL — `TypeError: pruefe_schwellwerte() takes 3 positional arguments but 4 were given` (für alle bestehenden Tests, da die Produktionsfunktion den `settings`-Parameter noch nicht kennt) sowie `AttributeError`/`ImportError`-artige Fehler für die neuen Tests, da `eskalations_pruefung.send_email` noch nicht existiert.

- [ ] **Step 3: Versand-Integration in `eskalations_pruefung.py` implementieren**

Import-Block am Dateianfang ergänzen (nach dem bestehenden `from app.models.schwellwert_stufe import SchwellwertStufe`):

```python
from app.core.config import Settings
from app.services.mailer import TEMPLATES_DIR, render_template, send_email
```

Nach der bestehenden `_resolve_empfaenger`-Funktion und vor `_schreibe_benachrichtigung` folgenden Code einfügen:

```python
_TYP_LABEL = {"fehlzeiten": "Fehlzeiten", "klassenbuch": "Klassenbucheinträge"}


def _eindeutige_nutzer_ids(empfaenger: list[dict]) -> list[int]:
    """Ein Nutzer mit mehreren Rollen (z.B. Klassenlehrkraft UND Bereichsleiter) darf nur eine Mail bekommen."""
    return list(dict.fromkeys(e["nutzer_id"] for e in empfaenger))


async def _versende_email(
    db: AsyncSession,
    schueler: Schueler,
    regel: SchwellwertRegel,
    stufe: SchwellwertStufe,
    neuer_stand: int,
    empfaenger: list[dict],
    settings: Settings,
) -> str:
    nutzer_ids = _eindeutige_nutzer_ids(empfaenger)
    result = await db.execute(select(Nutzer.email).where(Nutzer.id.in_(nutzer_ids)))
    to_addresses = list(result.scalars().all())

    klasse_name = "-"
    if schueler.klasse_id is not None:
        klasse_result = await db.execute(select(Klasse.name).where(Klasse.id == schueler.klasse_id))
        gefundener_name = klasse_result.scalar_one_or_none()
        if gefundener_name is not None:
            klasse_name = gefundener_name

    einheit_label = stufe.einheit or _TYP_LABEL.get(regel.typ, regel.typ)
    dashboard_link = f"{settings.dashboard_base_url}/students/{schueler.id}"

    subject, body = render_template(
        TEMPLATES_DIR,
        schueler_vorname=schueler.vorname,
        schueler_nachname=schueler.nachname,
        klasse=klasse_name,
        regel_typ=_TYP_LABEL.get(regel.typ, regel.typ),
        stufe_nr=str(stufe.stufe_nr),
        zaehlerstand=str(neuer_stand),
        einheit=einheit_label,
        dashboard_link=dashboard_link,
    )

    try:
        await send_email(settings, to_addresses, subject, body)
    except Exception:
        logger.exception(
            "E-Mail-Versand fehlgeschlagen fuer Schueler %d, Regel %d, Stufe %d",
            schueler.id, regel.id, stufe.stufe_nr,
        )
        return "fehler"
    return "gesendet"
```

Danach die bestehende `_schreibe_benachrichtigung`-Funktion komplett ersetzen durch:

```python
async def _schreibe_benachrichtigung(
    db: AsyncSession,
    schueler: Schueler,
    regel: SchwellwertRegel,
    stufe_nr: int,
    neuer_stand: int,
    einstellung: Einstellung,
    settings: Settings,
) -> None:
    stufe = (
        await db.execute(
            select(SchwellwertStufe).where(SchwellwertStufe.regel_id == regel.id, SchwellwertStufe.stufe_nr == stufe_nr)
        )
    ).scalar_one()

    if not einstellung.initialer_import_abgeschlossen:
        status = "initial_import"
        empfaenger: list[dict] = []
    else:
        empfaenger = await _resolve_empfaenger(db, schueler.klasse_id, stufe.empfaenger_rollen)
        if not empfaenger:
            status = "kein_empfaenger"
        else:
            status = await _versende_email(db, schueler, regel, stufe, neuer_stand, empfaenger, settings)

    db.add(
        Benachrichtigung(
            schueler_id=schueler.id,
            regel_id=regel.id,
            stufe_nr=stufe_nr,
            gesendet_am=datetime.now(timezone.utc),
            empfaenger=empfaenger,
            status=status,
        )
    )
```

Zuletzt `pruefe_schwellwerte` anpassen — Signatur und den Aufruf von `_schreibe_benachrichtigung` am Ende der Funktion:

```python
async def pruefe_schwellwerte(db: AsyncSession, heute: date, einstellung: Einstellung, settings: Settings) -> None:
```

(nur die Signaturzeile ersetzen, Funktionskörper bis zum letzten `if`-Block unverändert lassen) und den letzten Block der Funktion:

```python
            if neue_stufe_nr is not None and (alte_stufe_nr is None or neue_stufe_nr > alte_stufe_nr):
                await _schreibe_benachrichtigung(db, schueler, regel, neue_stufe_nr, neuer_stand, einstellung, settings)
```

- [ ] **Step 4: `sync_orchestrator.py` anpassen**

In `backend/app/services/sync_orchestrator.py`, die Zeile

```python
        await pruefe_schwellwerte(db, heute, einstellung)
```

ersetzen durch:

```python
        await pruefe_schwellwerte(db, heute, einstellung, settings)
```

(`settings` ist dort bereits importiert, siehe `from app.core.config import settings` am Dateianfang — keine weitere Änderung nötig.)

- [ ] **Step 5: Tests laufen lassen, Erfolg bestätigen**

```bash
docker exec absenzdash-test-runner python -m pytest -q tests/test_eskalations_pruefung.py -v
```

Erwartet: PASS (alle bestehenden + 5 neuen Tests).

- [ ] **Step 6: Volle Test-Suite laufen lassen**

```bash
docker exec absenzdash-test-runner python -m pytest -q
```

Erwartet: PASS, keine Regressionen (insbesondere `tests/test_sync_orchestrator.py` — dort wird `pruefe_schwellwerte` in den meisten Tests ohnehin gemockt; der eine reale Aufruf in `test_run_full_sync_end_to_end_triggers_benachrichtigung` endet in `status="kein_empfaenger"`, ruft `send_email` also nicht auf und bleibt unverändert grün).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/eskalations_pruefung.py backend/app/services/sync_orchestrator.py \
  backend/tests/test_eskalations_pruefung.py
git commit -m "feat: send actual emails for newly reached escalation stages"
```

---

### Task 3: Dokumentation

**Files:**
- Modify: `docs/backend-setup.md`
- Modify: `TECH-SPEC.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: nichts Neues (reine Doku-Aktualisierung nach Abschluss von Task 1+2).

- [ ] **Step 1: `docs/backend-setup.md` ergänzen**

Nach dem bestehenden Abschnitt `## WebUntis-Sync (ab Plan 2)` einen neuen Abschnitt einfügen:

```markdown
## E-Mail-Benachrichtigungen (ab Plan 4)

- **Config:** `SMTP_HOST`, `SMTP_FROM_ADDRESS`, `DASHBOARD_BASE_URL` sind Pflichtangaben (kein Start ohne sie, siehe `.env.example`). `SMTP_PORT` (Default 587), `SMTP_USER`/`SMTP_PASSWORD` (nur genutzt wenn `SMTP_USER` gesetzt ist) und `SMTP_USE_STARTTLS` (Default `true`) sind optional — für ein internes, unauthentifiziertes Relay `SMTP_USE_STARTTLS=false` und `SMTP_USER` leer lassen.
- **Mailinhalt anpassen:** `backend/app/templates/email_benachrichtigung.txt.default` ist die versionierte Default-Vorlage. Für schulspezifische Anpassungen `backend/app/templates/email_benachrichtigung.txt` anlegen (nicht versioniert, siehe `.gitignore`) — existiert diese Datei, wird sie statt der Default-Vorlage verwendet, ohne Neustart des Backends. Format: erste Zeile = Betreff, danach eine Leerzeile, danach der Mailtext. Verfügbare Platzhalter: `$schueler_vorname`, `$schueler_nachname`, `$klasse`, `$regel_typ`, `$stufe_nr`, `$zaehlerstand`, `$einheit`, `$dashboard_link`.
- **Bekannte Einschränkung:** Schlägt der SMTP-Versand fehl (z.B. Mailserver kurz nicht erreichbar), wird das im Benachrichtigungs-Log als `status="fehler"` vermerkt, aber **nicht automatisch erneut versucht** — durch die "Neuberechnung statt Inkrement"-Architektur des Sync-Jobs (siehe TECH-SPEC.md) würde ein unveränderter Zählerstand im nächsten Lauf ohnehin nicht erneut als "neu erreicht" erkannt. Betroffene Fälle sind im Benachrichtigungs-Log sichtbar und müssen bei Bedarf manuell nachverfolgt werden.
```

Danach den bestehenden Satz

```
- **Noch nicht abgedeckt:** manueller "Sync jetzt"-Endpunkt, Eskalations-Engine/Benachrichtigungen (beides spätere Pläne).
```

ersetzen durch:

```
- **Noch nicht abgedeckt:** manueller "Sync jetzt"-Endpunkt (späterer Plan).
```

- [ ] **Step 2: `TECH-SPEC.md` aktualisieren**

Grep-Treffer prüfen (`grep -n "SMTP_\*" TECH-SPEC.md`) und die Env-Var-Auflistung im docker-compose-Abschnitt (Zeile mit `SMTP_*`) ersetzen durch die konkrete Liste: `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_ADDRESS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_STARTTLS`, `DASHBOARD_BASE_URL`.

In der Schema-Tabelle die Zeile zu `benachrichtigung.status` (`"gesendet"`/`"kein_empfaenger"`/`"initial_import"`) um `"fehler"` ergänzen: `status` (`gesendet`/`kein_empfaenger`/`initial_import`/`fehler`).

- [ ] **Step 3: `ROADMAP.md` aktualisieren**

Punkt 1 aus der `## Geplant`-Liste entfernen und als neue Zeile in die `## Abgeschlossen`-Tabelle einfügen (nach der Plan-3-Zeile):

```markdown
| **Plan 4** — [E-Mail-Benachrichtigungen](docs/superpowers/plans/2026-07-26-email-benachrichtigungen.md) | SMTP-Versand bei neu erreichter Eskalationsstufe (`app/services/mailer.py`), admin-anpassbares Text-Template (gitignorete Override-Datei), neuer `benachrichtigung.status`-Wert `"fehler"` bei Versandfehlern | Automatischer Retry bei fehlgeschlagenem Versand (bewusst, siehe Design-Dokument) |
```

Die übrigen Punkte der `## Geplant`-Liste um eins nach oben nummerieren (aus 2/3/4/5 wird 1/2/3/4).

- [ ] **Step 4: Commit**

```bash
git add docs/backend-setup.md TECH-SPEC.md ROADMAP.md
git commit -m "docs: document email notification config, template override, and update roadmap"
```
