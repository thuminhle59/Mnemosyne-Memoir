# Memoir

<br />
<p align="center">
  <a>
    <img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/Mnemosyne_logo.png" alt="Logo" width="150" height="150">
  </a>
  <p align="center">
    Memory · Engine · Managing · Organizational · Intelligence · Resolution
  </p>
</p>
<br />

<p>
  Memoir là ứng dụng ghi nhớ theo quy trình các cuộc họp. Thay vì chỉ tóm tắt một meeting riêng lẻ, Memoir lưu lại meeting memory theo chuỗi: quyết định nào đã được chốt, action nào còn mở, evidence nào đang hỗ trợ, và nội dung mới có mâu thuẫn với các meeting trước hay không.
</p>
<p>
Từ đó, người dùng có thể đặt câu hỏi về nội dung cuộc họp hoặc tất cả những cuộc họp liên quan, gửi email đến team member để nhắc action cần làm, và nhận cảnh báo khi phát hiện mâu thuẫn giữa các phiên họp khác nhau.
</p>

<img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/memoir_explainer-screenshot.png" alt="Memoir screenshot" width="1000" height="800">

> Built for **GreenNode Claw-a-thon 2026** as a Custom Agent on **GreenNode AgentBase**.

> Lưu ý dữ liệu: chỉ nên dùng synthetic data, demo data, public data hoặc dữ liệu cá nhân được phép dùng. Không upload meeting nội bộ, recording của khách hàng, PII, hoặc dữ liệu nhạy cảm lên public demo runtime.

<p align="center">
  <a href="https://www.youtube.com/watch?v=K4t8Aiikbvs&t=3s"><strong>Product Demo</strong></a>
  <br />
  <br />
  <a href="https://endpoint-a2567aee-2312-4f87-94fb-bb40b89f4a12.agentbase-runtime.aiplatform.vngcloud.vn"><strong>Try it yourself »</strong></a>
  <br />
</p>

<details open="open">
  <summary><h2 style="display: inline-block">Table of Contents</h2></summary>
  <ol>
    <li><a href="#how-memoir-works">How Memoir Works</a></li>
    <li><a href="#architecture">Architecture</a></li>
    <li><a href="#backend-modules">Backend Modules</a></li>
    <li><a href="#frontend-modules">Frontend Modules</a></li>
    <li><a href="#project-layout">Project Layout</a></li>
    <li><a href="#thank-you">Thank You/a></li>
  </ol>
</details>

## How Memoir Works

- Người dùng upload file audio, transcript hoặc live-recording cuộc họp.
- Memoir tự động trích xuất quyết định, mâu thuẫn, actions, risks, và lưu toàn bộ vào bộ nhớ.
- Bắt contradiction: chỉ ra khi quyết định mới mâu thuẫn với meeting trước, kèm timestamp để truy vết.
- Tóm tắt risks cần lưu ý và actions kèm deadline thực hiện.
- Q&A theo context của dự án: Memoir trả lời trong phạm vi group/dự án của meeting.
- Hỗ trợ assign action và gửi email follow-up nhắc nhở đến team member.

> Memoir nhớ theo chuỗi meeting: so sánh meeting hiện tại với lịch sử dự án, không chỉ xử lý từng meeting rời rạc.

## Architecture

```text
Browser UI
  |
  | /api/* + X-Memoir-Owner
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

# Thank You
Xin cảm ơn GreenNode, VNG và Zalopay đã tài trợ và tạo cơ hội cho starters tham gia xây dựng AI Agent tại GreenNode Claw-a-thon 2026.

Nếu thích idea của Memoir, hãy ủng hộ bằng cách vote cho team Mnemosyne tại Claw-a-thon nhé :)
