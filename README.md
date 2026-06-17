<br />

<p align="center">
  <a>
    <img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/Mnemosyne.png" alt="Logo" width="140" height="140">
  </a>
  <h3 align="center">Logo</h3>
  <p align="center">
    Memory · Engine · Managing · Organizational · Intelligence · Resolution
    <br />
    <a href="youtube.com"><strong>Product Demo</strong></a>
    <br />
    <br />
    <a href="endpoint.com"><strong>Try it yourself»</strong></a>
    <br />
    <br />
  </p>
</p>    

 <br />

# Memoir

<p>Memoir là ứng dụng ghi nhớ quy trình họp, đóng vai trò như một bộ nhớ của tổ chức, giúp ghi nhớ toàn bộ lịch sử dự án và quy trình họp, phát hiện thay đổi và mẫu thuẫn theo thời gian của dự án, gợi nhắc quyết định bị lãng quên và trả lời câu hỏi xuyên suốt toàn bộ lịch sử họp.
</p>

> Built for **GreenNode Claw-a-thon 2026** as a Custom Agent on **GreenNode AgentBase**

<img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/memoir_explainer-screenshot.png" alt="Logo" width="500" height="450">

> **Data Compliance**: use synthetic, staged, public, or personal demo data only. Do not upload private customer meetings, internal recordings, or PII into a public demo runtime.

<!-- TABLE OF CONTENTS -->
<details open="open">
  <summary><h2 style="display: inline-block">Table of Contents</h2></summary>
  <ol>
    <li><a href="#description">Description</a></li>
    <li><a href="#Design">Design</a></li>
    <li><a href="#key-takeaways">Key TakeAways</a></li>
    <li><a href="#future-work">Future Work</a></li>
    <li><a href="#thank-you">Thank You</a></li>
  </ol>
</details>

> Built for **GreenNode Claw-a-thon 2026** as a Custom Agent on **GreenNode AgentBase**
> 
## What It Does

- Ingests `.txt`, `.md`, audio, or video files through chunked upload.
- Transcribes media with STT, applies glossary/terminology correction, and extracts structured memory.
- Stores meetings, transcripts, decisions, actions, facts/evidence, risks, contradictions, resurfaced items, terminology, playback audio, and group metadata in SQLite.
- Groups meetings by explicit `group_title`, with title-based fallback for older rows.
- Lets users drag meeting cards into groups and double-click group titles to rename them.
- Scopes local data by browser owner using `localStorage` plus the `X-Memoir-Owner` request header.
- Shows Summary, Actions, and Evidence tabs for the selected meeting.
- Answers Q&A only within the current selected meeting group/topic.
- Supports action assignment, owner save, and optional email notification.
- Lets users edit terminology, save it, and refresh a meeting so transcript and derived memory are reprocessed with the updated terminology.

## What Makes It Different

- Most meeting tools summarize one call. Memoir compares each selected meeting against prior meetings in the same topic/group.
- Contradictions are treated as concrete conflicts between dated meeting memories, not generic risk notes.
- Q&A is scoped to the active group/topic, so answers stay relevant to the selected meeting context.
- Terminology is user-correctable after ingest; users can refresh a meeting with the updated glossary instead of re-uploading from scratch.
- Meeting organization is user-controlled through drag/drop groups and inline group rename, independent from meeting-title rename.
- The same backend powers the local web app and the AgentBase runtime.

## Architecture

```text
Browser UI
  |
  | /api/* with X-Memoir-Owner
  v
FastAPI server.py
  |
  +--> chunked upload / progress / static web
  +--> meeting, action, glossary, group APIs
  |
  v
brain.py
  |
  +--> transcribe.py + media.py     media -> transcript
  +--> analyze.py + models.py       transcript -> structured report
  +--> retrieve.py                  scoped memory retrieval
  +--> db.py                        SQLite memory store
  +--> mailer.py                    optional action email
```

AgentBase uses `main.py`, which exposes the agent invocation contract and mounts the same FastAPI web app at `/`.

## Project Layout

```text
Mnemosyne/
  analyze.py          Transcript -> MeetingReport extraction
  brain.py            Ingest, Q&A, digest, contradiction, follow-up, terminology refresh
  config.py           Environment variables and runtime defaults
  db.py               SQLAlchemy/SQLite memory store and light migrations
  llm.py              OpenAI-compatible LLM client wrapper
  main.py             AgentBase entrypoint; mounts the web app
  mailer.py           Optional SMTP email for assignments/action digest
  media.py            Audio conversion, chunking, duration helpers
  models.py           Pydantic contracts for reports, facts, answers
  report.py           DOCX/PDF report rendering helpers
  retrieve.py         Lexical retrieval over stored meeting memory
  server.py           FastAPI REST API and static frontend
  transcribe.py       STT and term-correction pipeline
  web/                Browser UI assets
  tests/              Unit and API/frontend contract tests
  docs/               Product specs and handoff notes
```

## Backend Modules

| Module | Responsibility |
|---|---|
| `server.py` | REST API, static frontend, chunked upload, progress, owner scoping, meeting/group/action/glossary routes. |
| `main.py` | GreenNode AgentBase entrypoint, `/health`, `/invocations`, and web app mount. |
| `brain.py` | Core orchestration: ingest, Q&A, summary/digest, contradictions, resurfaced decisions, action follow-up, assignment, terminology refresh. |
| `db.py` | SQLite persistence, SQLAlchemy models, owner filtering, group metadata, display ids, light migrations. |
| `models.py` | Pydantic contracts for LLM output and memory objects. |
| `analyze.py` | Transcript analysis into structured meeting reports. |
| `transcribe.py` | STT request handling and terminology correction. |
| `media.py` | Audio/video conversion, chunking, duration and playback helpers. |
| `retrieve.py` | Lexical retrieval over scoped meeting memory for Q&A. |
| `mailer.py` | Optional assignment/action email delivery. |
| `report.py` | DOCX/PDF report helpers. |
| `config.py` | Environment variables and model/runtime defaults. |

## Frontend Modules

| File | Responsibility |
|---|---|
| `web/index.html` | App shell, sidebar, workspace tabs, Q&A panel, ingest drawer. |
| `web/styles.css` | Memoir visual system, responsive layout, cards, audio player, terminology, evidence/transcript panes. |
| `web/app.js` | Client state, API calls, owner header, meeting grouping, ingest/upload progress, action assignment, terminology editing, Q&A, tab rendering. |
| `web/assets/mnemosyne-logo.png` | Memoir logo asset. |
| `web/assets/add-user.png` | Action assignment icon asset. |

## Requirements

- Python 3.12
- `ffmpeg` available on `PATH`
- An OpenAI-compatible LLM/STT endpoint and API key
- Optional SMTP credentials for assignment emails
- Optional Docker for AgentBase image builds

Runtime configuration starts from `.env.example`. Local secrets belong in `.env`, which must not be committed.

## Related Docs

- `docs/SPEC.md` - current product and technical specification.
- `docs/FRONTEND_HANDOFF.md` - frontend/API handoff notes.
- `.env.example` - local runtime configuration template.
- `Dockerfile` - AgentBase-compatible container build.
- `tests/` - executable contracts for backend, frontend markup/CSS, mailer, and memory behavior.
