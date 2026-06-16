"""HTTP API for Memoir — a thin FastAPI layer over brain.py.

Architecture note: this file contains NO business logic. It only maps HTTP <-> the
existing `brain` / `db` functions and returns JSON. The core (brain, db, analyze,
transcribe, media, retrieve, models) stays UI-agnostic and unchanged, so a separate
frontend (or the Streamlit viewer) can drive the exact same brain.

Run: uvicorn server:app --host 0.0.0.0 --port 8080
Frontend: static files in ./web are served at / (SPA). All data via /api/*.
"""
import base64
import json
import os
import re
import shutil
import time
import uuid
from urllib.parse import quote

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

import config  # noqa: F401 (loads .env)
import db
import brain
import media
import report as report_mod

app = FastAPI(title="Memoir API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "null",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
db.init_db()

_ROOT = os.path.dirname(os.path.abspath(__file__))
_WEB = os.path.join(_ROOT, "web")
MAX_UPLOAD_BYTES = int(os.getenv("MNEMOSYNE_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
UPLOAD_CHUNK_BYTES = int(os.getenv("MNEMOSYNE_UPLOAD_CHUNK_BYTES", str(16 * 1024 * 1024)))
UPLOAD_STAGING_DIR = os.getenv("MNEMOSYNE_UPLOAD_STAGING_DIR", "/tmp/mnemosyne_uploads")
INGEST_PROGRESS_TTL_SEC = int(os.getenv("MNEMOSYNE_INGEST_PROGRESS_TTL_SEC", str(60 * 60)))
_INGEST_PROGRESS: dict[str, dict] = {}
INGEST_WARNING = "For fastest ingest, upload audio or paste transcript. Video may take several minutes. Please keep this window open"
TEXT_UPLOAD_EXTENSIONS = {".txt", ".md"}
ACTION_STATUS_ALIASES = {
    "pending": "mở",
    "open": "mở",
    "completed": "xong",
    "complete": "xong",
    "done": "xong",
    "cancel": "treo",
    "cancelled": "treo",
    "canceled": "treo",
    "mở": "mở",
    "đang làm": "đang làm",
    "xong": "xong",
    "quá hạn": "quá hạn",
    "treo": "treo",
}
ACTION_STATUSES = set(ACTION_STATUS_ALIASES.values())
OWNER_HEADER_ALIAS = "X-Memoir-Owner"


class ActionStatusBody(BaseModel):
    status: str


def owner_from_header(x_memoir_owner: str | None = Header(default=None, alias=OWNER_HEADER_ALIAS)) -> str | None:
    return db.clean_owner_id(x_memoir_owner) if x_memoir_owner else None


def _ensure_action_owner(action_id: int, owner_id: str):
    if owner_id is None:
        return db.get_action(action_id)
    action = db.get_action(action_id)
    if not action or not db.get_meeting(action.meeting_id, owner_id=owner_id):
        raise HTTPException(404, "Action not found")
    return action


class MeetingUpdateBody(BaseModel):
    title: str | None = None
    source_file: str | None = None
    group_title: str | None = None


class MeetingGroupUpdateBody(BaseModel):
    old_group_title: str
    new_group_title: str


@app.middleware("http")
async def no_store_frontend_assets(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ----------------------------------------------------------------- serializers

def _iso(dt):
    try:
        return dt.isoformat()
    except Exception:  # noqa: BLE001
        return None


def _meeting_brief(m, owner_id: str | None = None) -> dict:
    try:
        summary_brief = m.report().summary_brief.model_dump()
    except Exception:  # noqa: BLE001 - legacy/corrupt report fallback
        summary_brief = None
    display_id = db.display_id_for_meeting(m.id, owner_id=owner_id)
    return {
        "id": m.id, "display_id": display_id or m.id, "title": m.title, "date": m.date,
        "duration_sec": m.duration_sec, "source_file": m.source_file,
        "group_title": getattr(m, "group_title", None),
        "can_play_audio": os.path.exists(_audio_path(m.id)),
        "created_at": _iso(m.created_at), "summary": m.summary,
        "summary_brief": summary_brief,
    }


def _ts(m, *candidates):
    for candidate in candidates:
        ts = brain.estimate_timestamp(m, candidate) if candidate else None
        if ts:
            return ts
    return None


def _meeting_detail(m, owner_id: str | None = None) -> dict:
    rep = m.report()
    facts = db.facts_of_meeting(m.id)
    return {
        **_meeting_brief(m, owner_id=owner_id),
        "transcript": m.transcript or "",
        "key_points": rep.key_points,
        "decisions": [{"text": d.text, "quote": d.quote, "timestamp": _ts(m, d.quote, d.text)}
                      for d in rep.decisions],
        "action_items": [{"task": a.task, "owner": a.owner, "deadline": a.deadline,
                          "status": a.status, "quote": a.quote, "timestamp": _ts(m, a.quote, a.task)}
                         for a in rep.action_items],
        "risks": rep.risks,
        "facts": [{"type": f.type, "subject": f.subject, "statement": f.statement,
                   "quote": f.quote, "status": f.status, "timestamp": _ts(m, f.quote, f.statement, f.subject)}
                  for f in facts],
    }


def _action_detail(a) -> dict:
    m = db.get_meeting(a.meeting_id)
    data = a.as_dict()
    data["timestamp"] = _ts(m, a.quote, a.task) if m else None
    data["meeting_title"] = m.title if m else ""
    data["date"] = m.date if m else ""
    return data


def _suggest_glossary_terms(m, limit: int = 12, owner_id: str | None = None) -> list[dict]:
    rep = m.report()
    facts = db.facts_of_meeting(m.id)
    text = "\n".join([
        getattr(m, "title", "") or "",
        getattr(m, "summary", "") or "",
        rep.summary or "",
        " ".join(rep.key_points or []),
        " ".join(d.text for d in rep.decisions),
        " ".join(a.task for a in rep.action_items),
        " ".join(f"{f.subject} {f.statement}" for f in facts),
        getattr(m, "transcript", "") or "",
    ])
    existing_terms = db.glossary_terms(owner_id=owner_id) if owner_id is not None else db.glossary_terms()
    existing = {term.lower() for term in existing_terms}
    counts: dict[str, int] = {}
    patterns = [
        r"\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b",
        r"\b[A-Z]{2,}(?:\s+Server|\s+API|\s+Model|\s+Runtime)?\b",
        r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,2}\b",
    ]
    stop = {"Team", "Meeting", "No", "API", "HTTP", "URL"}
    for pattern in patterns:
        for match in re.findall(pattern, text):
            term = " ".join(match.split()).strip(".,:;()[]{}")
            if len(term) < 3 or term in stop or term.lower() in existing:
                continue
            counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return [
        {
            "term": term,
            "count": count,
            "reason": f"Seen {count} time{'s' if count != 1 else ''} in meeting evidence",
        }
        for term, count in ranked[:limit]
    ]


def _is_text_upload_metadata(filename: str | None, content_type: str | None) -> bool:
    name = (filename or "").lower()
    _, ext = os.path.splitext(name)
    content_type = (content_type or "").lower()
    return ext in TEXT_UPLOAD_EXTENSIONS or content_type.startswith("text/")


def _is_text_upload(file: UploadFile) -> bool:
    return _is_text_upload_metadata(file.filename, file.content_type)


def _decode_text_upload(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _cleanup_ingest_progress(now: float | None = None) -> None:
    now = now or time.time()
    expired = [
        job_id for job_id, progress in _INGEST_PROGRESS.items()
        if now - float(progress.get("updated_at", 0)) > INGEST_PROGRESS_TTL_SEC
    ]
    for job_id in expired:
        _INGEST_PROGRESS.pop(job_id, None)


def _set_ingest_progress(
    job_id: str | None,
    percent: int | float,
    stage: str,
    detail: str,
    *,
    status: str = "running",
    max_percent: int | float | None = None,
) -> None:
    if not job_id:
        return
    now = time.time()
    value = max(0, min(100, int(round(percent))))
    previous = _INGEST_PROGRESS.get(job_id, {})
    _INGEST_PROGRESS[job_id] = {
        **previous,
        "job_id": job_id,
        "percent": value,
        "stage": stage,
        "detail": detail,
        "status": status,
        "max_percent": int(round(max_percent)) if max_percent is not None else None,
        "stage_started_at": now,
        "updated_at": now,
    }


def _get_ingest_progress(job_id: str) -> dict:
    _cleanup_ingest_progress()
    progress = _INGEST_PROGRESS.get(job_id)
    if not progress:
        raise HTTPException(404, "Progress job not found")
    payload = dict(progress)
    if payload.get("status") == "running" and payload.get("max_percent") is not None:
        elapsed = max(0, time.time() - float(payload.get("stage_started_at", payload.get("updated_at", 0))))
        ticked = int(payload["percent"] + elapsed * 2)
        payload["percent"] = min(int(payload["max_percent"]), ticked)
    return {
        "job_id": payload["job_id"],
        "percent": int(payload["percent"]),
        "stage": payload["stage"],
        "detail": payload["detail"],
        "status": payload["status"],
        "updated_at": payload["updated_at"],
    }


def _upload_dir(upload_id: str) -> str:
    if not upload_id or not all(ch.isalnum() or ch == "-" for ch in upload_id):
        raise HTTPException(400, "Invalid upload id")
    return os.path.join(UPLOAD_STAGING_DIR, upload_id)


def _read_upload_meta(upload_id: str) -> dict:
    meta_path = os.path.join(_upload_dir(upload_id), "meta.json")
    if not os.path.exists(meta_path):
        raise HTTPException(404, "Upload session not found")
    with open(meta_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _audio_path(meeting_id: int) -> str:
    return os.path.join(_WEB, "audio", f"{meeting_id}.mp3")


def _store_playback_audio(meeting_id: int, upload: bytes | None, filename: str) -> None:
    if not upload:
        return
    try:
        os.makedirs(os.path.join(_WEB, "audio"), exist_ok=True)
        if (filename or "").lower().endswith(".mp3"):
            mp3 = upload
        else:
            mp3 = media.to_mp3(upload, filename)
        with open(_audio_path(meeting_id), "wb") as fh:
            fh.write(mp3)
    except Exception:
        # Playback is a convenience layer; ingest/transcript should still succeed.
        return


def _assemble_upload_parts(parts: list[str], dest_path: str) -> int:
    total = 0
    with open(dest_path, "wb") as out:
        for path in parts:
            with open(path, "rb") as src:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            total += os.path.getsize(path)
    return total


def _ingest_payload(
    *,
    upload: bytes | None,
    filename: str,
    content_type: str | None,
    text: str | None,
    title: str | None,
    date: str | None,
    on_duplicate: str,
    extract: bool,
    job_id: str | None = None,
    owner_id: str | None = None,
) -> dict:
    _set_ingest_progress(job_id, 72 if upload else 10, "validating", "Đang kiểm tra file ingest", max_percent=78)
    audio = upload
    if upload and len(upload) > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        _set_ingest_progress(job_id, 0, "error", f"Uploaded file is larger than {max_mb} MB", status="error")
        raise HTTPException(413, f"Uploaded file is larger than {max_mb} MB")
    if upload and _is_text_upload_metadata(filename, content_type):
        decoded = _decode_text_upload(upload).strip()
        if not decoded and not (text or "").strip():
            _set_ingest_progress(job_id, 0, "error", "Uploaded file is empty", status="error")
            raise HTTPException(400, "Uploaded file is empty")
        text = "\n\n".join(part for part in [(text or "").strip(), decoded] if part) or None
        audio = None
    t0 = time.time()
    _set_ingest_progress(
        job_id,
        78 if upload else 25,
        "ingesting",
        INGEST_WARNING,
        max_percent=95,
    )
    try:
        out = brain.ingest(
            text=text or None, audio=audio, date=date or None, title=title or None,
            filename=filename, extract=extract,
            source_file=(filename if upload else None), on_duplicate=on_duplicate,
            owner_id=owner_id,
        )
    except Exception as e:  # noqa: BLE001
        _set_ingest_progress(job_id, 0, "error", str(e), status="error")
        raise HTTPException(400, str(e))
    if audio and not out.get("skipped"):
        _set_ingest_progress(job_id, 96, "saving", "Đang lưu audio playback", max_percent=98)
        _store_playback_audio(out["meeting_id"], upload, filename)
    _set_ingest_progress(job_id, 100, "done", "Hoàn tất ingest", status="done")
    display_id = db.display_id_for_meeting(out["meeting_id"], owner_id=owner_id) or out["meeting_id"]
    response = {
        "meeting_id": out["meeting_id"],
        "display_id": display_id,
        "skipped": out.get("skipped", False),
        "facts_count": len(out.get("facts", [])),
        "contradictions": [c.model_dump() for c in out.get("contradictions", [])],
        "forgotten": out.get("forgotten", []),
        "elapsed_sec": round(time.time() - t0, 1),
        "report": out["report"].model_dump(),
    }
    if job_id:
        response["job_id"] = job_id
    return response


# ----------------------------------------------------------------- API: read

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def frontend_config():
    return {
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "upload_chunk_bytes": UPLOAD_CHUNK_BYTES,
    }


@app.get("/api/stats")
def stats(owner_id: str = Depends(owner_from_header)):
    return db.counts(owner_id=owner_id)


@app.get("/api/meetings")
def meetings(owner_id: str = Depends(owner_from_header)):
    return [_meeting_brief(m, owner_id=owner_id) for m in db.list_meetings(limit=1000, owner_id=owner_id)]


@app.get("/api/meetings/{meeting_id}")
def meeting(meeting_id: int, owner_id: str = Depends(owner_from_header)):
    m = db.get_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    return _meeting_detail(m, owner_id=owner_id)


@app.patch("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: int, body: MeetingUpdateBody, owner_id: str = Depends(owner_from_header)):
    if body.title is None and body.source_file is None and body.group_title is None:
        raise HTTPException(400, "No meeting metadata provided")
    if not db.update_meeting_metadata(
        meeting_id,
        title=body.title,
        source_file=body.source_file,
        group_title=body.group_title,
        **({"owner_id": owner_id} if owner_id is not None else {}),
    ):
        raise HTTPException(404, "meeting not found")
    m = db.get_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    return _meeting_brief(m, owner_id=owner_id)


@app.patch("/api/meeting_groups")
def update_meeting_group(body: MeetingGroupUpdateBody, owner_id: str = Depends(owner_from_header)):
    updated = (
        db.rename_meeting_group(body.old_group_title, body.new_group_title, owner_id=owner_id)
        if owner_id is not None
        else db.rename_meeting_group(body.old_group_title, body.new_group_title)
    )
    return {
        "old_group_title": body.old_group_title,
        "new_group_title": body.new_group_title,
        "updated": updated,
    }


@app.get("/api/meetings/{meeting_id}/audio")
def meeting_audio(meeting_id: int, owner_id: str = Depends(owner_from_header)):
    """Serve the stored audio for listen-back (Phase 3 stores it under web/audio)."""
    if owner_id is not None and not db.get_meeting(meeting_id, owner_id=owner_id):
        raise HTTPException(404, "meeting not found")
    path = _audio_path(meeting_id)
    if not os.path.exists(path):
        raise HTTPException(404, "no audio stored for this meeting")
    return FileResponse(path, media_type="audio/mpeg")


_REPORT_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@app.get("/api/meetings/{meeting_id}/report.{fmt}")
def meeting_report(meeting_id: int, fmt: str, owner_id: str = Depends(owner_from_header)):
    """Export a meeting's executive report as .docx or .pdf for download."""
    fmt = fmt.lower()
    if fmt not in _REPORT_MEDIA:
        raise HTTPException(400, "format must be docx or pdf")
    m = db.get_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    rep = m.report()
    try:
        data = report_mod.render_docx(rep) if fmt == "docx" else report_mod.render_pdf(rep)
    except Exception as exc:  # weasyprint native libs may be missing for pdf
        raise HTTPException(503, f"{fmt} export unavailable: {exc}")
    fname = report_mod.filename(rep, fmt)
    ascii_name = fname.encode("ascii", "ignore").decode("ascii") or f"meeting_{meeting_id}.{fmt}"
    quoted = quote(fname)
    return Response(
        content=data,
        media_type=_REPORT_MEDIA[fmt],
        headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"},
    )


@app.get("/api/actions")
def actions(status: str | None = None, owner_id: str = Depends(owner_from_header)):
    return [_action_detail(a) for a in db.all_actions(status=status, owner_id=owner_id)]


@app.patch("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionStatusBody, owner_id: str = Depends(owner_from_header)):
    status = ACTION_STATUS_ALIASES.get(body.status.strip().lower())
    if status not in ACTION_STATUSES:
        raise HTTPException(400, "Invalid action status")
    _ensure_action_owner(action_id, owner_id)
    if not db.update_action_status(action_id, status):
        raise HTTPException(404, "Action not found")
    return {"id": action_id, "status": status}


class AssignBody(BaseModel):
    owner: str
    email: str | None = None      # recipient typed at assign time; sent to once
    notify: bool = True
    note: str | None = None


@app.post("/api/actions/{action_id}/assign")
def assign_action(action_id: int, body: AssignBody, owner_id: str = Depends(owner_from_header)):
    if not body.owner.strip():
        raise HTTPException(400, "owner is required")
    _ensure_action_owner(action_id, owner_id)
    res = brain.assign_action(action_id, body.owner.strip(), email=body.email,
                              notify=body.notify, note=body.note)
    if not res.get("assigned"):
        raise HTTPException(404, "Action not found")
    return res


@app.get("/api/contradictions")
def contradictions(owner_id: str = Depends(owner_from_header)):
    return brain.contradiction_view(owner_id=owner_id)


@app.get("/api/resurfaced")
def resurfaced(owner_id: str = Depends(owner_from_header)):
    return brain.resurfaced_view(owner_id=owner_id)


@app.get("/api/digest")
def digest(scope: str = "all"):
    rep = brain.digest(scope)
    return {
        "title": rep.title, "summary": rep.summary, "key_points": rep.key_points,
        "decisions": [d.text for d in rep.decisions], "risks": rep.risks,
        "action_items": [{"task": a.task, "owner": a.owner, "deadline": a.deadline,
                          "status": a.status} for a in rep.action_items],
    }


@app.get("/api/glossary")
def glossary(owner_id: str = Depends(owner_from_header)):
    return [g.as_dict() for g in db.list_glossary(owner_id=owner_id)]


@app.get("/api/glossary/suggestions")
def glossary_suggestions(meeting_id: int, owner_id: str = Depends(owner_from_header)):
    m = db.get_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    return {"suggestions": _suggest_glossary_terms(m, owner_id=owner_id)}


# ----------------------------------------------------------------- API: write

class AskBody(BaseModel):
    question: str
    meeting_id: int | None = None


class UploadInitBody(BaseModel):
    filename: str
    size: int
    content_type: str | None = None


@app.post("/api/ask")
def ask(body: AskBody, owner_id: str = Depends(owner_from_header)):
    if owner_id is not None and body.meeting_id and not db.get_meeting(body.meeting_id, owner_id=owner_id):
        raise HTTPException(404, "meeting not found")
    ans = (
        brain.ask(body.question, meeting_id=body.meeting_id, owner_id=owner_id)
        if owner_id is not None
        else brain.ask(body.question, meeting_id=body.meeting_id)
    )
    return {"answer": ans.text,
            "citations": [c.model_dump() for c in ans.citations]}


@app.post("/api/ingest")
async def ingest(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    title: str | None = Form(default=None),
    date: str | None = Form(default=None),
    on_duplicate: str = Form(default="new"),
    extract: bool = Form(default=True),
    job_id: str | None = Form(default=None),
    owner_id: str = Depends(owner_from_header),
):
    upload = await file.read() if file else None
    filename = file.filename if file else "meeting.wav"
    progress_id = job_id or str(uuid.uuid4())
    if file and not upload and not (text or "").strip():
        _set_ingest_progress(progress_id, 0, "error", "Uploaded file is empty", status="error")
        raise HTTPException(400, "Uploaded file is empty")
    return await run_in_threadpool(
        _ingest_payload,
        upload=upload, filename=filename, content_type=file.content_type if file else None,
        text=text, title=title, date=date, on_duplicate=on_duplicate, extract=extract,
        job_id=progress_id,
        owner_id=owner_id,
    )


@app.get("/api/ingest/progress/{job_id}")
def ingest_progress(job_id: str):
    return _get_ingest_progress(job_id)


@app.post("/api/uploads")
def create_upload(body: UploadInitBody):
    _cleanup_ingest_progress()
    if body.size <= 0:
        raise HTTPException(400, "Uploaded file is empty")
    if body.size > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(413, f"Uploaded file is larger than {max_mb} MB")
    upload_id = str(uuid.uuid4())
    upload_dir = _upload_dir(upload_id)
    os.makedirs(upload_dir, exist_ok=False)
    total_chunks = (body.size + UPLOAD_CHUNK_BYTES - 1) // UPLOAD_CHUNK_BYTES
    meta = {
        "filename": body.filename or "meeting.wav",
        "size": body.size,
        "content_type": body.content_type,
        "total_chunks": total_chunks,
        "created_at": time.time(),
    }
    with open(os.path.join(upload_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    _set_ingest_progress(upload_id, 0, "queued", "Đã tạo phiên upload", max_percent=5)
    return {
        "upload_id": upload_id,
        "job_id": upload_id,
        "progress_url": f"/api/ingest/progress/{upload_id}",
        "chunk_size": UPLOAD_CHUNK_BYTES,
        "total_chunks": total_chunks,
    }


@app.post("/api/uploads/{upload_id}/chunks")
async def upload_chunk(
    upload_id: str,
    index: int = Form(...),
    chunk: UploadFile = File(...),
):
    meta = _read_upload_meta(upload_id)
    if index < 0 or index >= int(meta["total_chunks"]):
        raise HTTPException(400, "Invalid chunk index")
    data = await chunk.read()
    if not data:
        raise HTTPException(400, "Chunk is empty")
    if len(data) > UPLOAD_CHUNK_BYTES:
        raise HTTPException(413, "Chunk is too large")
    upload_dir = _upload_dir(upload_id)
    with open(os.path.join(upload_dir, f"{index}.part"), "wb") as fh:
        fh.write(data)
    received_chunks = len([name for name in os.listdir(upload_dir) if name.endswith(".part")])
    percent = int(round((received_chunks / int(meta["total_chunks"])) * 70))
    _set_ingest_progress(
        upload_id,
        percent,
        "uploading",
        f"Đã nhận {received_chunks}/{meta['total_chunks']} chunk",
        max_percent=70,
    )
    return {"received": index, "received_chunks": received_chunks, "percent": percent}


@app.post("/api/uploads/{upload_id}/complete")
async def complete_upload(
    upload_id: str,
    text: str | None = Form(default=None),
    title: str | None = Form(default=None),
    date: str | None = Form(default=None),
    on_duplicate: str = Form(default="new"),
    extract: bool = Form(default=True),
    owner_id: str = Depends(owner_from_header),
):
    upload_dir = _upload_dir(upload_id)
    meta = _read_upload_meta(upload_id)
    total_chunks = int(meta["total_chunks"])
    parts = [os.path.join(upload_dir, f"{i}.part") for i in range(total_chunks)]
    missing = [str(i) for i, path in enumerate(parts) if not os.path.exists(path)]
    if missing:
        _set_ingest_progress(upload_id, 70, "error", f"Missing chunks: {', '.join(missing[:5])}", status="error")
        raise HTTPException(400, f"Missing chunks: {', '.join(missing[:5])}")
    try:
        _set_ingest_progress(upload_id, 70, "assembling", "Đang ghép file upload", max_percent=76)
        assembled_path = os.path.join(upload_dir, "upload.bin")
        upload_size = _assemble_upload_parts(parts, assembled_path)
        if upload_size != int(meta["size"]):
            _set_ingest_progress(upload_id, 70, "error", "Upload size mismatch", status="error")
            raise HTTPException(400, "Upload size mismatch")
        with open(assembled_path, "rb") as fh:
            upload = fh.read()
        return await run_in_threadpool(
            _ingest_payload,
            upload=upload,
            filename=meta["filename"],
            content_type=meta.get("content_type"),
            text=text,
            title=title,
            date=date,
            on_duplicate=on_duplicate,
            extract=extract,
            job_id=upload_id,
            owner_id=owner_id,
        )
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


class CheckBody(BaseModel):
    audio_hash: str | None = None


@app.post("/api/ingest/check")
async def ingest_check(file: UploadFile = File(...), owner_id: str = Depends(owner_from_header)):
    """Pre-flight: tell the UI whether this exact file was already ingested."""
    data = await file.read()
    dup = db.find_by_audio_hash(db.audio_hash(data), owner_id=owner_id) if owner_id is not None else db.find_by_audio_hash(db.audio_hash(data))
    return {"duplicate": bool(dup),
            "meeting": _meeting_brief(dup, owner_id=owner_id) if dup else None}


class ReanalyzeBody(BaseModel):
    transcript: str


@app.post("/api/meetings/{meeting_id}/reanalyze")
def reanalyze(meeting_id: int, body: ReanalyzeBody, owner_id: str = Depends(owner_from_header)):
    try:
        out = (
            brain.reanalyze(meeting_id, body.transcript, owner_id=owner_id)
            if owner_id is not None
            else brain.reanalyze(meeting_id, body.transcript)
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"meeting_id": meeting_id, "facts_count": len(out["facts"]),
            "contradictions": [c.model_dump() for c in out["contradictions"]],
            "forgotten": out.get("forgotten", [])}


@app.post("/api/meetings/{meeting_id}/apply_glossary")
def apply_glossary(meeting_id: int, owner_id: str = Depends(owner_from_header)):
    try:
        out = (
            brain.apply_glossary_to_meeting(meeting_id, owner_id=owner_id)
            if owner_id is not None
            else brain.apply_glossary_to_meeting(meeting_id)
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"meeting_id": meeting_id, "changed": out["changed"],
            "facts_count": len(out["facts"]),
            "contradictions": [c.model_dump() for c in out["contradictions"]],
            "forgotten": out.get("forgotten", [])}


@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, owner_id: str = Depends(owner_from_header)):
    deleted = db.delete_meeting(meeting_id, owner_id=owner_id) if owner_id is not None else db.delete_meeting(meeting_id)
    if not deleted:
        raise HTTPException(404, "meeting not found")
    path = _audio_path(meeting_id)
    if os.path.exists(path):
        os.remove(path)
    return {"status": "deleted", "meeting_id": meeting_id}


@app.post("/api/followup")
def followup():
    return {"updates": brain.follow_up()}


@app.post("/api/scan_forgotten")
def scan_forgotten():
    return {"resurfaced": brain.scan_forgotten()}


@app.post("/api/redetect_contradictions")
def redetect_contradictions():
    """Wipe all contradictions and re-run detection chronologically across all meetings."""
    return brain.redetect_all_contradictions()


class NotifyBody(BaseModel):
    to: list[str] | None = None      # override recipients; None -> config.EMAIL_TO
    refresh: bool = True             # run follow_up() to refresh statuses before sending


@app.post("/api/notify/actions")
def notify_actions(body: NotifyBody):
    return brain.notify_actions(to=body.to, refresh=body.refresh)


class GlossaryBody(BaseModel):
    term: str
    wrong: str | None = None


@app.post("/api/glossary")
def add_glossary(body: GlossaryBody, owner_id: str = Depends(owner_from_header)):
    gid = db.add_glossary(body.term, wrong=body.wrong, owner_id=owner_id) if owner_id is not None else db.add_glossary(body.term, wrong=body.wrong)
    return {"id": gid}


@app.post("/api/glossary/learn")
async def learn_glossary(file: UploadFile = File(...), owner_id: str = Depends(owner_from_header)):
    raw = await file.read()
    text = raw.decode("utf-8", "ignore")  # txt/md; docx parsed client-side or extend here
    terms = brain.learn_glossary(text, owner_id=owner_id) if owner_id is not None else brain.learn_glossary(text)
    return {"terms": terms}


@app.delete("/api/glossary/{gid}")
def delete_glossary(gid: int, owner_id: str = Depends(owner_from_header)):
    deleted = db.delete_glossary(gid, owner_id=owner_id) if owner_id is not None else db.delete_glossary(gid)
    if not deleted:
        raise HTTPException(404, "glossary term not found")
    return {"status": "deleted", "id": gid}


# ----------------------------------------------------------------- static SPA

def _frontend_bootstrap() -> dict:
    return {
        "config": frontend_config(),
        "stats": db.counts(owner_id="__bootstrap_empty__"),
        "meetings": [],
        "meeting_details": {},
        "actions": [],
        "contradictions": [],
        "resurfaced": [],
        "glossary": [],
        "digest": None,
    }


@app.get("/", response_class=HTMLResponse)
def frontend_index():
    index_path = os.path.join(_WEB, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("Memoir frontend not found", status_code=404)
    with open(index_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    payload = json.dumps(_frontend_bootstrap(), ensure_ascii=False).replace("</", "<\\/")
    bootstrap = f'<script id="memoirBootstrap" type="application/json">{payload}</script>'
    return html.replace("</head>", f"{bootstrap}\n  </head>")


if os.path.isdir(_WEB):
    app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")
else:
    @app.get("/api")
    def root():
        return JSONResponse({"service": "Memoir API",
                             "note": "frontend not built yet; see /docs for API"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080)
