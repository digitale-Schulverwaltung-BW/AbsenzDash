from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path
from string import Template

from pydantic import EmailStr, TypeAdapter

from app.core.config import Settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_email_adapter = TypeAdapter(EmailStr)


def _validate_recipient_addresses(to_addresses: list[str]) -> None:
    """Wirft ValueError, falls eine Empfaengeradresse kein gueltiges E-Mail-Format hat."""
    for adresse in to_addresses:
        try:
            _email_adapter.validate_python(adresse)
        except Exception as exc:
            raise ValueError(f"Ungueltige Empfaengeradresse: {adresse!r}") from exc


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
    _validate_recipient_addresses(to_addresses)
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

    # CR/LF aus eingesetzten Werten entfernen: verhindert Header-/Content-Manipulation
    # ueber z.B. Schuelernamen oder Klassenbezeichnungen mit eingebetteten Zeilenumbruechen.
    bereinigte_werte = {schluessel: wert.replace("\r", "").replace("\n", "") for schluessel, wert in werte.items()}

    subject = Template(subject_template).substitute(**bereinigte_werte)
    body = Template(body_template).substitute(**bereinigte_werte)
    return subject, body
