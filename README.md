# Memoir - Memory Decision Agent

Memoir is a meeting memory agent for teams that need decisions to survive across meetings. It ingests transcripts, audio, or video, then builds a long-running decision layer: what was decided, what changed, what was forgotten, who owns the next action, and what evidence supports each answer.

Built for GreenNode Claw-a-thon 2026 as a Custom Agent on GreenNode AgentBase.

> Data compliance: use synthetic, staged, or personal demo data only. Do not upload internal/customer meetings or PII.

## Demo

AgentBase endpoint:

```text
https://endpoint-67bc4eb0-570b-4ede-b08b-0f25cfe55fdd.agentbase-runtime.aiplatform.vngcloud.vn
```

Health check:

```bash
curl -i https://endpoint-67bc4eb0-570b-4ede-b08b-0f25cfe55fdd.agentbase-runtime.aiplatform.vngcloud.vn/health
```

Local app:

```text
http://127.0.0.1:18092
```

## What Makes It Different

Most meeting tools summarize one call. Memoir compares each new meeting against the history of prior meetings in the same memory source or topic group.

- **Executive Brief**: shows the executive digest, decisions, contradictions, risks, and blockers without requiring a manual digest click.
- **Actions**: shows important actions for the selected meeting, supports checkbox completion, and keeps completed actions in place with strike-through.
- **Evidence Lab**: combines evidence graph and read-only transcript evidence with clickable timestamps.
- **Contradiction Radar**: detects concrete conflicts in decisions, facts, numbers, or commitments across meeting history.
- **Forgotten Decision Surfacing**: brings back commitments and decisions that were mentioned before but not closed.
- **Evidence Q&A**: answers questions using meeting memory and supporting evidence, scoped to the selected group/folder.
- **Terminology Learning**: automatically learns team-specific terms, lists them by mention count, and lets users edit the terminology list inline.
- **Large File Upload**: supports direct upload for small files and chunked upload for larger audio/video files.
- **Audio Playback**: stores playable audio when available and seeks to evidence timestamps from summary, actions, contradictions, and transcript.

## Current Product State

The current frontend is the Memoir redesign, using the Claude Design-inspired layout while keeping the app's red/gray Memoir theme.

- Left sidebar groups meetings by topic/scope and only shows meeting name, meeting time, and duration.
- Meeting names can be renamed by double-clicking, and input timestamps use local `yyyy-MM-dd HH:mm:ss` format.
- Terminology is collapsible. The normal list stays simple; edit mode is opened inside the Terminology section.
- The upload flow supports `Upload audio`, `Recording`, and `Paste transcript`. Mic recording is currently disabled in the UI; tab/screen recording has been removed.
- Upload progress now uses simple stage text such as `Preparing {filename}. Please keep this window open.` with percentage updates.
- Meeting Summary only shows important executive points and always renders full sentences without `...` truncation.
- The manual `Refresh follow-up` and contradiction `Re-detect` buttons were removed from the main UI to keep the experience cleaner.

## Recent Backend Enhancements

Recent Claude/backend updates improved the agent logic behind the UI:

- Better fact extraction rules that focus on concrete decisions, facts, numbers, and commitments.
- In-meeting fact deduplication before saving to memory.
- Batched contradiction detection against recent historical candidates, with lower false positives for vague risks or assumptions.
- Same-file audio detection through upload hashing, with an override path for intentionally re-ingesting the same file.
- Audio/video ingestion through WAV chunking, per-chunk STT correction, and chunk maps for more accurate timestamp estimates.
- Retrieval that normalizes Vietnamese diacritics and falls back to recent context when lexical matches are sparse.
- Action assignment, owner updates, and optional email notification through the mailer layer.
- Action digest notification for open and overdue actions.
- Meeting deletion now cascades derived facts, actions, action links, contradictions, and playback audio references.

## Product Layout

Memoir is a three-panel web app:

- **Left sidebar**: grouped meeting library, editable meeting names, delete actions, and terminology.
- **Middle workspace**: Executive Brief, Actions, Evidence Lab, and compact audio playback.
- **Right panel**: Ask Memoir, an evidence-backed Q&A assistant across the selected memory scope.

Tabs:

| Tab | Purpose |
|---|---|
| `Executive Brief` | Executive digest, decisions, contradictions, risks, and blockers. |
| `Actions` | Important action items for the selected meeting with completion checkboxes. |
| `Evidence Lab` | Evidence graph and transcript evidence with timestamp playback. |

## Architecture

```text
Browser SPA
   |
   | fetch /api/*
   v
FastAPI server.py
   |
   v
brain.py
   |
   +--> transcribe.py / media.py
   +--> analyze.py / retrieve.py
   +--> mailer.py
   +--> db.py SQLite memory store
```

Important modules:

| Module | Role |
|---|---|
| `server.py` | REST API, upload/chunking, glossary, meeting metadata, action routes, audio routes. |
| `main.py` | AgentBase-compatible app, static web mount, `/health`, and `/invocations`. |
| `brain.py` | Ingest, ask, digest, contradiction detection, forgotten decision surfacing, action follow-up, assignment, notification. |
| `db.py` | SQLite persistence for meetings, facts, actions, action links, contradictions, resurfaced items, and glossary. |
| `retrieve.py` | Evidence retrieval and ranking for Q&A. |
| `media.py` | Media conversion, chunking support, and playback audio handling. |
| `mailer.py` | Optional assignment and action digest email delivery. |
| `web/` | Static frontend served locally and on AgentBase. |

