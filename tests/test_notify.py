"""notify_actions: brain orchestration + HTTP route, with mailer stubbed out."""
from fastapi.testclient import TestClient

import brain
import db
import mailer
import server
from models import ActionItem, MeetingReport


def _seed_meeting_with_actions():
    rep = MeetingReport(
        title="Họp tuần", date="2026-06-01", summary="s",
        action_items=[
            ActionItem(task="Làm A", owner="Lan", deadline="2099-01-01", status="mở"),
            ActionItem(task="Làm B", owner="Minh", status="quá hạn"),
            ActionItem(task="Làm C", owner="An", status="xong"),
        ],
    )
    return db.save_meeting(rep, transcript="t")


def test_notify_actions_sends_open_and_overdue(monkeypatch):
    _seed_meeting_with_actions()
    captured = {}

    def fake_send(actions, meeting_titles=None, to=None):
        captured["actions"] = list(actions)
        captured["titles"] = meeting_titles
        captured["to"] = to
        return True

    monkeypatch.setattr(mailer, "send_action_digest", fake_send)
    res = brain.notify_actions(refresh=False)            # refresh=False -> no LLM

    assert res == {"sent": True, "open_items": 2, "overdue": 1, "reason": "sent"}
    assert captured["titles"] == {1: "Họp tuần"}         # meeting id -> title map passed
    assert {a.task for a in captured["actions"]} == {"Làm A", "Làm B", "Làm C"}


def test_notify_actions_reason_when_disabled(monkeypatch):
    _seed_meeting_with_actions()
    monkeypatch.setattr(mailer, "send_action_digest",
                        lambda *a, **k: False)            # email disabled/failed
    res = brain.notify_actions(refresh=False)
    assert res["sent"] is False and res["reason"] == "email_disabled"
    assert res["open_items"] == 2


def test_notify_actions_no_open_items(monkeypatch):
    rep = MeetingReport(title="x", date="2026-06-01", summary="s",
                        action_items=[ActionItem(task="done", status="xong")])
    db.save_meeting(rep, transcript="t")
    monkeypatch.setattr(mailer, "send_action_digest", lambda *a, **k: False)
    res = brain.notify_actions(refresh=False)
    assert res == {"sent": False, "open_items": 0, "overdue": 0, "reason": "no_open_items"}


def test_route_notify_actions(monkeypatch):
    _seed_meeting_with_actions()
    monkeypatch.setattr(mailer, "send_action_digest", lambda *a, **k: True)
    client = TestClient(server.app)
    r = client.post("/api/notify/actions", json={"refresh": False})
    assert r.status_code == 200
    assert r.json() == {"sent": True, "open_items": 2, "overdue": 1, "reason": "sent"}
