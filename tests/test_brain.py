"""Tests for extract_facts, detect_contradictions, ingest, retrieve (mock LLM)."""
import json

import analyze
import db
import brain
import media
import retrieve as retrieve_mod
from models import MeetingReport, ActionItem, KnowledgeFact, Decision


def _report(title="Họp", date="2026-06-02", summary="tóm tắt", actions=None, transcript="nội dung họp"):
    return MeetingReport(title=title, date=date, summary=summary,
                         action_items=actions or [], full_transcript=transcript)


# ---------------------------------------------------------------- extract_facts

def test_analysis_prompts_preserve_english_terms_and_proper_nouns():
    transcript = "Team Merchant nói AgentBase, OpenClaw, MCP Server, QA và UAT."
    analysis_prompt = analyze._prompt(transcript, "2026-06-16")
    facts_prompt = brain._facts_prompt(_report(summary="AgentBase and OpenClaw"), transcript)

    for prompt in [analysis_prompt, facts_prompt]:
        assert "GIỮ NGUYÊN chính xác tiếng Anh" in prompt
        assert "KHÔNG phiên âm" in prompt
        assert "Merchant, AgentBase, OpenClaw, MCP Server, QA, UAT" in prompt


def test_analysis_and_fact_prompts_allow_summary_like_decisions_without_quotes():
    transcript = "Cả nhóm thống nhất triển khai Pilot trước, Full Rollout chờ sau."
    analysis_prompt = analyze._prompt(transcript, "2026-06-16")
    facts_prompt = brain._facts_prompt(
        _report(summary="Cuộc họp chốt triển khai Pilot trước Full Rollout."),
        transcript,
    )

    assert '"decisions": [{"text": str, "quote": null}]' in analysis_prompt
    assert "decision có thể là câu tổng hợp giống summary" in analysis_prompt
    assert "KHÔNG cần quote gốc cho decisions" in analysis_prompt
    assert "ĐƯỢC trích fact hoặc quyết định từ phần Tóm tắt" in facts_prompt
    assert "quote có thể là null" in facts_prompt


def test_analysis_prompt_requests_structured_summary_brief():
    prompt = analyze._prompt("Transcript", "2026-06-16")

    assert '"summary_brief"' in prompt
    assert '"context": str|null' in prompt
    assert '"decisions": [str]' in prompt
    assert '"risk": str|null' in prompt
    assert '"next_step": str|null' in prompt
    assert "Context: đúng 1 câu" in prompt
    assert "Decisions: tối đa 2 câu" in prompt
    assert "Risks: đúng 1 câu" in prompt
    assert "Next steps: đúng 1 câu" in prompt


def test_meeting_report_normalizes_summary_brief_limits_and_fallbacks():
    report = MeetingReport.model_validate({
        "title": "Họp Pilot",
        "date": "2026-06-16",
        "summary": "Cuộc họp chốt Pilot. Câu phụ.",
        "summary_brief": {
            "context": "",
            "decisions": ["Mở Pilot", "Không Full Rollout", "Bỏ câu thứ ba"],
            "risk": "",
            "next_step": "",
        },
        "decisions": [
            {"text": "Mở Pilot", "quote": None},
            {"text": "Không Full Rollout", "quote": None},
        ],
        "action_items": [{"task": "Gửi checklist", "owner": "An", "deadline": None}],
        "risks": ["Latency còn cao"],
    })

    assert report.summary_brief.context == "Cuộc họp chốt Pilot."
    assert report.summary_brief.decisions == ["Mở Pilot", "Không Full Rollout"]
    assert report.summary_brief.risk == "Latency còn cao"
    assert report.summary_brief.next_step == "Gửi checklist"


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


def test_extract_facts_dedupes_within_meeting(monkeypatch):
    """Identical claims (case/whitespace-insensitive) collapse to one fact."""
    payload = {"facts": [
        {"type": "số liệu", "subject": "ngân sách", "statement": "500tr", "quote": "a"},
        {"type": "số liệu", "subject": "Ngân Sách", "statement": " 500TR ", "quote": "b"},  # dup
        {"type": "quyết định", "subject": "ngày launch", "statement": "30/6", "quote": "c"},
    ]}
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(payload))
    facts = brain.extract_facts(_report(), "transcript")
    assert [(f.subject, f.statement) for f in facts] == [("ngân sách", "500tr"), ("ngày launch", "30/6")]


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


