"""Memory store (SQLAlchemy) — the organizational memory behind Mnemosyne.

Portable between local SQLite (demo) and a managed DB via DATABASE_URL. Five tables:
  meetings        — one row per ingested meeting (full MeetingReport JSON + transcript)
  action_items    — denormalized from the report so the dashboard/follow-up are cheap
  action_links    — trace where an old action was re-mentioned across meetings
  knowledge_facts — accumulating atomic facts; the unit reasoning operates on
  contradictions  — conflicting fact pairs detected at ingest

Pattern follows zalopay-promo-agent/db.py: declarative_base, content_hash dedup,
light create-or-migrate init. LLM types live in models.py; this module persists them.
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey, select, func,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL
from models import MeetingReport, KnowledgeFact, Contradiction

Base = declarative_base()

# SQLite needs check_same_thread=False for Streamlit's multi-threading.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(512))
    date = Column(String(32), index=True)
    duration_min = Column(Integer, nullable=True)
    summary = Column(Text)
    report_json = Column(Text)            # full MeetingReport.model_dump_json()
    transcript = Column(Text)
    duration_sec = Column(Integer, nullable=True)    # audio length, for ≈timestamps
    source_file = Column(String(512), nullable=True) # uploaded file name
    audio_hash = Column(String(64), index=True, nullable=True)  # same-file detection
    content_hash = Column(String(64), index=True)    # dedup re-ingest (not unique: allow "save as new")
    created_at = Column(DateTime)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "date": self.date,
            "duration_min": self.duration_min, "summary": self.summary,
            "source_file": self.source_file, "created_at": self.created_at,
        }

    def report(self) -> MeetingReport:
        return MeetingReport.model_validate_json(self.report_json)


class Action(Base):
    __tablename__ = "action_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    task = Column(Text)
    owner = Column(String(128), index=True)
    deadline = Column(String(64))
    priority = Column(String(16))
    status = Column(String(16), default="mở", index=True)
    quote = Column(Text)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "meeting_id": self.meeting_id, "task": self.task,
            "owner": self.owner, "deadline": self.deadline, "priority": self.priority,
            "status": self.status,
        }


class ActionLink(Base):
    __tablename__ = "action_links"
    id = Column(Integer, primary_key=True, autoincrement=True)
    action_id = Column(Integer, ForeignKey("action_items.id"), index=True)
    related_meeting_id = Column(Integer, ForeignKey("meetings.id"))
    note = Column(Text)


class Fact(Base):
    __tablename__ = "knowledge_facts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), index=True)
    type = Column(String(32))
    subject = Column(String(256), index=True)
    statement = Column(Text)
    quote = Column(Text)
    status = Column(String(16), default="hiệu lực", index=True)
    created_at = Column(DateTime)

    def to_model(self) -> KnowledgeFact:
        return KnowledgeFact(
            type=self.type, subject=self.subject, statement=self.statement,
            quote=self.quote, status=self.status, source_meeting_id=self.meeting_id,
        )

    def as_dict(self) -> dict:
        return {
            "id": self.id, "meeting_id": self.meeting_id, "type": self.type,
            "subject": self.subject, "statement": self.statement,
            "quote": self.quote, "status": self.status,
        }


class ContradictionRow(Base):
    __tablename__ = "contradictions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    fact_a_id = Column(Integer, ForeignKey("knowledge_facts.id"))
    fact_b_id = Column(Integer, ForeignKey("knowledge_facts.id"))
    subject = Column(String(256), index=True)
    explanation = Column(Text)
    severity = Column(String(16))
    detected_at = Column(DateTime)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "subject": self.subject, "explanation": self.explanation,
            "severity": self.severity, "fact_a_id": self.fact_a_id, "fact_b_id": self.fact_b_id,
        }


class Resurfaced(Base):
    """A decision/topic that was rejected or raised-then-dropped in an older meeting
    and is being brought up again now (Forgotten Decision Detector)."""
    __tablename__ = "resurfaced"
    id = Column(Integer, primary_key=True, autoincrement=True)
    subject = Column(String(256), index=True)
    kind = Column(String(16))                 # "rejected" | "forgotten"
    explanation = Column(Text)
    old_fact_id = Column(Integer, ForeignKey("knowledge_facts.id"))   # prior mention
    new_fact_id = Column(Integer, ForeignKey("knowledge_facts.id"))   # current mention
    detected_at = Column(DateTime)

    def as_dict(self) -> dict:
        return {"id": self.id, "subject": self.subject, "kind": self.kind,
                "explanation": self.explanation, "old_fact_id": self.old_fact_id,
                "new_fact_id": self.new_fact_id}


class Glossary(Base):
    """Org/team/project terminology learned from a 'training guide'.
    - term-only row (wrong=NULL): a canonical proper noun for the STT LLM glossary.
    - mapping row (wrong set): a known mis-hearing -> correct term (deterministic regex fix).
    """
    __tablename__ = "glossary"
    id = Column(Integer, primary_key=True, autoincrement=True)
    wrong = Column(String(256), nullable=True)   # mis-heard form (optional)
    term = Column(String(256))                    # canonical/correct term
    created_at = Column(DateTime)

    def as_dict(self) -> dict:
        return {"id": self.id, "wrong": self.wrong, "term": self.term}


def init_db() -> None:
    Base.metadata.create_all(engine)
    # light migration: add new columns to a pre-existing meetings table
    from sqlalchemy import inspect, text as _sql
    cols = [c["name"] for c in inspect(engine).get_columns("meetings")]
    add = {
        "duration_sec": "INTEGER",
        "source_file": "VARCHAR(512)",
        "audio_hash": "VARCHAR(64)",
    }
    with engine.begin() as conn:
        for name, sqltype in add.items():
            if name not in cols:
                conn.execute(_sql(f"ALTER TABLE meetings ADD COLUMN {name} {sqltype}"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_hash(title: str, date: str, transcript: str, salt: str = "") -> str:
    raw = f"{title}|{date}|{transcript}|{salt}".lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audio_hash(data: bytes) -> str:
    """Stable hash of the uploaded audio bytes — to detect the same file re-uploaded."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- writes

