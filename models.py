"""Pydantic schemas — the LLM output contracts and memory-layer units.

Meeting Ghost types (Decision, ActionItem, MeetingReport) are kept; the memory
layer adds KnowledgeFact and Contradiction. All are plain data validated from LLM
JSON, so they stay decoupled from the SQLAlchemy rows in db.py.
"""
from typing import Literal, Optional
import re

from pydantic import BaseModel, Field, model_validator

Priority = Literal["cao", "trung bình", "thấp"]
ActionStatus = Literal["mở", "đang làm", "xong", "quá hạn", "treo"]
FactType = Literal["quyết định", "fact", "cam kết", "số liệu", "giả định", "rủi ro"]
FactStatus = Literal["hiệu lực", "đã thay thế", "mâu thuẫn"]
Severity = Literal["cao", "trung bình", "thấp"]


class Decision(BaseModel):
    text: str
    timestamp: Optional[str] = None  # always None in v1 (STT has no timestamps)
    quote: Optional[str] = None


class ActionItem(BaseModel):
    task: str
    owner: Optional[str] = None
    deadline: Optional[str] = None
    priority: Priority = "trung bình"
    timestamp: Optional[str] = None
    quote: Optional[str] = None
    status: ActionStatus = "mở"               # follow-up tracking across meetings
    source_meeting_id: Optional[int] = None   # provenance (set on save)


class SummaryBrief(BaseModel):
    context: Optional[str] = None
    decisions: list[str] = Field(default_factory=list)
    risk: Optional[str] = None
    next_step: Optional[str] = None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def _first_sentence(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    parts = re.split(r"(?<=[.!?。])\s+", cleaned, maxsplit=1)
    return _clean_text(parts[0])


class MeetingReport(BaseModel):
    title: str
    date: str
    duration_min: Optional[int] = None
    summary: str
    summary_brief: SummaryBrief = Field(default_factory=SummaryBrief)
    key_points: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_meeting: Optional[str] = None
    full_transcript: str = ""

    @model_validator(mode="after")
    def normalize_summary_brief(self) -> "MeetingReport":
        brief = self.summary_brief or SummaryBrief()
        context = _first_sentence(brief.context) or _first_sentence(self.summary)
        decisions = [_clean_text(item) for item in brief.decisions]
        decisions = [item for item in decisions if item][:2]
        if not decisions:
            decisions = [_clean_text(d.text) for d in self.decisions]
            decisions = [item for item in decisions if item][:2]
        risk = _first_sentence(brief.risk) or _first_sentence(self.risks[0] if self.risks else None)
        next_step = _first_sentence(brief.next_step)
        if not next_step and self.action_items:
            next_step = _first_sentence(self.action_items[0].task)
        self.summary_brief = SummaryBrief(
            context=context,
            decisions=decisions,
            risk=risk,
            next_step=next_step,
        )
        return self


class KnowledgeFact(BaseModel):
    """An atomic, normalized claim extracted from a meeting — the unit of memory
    that reasoning, recall and contradiction detection all operate on."""
    type: FactType
    subject: str            # what it is about, e.g. "ngân sách Q3", "ngày launch"
    statement: str          # normalized claim
    quote: Optional[str] = None   # original sentence as evidence
    status: FactStatus = "hiệu lực"
    source_meeting_id: Optional[int] = None


class Contradiction(BaseModel):
    """A conflict between two facts about the same subject, found at ingest."""
    subject: str
    explanation: str
    severity: Severity = "trung bình"
    fact_a_id: Optional[int] = None
    fact_b_id: Optional[int] = None


class Citation(BaseModel):
    """Provenance for a Q&A answer: which meeting + supporting quote (+ ≈timestamp)."""
    meeting_id: Optional[int] = None
    meeting_title: str = ""
    date: str = ""
    quote: str = ""
    timestamp: Optional[str] = None   # approximate mm:ss for listen-back


class Answer(BaseModel):
    """Historical-recall Q&A result with mandatory citations."""
    text: str
    citations: list[Citation] = Field(default_factory=list)


class FactList(BaseModel):
    """Wrapper so the extractor can return a single validated JSON object."""
    facts: list[KnowledgeFact] = Field(default_factory=list)
