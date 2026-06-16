"""mailer: text + action-digest delivery is best-effort and guarded."""
from types import SimpleNamespace

import config
import mailer


def _action(task, status="mở", owner=None, deadline=None, meeting_id=1):
    return SimpleNamespace(task=task, status=status, owner=owner,
                           deadline=deadline, meeting_id=meeting_id)


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
