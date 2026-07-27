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
