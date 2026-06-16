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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
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


class ActionStatusBody(BaseModel):
    status: str


class MeetingUpdateBody(BaseModel):
    title: str | None = None
    source_file: str | None = None


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


def _meeting_brief(m) -> dict:
    return {
        "id": m.id, "title": m.title, "date": m.date,
        "duration_sec": m.duration_sec, "source_file": m.source_file,
        "can_play_audio": os.path.exists(_audio_path(m.id)),
        "created_at": _iso(m.created_at), "summary": m.summary,
    }


def _ts(m, quote):
    return brain.estimate_timestamp(m, quote) if quote else None


def _meeting_detail(m) -> dict:
    rep = m.report()
    facts = db.facts_of_meeting(m.id)
    return {
        **_meeting_brief(m),
        "transcript": m.transcript or "",
        "key_points": rep.key_points,
        "decisions": [{"text": d.text, "quote": d.quote, "timestamp": _ts(m, d.quote)}
                      for d in rep.decisions],
        "action_items": [{"task": a.task, "owner": a.owner, "deadline": a.deadline,
                          "status": a.status, "quote": a.quote, "timestamp": _ts(m, a.quote)}
                         for a in rep.action_items],
        "risks": rep.risks,
        "facts": [{"type": f.type, "subject": f.subject, "statement": f.statement,
                   "quote": f.quote, "status": f.status, "timestamp": _ts(m, f.quote)}
                  for f in facts],
    }


def _action_detail(a) -> dict:
    m = db.get_meeting(a.meeting_id)
    data = a.as_dict()
    data["timestamp"] = _ts(m, a.quote) if m else None
    data["meeting_title"] = m.title if m else ""
    data["date"] = m.date if m else ""
    return data


