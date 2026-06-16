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

    assert "Memoir" in html
    assert "Decision Memory" in html
    assert "app.js" in html
    assert "assets/mnemosyne-logo.png?v=20260616-logo" in html
    assert (WEB / "assets" / "mnemosyne-logo.png").exists()
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


def test_ingest_form_keeps_audio_file_upload_path_reliable():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '<form id="ingestForm">' in html
    assert 'class="file-upload-row ingest-panel"' in html
    assert '<span class="file-upload-button">Upload</span>' in html
    assert '<span id="ingestFileLabel" class="file-name-line">No file selected</span>' in html
    assert "Optional audio/video upload" not in html
    assert "Memoir will upload this file in chunks." not in js
    assert '`${file.name}`' in js
    assert 'if (file) form.append("file", file);' in js
    assert 'if (file && !text) form.append("file", file);' not in js


def test_frontend_uses_chunked_upload_for_every_file_input():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "DIRECT_UPLOAD_BYTES" not in js
    assert "isPayloadTooLarge" not in js
    assert "const CHUNK_UPLOAD_CONCURRENCY = 3;" in js
    assert "uploadNextChunk" in js
    assert "workers = Array.from" in js
    assert "const chunkLoaded = Array(totalChunks).fill(0);" in js
    assert "function uploadedChunkBytes()" in js
    assert "if (file) {" in js
    assert "out = await chunkedIngestMeeting(file, text);" in js


def test_tabs_use_stable_data_attributes_and_delegated_handler():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    for tab in ["digest", "memory", "transcript"]:
        assert f'data-tab="{tab}"' in html
        assert f'{tab}View' in html

    assert 'id="tabDigest"' in html
    assert 'id="tabDigest" class="tab active" href="#digestView" data-tab="digest" onclick="switchTab(\'digest\')">Summary</a>' in html
    assert "Executive Brief" not in html
    assert 'section id="digestView" class="view scroll active"' in html
    assert 'document.querySelector(".tabs").addEventListener("click"' in js
    assert "button.dataset.tab" in js
    assert '[data-tab="${key}"]' in js
    assert "function switchTab(tab)" in js
    assert "window.switchTab = switchTab" in js
    assert 'onclick="switchTab(' in html
    assert 'href="#digestView"' in html
    assert 'href="#transcriptView"' in html


def test_tabs_have_inline_switch_fallback_before_external_app_js():
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert "window.switchTab = function switchTab" in html
    assert "window.__MNEMOSYNE_TAB = tab" in html
    assert "document.querySelectorAll(\".tab\")" in html
    assert "document.querySelectorAll(\".view\")" in html
    assert "window.addEventListener(\"hashchange\"" in html
    assert html.index("window.switchTab = function switchTab") < html.index("app.js")


def test_app_preserves_tab_selected_before_data_finishes_loading():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "tab: currentTabFromLocation()" in js
    assert "window.__MNEMOSYNE_TAB = tab" in js
    assert "state.tab = window.__MNEMOSYNE_TAB || state.tab" in js


def test_tablet_layout_keeps_sidebar_from_collapsing_under_chat():
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert ".workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: 268px minmax(520px, 1fr) 336px;" in css
    assert ".workspace { grid-template-columns: 244px minmax(360px, 1fr); }" in css
    assert ".terminology { flex: 0 1 min(34vh, 260px); min-height: 0; }" in css
    assert "styles.css?v=20260616-evidence-dropdown" in html
    assert "app.js?v=20260616-evidence-dropdown" in html
    assert 'data-export="docx"' in html
    assert 'data-export="pdf"' not in html
    assert "PDF (.pdf)" not in html


def test_terminology_section_is_compact_inside_sidebar():
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert ".knowledge { flex: 0 1 min(34vh, 260px); max-height: min(34vh, 260px);" in css
    assert ".glossary-panel { flex: 1; min-height: 0;" in css
    assert ".inline-form" not in css
    assert ".guide-drop" not in css
    assert ".term-list { min-height: 0;" in css
    assert ".term span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }" in css


def test_frontend_positions_memoir_as_decision_memory_agent():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for label in [
        "Decision Memory",
        "Decision",
        "Summary",
        "Decisions",
        "Contradictions",
        "Risks &amp; Blockers",
        "Actions",
        "Evidence",
        "Ask Memoir",
    ]:
        assert label in html
    assert "Evidence Lab" not in html
    assert "Evidence Graph" not in html
    assert 'id="evidenceFilterBtn"' in html
    assert "Filter by: All" in html
    assert "data-evidence-filter-all" in html
    assert 'id="evidenceTypeOptions"' in html
    assert 'id="evidenceTypeFilter" multiple' not in html
    assert "Decision Drift" not in html
    assert "Contradiction Radar" not in html
    assert "Action Memory" not in html
    assert "<span>Contradiction</span>" in html
    assert "<span>Action</span>" in html
    assert '<article class="radar-card signal-card green">\n                <strong id="decisionDriftCount">0</strong>' in html
    assert '<article class="radar-card signal-card red accent">\n                <strong id="contradictionCount">0</strong>' in html
    assert 'id="tabMemory" class="tab" href="#memoryView" data-tab="memory" onclick="switchTab(\'memory\')">Actions</a>' in html
    assert "Memory Ops" not in html
    assert "Highlights" not in html
    assert "Topics covered" not in html
    assert 'id="highlights"' not in html
    assert 'id="topics"' not in html

    assert "tab: currentTabFromLocation()" in js
    assert "decisionDriftCount" in js
    assert "contradictionsForgotten" in js
    assert "renderActionCheckbox" in js
    assert "renderTranscriptEvidence" in js
    assert "seekToTimestamp" in js
    assert ".memory-hero" in css
    assert ".executive-grid" in css
    assert ".player" in css
    assert ".timestamp-button" in css
    assert "function severityBadge" in js
    assert "function severityKey" in js
    assert "severity-badge" in css
    assert "severity-high" in css
    assert "severity-medium" in css
    assert "severity-low" in css
    assert 'text: `[${c.severity}] ${c.subject}: ${c.explanation}`' not in js
    assert 'detail: "Contradiction"' not in js
    assert "const highlights" not in js
    assert 'const tp = $("topics")' not in js
    assert ".signals { width: fit-content; display: grid; grid-template-columns: repeat(3, max-content);" in css
    assert ".signal-card { min-height: 34px; display: flex; align-items: baseline;" in css
    assert ".signal-card strong { flex: 0 0 auto;" in css


