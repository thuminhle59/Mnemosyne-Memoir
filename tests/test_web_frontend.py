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

    for tab in ["transcript", "digest", "memory"]:
        assert f'data-tab="{tab}"' in html
        assert f'{tab}View' in html

    assert 'id="tabMemory"' in html
    assert "Memory Ops" in html
    assert 'section id="memoryView" class="view scroll active"' in html
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

    assert ".sidebar { grid-row: 1 / span 2; }" in css
    assert ".terminology { flex: 0 0 auto;" in css
    assert "styles.css?v=20260615-memoir-soft-gray" in html


def test_terminology_section_is_compact_inside_sidebar():
    css = (WEB / "styles.css").read_text(encoding="utf-8")

    assert ".terminology { flex: 0 0 auto; max-height: min(34vh, 230px);" in css
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
        "Contradiction Radar",
        "Resurfaced Decisions",
        "Action Memory",
        "Evidence Lab",
        "Evidence Q&amp;A",
        "Not a meeting recorder",
    ]:
        assert label in html

    assert "tab: currentTabFromLocation()" in js
    assert "decisionDriftCount" in js
    assert "decisionThreads" in js
    assert "contradictionList" in js
    assert "resurfacedList" in js
    assert ".memory-hero" in css
    assert ".agent-edge-grid" in css
    assert ".ops-intro" in css
    assert ".radar-card" in css


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

    assert 'class="memory-overview"' in html
    assert 'class="memory-side-stack"' in html
    assert ".memory-overview { display: grid;" in css
    assert ".memory-side-stack { display: grid;" in css
    assert ".memory-grid article { min-height: 0; max-height:" in css
    assert ".memory-grid article ul { min-height: 0; overflow: auto;" in css
    assert ".memory-grid article.wide { max-height:" in css
    assert ".ops-intro { min-height:" in css
    assert ".radar-card { min-height: 88px;" in css


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


def test_frontend_does_not_hardcode_200mb_upload_limit():
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "Selected file is larger than 200 MB" not in js
    assert "This file is larger than 200 MB" not in js
    assert "formatUploadLimit" in js
