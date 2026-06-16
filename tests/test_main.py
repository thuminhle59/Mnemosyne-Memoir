"""End-to-end: main.process routing + the design's acceptance scenario.

Two linked Vietnamese meetings where the launch date changes (30/6 -> 15/7):
ingest both -> contradiction detected -> recall Q&A answers with citations.
LLM is mocked with a prompt router so the flow is deterministic.
"""
import json

from fastapi.testclient import TestClient

import db
import main
import brain


def _router(prompt, model, **k):
    # fact extraction
    if "TRÍCH" in prompt or '"facts"' in prompt:
        stmt = "15/7" if "15/7" in prompt else "30/6"
        return json.dumps({"facts": [
            {"type": "quyết định", "subject": "ngày launch", "statement": stmt,
             "quote": f"chốt {stmt}"},
        ]})
    # batched contradiction verdict (one candidate -> index 0).
    # Key on the listing header, not "MÂU THUẪN" — that word now also appears in the
    # ask-prompt rule about recorded contradictions.
    if "DANH SÁCH CŨ" in prompt:
        return json.dumps({"conflicts": [
            {"index": 0, "explanation": "30/6 vs 15/7", "severity": "cao"}]})
    # recall answer
    if "CÂU HỎI" in prompt:
        return json.dumps({
            "answer": "Ban đầu chốt 30/6, sau dời sang 15/7.",
            "citations": [{"meeting_id": 1, "quote": "chốt 30/6"},
                          {"meeting_id": 2, "quote": "chốt 15/7"}],
        })
    return "{}"


def test_e2e_two_meetings_contradiction_and_recall(monkeypatch):
    # analyze is mocked so we don't need a real summarizer; transcript drives the facts
    from models import MeetingReport

    def fake_analyze(transcript, date):
        return MeetingReport(title="Họp", date=date, summary=transcript, full_transcript=transcript)

    monkeypatch.setattr(brain.analyze, "analyze", fake_analyze)
    monkeypatch.setattr(brain.llm, "chat", _router)

    r1 = main.process({"action": "ingest", "text": "tuần 1: chốt ngày launch 30/6",
                       "date": "2026-06-02", "title": "Họp tuần 1"})
    assert r1["status"] == "success"
    r2 = main.process({"action": "ingest", "text": "tuần 2: dời ngày launch 15/7",
                       "date": "2026-06-09", "title": "Họp tuần 2"})
    assert r2["status"] == "success"
    assert len(r2["contradictions"]) == 1  # proactive detection at ingest

    # memory state
    assert db.counts()["meetings"] == 2
    assert db.counts()["contradictions"] == 1
    actives = db.facts_by_subject("ngày launch", status="hiệu lực")
    assert [f.statement for f in actives] == ["15/7"]  # latest wins

    # recall Q&A with citations
    ans = main.process({"action": "ask", "question": "ngày launch hiện tại là khi nào?"})
    assert ans["status"] == "success"
    assert "15/7" in ans["answer"]
    assert len(ans["citations"]) == 2
    assert ans["citations"][0]["meeting_title"]  # enriched from db


def test_process_unknown_action():
    out = main.process({"action": "nope"})
    assert out["status"] == "error"
    assert "unknown action" in out["message"]


def test_process_ingest_requires_input():
    out = main.process({"action": "ingest"})
    assert out["status"] == "error"


def test_agentbase_runtime_serves_web_dashboard():
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Memoir" in response.text
    assert "app.js" in response.text


def test_agentbase_runtime_exposes_frontend_api():
    client = TestClient(main.app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agentbase_runtime_keeps_invocation_contract_when_web_is_mounted():
    client = TestClient(main.app)

    health = client.get("/health")
    invocation = client.post("/invocations", json={})

    assert health.status_code == 200
    assert "status" in health.json()
    assert invocation.status_code == 200
    assert invocation.json()["status"] == "error"
    assert "ingest needs" in invocation.json()["message"]
