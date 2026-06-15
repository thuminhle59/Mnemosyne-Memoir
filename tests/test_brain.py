"""Tests for extract_facts, detect_contradictions, ingest, retrieve (mock LLM)."""
import json

import db
import brain
import retrieve as retrieve_mod
from models import MeetingReport, ActionItem, KnowledgeFact


def _report(title="Họp", date="2026-06-02", summary="tóm tắt", actions=None, transcript="nội dung họp"):
    return MeetingReport(title=title, date=date, summary=summary,
                         action_items=actions or [], full_transcript=transcript)


# ---------------------------------------------------------------- extract_facts

def test_extract_facts_parses_factlist(monkeypatch):
    payload = {"facts": [
        {"type": "quyết định", "subject": "ngày launch", "statement": "30/6", "quote": "chốt 30/6"},
        {"type": "số liệu", "subject": "ngân sách", "statement": "500tr", "quote": None},
    ]}
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(payload))
    facts = brain.extract_facts(_report(), "transcript")
    assert [f.subject for f in facts] == ["ngày launch", "ngân sách"]
    assert facts[0].type == "quyết định"


def test_extract_facts_returns_empty_on_bad_json(monkeypatch):
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: "xin lỗi, không có JSON")
    assert brain.extract_facts(_report(), "t") == []


# ---------------------------------------------------------------- ingest

def test_ingest_saves_meeting_facts_and_runs_contradiction(monkeypatch):
    monkeypatch.setattr(brain.analyze, "analyze",
                        lambda transcript, date: _report(date=date, transcript=transcript))
    facts_json = {"facts": [{"type": "quyết định", "subject": "ngày launch",
                             "statement": "30/6", "quote": "chốt 30/6"}]}

    def fake_chat(prompt, model, **k):
        # only the fact-extraction prompt is hit here (no prior facts -> no contra call)
        return json.dumps(facts_json)

    monkeypatch.setattr(brain.llm, "chat", fake_chat)
    out = brain.ingest(text="cuộc họp chốt ngày launch 30/6", date="2026-06-02", title="Họp 1")
    assert out["meeting_id"] > 0
    assert db.counts()["meetings"] == 1
    assert db.counts()["facts"] == 1
    saved = db.all_facts()
    assert saved[0].subject == "ngày launch"
    assert saved[0].meeting_id == out["meeting_id"]


def test_reanalyze_replaces_report_and_facts(monkeypatch):
    # initial ingest via text
    monkeypatch.setattr(brain.analyze, "analyze",
                        lambda transcript, date: _report(date=date, summary=transcript,
                                                         actions=[ActionItem(task="cũ")]))
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"facts": [{"type": "fact", "subject": "s", "statement": transcript_marker(prompt)}]}))
    out = brain.ingest(text="bản gốc", title="Họp", date="2026-06-02")
    mid = out["meeting_id"]

    # edit transcript + reanalyze
    monkeypatch.setattr(brain.analyze, "analyze",
                        lambda transcript, date: _report(date=date, summary=transcript,
                                                         actions=[ActionItem(task="mới")]))
    brain.reanalyze(mid, "bản đã sửa")
    rep = db.get_meeting(mid).report()
    assert rep.summary == "bản đã sửa"
    assert [a.task for a in db.all_actions()] == ["mới"]   # old action replaced
    assert db.counts()["facts"] >= 1


def transcript_marker(prompt):
    return "x"


def test_ingest_detects_contradiction_across_meetings(monkeypatch):
    monkeypatch.setattr(brain.analyze, "analyze",
                        lambda transcript, date: _report(date=date, transcript=transcript))

    def chat_router(prompt, model, **k):
        if '"facts"' in prompt or "TRÍCH" in prompt:
            subj_stmt = ("15/7" if "15/7" in prompt else "30/6")
            return json.dumps({"facts": [{"type": "quyết định", "subject": "ngày launch",
                                          "statement": subj_stmt, "quote": ""}]})
        # contradiction verdict prompt
        return json.dumps({"contradicts": True, "explanation": "30/6 vs 15/7", "severity": "cao"})

    monkeypatch.setattr(brain.llm, "chat", chat_router)

    brain.ingest(text="họp tuần 1: chốt ngày launch 30/6", date="2026-06-02", title="M1")
    out2 = brain.ingest(text="họp tuần 2: dời ngày launch 15/7", date="2026-06-09", title="M2")

    assert len(out2["contradictions"]) == 1
    assert out2["contradictions"][0].subject == "ngày launch"
    # the older fact got superseded
    actives = db.facts_by_subject("ngày launch", status="hiệu lực")
    assert [f.statement for f in actives] == ["15/7"]
    assert db.counts()["contradictions"] == 1


