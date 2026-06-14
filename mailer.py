"""Optional SMTP delivery of the report file. Never raises into the caller."""
import logging
import smtplib
from email.message import EmailMessage
import config
import report

log = logging.getLogger("meeting-ghost.mailer")

_MIME = {
    "docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pdf": ("application", "pdf"),
}


def send(report_bytes: bytes, fmt: str, title: str, date: str) -> bool:
    """Returns True if an email was sent, False if disabled or failed."""
    if not config.EMAIL_ENABLED or not config.SMTP_HOST or not config.EMAIL_TO:
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[Meeting Ghost] {title} — {date}"
        msg["From"] = config.EMAIL_FROM
        msg["To"] = ", ".join(config.EMAIL_TO)
        msg.set_content(f"Biên bản cuộc họp '{title}' ({date}) đính kèm.")
        maintype, subtype = _MIME.get(fmt, ("application", "octet-stream"))
        msg.add_attachment(report_bytes, maintype=maintype, subtype=subtype,
                           filename=report.build_filename(title, date, fmt))
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as s:
            s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 - email is best-effort
        log.warning("email send failed: %s", e)
        return False
