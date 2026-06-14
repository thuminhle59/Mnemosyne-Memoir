# Mnemosyne — ZaloPay Meeting Brain

> Design locked in session *"ZaloPay Meeting Brain AI Agent"* (2026-06-14).
> Built for GreenNode Claw-a-thon 2026. Deadline: **17/06/2026 12:00 (VN)**.

## 1. Positioning

**Mnemosyne = Meeting Ghost + a queryable organizational-memory layer.**

Meeting Ghost was *stateless*: audio in → one report out, nothing kept. Mnemosyne
keeps every meeting in a store and reasons **across** meetings — recall, multi-source
Q&A, proactive contradiction detection, action follow-up, executive digest.

Reuse the verified Meeting Ghost ingestion pipeline; add a memory + reasoning + chat
layer on top. Convention kept: Pydantic schema, decoupled modules tested in isolation,
extraction model + reasoning model (all env vars), deploy as Custom Agent on GreenNode
AgentBase.

### Data strategy — option C (agreed)
DB + load-into-context **now**, wrapped behind a `retrieve(query)` interface so it can be
upgraded to full RAG (embeddings + vector search) **after** the hackathon **without
changing call sites**. No vector DB in v1 — MiniMax/Gemini long context holds dozens of
meetings fine.

## 2. Compliance (Claw-a-thon rulebook) ⚠️

A meeting agent is high-risk for the data rule. Mandatory:
- Demo only with **synthetic / staged / public / personal** meeting data. Never real
  internal/customer meetings or PII. (`tests/fixtures/sample_transcript_vi.txt` is a
  compliant demo asset.)
- Email reports go to the **builder's own** address (simulate Outlook with Gmail if needed).
- State the synthetic-data scope explicitly in the Use Case Description.

## 3. Module map

| Module | Origin | Role |
|---|---|---|
| `recorder/record.py` | ♻️ reuse | Capture Teams audio / accept a file → ingest |
| `transcribe.py` | ♻️ reuse | Audio → text (no timestamps, per decision) |
| `analyze.py` + `models.py` | ♻️ reuse (extended) | Transcript → `MeetingReport` JSON |
| `report.py`, `mailer.py`, `llm.py`, `config.py` | ♻️ reuse | docx/pdf, email, LLM client, config |
| **`db.py`** | 🆕 (pattern from `zalopay-promo-agent`) | SQLAlchemy/SQLite: 5 tables |
| **`retrieve.py`** | 🆕 | `retrieve(query)` full-history, timeline-sorted (RAG-v2 seam) |
| **`brain.py`** | 🆕 | 5 reasoning flows |
| **`viewer/app.py`** | ♻️ extended | Streamlit: Meetings / Chat / Actions / Digest |
| **`main.py`** | ♻️ extended | AgentBase entrypoint, route by `action` |
| **`bot/`** | 🆕 (nice-to-have) | OpenClaw Zalo/Telegram → `brain.py` |

### Data flow
```
INGEST: audio/file → transcribe → analyze (MeetingReport) → extract_facts (KnowledgeFact[])
        → db.save_meeting + save_facts + save_actions
        → detect_contradictions(new_facts)            # proactive, at ingest time
        → (optional) report docx/pdf as before

QUERY:  question → retrieve(query) → relevant meetings+facts (full history, timeline)
        → brain.* → answer
        (Streamlit Chat / OpenClaw bot / /invocations all call the same brain.py)
```

## 4. Data model

### Pydantic (`models.py`)
Keep `Decision`, `MeetingReport`. Extend `ActionItem`; add `KnowledgeFact`, `Contradiction`.
```python
class ActionItem(BaseModel):
    task: str
    owner: str | None = None
    deadline: str | None = None
    priority: Literal["cao","trung bình","thấp"] = "trung bình"
    quote: str | None = None
    status: Literal["mở","đang làm","xong","quá hạn","treo"] = "mở"   # follow-up
    source_meeting_id: int | None = None                              # provenance

class KnowledgeFact(BaseModel):
    type: Literal["quyết định","fact","cam kết","số liệu","giả định","rủi ro"]
    subject: str            # e.g. "ngân sách Q3", "ngày launch"
    statement: str          # normalized claim
    quote: str | None = None
    status: Literal["hiệu lực","đã thay thế","mâu thuẫn"] = "hiệu lực"

class Contradiction(BaseModel):
    subject: str
    explanation: str
    severity: Literal["cao","trung bình","thấp"] = "trung bình"
```

