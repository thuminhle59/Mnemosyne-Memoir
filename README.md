# 🧠 Mnemosyne — ZaloPay Meeting Brain

A queryable **organizational memory** for meetings. Mnemosyne ingests meetings
(audio or transcript), turns them into structured reports + atomic facts, and reasons
**across** every past meeting: historical recall Q&A with citations, proactive
contradiction detection, action follow-up, and executive digests.

Built for **GreenNode Claw-a-thon 2026**. Deploys as a Custom Agent on GreenNode AgentBase.

> ⚠️ **Data compliance:** demo only with synthetic / staged / personal meeting data.
> No real internal/customer meetings or PII (per Claw-a-thon rulebook).

## What it does

| Capability | How |
|---|---|
| **Ingest** | audio → Whisper STT → report → atomic `KnowledgeFact`s → stored |
| **Historical Recall Q&A** | ask anything; answers cite the meeting(s) + quote, narrated on a timeline |
| **Contradiction detection** | at ingest, a new fact that conflicts with an earlier one (e.g. launch 30/6 → 15/7) raises a proactive warning |
| **Action follow-up** | tracks action items across meetings; marks done / overdue / pending |
| **Executive digest** | one-click leadership summary across all meetings (docx/pdf) |

## Architecture

```
audio/transcript ─► transcribe ─► analyze ─► extract_facts ─► db.save ─► detect_contradictions
                                                                  │
question ─► retrieve(full history, timeline) ─► brain.ask/digest/follow_up ─► answer
```

Built on the verified Meeting Ghost ingestion pipeline + a new memory layer
(`db.py`, `retrieve.py`, `brain.py`). `retrieve()` is the upgrade seam: v1 is keyword
overlap; v2 swaps in embeddings/RAG without changing callers. The browser dashboard,
FastAPI routes, and AgentBase invocation endpoint share one `brain.py`.

| Module | Role |
|---|---|
| `models.py` | Pydantic contracts (`MeetingReport`, `KnowledgeFact`, `Contradiction`, `Answer`) |
| `db.py` | SQLAlchemy store: meetings / action_items / action_links / knowledge_facts / contradictions |
| `retrieve.py` | full-history, timeline-sorted retrieval (RAG-v2 seam) |
| `brain.py` | `ingest` · `ask` · `detect_contradictions` · `digest` · `follow_up` |
| `analyze.py` `transcribe.py` `report.py` `mailer.py` `llm.py` | reused ingestion/output |
| `web/` | Browser dashboard used locally and on the deployed AgentBase endpoint |
| `server.py` | FastAPI routes for the dashboard (`/api/*`) |
| `main.py` | AgentBase entrypoint, routed by `action`, also mounts the web dashboard |

## Run locally

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in LLM_API_KEY (GreenNode MaaS)

# AgentBase-compatible runtime + web dashboard
uvicorn main:app --host 0.0.0.0 --port 8080
# open http://127.0.0.1:8080

# Optional local FastAPI-only dev server for the same dashboard/API
uvicorn server:app --host 0.0.0.0 --port 8080
```

## AgentBase deployment shape

The Docker image serves `main:app` with Uvicorn. `main.py` creates a
`GreenNodeAgentBaseApp` and mounts the same frontend that was built in `web/`.

Production routes on the AgentBase endpoint:

- `GET /` browser dashboard
- `GET /api/health` and the rest of `/api/*` for frontend actions
- `GET /health`
- `POST /invocations`

### Agent API (`POST /invocations`)
Routed by `action`:
```jsonc
{"action": "ingest",  "text": "<transcript>", "title": "Họp tuần 1", "date": "2026-06-02"}
{"action": "ingest",  "audio_base64": "...", "format": "docx"}
{"action": "ask",     "question": "Ngày launch hiện tại là khi nào?"}
{"action": "digest",  "scope": "all", "format": "docx"}
{"action": "followup"}
```

## Models (GreenNode MaaS, all env-configurable)

| Tier | Default | Fallback |
|---|---|---|
| STT | `openai/whisper-large-v3` | — |
| Extraction (report + facts) | `minimax/minimax-m2.5` | `google/gemma-4-31b-it` |
| Reasoning (Q&A / contradiction / digest) | `gemini/gemini-2.5-pro` | `google/gemma-4-31b-it` |

## Tests

```bash
python -m pytest tests/ -q     # LLM mocked
```

See [`docs/SPEC.md`](docs/SPEC.md) for the full design.
