"""Optional SMTP delivery (report attachments + todo/action reminders).

Never raises into the caller — every send is best-effort and returns a bool.
"""
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


def _enabled() -> bool:
    return bool(config.EMAIL_ENABLED and config.SMTP_HOST and config.EMAIL_TO)


def _deliver(msg: EmailMessage) -> bool:
    """Open an SMTP connection and send `msg`. Returns True on success.

    Uses implicit TLS (SMTP_SSL, e.g. port 465) when config.SMTP_SSL is set,
    otherwise plain SMTP + STARTTLS (e.g. port 587).
    """
    try:
        if config.SMTP_SSL:
            s = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT)
        else:
            s = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT)
        with s:
            if not config.SMTP_SSL:
                s.starttls()
            if config.SMTP_USER:
                s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 - email is best-effort
        log.warning("email send failed: %s", e)
        return False


def send(report_bytes: bytes, fmt: str, title: str, date: str) -> bool:
    """Returns True if an email was sent, False if disabled or failed."""
    if not _enabled():
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[Memoir] {title} — {date}"
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(config.EMAIL_TO)
    msg.set_content(f"Biên bản cuộc họp '{title}' ({date}) đính kèm.")
    maintype, subtype = _MIME.get(fmt, ("application", "octet-stream"))
    msg.add_attachment(report_bytes, maintype=maintype, subtype=subtype,
                       filename=report.build_filename(title, date, fmt))
    return _deliver(msg)


def send_text(subject: str, body: str, to: list[str] | None = None) -> bool:
    """Send a plain-text email. Returns True if sent, False if disabled/failed."""
    recipients = to or config.EMAIL_TO
    if not (config.EMAIL_ENABLED and config.SMTP_HOST and recipients):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    return _deliver(msg)


def _format_action_digest(actions, meeting_titles: dict | None = None) -> str:
    """Render not-done actions into a Vietnamese reminder body, overdue first."""
    titles = meeting_titles or {}
    overdue = [a for a in actions if a.status == "quá hạn"]
    pending = [a for a in actions if a.status not in ("quá hạn", "xong")]

    def line(a) -> str:
        parts = [f"  • {a.task}"]
        if a.owner:
            parts.append(f"— phụ trách: {a.owner}")
        if a.deadline:
            parts.append(f"— hạn: {a.deadline}")
        src = titles.get(a.meeting_id)
        if src:
            parts.append(f"(từ họp: {src})")
        return " ".join(parts)

    blocks: list[str] = []
    if overdue:
        blocks.append("⚠️ QUÁ HẠN ({}):\n".format(len(overdue))
                      + "\n".join(line(a) for a in overdue))
    if pending:
        blocks.append("📋 CHƯA XONG ({}):\n".format(len(pending))
                      + "\n".join(line(a) for a in pending))
    if not blocks:
        return "Không có công việc nào đang mở hoặc quá hạn. 🎉"
    return "\n\n".join(blocks)


def send_assignment(action, to: str, note: str | None = None,
                    meeting_title: str | None = None) -> bool:
    """Email one assignee that they have been given `action`. `to` is a single
    address. Returns False if email is disabled/failed (best-effort)."""
    if not to:
        return False
    lines = ["Bạn vừa được giao một công việc từ Memoir:", "",
             f"  • Việc: {action.task}"]
    if action.deadline:
        lines.append(f"  • Hạn: {action.deadline}")
    if action.priority:
        lines.append(f"  • Ưu tiên: {action.priority}")
    if meeting_title:
        lines.append(f"  • Từ cuộc họp: {meeting_title}")
    if note:
        lines += ["", f"Ghi chú: {note}"]
    subject = "[Memoir] Bạn được giao việc"
    return send_text(subject, "\n".join(lines), to=[to])


def send_action_digest(actions, meeting_titles: dict | None = None,
                       to: list[str] | None = None) -> bool:
    """Email a todo/action reminder. `actions` is a list of Action rows.

    Skips sending (returns False) when email is disabled or there is nothing
    open or overdue to report.
    """
    open_items = [a for a in actions if a.status != "xong"]
    if not open_items:
        return False
    n_overdue = sum(1 for a in open_items if a.status == "quá hạn")
    suffix = f" — {n_overdue} quá hạn" if n_overdue else ""
    subject = f"[Memoir] Nhắc việc: {len(open_items)} action item{suffix}"
    return send_text(subject, _format_action_digest(open_items, meeting_titles), to=to)