### DB tables (SQLAlchemy/SQLite — `db.py`)
| Table | Key columns | Notes |
|---|---|---|
| `meetings` | id, title, date, duration_min, summary, report_json, transcript, created_at, content_hash | 1 row/meeting; `content_hash` dedups re-ingest |
| `action_items` | id, meeting_id (FK), task, owner, deadline, priority, status, quote | denormalized from report_json at save time |
| `action_links` | id, action_id, related_meeting_id, note | trace where an old action was re-mentioned (follow-up) |
| `knowledge_facts` | id, meeting_id, type, subject, statement, quote, status, created_at | accumulating memory; unit of reasoning |
| `contradictions` | id, fact_a_id, fact_b_id, subject, explanation, severity, detected_at | conflicting fact pairs (detected at ingest) |

## 5. Brain flows (`brain.py`)
Pure functions: data from `db`/`retrieve` → `llm` → Pydantic. Tested with mock LLM.

1. **`ingest(audio|text, date, title) -> Meeting`** — transcribe → analyze → `extract_facts`
   → save → `detect_contradictions`.
2. **`ask(question) -> Answer{text, citations[]}`** — Historical Recall Q&A. `retrieve` full
   history, timeline-sorted → LLM answers with **mandatory citations** (meeting title/date +
   quote); progressive topics presented as a timeline; "not mentioned" if absent.
3. **`detect_contradictions(new_facts) -> Contradiction[]`** — for each new fact, compare with
   active facts of the same `subject`; on conflict write `contradictions`, mark old fact
   `đã thay thế`/`mâu thuẫn`, surface a proactive warning. (e.g. launch 30/6 vs 15/7).
4. **`digest(scope) -> DigestReport`** — scope = all / project / date-range. Summaries + open
   actions + contradictions → executive digest; exportable docx/pdf via `report.py`.
5. **`follow_up() -> ActionStatus[]`** — match action items across meetings (owner + similar
   task); on a new meeting, LLM judges mentioned/done/overdue → update status + `action_links`.

## 6. Models per tier (env-configurable; locked after plan)
| Tier | Primary | Fallback |
|---|---|---|
| STT | `openai/whisper-large-v3` | — |
| Extraction (report + facts) | `minimax/minimax-m2.5` (safe, verified) | `google/gemma-4-31b-it` |
| Reasoning (Q&A/contradiction/digest) | `gemini/gemini-2.5-pro` | `deepseek/deepseek-v4-pro` |
| Embeddings (RAG v2 only) | `baai/bge-m3` | `qwen/qwen3-embedding-8b` |
| Reranker (RAG v2 only) | `qwen/qwen3-reranker-8b` | — |

Avoid `*-thinking` / `deepseek-r1-*` for JSON tasks (known `content=None` trap).
Upgrade path: try `gemini/gemini-2.5-flash` for extraction after a Vietnamese-JSON smoke test.

## 7. Deploy & test
- **Deploy:** Custom Agent on GreenNode AgentBase (pattern `user-quality-evaluator`).
  `main.py` runs `greennode_agentbase`, EXPOSE 8080. SQLite in-container for demo;
  `DATABASE_URL` env to migrate to Postgres. Endpoint must be switched to **public**.
- **Streamlit** is the primary demo face; OpenClaw bot is nice-to-have.
- **Tests (TDD, mock LLM):** db save/dedup/denormalize/query-by-subject; retrieve full-history
  + timeline + limit; each brain flow with fixed JSON; contradiction with 2 opposing facts;
  follow_up status update. E2E: ingest 2 linked Vietnamese meetings + 1 contradiction → recall
  query → check citations + contradiction warning.

## 8. Build order (priority for deadline)
1. `db.py` + extended `models.py`
2. `retrieve.py` + `brain.ingest`/`extract_facts`
3. `brain.ask` (core demo feature)
4. `brain.detect_contradictions` (wow factor)
5. `viewer` Chat + Meetings + Actions
6. `brain.digest` + `brain.follow_up`
7. Deploy AgentBase
8. (if time) OpenClaw bot

> If time runs short, cut from #8 upward. Minimum acceptable MVP = #1–#5.
