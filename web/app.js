const FILE_PROTOCOL_REDIRECTED = window.location.protocol === "file:";
if (FILE_PROTOCOL_REDIRECTED) {
  window.location.replace("http://127.0.0.1:8080/");
}

const API_ORIGIN = window.location.protocol === "file:" ? "http://127.0.0.1:8080" : "";
const apiUrl = (path) => `${API_ORIGIN}${path}`;

const API = {
  health: apiUrl("/api/health"),
  config: apiUrl("/api/config"),
  uploads: apiUrl("/api/uploads"),
  uploadChunk: (id) => apiUrl(`/api/uploads/${id}/chunks`),
  uploadComplete: (id) => apiUrl(`/api/uploads/${id}/complete`),
  stats: apiUrl("/api/stats"),
  meetings: apiUrl("/api/meetings"),
  meeting: (id) => apiUrl(`/api/meetings/${id}`),
  audio: (id) => apiUrl(`/api/meetings/${id}/audio`),
  updateMeeting: (id) => apiUrl(`/api/meetings/${id}`),
  ask: apiUrl("/api/ask"),
  ingest: apiUrl("/api/ingest"),
  actions: apiUrl("/api/actions"),
  action: (id) => apiUrl(`/api/actions/${id}`),
  contradictions: apiUrl("/api/contradictions"),
  resurfaced: apiUrl("/api/resurfaced"),
  digest: apiUrl("/api/digest"),
  followup: apiUrl("/api/followup"),
  scanForgotten: apiUrl("/api/scan_forgotten"),
  reanalyze: (id) => apiUrl(`/api/meetings/${id}/reanalyze`),
  deleteMeeting: (id) => apiUrl(`/api/meetings/${id}`),
  glossary: apiUrl("/api/glossary"),
  glossarySuggestions: (id) => apiUrl(`/api/glossary/suggestions?meeting_id=${id}`),
  glossaryLearn: apiUrl("/api/glossary/learn"),
  glossaryItem: (id) => apiUrl(`/api/glossary/${id}`),
};

const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
const DIRECT_UPLOAD_BYTES = 64 * 1024 * 1024;
const DEFAULT_UPLOAD_CHUNK_BYTES = 16 * 1024 * 1024;

function currentTabFromLocation() {
  return {
    "#memoryView": "memory",
    "#digestView": "digest",
    "#transcriptView": "transcript",
  }[window.location.hash] || window.__MNEMOSYNE_TAB || "digest";
}

const state = {
  meetings: [],
  activeId: null,
  active: null,
  stats: {},
  actions: [],
  contradictions: [],
  resurfaced: [],
  glossary: [],
  glossarySuggestions: [],
  maxUploadBytes: MAX_UPLOAD_BYTES,
  uploadChunkBytes: DEFAULT_UPLOAD_CHUNK_BYTES,
  tab: currentTabFromLocation(),
  librarySearch: "",
  timeFilter: "all",
  sidebarCollapsed: false,
  glossaryCollapsed: true,
  transcriptSearch: "",
  previewUrl: null,
  recordedFile: null,
  recorder: null,
  recordChunks: [],
  recordStream: null,
  recordTimer: null,
  recordStartMs: 0,
  chat: [
    {
      role: "assistant",
      text: "Mình đã sẵn sàng vận hành lớp trí nhớ quyết định. Hỏi về decision drift, mâu thuẫn, việc còn mở hoặc bằng chứng lịch sử; câu trả lời sẽ kèm nguồn khi backend có chứng cứ.",
      citations: [],
    },
  ],
};

const $ = (id) => document.getElementById(id);

async function request(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (error) {
    throw new Error(`Cannot reach Memoir API at ${API_ORIGIN || window.location.origin}. Make sure the server is running on http://127.0.0.1:8080.`);
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      message = data.detail || data.message || message;
    } catch (_) {
      // Keep HTTP status as message.
    }
    throw new Error(message);
  }
  return res.json();
}

function isPayloadTooLarge(error) {
  return /413|payload too large|request entity too large|larger than/i.test(error?.message || "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function setBusy(label) {
  showToast(label);
}

function setUploadStatus(message) {
  const status = $("uploadStatus");
  if (status) status.textContent = message || "";
}

function setIngestBusy(isBusy) {
  const submit = $("ingestSubmitBtn");
  const cancel = $("cancelIngestBtn");
  const close = $("closeImportBtn");
  if (submit) {
    submit.disabled = isBusy;
    submit.textContent = isBusy ? "Uploading..." : "Ingest";
  }
  if (cancel) cancel.disabled = isBusy;
  if (close) close.disabled = isBusy;
}

function formatUploadLimit(bytes = state.maxUploadBytes) {
  return `${Math.floor(bytes / 1024 / 1024)} MB`;
}

function isAudioFile(file) {
  return /^audio\//.test(file?.type || "") || /\.(wav|mp3|m4a|aiff|ogg)$/i.test(file?.name || "");
}

function isVideoFile(file) {
  return /^video\//.test(file?.type || "") || /\.(mp4|webm)$/i.test(file?.name || "");
}

function isPlayableSourceFile(name) {
  return /\.(wav|mp3|m4a|aiff|ogg|mp4|webm)$/i.test(name || "");
}

function clearFilePreview() {
  const preview = $("filePreview");
  const audio = $("audioPreview");
  const video = $("videoPreview");
  if (audio) {
    audio.pause();
    audio.removeAttribute("src");
    audio.hidden = true;
    audio.load();
  }
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.hidden = true;
    video.load();
  }
  if (state.previewUrl) {
    URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = null;
  }
  if (preview) preview.hidden = true;
}

