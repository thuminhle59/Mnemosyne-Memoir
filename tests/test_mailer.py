"""mailer: text + action-digest delivery is best-effort and guarded."""
from types import SimpleNamespace

import smtplib

import config
import mailer


def _action(task, status="mở", owner=None, deadline=None, meeting_id=1):
    return SimpleNamespace(task=task, status=status, owner=owner,
                           deadline=deadline, meeting_id=meeting_id, priority=None)


def test_send_text_disabled_returns_false(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", False)
    assert mailer.send_text("s", "b") is False


def test_send_text_no_recipients_returns_false(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "EMAIL_TO", [])
    assert mailer.send_text("s", "b") is False


def test_send_text_delivers_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "EMAIL_TO", ["a@b.c"])
    sent = {}
    monkeypatch.setattr(mailer, "_deliver",
                        lambda msg: sent.update(subject=msg["Subject"], to=msg["To"]) or True)
    assert mailer.send_text("Hi", "body", to=["x@y.z"]) is True
    assert sent["to"] == "x@y.z"


def test_format_digest_groups_and_skips_done():
    acts = [_action("Làm A", "quá hạn", owner="Lan", deadline="2026-06-10"),
            _action("Làm B", "mở", owner="Minh"),
            _action("Làm C", "xong")]
    body = mailer._format_action_digest(acts, {1: "Họp tuần"})
    assert "QUÁ HẠN (1)" in body and "CHƯA XONG (1)" in body
    assert "Làm A" in body and "Làm B" in body
    assert "Làm C" not in body            # done items excluded
    assert "Lan" in body and "Họp tuần" in body


def test_send_action_digest_no_open_items(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "EMAIL_TO", ["a@b.c"])
    assert mailer.send_action_digest([_action("done", "xong")]) is False


def test_send_action_digest_sends_with_overdue_subject(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "EMAIL_TO", ["a@b.c"])
    captured = {}
    monkeypatch.setattr(mailer, "_deliver",
                        lambda msg: captured.update(subject=msg["Subject"]) or True)
    ok = mailer.send_action_digest([_action("x", "quá hạn"), _action("y", "mở")])
    assert ok is True
    assert "2 action item" in captured["subject"] and "1 quá hạn" in captured["subject"]


def test_send_assignment_uses_default_subject(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "EMAIL_TO", ["a@b.c"])
    captured = {}
    monkeypatch.setattr(mailer, "_deliver",
                        lambda msg: captured.update(subject=msg["Subject"], body=msg.get_content()) or True)

    ok = mailer.send_assignment(_action("Một task rất dài"), "owner@example.com")

    assert ok is True
    assert captured["subject"] == "[Memoir] Bạn được giao việc"
    assert "Một task rất dài" in captured["body"]


class _FakeSMTP:
    """Records connection mode + calls, mimics smtplib context-manager API."""
    last = {}

    def __init__(self, host, port, *a, **k):
        _FakeSMTP.last = {"host": host, "port": port, "starttls": False, "ssl": False}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, *a, **k): _FakeSMTP.last["starttls"] = True
    def login(self, *a, **k): pass
    def send_message(self, msg): _FakeSMTP.last["sent"] = True


class _FakeSMTPSSL(_FakeSMTP):
    def __init__(self, host, port, *a, **k):
        super().__init__(host, port); _FakeSMTP.last["ssl"] = True


def _enable_email(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(config, "EMAIL_TO", ["a@b.c"])
    monkeypatch.setattr(config, "SMTP_USER", "u")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)


def test_deliver_uses_implicit_ssl_when_configured(monkeypatch):
    _enable_email(monkeypatch)
    monkeypatch.setattr(config, "SMTP_SSL", True)
    monkeypatch.setattr(config, "SMTP_PORT", 465)
    assert mailer.send_text("s", "b") is True
    assert _FakeSMTP.last["ssl"] is True and _FakeSMTP.last["starttls"] is False


def test_deliver_uses_starttls_when_not_ssl(monkeypatch):
    _enable_email(monkeypatch)
    monkeypatch.setattr(config, "SMTP_SSL", False)
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    assert mailer.send_text("s", "b") is True
    assert _FakeSMTP.last["ssl"] is False and _FakeSMTP.last["starttls"] is True
