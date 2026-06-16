"""Real-LLM quality harness for the reasoning flows (NOT a unit test — hits MaaS).

Ingests the 3-meeting Nova Merchant Portal series (deliberately seeded with two
cross-meeting contradictions, revisited decisions, and deadlined actions) into a
THROWAWAY DB, then exercises every reasoning flow and prints the output for human
inspection: contradiction detection, forgotten/resurfaced decisions, Q&A recall +
decision intelligence, action follow-up, and the executive digest.

Run:  python demo-meetings/quality_check.py
"""
import os
import sys
import tempfile

# point at a throwaway DB BEFORE importing config/db (load_dotenv won't override)
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.gettempdir(), "mnemosyne_quality.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import brain

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES = [
    ("2026-05-01", "Deploy Nova Merchant Portal — kickoff",
     "2026-05-01 deploy Nova Merchant Portal.txt"),
    ("2026-06-01", "Deploy Nova Merchant Portal — pilot review",
     "2026-06-01 deploy Nova Merchant Portal.txt"),
    ("2026-06-10", "Deploy Nova Merchant Portal — go/no-go",
     "2026-06-10 deploy Nova Merchant Portal.txt"),
]

QUESTIONS = [
    "Ngày go live đầu tiên của Auto Settlement được chốt là ngày nào, và ở dạng nào (canary hay full rollout)?",
    "Quyết định về mandatory OTP cho phase 1 đã thay đổi thế nào qua các cuộc họp?",
    "Bulk refund có nằm trong phạm vi release lần này không? Vì sao?",
    "Latency summary p95 mới nhất là bao nhiêu và có đạt tiêu chí go/no-go không?",
    "Marketing đề xuất gì về ngày deploy, và QA phản ứng ra sao?",
    "Có điều gì về kế hoạch màu xanh trên sao Hỏa được nhắc đến không?",  # negative control
]


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def main():
    db.Base.metadata.drop_all(db.engine)
    db.Base.metadata.create_all(db.engine)

    hr("INGEST (real LLM: analyze + extract_facts + contradiction + forgotten)")
    for date, title, fname in SERIES:
        text = open(os.path.join(HERE, fname), encoding="utf-8").read()
        out = brain.ingest(text=text, date=date, title=title)
        print(f"\n• {date}  {title}  (meeting_id={out['meeting_id']})")
        print(f"  facts trích: {len(out['facts'])}")
        for c in out["contradictions"]:
            print(f"  ⚠ MÂU THUẪN [{c.severity}] {c.subject}: {c.explanation}")
        for f in out["forgotten"]:
            print(f"  ↺ RESURFACED [{f['kind']}] {f['subject']}: {f['explanation']}")

    hr("CONTRADICTIONS (enriched view)")
    for c in brain.contradiction_view():
        print(f"\n[{c['severity']}] {c['subject']}\n  {c['explanation']}")
        for side in ("old", "new"):
            s = c[side]
            if s:
                print(f"  {side}: «{s['statement']}» — {s['meeting_title']} ({s['date']})"
                      + (f" ⏱≈{s['timestamp']}" if s.get('timestamp') else ""))

    hr("FORGOTTEN / RESURFACED (full rescan)")
    for r in brain.scan_forgotten():
        print(f"  [{r['kind']}] {r['subject']}: {r['explanation']}")

    hr("Q&A RECALL + DECISION INTELLIGENCE")
    for q in QUESTIONS:
        ans = brain.ask(q)
        print(f"\nQ: {q}\nA: {ans.text}")
        for c in ans.citations:
            print(f"   ↳ [{c.meeting_id}] {c.meeting_title} ({c.date})"
                  + (f" ⏱≈{c.timestamp}" if c.timestamp else "")
                  + (f"  «{c.quote}»" if c.quote else ""))

    hr("ACTION FOLLOW-UP")
    for r in brain.follow_up():
        print(f"  #{r['action_id']} [{r['status']}] {r['task']}\n       {r['note']}")

    hr("EXECUTIVE DIGEST")
    rep = brain.digest("all")
    print(f"\nTóm tắt: {rep.summary}")
    print("Quyết định lớn:")
    for d in rep.decisions:
        print(f"  - {d.text}")
    print("Rủi ro:")
    for r in rep.risks:
        print(f"  - {r}")
    print(f"Việc còn mở: {len(rep.action_items)}")


if __name__ == "__main__":
    main()