function updateFilePreview(file) {
  clearFilePreview();
  if (!file || (!isAudioFile(file) && !isVideoFile(file))) return;
  const preview = $("filePreview");
  const media = isVideoFile(file) ? $("videoPreview") : $("audioPreview");
  state.previewUrl = URL.createObjectURL(file);
  media.src = state.previewUrl;
  media.hidden = false;
  preview.hidden = false;
}

function fmtDate(value) {
  return value || "no date";
}

function fmtDuration(seconds) {
  if (!seconds) return "transcript";
  const mm = Math.floor(seconds / 60);
  const ss = String(seconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function fmtClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const mm = Math.floor(seconds / 60);
  const ss = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${String(mm).padStart(2, "0")}:${ss}`;
}

function parseTimestamp(value) {
  if (!value) return null;
  const parts = String(value).trim().split(":").map((x) => Number.parseInt(x, 10));
  if (parts.some((x) => !Number.isFinite(x))) return null;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return null;
}

function listHtml(items, render) {
  if (!items || !items.length) return '<li class="empty">No items yet</li>';
  return items.map(render).join("");
}

function timestampButton(timestamp) {
  return timestamp ? `<button class="timestamp-button" type="button" data-ts="${escapeHtml(timestamp)}">≈${escapeHtml(timestamp)}</button>` : "";
}

function renderLine(text, timestamp, detail = "") {
  return `
    <li class="line-item">
      <p>${escapeHtml(text)}</p>
      <div class="line-meta">${timestampButton(timestamp)}${detail ? `<span>${escapeHtml(detail)}</span>` : ""}</div>
    </li>
  `;
}

function renderStats() {
  $("meetingCount").textContent = state.stats.meetings ?? state.meetings.length;
  $("termCount").textContent = `${state.glossary.length} terms`;
}

function renderMeetings() {
  const q = state.librarySearch.trim().toLowerCase();
  const meetings = state.meetings.filter((m) => {
    const text = `${m.title || ""} ${m.summary || ""} ${m.date || ""}`.toLowerCase();
    return (!q || text.includes(q)) && meetingMatchesTimeFilter(m);
  });
  $("meetingList").innerHTML = meetings.length ? meetings.map((m) => `
    <div class="meeting-card ${m.id === state.activeId ? "active" : ""}" data-meeting-id="${m.id}">
      <div class="card-meta">
        <span class="status-dot ${m.can_play_audio ? "ready" : ""}"></span>
        <span>${fmtDate(m.date)}</span>
        <span style="margin-left:auto">${escapeHtml(m.source_file || fmtDuration(m.duration_sec))}</span>
        <button class="meeting-delete" type="button" data-meeting-delete="${m.id}" aria-label="Delete meeting">x</button>
      </div>
      <input class="meeting-title-input" data-meeting-title="${m.id}" value="${escapeHtml(m.title || `Meeting #${m.id}`)}" aria-label="Edit meeting name">
      <p class="meeting-source-line">${escapeHtml(m.source_file || `Meeting #${m.id}`)}</p>
    </div>
  `).join("") : '<div class="meeting-card"><h3>No memory sources</h3><p>Use New meeting to ingest one.</p></div>';

  document.querySelectorAll("[data-meeting-id]").forEach((el) => {
    el.addEventListener("click", (event) => {
      if (event.target.closest("input, button")) return;
      selectMeeting(Number(el.dataset.meetingId));
    });
  });
}

function meetingMatchesTimeFilter(meeting) {
  if (state.timeFilter === "all" || !meeting.date) return true;
  const parsed = new Date(meeting.date);
  if (Number.isNaN(parsed.getTime())) return true;
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (state.timeFilter === "today") return parsed >= startToday;
  const startWeek = new Date(startToday);
  startWeek.setDate(startToday.getDate() - startToday.getDay());
  if (state.timeFilter === "week") return parsed >= startWeek;
  const startMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  if (state.timeFilter === "month") return parsed >= startMonth;
  return true;
}

function renderActive() {
  const m = state.active;
  $("activeMeta").textContent = m ? `${fmtDate(m.date)} · ${fmtDuration(m.duration_sec)} · #${m.id}` : "No meeting selected";
  $("activeTitleInput").value = m ? (m.title || `Meeting #${m.id}`) : "Memoir";
  $("activeTitleInput").disabled = !m;
  $("activeSummary").textContent = m ? (m.summary || "No summary yet.") : "Load meetings or ingest a transcript to start building a cross-meeting decision memory layer.";
  renderMeetingPlayer();
  renderDigest();
  renderMemory();
  renderEvidence();
}

function renderMeetingPlayer() {
  const m = state.active;
  const audio = $("meetingAudio");
  const button = $("playerToggleBtn");
  const label = $("playerLabel");
  const time = $("playerTime");
  const canPlay = Boolean(m?.id && m.can_play_audio);
  audio.pause();
  button.classList.remove("playing");
  time.textContent = "00:00";
  if (!canPlay) {
    audio.removeAttribute("src");
    audio.load();
    button.disabled = true;
    label.textContent = m && isPlayableSourceFile(m.source_file) ? "Audio not stored; re-upload to enable playback" : (m ? "No audio for this meeting" : "No audio selected");
    return;
  }
  audio.src = API.audio(m.id);
  button.disabled = false;
  label.textContent = m.source_file || `Meeting #${m.id}`;
}

async function toggleMeetingPlayback() {
  const audio = $("meetingAudio");
  const button = $("playerToggleBtn");
  if (!audio.src || button.disabled) return;
  try {
    if (audio.paused) {
      await audio.play();
    } else {
      audio.pause();
    }
  } catch (error) {
    showToast("No stored audio available for this meeting yet.");
  }
}

async function seekToTimestamp(timestamp) {
  const seconds = parseTimestamp(timestamp);
  const audio = $("meetingAudio");
  if (seconds === null || !audio.src) {
    showToast("No playable timestamp for this meeting.");
    return;
  }
  audio.currentTime = seconds;
  try {
    await audio.play();
  } catch (error) {
    showToast("No stored audio available for this meeting yet.");
  }
}

function renderDigest() {
  const m = state.active || {};
  const facts = m.facts || [];
  const factDecisions = facts.filter((f) => f.type === "quyết định" || f.type === "cam kết");
  const decisionRows = [
    ...(m.key_points || []).map((text) => ({ text, detail: "Signal brief" })),
    ...(m.decisions || []).map((d) => ({ text: d.text, timestamp: d.timestamp, detail: "Decision" })),
    ...factDecisions.map((f) => ({ text: `${f.subject}: ${f.statement}`, timestamp: f.timestamp, detail: `${f.type} · ${f.status}` })),
  ];
  const contradictionRows = [
    ...state.contradictions.map((c) => ({
      text: `[${c.severity}] ${c.subject}: ${c.explanation}`,
      timestamp: c.new?.timestamp || c.old?.timestamp,
      detail: "Contradiction",
    })),
    ...state.resurfaced.map((r) => ({
      text: `${r.subject}: ${r.explanation}`,
      timestamp: r.new?.timestamp || r.old?.timestamp,
      detail: r.kind || "Forgotten decision",
    })),
  ];
  $("decisions").innerHTML = listHtml(decisionRows, (d) => renderLine(d.text, d.timestamp, d.detail));
  $("contradictionsForgotten").innerHTML = listHtml(contradictionRows, (r) => renderLine(r.text, r.timestamp, r.detail));
  $("risks").innerHTML = listHtml(m.risks, (x) => renderLine(x, null, "Risk"));
}

function renderMemory() {
  const m = state.active || {};
  const openActions = state.actions.filter((a) => a.status !== "xong");
  $("decisionDriftCount").textContent = state.contradictions.length + state.resurfaced.length;
  $("contradictionCount").textContent = state.contradictions.length;
  $("openActionCount").textContent = openActions.length;
  const currentDecisions = (m.decisions || []).map((d) => ({ ...d, type: "decision" }));
  const actions = state.actions.map((a) => ({ ...a, type: "action" }));
  $("allActions").innerHTML = listHtml([...currentDecisions, ...actions], (item) => {
    if (item.type === "decision") {
      return `
        <li class="decision-state">
          <b>${escapeHtml(item.text)}</b>
          <div class="line-meta">${timestampButton(item.timestamp)}<span>Current decision state</span></div>
        </li>
      `;
    }
    return `
      <li>
        <b>${escapeHtml(item.task)}</b>
        <div class="line-meta">
          ${timestampButton(item.timestamp)}
          <span>${escapeHtml(item.owner || "Unassigned")} · ${escapeHtml(item.deadline || "no deadline")} · ${escapeHtml(statusLabel(item.status))}</span>
        </div>
        ${renderActionStatusControls(item)}
      </li>
    `;
  });
}

function statusKey(status) {
  if (status === "xong" || status === "completed") return "completed";
  if (status === "treo" || status === "cancel" || status === "cancelled") return "cancel";
  return "pending";
}

function statusLabel(status) {
  return {
    pending: "pending",
    completed: "completed",
    cancel: "cancel",
  }[statusKey(status)];
}

function renderActionStatusControls(action) {
  return `
    <div class="action-status-controls" aria-label="Action status">
      ${["pending", "completed", "cancel"].map((status) => `
        <button type="button" class="${statusKey(action.status) === status ? "active" : ""}" data-action-status="${status}" data-action-id="${action.id}">
          ${status}
        </button>
      `).join("")}
    </div>
  `;
}

function collectEvidenceMentions() {
  const m = state.active || {};
  const mentions = [];
  const add = (quote, timestamp, label) => {
    if (quote && timestamp) mentions.push({ quote: String(quote), timestamp, label });
  };
  (m.decisions || []).forEach((d) => add(d.quote || d.text, d.timestamp, "Decision"));
  (m.action_items || []).forEach((a) => add(a.quote || a.task, a.timestamp, "Action"));
  (m.facts || []).forEach((f) => add(f.quote || f.statement, f.timestamp, f.type));
  state.contradictions.forEach((c) => {
    add(c.new?.quote, c.new?.timestamp, "Contradiction");
    add(c.old?.quote, c.old?.timestamp, "Contradiction");
  });
  state.resurfaced.forEach((r) => {
    add(r.new?.quote, r.new?.timestamp, "Forgotten");
    add(r.old?.quote, r.old?.timestamp, "Forgotten");
  });
  return mentions;
}

function highlightQuery(text, query) {
  const safe = escapeHtml(text);
  if (!query) return safe;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return safe.replace(new RegExp(escaped, "ig"), (match) => `<mark>${match}</mark>`);
}

function renderTranscriptEvidence() {
  const transcript = state.active?.transcript || "";
  const query = state.transcriptSearch.trim();
  const mentions = collectEvidenceMentions();
  const lines = transcript.split(/\n+/).filter((line) => line.trim());
  const rows = lines.length ? lines : [transcript || "No transcript selected."];
  const filtered = rows.filter((line) => {
    if (!query) return true;
    return line.toLowerCase().includes(query.toLowerCase());
  });
  $("transcriptText").innerHTML = filtered.map((line) => {
    const hit = mentions.find((m) => {
      const quote = m.quote.toLowerCase();
      const text = line.toLowerCase();
      return quote.includes(text.slice(0, 80)) || text.includes(quote.slice(0, 80));
    });
    return `
      <div class="transcript-line">
        <div class="line-meta">${hit ? timestampButton(hit.timestamp) : ""}${hit ? `<span>${escapeHtml(hit.label)}</span>` : ""}</div>
        <div>${highlightQuery(line, query)}</div>
      </div>
    `;
  }).join("");
}

function renderEvidence() {
  const allFacts = state.active?.facts || [];
  $("facts").innerHTML = listHtml(allFacts, (f) => `
    <li class="line-item">
      <p><b>${escapeHtml(f.subject)}</b>: ${escapeHtml(f.statement)}</p>
      <div class="line-meta">${timestampButton(f.timestamp)}<span>${escapeHtml(f.type)} · ${escapeHtml(f.status)}</span></div>
    </li>
  `);
  renderTranscriptEvidence();
}

function renderGlossary() {
  $("glossaryList").innerHTML = state.glossary.length ? state.glossary.map((g) => `
    <div class="term">
      <span>${g.wrong ? `${escapeHtml(g.wrong)} -> ` : ""}<b>${escapeHtml(g.term)}</b></span>
      <button class="ghost-btn" data-term-delete="${g.id}" type="button">x</button>
    </div>
  `).join("") : '<div class="term">No terminology yet</div>';
  document.querySelectorAll("[data-term-delete]").forEach((btn) => {
    btn.addEventListener("click", () => deleteTerm(Number(btn.dataset.termDelete)));
  });
  renderGlossarySuggestions();
  renderGlossaryPanelState();
  renderStats();
}

function renderGlossaryPanelState() {
  const section = document.querySelector(".terminology");
  const button = $("toggleGlossaryBtn");
  if (!section || !button) return;
  section.classList.toggle("collapsed", state.glossaryCollapsed);
  button.setAttribute("aria-expanded", String(!state.glossaryCollapsed));
}

function renderGlossarySuggestions() {
  const box = $("suggestedTerms");
  if (!box) return;
  if (!state.activeId) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `
    <div class="suggested-title">Suggested terms</div>
    ${state.glossarySuggestions.length ? state.glossarySuggestions.map((item) => `
      <button class="suggested-term" type="button" data-suggested-term="${escapeHtml(item.term)}">
        <span>${escapeHtml(item.term)}</span>
        <small>${escapeHtml(item.reason || "Found in this meeting")}</small>
      </button>
    `).join("") : '<div class="suggested-empty">No new terms found</div>'}
  `;
}

function renderChat() {
  $("chatMessages").innerHTML = state.chat.map((msg) => `
    <div class="msg ${msg.role === "user" ? "user" : "assistant"}">
      ${escapeHtml(msg.text).replace(/\n/g, "<br>")}
      ${msg.citations && msg.citations.length ? `<div class="citations">${msg.citations.map((c) => `
        <div>#${escapeHtml(c.meeting_id || "?")} · ${escapeHtml(c.meeting_title || "")} ${c.timestamp ? `· ≈${escapeHtml(c.timestamp)}` : ""}<br><small>${escapeHtml(c.quote || "")}</small></div>
      `).join("")}</div>` : ""}
    </div>
  `).join("");
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
}

function renderSuggestions() {
  const suggestions = [
    "Decision nào đã drift so với cuộc họp trước?",
    "Có claim nào đang mâu thuẫn với lịch sử không?",
    "Action debt nào còn mở và ai đang sở hữu?",
    "Ý tưởng nào từng bị bác nay resurfaced lại?",
  ];
  $("suggestions").innerHTML = suggestions.map((s) => `<button type="button" data-suggestion="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join("");
  document.querySelectorAll("[data-suggestion]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("chatInput").value = btn.dataset.suggestion;
      $("chatForm").requestSubmit();
    });
  });
}

function renderTabs() {
  state.tab = window.__MNEMOSYNE_TAB || state.tab;
  ["digest", "memory", "transcript"].forEach((key) => {
    document.querySelector(`[data-tab="${key}"]`)?.classList.toggle("active", state.tab === key);
    $(`${key}View`)?.classList.toggle("active", state.tab === key);
  });
}

function switchTab(tab) {
  if (!["digest", "memory", "transcript"].includes(tab)) return;
  window.__MNEMOSYNE_TAB = tab;
  state.tab = tab;
  renderTabs();
}

window.switchTab = switchTab;

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  $("app").classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  const button = $("toggleSidebarBtn");
  if (button) {
    button.textContent = state.sidebarCollapsed ? "›" : "‹";
    button.setAttribute("aria-label", state.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar");
    button.setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  }
}

function renderAll() {
  renderStats();
  renderMeetings();
  renderActive();
  renderGlossary();
  renderChat();
  renderTabs();
}

async function loadBaseData() {
  const [config, stats, meetings, actions, contradictions, resurfaced, glossary] = await Promise.all([
    request(API.config),
    request(API.stats),
    request(API.meetings),
    request(API.actions),
    request(API.contradictions),
    request(API.resurfaced),
    request(API.glossary),
  ]);
  state.maxUploadBytes = config.max_upload_bytes || MAX_UPLOAD_BYTES;
  state.uploadChunkBytes = config.upload_chunk_bytes || DEFAULT_UPLOAD_CHUNK_BYTES;
  state.stats = stats;
  state.meetings = meetings;
  state.actions = actions;
  state.contradictions = contradictions;
  state.resurfaced = resurfaced;
  state.glossary = glossary;
  if (!state.activeId && meetings.length) {
    await selectMeeting(meetings[0].id, false);
  }
  renderAll();
}

async function selectMeeting(id, rerender = true) {
  state.activeId = id;
  state.active = await request(API.meeting(id));
  await loadGlossarySuggestions(id);
  if (rerender) renderAll();
}

async function loadGlossarySuggestions(id = state.activeId) {
  if (!id) {
    state.glossarySuggestions = [];
    return;
  }
  try {
    const out = await request(API.glossarySuggestions(id));
    state.glossarySuggestions = out.suggestions || [];
  } catch (_) {
    state.glossarySuggestions = [];
  }
}

async function updateMeetingName(id, title) {
  const clean = title.trim();
  if (!id || !clean) return;
  const out = await request(API.updateMeeting(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: clean, source_file: clean }),
  });
  state.meetings = state.meetings.map((m) => (m.id === id ? { ...m, ...out } : m));
  if (state.activeId === id) {
    state.active = { ...state.active, ...out };
  }
  renderMeetings();
  renderActive();
  showToast("Meeting name updated");
}

async function sendQuestion(question) {
  state.chat.push({ role: "user", text: question, citations: [] });
  renderChat();
  const answer = await request(API.ask, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  state.chat.push({ role: "assistant", text: answer.answer || "No answer.", citations: answer.citations || [] });
  renderChat();
}

function fmtRecClock(ms) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function setRecordingUi(active) {
  $("recordTabBtn").hidden = active;
  $("recordMicBtn").hidden = active;
  $("recordStopBtn").hidden = !active;
}

function resetRecording() {
  if (state.recorder && state.recorder.state !== "inactive") {
    try { state.recorder.stop(); } catch (_e) {}
  }
  if (state.recordStream) {
    state.recordStream.getTracks().forEach((t) => t.stop());
    state.recordStream = null;
  }
  if (state.recordTimer) { clearInterval(state.recordTimer); state.recordTimer = null; }
  state.recorder = null;
  state.recordChunks = [];
  state.recordedFile = null;
  setRecordingUi(false);
  const status = $("recordStatus");
  if (status) status.textContent = "";
}

async function startRecording(mode) {
  if (!navigator.mediaDevices) {
    $("recordStatus").textContent = "Trình duyệt không hỗ trợ ghi âm.";
    return;
  }
  try {
    let stream;
    if (mode === "tab") {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      if (!stream.getAudioTracks().length) {
        stream.getTracks().forEach((t) => t.stop());
        throw new Error("Không bắt được audio — khi chia sẻ hãy tick 'Share tab audio'.");
      }
    } else {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }
    state.recordStream = stream;
    state.recordChunks = [];
    const audioStream = new MediaStream(stream.getAudioTracks());  // audio-only -> nhẹ
    const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    const rec = new MediaRecorder(audioStream, mime ? { mimeType: mime } : undefined);
    rec.ondataavailable = (e) => { if (e.data && e.data.size) state.recordChunks.push(e.data); };
    rec.onstop = onRecordingStop;
    state.recorder = rec;
    rec.start(1000);
    state.recordStartMs = Date.now();
    setRecordingUi(true);
    $("recordStatus").textContent = "● Đang ghi 00:00";
    state.recordTimer = setInterval(() => {
      $("recordStatus").textContent = "● Đang ghi " + fmtRecClock(Date.now() - state.recordStartMs);
    }, 500);
    stream.getVideoTracks().forEach((t) => t.addEventListener("ended", stopRecording));
  } catch (err) {
    $("recordStatus").textContent = "Lỗi ghi: " + err.message;
  }
}

function stopRecording() {
  if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
}

function onRecordingStop() {
  if (state.recordTimer) { clearInterval(state.recordTimer); state.recordTimer = null; }
  if (state.recordStream) { state.recordStream.getTracks().forEach((t) => t.stop()); state.recordStream = null; }
  setRecordingUi(false);
  const secs = Math.round((Date.now() - state.recordStartMs) / 1000);
  const type = (state.recorder && state.recorder.mimeType) || "audio/webm";
  const blob = new Blob(state.recordChunks, { type });
  state.recordChunks = [];
  if (!blob.size) { $("recordStatus").textContent = "Không ghi được dữ liệu."; return; }
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  state.recordedFile = new File([blob], `recording-${stamp}.webm`, { type: blob.type });
  $("recordStatus").textContent =
    `✓ Đã ghi ${fmtRecClock(secs * 1000)} (${(blob.size / 1024 / 1024).toFixed(1)} MB) — bấm Ingest để nạp.`;
  $("ingestFileLabel").textContent = state.recordedFile.name;
  try { updateFilePreview(state.recordedFile); } catch (_e) {}
}

async function ingestMeeting() {
  const form = new FormData();
  const file = $("ingestFile").files[0] || state.recordedFile;
  const text = $("ingestText").value.trim();
  if (!file && !text) throw new Error("Paste transcript or choose a file.");
  if (file && file.size === 0) throw new Error("Selected file is empty. Choose a different file.");
  if (file && file.size > state.maxUploadBytes) throw new Error(`Selected file is larger than ${formatUploadLimit()}. Split it or use a shorter clip.`);
  if (file) form.append("file", file);
  if (text) form.append("text", text);
  form.append("title", $("ingestTitle").value.trim());
  form.append("date", $("ingestDate").value);
  form.append("extract", $("extractAudio").checked ? "true" : "false");
  form.append("on_duplicate", "new");
  setUploadStatus(file ? `Uploading ${file.name}... keep this window open.` : "Sending transcript...");
  await request(API.health);
  let out;
  if (file && file.size > DIRECT_UPLOAD_BYTES) {
    out = await chunkedIngestMeeting(file, text);
  } else {
    try {
      out = await request(API.ingest, { method: "POST", body: form });
    } catch (error) {
      if (!file || !isPayloadTooLarge(error)) throw error;
      setUploadStatus("Gateway rejected direct upload. Switching to chunked upload...");
      out = await chunkedIngestMeeting(file, text);
    }
  }
  setUploadStatus("Upload complete. Refreshing memory...");
  $("importDialog").close();
  clearFilePreview();
  resetRecording();
  showToast(`Ingested meeting #${out.meeting_id}`);
  await loadBaseData();
  await selectMeeting(out.meeting_id);
}

async function chunkedIngestMeeting(file, text) {
  const session = await request(API.uploads, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      content_type: file.type || "application/octet-stream",
    }),
  });
  const chunkSize = session.chunk_size || state.uploadChunkBytes || DEFAULT_UPLOAD_CHUNK_BYTES;
  const totalChunks = session.total_chunks || Math.ceil(file.size / chunkSize);
  for (let index = 0; index < totalChunks; index += 1) {
    const start = index * chunkSize;
    const chunk = file.slice(start, Math.min(start + chunkSize, file.size));
    const chunkForm = new FormData();
    chunkForm.append("index", String(index));
    chunkForm.append("chunk", chunk, `${file.name}.part${index}`);
    setUploadStatus(`Uploading ${file.name}: ${index + 1}/${totalChunks} chunks...`);
    await request(API.uploadChunk(session.upload_id), { method: "POST", body: chunkForm });
  }
  const completeForm = new FormData();
  if (text) completeForm.append("text", text);
  completeForm.append("title", $("ingestTitle").value.trim());
  completeForm.append("date", $("ingestDate").value);
  completeForm.append("extract", $("extractAudio").checked ? "true" : "false");
  completeForm.append("on_duplicate", "new");
  setUploadStatus("Processing uploaded chunks...");
  return request(API.uploadComplete(session.upload_id), { method: "POST", body: completeForm });
}