def save_meeting(report: MeetingReport, transcript: str = "", duration_sec: int | None = None,
                 source_file: str | None = None, audio_hash_val: str | None = None,
                 dedup: bool = True, dedup_salt: str = "") -> int:
    """Persist a meeting + its action items. With dedup=True, identical content
    (same title+date+transcript) returns the existing id. Pass dedup=False or a
    dedup_salt to force a separate row ('save as new')."""
    transcript = transcript or report.full_transcript
    h = make_hash(report.title, report.date, transcript, salt=dedup_salt)
    with SessionLocal() as s:
        if dedup:
            existing = s.scalar(select(Meeting.id).where(Meeting.content_hash == h))
            if existing:
                return existing
        m = Meeting(
            title=report.title, date=report.date, duration_min=report.duration_min,
            summary=report.summary, report_json=report.model_dump_json(),
            transcript=transcript, duration_sec=duration_sec, source_file=source_file,
            audio_hash=audio_hash_val, content_hash=h, created_at=_now(),
        )
        s.add(m)
        s.flush()  # assign m.id
        for ai in report.action_items:
            s.add(Action(
                meeting_id=m.id, task=ai.task, owner=ai.owner, deadline=ai.deadline,
                priority=ai.priority, status=ai.status, quote=ai.quote,
            ))
        s.commit()
        return m.id


def find_by_audio_hash(h: str) -> Meeting | None:
    with SessionLocal() as s:
        return s.scalar(select(Meeting).where(Meeting.audio_hash == h))


