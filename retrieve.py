"""Retrieval seam for the memory layer.

v1 is keyword overlap over the full history (no vector DB) — enough for the demo
scale of dozens of meetings. The contract (`retrieve(query) -> RetrievedContext`)
is the upgrade seam: v2 swaps the body for embeddings + vector search WITHOUT
changing callers in brain.py.

Always considers the FULL history and returns facts in timeline order, so recall
("đã đề cập ở cuộc họp nào") and reasoning get a chronological view.
"""
import re
import unicodedata
from dataclasses import dataclass, field

import db

# Vietnamese stopwords kept tiny on purpose — just the noisy connectors that hurt overlap.
# Stored WITHOUT diacritics because tokens are diacritic-stripped before the membership test.
_STOP = {
    "la", "va", "cua", "co", "cho", "cac", "nhung", "duoc", "mot", "nay", "do", "khi",
    "thi", "o", "da", "se", "voi", "ve", "trong", "ra", "di", "roi", "khong", "gi",
    "the", "a", "an", "of", "to", "is", "are", "what", "how",
}


def _strip_diacritics(text: str) -> str:
    """Fold Vietnamese diacritics so 'ngân sách' and 'ngan sach' match.

    NFD splits base letters from combining marks; we drop the marks and map đ/Đ
    (which has no combining-mark decomposition) to d. Matching only — display text
    keeps its accents because callers read from the original db rows, not these tokens.
    """
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def _tokens(text: str) -> set[str]:
    folded = _strip_diacritics((text or "").lower())
    return {t for t in re.findall(r"\w+", folded) if t not in _STOP and len(t) > 1}


@dataclass
class RetrievedContext:
    meetings: list = field(default_factory=list)   # db.Meeting rows (summaries)
    facts: list = field(default_factory=list)      # db.Fact rows, timeline order

    def is_empty(self) -> bool:
        return not self.meetings and not self.facts


def _score(query_tokens: set[str], subject: str = "", *texts: str) -> int:
    """Keyword overlap with a subject boost: a hit in `subject` (the cross-meeting
    join key) counts double so the most on-topic facts rank above passing mentions."""
    if not query_tokens:
        return 1  # empty/broad query: keep everything
    subj = query_tokens & _tokens(subject)
    body = set()
    for t in texts:
        body |= _tokens(t)
    return 2 * len(subj) + len(query_tokens & body)


def retrieve(query: str, limit: int = 50, recent_fallback: int = 20) -> RetrievedContext:
    """Return meetings + facts relevant to `query`, full history, timeline-sorted.

    Hits are ranked by relevance, capped at `limit`, then restored to timeline order
    for narration — so when more than `limit` facts match, it's the most relevant ones
    that survive the cap (not an arbitrary chronological slice).

    If nothing matches the keywords, fall back to the most recent slice so the LLM
    still has grounding (and can correctly answer "chưa từng đề cập").
    """
    qt = _tokens(query)
    facts = db.all_facts(limit=10000)          # oldest -> newest
    meetings = db.list_meetings(limit=10000)   # newest -> oldest

    # keep original index as a stable tiebreaker + to restore timeline order after ranking
    scored_facts = [(i, f, _score(qt, f.subject, f.statement, f.quote or ""))
                    for i, f in enumerate(facts)]
    scored_meets = [(m, _score(qt, m.title, m.summary)) for m in meetings]

    hit_facts = [(i, f) for i, f, s in scored_facts if s > 0]
    hit_meets = [m for m, s in scored_meets if s > 0]

    if not hit_facts and not hit_meets:
        # no keyword hit -> recent grounding so the model can say "not mentioned"
        hit_facts = list(enumerate(facts))[-recent_fallback:]
        hit_meets = meetings[:recent_fallback]
        ranked_facts = [f for _, f in hit_facts]
    else:
        # rank by score desc (then chronological), cap, then restore timeline order
        by_score = sorted(((i, f, s) for i, f, s in scored_facts if s > 0),
                          key=lambda t: (-t[2], t[0]))[:limit]
        ranked_facts = [f for i, f in sorted(((i, f) for i, f, _ in by_score),
                                             key=lambda t: t[0])]

    # meetings back to chronological (oldest first) for timeline narration
    hit_meets = sorted(hit_meets[:limit], key=lambda m: (m.date or "", m.id or 0))
    return RetrievedContext(meetings=hit_meets, facts=ranked_facts)