async function reanalyzeActive() {
  if (!state.activeId) return;
  await request(API.reanalyze(state.activeId), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript: $("transcriptText").textContent }),
  });
  showToast("Reanalyzed transcript");
  await selectMeeting(state.activeId);
}

async function deleteActive() {
  if (!state.activeId) return;
  const title = state.active?.title || `meeting #${state.activeId}`;
  if (!window.confirm(`Delete ${title}?`)) return;
  await request(API.deleteMeeting(state.activeId), { method: "DELETE" });
  state.activeId = null;
  state.active = null;
  await loadBaseData();
  showToast("Meeting deleted");
}

async function deleteMeetingById(id) {
  if (!id) return;
  const meeting = state.meetings.find((m) => m.id === id);
  const title = meeting?.title || `meeting #${id}`;
  if (!window.confirm(`Delete ${title}?`)) return;
  await request(API.deleteMeeting(id), { method: "DELETE" });
  if (state.activeId === id) {
    state.activeId = null;
    state.active = null;
  }
  await loadBaseData();
  showToast("Meeting deleted");
}

async function generateDigest() {
  const digest = await request(API.digest);
  state.chat.push({
    role: "assistant",
    text: `${digest.title || "Executive Digest"}\n\n${digest.summary || ""}`,
    citations: [],
  });
  renderChat();
  showToast("Digest generated in chat");
}