def _suggest_glossary_terms(m, limit: int = 12) -> list[dict]:
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
    existing = {term.lower() for term in db.glossary_terms()}
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
) -> dict:
    audio = upload
    if upload and len(upload) > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(413, f"Uploaded file is larger than {max_mb} MB")
    if upload and _is_text_upload_metadata(filename, content_type):
        decoded = _decode_text_upload(upload).strip()
        if not decoded and not (text or "").strip():
            raise HTTPException(400, "Uploaded file is empty")
        text = "\n\n".join(part for part in [(text or "").strip(), decoded] if part) or None
        audio = None
    t0 = time.time()
    try:
        out = brain.ingest(
            text=text or None, audio=audio, date=date or None, title=title or None,
            filename=filename, extract=extract,
            source_file=(filename if upload else None), on_duplicate=on_duplicate,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    if audio and not out.get("skipped"):
        _store_playback_audio(out["meeting_id"], upload, filename)
    return {
        "meeting_id": out["meeting_id"],
        "skipped": out.get("skipped", False),
        "facts_count": len(out.get("facts", [])),
        "contradictions": [c.model_dump() for c in out.get("contradictions", [])],
        "forgotten": out.get("forgotten", []),
        "elapsed_sec": round(time.time() - t0, 1),
        "report": out["report"].model_dump(),
    }


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
def stats():
    return db.counts()


@app.get("/api/meetings")
def meetings():
    return [_meeting_brief(m) for m in db.list_meetings(limit=1000)]


@app.get("/api/meetings/{meeting_id}")
def meeting(meeting_id: int):
    m = db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    return _meeting_detail(m)


@app.patch("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: int, body: MeetingUpdateBody):
    if body.title is None and body.source_file is None:
        raise HTTPException(400, "No meeting metadata provided")
    if not db.update_meeting_metadata(
        meeting_id,
        title=body.title,
        source_file=body.source_file,
    ):
        raise HTTPException(404, "meeting not found")
    m = db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    return _meeting_brief(m)


@app.get("/api/meetings/{meeting_id}/audio")
def meeting_audio(meeting_id: int):
    """Serve the stored audio for listen-back (Phase 3 stores it under web/audio)."""
    path = _audio_path(meeting_id)
    if not os.path.exists(path):
        raise HTTPException(404, "no audio stored for this meeting")
    return FileResponse(path, media_type="audio/mpeg")


_REPORT_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@app.get("/api/meetings/{meeting_id}/report.{fmt}")
def meeting_report(meeting_id: int, fmt: str):
    """Export a meeting's executive report as .docx or .pdf for download."""
    fmt = fmt.lower()
    if fmt not in _REPORT_MEDIA:
        raise HTTPException(400, "format must be docx or pdf")
    m = db.get_meeting(meeting_id)
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
def actions(status: str | None = None):
    return [_action_detail(a) for a in db.all_actions(status=status)]


@app.patch("/api/actions/{action_id}")
def update_action(action_id: int, body: ActionStatusBody):
    status = ACTION_STATUS_ALIASES.get(body.status.strip().lower())
    if status not in ACTION_STATUSES:
        raise HTTPException(400, "Invalid action status")
    if not db.update_action_status(action_id, status):
        raise HTTPException(404, "Action not found")
    return {"id": action_id, "status": status}


class AssignBody(BaseModel):
    owner: str
    email: str | None = None      # recipient typed at assign time; sent to once
    notify: bool = True
    note: str | None = None


@app.post("/api/actions/{action_id}/assign")
def assign_action(action_id: int, body: AssignBody):
    if not body.owner.strip():
        raise HTTPException(400, "owner is required")
    res = brain.assign_action(action_id, body.owner.strip(), email=body.email,
                              notify=body.notify, note=body.note)
    if not res.get("assigned"):
        raise HTTPException(404, "Action not found")
    return res


@app.get("/api/contradictions")
def contradictions():
    return brain.contradiction_view()


@app.get("/api/resurfaced")
def resurfaced():
    return brain.resurfaced_view()


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
def glossary():
    return [g.as_dict() for g in db.list_glossary()]


@app.get("/api/glossary/suggestions")
def glossary_suggestions(meeting_id: int):
    m = db.get_meeting(meeting_id)
    if not m:
        raise HTTPException(404, "meeting not found")
    return {"suggestions": _suggest_glossary_terms(m)}


# ----------------------------------------------------------------- API: write

class AskBody(BaseModel):
    question: str


class UploadInitBody(BaseModel):
    filename: str
    size: int
    content_type: str | None = None


@app.post("/api/ask")
def ask(body: AskBody):
    ans = brain.ask(body.question)
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
):
    upload = await file.read() if file else None
    filename = file.filename if file else "meeting.wav"
    if file and not upload and not (text or "").strip():
        raise HTTPException(400, "Uploaded file is empty")
    return await run_in_threadpool(
        _ingest_payload,
        upload=upload, filename=filename, content_type=file.content_type if file else None,
        text=text, title=title, date=date, on_duplicate=on_duplicate, extract=extract,
    )


@app.post("/api/uploads")
def create_upload(body: UploadInitBody):
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
    return {
        "upload_id": upload_id,
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
    return {"received": index}


@app.post("/api/uploads/{upload_id}/complete")
async def complete_upload(
    upload_id: str,
    text: str | None = Form(default=None),
    title: str | None = Form(default=None),
    date: str | None = Form(default=None),
    on_duplicate: str = Form(default="new"),
    extract: bool = Form(default=True),
):
    upload_dir = _upload_dir(upload_id)
    meta = _read_upload_meta(upload_id)
    total_chunks = int(meta["total_chunks"])
    parts = [os.path.join(upload_dir, f"{i}.part") for i in range(total_chunks)]
    missing = [str(i) for i, path in enumerate(parts) if not os.path.exists(path)]
    if missing:
        raise HTTPException(400, f"Missing chunks: {', '.join(missing[:5])}")
    try:
        upload = b"".join(open(path, "rb").read() for path in parts)
        if len(upload) != int(meta["size"]):
            raise HTTPException(400, "Upload size mismatch")
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
        )
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


class CheckBody(BaseModel):
    audio_hash: str | None = None


@app.post("/api/ingest/check")
async def ingest_check(file: UploadFile = File(...)):
    """Pre-flight: tell the UI whether this exact file was already ingested."""
    data = await file.read()
    dup = db.find_by_audio_hash(db.audio_hash(data))
    return {"duplicate": bool(dup),
            "meeting": _meeting_brief(dup) if dup else None}


class ReanalyzeBody(BaseModel):
    transcript: str


@app.post("/api/meetings/{meeting_id}/reanalyze")
def reanalyze(meeting_id: int, body: ReanalyzeBody):
    try:
        out = brain.reanalyze(meeting_id, body.transcript)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"meeting_id": meeting_id, "facts_count": len(out["facts"]),
            "contradictions": [c.model_dump() for c in out["contradictions"]],
            "forgotten": out.get("forgotten", [])}


@app.delete("/api/meetings/{meeting_id}")
def delete_meeting(meeting_id: int):
    db.delete_meeting(meeting_id)
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
def add_glossary(body: GlossaryBody):
    gid = db.add_glossary(body.term, wrong=body.wrong)
    return {"id": gid}


@app.post("/api/glossary/learn")
async def learn_glossary(file: UploadFile = File(...)):
    raw = await file.read()
    text = raw.decode("utf-8", "ignore")  # txt/md; docx parsed client-side or extend here
    terms = brain.learn_glossary(text)
    return {"terms": terms}


@app.delete("/api/glossary/{gid}")
def delete_glossary(gid: int):
    db.delete_glossary(gid)
    return {"status": "deleted", "id": gid}


# ----------------------------------------------------------------- static SPA

def _frontend_bootstrap() -> dict:
    meeting_rows = [_meeting_brief(m) for m in db.list_meetings(limit=1000)]
    meeting_details = {}
    if meeting_rows:
        first = db.get_meeting(meeting_rows[0]["id"])
        if first:
            meeting_details[str(first.id)] = _meeting_detail(first)
    return {
        "config": frontend_config(),
        "stats": stats(),
        "meetings": meeting_rows,
        "meeting_details": meeting_details,
        "actions": actions(),
        "contradictions": contradictions(),
        "resurfaced": resurfaced(),
        "glossary": glossary(),
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