# ---------------------------------------------------------------- forgotten decisions

def test_detect_forgotten_decision_resurfaced(monkeypatch):
    from models import KnowledgeFact
    m1 = db.save_meeting(_report(title="Họp 1", date="2026-06-01", transcript="t1"))
    db.save_facts(m1, [KnowledgeFact(type="quyết định", subject="tính năng X",
                                     statement="Quyết định KHÔNG làm tính năng X")])
    m2 = db.save_meeting(_report(title="Họp 2", date="2026-06-08", transcript="t2"))
    nf = KnowledgeFact(type="quyết định", subject="tính năng X",
                       statement="Đề xuất làm lại tính năng X", source_meeting_id=m2)
    db.save_facts(m2, [nf])
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"resurfaced": True, "kind": "rejected", "explanation": "X từng bị bác, nay nhắc lại"}))
    found = brain.detect_forgotten_decisions([nf])
    assert len(found) == 1 and found[0]["kind"] == "rejected"
    assert db.counts()["resurfaced"] == 1
    view = brain.resurfaced_view()
    assert view[0]["new"]["statement"] == "Đề xuất làm lại tính năng X"


def test_detect_forgotten_skips_when_none(monkeypatch):
    from models import KnowledgeFact
    m1 = db.save_meeting(_report(title="A", date="2026-06-01", transcript="t1"))
    db.save_facts(m1, [KnowledgeFact(type="quyết định", subject="ngân sách", statement="500tr")])
    m2 = db.save_meeting(_report(title="B", date="2026-06-08", transcript="t2"))
    nf = KnowledgeFact(type="quyết định", subject="ngân sách", statement="600tr", source_meeting_id=m2)
    db.save_facts(m2, [nf])
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"resurfaced": False, "kind": "none", "explanation": ""}))
    assert brain.detect_forgotten_decisions([nf]) == []
    assert db.counts()["resurfaced"] == 0


# ---------------------------------------------------------------- retrieve

def test_retrieve_keyword_match_timeline_order():
    m1 = db.save_meeting(_report(title="Họp ngân sách", date="2026-06-01", transcript="t1"))
    m2 = db.save_meeting(_report(title="Họp kỹ thuật", date="2026-06-09", transcript="t2"))
    db.save_facts(m1, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr")])
    db.save_facts(m2, [KnowledgeFact(type="fact", subject="kiến trúc", statement="microservice")])
    ctx = retrieve_mod.retrieve("ngân sách bao nhiêu")
    subjects = [f.subject for f in ctx.facts]
    assert "ngân sách" in subjects
    assert "kiến trúc" not in subjects
    # meetings chronological
    assert [m.date for m in ctx.meetings] == sorted(m.date for m in ctx.meetings)


def test_retrieve_fallback_when_no_match():
    db.save_meeting(_report(title="Họp X", transcript="abc"))
    ctx = retrieve_mod.retrieve("một chủ đề hoàn toàn không liên quan zzz")
    assert not ctx.is_empty()  # falls back to recent grounding


# ---------------------------------------------------------------- correct_terms (STT layer 3)

def test_correct_terms_applies_reasonable_fix(monkeypatch):
    monkeypatch.setattr(brain.config, "STT_LLM_CORRECT", True)
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"corrected": "Cuộc thi Claw-a-thon của GreenNode rất hay."}))
    out = brain.correct_terms("Cuộc thi CloudTown của Green Node rất hay.")
    assert out == "Cuộc thi Claw-a-thon của GreenNode rất hay."


def test_correct_terms_guardrail_rejects_over_edit(monkeypatch):
    monkeypatch.setattr(brain.config, "STT_LLM_CORRECT", True)
    original = "Đây là một đoạn transcript dài bình thường nói về kế hoạch dự án và ngân sách."
    # model tries to truncate drastically -> guardrail keeps original
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"corrected": "ok"}))
    assert brain.correct_terms(original) == original


def test_correct_terms_disabled_returns_original(monkeypatch):
    monkeypatch.setattr(brain.config, "STT_LLM_CORRECT", False)
    s = "bất kỳ transcript nào"
    assert brain.correct_terms(s) == s


# ---------------------------------------------------------------- timestamp + contradiction view