async function runFollowup() {
  await request(API.followup, { method: "POST" });
  const actions = await request(API.actions);
  state.actions = actions;
  renderMemory();
  showToast("Action statuses refreshed");
}

async function updateActionStatus(id, status) {
  await request(API.action(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  state.actions = await request(API.actions);
  renderMemory();
  showToast("Action status updated");
}

async function addTerm(event) {
  event.preventDefault();
  const term = $("termInput").value.trim();
  const wrong = $("wrongInput").value.trim();
  if (!term) return;
  await request(API.glossary, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term, wrong: wrong || null }),
  });
  $("termInput").value = "";
  $("wrongInput").value = "";
  state.glossary = await request(API.glossary);
  await loadGlossarySuggestions();
  renderGlossary();
}

async function deleteTerm(id) {
  await request(API.glossaryItem(id), { method: "DELETE" });
  state.glossary = await request(API.glossary);
  await loadGlossarySuggestions();
  renderGlossary();
}

async function addSuggestedTerm(term) {
  if (!term) return;
  await request(API.glossary, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term, wrong: null }),
  });
  state.glossary = await request(API.glossary);
  await loadGlossarySuggestions();
  renderGlossary();
  showToast(`Learned ${term}`);
}

async function learnGuide(event) {
  event.preventDefault();
  const file = $("guideFile").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const out = await request(API.glossaryLearn, { method: "POST", body: form });
  state.glossary = await request(API.glossary);
  await loadGlossarySuggestions();
  renderGlossary();
  showToast(`Learned ${(out.terms || []).length} terms`);
}

