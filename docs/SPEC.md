# Memoir Product and Technical Spec

Memoir is the current product name for the Mnemosyne meeting-memory agent. It turns meeting transcripts, audio, or video into a persistent decision memory that can be searched, compared, corrected, and queried across related meetings.

## 1. Product Goal

Memoir should answer one question well:

> What did this team decide, what changed, who owns the next work, and what evidence supports it?

The first screen is the working product, not a landing page. Users ingest files, browse grouped meetings, inspect extracted memory, edit terminology, refresh analysis, assign actions, and ask questions against the current group/topic.

## 2. Current UX Contract

### Left Sidebar

- Shows owner-scoped meeting library.
- Meetings are grouped by `group_title`.
- Old meetings without `group_title` fall back to derived grouping from meeting title.
- Group count badges are hidden.
- Group titles wrap and can be renamed inline by double-clicking.
- Meeting cards can be dragged into another group; drop saves the new `group_title`.
- Meeting title rename remains separate from group rename.
- Renaming a meeting title must not regroup a meeting once it has an explicit `group_title`.
- A small note under time filters says `Drag and drop meeting into group`.
- Terminology is editable, filterable, and positioned above the footer so it does not overlap `Remembered by Memoir`.

### Main Workspace

Tabs:

| Tab | Purpose |
|---|---|
| `Summary` | Important selected-meeting summary, decisions, contradictions, risks/blockers, and audio playback. |
| `Actions` | Action completion, owner assignment, optional email send. |
| `Evidence` | Evidence list and transcript panel. |

Summary constraints:

- Do not show literal labels such as `context`, `decisions`, `risk`, or `next step` in the summary text.
- Keep risk and next-step summary to the single most important sentence each.
- Decisions can include important facts or decision-like summary items when they are concrete.
- Decision rows show timestamps where available and do not need original quotes.
- Contradictions should be phrased as a natural conflict explanation and cite meeting numbers in parentheses, instead of mechanically saying `Trước -> Nay`.

Evidence constraints:

- The tab label is `Evidence`.
- The section title is `Evidences`.
- Evidence list can be filtered by type with dropdown checkboxes.
- Transcript has its own title, filter at the top right, and internal scroll.
- Transcript line timestamp chips are hidden in the main transcript body.
- Evidence and transcript cards use fixed height with internal scrolling.

Audio playback constraints:

- Do not show meeting title in the audio player.
- Use compact minimized-player styling.
- Audio seeks to approximate timestamps where evidence/action timestamps are available.

### Right Q&A Panel

- Header is `Ask Memoir`.
- Scope line is `Answer across memory, not just one transcript` and remains on one line.
- Input placeholder is `Ask Memoir anything`.
- Enter submits, Shift+Enter inserts a newline.
- Suggestions use Vietnamese phrasing without unnecessary English jargon.
- Q&A answers must not show a separate citation section in the UI.
- Q&A is scoped to meetings in the same group/topic as the selected meeting.

### Ingest Drawer

- File upload shows only one selected filename next to the Upload button.
- Ingest shows one warning line:
  `For fastest ingest, upload audio or paste transcript. Video may take several minutes. Please keep this window open`
- Progress percent and bar update continuously from upload through ingest completion.
- All file inputs use chunked upload.
- `Remembered by Memoir` is centered in its row.

## 3. Data Ownership and Local Isolation

The app uses lightweight owner scoping for local/demo use:

- Frontend creates `memoir_owner_id` in `localStorage`.
- Every API request includes `X-Memoir-Owner`.
- Backend filters meetings and glossary by `owner_id`.
- New meetings and glossary rows are stored with the current owner id.
- Incognito starts with a different owner id and therefore an empty library.

This is not authentication. It is a local/demo isolation layer so user A and user B do not see each other's local data in the same shared app runtime.

## 4. Data Model

### Pydantic Contracts

| Type | Purpose |
|---|---|
| `MeetingReport` | Full extracted report, summary brief, decisions, actions, risks, transcript. |
| `SummaryBrief` | Compact summary fields normalized to short important sentences. |
| `Decision` | Concrete decision/fact-like decision with optional timestamp and quote. |
| `ActionItem` | Task, owner, deadline, priority, status, timestamp, quote. |
| `KnowledgeFact` | Atomic evidence unit for reasoning. |
| `Contradiction` | Conflict between two fact rows. |
| `Citation` | Meeting/date/quote/timestamp provenance for backend answers. |
| `Answer` | Q&A result. |

