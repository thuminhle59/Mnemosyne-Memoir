"""Mnemosyne agent entrypoint (GreenNode AgentBase).

One endpoint, routed by `action`:
  ingest   {audio_base64|text, date?, title?, format?}  -> save meeting + facts + contradictions
  ask      {question}                                   -> recall Q&A with citations
  digest   {scope?}                                     -> executive digest (+ optional file)
  followup {}                                           -> re-check action statuses

The AgentBase runtime also mounts the web dashboard/API, so the deployed endpoint
serves both the agent contract and the browser frontend.
"""
import base64
import datetime as _dt
import logging

from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext

import config  # noqa: F401  (loads .env early)
import db
import brain
import report as report_mod

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mnemosyne")

db.init_db()

_VALID_FORMATS = {"docx", "pdf"}


def _do_ingest(payload: dict) -> dict:
    text = payload.get("text")
    audio = None
    filename = payload.get("filename", "meeting.wav")
    if not text:
        b64 = payload.get("audio_base64")
        if not b64:
            return {"status": "error", "message": "ingest needs 'text' or 'audio_base64'"}
        audio = base64.b64decode(b64)
    # brain.ingest transcodes to WAV + chunks long audio (endpoint only accepts WAV).
    out = brain.ingest(
        text=text, audio=audio,
        date=payload.get("date") or _dt.date.today().isoformat(),
        title=payload.get("meeting_title") or payload.get("title"),
        language=payload.get("language", "vi"),
        filename=filename,
        extract=payload.get("extract_audio", True),
        source_file=payload.get("filename"),
        on_duplicate=payload.get("on_duplicate", "new"),
    )
    resp = {
        "status": "success",
        "meeting_id": out["meeting_id"],
        "skipped": out.get("skipped", False),
        "report": out["report"].model_dump(),
        "facts": [f.model_dump() for f in out["facts"]],
        "contradictions": [c.model_dump() for c in out["contradictions"]],
        "forgotten": out.get("forgotten", []),
    }
    fmt = (payload.get("format") or "").lower()
    if fmt in _VALID_FORMATS:
        rep = out["report"]
        try:
            data = report_mod.render_docx(rep) if fmt == "docx" else report_mod.render_pdf(rep)
            out_fmt = fmt
        except Exception as e:  # noqa: BLE001 - pdf libs optional
            log.warning("render %s failed (%s); degrading to docx", fmt, e)
            data, out_fmt = report_mod.render_docx(rep), "docx"
        resp["report_filename"] = report_mod.filename(rep, out_fmt)
        resp["report_base64"] = base64.b64encode(data).decode()
    return resp


def _do_ask(payload: dict) -> dict:
    q = payload.get("question")
    if not q:
        return {"status": "error", "message": "ask needs 'question'"}
    ans = brain.ask(q)
    return {"status": "success", "answer": ans.text,
            "citations": [c.model_dump() for c in ans.citations]}


def _do_digest(payload: dict) -> dict:
    rep = brain.digest(payload.get("scope", "all"))
    resp = {"status": "success", "digest": rep.model_dump()}
    fmt = (payload.get("format") or "").lower()
    if fmt in _VALID_FORMATS:
        try:
            data = report_mod.render_docx(rep) if fmt == "docx" else report_mod.render_pdf(rep)
            out_fmt = fmt
        except Exception:  # noqa: BLE001
            data, out_fmt = report_mod.render_docx(rep), "docx"
        resp["report_filename"] = report_mod.filename(rep, out_fmt)
        resp["report_base64"] = base64.b64encode(data).decode()
    return resp


def _do_followup(_payload: dict) -> dict:
    return {"status": "success", "updates": brain.follow_up()}


def _do_scan_forgotten(_payload: dict) -> dict:
    return {"status": "success", "resurfaced": brain.scan_forgotten()}


_ROUTES = {
    "ingest": _do_ingest,
    "ask": _do_ask,
    "digest": _do_digest,
    "followup": _do_followup,
    "scan_forgotten": _do_scan_forgotten,
}


def process(payload: dict) -> dict:
    action = (payload.get("action") or "ingest").lower()
    fn = _ROUTES.get(action)
    if not fn:
        return {"status": "error",
                "message": f"unknown action '{action}' (use {sorted(_ROUTES)})"}
    try:
        return fn(payload)
    except Exception as e:  # noqa: BLE001
        log.exception("action %s failed", action)
        return {"status": "error", "message": str(e)}


app = GreenNodeAgentBaseApp()


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    return process(payload or {})


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


# Mount the browser dashboard after SDK routes so AgentBase-owned `/health` and
# `/invocations` keep their contract while the deployed endpoint can serve `/`.
import server as web_server  # noqa: E402

app.mount("/", web_server.app)


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
