"""SMTP email notifier."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from bakasur.config import Settings
from bakasur.models import ApplicationRow, ValidationIssue


class EmailNotifier:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    def _send(self, subject: str, body: str) -> None:
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

    def send_digest(
        self,
        gazette_id: str,
        rows: list[ApplicationRow],
        review: list[ValidationIssue],
        *,
        extracted: int,
        sheet_url: str | None = None,
        sheets_pending: int = 0,
        sheets_error: str | None = None,
    ) -> None:
        if rows:
            subject = f"Goa Gazette 39A — {len(rows)} new application(s)"
        elif review:
            subject = f"Goa Gazette 39A — {len(review)} issue(s) need review"
        elif extracted == 0:
            subject = "Goa Gazette 39A — no rows found"
        else:
            return

        lines = [f"Gazette: {gazette_id}", ""]
        if extracted == 0:
            lines.append(
                "No 39A application rows were found. If this gazette contains a 39A "
                "notification, the table was probably not detected — check the PDF."
            )
            lines.append("")
        if sheet_url:
            lines.append(f"Sheet: {sheet_url}")
            lines.append("")
        if sheets_error:
            lines.append(
                f"WARNING: Google Sheets upload failed; {sheets_pending} record(s) are "
                f"queued and will be retried on the next run ({sheets_error})."
            )
            lines.append("")

        if rows:
            lines.append(f"{len(rows)} new application row(s):")
            for row in rows[:20]:
                lines.append(
                    f"- {row.sr_no or '?'} | {row.applicant or 'N/A'} | "
                    f"{row.village or ''}, {row.taluka or ''} | {row.decision or ''}"
                )
            if len(rows) > 20:
                lines.append(f"... and {len(rows) - 20} more")
            lines.append("")

        if review:
            errors = sum(1 for i in review if i.severity == "error")
            lines.append(
                f"Review queue: {len(review)} issue(s) "
                f"({errors} rejected row(s), {len(review) - errors} warning(s))"
            )
            for issue in review[:20]:
                where = ""
                if issue.row:
                    where = (
                        f" — notification {issue.row.notification_no or '?'}, "
                        f"Sr. {issue.row.sr_no or '?'}"
                    )
                lines.append(f"- [{issue.severity}] {issue.reason}{where}")
            if len(review) > 20:
                lines.append(f"... and {len(review) - 20} more")

        self._send(subject, "\n".join(lines).rstrip())

    def send_failure(self, gazette_id: str, error: str) -> None:
        self._send(
            f"Goa Gazette 39A — processing failed ({gazette_id})",
            f"Gazette {gazette_id} failed:\n\n{error}",
        )