def test_estimate_timestamp_proportional():
    import types
    m = types.SimpleNamespace(transcript="A" * 100 + "MỤC TIÊU", duration_sec=200)
    ts = brain.estimate_timestamp(m, "MỤC TIÊU")
    assert ts == "03:05"  # idx 100 / len 108 * 200s ≈ 185s


def test_estimate_timestamp_none_without_duration():
    import types
    m = types.SimpleNamespace(transcript="abc", duration_sec=None)
    assert brain.estimate_timestamp(m, "abc") is None


def test_estimate_timestamp_uses_chunk_map():
    import types, json
    transcript = "AAAA TARGET0\nBBBB TARGET1"   # chunk0 chars 0-11, chunk1 chars 13-24
    chunk_map = json.dumps([
        {"t0": 0, "c0": 0, "clen": 12, "dur": 600},
        {"t0": 600, "c0": 13, "clen": 12, "dur": 600},
    ])
    m = types.SimpleNamespace(transcript=transcript, duration_sec=1200, chunk_map=chunk_map)
    # "TARGET1" sits in chunk1 (t0=600); proportional-whole would mis-place it earlier
    assert brain.estimate_timestamp(m, "TARGET1") == "14:10"


def test_contradiction_view_enriches_both_sides():
    from models import Contradiction
    mid = db.save_meeting(_report(title="Họp 1", date="2026-06-02", transcript="t"))
    fids = db.save_facts(mid, [
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="30/6", quote="chốt 30/6"),
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="15/7", quote="dời 15/7"),
    ])
    db.save_contradiction(Contradiction(subject="ngày launch", explanation="30/6 vs 15/7",
                                        severity="cao", fact_a_id=fids[0], fact_b_id=fids[1]))
    view = brain.contradiction_view()
    assert len(view) == 1
    assert view[0]["explanation"] == "30/6 vs 15/7"
    assert view[0]["old"]["statement"] == "30/6"
    assert view[0]["new"]["quote"] == "dời 15/7"
    assert view[0]["old"]["meeting_title"] == "Họp 1"


# ---------------------------------------------------------------- ask

def test_ask_returns_answer_with_enriched_citations(monkeypatch):
    mid = db.save_meeting(_report(title="Họp ngân sách", date="2026-06-01", transcript="t"))
    db.save_facts(mid, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr")])

    def fake_chat(prompt, model, **k):
        return json.dumps({
            "answer": "Ngân sách chốt 500tr ở họp 01/6.",
            "citations": [{"meeting_id": mid, "quote": "ngân sách 500tr"}],
        })

    monkeypatch.setattr(brain.llm, "chat", fake_chat)
    ans = brain.ask("ngân sách bao nhiêu")
    assert "500tr" in ans.text
    assert len(ans.citations) == 1
    # citation enriched from db
    assert ans.citations[0].meeting_title == "Họp ngân sách"
    assert ans.citations[0].date == "2026-06-01"


def test_ask_empty_memory_returns_message():
    ans = brain.ask("bất kỳ")
    assert "Chưa có cuộc họp" in ans.text


# ---------------------------------------------------------------- digest

def test_digest_builds_report_with_open_actions(monkeypatch):
    db.save_meeting(_report(title="Họp 1", date="2026-06-01",
                            actions=[ActionItem(task="Deploy", owner="An")], transcript="t1"))
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps({
        "summary": "Tổng quan dự án.", "key_points": ["điểm 1"],
        "decisions": ["chốt A"], "risks": ["rủi ro X"],
    }))
    rep = brain.digest("all")
    assert rep.title.startswith("Executive Digest")
    assert rep.summary == "Tổng quan dự án."
    assert any(a.task == "Deploy" for a in rep.action_items)  # open action carried in


# ---------------------------------------------------------------- follow_up

def test_follow_up_updates_status_and_links(monkeypatch):
    m1 = db.save_meeting(_report(title="Họp 1", date="2026-06-01",
                                 actions=[ActionItem(task="Viết spec", owner="An")], transcript="t1"))
    m2 = db.save_meeting(_report(title="Họp 2", date="2026-06-08",
                                 summary="An đã hoàn thành spec", transcript="t2"))
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps({
        "status": "xong", "note": "đã xong ở họp 2", "related_meeting_id": m2,
    }))
    res = brain.follow_up()
    assert len(res) == 1
    assert res[0]["status"] == "xong"
    # status persisted
    action = db.all_actions()[0]
    assert action.status == "xong"
