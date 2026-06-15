# Memoir - Memory Decision Agent

Decision memory for meetings. Memoir ingests transcripts, audio, or video, then turns them into a searchable long-running memory layer: executive briefs, decision drift, contradictions, resurfaced forgotten decisions, action tracking, evidence-backed Q&A, and audio playback tied to timestamps.

Built for GreenNode Claw-a-thon 2026 as a Custom Agent on GreenNode AgentBase.

> Data compliance: use synthetic, staged, or personal demo meeting data only. Do not upload internal/customer meetings or PII.

## Why Memoir Is Different

Most meeting tools summarize one call. Memoir compares the current meeting against prior meeting history.

| Capability | What it does |
|---|---|
| Executive Brief | Summarizes decisions, contradictions, forgotten decisions, risks, and blockers in scrollable review panels. |
| Memory Ops | Tracks actions across meetings and lets users mark items as pending, completed, or canceled. |
| Evidence Lab | Shows an evidence graph and transcript evidence with clickable timestamps. |
| Contradiction Radar | Flags claims that conflict with earlier decisions or facts. |
| Resurfaced Decisions | Brings back forgotten commitments, rejected ideas, and unresolved action debt. |
| Evidence Q&A | Answers questions across meeting memory with citations instead of vibe-only summaries. |
| Terminology Learning | Lets users add domain terms and confirm suggested terms so the agent better understands team vocabulary. |
| Large File Upload | Supports chunked upload for large audio/video files, with a configured 500 MB app limit. |
| Audio Playback | Stores playable audio when possible and seeks to evidence timestamps from brief/transcript items. |

## Current Deployment

Production AgentBase endpoint:

```text
https://endpoint-67bc4eb0-570b-4ede-b08b-0f25cfe55fdd.agentbase-runtime.aiplatform.vngcloud.vn
```

Runtime:

```text
memoir-4x8
runtime-5a34befa-a3fb-49df-8aa6-51d04f9b2f9f
runtime-s2-general-4x8
```

Health checks:

```bash
curl -i https://endpoint-67bc4eb0-570b-4ede-b08b-0f25cfe55fdd.agentbase-runtime.aiplatform.vngcloud.vn/health
curl -i https://endpoint-67bc4eb0-570b-4ede-b08b-0f25cfe55fdd.agentbase-runtime.aiplatform.vngcloud.vn/api/config
```

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
   +--> db.py SQLite memory store
```

AgentBase container entrypoint:

```text
main:app -> FastAPI + AgentBase /invocations + static web dashboard
```

Important modules:

| Module | Role |
|---|---|
| `server.py` | Dashboard REST API, upload/chunking routes, glossary, meeting metadata, audio routes. |
| `main.py` | AgentBase-compatible app and `/invocations` entrypoint. |
| `brain.py` | Ingest, ask, digest, contradiction detection, follow-up logic. |
| `db.py` | SQLite persistence for meetings, facts, actions, contradictions, glossary. |
| `media.py` | Media conversion and playback audio storage. |
| `web/` | Static frontend served locally and on AgentBase. |
| `tests/` | Unit and frontend contract tests. |

## Local Setup

```bash
cd /Users/thule/Desktop/DSProjects/Zalopay/Claw-a-thon/Mnemosyne

python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with the required LLM/STT settings. Do not commit `.env`.

Run the AgentBase-compatible local app:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

Run the local frontend/API dev server:

```bash
uvicorn server:app --host 127.0.0.1 --port 18092
```

Open:

```text
http://127.0.0.1:18092
```

## Main API Routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | AgentBase health check. |
| `GET` | `/api/config` | Upload limits and chunk size. |
| `GET` | `/api/meetings` | List memory sources. |
| `GET` | `/api/meetings/{id}` | Meeting detail, transcript, decisions, facts, actions. |
| `PATCH` | `/api/meetings/{id}` | Edit meeting/source title metadata. |
| `DELETE` | `/api/meetings/{id}` | Delete a meeting. |
| `GET` | `/api/meetings/{id}/audio` | Playback audio if stored. |
| `POST` | `/api/ingest` | Direct transcript/audio/video ingest. |
| `POST` | `/api/uploads` | Start chunked upload for large media. |
| `POST` | `/api/uploads/{id}/chunks` | Upload one chunk. |
| `POST` | `/api/uploads/{id}/complete` | Complete chunked upload and ingest. |
| `POST` | `/api/ask` | Evidence-backed Q&A across memory. |
| `GET` | `/api/digest` | Executive digest. |
| `POST` | `/api/followup` | Refresh follow-up/action memory. |
| `GET` | `/api/glossary` | List terminology. |
| `POST` | `/api/glossary` | Add terminology or misheard mapping. |
| `GET` | `/api/glossary/suggestions` | Suggested terms from current meeting. |

AgentBase invocation route:

```http
POST /invocations
```

Example payloads:

```json
{"action":"ingest","text":"<transcript>","title":"Weekly sync","date":"2026-06-15"}
{"action":"ask","question":"What decision changed since last meeting?"}
{"action":"digest","scope":"all"}
{"action":"followup"}
```

## Upload Notes

The frontend reads `/api/config` and uses chunked upload for larger files.

Current deployed config:

```json
{"max_upload_bytes":524288000,"max_upload_mb":500,"upload_chunk_bytes":16777216}
```

Recommended demo flow:

1. Use small `.mp3`, `.mp4`, `.txt`, or `.md` files for fast tests.
2. For large video, expect several minutes for upload and backend processing.
3. If playback is unavailable for old records, re-upload the file so Memoir can store playback audio.

## Tests

```bash
source venv/bin/activate
python -m pytest -q
```

Current suite: 72 tests.

## Docker And AgentBase

Build for AgentBase runtime:

```bash
docker build --platform linux/amd64 -t vcr.vngcloud.vn/111480-abp111659/memoir-4x8:<tag> .
docker push vcr.vngcloud.vn/111480-abp111659/memoir-4x8:<tag>
```

Runtime requirements:

- Container listens on port `8080`.
- `GET /health` returns HTTP 200.
- Runtime env variables such as `GREENNODE_CLIENT_ID`, `GREENNODE_CLIENT_SECRET`, `GREENNODE_AGENT_IDENTITY`, and `GREENNODE_ENDPOINT_URL` are injected by AgentBase and should not be set manually in `.env`.

## GitHub

Remote:

```bash
git remote -v
```

Push workflow:

```bash
git status
git add README.md
git commit -m "Update README"
git push origin main
```

Never commit local secrets or generated demo data:

- `.env`
- `.greennode.json`
- `.gh-config/`
- `*.db`
- uploaded audio/video files

## Design Artifacts

- `web/index.html`, `web/styles.css`, `web/app.js`: current frontend.
- `web/mockup-a.html`, `web/mockup-a.css`: interactive frontend mockup kept for reference.
- `web/backup-designs/`: snapshot before the Claude-style redesign.
- `docs/FRONTEND_HANDOFF.md`: detailed API/frontend handoff notes.
