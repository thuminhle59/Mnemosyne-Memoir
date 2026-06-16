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
    assert 'if (file) form.append("file", file);' in js
    assert 'if (file && !text) form.append("file", file);' not in js


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
    assert ".terminology { flex: 0 0 auto;" in css
    assert "styles.css?v=20260616-ingest-progress-live" in html


def test_terminology_section_is_compact_inside_sidebar():
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert ".knowledge { flex: 0 0 auto; max-height: min(34vh, 260px);" in css
    assert ".glossary-panel { min-height: 0;" in css
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
        "Decision Drift",
        "Summary",
        "Decisions",
        "Contradictions",
        "Risks &amp; Blockers",
        "Actions",
        "Evidence Lab",
        "Evidence Graph",
        "Ask Memoir",
    ]:
        assert label in html
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
    assert ".signal-card { min-height: 52px; display: flex; align-items: baseline;" in css
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
    assert "function executiveSummaryLines" in js
    assert "splitSummarySentences" in js
    assert "chosen.slice(0, 3)" in js
    assert "clean.slice" not in js
    assert "trim()}..." not in js
    assert 'const label = meeting ? "Meeting summary" : "Summary";' in js
    assert "const readable = executiveSummaryLines(meeting)" in js
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
    assert ".summary p + p" in css
    assert ".summary-groups" not in css
    assert ".summary-group" not in css


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
    assert ".signal-card span { min-width: 0;" in css
    assert "font-size: 9px" in css
    assert "font-size: 24px" in css


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
    assert ".action-toolbar" not in css
    assert "scrollIntoView({ behavior: \"smooth\", block: \"start\" })" in (WEB / "app.js").read_text(encoding="utf-8")
    assert "<h2>Contradictions</h2>" in html
    assert "Contradictions &amp; Forgotten Decisions" not in html
    assert "redetectContradictions" not in (WEB / "app.js").read_text(encoding="utf-8")
    assert "Re-detect" not in html
    assert ".scroll-card ul { flex: 1; min-height: 0; overflow: auto;" in css
    assert ".scroll-card.wide { grid-column: 1 / -1; height: clamp(190px, 24vh, 250px); max-height: none; }" in css
    assert ".transcript-view, .memory-grid article ul,\n  .action-workbench ul, .evidence-graph ul { overflow: visible; }" in css
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
    assert "state.actions = await request(API.actions);\n  renderMemory();\n  showToast(\"Action status updated\");" not in js
    assert 'const openScore = statusKey(action.status) !== "completed" ? 1 : 0;' not in js
    assert 'item.owner || "Unassigned"' not in js
    assert ".action-check-row" in css
    assert ".action-check-input" in css
    assert ".action-completed" in css
    assert ".action-status-controls" not in css
    assert ".decision-state" not in css
    assert ".executive-grid, .lab-grid, .brief-grid, .memory-board { grid-template-columns: 1fr;" not in css
    assert ".lab-grid { display: grid;" in css
    assert ".transcript-view { min-height: 0; overflow: auto;" in css
    assert ".player { height: 46px;" in css


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
    assert "await requestWithXhr(url, options)" in js
    assert "new XMLHttpRequest()" in js


def test_frontend_request_uses_xhr_for_upload_progress_events():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'const needsUploadProgress = typeof options.onUploadProgress === "function";' in js
    assert 'xhr.upload.onprogress = (event) => {' in js
    assert "options.onUploadProgress(event.loaded, event.total, event)" in js
    assert 'typeof window.fetch === "function" && !needsUploadProgress' in js
    assert "requestWithXhr(url, options)" in js


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
    assert html.count("ingest-source-box") == 3

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
    assert "setUploadProgress(10 + ratio * 70, \"Uploading\");" in js
    assert "setUploadProgress(chunkBase, \"Uploading\");" in js
    assert "const chunkSpan = 70 / totalChunks;" in js
    assert "setUploadProgress(chunkBase + ratio * chunkSpan, \"Uploading\");" in js
    assert "setIngestPercent(85);" in js
    assert "setIngestPercent(100);" in js
    assert "Math.round(percent)" in js
    assert '.ingest-progress[hidden] { display: none; }' in css
    assert ".ingest-progress" in css
    assert ".ingest-progress.error" in css
    assert ".ingest-progress-track" in css
    assert ".ingest-progress-fill" in css
    assert ".upload-progress" not in css
    assert ".upload-progress-fill" not in css


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
    assert 'id="playerLabel"' in html
    assert "function renderMeetingPlayer()" in js
    assert "audio.src = API.audio(m.id)" in js
    assert "function toggleMeetingPlayback()" in js
    assert "await audio.play()" in js
    assert "m.can_play_audio" in js
    assert "const canPlay = Boolean(m?.id && m.can_play_audio);" in js
    assert ".play.playing::before" in css