def test_reingesting_same_audio_reuses_existing_analysis_for_stable_decisions(monkeypatch):
    calls = {"analyze": 0, "facts": 0}

    def fake_analyze(transcript, date):
        calls["analyze"] += 1
        return _report(
            title="Original",
            date=date,
            transcript=transcript,
        ).model_copy(update={
            "decisions": [Decision(text=f"Decision version {calls['analyze']}", quote="quote")]
        })

    def fake_extract(report, transcript):
        calls["facts"] += 1
        return [KnowledgeFact(type="quyết định", subject="scope", statement=report.decisions[0].text, quote="quote")]

    monkeypatch.setattr(media, "audio_to_wav_chunks", lambda audio, filename, chunk_sec, do_extract: [b"wav"])
    monkeypatch.setattr(media, "wav_duration", lambda chunk: 12.0)
    monkeypatch.setattr(brain.transcribe, "transcribe", lambda *a, **k: "transcript")
    monkeypatch.setattr(brain, "correct_terms", lambda text: text)
    monkeypatch.setattr(brain.transcribe, "apply_corrections", lambda text: text)
    monkeypatch.setattr(brain.analyze, "analyze", fake_analyze)
    monkeypatch.setattr(brain, "extract_facts", fake_extract)
    monkeypatch.setattr(brain, "detect_contradictions", lambda facts: [])
    monkeypatch.setattr(brain, "detect_forgotten_decisions", lambda facts: [])

    first = brain.ingest(audio=b"same raw file", date="2026-06-16", title="First", on_duplicate="new")
    second = brain.ingest(audio=b"same raw file", date="2026-06-16", title="Second", on_duplicate="new")

    assert first["meeting_id"] != second["meeting_id"]
    assert first["report"].decisions[0].text == "Decision version 1"
    assert second["report"].decisions[0].text == "Decision version 1"
    assert second["duplicate_of"] == first["meeting_id"]
    assert calls == {"analyze": 1, "facts": 1}
    assert [m.report().decisions[0].text for m in db.list_meetings(limit=10)] == [
        "Decision version 1",
        "Decision version 1",
    ]


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
        # batched contradiction verdict prompt (one candidate -> index 0)
        return json.dumps({"conflicts": [
            {"index": 0, "explanation": "30/6 vs 15/7", "severity": "cao"}]})

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
        {"resurfaced": True, "index": 0, "kind": "rejected",
         "explanation": "X từng bị bác, nay nhắc lại"}))
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


def test_correct_terms_guardrail_preserves_unknown_proper_nouns(monkeypatch):
    monkeypatch.setattr(brain.config, "STT_LLM_CORRECT", True)
    original = "Team Nova Portal đang chuẩn bị pilot settlement."
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"corrected": "Team OpenClaw Portal đang chuẩn bị pilot settlement."}))

    assert brain.correct_terms(original) == original


def test_correct_terms_disabled_returns_original(monkeypatch):
    monkeypatch.setattr(brain.config, "STT_LLM_CORRECT", False)
    s = "bất kỳ transcript nào"
    assert brain.correct_terms(s) == s


def test_apply_glossary_to_meeting_reanalyzes_when_transcript_changes(monkeypatch):
    class Meeting:
        id = 7
        transcript = "CloudTown sync"

    captured = {}
    monkeypatch.setattr(brain.db, "get_meeting", lambda meeting_id: Meeting())
    monkeypatch.setattr(brain, "correct_terms", lambda text: text)
    monkeypatch.setattr(brain.transcribe, "apply_corrections", lambda text: text.replace("CloudTown", "Claw-a-thon"))
    monkeypatch.setattr(brain, "reanalyze", lambda meeting_id, transcript: captured.setdefault("out", {
        "meeting_id": meeting_id,
        "report": None,
        "facts": [],
        "contradictions": [],
        "forgotten": [],
        "transcript": transcript,
    }))

    out = brain.apply_glossary_to_meeting(7)

    assert out["changed"] is True
    assert captured["out"]["transcript"] == "Claw-a-thon sync"