def test_meeting_summary_lives_inside_executive_brief_view():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    head_start = html.index('<div class="content-head meeting-head">')
    digest_start = html.index('<section id="digestView"')
    summary_pos = html.index('id="activeSummary"')

    assert summary_pos > digest_start
    assert summary_pos > head_start
    assert '<div id="activeSummary" class="summary digest-summary">' in html
    assert "function renderExecutiveSummary" in js
    assert "function renderStructuredSummaryBrief" in js
    assert "function fallbackSummaryLines" in js
    assert "meeting.summary_brief" in js
    assert "summaryBriefLines" in js
    for label in ["Context", "Decisions", "Risk", "Next step"]:
        assert f'"{label}"' not in js
    assert "summary-section-title" not in js
    assert "function executiveSummaryLines" not in js
    assert "splitSummarySentences" not in js
    assert "chosen.slice(0, 3)" not in js
    assert "clean.slice" not in js
    assert "trim()}..." not in js
    assert 'const label = meeting ? "Meeting summary" : "Summary";' in js
    assert "renderStructuredSummaryBrief(box, meeting.summary_brief)" in js
    assert "request(API.digest)" not in js
    assert "state.digest = digestResult.status" not in js
    assert "const digest = state.digest || {};" not in js
    assert 'id="digestBtn"' not in html
    assert "Generate executive brief" not in html
    assert "function generateDigest" not in js
    assert "digestBtn" not in js
    assert "summary-label" in js
    assert "function executiveSummaryGroups" not in js
    assert "TL;DR" not in js
    assert ".digest-summary" in css
    assert ".summary-label" in css
    assert ".summary-section-title" not in css
    assert ".summary p + p" in css
    assert ".summary-groups" not in css
    assert ".summary-group" not in css


def test_frontend_persists_owner_id_and_sends_owner_header():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'const OWNER_STORAGE_KEY = "memoir_owner_id";' in js
    assert "function getOwnerId()" in js
    assert "window.localStorage.getItem(OWNER_STORAGE_KEY)" in js
    assert "window.crypto.randomUUID()" in js
    assert '"X-Memoir-Owner": getOwnerId()' in js
    assert "const requestOptions = withOwnerHeader(options)" in js


def test_decision_list_does_not_render_signal_brief_detail():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '"Signal brief"' not in js
    assert 'const decisionRows = (m.decisions || []).map((d) => ({ text: d.text, timestamp: d.timestamp }));' in js
    assert 'renderLine(d.text, d.timestamp)' in js
    assert "...(m.key_points || []).map((text) => ({ text }))" not in js
    assert 'detail: "Decision"' not in js
    assert "factDecisions" not in js


def test_risk_list_does_not_render_risk_detail_label():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '$("risks").innerHTML = listHtml(m.risks, (x) => renderLine(x));' in js
    assert '$("risks").innerHTML = listHtml(m.risks, (x) => renderLine(x, null, "Risk"));' not in js


def test_summary_and_contradictions_are_scoped_to_selected_meeting():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function citationMatchesActiveMeeting" in js
    assert "function activeContradictions" in js
    assert "function activeResurfaced" in js
    assert "currentContradictions.map((c)" in js
    assert "currentResurfaced.map((r)" in js
    assert "state.contradictions.map((c)" not in js
    assert "state.resurfaced.map((r)" not in js
    assert "const currentContradictions = activeContradictions();" in js
    assert "const currentResurfaced = activeResurfaced();" in js
    assert "currentContradictions.length + currentResurfaced.length" in js
    assert "currentContradictions.length;" in js
    assert "function contradictionText(c)" in js
    assert "Đã thay đổi từ" in js
    assert "sang ${newStatement}" in js
    assert "(meeting #${meetingDisplayIdById(citation.meeting_id)})" in js


def test_evidence_mentions_are_scoped_to_selected_meeting():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "activeContradictions().forEach((c)" in js
    assert "activeResurfaced().forEach((r)" in js
    assert "state.contradictions.forEach((c)" not in js
    assert "state.resurfaced.forEach((r)" not in js


def test_metric_cards_live_below_meeting_title_before_tabs():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    title_pos = html.index('id="activeTitleInput"')
    signals_pos = html.index('class="signals memory-hero"')
    tabs_pos = html.index('class="tabs" role="tablist"')
    digest_pos = html.index('<section id="digestView"')

    assert title_pos < signals_pos < tabs_pos < digest_pos
    assert "<small>Decisions or facts" not in html
    assert "<small>Conflicting claims" not in html
    assert "<small>Open commitments" not in html
    assert ".signals { width: fit-content;" in css
    assert ".signal-card { min-height: 34px;" in css
    assert ".signal-card span { min-width: 0;" in css
    assert "font-size: 8px" in css
    assert "font-size: 20px" in css


def test_memory_ops_filters_actions_to_selected_meeting():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function actionsForActiveMeeting()" in js
    assert "Number(a.meeting_id) === Number(state.activeId)" in js
    assert "const activeActions = actionsForActiveMeeting();" in js
    assert "const actions = importantActions(activeActions);" in js
    assert 'state.actions.map((a) => ({ ...a, type: "action" }))' not in js


def test_alert_banner_stack_is_not_rendered_below_tabs():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "bannerStack" not in html
    assert "renderBanners" not in js
    assert "banner-stack" not in css


