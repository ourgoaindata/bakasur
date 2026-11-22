"""Send a plain-text email over SMTP; a no-op unless email is enabled and has recipients."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from bakasur.core.config import CoreSettings


class EmailSender:
    def __init__(self, cfg: CoreSettings) -> None:
        self.cfg = cfg

    def send(self, subject: str, body: str) -> None:
        if not self.cfg.email_enabled or not self.cfg.email_to:
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.cfg.email_from or self.cfg.smtp_user
        msg["To"] = ", ".join(self.cfg.email_to)
        msg.set_content(body)
        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port) as server:
            server.starttls()
            if self.cfg.smtp_user:
                server.login(self.cfg.smtp_user, self.cfg.smtp_password)
            server.send_message(msg)