def test_apply_glossary_to_meeting_refreshes_analysis_when_no_mapping_matches(monkeypatch):
    class Meeting:
        id = 7
        transcript = "No glossary miss here"

    called = {"reanalyze": False, "transcript": None}
    monkeypatch.setattr(brain.db, "get_meeting", lambda meeting_id: Meeting())
    monkeypatch.setattr(brain, "correct_terms", lambda text: text)
    monkeypatch.setattr(brain.transcribe, "apply_corrections", lambda text: text)

    def fake_reanalyze(meeting_id, transcript):
        called.update(reanalyze=True, transcript=transcript)
        return {
            "meeting_id": meeting_id,
            "report": None,
            "facts": [],
            "contradictions": [],
            "forgotten": [],
        }

    monkeypatch.setattr(brain, "reanalyze", fake_reanalyze)

    out = brain.apply_glossary_to_meeting(7)

    assert out["changed"] is False
    assert called["reanalyze"] is True
    assert called["transcript"] == "No glossary miss here"


def test_apply_glossary_to_meeting_normalizes_report_facts_and_title_after_reanalysis(monkeypatch):
    db.add_glossary("Claw-a-thon", wrong="CloudTown")
    mid = db.save_meeting(
        _report(title="CloudTown - Họp", summary="CloudTown summary", transcript="CloudTown transcript"),
        transcript="CloudTown transcript",
    )

    monkeypatch.setattr(brain, "correct_terms", lambda text: text)
    monkeypatch.setattr(brain.analyze, "analyze", lambda transcript, date: _report(
        title="CloudTown - Họp",
        date=date,
        summary="CloudTown summary",
        actions=[ActionItem(task="CloudTown action", owner="CloudTown owner", quote="CloudTown quote")],
        transcript=transcript,
    ).model_copy(update={
        "decisions": [Decision(text="CloudTown decision", quote=None)],
        "risks": ["CloudTown risk"],
        "key_points": ["CloudTown key point"],
    }))
    monkeypatch.setattr(brain, "extract_facts", lambda report, transcript: [
        KnowledgeFact(type="fact", subject="CloudTown subject", statement="CloudTown fact", quote="CloudTown quote")
    ])
    monkeypatch.setattr(brain, "detect_contradictions", lambda facts: [])
    monkeypatch.setattr(brain, "detect_forgotten_decisions", lambda facts: [])

    out = brain.apply_glossary_to_meeting(mid)

    meeting = db.get_meeting(mid)
    report = meeting.report()
    facts = db.facts_of_meeting(mid)
    actions = db.all_actions()
    assert out["changed"] is True
    assert meeting.title == "Claw-a-thon - Họp"
    assert meeting.transcript == "Claw-a-thon transcript"
    assert report.summary == "Claw-a-thon summary"
    assert report.decisions[0].text == "Claw-a-thon decision"
    assert report.risks == ["Claw-a-thon risk"]
    assert report.key_points == ["Claw-a-thon key point"]
    assert actions[0].task == "Claw-a-thon action"
    assert actions[0].owner == "Claw-a-thon owner"
    assert facts[0].subject == "Claw-a-thon subject"
    assert facts[0].statement == "Claw-a-thon fact"


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


def test_estimate_timestamp_can_match_compact_task_text():
    import types
    transcript = "Mở đầu. Mọi người cần cài đặt Docker Desktop và đảm bảo mỗi team có ít nhất 1 máy đã set up Docker + GitHub."
    m = types.SimpleNamespace(transcript=transcript, duration_sec=120)

    assert brain.estimate_timestamp(m, "Cài Docker Desktop set up Docker GitHub") == "00:33"


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


def test_contradiction_view_skips_orphaned_fact_links():
    from models import Contradiction
    mid = db.save_meeting(_report(title="Họp 1", date="2026-06-02", transcript="t"))
    fids = db.save_facts(mid, [
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="30/6", quote="chốt 30/6"),
    ])
    db.save_contradiction(Contradiction(subject="ngày launch", explanation="orphan",
                                        fact_a_id=fids[0], fact_b_id=999999))
    assert brain.contradiction_view() == []


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


