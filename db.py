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
DEFAULT_OWNER_ID = "local-dev-user"

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
    chunk_map = Column(Text, nullable=True)          # JSON [{t0,c0,clen,dur}] for chunk-accurate ≈ts
    source_file = Column(String(512), nullable=True) # uploaded file name
    group_title = Column(String(512), nullable=True) # user-controlled sidebar folder
    owner_id = Column(String(128), index=True, nullable=True)  # simple browser/workspace owner scope
    audio_hash = Column(String(64), index=True, nullable=True)  # same-file detection
    content_hash = Column(String(64), index=True)    # dedup re-ingest (not unique: allow "save as new")
    created_at = Column(DateTime)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "date": self.date,
            "duration_min": self.duration_min, "summary": self.summary,
            "source_file": self.source_file, "group_title": self.group_title,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
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
            "status": self.status, "quote": self.quote,
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
    owner_id = Column(String(128), index=True, nullable=True)
    created_at = Column(DateTime)

    def as_dict(self) -> dict:
        return {"id": self.id, "wrong": self.wrong, "term": self.term, "owner_id": self.owner_id}


def init_db() -> None:
    Base.metadata.create_all(engine)
    # light migration: add new columns to a pre-existing meetings table
    from sqlalchemy import inspect, text as _sql
    cols = [c["name"] for c in inspect(engine).get_columns("meetings")]
    add = {
        "duration_sec": "INTEGER",
        "chunk_map": "TEXT",
        "source_file": "VARCHAR(512)",
        "group_title": "VARCHAR(512)",
        "owner_id": "VARCHAR(128)",
        "audio_hash": "VARCHAR(64)",
    }
    with engine.begin() as conn:
        for name, sqltype in add.items():
            if name not in cols:
                conn.execute(_sql(f"ALTER TABLE meetings ADD COLUMN {name} {sqltype}"))
    glossary_cols = [c["name"] for c in inspect(engine).get_columns("glossary")]
    with engine.begin() as conn:
        if "owner_id" not in glossary_cols:
            conn.execute(_sql("ALTER TABLE glossary ADD COLUMN owner_id VARCHAR(128)"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_hash(title: str, date: str, transcript: str, salt: str = "") -> str:
    raw = f"{title}|{date}|{transcript}|{salt}".lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audio_hash(data: bytes) -> str:
    """Stable hash of the uploaded audio bytes — to detect the same file re-uploaded."""
    return hashlib.sha256(data).hexdigest()


def clean_owner_id(owner_id: str | None = None) -> str:
    owner = (owner_id or DEFAULT_OWNER_ID).strip()
    return owner[:128] or DEFAULT_OWNER_ID


def derive_group_title(title: str | None = None, source_file: str | None = None) -> str:
    base = (title or source_file or "").strip()
    if not base:
        return "Ungrouped"
    for sep in (" - ", " – ", " — ", "/", ":", "|"):
        if sep in base:
            return base.split(sep, 1)[0].strip() or base
    import re
    cleaned = re.sub(r"^\d{4}[-_]\d{2}[-_]\d{2}[\s_-]*", "", base).strip()
    return cleaned or base


# ---------------------------------------------------------------- writes

def save_meeting(report: MeetingReport, transcript: str = "", duration_sec: int | None = None,
                 source_file: str | None = None, audio_hash_val: str | None = None,
                 dedup: bool = True, dedup_salt: str = "", chunk_map: str | None = None,
                 owner_id: str | None = None) -> int:
    """Persist a meeting + its action items. With dedup=True, identical content
    (same title+date+transcript) returns the existing id. Pass dedup=False or a
    dedup_salt to force a separate row ('save as new')."""
    transcript = transcript or report.full_transcript
    owner = clean_owner_id(owner_id)
    h = make_hash(report.title, report.date, transcript, salt=dedup_salt)
    with SessionLocal() as s:
        if dedup:
            existing = s.scalar(select(Meeting.id).where(Meeting.content_hash == h, Meeting.owner_id == owner))
            if existing:
                return existing
        m = Meeting(
            title=report.title, date=report.date, duration_min=report.duration_min,
            summary=report.summary, report_json=report.model_dump_json(),
            transcript=transcript, duration_sec=duration_sec, chunk_map=chunk_map,
            source_file=source_file, group_title=None, owner_id=owner,
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


def find_by_audio_hash(h: str, owner_id: str | None = None) -> Meeting | None:
    owner = clean_owner_id(owner_id)
    with SessionLocal() as s:
        return s.scalar(select(Meeting).where(Meeting.audio_hash == h, Meeting.owner_id == owner))


def delete_meeting(meeting_id: int, owner_id: str | None = None) -> bool:
    """Remove a meeting and everything derived from it (facts, actions, links,
    and contradictions referencing its facts)."""
    with SessionLocal() as s:
        owner = clean_owner_id(owner_id) if owner_id is not None else None
        m = s.get(Meeting, meeting_id)
        if not m or (owner is not None and m.owner_id != owner):
            return False
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
        return True


def update_transcript(meeting_id: int, transcript: str) -> None:
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        if m:
            m.transcript = transcript
            s.commit()


def update_meeting_metadata(
    meeting_id: int,
    title: str | None = None,
    source_file: str | None = None,
    group_title: str | None = None,
    owner_id: str | None = None,
) -> bool:
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        owner = clean_owner_id(owner_id) if owner_id is not None else None
        if not m or (owner is not None and m.owner_id != owner):
            return False
        if title is not None:
            new_title = title.strip() or m.title
            m.title = new_title
            # Keep the embedded report in sync so exports (which read report_json)
            # use the renamed title, not the original ingest title.
            if m.report_json:
                try:
                    rep = json.loads(m.report_json)
                    rep["title"] = new_title
                    m.report_json = json.dumps(rep, ensure_ascii=False)
                except (ValueError, TypeError):
                    pass
        if source_file is not None:
            m.source_file = source_file.strip() or m.source_file
        if group_title is not None:
            m.group_title = group_title.strip() or None
        s.commit()
        return True


def rename_meeting_group(old_group_title: str, new_group_title: str, owner_id: str | None = None) -> int:
    old_clean = old_group_title.strip()
    new_clean = new_group_title.strip()
    if not old_clean or not new_clean:
        return 0
    updated = 0
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        q = select(Meeting)
        if owner is not None:
            q = q.where(Meeting.owner_id == owner)
        meetings = s.scalars(q).all()
        for m in meetings:
            current = m.group_title or derive_group_title(m.title, m.source_file)
            if current == old_clean:
                m.group_title = new_clean
                updated += 1
        s.commit()
    return updated


def update_report(meeting_id: int, report: MeetingReport, owner_id: str | None = None) -> None:
    """Replace a meeting's analysis (summary/report_json) and rebuild its action_items."""
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        owner = clean_owner_id(owner_id) if owner_id is not None else None
        if not m or (owner is not None and m.owner_id != owner):
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


def update_action_status(action_id: int, status: str) -> bool:
    with SessionLocal() as s:
        row = s.get(Action, action_id)
        if row:
            row.status = status
            s.commit()
            return True
        return False


def update_action_owner(action_id: int, owner: str) -> bool:
    with SessionLocal() as s:
        row = s.get(Action, action_id)
        if row:
            row.owner = owner
            s.commit()
            return True
        return False


def get_action(action_id: int) -> Action | None:
    with SessionLocal() as s:
        return s.get(Action, action_id)


def add_action_link(action_id: int, related_meeting_id: int, note: str = "") -> int:
    with SessionLocal() as s:
        row = ActionLink(action_id=action_id, related_meeting_id=related_meeting_id, note=note)
        s.add(row)
        s.commit()
        return row.id


# ---------------------------------------------------------------- reads

def list_meetings(limit: int = 100, owner_id: str | None = None) -> list[Meeting]:
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        q = select(Meeting)
        if owner is not None:
            q = q.where(Meeting.owner_id == owner)
        return list(s.scalars(q.order_by(Meeting.date.desc(), Meeting.id.desc()).limit(limit)))


def get_meeting(meeting_id: int, owner_id: str | None = None) -> Meeting | None:
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        if owner is not None and (not m or m.owner_id != owner):
            return None
        return m


def display_id_for_meeting(meeting_id: int, owner_id: str | None = None) -> int | None:
    """User-facing meeting number scoped to an owner, independent of DB primary key."""
    with SessionLocal() as s:
        m = s.get(Meeting, meeting_id)
        if not m:
            return None
        owner = clean_owner_id(owner_id) if owner_id is not None else m.owner_id
        q = select(func.count(Meeting.id)).where(Meeting.id <= meeting_id)
        if owner:
            q = q.where(Meeting.owner_id == owner)
        return int(s.scalar(q) or 0)


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


def all_actions(status: str | None = None, owner_id: str | None = None) -> list[Action]:
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        q = select(Action)
        if owner is not None:
            q = q.join(Meeting, Action.meeting_id == Meeting.id).where(Meeting.owner_id == owner)
        if status:
            q = q.where(Action.status == status)
        return list(s.scalars(q.order_by(Action.owner, Action.id)))


def all_contradictions() -> list[ContradictionRow]:
    with SessionLocal() as s:
        return list(s.scalars(
            select(ContradictionRow).order_by(ContradictionRow.detected_at.desc())
        ))


def clear_all_contradictions() -> int:
    """Delete every contradiction row and reset all replaced facts back to hiệu lực.
    Used before a full re-detection pass."""
    with SessionLocal() as s:
        rows = list(s.scalars(select(ContradictionRow)))
        count = len(rows)
        # Collect fact ids that were marked replaced so we can restore them.
        replaced_ids = {r.fact_a_id for r in rows if r.fact_a_id}
        for row in rows:
            s.delete(row)
        # Restore superseded facts so they participate in the new pass.
        if replaced_ids:
            facts = list(s.scalars(select(Fact).where(Fact.id.in_(replaced_ids))))
            for f in facts:
                if f.status == "đã thay thế":
                    f.status = "hiệu lực"
        s.commit()
        return count


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

def add_glossary(term: str, wrong: str | None = None, owner_id: str | None = None) -> int:
    term = (term or "").strip()
    wrong = (wrong or "").strip() or None
    if not term:
        return 0
    owner = clean_owner_id(owner_id)
    with SessionLocal() as s:
        # avoid exact duplicates
        exists = s.scalar(select(Glossary.id).where(
            func.lower(Glossary.term) == term.lower(),
            (func.lower(Glossary.wrong) == wrong.lower()) if wrong else Glossary.wrong.is_(None),
            Glossary.owner_id == owner,
        ))
        if exists:
            return exists
        row = Glossary(term=term, wrong=wrong, owner_id=owner, created_at=_now())
        s.add(row)
        s.commit()
        return row.id


def list_glossary(owner_id: str | None = None) -> list[Glossary]:
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        q = select(Glossary)
        if owner is not None:
            q = q.where(Glossary.owner_id == owner)
        return list(s.scalars(q.order_by(Glossary.id.asc())))


def delete_glossary(gid: int, owner_id: str | None = None) -> bool:
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        q = s.query(Glossary).filter(Glossary.id == gid)
        if owner is not None:
            q = q.filter(Glossary.owner_id == owner)
        deleted = q.delete(synchronize_session=False)
        s.commit()
        return bool(deleted)


def glossary_terms(owner_id: str | None = None) -> list[str]:
    return [g.term for g in list_glossary(owner_id=owner_id)]


def glossary_fixes(owner_id: str | None = None) -> list[tuple[str, str]]:
    return [(g.wrong, g.term) for g in list_glossary(owner_id=owner_id) if g.wrong]


def counts(owner_id: str | None = None) -> dict:
    owner = clean_owner_id(owner_id) if owner_id is not None else None
    with SessionLocal() as s:
        if owner is None:
            meeting_count = s.scalar(select(func.count(Meeting.id))) or 0
            fact_count = s.scalar(select(func.count(Fact.id))) or 0
            action_count = s.scalar(select(func.count(Action.id))) or 0
        else:
            meeting_count = s.scalar(select(func.count(Meeting.id)).where(Meeting.owner_id == owner)) or 0
            fact_count = s.scalar(
                select(func.count(Fact.id)).join(Meeting, Fact.meeting_id == Meeting.id).where(Meeting.owner_id == owner)
            ) or 0
            action_count = s.scalar(
                select(func.count(Action.id)).join(Meeting, Action.meeting_id == Meeting.id).where(Meeting.owner_id == owner)
            ) or 0
        return {
            "meetings": meeting_count,
            "facts": fact_count,
            "actions": action_count,
            "contradictions": s.scalar(select(func.count(ContradictionRow.id))) or 0,
            "resurfaced": s.scalar(select(func.count(Resurfaced.id))) or 0,
        }