### SQL Tables

| Table | Purpose |
|---|---|
| `meetings` | One row per meeting; includes title, date, transcript, report JSON, source file, `group_title`, `owner_id`, hashes, audio timing metadata. |
| `action_items` | Denormalized actions from reports, with owner/status/deadline. |
| `action_links` | Follow-up links from older action to later meeting. |
| `knowledge_facts` | Atomic facts/evidence extracted from meetings. |
| `contradictions` | Fact-pair conflicts detected during ingest/rebuild. |
| `resurfaced` | Old rejected/forgotten decisions raised again. |
| `glossary` | Owner-scoped canonical terms and optional wrong-term mappings. |

Migration rule:

- `db.init_db()` must keep light migrations for new columns so older local SQLite files still boot.
- `group_title` and `owner_id` must be nullable to preserve old demo data.

## 5. Ingest Pipeline

```text
file/text input
  -> chunked upload (files only)
  -> assemble upload
  -> media conversion/chunking when needed
  -> STT
  -> deterministic + LLM terminology correction
  -> analyze transcript into MeetingReport
  -> extract KnowledgeFact rows
  -> save meeting/actions/facts
  -> detect contradictions
  -> scan resurfaced decisions
  -> store playback audio when available
```

Important rules:

- Preserve proper nouns and English product/team names when they are already reasonable.
- Glossary refresh applies current terminology to transcript/title and reanalyzes derived memory.
- Same-file upload can be detected by audio hash.
- Upload progress is backend-visible through `/api/ingest/progress/{job_id}`.
- Media staging lives in `MNEMOSYNE_UPLOAD_STAGING_DIR`.

## 6. Reasoning Rules

### Decisions

- Extract only concrete decisions or concrete fact-like statements useful for decision memory.
- Include important summary-like facts if they represent a clear operational commitment, timeline, scope, owner, threshold, or go/no-go statement.
- Prefer exact English terms and proper nouns over Vietnamese phonetic substitutions.
- Add a timestamp when the transcript/audio evidence can support one.
- Do not require quote display in the UI.

### Contradictions

- A contradiction is a real conflict between two concrete claims.
- Avoid false positives for vague risks, preferences, or unrelated statements.
- Phrase output as a concise explanation of what conflicts and why it matters.
- Cite meeting numbers inline, for example `(meeting #1)` and `(meeting #2)`.
- Use severity only when it helps sorting; do not let labels dominate the UI.

### Summary

- Keep only the most important content for executive scanning.
- Do not render internal bucket names to users.
- Risk: one sentence.
- Next step: one sentence.
- Decisions: at most the top concrete decisions/facts for the selected meeting.

### Q&A

- Scope to the selected meeting group/topic.
- Use retrieved facts, summaries, decisions, actions, contradictions, and transcript snippets from the allowed meetings only.
- If evidence is absent, say it was not mentioned in the scoped meetings.
- UI answer text must not append a separate citation list.

## 7. API Contract

Owner-scoped routes use `X-Memoir-Owner`.

