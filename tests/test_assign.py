"""assign_action: set owner + optional one-shot email to the assignee."""
from fastapi.testclient import TestClient

import brain
import db
import mailer
import server
from models import ActionItem, MeetingReport


def _seed_one_action():
    rep = MeetingReport(
        title="Họp tuần", date="2026-06-01", summary="s",
        action_items=[ActionItem(task="Làm A", deadline="2026-07-01", priority="cao")],
    )
    db.save_meeting(rep, transcript="t")
    return db.all_actions()[0].id


def test_assign_sets_owner_and_emails(monkeypatch):
    aid = _seed_one_action()
    captured = {}

    def fake_send(action, to, note=None, meeting_title=None):
        captured.update(task=action.task, to=to, title=meeting_title, note=note)
        return True

    monkeypatch.setattr(mailer, "send_assignment", fake_send)
    res = brain.assign_action(aid, "Lan", email="lan@cty.com", note="gấp")

    assert res == {"assigned": True, "owner": "Lan", "sent": True, "reason": "sent"}
    assert db.get_action(aid).owner == "Lan"            # owner persisted
    assert captured == {"task": "Làm A", "to": "lan@cty.com",
                        "title": "Họp tuần", "note": "gấp"}


def test_assign_without_email_skips_send(monkeypatch):
    aid = _seed_one_action()
    monkeypatch.setattr(mailer, "send_assignment",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send")))
    res = brain.assign_action(aid, "Minh", email=None)
    assert res["assigned"] is True and res["sent"] is False and res["reason"] == "no_email"
    assert db.get_action(aid).owner == "Minh"


def test_assign_notify_false_skips_send(monkeypatch):
    aid = _seed_one_action()
    res = brain.assign_action(aid, "An", email="an@cty.com", notify=False)
    assert res["sent"] is False and res["reason"] == "no_notify"


def test_assign_missing_action():
    res = brain.assign_action(99999, "Lan", email="x@y.z")
    assert res == {"assigned": False, "reason": "not_found"}


def test_route_assign_emails_owner(monkeypatch):
    aid = _seed_one_action()
    monkeypatch.setattr(mailer, "send_assignment", lambda *a, **k: True)
    client = TestClient(server.app)
    r = client.post(f"/api/actions/{aid}/assign",
                    json={"owner": "Lan", "email": "lan@cty.com"})
    assert r.status_code == 200
    assert r.json()["sent"] is True and r.json()["owner"] == "Lan"


def test_route_assign_404_for_unknown(monkeypatch):
    monkeypatch.setattr(mailer, "send_assignment", lambda *a, **k: True)
    client = TestClient(server.app)
    r = client.post("/api/actions/99999/assign", json={"owner": "Lan"})
    assert r.status_code == 404
