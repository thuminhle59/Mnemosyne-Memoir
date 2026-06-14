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
  ask: apiUrl("/api/ask"),
  ingest: apiUrl("/api/ingest"),
  actions: apiUrl("/api/actions"),
  contradictions: apiUrl("/api/contradictions"),
  resurfaced: apiUrl("/api/resurfaced"),
  digest: apiUrl("/api/digest"),
  followup: apiUrl("/api/followup"),
  scanForgotten: apiUrl("/api/scan_forgotten"),
  reanalyze: (id) => apiUrl(`/api/meetings/${id}/reanalyze`),
  deleteMeeting: (id) => apiUrl(`/api/meetings/${id}`),
  glossary: apiUrl("/api/glossary"),
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
  }[window.location.hash] || window.__MNEMOSYNE_TAB || "memory";
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
  maxUploadBytes: MAX_UPLOAD_BYTES,
  uploadChunkBytes: DEFAULT_UPLOAD_CHUNK_BYTES,
  tab: currentTabFromLocation(),
  librarySearch: "",
  transcriptSearch: "",
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

function fmtDate(value) {
  return value || "no date";
}

function fmtDuration(seconds) {
  if (!seconds) return "transcript";
  const mm = Math.floor(seconds / 60);
  const ss = String(seconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function listHtml(items, render) {
  if (!items || !items.length) return '<li class="empty">No items yet</li>';
  return items.map(render).join("");
}

function renderStats() {
  $("meetingCount").textContent = state.stats.meetings ?? state.meetings.length;
  $("termCount").textContent = `${state.glossary.length} terms`;
}

function renderMeetings() {
  const q = state.librarySearch.trim().toLowerCase();
  const meetings = state.meetings.filter((m) => {
    const text = `${m.title || ""} ${m.summary || ""} ${m.date || ""}`.toLowerCase();
    return !q || text.includes(q);
  });
  $("meetingList").innerHTML = meetings.length ? meetings.map((m) => `
    <div class="meeting-card ${m.id === state.activeId ? "active" : ""}" data-meeting-id="${m.id}">
      <div class="card-meta"><span class="status-dot"></span><span>${fmtDate(m.date)}</span><span style="margin-left:auto">${fmtDuration(m.duration_sec)}</span></div>
      <h3>${escapeHtml(m.title || `Meeting #${m.id}`)}</h3>
      <p>${escapeHtml(m.summary || m.source_file || "No summary yet")}</p>
    </div>
  `).join("") : '<div class="meeting-card"><h3>No memory sources</h3><p>Use New meeting to ingest one.</p></div>';

  document.querySelectorAll("[data-meeting-id]").forEach((el) => {
    el.addEventListener("click", () => selectMeeting(Number(el.dataset.meetingId)));
  });
}

function renderActive() {
  const m = state.active;
  $("activeMeta").textContent = m ? `${fmtDate(m.date)} · ${fmtDuration(m.duration_sec)} · #${m.id}` : "No meeting selected";
  $("activeTitle").textContent = m ? (m.title || `Meeting #${m.id}`) : "Memoir";
  $("activeSummary").textContent = m ? (m.summary || "No summary yet.") : "Load meetings or ingest a transcript to start building a cross-meeting decision memory layer.";
  $("transcriptText").value = m ? (m.transcript || "") : "";
  renderDigest();
  renderMemory();
}

function renderDigest() {
  const m = state.active || {};
  $("keyPoints").innerHTML = listHtml(m.key_points, (x) => `<li>${escapeHtml(x)}</li>`);
  $("decisions").innerHTML = listHtml(m.decisions, (d) => `<li>${escapeHtml(d.text)}${d.timestamp ? ` <code>${escapeHtml(d.timestamp)}</code>` : ""}</li>`);
  $("meetingActions").innerHTML = listHtml(m.action_items, (a) => `<li>${escapeHtml(a.task)}${a.owner ? ` · ${escapeHtml(a.owner)}` : ""}${a.deadline ? ` · ${escapeHtml(a.deadline)}` : ""}</li>`);
  $("risks").innerHTML = listHtml(m.risks, (x) => `<li>${escapeHtml(x)}</li>`);
}

function renderMemory() {
  const m = state.active || {};
  const allFacts = m.facts || [];
  const decisions = allFacts.filter((f) => f.type === "quyết định" || f.type === "cam kết");
  const openActions = state.actions.filter((a) => a.status !== "xong");
  $("decisionDriftCount").textContent = state.contradictions.length + state.resurfaced.length;
  $("contradictionCount").textContent = state.contradictions.length;
  $("openActionCount").textContent = openActions.length;
  $("decisionThreads").innerHTML = listHtml(decisions, (f) => `
    <li><b>${escapeHtml(f.subject)}</b><br><span>${escapeHtml(f.statement)}</span> <small>${escapeHtml(f.status)}</small></li>
  `);
  $("contradictionList").innerHTML = listHtml(state.contradictions, (c) => `
    <li><b>[${escapeHtml(c.severity)}] ${escapeHtml(c.subject)}</b><br><span>${escapeHtml(c.explanation)}</span></li>
  `);
  $("resurfacedList").innerHTML = listHtml(state.resurfaced, (r) => `
    <li><b>${escapeHtml(r.subject)}</b><br><span>${escapeHtml(r.explanation)}</span> <small>${escapeHtml(r.kind || "")}</small></li>
  `);
  $("facts").innerHTML = listHtml(allFacts, (f) => `
    <li><b>${escapeHtml(f.subject)}</b>: ${escapeHtml(f.statement)} <small>${escapeHtml(f.type)} · ${escapeHtml(f.status)}</small></li>
  `);
  $("allActions").innerHTML = listHtml(openActions, (a) => `
    <li><b>${escapeHtml(a.task)}</b><br><small>${escapeHtml(a.owner || "Unassigned")} · ${escapeHtml(a.deadline || "no deadline")} · ${escapeHtml(a.status || "mở")}</small></li>
  `);
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
  renderStats();
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
  ["transcript", "digest", "memory"].forEach((key) => {
    document.querySelector(`[data-tab="${key}"]`)?.classList.toggle("active", state.tab === key);
    $(`${key}View`)?.classList.toggle("active", state.tab === key);
  });
}

function switchTab(tab) {
  if (!["transcript", "digest", "memory"].includes(tab)) return;
  window.__MNEMOSYNE_TAB = tab;
  state.tab = tab;
  renderTabs();
}

window.switchTab = switchTab;

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
  if (rerender) renderAll();
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

async function ingestMeeting() {
  const form = new FormData();
  const file = $("ingestFile").files[0];
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
    body: JSON.stringify({ transcript: $("transcriptText").value }),
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
  renderGlossary();
}

async function deleteTerm(id) {
  await request(API.glossaryItem(id), { method: "DELETE" });
  state.glossary = await request(API.glossary);
  renderGlossary();
}

async function learnGuide(event) {
  event.preventDefault();
  const file = $("guideFile").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const out = await request(API.glossaryLearn, { method: "POST", body: form });
  state.glossary = await request(API.glossary);
  renderGlossary();
  showToast(`Learned ${(out.terms || []).length} terms`);
}

function bindEvents() {
  $("newMeetingBtn").addEventListener("click", () => $("importDialog").showModal());
  $("closeImportBtn").addEventListener("click", () => $("importDialog").close());
  $("cancelIngestBtn").addEventListener("click", () => $("importDialog").close());
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
  $("transcriptSearch").addEventListener("input", (event) => {
    state.transcriptSearch = event.target.value;
    const txt = $("transcriptText");
    const q = state.transcriptSearch;
    if (q) {
      const idx = txt.value.toLowerCase().indexOf(q.toLowerCase());
      if (idx >= 0) {
        txt.focus();
        txt.setSelectionRange(idx, idx + q.length);
      }
    }
  });
  $("reanalyzeBtn").addEventListener("click", () => reanalyzeActive().catch((e) => showToast(e.message)));
  $("deleteMeetingBtn").addEventListener("click", () => deleteActive().catch((e) => showToast(e.message)));
  $("digestBtn").addEventListener("click", () => generateDigest().catch((e) => showToast(e.message)));
  $("followupBtn").addEventListener("click", () => runFollowup().catch((e) => showToast(e.message)));
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
    $("glossaryPanel").hidden = !$("glossaryPanel").hidden;
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