function bindEvents() {
  $("newMeetingBtn").addEventListener("click", () => $("importDialog").showModal());
  $("toggleSidebarBtn").addEventListener("click", toggleSidebar);
  $("closeImportBtn").addEventListener("click", () => {
    $("importDialog").close();
    clearFilePreview();
    resetRecording();
  });
  $("cancelIngestBtn").addEventListener("click", () => {
    $("importDialog").close();
    clearFilePreview();
    resetRecording();
  });
  $("recordTabBtn").addEventListener("click", () => startRecording("tab"));
  $("recordMicBtn").addEventListener("click", () => startRecording("mic"));
  $("recordStopBtn").addEventListener("click", stopRecording);
  $("ingestForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    setIngestBusy(true);
    try {
      setBusy("Ingesting meeting...");
      await ingestMeeting();
    } catch (error) {
      setUploadStatus(error.message);
      showToast(error.message);
    } finally {
      setIngestBusy(false);
    }
  });
  $("ingestFile").addEventListener("change", () => {
    const file = $("ingestFile").files[0];
    $("ingestFileLabel").textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB` : "Optional audio/video upload";
    updateFilePreview(file);
    if (file && file.size === 0) {
      setUploadStatus("This file is empty. Choose another file.");
    } else if (file && file.size > state.maxUploadBytes) {
      setUploadStatus(`This file is larger than ${formatUploadLimit()}. Split it before upload.`);
    } else if (file && file.size > DIRECT_UPLOAD_BYTES) {
      setUploadStatus("Large file detected. Memoir will upload it in chunks.");
    } else {
      setUploadStatus("");
    }
  });
  $("librarySearch").addEventListener("input", (event) => {
    state.librarySearch = event.target.value;
    renderMeetings();
  });
  $("globalSearch").addEventListener("input", (event) => {
    state.librarySearch = event.target.value;
    $("librarySearch").value = event.target.value;
    renderMeetings();
  });
  document.querySelectorAll("[data-time-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.timeFilter = button.dataset.timeFilter;
      document.querySelectorAll("[data-time-filter]").forEach((item) => {
        item.classList.toggle("active", item.dataset.timeFilter === state.timeFilter);
      });
      renderMeetings();
    });
  });
  $("activeTitleInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.target.blur();
    }
  });
  $("activeTitleInput").addEventListener("blur", (event) => {
    updateMeetingName(state.activeId, event.target.value).catch((e) => showToast(e.message));
  });
  $("transcriptSearch").addEventListener("input", (event) => {
    state.transcriptSearch = event.target.value;
    renderTranscriptEvidence();
  });
  $("reanalyzeBtn")?.addEventListener("click", () => reanalyzeActive().catch((e) => showToast(e.message)));
  $("deleteMeetingBtn").addEventListener("click", () => deleteActive().catch((e) => showToast(e.message)));
  $("digestBtn").addEventListener("click", () => generateDigest().catch((e) => showToast(e.message)));
  $("followupBtn").addEventListener("click", () => runFollowup().catch((e) => showToast(e.message)));
  $("playerToggleBtn").addEventListener("click", () => toggleMeetingPlayback());
  $("meetingAudio").addEventListener("play", () => $("playerToggleBtn").classList.add("playing"));
  $("meetingAudio").addEventListener("pause", () => $("playerToggleBtn").classList.remove("playing"));
  $("meetingAudio").addEventListener("ended", () => $("playerToggleBtn").classList.remove("playing"));
  $("meetingAudio").addEventListener("timeupdate", (event) => {
    $("playerTime").textContent = fmtClock(event.target.currentTime);
  });
  $("meetingAudio").addEventListener("error", () => {
    $("playerToggleBtn").classList.remove("playing");
    showToast("Audio playback is not available for this meeting.");
  });
  document.addEventListener("click", (event) => {
    const meetingDelete = event.target.closest("[data-meeting-delete]");
    if (meetingDelete) {
      event.preventDefault();
      event.stopPropagation();
      deleteMeetingById(Number(meetingDelete.dataset.meetingDelete)).catch((e) => showToast(e.message));
      return;
    }
    const suggested = event.target.closest("[data-suggested-term]");
    if (suggested) {
      event.preventDefault();
      addSuggestedTerm(suggested.dataset.suggestedTerm).catch((e) => showToast(e.message));
      return;
    }
    const ts = event.target.closest("[data-ts]");
    if (ts) {
      event.preventDefault();
      seekToTimestamp(ts.dataset.ts);
      return;
    }
    const status = event.target.closest("[data-action-status]");
    if (status) {
      event.preventDefault();
      updateActionStatus(Number(status.dataset.actionId), status.dataset.actionStatus).catch((e) => showToast(e.message));
    }
  });
  document.addEventListener("keydown", (event) => {
    const input = event.target.closest("[data-meeting-title]");
    if (input && event.key === "Enter") {
      event.preventDefault();
      input.blur();
    }
  });
  document.addEventListener("blur", (event) => {
    const input = event.target.closest("[data-meeting-title]");
    if (input) {
      updateMeetingName(Number(input.dataset.meetingTitle), input.value).catch((e) => showToast(e.message));
    }
  }, true);
  $("chatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("chatInput");
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    try {
      await sendQuestion(q);
    } catch (error) {
      state.chat.push({ role: "assistant", text: error.message, citations: [] });
      renderChat();
    }
  });
  $("glossaryForm").addEventListener("submit", addTerm);
  $("guideForm").addEventListener("submit", learnGuide);
  $("toggleGlossaryBtn").addEventListener("click", () => {
    state.glossaryCollapsed = !state.glossaryCollapsed;
    renderGlossaryPanelState();
  });
  document.querySelectorAll(".tabs [data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  document.querySelector(".tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab]");
    if (button) {
      switchTab(button.dataset.tab);
    }
  });
}

async function boot() {
  bindEvents();
  renderSuggestions();
  renderAll();
  try {
    await loadBaseData();
  } catch (error) {
    state.chat.push({ role: "assistant", text: `Cannot reach API: ${error.message}`, citations: [] });
    renderChat();
    showToast("API unavailable");
  }
}

boot();