def test_memory_dashboard_uses_compact_scrollable_panels():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'class="stage-body"' in html
    assert 'class="player"' in html
    assert ".stage-body { flex: 1;" in css
    assert ".content-scroll { flex: 1; min-height: 0; overflow: auto;" in css
    assert ".executive-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert ".brief-card.scroll-card { height: clamp(380px, 48vh, 500px);" in css
    assert 'class="toolbar executive-nav"' in html
    assert 'data-scroll-target="decisionsCard"' in html
    assert 'data-scroll-target="contradictionsCard"' in html
    assert 'data-scroll-target="risksCard"' in html
    assert 'id="decisionsCard" class="brief-card scroll-card"' in html
    assert 'id="contradictionsCard" class="brief-card scroll-card"' in html
    assert 'id="contradictionsCard" class="brief-card scroll-card alert"' not in html
    assert "redetectContradictionsBtn" not in html
    assert 'id="risksCard" class="brief-card scroll-card wide"' in html
    assert ".executive-nav" in css
    assert ".section-jump-btn" in css
    assert ".executive-nav button { min-height: 32px; }" in css
    assert ".section-jump-btn { border: 1px solid var(--line); border-radius: 8px;" in css
    assert "font-size: 13px" in css
    assert ".action-toolbar" not in css
    assert "scrollIntoView({ behavior: \"smooth\", block: \"start\" })" in (WEB / "app.js").read_text(encoding="utf-8")
    assert "<h2>Contradictions</h2>" in html
    assert "Contradictions &amp; Forgotten Decisions" not in html
    assert "redetectContradictions" not in (WEB / "app.js").read_text(encoding="utf-8")
    assert "Re-detect" not in html
    assert ".scroll-card ul { flex: 1; min-height: 0; overflow: auto;" in css
    assert ".scroll-card.wide { grid-column: 1 / -1; height: clamp(190px, 24vh, 250px); max-height: none; }" in css
    assert ".memory-grid article ul,\n  .action-workbench ul { overflow: visible; }" in css
    assert ".transcript-view, .memory-grid article ul,\n  .action-workbench ul, .evidence-graph ul { overflow: visible; }" not in css
    assert ".scroll-card ul, .memory-grid article ul" not in css


def test_actions_tab_shows_important_actions_with_completion_checkboxes():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert '<ul id="allActions"></ul>' in html
    assert "Current decision state" not in js
    assert "decision-state" not in js
    assert "action-status-controls" not in js
    assert "data-action-status" not in js
    assert "importantActions" in js
    assert "renderActionCheckbox" in js
    assert "actionMetaText" in js
    assert 'type="checkbox"' in js
    assert 'data-action-toggle' in js
    assert 'updateActionStatus(Number(toggle.dataset.actionId), toggle.checked ? "completed" : "pending", toggle)' in js
    assert 'data-assign-toggle' in js
    assert 'Assign ✉' not in js
    assert 'class="assign-toggle icon-assign-toggle"' in js
    assert './assets/add-user.png?v=20260616' in js
    assert 'aria-label="Assign owner"' in js
    assert 'data-assign-form data-action-id="${item.id}" hidden' in js
    assert 'data-assign-owner' in js
    assert 'class="assign-owner"' in js
    assert 'placeholder="Người phụ trách"' in js
    assert 'placeholder="email"' in js
    assert '>Assign</button>' in js
    assert '>Send</button>' in js
    assert 'data-assign-owner-save' in js
    assert 'assignAction(Number(assignOwnerSave.dataset.actionId), owner, "", assignOwnerSave, false)' in js
    assert 'showToast("Nhập email để gửi assignment", "error")' in js
    assert 'assignAction(Number(assignSend.dataset.actionId), owner, email, assignSend, true)' in js
    assert 'const cleanOwner = owner.trim() || cleanEmail' in js
    assert 'body: JSON.stringify({ owner: cleanOwner, email: cleanEmail || null, notify })' in js
    assert '`Đã giao cho ${res.owner} & gửi email tới ${cleanEmail}`' in js
    assert "state.actions = await request(API.actions);\n  renderMemory();\n  showToast(\"Action status updated\");" not in js
    assert 'const openScore = statusKey(action.status) !== "completed" ? 1 : 0;' not in js
    assert 'item.owner || "Unassigned"' not in js
    assert ".action-check-row" in css
    assert ".action-check-input" in css
    assert ".action-completed" in css
    assert ".assign-toggle { border: 1px solid var(--line); border-radius: 7px; background: #fff;" in css
    assert ".icon-assign-toggle { width: 20px; height: 18px;" in css
    assert ".icon-assign-toggle img { width: 12px; height: 12px;" in css
    assert ".assign-owner { width: 130px; flex: 0 0 130px; }" in css
    assert ".assign-email { width: 200px; flex: 0 0 200px; }" in css
    assert ".assign-send { border: 1px solid var(--line); border-radius: 8px; background: var(--rail);" in css
    assert ".action-status-controls" not in css
    assert ".decision-state" not in css
    assert ".executive-grid, .lab-grid, .brief-grid, .memory-board { grid-template-columns: 1fr;" not in css
    assert ".lab-grid { display: grid;" in css
    assert ".transcript-view { min-height: 0; overflow: auto;" in css
    assert ".player { height: 44px;" in css


def test_important_actions_dedupe_same_password_intent():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function dedupeActionsByIntent" in js
    assert "function actionIntentKey" in js
    assert 'text.includes("password") || text.includes("mật khẩu")' in js
    assert "dedupeActionsByIntent(important)" in js


def test_executive_brief_has_no_manual_followup_refresh_button():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "Refresh follow-up" not in html
    assert "followupBtn" not in html
    assert "followupBtn" not in js
    assert "function runFollowup" not in js


def test_frontend_uses_localhost_api_when_opened_from_file_protocol():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'window.location.protocol === "file:"' in js
    assert 'http://127.0.0.1:8080' in js
    assert 'apiUrl("/api/ask")' in js


def test_frontend_request_falls_back_when_fetch_is_unavailable():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function requestWithXhr" in js
    assert 'typeof window.fetch === "function"' in js
    assert "await requestWithXhr(url, requestOptions)" in js
    assert "new XMLHttpRequest()" in js


def test_frontend_request_uses_xhr_for_upload_progress_events():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'const needsUploadProgress = typeof requestOptions.onUploadProgress === "function";' in js
    assert 'xhr.upload.onprogress = (event) => {' in js
    assert "options.onUploadProgress(event.loaded, event.total, event)" in js
    assert 'typeof window.fetch === "function" && !needsUploadProgress' in js
    assert "requestWithXhr(url, requestOptions)" in js


def test_frontend_reads_server_bootstrap_from_json_script():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function readBootstrapData" in js
    assert 'document.getElementById("memoirBootstrap")' in js
    assert "JSON.parse(node.textContent)" in js
    assert "const BOOTSTRAP_DATA = readBootstrapData();" in js


def test_file_protocol_redirects_to_served_frontend_before_fetching():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'window.location.replace("http://127.0.0.1:8080/")' in js
    assert "FILE_PROTOCOL_REDIRECTED" in js
    assert js.index("FILE_PROTOCOL_REDIRECTED") < js.index("const API =")


def test_ingest_upload_flow_has_reliability_guards():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'id="ingestSubmitBtn"' in html
    assert 'id="uploadStatus"' in html
    assert 'health: apiUrl("/api/health")' in js
    assert 'config: apiUrl("/api/config")' in js
    assert "MAX_UPLOAD_BYTES" in js
    assert "state.maxUploadBytes" in js
    assert "file.size === 0" in js
    assert "setIngestBusy(true)" in js
    assert "setIngestBusy(false)" in js
    assert "Cannot reach Memoir API" in js


def test_ingest_form_can_switch_between_upload_recording_and_transcript_modes():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="ingestMode"' in html
    assert '<option value="upload">Upload audio</option>' in html
    assert '<option value="recording">Recording</option>' in html
    assert '<option value="transcript">Paste transcript</option>' in html
    for mode in ["upload", "recording", "transcript"]:
        assert f'data-ingest-panel="{mode}"' in html
    assert html.count("ingest-source-box") == 2
    assert 'class="file-upload-row ingest-panel"' in html

    assert "function setIngestMode(mode)" in js
    assert "[data-ingest-panel]" in js
    assert 'panel.dataset.ingestPanel !== mode' in js
    assert 'clearFilePreview()' in js
    assert 'resetRecording()' in js
    assert ".ingest-mode-row" in css
    assert ".ingest-source-box { margin: 0 0 10px; padding: 13px; border: 1px solid var(--line); border-radius: 10px; background: #fff;" in css
    assert ".ingest-source-box .transcript-editor.compact" in css
    assert "[data-ingest-panel][hidden]" in css


def test_import_dialog_uses_compact_x_close_button():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="closeImportBtn" class="dialog-close-btn" type="button" aria-label="Close import dialog">x</button>' in html
    assert '<button id="closeImportBtn" class="ghost-btn" type="button">Close</button>' not in html
    assert ".dialog-close-btn" in css
    assert "width: 28px; height: 28px;" in css


def test_recording_input_uses_plain_labels_without_symbols():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "Hoặc ghi trực tiếp cuộc họp của bạn" not in html
    assert "🔴" not in html
    assert "🎙" not in html
    assert "⏹" not in html
    assert "Record tab or screen" not in html
    assert 'id="recordTabBtn"' not in html
    assert ">Record mic<" in html
    assert 'id="recordMicBtn" class="ghost-btn record-action-btn">Record mic</button>' in html
    assert ">Stop and save<" in html
    assert "Ready to record from microphone." in html
    assert ".record-label" not in css


def test_recording_mic_enables_when_browser_supports_media_recorder():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "recordTabBtn" not in html
    assert "recordTabBtn" not in js
    assert 'id="recordMicBtn" class="ghost-btn record-action-btn">Record mic</button>' in html
    assert "function canRecordMic" in js
    assert "function refreshRecordingSupport" in js
    assert "button.disabled = !supported" in js
    assert 'startRecording("mic")' in js
    assert '$("recordStatus").textContent = "Recording is not available yet."' not in js
    assert ".record-action-btn" in css
    assert ".record-action-btn:disabled" in css
    assert "cursor: not-allowed" in css
    assert "Ready to record from microphone." in js
    assert 'font-family: "Hanken Grotesk", -apple-system, BlinkMacSystemFont, sans-serif' in css


def test_ingest_file_shows_single_percent_progress_in_warning_area():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="uploadStatus"' in html
    assert html.index('id="uploadStatus"') < html.index('id="ingestProgress"')
    assert 'id="ingestProgress" class="ingest-progress" aria-label="Ingest progress" hidden' in html
    assert 'id="ingestProgressPercent">0%</span>' in html
    assert 'id="ingestStages"' not in html
    assert 'data-stage="prepare"' not in html
    assert 'id="uploadProgress"' not in html
    assert 'role="progressbar"' not in html
    assert 'id="uploadProgressPercent"' not in html
    assert "function showIngestProgress()" in js
    assert "function setIngestPercent(percent, variant = \"\")" in js
    assert "function setUploadProgress" in js
    assert "function resetUploadProgress" in js
    assert "function hasSelectedIngestFile()" in js
    assert "if (file) showIngestProgress();" in js
    assert "if (file) setIngestPercent(0);" in js
    assert 'if (hasSelectedIngestFile()) setUploadProgress(0, "Upload interrupted", error.message, "error");' in js
    assert "onUploadProgress: (loaded, total) => {" in js
    assert "function setFileIngestProgress(percent, variant = \"\")" in js
    assert "setUploadProgress(0, \"Upload interrupted\", error.message, \"error\");" in js
    assert "chunkLoaded[index] = Math.max(chunkLoaded[index], chunk.size * ratio);" in js
    assert "setFileIngestProgress((uploadedChunkBytes() / file.size) * 70);" in js
    assert 'setUploadProgress(0, "Uploading")' not in js
    assert 'setUploadProgress(70, "Uploading")' not in js
    assert 'setUploadStatus(`Đang tải lên ${file.name}' not in js
    assert "const workers = Array.from({ length: workerCount }, () => uploadNextChunk());" in js
    assert "ingestProgress: (id) => apiUrl(`/api/ingest/progress/${id}`)" in js
    assert "function pollBackendIngestProgress(jobId, floor = 0)" in js
    assert "const stopProgress = pollBackendIngestProgress(session.job_id || session.upload_id, 70);" in js
    assert "form.append(\"job_id\", jobId);" in js
    assert "setIngestPercent(85);" not in js
    assert "setIngestPercent(100);" in js
    assert "Math.round(percent)" in js
    assert '.ingest-progress[hidden] { display: none; }' in css
    assert ".ingest-progress" in css
    assert ".ingest-progress.error" in css
    assert ".ingest-progress-track" in css
    assert ".ingest-progress-fill" in css
    assert ".upload-progress" not in css
    assert ".upload-progress-fill" not in css


def test_ingest_file_warning_uses_fastest_ingest_copy():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    warning = "For fastest ingest, upload audio or paste transcript. Video may take several minutes. Please keep this window open"

    assert warning in js
    assert warning in server
    assert "Đang bóc băng & phân tích nội dung" not in js
    assert "Đang bóc băng & phân tích nội dung" not in server


def test_ingest_percent_progress_marks_errors_and_resets_cleanly():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'setIngestPercent(percent, "error")' in js
    assert 'box.classList.toggle("error", variant === "error")' in js
    assert 'box.classList.remove("error")' in js
    assert "showIngestProgress();" in js
    assert ".ingest-progress.error" in css


def test_ingest_file_input_supports_local_media_playback_preview():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="filePreview"' in html
    assert 'id="audioPreview" controls preload="metadata"' in html
    assert 'id="videoPreview" controls preload="metadata" playsinline' in html
    assert "URL.createObjectURL(file)" in js
    assert "URL.revokeObjectURL(state.previewUrl)" in js
    assert "function updateFilePreview(file)" in js
    assert "updateFilePreview(file)" in js
    assert ".file-preview" in css


def test_middle_player_plays_stored_audio_for_active_meeting():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="playerToggleBtn"' in html
    assert 'id="meetingAudio" preload="metadata"' in html
    assert 'id="playerLabel"' not in html
    assert 'class="player-progress"' in html
    assert 'id="playerProgressFill"' in html
    assert 'class="player-volume"' in html
    assert "function renderMeetingPlayer()" in js
    assert "audio.src = API.audio(m.id)" in js
    assert "updatePlayerProgress(0, 0);" in js
    assert "function updatePlayerProgress(current, duration)" in js
    assert "function toggleMeetingPlayback()" in js
    assert "await audio.play()" in js
    assert "m.can_play_audio" in js
    assert "const canPlay = Boolean(m?.id && m.can_play_audio);" in js
    assert "$(\"playerLabel\")" not in js
    assert ".play.playing::before" in css
    assert ".player-progress" in css
    assert ".player-volume" in css


def test_evidence_lab_uses_readonly_timestamped_transcript():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '<textarea id="transcriptText"' not in html
    assert 'id="transcriptText" class="transcript-view"' in html
    assert 'id="transcriptSearch"' in html
    assert '<div class="toolbar transcript-toolbar">' in html
    assert "<h2>Transcript</h2>" in html
    assert 'placeholder="Filter transcript"' in html
    assert "function renderTranscriptEvidence()" in js
    assert "function transcriptMinuteMarkers" not in js
    assert "transcript-minute-marker" not in js
    assert "collectEvidenceMentions()" in js
    assert "timestamp-button" in js
    assert "audio.currentTime = seconds" in js
    assert ".transcript-toolbar { justify-content: space-between; align-items: center; }" in (WEB / "styles.css").read_text(encoding="utf-8")


def test_evidence_graph_omits_fact_status_labels():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert '<span>${escapeHtml(f.type)}</span>' in js
    assert "${escapeHtml(f.type)} · ${escapeHtml(f.status)}" not in js
    assert "evidenceFilterBtn" in html
    assert "evidenceTypeOptions" in html
    assert "<h2>Evidences</h2>" in html
    assert "evidenceFilterMenu" in js
    assert "state.evidenceTypeFilter" in js
    assert "selectedOptions" not in js
    assert "data-evidence-filter-all" in js
    assert "data-evidence-filter-type" in js
    assert ".evidence-filter-row" in css
    assert ".evidence-filter-row h2" in css
    assert ".evidence-filter-menu" in css
    assert ".transcript-minute-marker" not in css


def test_evidence_and_transcript_cards_have_internal_scroll_panes():
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert ".lab-grid { display: grid;" in css
    assert "height: clamp(460px, 64vh, 700px)" in css
    assert ".evidence-graph, .transcript-panel { min-height: 0; height: 100%; overflow: hidden;" in css
    assert ".evidence-graph ul { flex: 1 1 auto; min-height: 0; overflow: auto; }" in css
    assert ".transcript-view { min-height: 0; overflow: auto; flex: 1;" in css
    assert ".evidence-graph, .transcript-panel { height: min(56vh, 520px); }" in css


def test_frontend_does_not_hardcode_200mb_upload_limit():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "Selected file is larger than 200 MB" not in js
    assert "This file is larger than 200 MB" not in js
    assert "formatUploadLimit" in js


def test_sidebar_matches_claude_library_pattern_with_edit_and_delete():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "Cross-meeting memory" not in html
    assert "Contradiction detection" not in html
    assert "Evidence-backed Q&amp;A" not in html
    assert 'class="time-filter"' in html
    for label in ["All", "Today", "Week", "Month"]:
        assert label in html
    for label in ["Tất cả", "Hôm nay", "Tuần này", "Tháng này"]:
        assert label not in html
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in css
    assert "text-overflow: ellipsis" in css
    assert "meeting-title-input" in js
    assert '<textarea id="activeTitleInput" class="active-title-input" rows="1" aria-label="Edit meeting name">Memoir</textarea>' in html
    assert "data-meeting-delete" in js
    assert "updateMeetingName" in js
    assert "API.updateMeeting" in js
    assert ".meeting-delete" in css
    assert ".active-title-input" in css
    assert ".library { min-height: 0; display: flex; flex-direction: column; background: var(--rail);" in css
    assert ".meeting-list { min-height: 0; flex: 1; overflow: auto; padding: 0 12px; background: var(--rail); }" in css


def test_active_meeting_title_wraps_long_names_in_header():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert '<textarea id="activeTitleInput" class="active-title-input" rows="1" aria-label="Edit meeting name">Memoir</textarea>' in html
    assert "function resizeActiveTitle" in js
    assert "$(\"activeTitleInput\").style.height = \"auto\"" in js
    assert "$(\"activeTitleInput\").style.height = `${$(\"activeTitleInput\").scrollHeight}px`" in js
    assert "resizeActiveTitle()" in js
    assert "event.shiftKey" in js
    assert "white-space: normal" in css
    assert "overflow-wrap: anywhere" in css
    assert "resize: none" in css
    assert "overflow: hidden" in css


def test_main_app_sidebar_can_use_grouped_meeting_folder_layout():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert '<p class="sidebar-dnd-note">Drag and drop meeting into group</p>' in html
    assert html.index('class="time-filter"') < html.index('class="sidebar-dnd-note"') < html.index('id="meetingList"')
    assert "function deriveMeetingGroup" in js
    assert "function groupMeetingsForSidebar" in js
    assert 'class="group-folder"' in js
    assert 'class="group-title"' in js
    assert "group-dnd-note" not in js
    assert "<small>${groupMeetings.length}</small>" not in js
    assert "? \"v\" : \">\"" not in js
    assert 'class="meeting-card group-meeting' in js
    assert 'class="meeting-compact-title"' in js
    assert 'class="meeting-compact-meta"' in js
    assert "meetingDateTime(m)" in js
    assert "meetingDurationLabel(m)" in js
    assert "meeting-source-line" not in js
    assert "data-meeting-delete" in js
    assert "data-meeting-title" in js

    assert ".group-folder" in css
    assert ".group-title" in css
    assert ".sidebar-dnd-note" in css
    assert ".sidebar-dnd-note { margin: -7px 12px 4px;" in css
    assert ".group-dnd-note" not in css
    assert ".group-title small" not in css
    assert ".group-title span" not in css
    assert "white-space: normal" in css
    assert "overflow-wrap: anywhere" in css
    assert ".group-meeting" in css
    assert ".meeting-compact-meta" in css


def test_sidebar_groups_can_be_renamed_and_receive_dragged_meetings():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "meeting.group_title || deriveMeetingGroup(meeting)" in js
    assert 'data-group-title="${escapeHtml(group)}"' in js
    assert 'draggable="true"' in js
    assert 'data-group-name="${escapeHtml(group)}"' in js
    assert '<textarea class="group-title-input" rows="1" readonly data-group-title-input="${escapeHtml(group)}"' in js
    assert "function resizeGroupTitleInput(input)" in js
    assert "resizeGroupTitleInputs();" in js
    assert "function updateMeetingGroup(id, groupTitle)" in js
    assert "body: JSON.stringify({ group_title: clean })" in js
    assert "function renameMeetingGroup(oldGroupTitle, newGroupTitle)" in js
    assert "API.renameGroup" in js
    assert "dragstart" in js
    assert "dragover" in js
    assert "drop" in js
    assert "dblclick" in js
    assert ".group-folder.drag-over" in css
    assert ".group-title-input" in css
    assert ".group-title-input { display: block; width: 100%; min-width: 0; min-height: 0;" in css


def test_sidebar_meeting_names_wrap_and_rename_only_after_double_click():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'readonly data-meeting-title="${m.id}"' in js
    assert 'event.type === "dblclick"' in js
    assert "enableMeetingTitleEdit(input)" in js
    assert "disableMeetingTitleEdit(input)" in js
    assert "function finishMeetingTitleEdit(input)" in js
    assert 'if (input && event.key === "Enter" && !input.hasAttribute("readonly"))' in js
    assert "finishMeetingTitleEdit(input).catch((e) => showToast(e.message));" in js
    assert "let meetingTitleClickTimer = null;" in js
    assert "function scheduleMeetingTitleSelection(id)" in js
    assert "window.clearTimeout(meetingTitleClickTimer);" in js
    assert "meetingTitleClickTimer = window.setTimeout(() => selectMeeting(id), 220);" in js
    assert "const readonlyTitle = event.target.closest(\"[data-meeting-title][readonly]\");" in js
    assert "scheduleMeetingTitleSelection(Number(el.dataset.meetingId));" in js
    assert ".meeting-title-input { width: 100%;" in css
    assert "white-space: normal" in css
    assert "overflow-wrap: anywhere" in css
    assert ".meeting-title-input[readonly]" in css


def test_frontend_uses_owner_scoped_display_id_for_visible_meeting_numbers():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "function meetingDisplayId(meeting)" in js
    assert '<span class="meeting-num">#${meetingDisplayId(m)}</span>' in js
    assert '`${formatDateTimeSeconds(m.date)} · ${fmtDuration(m.duration_sec)} · #${meetingDisplayId(m)}`' in js
    assert "showToast(`Ingested meeting #${out.display_id || out.meeting_id}`);" in js
    assert "return citation?.meeting_id ? `(meeting #${meetingDisplayIdById(citation.meeting_id)})` : \"\";" in js


def test_clicking_readonly_meeting_title_selects_that_meeting():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "if (shouldIgnoreMeetingCardClick(event.target)) return;" in js
    assert "const readonlyTitle = event.target.closest(\"[data-meeting-title][readonly]\");" in js
    assert "if (readonlyTitle) {" in js
    assert "selectMeeting(Number(el.dataset.meetingId));" in js
    assert "target.closest(\"[data-meeting-title]:not([readonly])\")" in js
    assert 'event.target.closest("input, textarea, button")' not in js


def test_renaming_meeting_rerenders_groups_after_update():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "async function updateMeetingName(id, title)" in js
    assert "state.meetings = state.meetings.map((m) => (m.id === id ? { ...m, ...out } : m));" in js
    assert "renderAll();" in js
    assert "renderMeetings();\n  renderActive();\n  showToast(\"Meeting name updated\");" not in js


def test_sidebar_meeting_datetime_includes_seconds():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'id="ingestDate" class="input" type="datetime-local" step="1"' in html
    assert "function formatDateTimeSeconds" in js
    assert "function formatLocalDateTimeInput" in js
    assert "yyyy-MM-dd HH:MM:SS" not in js
    assert "meetingDateTime(m)" in js
    assert "padStart(2, \"0\")" in js
    assert '$("ingestDate").value = formatLocalDateTimeInput()' in js


def test_terminology_panel_lists_auto_learns_and_allows_inline_editing():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="editTermsBtn"' in html
    assert 'id="saveTermsBtn"' in html
    assert 'id="applyTermsBtn"' in html
    assert 'aria-label="Refresh selected meeting with saved terminology" hidden>Refresh</button>' in html
    assert 'id="cancelTermsBtn"' in html
    assert 'id="termEditorPanel"' in html
    assert 'id="termFilterInput"' in html
    assert '<div class="term-toolbar" aria-label="Terminology editor">\n                  <input id="termFilterInput"' in html
    assert 'id="termEditList"' in html
    assert 'id="termAddRow"' in html
    assert 'id="addTermBtn"' in html
    assert 'id="suggestedTerms"' not in html
    assert 'id="glossaryForm"' not in html
    assert 'id="guideForm"' not in html
    assert 'id="termInput"' not in html
    assert 'id="wrongInput"' not in html
    assert 'glossarySuggestions: (id) => apiUrl(`/api/glossary/suggestions?meeting_id=${id}`)' in js
    assert "loadGlossarySuggestions" in js
    assert "autoLearnSuggestedTerms" in js
    assert "beginGlossaryEdit" in js
    assert "saveGlossaryEdit" in js
    assert "saveGlossaryAndApplySelected" in js
    assert "applyGlossary: (id) => apiUrl(`/api/meetings/${id}/apply_glossary`)" in js
    assert 'await saveGlossaryEdit({ exitEditing: false });' in js
    assert 'showToast("Terminology saved");' in js
    assert 'alert(`Could not refresh meeting: ${error.message}`);' in js
    assert '$("applyTermsBtn").hidden = !state.glossaryEditing' in js
    assert 'wrong: changed ? String(original.term || "").trim() : (draft.wrong || null)' in js
    assert '$("termEditorPanel").hidden = false' in js
    assert '$("termEditList").hidden = !state.glossaryEditing' in js
    assert '$("glossaryList").hidden = state.glossaryEditing' in js
    assert "glossaryFilter" in js
    assert "function glossaryMatchesFilter" in js
    assert '$("termFilterInput").addEventListener("input"' in js
    assert "data-delete-term" in js
    assert "glossaryMentionCount" in js
    assert "Number(b.count || 0) - Number(a.count || 0)" in js
    assert "data-suggested-term" not in js
    assert "Suggested terms" not in js
    assert "<button class=\"suggested-term\"" not in js
    assert "glossaryForm" not in js
    assert "guideForm" not in js
    assert ".term-toolbar" in css
    assert ".terminology { flex: 0 1 min(34vh, 260px); min-height: 0; }" in css
    assert ".knowledge { flex: 0 1 min(34vh, 260px); max-height: min(34vh, 260px);" in css
    assert ".term-filter-input" in css
    assert ".term-editor-panel" in css
    assert ".term-edit-list" in css
    assert ".term-editor-btn" in css
    assert ".term-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto auto auto auto;" in css
    assert ".term-add { display: grid; grid-template-columns: minmax(0, 1fr) 44px;" in css
    assert ".term-add .term-editor-btn { width: 44px; min-height: 32px; padding: 0; }" in css
    assert "background: #f3f3f3" in css
    assert ".suggested-terms" not in css
    assert ".suggested-term" not in css


def test_sidebar_signature_replaces_fastapi_connection_copy():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "API connected through FastAPI" not in html
    assert '<div class="memoir-signature"><em>Remembered by Memoir</em></div>' in html
    assert ".memoir-signature" in css
    assert "font-style: italic" in css
    assert "text-align: center" in css


def test_left_sidebar_is_collapsible_and_meeting_cards_hide_transcript_content():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="toggleSidebarBtn"' in html
    assert 'aria-label="Collapse sidebar"' in html
    assert "sidebarCollapsed" in js
    assert "function toggleSidebar()" in js
    assert ".app-shell.sidebar-collapsed .library" in css
    assert ".app-shell.sidebar-collapsed .workspace" in css
    assert "m.summary || m.source_file || \"No summary yet\"" not in js
    assert 'class="meeting-source-line"' not in js


def test_terminology_defaults_collapsed_to_section_name_only():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'aria-expanded="false"' in html
    assert "glossaryCollapsed: true" in js
    assert "renderGlossaryPanelState" in js
    assert ".knowledge.collapsed .glossary-panel" in css
    assert ".knowledge.collapsed .knowledge-title b" in css


def test_grouped_meetings_mockup_keeps_changes_to_left_sidebar_only():
    html = (WEB / "meeting-groups-mockup.html").read_text(encoding="utf-8")

    assert './styles.css?v=20260615-claude-redesign' in html
    assert '<section class="content stage">' in html
    assert '<aside class="chat qa">' in html
    assert 'class="stage-body"' in html
    assert 'class="executive-grid brief-grid"' in html
    assert 'class="player"' in html
    assert 'class="chat-form askbar"' in html
    assert 'id="mockNewMeetingBtn"' in html
    assert 'id="mockNewMeetingDialog"' in html
    assert 'id="mockNewMeetingForm"' in html
    assert 'id="mockMeetingTopic"' in html
    assert "function switchMockTab(tab)" in html
    assert "document.querySelectorAll(\".tabs .tab\")" in html
    assert 'id="memoryView" class="view scroll"' in html
    assert 'id="transcriptView" class="view scroll"' in html
    assert "function addMockMeeting" in html
    assert "window.switchMockTab = switchMockTab" in html
    assert "window.openMockNewMeetingDialog = openMockNewMeetingDialog" in html
    assert "initialTabFromHash" in html
    assert "history.replaceState(null, \"\", `#${tab}View`)" in html
    assert "function resetViewportToTop" in html
    assert 'window.scrollTo({ top: 0, left: 0, behavior: "auto" })' in html
    assert "requestAnimationFrame(resetViewportToTop)" in html
    assert 'window.addEventListener("load", resetViewportToTop)' in html
    assert "setTimeout(resetViewportToTop, 150)" in html
    assert "globalThis.switchMockTab = switchMockTab" in html
    assert "globalThis.openMockNewMeetingDialog = openMockNewMeetingDialog" in html
    assert 'onclick="switchMockTab(\'memory\'); return false;"' in html
    assert 'onclick="openMockNewMeetingDialog()"' in html
    assert 'data-folder-name="${group}"' in html
    assert 'contenteditable="true"' in html
    assert 'primaryTopic: "Planning"' in html
    assert 'primaryTopic: "Review"' in html
    assert 'primaryTopic: "Training"' in html
    assert '<strong>${m.title}</strong>' not in html
    assert '<div class="meeting-compact-title"><b>${m.title}</b></div>' in html
    assert '<div class="meeting-compact-meta"><span>${m.date} · ${m.time}</span><span>${m.meta}</span></div>' in html
    assert 'time: "09:00"' in html
    assert "Topic/scope can come from shared input topic or manual folder name." not in html
    assert 'class="group-hint"' not in html
    assert "data-move" not in html
    assert "<select" not in html
    assert "document.addEventListener(\"change\"" not in html
    assert 'class="main"' not in html
    assert 'class="scope-card"' not in html


def test_right_qa_panel_uses_claude_design_structure_with_memoir_colors():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert '<aside class="chat qa claude-qa">' in html
    assert '<div class="qa-title-row">' in html
    assert '<img class="qa-agent-logo" src="./assets/mnemosyne-logo.png?v=20260616-logo" alt="" aria-hidden="true">' in html
    assert '<strong class="qa-title-main">Ask Memoir</strong>' in html
    assert "Evidence Q&amp;A" not in html
    assert '<strong id="chatScope" class="qa-scope-line">Answer across memory, not just one transcript</strong>' in html
    assert '<section class="qa-scope-card">' not in html
    assert '<div id="suggestions" class="suggestions quick-prompts"></div>' in html
    assert 'class="chat-form askbar qa-composer"' in html
    assert '<textarea id="chatInput" rows="1" placeholder="Ask Memoir anything"></textarea>' in html
    assert '<span aria-hidden="true">↗</span>' in html

    assert "function renderChatTextWithInlineCitations" not in js
    assert "inlineCitationButton" not in js
    assert "inline-cite" not in js
    assert '<p>${escapeHtml(msg.text || "").replace(/\\n/g, "<br>")}</p>' in js
    assert "citation-pill" not in js
    assert "citation-dot" not in js
    assert '<div class="citations">' not in js
    assert "Họp #${escapeHtml(c.meeting_id || \"?\")}" not in js
    assert "Mình đã đọc xong transcript cuộc họp này. Hỏi bất cứ điều gì" in js
    assert "body: JSON.stringify({ question, meeting_id: state.activeId })" in js
    assert "msg-row" in js
    assert "agent-avatar" in js
    assert "mnemosyne-logo.png?v=20260616-logo" in js
    assert "quick-prompts" in css
    assert ".claude-qa { margin: 0;" in css
    claude_qa_rule = css.split(".claude-qa {", 1)[1].split("}", 1)[0]
    assert "border:" not in claude_qa_rule
    assert "border-radius:" not in claude_qa_rule
    assert "box-shadow:" not in claude_qa_rule
    assert "background: transparent" in claude_qa_rule
    assert ".qa-title-row" in css
    assert ".qa-agent-logo" in css
    assert ".qa-title-main" in css
    assert "font-size: 18px" in css
    assert ".qa-scope-line" in css
    assert "color: var(--muted)" in css
    assert ".qa-title-row > div { display: grid; gap: 3px; }" in css
    assert ".qa-scope-line { display: block; margin-top: 0; color: var(--muted); font-family: \"JetBrains Mono\", monospace; font-size: 9px; line-height: 1.2; font-weight: 500; white-space: nowrap; letter-spacing: 0; word-spacing: 0; }" in css
    assert ".qa-head { padding:" in css
    assert "border-bottom: 1px solid var(--line)" in css
    assert ".qa-scope-card" not in css
    assert ".qa-composer" in css
    assert ".msg-row" in css
    assert ".agent-avatar" in css
    assert ".inline-cite" not in css
    assert ".citation-pill" not in css
    assert ".citation-dot" not in css
    assert ".qa { min-width: 0;" in css
    assert "var(--red)" in css
    assert "var(--rail)" in css


def test_qa_enter_submits_and_shift_enter_keeps_newline():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '$("chatInput").addEventListener("keydown", (event) => {' in js
    assert 'event.key !== "Enter"' in js
    assert "event.shiftKey" in js
    assert "event.isComposing" in js
    assert "event.preventDefault();" in js
    assert '$("chatForm").requestSubmit();' in js


def test_qa_suggestion_uses_vietnamese_change_wording():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '"Decision nào đã thay đổi so với cuộc họp trước?"' in js
    assert "Decision nào đã drift so với cuộc họp trước?" not in js
    assert "Action debt nào còn mở và ai đang sở hữu?" not in js
    assert '"Ý tưởng nào từng bị bác nay được nhắc lại?"' in js
    assert "Ý tưởng nào từng bị bác nay resurfaced lại?" not in js