| Method | Route | Owner-scoped | Purpose |
|---|---|---:|---|
| `GET` | `/api/health` | No | Local API health. |
| `GET` | `/api/config` | No | Upload limits and chunk size. |
| `GET` | `/api/stats` | Yes | Counts for current owner. |
| `GET` | `/api/meetings` | Yes | Meeting list. |
| `GET` | `/api/meetings/{id}` | Yes | Meeting detail. |
| `PATCH` | `/api/meetings/{id}` | Yes | Update title/source/group. |
| `PATCH` | `/api/meeting_groups` | Yes | Rename all meetings in a group. |
| `DELETE` | `/api/meetings/{id}` | Yes | Delete meeting and derived records. |
| `GET` | `/api/meetings/{id}/audio` | Yes | Audio playback. |
| `GET` | `/api/meetings/{id}/report.docx` | Yes | DOCX export. |
| `POST` | `/api/meetings/{id}/reanalyze` | Yes | Reanalyze supplied transcript. |
| `POST` | `/api/meetings/{id}/apply_glossary` | Yes | Apply terminology and reanalyze. |
| `POST` | `/api/uploads` | No | Create upload session. |
| `POST` | `/api/uploads/{id}/chunks` | No | Upload chunk. |
| `POST` | `/api/uploads/{id}/complete` | Yes | Assemble and ingest. |
| `GET` | `/api/ingest/progress/{job_id}` | No | Upload/ingest progress. |
| `POST` | `/api/ingest` | Yes | Direct ingest fallback. |
| `POST` | `/api/ingest/check` | Yes | Same-file check. |
| `GET` | `/api/actions` | Yes | Action list. |
| `PATCH` | `/api/actions/{id}` | Yes | Action status. |
| `POST` | `/api/actions/{id}/assign` | Yes | Save owner/email and optionally notify. |
| `GET` | `/api/contradictions` | Yes | Contradiction list. |
| `GET` | `/api/resurfaced` | Yes | Resurfaced items. |
| `POST` | `/api/ask` | Yes | Group-scoped Q&A. |
| `GET` | `/api/glossary` | Yes | Terminology list. |
| `POST` | `/api/glossary` | Yes | Add term. |
| `DELETE` | `/api/glossary/{id}` | Yes | Delete term. |
| `GET` | `/api/glossary/suggestions` | Yes | Suggest terms for selected meeting. |
| `POST` | `/api/glossary/learn` | Yes | Learn terms from uploaded text. |
| `POST` | `/api/followup` | No | Maintenance scan. |
| `POST` | `/api/scan_forgotten` | No | Maintenance scan. |
| `POST` | `/api/redetect_contradictions` | No | Maintenance rebuild. |
| `POST` | `/api/notify/actions` | No | Action digest email. |

AgentBase:

- `GET /health` is handled by `main.py`.
- `POST /invocations` routes actions through `main.process`.
- `main.py` mounts `server.app` at `/` so the deployed runtime serves the same browser UI.

## 8. Configuration

Core defaults live in `config.py` and `.env.example`.

Required for real ingestion:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `STT_URL`

Safe local defaults:

- `DATABASE_URL=sqlite:///mnemosyne.db`
- `SUMMARY_MODEL=minimax/minimax-m2.5`
- `REASONING_MODEL=google/gemma-4-31b-it`
- `MNEMOSYNE_MAX_UPLOAD_BYTES=524288000`
- `MNEMOSYNE_UPLOAD_CHUNK_BYTES=16777216`

Optional email:

- `EMAIL_ENABLED=true`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_SSL`
- `SMTP_USER`
- `SMTP_PASS`
- `EMAIL_FROM`
- `EMAIL_TO`

## 9. Testing Requirements

Before GitHub push:

```bash
PYTHONPATH=. python -m pytest -q
```

Coverage expectations:

- DB migration and owner/group filtering.
- Meeting display ids per owner.
- Chunked upload API and progress.
- Meeting grouping and group rename frontend contract.
- Terminology save/refresh endpoints.
- Proper-noun correction guardrails.
- Q&A scoping by selected group/topic.
- Action owner assignment/email behavior.
- Evidence/transcript internal scroll UI contracts.

## 10. GitHub Readiness

Repository must be usable after:

```bash
git clone <repo>
cd Mnemosyne
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn server:app --host 127.0.0.1 --port 18093
```

Do not push:

- `.env`, `.env.*`
- `.greennode.json`
- `.agentbase/`
- `.gh-config/`
- `mnemosyne.db`
- private recordings/transcripts/reports
- generated media/report artifacts except intentional demo assets

Push:

- Source files.
- Tests.
- `web/assets/add-user.png`.
- `.env.example`.
- README and this spec.

## 11. Known Limitations

- Owner scoping is local/demo isolation, not authentication.
- SQLite is fine for local/demo. Use a managed database through `DATABASE_URL` for persistent multi-user production.
- PDF rendering depends on native WeasyPrint libraries. DOCX export is the safer default.
- Video ingest is slower than audio/transcript because it must convert media before STT.
- AgentBase runtime storage may not be durable across redeploys unless `DATABASE_URL` points to external storage.