## Local Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with the required LLM/STT settings. Do not commit `.env`.

Run the local web app:

```bash
uvicorn server:app --host 127.0.0.1 --port 18092
```

Open:

```text
http://127.0.0.1:18092
```

AgentBase-compatible entrypoint:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Core API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | AgentBase runtime health check. |
| `GET` | `/api/health` | Local API health check. |
| `GET` | `/api/config` | Upload limit and chunk size advertised to the frontend. |
| `GET` | `/api/stats` | Counts for meetings, facts, actions, contradictions, and resurfaced items. |
| `POST` | `/api/ingest` | Ingest transcript, audio, or video. |
| `POST` | `/api/ingest/check` | Check whether an uploaded file was already ingested. |
| `POST` | `/api/uploads` | Start chunked upload session. |
| `POST` | `/api/uploads/{id}/chunks` | Upload one chunk. |
| `POST` | `/api/uploads/{id}/complete` | Complete chunked upload and ingest the assembled file. |
| `GET` | `/api/meetings` | Meeting library. |
| `GET` | `/api/meetings/{id}` | Meeting detail, transcript, and derived memory. |
| `PATCH` | `/api/meetings/{id}` | Edit meeting metadata such as title/date. |
| `DELETE` | `/api/meetings/{id}` | Delete meeting and derived records. |
| `GET` | `/api/meetings/{id}/audio` | Playback audio for a meeting. |
| `GET` | `/api/meetings/{id}/report.{fmt}` | Export report formats supported by the backend. |
| `GET` | `/api/actions` | List actions, optionally filtered by status. |
| `PATCH` | `/api/actions/{id}` | Update action status. |
| `POST` | `/api/actions/{id}/assign` | Assign an action owner and optionally notify by email. |
| `GET` | `/api/contradictions` | List detected contradictions. |
| `GET` | `/api/resurfaced` | List resurfaced forgotten decisions. |
| `GET` | `/api/digest` | Executive digest across the selected scope. |
| `POST` | `/api/ask` | Evidence-backed Q&A. |
| `POST` | `/api/followup` | Backend follow-up scan for action memory. |
| `POST` | `/api/scan_forgotten` | Backend scan for forgotten decisions. |
| `POST` | `/api/notify/actions` | Send action digest notification when mail is configured. |
| `GET` | `/api/glossary` | List learned terminology. |
| `POST` | `/api/glossary` | Add or correct a term. |
| `DELETE` | `/api/glossary/{id}` | Delete a learned term. |
| `GET` | `/api/glossary/suggestions` | Suggest terms from a meeting transcript. |
| `POST` | `/api/glossary/learn` | Learn terminology from an uploaded guide/transcript. |

Backend-only maintenance route:

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/redetect_contradictions` | Rebuild contradiction memory. Kept for maintenance; hidden from the current UI. |

AgentBase invocation route:

```http
POST /invocations
```

Example:

```json
{"action":"ask","question":"What decision changed since last meeting?"}
```

## Upload Notes

Memoir supports direct upload for small files and chunked upload for larger media. The deployed app advertises the current application limit through `/api/config`.

Playback depends on a stored audio file. For old meetings without stored playback audio, re-upload the source file to enable playback.

Recording status:

- `Upload audio` is the recommended flow.
- `Paste transcript` works for transcript-only demos.
- `Recording` is present as a placeholder, but mic recording is disabled until browser recording is fully wired.
- Tab/screen recording has been removed from the UI.

## Environment Notes

Do not commit real secrets. Keep them in `.env` locally or in AgentBase runtime environment variables.

Common local variables:

| Variable | Purpose |
|---|---|
| `MNEMOSYNE_UPLOAD_STAGING_DIR` | Optional staging path for chunked uploads. Defaults to `/tmp/mnemosyne_uploads`. |
| LLM/STT variables from `.env.example` | Used by transcription, analysis, contradiction detection, digest, and Q&A. |
| Mail variables from `.env.example` | Optional. Used by assignment emails and action digest notifications. |

AgentBase injects runtime variables such as `GREENNODE_CLIENT_ID`, `GREENNODE_CLIENT_SECRET`, `GREENNODE_AGENT_IDENTITY`, and `GREENNODE_ENDPOINT_URL`. Do not hard-code these in source files.

## Tests

Run the full test suite:

```bash
python -m pytest -q
```

Focused frontend contract tests:

```bash
python -m pytest tests/test_web_frontend.py -q
```

## AgentBase Notes

Runtime requirements:

- Container listens on port `8080`.
- `GET /health` returns HTTP 200.
- Static frontend is served by the AgentBase-compatible `main.py` app.
- Runtime size has been tested with the `memoir` runtime configuration.

## Design Artifacts

- `web/index.html`, `web/styles.css`, `web/app.js`: current Memoir frontend.
- `docs/FRONTEND_HANDOFF.md`: detailed API/frontend handoff notes.
- Local-only mockups and reversible UI snapshots are intentionally ignored by git through `.gitignore` (`web/*mockup.html`, `web/backup-designs/`).

## Commit Prep Checklist

- Confirm `.env` is not staged.
- Confirm local mockups and backup designs are not staged.
- Run `python -m pytest -q`.
- Check `git status --short`.
- Review generated/demo assets before committing.
- Push to the GitHub repository only after verifying the AgentBase endpoint and local app both load.
