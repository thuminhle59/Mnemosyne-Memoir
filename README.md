# Memoir - Memory Decision Agent

Memoir is a meeting memory agent. It ingests transcripts, audio, or video, then builds a long-running decision layer across meetings: what was decided, what changed, what was forgotten, who owns the next action, and what evidence supports each answer.

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

## What Makes It Different

Most meeting tools summarize one call. Memoir compares each new meeting against the history of prior meetings.

- **Executive Brief**: decisions, contradictions, forgotten decisions, risks, and blockers.
- **Memory Ops**: action memory with pending, completed, and canceled states.
- **Evidence Lab**: evidence graph plus transcript evidence with clickable timestamps.
- **Contradiction Radar**: flags claims that conflict with earlier facts or decisions.
- **Resurfaced Decisions**: brings back forgotten commitments and unresolved action debt.
- **Evidence Q&A**: answers across meeting memory with citations.
- **Terminology Learning**: lets users teach team-specific vocabulary and confirm suggested terms.
- **Large File Upload**: supports chunked audio/video upload for longer meetings.
- **Audio Playback**: stores playable audio when possible and seeks to evidence timestamps.

## Product Layout

Memoir is a three-panel web app:

- **Left sidebar**: meeting library, editable meeting names, delete actions, terminology.
- **Middle workspace**: Executive Brief, Memory Ops, Evidence Lab, and audio playback.
- **Right sidebar**: evidence-backed Q&A across all meeting memory.

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

Important modules:

| Module | Role |
|---|---|
| `server.py` | REST API, upload/chunking, glossary, meeting metadata, audio routes. |
| `main.py` | AgentBase-compatible app and `/invocations` endpoint. |
| `brain.py` | Ingest, ask, digest, contradiction detection, follow-up logic. |
| `db.py` | SQLite persistence for meetings, facts, actions, contradictions, glossary. |
| `media.py` | Media conversion and playback audio storage. |
| `web/` | Static frontend served locally and on AgentBase. |

## Local Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with the required LLM/STT settings. Do not commit `.env`.

Run locally:

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
| `GET` | `/health` | Runtime health check. |
| `GET` | `/api/config` | Upload limits and chunk size. |
| `POST` | `/api/ingest` | Ingest transcript/audio/video. |
| `POST` | `/api/uploads/*` | Chunked upload for large files. |
| `GET` | `/api/meetings` | Meeting library. |
| `GET` | `/api/meetings/{id}` | Meeting detail and transcript evidence. |
| `PATCH` | `/api/meetings/{id}` | Edit meeting metadata. |
| `GET` | `/api/meetings/{id}/audio` | Playback audio. |
| `POST` | `/api/ask` | Evidence-backed Q&A. |
| `GET` | `/api/digest` | Executive digest. |
| `POST` | `/api/followup` | Refresh action memory. |
| `GET/POST` | `/api/glossary*` | Terminology learning. |

AgentBase invocation route:

```http
POST /invocations
```

Example:

```json
{"action":"ask","question":"What decision changed since last meeting?"}
```

## Upload Notes

Memoir supports direct upload for small files and chunked upload for larger media. The deployed app currently advertises a 500 MB application upload limit through `/api/config`.

For old meetings without stored playback audio, re-upload the source file to enable playback.

## Tests

```bash
python -m pytest -q
```

## AgentBase Notes

Runtime requirements:

- Container listens on port `8080`.
- `GET /health` returns HTTP 200.
- AgentBase injects runtime variables such as `GREENNODE_CLIENT_ID`, `GREENNODE_CLIENT_SECRET`, `GREENNODE_AGENT_IDENTITY`, and `GREENNODE_ENDPOINT_URL`. Do not set these manually in `.env`.

## Design Artifacts

- `web/index.html`, `web/styles.css`, `web/app.js`: current frontend.
- `web/mockup-a.html`, `web/mockup-a.css`: interactive frontend mockup kept for reference.
- `web/backup-designs/`: snapshot before the Claude-style redesign.
- `docs/FRONTEND_HANDOFF.md`: detailed API/frontend handoff notes.