def test_evidence_lab_uses_readonly_timestamped_transcript():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert '<textarea id="transcriptText"' not in html
    assert 'id="transcriptText" class="transcript-view"' in html
    assert 'id="transcriptSearch"' in html
    assert "function renderTranscriptEvidence()" in js
    assert "collectEvidenceMentions()" in js
    assert "timestamp-button" in js
    assert "audio.currentTime = seconds" in js


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
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert "function deriveMeetingGroup" in js
    assert "function groupMeetingsForSidebar" in js
    assert 'class="group-folder"' in js
    assert 'class="group-title"' in js
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
    assert ".group-title span" not in css
    assert "white-space: normal" in css
    assert "overflow-wrap: anywhere" in css
    assert ".group-meeting" in css
    assert ".meeting-compact-meta" in css


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
    assert "function shouldIgnoreMeetingCardClick" in js
    assert "target.closest(\"[data-meeting-title]:not([readonly])\")" in js
    assert 'target.closest("button, input")' in js
    assert 'event.target.closest("input, textarea, button")' not in js
    assert ".meeting-title-input { width: 100%;" in css
    assert "white-space: normal" in css
    assert "overflow-wrap: anywhere" in css
    assert ".meeting-title-input[readonly]" in css


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
    assert 'id="cancelTermsBtn"' in html
    assert 'id="termEditorPanel"' in html
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
    assert '$("termEditorPanel").hidden = false' in js
    assert '$("termEditList").hidden = !state.glossaryEditing' in js
    assert '$("glossaryList").hidden = state.glossaryEditing' in js
    assert "data-delete-term" in js
    assert "glossaryMentionCount" in js
    assert "Number(b.count || 0) - Number(a.count || 0)" in js
    assert "data-suggested-term" not in js
    assert "Suggested terms" not in js
    assert "<button class=\"suggested-term\"" not in js
    assert "glossaryForm" not in js
    assert "guideForm" not in js
    assert ".term-toolbar" in css
    assert ".term-editor-panel" in css
    assert ".term-edit-list" in css
    assert ".term-editor-btn" in css
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
    assert '<strong id="chatScope" class="qa-scope-line">Ask across memory, not one transcript</strong>' in html
    assert '<section class="qa-scope-card">' not in html
    assert '<div id="suggestions" class="suggestions quick-prompts"></div>' in html
    assert 'class="chat-form askbar qa-composer"' in html
    assert '<span aria-hidden="true">↗</span>' in html

    assert "citation-pill" in js
    assert "citation-dot" in js
    assert "Mình đã đọc xong transcript cuộc họp này. Hỏi bất cứ điều gì" in js
    assert "msg-row" in js
    assert "agent-avatar" in js
    assert "mnemosyne-logo.png?v=20260616-logo" in js
    assert "quick-prompts" in css
    assert ".claude-qa { margin:" in css
    assert "background: var(--surface)" in css
    assert ".qa-title-row" in css
    assert ".qa-agent-logo" in css
    assert ".qa-title-main" in css
    assert "font-size: 18px" in css
    assert ".qa-scope-line" in css
    assert "color: var(--muted)" in css
    assert ".qa-scope-line { display: block; margin-top: 6px; color: var(--muted); font-family: \"JetBrains Mono\", monospace; font-size: 9px; line-height: 1.3; font-weight: 500; white-space: nowrap; letter-spacing: 0; }" in css
    assert ".qa-head { padding:" in css
    assert "border-bottom: 1px solid var(--line)" in css
    assert ".qa-scope-card" not in css
    assert ".qa-composer" in css
    assert ".msg-row" in css
    assert ".agent-avatar" in css
    assert ".citation-pill" in css
    assert ".qa { min-width: 0;" in css
    assert "var(--red)" in css
    assert "var(--rail)" in css
