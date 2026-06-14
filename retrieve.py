"""Retrieval seam for the memory layer.

v1 is keyword overlap over the full history (no vector DB) — enough for the demo
scale of dozens of meetings. The contract (`retrieve(query) -> RetrievedContext`)
is the upgrade seam: v2 swaps the body for embeddings + vector search WITHOUT
changing callers in brain.py.

Always considers the FULL history and returns facts in timeline order, so recall
("đã đề cập ở cuộc họp nào") and reasoning get a chronological view.
"""
import re
from dataclasses import dataclass, field

import db

# Vietnamese stopwords kept tiny on purpose — just the noisy connectors that hurt overlap.
_STOP = {
    "là", "và", "của", "có", "cho", "các", "những", "được", "một", "này", "đó", "khi",
    "thì", "ở", "đã", "sẽ", "với", "về", "trong", "ra", "đi", "rồi", "không", "gì",
    "the", "a", "an", "of", "to", "is", "are", "what", "how",
}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"\w+", (text or "").lower()) if t not in _STOP and len(t) > 1}


@dataclass
class RetrievedContext:
    meetings: list = field(default_factory=list)   # db.Meeting rows (summaries)
    facts: list = field(default_factory=list)      # db.Fact rows, timeline order

    def is_empty(self) -> bool:
        return not self.meetings and not self.facts


def _score(query_tokens: set[str], *texts: str) -> int:
    if not query_tokens:
        return 1  # empty/broad query: keep everything
    hay = set()
    for t in texts:
        hay |= _tokens(t)
    return len(query_tokens & hay)


def retrieve(query: str, limit: int = 50, recent_fallback: int = 20) -> RetrievedContext:
    """Return meetings + facts relevant to `query`, full history, timeline-sorted.

    If nothing matches the keywords, fall back to the most recent slice so the LLM
    still has grounding (and can correctly answer "chưa từng đề cập").
    """
    qt = _tokens(query)
    facts = db.all_facts(limit=10000)          # oldest -> newest
    meetings = db.list_meetings(limit=10000)   # newest -> oldest

    scored_facts = [(f, _score(qt, f.subject, f.statement, f.quote or "")) for f in facts]
    scored_meets = [(m, _score(qt, m.title, m.summary)) for m in meetings]

    hit_facts = [f for f, s in scored_facts if s > 0]
    hit_meets = [m for m, s in scored_meets if s > 0]

    if not hit_facts and not hit_meets:
        # no keyword hit -> recent grounding so the model can say "not mentioned"
        hit_facts = facts[-recent_fallback:]
        hit_meets = meetings[:recent_fallback]

    hit_facts = hit_facts[:limit]
    # meetings back to chronological (oldest first) for timeline narration
    hit_meets = sorted(hit_meets[:limit], key=lambda m: (m.date or "", m.id or 0))
    return RetrievedContext(meetings=hit_meets, facts=hit_facts)
