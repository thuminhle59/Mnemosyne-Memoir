"""Tests for the keyword retrieval seam: diacritic-insensitive matching and
relevance-ranked capping (the most relevant facts must survive a small limit)."""
import db
import retrieve as retrieve_mod
from models import MeetingReport, KnowledgeFact


def _report(title="Họp", date="2026-06-01", transcript="t"):
    return MeetingReport(title=title, date=date, summary=title, full_transcript=transcript)


def test_tokens_are_diacritic_insensitive():
    assert retrieve_mod._tokens("Ngân Sách") == retrieve_mod._tokens("ngan sach")
    # đ folds to d
    assert "dong" in retrieve_mod._tokens("đồng")


def test_retrieve_matches_query_without_diacritics():
    m = db.save_meeting(_report(title="Họp ngân sách"))
    db.save_facts(m, [KnowledgeFact(type="số liệu", subject="ngân sách", statement="500tr")])
    ctx = retrieve_mod.retrieve("ngan sach bao nhieu")   # user typed no accents
    assert "ngân sách" in [f.subject for f in ctx.facts]


def test_retrieve_ranks_relevant_facts_above_cap():
    """With more matches than the limit, the on-topic fact must not be dropped just
    because it is chronologically early."""
    m = db.save_meeting(_report(title="Họp"))
    facts = [KnowledgeFact(type="fact", subject="ngân sách", statement="ngân sách Q3 là 500tr")]
    # add filler facts that only weakly match ("Q3") and were created later
    for i in range(10):
        facts.append(KnowledgeFact(type="fact", subject=f"việc {i}", statement="Q3 linh tinh"))
    db.save_facts(m, facts)
    ctx = retrieve_mod.retrieve("ngân sách Q3", limit=3)
    subjects = [f.subject for f in ctx.facts]
    assert len(subjects) <= 3
    assert "ngân sách" in subjects        # strongest match kept despite the cap


def test_retrieve_results_stay_timeline_ordered():
    m1 = db.save_meeting(_report(title="A", date="2026-06-01"))
    m2 = db.save_meeting(_report(title="B", date="2026-06-09"))
    db.save_facts(m1, [KnowledgeFact(type="fact", subject="ngân sách", statement="cũ")])
    db.save_facts(m2, [KnowledgeFact(type="fact", subject="ngân sách", statement="mới")])
    ctx = retrieve_mod.retrieve("ngân sách", limit=50)
    # facts returned oldest -> newest for timeline narration
    ids = [f.id for f in ctx.facts]
    assert ids == sorted(ids)
