"""Tests for the memory store: save, dedup, denormalize, query-by-subject."""
import db
from models import MeetingReport, ActionItem, KnowledgeFact, Contradiction


def _report(title="Họp Sprint", date="2026-06-02", actions=None, transcript="abc"):
    return MeetingReport(
        title=title, date=date, summary="tóm tắt",
        action_items=actions or [],
        full_transcript=transcript,
    )


def test_save_meeting_and_denormalize_actions():
    r = _report(actions=[
        ActionItem(task="Viết spec", owner="An", deadline="2026-06-05", priority="cao"),
        ActionItem(task="Review PR", owner="Bình"),
    ])
    mid = db.save_meeting(r)
    assert mid > 0
    actions = db.all_actions()
    assert len(actions) == 2
    assert {a.owner for a in actions} == {"An", "Bình"}
    assert all(a.meeting_id == mid for a in actions)
    # default status applied
    assert actions[0].status == "mở"


def test_save_meeting_dedup_by_content_hash():
    r = _report(transcript="same content")
    first = db.save_meeting(r)
    second = db.save_meeting(_report(transcript="same content"))
    assert first == second
    assert db.counts()["meetings"] == 1


def test_report_roundtrip():
    r = _report(actions=[ActionItem(task="X", priority="thấp")])
    mid = db.save_meeting(r)
    loaded = db.get_meeting(mid).report()
    assert loaded.title == r.title
    assert loaded.action_items[0].task == "X"


def test_facts_by_subject_and_status_filter():
    mid = db.save_meeting(_report())
    db.save_facts(mid, [
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="30/6"),
        KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr"),
    ])
    launch = db.facts_by_subject("Ngày Launch")  # case-insensitive
    assert len(launch) == 1
    assert launch[0].statement == "30/6"
    # active filter
    active = db.facts_by_subject("ngày launch", status="hiệu lực")
    assert len(active) == 1
    db.set_fact_status(launch[0].id, "đã thay thế")
    assert db.facts_by_subject("ngày launch", status="hiệu lực") == []


def test_all_facts_timeline_order():
    m1 = db.save_meeting(_report(date="2026-06-01", transcript="t1"))
    m2 = db.save_meeting(_report(date="2026-06-09", transcript="t2"))
    db.save_facts(m1, [KnowledgeFact(type="fact", subject="s", statement="cũ")])
    db.save_facts(m2, [KnowledgeFact(type="fact", subject="s", statement="mới")])
    facts = db.all_facts()
    assert [f.statement for f in facts] == ["cũ", "mới"]


def test_contradiction_and_action_link():
    mid = db.save_meeting(_report(actions=[ActionItem(task="Deploy")]))
    fids = db.save_facts(mid, [
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="30/6"),
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="15/7"),
    ])
    cid = db.save_contradiction(Contradiction(
        subject="ngày launch", explanation="30/6 vs 15/7", severity="cao",
        fact_a_id=fids[0], fact_b_id=fids[1],
    ))
    assert cid > 0
    assert db.all_contradictions()[0].subject == "ngày launch"

    action_id = db.all_actions()[0].id
    db.update_action_status(action_id, "xong")
    assert db.all_actions(status="xong")[0].id == action_id
    link_id = db.add_action_link(action_id, mid, "nhắc lại")
    assert link_id > 0


def test_delete_meeting_cascades():
    from models import Contradiction
    mid = db.save_meeting(_report(actions=[ActionItem(task="A")]))
    fids = db.save_facts(mid, [
        KnowledgeFact(type="quyết định", subject="s", statement="x"),
        KnowledgeFact(type="quyết định", subject="s", statement="y"),
    ])
    db.save_contradiction(Contradiction(subject="s", explanation="x vs y",
                                        fact_a_id=fids[0], fact_b_id=fids[1]))
    assert db.counts()["meetings"] == 1
    db.delete_meeting(mid)
    assert db.counts() == {"meetings": 0, "facts": 0, "actions": 0,
                           "contradictions": 0, "resurfaced": 0}


def test_save_meeting_as_new_bypasses_dedup():
    r = _report(transcript="same")
    a = db.save_meeting(r, dedup=True)
    b = db.save_meeting(_report(transcript="same"), dedup=False, dedup_salt="x2")
    assert a != b
    assert db.counts()["meetings"] == 2


def test_audio_hash_lookup():
    h = db.audio_hash(b"raw audio bytes")
    mid = db.save_meeting(_report(), audio_hash_val=h)
    found = db.find_by_audio_hash(h)
    assert found is not None and found.id == mid


def test_counts():
    mid = db.save_meeting(_report(actions=[ActionItem(task="A")]))
    db.save_facts(mid, [KnowledgeFact(type="fact", subject="s", statement="x")])
    c = db.counts()
    assert c == {"meetings": 1, "facts": 1, "actions": 1, "contradictions": 0, "resurfaced": 0}