def test_ask_scopes_answer_to_active_meeting_group(monkeypatch):
    merchant = db.save_meeting(_report(title="Merchant Portal - Họp 1", date="2026-06-01", transcript="t1"))
    claw = db.save_meeting(_report(title="Claw-a-thon - Họp 1", date="2026-06-02", transcript="t2"))
    db.update_meeting_metadata(merchant, group_title="Merchant Portal")
    db.update_meeting_metadata(claw, group_title="Claw-a-thon")
    db.save_facts(merchant, [KnowledgeFact(type="quyết định", subject="ngân sách", statement="Merchant dùng 500tr")])
    db.save_facts(claw, [KnowledgeFact(type="quyết định", subject="ngân sách", statement="Claw-a-thon dùng 10 triệu")])
    captured = {}

    def fake_chat(prompt, model, **k):
        captured["prompt"] = prompt
        return json.dumps({
            "answer": "Merchant dùng 500tr.",
            "citations": [
                {"meeting_id": merchant, "quote": "Merchant dùng 500tr"},
                {"meeting_id": claw, "quote": "Claw-a-thon dùng 10 triệu"},
            ],
        })

    monkeypatch.setattr(brain.llm, "chat", fake_chat)

    ans = brain.ask("ngân sách bao nhiêu?", meeting_id=merchant)

    assert "Merchant dùng 500tr" in captured["prompt"]
    assert "Claw-a-thon dùng 10 triệu" not in captured["prompt"]
    assert [c.meeting_id for c in ans.citations] == [merchant]


def test_ask_empty_memory_returns_message():
    ans = brain.ask("bất kỳ")
    assert "Chưa có cuộc họp" in ans.text


def _seed_contradiction():
    from models import Contradiction
    mid = db.save_meeting(_report(title="Họp launch", date="2026-06-02", transcript="t"))
    fids = db.save_facts(mid, [
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="30/6", quote="chốt 30/6"),
        KnowledgeFact(type="quyết định", subject="ngày launch", statement="15/7", quote="dời 15/7"),
    ])
    db.save_contradiction(Contradiction(subject="ngày launch", explanation="30/6 đổi sang 15/7",
                                        severity="cao", fact_a_id=fids[0], fact_b_id=fids[1]))


def test_ask_injects_relevant_contradiction_into_context(monkeypatch):
    _seed_contradiction()
    seen = {}

    def capture(prompt, model, **k):
        seen["prompt"] = prompt
        return json.dumps({"answer": "Ban đầu 30/6, sau dời 15/7.", "citations": []})

    monkeypatch.setattr(brain.llm, "chat", capture)
    brain.ask("ngày launch chốt khi nào?")
    assert "### ⚠ MÂU THUẪN ĐÃ GHI NHẬN" in seen["prompt"]   # the injected block, not the rule
    assert "30/6" in seen["prompt"] and "15/7" in seen["prompt"]


