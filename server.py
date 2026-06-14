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
import shutil
import time
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

import config  # noqa: F401 (loads .env)
import db
import brain
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


@app.get("/api/meetings/{meeting_id}/audio")
def meeting_audio(meeting_id: int):
    """Serve the stored audio for listen-back (Phase 3 stores it under web/audio)."""
    path = os.path.join(_WEB, "audio", f"{meeting_id}.mp3")
    if not os.path.exists(path):
        raise HTTPException(404, "no audio stored for this meeting")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/api/actions")
def actions(status: str | None = None):
    return [a.as_dict() for a in db.all_actions(status=status)]


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
    return {"status": "deleted", "meeting_id": meeting_id}


@app.post("/api/followup")
def followup():
    return {"updates": brain.follow_up()}


@app.post("/api/scan_forgotten")
def scan_forgotten():
    return {"resurfaced": brain.scan_forgotten()}


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

if os.path.isdir(_WEB):
    app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")
else:
    @app.get("/")
    def root():
        return JSONResponse({"service": "Memoir API",
                             "note": "frontend not built yet; see /docs for API"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080)
