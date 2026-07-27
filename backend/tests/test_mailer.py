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