def test_ask_omits_contradiction_block_when_unrelated(monkeypatch):
    _seed_contradiction()
    db.save_facts(db.save_meeting(_report(title="Họp NS", date="2026-06-03", transcript="t2")),
                  [KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr")])
    seen = {}

    def capture(prompt, model, **k):
        seen["prompt"] = prompt
        return json.dumps({"answer": "500tr.", "citations": []})

    monkeypatch.setattr(brain.llm, "chat", capture)
    brain.ask("ngân sách bao nhiêu?")   # unrelated to the launch-date contradiction
    assert "### ⚠ MÂU THUẪN ĐÃ GHI NHẬN" not in seen["prompt"]


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


# ---------------------------------------------------------------- quality: contradictions

def test_detect_contradictions_skips_speculative_types(monkeypatch):
    """Assumptions/risks must not trigger contradiction detection (no LLM call)."""
    m1 = db.save_meeting(_report(title="Họp 1", date="2026-06-01", transcript="t1"))
    db.save_facts(m1, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr")])
    m2 = db.save_meeting(_report(title="Họp 2", date="2026-06-08", transcript="t2"))
    nf = KnowledgeFact(type="giả định", subject="ngân sách",
                       statement="có thể lên 1 tỷ", source_meeting_id=m2)
    db.save_facts(m2, [nf])

    def boom(prompt, model, **k):
        raise AssertionError("LLM must not be called for a speculative fact")

    monkeypatch.setattr(brain.llm, "chat", boom)
    assert brain.detect_contradictions([nf]) == []
    assert db.counts()["contradictions"] == 0


def test_ingest_skips_contradiction_for_different_pilot_milestones(monkeypatch):
    """Selecting merchants for a pilot and running the pilot are different milestones,
    so their dates should not be surfaced as a contradiction."""
    monkeypatch.setattr(brain.analyze, "analyze",
                        lambda transcript, date: _report(date=date, transcript=transcript))

    def fake_extract(_report_obj, transcript):
        if "1/6" in transcript:
            return [KnowledgeFact(type="số liệu", subject="ngày pilot Merchant",
                                  statement="Ngày pilot Merchant là 1/6/2026")]
        return [KnowledgeFact(type="số liệu", subject="ngày chọn merchant pilot",
                              statement="Ngày chọn merchant pilot là 15/5/2026")]

    def fake_chat(prompt, model, **k):
        return json.dumps({"conflicts": [
            {"index": 0,
             "explanation": "Trước: ngày pilot Merchant là 1/6/2026 → Nay: ngày chọn merchant pilot là 15/5/2026",
             "severity": "trung bình"}
        ]})

    monkeypatch.setattr(brain, "extract_facts", fake_extract)
    monkeypatch.setattr(brain.llm, "chat", fake_chat)

    brain.ingest(text="Chốt ngày pilot Merchant là 1/6/2026", date="2026-05-01", title="Kế hoạch pilot")
    out = brain.ingest(text="Ngày chọn merchant pilot là 15/5/2026", date="2026-05-10", title="Chuẩn bị pilot")

    assert out["contradictions"] == []
    assert db.counts()["contradictions"] == 0


def test_detect_contradictions_dedupes_one_row_per_new_fact(monkeypatch):
    """A new value conflicting with several prior values of the same subject yields
    ONE surfaced contradiction, but supersedes every prior value."""
    m1 = db.save_meeting(_report(title="H1", date="2026-06-01", transcript="t1"))
    db.save_facts(m1, [KnowledgeFact(type="quyết định", subject="ngày launch", statement="30/6")])
    m2 = db.save_meeting(_report(title="H2", date="2026-06-05", transcript="t2"))
    db.save_facts(m2, [KnowledgeFact(type="quyết định", subject="ngày launch", statement="12/7")])
    m3 = db.save_meeting(_report(title="H3", date="2026-06-10", transcript="t3"))
    nf = KnowledgeFact(type="quyết định", subject="ngày launch", statement="18/7", source_meeting_id=m3)
    db.save_facts(m3, [nf])

    # one batched call lists both prior values -> both indices conflict
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"conflicts": [
            {"index": 0, "explanation": "đổi ngày launch", "severity": "trung bình"},
            {"index": 1, "explanation": "đổi ngày launch", "severity": "trung bình"}]}))
    found = brain.detect_contradictions([nf])
    assert len(found) == 1                       # one surfaced row, not two
    assert db.counts()["contradictions"] == 1
    # both prior values superseded; only the new value stays active
    actives = db.facts_by_subject("ngày launch", status="hiệu lực")
    assert [f.statement for f in actives] == ["18/7"]


def test_detect_contradictions_is_one_call_per_new_fact(monkeypatch):
    """Batching: 1 new fact with N same-subject candidates => exactly ONE LLM call
    (not N). Guards against regressing to per-pair calls."""
    m1 = db.save_meeting(_report(title="H1", date="2026-06-01", transcript="t1"))
    db.save_facts(m1, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="100tr")])
    m2 = db.save_meeting(_report(title="H2", date="2026-06-03", transcript="t2"))
    db.save_facts(m2, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="200tr")])
    m3 = db.save_meeting(_report(title="H3", date="2026-06-05", transcript="t3"))
    db.save_facts(m3, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="300tr")])
    m4 = db.save_meeting(_report(title="H4", date="2026-06-10", transcript="t4"))
    nf = KnowledgeFact(type="số liệu", subject="ngân sách", statement="999tr", source_meeting_id=m4)
    db.save_facts(m4, [nf])

    calls = {"n": 0}

    def counting_chat(prompt, model, **k):
        calls["n"] += 1
        return json.dumps({"conflicts": []})   # no conflict, just count the call

    monkeypatch.setattr(brain.llm, "chat", counting_chat)
    brain.detect_contradictions([nf])
    assert calls["n"] == 1                        # 3 candidates, still one batched call


def test_detect_contradictions_skips_duplicate_meeting_source(monkeypatch):
    """Re-ingesting the same source file/date should not create contradictions between
    a detailed fact and a date-only fact extracted from the duplicate."""
    m1 = db.save_meeting(_report(title="Bản 1", date="2026-05-01", transcript="t1"),
                         source_file="meeting.mp3", dedup=False)
    db.save_facts(m1, [KnowledgeFact(
        type="cam kết",
        subject="ngày cung cấp tài liệu kỹ thuật",
        statement="Tech cung cấp tài liệu trước ngày 24/05/2026",
    )])
    m2 = db.save_meeting(_report(title="Bản 2", date="2026-05-01", transcript="t2"),
                         source_file="meeting.mp3", dedup=False)
    nf = KnowledgeFact(type="số liệu", subject="ngày cung cấp tài liệu kỹ thuật",
                       statement="24/05/2026", source_meeting_id=m2)
    db.save_facts(m2, [nf])

    def boom(prompt, model, **k):
        raise AssertionError("Duplicate source meetings must not reach LLM contradiction detection")

    monkeypatch.setattr(brain.llm, "chat", boom)
    assert brain.detect_contradictions([nf]) == []
    assert db.counts()["contradictions"] == 0


