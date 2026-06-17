<br />
<p align="center">
  <a>
    <img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/Mnemosyne_cropped.png" alt="Logo" width="150" height="150">
  </a>
  <p align="center">
    Memory · Engine · Managing · Organizational · Intelligence · Resolution
  </p>
</p>    
 <br />
 
# Memoir

<p>Memoir là ứng dụng ghi nhớ quy trình họp, đóng vai trò như một bộ nhớ của tổ chức, giúp ghi nhớ toàn bộ lịch sử dự án, tóm tắt quá trình cuộc họp, phát hiện thay đổi và mẫu thuẫn theo thời gian, gợi nhắc quyết định bị lãng quên và trả lời câu hỏi xuyên suốt toàn bộ lịch sử.
</p>

> Built for **GreenNode Claw-a-thon 2026** as a Custom Agent on **GreenNode AgentBase**

<img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/memoir_explainer-screenshot.png" alt="Logo" width="1000" height="800">

> **Data Compliance**: use synthetic, staged, public, or personal demo data only. Do not upload private customer meetings, internal recordings, or PII into a public demo runtime.

  <br />
  <a href="youtube.com"><strong>Product Demo</strong></a>
  <br />
  <a href="endpoint.com"><strong>Try it yourself»</strong></a>
  <br />
    
<!-- TABLE OF CONTENTS -->
<details open="open">
  <summary><h2 style="display: inline-block">Table of Contents</h2></summary>
  <ol>
    <li><a href="#what-it-does">What It Does</a></li>
    <li><a href="#architecture">Architecture</a></li>
    <li><a href="#project-layout">Project Layout/a></li>
    <li><a href="#backend-modules">Backend Modules/a></li>
    <li><a href="#frontend-modules">Frontend Modules/a></li>
    <li><a href="#requirements">Requirements/a></li>
    <li><a href="#related-docs">Related Docs/a></li>
    <li><a href="#thank-you">Thank You</a></li>
  </ol>
</details>

> Built for **GreenNode Claw-a-thon 2026** as a Custom Agent on **GreenNode AgentBase**
> 
## What It Does

- Ingest file .txt, .md, audio, hoặc video bằng chunked upload.
- Transcribe media bằng STT, rồi extract structured memory.
- Lưu meetings, transcript, decisions, actions, facts/evidence, risks, contradictions, resurfaced items, terminology vào SQLite.
- Nhớ theo chuỗi meeting: so sánh meeting hiện tại với lịch sử, không xử lý từng transcript rời rạc.
- Tóm tắt cuộc học, quyết định đã chốt và risks/blockers.
- Bắt contradiction: chỉ ra khi claim/decision mới mâu thuẫn với meeting trước, kèm timestamp để truy vết.
- Q&A theo context: trả lời trong phạm vi group/topic của meeting đang chọn.
- Hỗ trợ assign action và gửi email follow-up nhắc nhở.

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

| Module | Vai trò |
|---|---|
| `server.py` | REST API, static frontend, chunked upload, progress, owner scoping, meeting/group/action/glossary routes. |
| `main.py` | AgentBase entrypoint, `/health`, `/invocations`, và web app mount. |
| `brain.py` | Core orchestration: ingest, Q&A, summary/digest, contradictions, resurfaced decisions, action follow-up, assignment, terminology refresh. |
| `db.py` | SQLite persistence, SQLAlchemy models, owner filtering, group metadata, display ids, light migrations. |
| `models.py` | Pydantic contracts cho LLM output và memory objects. |
| `analyze.py` | Phân tích transcript thành structured meeting report. |
| `transcribe.py` | STT request handling và terminology correction pipeline. |
| `media.py` | Audio/video conversion, chunking, duration và playback helpers. |
| `retrieve.py` | Lexical retrieval trên scoped meeting memory cho Q&A. |
| `mailer.py` | Optional SMTP email delivery cho assignment/action. |
| `report.py` | DOCX/PDF report helpers. |
| `config.py` | Environment variables và model/runtime defaults. |

## Frontend Modules

| File | Vai trò |
|---|---|
| `web/index.html` | App shell, sidebar, workspace tabs, Q&A panel, ingest drawer. |
| `web/styles.css` | Visual system, responsive layout, cards, audio player, terminology, evidence/transcript panes. |
| `web/app.js` | Client state, API calls, owner header, meeting grouping, ingest/upload progress, action assignment, terminology editing, Q&A, tab rendering. |
| `web/assets/mnemosyne-logo.png` | Logo Memoir. |
| `web/assets/add-user.png` | Icon assign owner/action. |

## Requirements

Để clone repo và chạy/build app ở local, máy cần có:

- Python 3.12.
- `ffmpeg` có sẵn trên `PATH` để xử lý audio/video ingest.
- OpenAI-compatible LLM/STT endpoint và API key.
- Docker nếu muốn build container hoặc deploy lên AgentBase.
- SMTP credentials nếu muốn dùng tính năng gửi email assignment.

Setup local:

```bash
LLM_API_KEY=<your-api-key>
LLM_BASE_URL=<openai-compatible-base-url>
STT_URL=<openai-compatible-stt-url>
STT_MODEL=<stt-model>
DATABASE_URL=sqlite:///mnemosyne.db
```

Chạy app local:

```bash
uvicorn server:app --host 127.0.0.1 --port 18093
```

Mở browser tại:

```text
http://127.0.0.1:18093/
```

Chạy test:

```bash
PYTHONPATH=. pytest -q
```

Build Docker image:

```bash
docker build --platform linux/amd64 -t memoir:local .
docker run --rm -p 8080:8080 --env-file .env memoir:local
```

Sau khi container chạy, kiểm tra:

```text
http://127.0.0.1:8080/health
```

Local secrets nên để trong `.env` và không commit file này.

## Related Docs

- `docs/SPEC.md` - product và technical specification hiện tại.
- `docs/FRONTEND_HANDOFF.md` - frontend/API handoff notes.
- `.env.example` - template cấu hình runtime local.
- `Dockerfile` - container build tương thích AgentBase.
- `tests/` - executable contracts cho backend, frontend markup/CSS, mailer và memory behavior.

## Thank You

Cảm ơn BTC GreenNode, VNG và Zalopay đã tạo cơ hội cho VNG starters học hỏi và tham gia cuộc thi xây dựnng AI Agent tại GreenNode Claw-a-thon 2026.

Nếu bạn thích idea của mình, hãy ủng hộ bằng cách cho vote cho team Mnemosyne nhé :)
