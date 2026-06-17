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

Memoir là ứng dụng ghi nhớ quyết định từ các cuộc họp. Thay vì chỉ tóm tắt một transcript riêng lẻ, Memoir lưu lại meeting memory theo chuỗi: quyết định nào đã được chốt, action nào còn mở, evidence nào đang hỗ trợ, và nội dung mới có mâu thuẫn với các meeting trước hay không.

<img src="https://github.com/thuminhle59/Mnemosyne-Memoir/blob/main/assets/memoir_explainer-screenshot.png" alt="Memoir screenshot" width="1000" height="800">

> Built for **GreenNode Claw-a-thon 2026** as a Custom Agent on **GreenNode AgentBase**.

> Lưu ý dữ liệu: chỉ nên dùng synthetic data, demo data, public data hoặc dữ liệu cá nhân được phép dùng. Không upload meeting nội bộ, recording của khách hàng, PII, hoặc dữ liệu nhạy cảm lên public demo runtime.

<p align="center">
  <a href="https://www.youtube.com/watch?v=NsgFB0NUdfw"><strong>Product Demo</strong></a>
  <br />
  <br />
  <a href="https://endpoint-a2567aee-2312-4f87-94fb-bb40b89f4a12.agentbase-runtime.aiplatform.vngcloud.vn"><strong>Try it yourself »</strong></a>
  <br />
</p>

<details open="open">
  <summary><h2 style="display: inline-block">Table of Contents</h2></summary>
  <ol>
    <li><a href="#memoir-làm-gì">Memoir Làm Gì</a></li>
    <li><a href="#điểm-khác-biệt">Điểm Khác Biệt</a></li>
    <li><a href="#architecture">Architecture</a></li>
    <li><a href="#backend-modules">Backend Modules</a></li>
    <li><a href="#frontend-modules">Frontend Modules</a></li>
    <li><a href="#project-layout">Project Layout</a></li>
    <li><a href="#requirements">Requirements</a></li>
    <li><a href="#tài-liệu-liên-quan">Tài Liệu Liên Quan</a></li>
  </ol>
</details>

## Memoir Làm Gì

Memoir giúp team biến transcript, audio, hoặc video meeting thành bộ nhớ quyết định có thể tra cứu và so sánh lại về sau.

- Ingest file `.txt`, `.md`, audio, hoặc video bằng chunked upload.
- Transcribe media bằng STT, sửa terminology/tên riêng, rồi extract structured memory.
- Lưu meetings, transcript, decisions, actions, facts/evidence, risks, contradictions, resurfaced items, terminology, playback audio và group metadata vào SQLite.
- Group meetings theo `group_title`; nếu data cũ chưa có `group_title`, app fallback theo title hiện tại.
- Cho phép kéo thả meeting card vào group khác và double-click group title để rename inline.
- Tách dữ liệu local theo browser owner bằng `localStorage` và header `X-Memoir-Owner`.
- Hiển thị các tab `Summary`, `Actions`, và `Evidence` cho meeting đang chọn.
- Q&A chỉ trả lời trong phạm vi group/topic của meeting đang chọn.
- Hỗ trợ assign action, lưu owner/email và gửi email follow-up nếu đã cấu hình SMTP.
- Cho phép edit terminology, save, rồi refresh meeting để reprocess transcript và derived memory theo terminology mới.

## Điểm Khác Biệt

Memoir khác các meeting summarizer thông thường ở chỗ nó tập trung vào **decision memory** thay vì chỉ tạo một bản tóm tắt.

- **Nhớ theo chuỗi meeting**: Memoir so sánh meeting đang chọn với các meeting trước trong cùng group/topic.
- **Bắt contradiction có ngữ cảnh**: contradictions là mâu thuẫn giữa các claim/quyết định cụ thể, có cite meeting number để truy vết.
- **Decision-first**: UI ưu tiên decisions, actions, evidence và risks quan trọng nhất, tránh summary dài và khó scan.
- **Terminology-aware**: user có thể sửa glossary/terminology sau ingest và refresh lại meeting mà không cần upload lại file.
- **Q&A đúng phạm vi**: câu trả lời chỉ dựa trên meetings cùng group/topic, giảm việc lẫn nội dung giữa các topic.
- **Workflow sau meeting**: action có owner, email, status và deadline để follow up tiếp sau khi họp.
- **Cùng một backend cho local và deploy**: FastAPI app local và AgentBase runtime dùng chung core ingest/reasoning.

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

Khi deploy lên AgentBase, `main.py` expose `/health`, `/invocations` và mount cùng FastAPI web app tại `/`.

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

## Requirements

Để clone repo và chạy/build app ở local, máy cần có:

- Python 3.12.
- `ffmpeg` có sẵn trên `PATH` để xử lý audio/video ingest.
- OpenAI-compatible LLM/STT endpoint và API key.
- Docker nếu muốn build container hoặc deploy lên AgentBase.
- SMTP credentials nếu muốn dùng tính năng gửi email assignment.

Setup local:

```bash
git clone <repo-url>
cd <repo-folder>/Mnemosyne

python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

Sau đó mở `.env` và điền các giá trị tối thiểu:

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

## Tài Liệu Liên Quan

- `docs/SPEC.md` - product và technical specification hiện tại.
- `docs/FRONTEND_HANDOFF.md` - frontend/API handoff notes.
- `.env.example` - template cấu hình runtime local.
- `Dockerfile` - container build tương thích AgentBase.
- `tests/` - executable contracts cho backend, frontend markup/CSS, mailer và memory behavior.
