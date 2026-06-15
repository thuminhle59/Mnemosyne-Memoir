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
    assert "assets/mnemosyne-logo.png" in html
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
    assert "Executive Brief" in html
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

    assert ".workspace { grid-template-columns: 244px minmax(420px, 1fr); }" in css
    assert ".terminology { flex: 0 0 auto;" in css
    assert "styles.css?v=20260615-claude-redesign" in html


def test_terminology_section_is_compact_inside_sidebar():
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert ".knowledge { flex: 0 0 auto; max-height: min(34vh, 260px);" in css
    assert ".glossary-panel { min-height: 0;" in css
    assert ".inline-form { display: grid; grid-template-columns: 1fr auto;" in css
    assert ".term-list { min-height: 0;" in css
    assert ".term span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }" in css


def test_frontend_positions_memoir_as_decision_memory_agent():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    for label in [
        "Decision Memory",
        "Decision Drift",
        "Executive Brief",
        "Decisions",
        "Contradictions &amp; Forgotten Decisions",
        "Risks &amp; Blockers",
        "Actions",
        "Evidence Lab",
        "Evidence Graph",
        "Evidence Q&amp;A",
    ]:
        assert label in html

    assert "tab: currentTabFromLocation()" in js
    assert "decisionDriftCount" in js
    assert "contradictionsForgotten" in js
    assert "renderActionStatusControls" in js
    assert "renderTranscriptEvidence" in js
    assert "seekToTimestamp" in js
    assert ".memory-hero" in css
    assert ".executive-grid" in css
    assert ".player" in css
    assert ".timestamp-button" in css


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
    assert ".executive-grid { display: grid;" in css
    assert ".scroll-card ul { min-height: 0; overflow: auto;" in css
    assert ".lab-grid { display: grid;" in css
    assert ".transcript-view { min-height: 0; overflow: auto;" in css
    assert ".player { height: 46px;" in css


def test_frontend_uses_localhost_api_when_opened_from_file_protocol():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'window.location.protocol === "file:"' in js
    assert 'http://127.0.0.1:8080' in js
    assert 'apiUrl("/api/ask")' in js


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
    assert "activeTitleInput" in html
    assert "data-meeting-delete" in js
    assert "updateMeetingName" in js
    assert "API.updateMeeting" in js
    assert ".meeting-delete" in css
    assert ".active-title-input" in css


def test_terminology_panel_shows_auto_suggestions_to_confirm():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'id="suggestedTerms"' in html
    assert 'glossarySuggestions: (id) => apiUrl(`/api/glossary/suggestions?meeting_id=${id}`)' in js
    assert "loadGlossarySuggestions" in js
    assert "renderGlossarySuggestions" in js
    assert "data-suggested-term" in js
    assert "Suggested terms" in js
    assert ".suggested-terms" in css


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
    assert 'class="meeting-source-line"' in js


def test_terminology_defaults_collapsed_to_section_name_only():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert 'aria-expanded="false"' in html
    assert "glossaryCollapsed: true" in js
    assert "renderGlossaryPanelState" in js
    assert ".knowledge.collapsed .glossary-panel" in css
    assert ".knowledge.collapsed .knowledge-title b" in css