def test_detect_contradictions_discards_verdict_that_says_not_contradiction(monkeypatch):
    m1 = db.save_meeting(_report(title="H1", date="2026-06-01", transcript="t1"))
    db.save_facts(m1, [KnowledgeFact(type="số liệu", subject="test case regression",
                                     statement="QA hoàn tất regression ngày 20/05/2026")])
    m2 = db.save_meeting(_report(title="H2", date="2026-06-02", transcript="t2"))
    nf = KnowledgeFact(type="số liệu", subject="test case regression",
                       statement="Còn 12 test case chưa chạy xong", source_meeting_id=m2)
    db.save_facts(m2, [nf])

    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"conflicts": [{"index": 0,
                        "explanation": "Không mâu thuẫn: một câu nói kế hoạch tương lai, một câu nói trạng thái hiện tại.",
                        "severity": "thấp"}]}))

    assert brain.detect_contradictions([nf]) == []
    assert db.counts()["contradictions"] == 0


# ---------------------------------------------------------------- quality: follow_up overdue

def test_follow_up_marks_overdue_when_deadline_passed():
    """A past ISO deadline with no later meeting flips the action to 'quá hạn' (no LLM)."""
    db.save_meeting(_report(title="Họp 1", date="2026-06-01",
                            actions=[ActionItem(task="Nộp báo cáo", deadline="2026-06-05")],
                            transcript="t1"))
    res = brain.follow_up()   # today (2026-06-15) > 2026-06-05
    assert res and res[0]["status"] == "quá hạn"
    assert db.all_actions()[0].status == "quá hạn"


def test_follow_up_overdue_overrides_model(monkeypatch):
    db.save_meeting(_report(title="Họp 1", date="2026-06-01",
                            actions=[ActionItem(task="Viết spec", deadline="2026-06-05")],
                            transcript="t1"))
    db.save_meeting(_report(title="Họp 2", date="2026-06-08", summary="bàn việc khác",
                            transcript="t2"))
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"status": "mở", "note": "chưa nhắc lại", "related_meeting_id": None}))
    res = brain.follow_up()
    assert res[0]["status"] == "quá hạn"   # deterministic overdue beats the model's "mở"


def test_follow_up_ignores_hallucinated_related_meeting(monkeypatch):
    db.save_meeting(_report(title="Họp 1", date="2026-06-01",
                            actions=[ActionItem(task="Viết spec")], transcript="t1"))
    db.save_meeting(_report(title="Họp 2", date="2026-06-08", transcript="t2"))
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"status": "đang làm", "note": "n", "related_meeting_id": 9999}))
    brain.follow_up()
    with db.SessionLocal() as s:
        assert s.scalar(db.select(db.func.count(db.ActionLink.id))) == 0


# ---------------------------------------------------------------- quality: Q&A citations

def test_ask_drops_invalid_and_duplicate_citations(monkeypatch):
    mid = db.save_meeting(_report(title="Họp ngân sách", date="2026-06-01", transcript="t"))
    db.save_facts(mid, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr")])
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps({
        "answer": "500tr.",
        "citations": [
            {"meeting_id": mid, "quote": "ngân sách 500tr"},
            {"meeting_id": 9999, "quote": "ảo"},                 # invalid id -> dropped
            {"meeting_id": mid, "quote": "ngân sách 500tr"},     # duplicate -> dropped
        ],
    }))
    ans = brain.ask("ngân sách bao nhiêu")
    assert len(ans.citations) == 1
    assert ans.citations[0].meeting_id == mid


def test_ask_empty_answer_falls_back(monkeypatch):
    db.save_meeting(_report(title="Họp", date="2026-06-01", transcript="t"))
    monkeypatch.setattr(brain.llm, "chat", lambda prompt, model, **k: json.dumps(
        {"answer": "  ", "citations": []}))
    ans = brain.ask("câu hỏi gì đó")
    assert "Chưa từng được đề cập" in ans.text
