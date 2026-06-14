"""Pydantic schemas — the LLM output contracts and memory-layer units.

Meeting Ghost types (Decision, ActionItem, MeetingReport) are kept; the memory
layer adds KnowledgeFact and Contradiction. All are plain data validated from LLM
JSON, so they stay decoupled from the SQLAlchemy rows in db.py.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

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


class MeetingReport(BaseModel):
    title: str
    date: str
    duration_min: Optional[int] = None
    summary: str
    key_points: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_meeting: Optional[str] = None
    full_transcript: str = ""


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