def delete_meeting(meeting_id: int) -> None:
    """Remove a meeting and everything derived from it (facts, actions, links,
    and contradictions referencing its facts)."""
    with SessionLocal() as s:
        fact_ids = list(s.scalars(select(Fact.id).where(Fact.meeting_id == meeting_id)))
        action_ids = list(s.scalars(select(Action.id).where(Action.meeting_id == meeting_id)))
        if fact_ids:
            s.query(ContradictionRow).filter(
                (ContradictionRow.fact_a_id.in_(fact_ids)) | (ContradictionRow.fact_b_id.in_(fact_ids))
            ).delete(synchronize_session=False)
            s.query(Resurfaced).filter(
                (Resurfaced.old_fact_id.in_(fact_ids)) | (Resurfaced.new_fact_id.in_(fact_ids))
            ).delete(synchronize_session=False)
        if action_ids:
            s.query(ActionLink).filter(ActionLink.action_id.in_(action_ids)).delete(synchronize_session=False)
        s.query(ActionLink).filter(ActionLink.related_meeting_id == meeting_id).delete(synchronize_session=False)
        s.query(Fact).filter(Fact.meeting_id == meeting_id).delete(synchronize_session=False)
        s.query(Action).filter(Action.meeting_id == meeting_id).delete(synchronize_session=False)
        s.query(Meeting).filter(Meeting.id == meeting_id).delete(synchronize_session=False)
        s.commit()


def update_transcript(meeting_id: int, transcript: str) -> None:
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        if m:
            m.transcript = transcript
            s.commit()


def update_report(meeting_id: int, report: MeetingReport) -> None:
    """Replace a meeting's analysis (summary/report_json) and rebuild its action_items."""
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        if not m:
            return
        m.summary = report.summary
        m.report_json = report.model_dump_json()
        s.query(Action).filter(Action.meeting_id == meeting_id).delete(synchronize_session=False)
        for ai in report.action_items:
            s.add(Action(
                meeting_id=meeting_id, task=ai.task, owner=ai.owner, deadline=ai.deadline,
                priority=ai.priority, status=ai.status, quote=ai.quote,
            ))
        s.commit()


def clear_facts(meeting_id: int) -> None:
    """Delete a meeting's facts and any contradictions referencing them (for reanalyze)."""
    with SessionLocal() as s:
        fact_ids = list(s.scalars(select(Fact.id).where(Fact.meeting_id == meeting_id)))
        if fact_ids:
            s.query(ContradictionRow).filter(
                (ContradictionRow.fact_a_id.in_(fact_ids)) | (ContradictionRow.fact_b_id.in_(fact_ids))
            ).delete(synchronize_session=False)
            s.query(Resurfaced).filter(
                (Resurfaced.old_fact_id.in_(fact_ids)) | (Resurfaced.new_fact_id.in_(fact_ids))
            ).delete(synchronize_session=False)
        s.query(Fact).filter(Fact.meeting_id == meeting_id).delete(synchronize_session=False)
        s.commit()


def save_facts(meeting_id: int, facts: list[KnowledgeFact]) -> list[int]:
    ids = []
    with SessionLocal() as s:
        for f in facts:
            row = Fact(
                meeting_id=meeting_id, type=f.type, subject=f.subject,
                statement=f.statement, quote=f.quote, status=f.status, created_at=_now(),
            )
            s.add(row)
            s.flush()
            ids.append(row.id)
        s.commit()
    return ids


def save_contradiction(c: Contradiction) -> int:
    with SessionLocal() as s:
        row = ContradictionRow(
            fact_a_id=c.fact_a_id, fact_b_id=c.fact_b_id, subject=c.subject,
            explanation=c.explanation, severity=c.severity, detected_at=_now(),
        )
        s.add(row)
        s.commit()
        return row.id


def set_fact_status(fact_id: int, status: str) -> None:
    with SessionLocal() as s:
        row = s.get(Fact, fact_id)
        if row:
            row.status = status
            s.commit()


def update_action_status(action_id: int, status: str) -> None:
    with SessionLocal() as s:
        row = s.get(Action, action_id)
        if row:
            row.status = status
            s.commit()


def add_action_link(action_id: int, related_meeting_id: int, note: str = "") -> int:
    with SessionLocal() as s:
        row = ActionLink(action_id=action_id, related_meeting_id=related_meeting_id, note=note)
        s.add(row)
        s.commit()
        return row.id


# ---------------------------------------------------------------- reads

def list_meetings(limit: int = 100) -> list[Meeting]:
    with SessionLocal() as s:
        return list(s.scalars(
            select(Meeting).order_by(Meeting.date.desc(), Meeting.id.desc()).limit(limit)
        ))


