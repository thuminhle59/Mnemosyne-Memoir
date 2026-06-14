# Mnemosyne Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Claude Design Meeting Brain prototype into a static SPA served by Mnemosyne's FastAPI backend.

**Architecture:** Create `web` as a vanilla HTML/CSS/JS app inside the Mnemosyne repo. The app keeps the Claude Design layout and visual language, but replaces mock state with calls to existing `/api/*` endpoints in `server.py`.

**Tech Stack:** FastAPI static files, vanilla JavaScript, CSS, pytest.

---

### Task 1: Static Frontend Contract Test

**Files:**
- Create: `tests/test_web_frontend.py`
- Verify: `web/index.html`
- Verify: `web/app.js`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_web_frontend_exists_and_is_wired_to_api():
    index = WEB / "index.html"
    app_js = WEB / "app.js"

    assert index.exists()
    assert app_js.exists()

    html = index.read_text(encoding="utf-8")
    js = app_js.read_text(encoding="utf-8")

    assert "Meeting Brain" in html
    assert "app.js" in html
    for endpoint in [
        "/api/stats",
        "/api/meetings",
        "/api/ask",
        "/api/ingest",
        "/api/actions",
        "/api/contradictions",
        "/api/resurfaced",
        "/api/glossary",
    ]:
        assert endpoint in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_web_frontend.py -q`

Expected: FAIL because `web/index.html` and `web/app.js` do not exist.

### Task 2: Port Claude Design Shell

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`

- [ ] **Step 1: Create the page shell**

Use the Claude Design layout: top bar, left meeting library, center meeting detail, right chat panel, import modal.

- [ ] **Step 2: Keep the styling local**

Move visual styles into `styles.css`. Use the same fonts, warm editorial palette, compact dashboard layout, and responsive mobile stacking.

### Task 3: Wire Data and Interactions

**Files:**
- Create: `web/app.js`

- [ ] **Step 1: Implement API client helpers**

Use `fetch()` for `/api/stats`, `/api/meetings`, `/api/meetings/{id}`, `/api/ask`, `/api/ingest`, `/api/actions`, `/api/contradictions`, `/api/resurfaced`, `/api/glossary`, and `/api/glossary/learn`.

- [ ] **Step 2: Render backend data**

Render stats, meeting list, active meeting summary, transcript, decisions, actions, facts, contradictions, resurfaced decisions, glossary, and chat citations.

- [ ] **Step 3: Implement write workflows**

Support transcript ingest, file ingest, chat ask, glossary paste/upload, action refresh, digest generation, meeting reanalysis, and meeting deletion.

### Task 4: Verify

**Files:**
- Verify: `tests/test_web_frontend.py`
- Verify: existing Mnemosyne tests

- [ ] **Step 1: Run focused test**

Run: `venv/bin/python -m pytest tests/test_web_frontend.py -q`

Expected: PASS.

- [ ] **Step 2: Run backend regression tests**

Run: `venv/bin/python -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 3: Start API server**

Run: `venv/bin/uvicorn server:app --host 127.0.0.1 --port 8080`

Expected: server starts and serves the SPA at `http://127.0.0.1:8080/`.