def get_meeting(meeting_id: int) -> Meeting | None:
    with SessionLocal() as s:
        return s.get(Meeting, meeting_id)


def get_fact(fact_id: int) -> Fact | None:
    with SessionLocal() as s:
        return s.get(Fact, fact_id)


def facts_of_meeting(meeting_id: int) -> list[Fact]:
    with SessionLocal() as s:
        return list(s.scalars(
            select(Fact).where(Fact.meeting_id == meeting_id).order_by(Fact.id.asc())
        ))


def all_facts(limit: int = 1000) -> list[Fact]:
    """Full-history facts, oldest first (timeline order for recall/reasoning)."""
    with SessionLocal() as s:
        return list(s.scalars(
            select(Fact).order_by(Fact.created_at.asc(), Fact.id.asc()).limit(limit)
        ))


def facts_by_subject(subject: str, status: str | None = None) -> list[Fact]:
    with SessionLocal() as s:
        q = select(Fact).where(func.lower(Fact.subject) == subject.lower())
        if status:
            q = q.where(Fact.status == status)
        return list(s.scalars(q.order_by(Fact.created_at.asc(), Fact.id.asc())))


def all_actions(status: str | None = None) -> list[Action]:
    with SessionLocal() as s:
        q = select(Action)
        if status:
            q = q.where(Action.status == status)
        return list(s.scalars(q.order_by(Action.owner, Action.id)))


def all_contradictions() -> list[ContradictionRow]:
    with SessionLocal() as s:
        return list(s.scalars(
            select(ContradictionRow).order_by(ContradictionRow.detected_at.desc())
        ))


def save_resurfaced(subject: str, kind: str, explanation: str,
                    old_fact_id: int | None, new_fact_id: int | None) -> int:
    with SessionLocal() as s:
        row = Resurfaced(subject=subject, kind=kind, explanation=explanation,
                         old_fact_id=old_fact_id, new_fact_id=new_fact_id, detected_at=_now())
        s.add(row)
        s.commit()
        return row.id


def all_resurfaced() -> list[Resurfaced]:
    with SessionLocal() as s:
        return list(s.scalars(select(Resurfaced).order_by(Resurfaced.detected_at.desc())))


def clear_resurfaced() -> None:
    with SessionLocal() as s:
        s.query(Resurfaced).delete(synchronize_session=False)
        s.commit()


# ---------------------------------------------------------------- glossary

def add_glossary(term: str, wrong: str | None = None) -> int:
    term = (term or "").strip()
    wrong = (wrong or "").strip() or None
    if not term:
        return 0
    with SessionLocal() as s:
        # avoid exact duplicates
        exists = s.scalar(select(Glossary.id).where(
            func.lower(Glossary.term) == term.lower(),
            (func.lower(Glossary.wrong) == wrong.lower()) if wrong else Glossary.wrong.is_(None),
        ))
        if exists:
            return exists
        row = Glossary(term=term, wrong=wrong, created_at=_now())
        s.add(row)
        s.commit()
        return row.id


def list_glossary() -> list[Glossary]:
    with SessionLocal() as s:
        return list(s.scalars(select(Glossary).order_by(Glossary.id.asc())))


def delete_glossary(gid: int) -> None:
    with SessionLocal() as s:
        s.query(Glossary).filter(Glossary.id == gid).delete(synchronize_session=False)
        s.commit()


def glossary_terms() -> list[str]:
    return [g.term for g in list_glossary()]


def glossary_fixes() -> list[tuple[str, str]]:
    return [(g.wrong, g.term) for g in list_glossary() if g.wrong]


def counts() -> dict:
    with SessionLocal() as s:
        return {
            "meetings": s.scalar(select(func.count(Meeting.id))) or 0,
            "facts": s.scalar(select(func.count(Fact.id))) or 0,
            "actions": s.scalar(select(func.count(Action.id))) or 0,
            "contradictions": s.scalar(select(func.count(ContradictionRow.id))) or 0,
            "resurfaced": s.scalar(select(func.count(Resurfaced.id))) or 0,
        }
