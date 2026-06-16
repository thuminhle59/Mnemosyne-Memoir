const FILE_PROTOCOL_REDIRECTED = window.location.protocol === "file:";
if (FILE_PROTOCOL_REDIRECTED) {
  window.location.replace("http://127.0.0.1:8080/");
}

const API_ORIGIN = window.location.protocol === "file:" ? "http://127.0.0.1:8080" : "";
const apiUrl = (path) => `${API_ORIGIN}${path}`;
const OWNER_STORAGE_KEY = "memoir_owner_id";

function getOwnerId() {
  try {
    const existing = window.localStorage.getItem(OWNER_STORAGE_KEY);
    if (existing) return existing;
    const generated = window.crypto.randomUUID();
    window.localStorage.setItem(OWNER_STORAGE_KEY, generated);
    return generated;
  } catch (_) {
    return "browser-session-owner";
  }
}

function withOwnerHeader(options = {}) {
  return {
    ...options,
    headers: {
      ...(options.headers || {}),
      "X-Memoir-Owner": getOwnerId(),
    },
  };
}

const API = {
  health: apiUrl("/api/health"),
  config: apiUrl("/api/config"),
  uploads: apiUrl("/api/uploads"),
  uploadChunk: (id) => apiUrl(`/api/uploads/${id}/chunks`),
  uploadComplete: (id) => apiUrl(`/api/uploads/${id}/complete`),
  ingestProgress: (id) => apiUrl(`/api/ingest/progress/${id}`),
  stats: apiUrl("/api/stats"),
  meetings: apiUrl("/api/meetings"),
  meeting: (id) => apiUrl(`/api/meetings/${id}`),
  audio: (id) => apiUrl(`/api/meetings/${id}/audio`),
  report: (id, fmt) => apiUrl(`/api/meetings/${id}/report.${fmt}`),
  updateMeeting: (id) => apiUrl(`/api/meetings/${id}`),
  renameGroup: apiUrl("/api/meeting_groups"),
  ask: apiUrl("/api/ask"),
  ingest: apiUrl("/api/ingest"),
  actions: apiUrl("/api/actions"),
  action: (id) => apiUrl(`/api/actions/${id}`),
  assignAction: (id) => apiUrl(`/api/actions/${id}/assign`),
  contradictions: apiUrl("/api/contradictions"),
  resurfaced: apiUrl("/api/resurfaced"),
  digest: apiUrl("/api/digest"),
  followup: apiUrl("/api/followup"),
  scanForgotten: apiUrl("/api/scan_forgotten"),
  reanalyze: (id) => apiUrl(`/api/meetings/${id}/reanalyze`),
  applyGlossary: (id) => apiUrl(`/api/meetings/${id}/apply_glossary`),
  deleteMeeting: (id) => apiUrl(`/api/meetings/${id}`),
  glossary: apiUrl("/api/glossary"),
  glossarySuggestions: (id) => apiUrl(`/api/glossary/suggestions?meeting_id=${id}`),
  glossaryLearn: apiUrl("/api/glossary/learn"),
  glossaryItem: (id) => apiUrl(`/api/glossary/${id}`),
};

function readBootstrapData() {
  const node = document.getElementById("memoirBootstrap");
  if (!node?.textContent) return window.__MEMOIR_BOOTSTRAP__ || null;
  try {
    return JSON.parse(node.textContent);
  } catch (_) {
    return window.__MEMOIR_BOOTSTRAP__ || null;
  }
}

const BOOTSTRAP_DATA = readBootstrapData();

const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
const DEFAULT_UPLOAD_CHUNK_BYTES = 16 * 1024 * 1024;
const CHUNK_UPLOAD_CONCURRENCY = 3;
const INGEST_WARNING = "For fastest ingest, upload audio or paste transcript. Video may take several minutes. Please keep this window open";

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
  digest: null,
  glossary: [],
  glossarySuggestions: [],
  maxUploadBytes: MAX_UPLOAD_BYTES,
  uploadChunkBytes: DEFAULT_UPLOAD_CHUNK_BYTES,
  tab: currentTabFromLocation(),
  librarySearch: "",
  timeFilter: "all",
  sidebarCollapsed: false,
  glossaryCollapsed: true,
  glossaryEditing: false,
  glossaryDraft: [],
  glossaryFilter: "",
  evidenceTypeFilter: [],
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
      text: "Mình đã đọc xong transcript cuộc họp này. Hỏi bất cứ điều gì",
      citations: [],
    },
  ],
};

const $ = (id) => document.getElementById(id);
let meetingTitleClickTimer = null;

function parseJsonText(text) {
  if (!text) return null;
  return JSON.parse(text);
}

function requestWithXhr(url, options = {}) {
  return new Promise((resolve, reject) => {
    if (typeof window.XMLHttpRequest !== "function") {
      reject(new Error("Browser does not expose fetch or XMLHttpRequest"));
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open(options.method || "GET", url, true);
    Object.entries(options.headers || {}).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    if (typeof options.onUploadProgress === "function" && xhr.upload) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) {
          options.onUploadProgress(event.loaded, event.total, event);
        }
      };
    }
    if (options.signal) {
      if (options.signal.aborted) {
        xhr.abort();
        reject(new DOMException("The operation was aborted.", "AbortError"));
        return;
      }
      options.signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.onload = () => {
      const response = {
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        statusText: xhr.statusText,
        json: async () => parseJsonText(xhr.responseText),
      };
      resolve(response);
    };
    xhr.onerror = () => reject(new Error("Network request failed"));
    xhr.onabort = () => reject(new DOMException("The operation was aborted.", "AbortError"));
    xhr.send(options.body || null);
  });
}

async function request(url, options = {}) {
  let res;
  const requestOptions = withOwnerHeader(options);
  try {
    const needsUploadProgress = typeof requestOptions.onUploadProgress === "function";
    res = typeof window.fetch === "function" && !needsUploadProgress
      ? await window.fetch(url, requestOptions)
      : await requestWithXhr(url, requestOptions);
  } catch (error) {
    if (error?.name === "AbortError") throw error;
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

function bootstrapMeetingDetail(id) {
  return BOOTSTRAP_DATA?.meeting_details?.[String(id)] || null;
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

function setUploadProgress(percent, label, detail, variant = "") {
  if (variant === "error") {
    if ($("ingestProgress")?.hidden) showIngestProgress();
    setIngestPercent(percent, "error");
    setUploadStatus(detail || label || "Upload interrupted.");
    return;
  }
  setIngestPercent(percent);
  if (detail || label) setUploadStatus(detail || label);
}

function setFileIngestProgress(percent, variant = "") {
  setIngestPercent(percent, variant);
}

function showIngestProgress() {
  const box = $("ingestProgress");
  if (!box) return;
  box.hidden = false;
  box.classList.remove("error");
}

function setIngestPercent(percent, variant = "") {
  const box = $("ingestProgress");
  if (!box) return;
  showIngestProgress();
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  box.classList.toggle("error", variant === "error");
  const label = $("ingestProgressPercent");
  const fill = $("ingestProgressFill");
  if (label) label.textContent = `${value}%`;
  if (fill) fill.style.width = `${value}%`;
}

function makeClientJobId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `job-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function progressStatusText(progress) {
  if (hasSelectedIngestFile()) return INGEST_WARNING;
  if (progress?.detail) return progress.detail;
  return {
    queued: "Đang chuẩn bị ingest.",
    uploading: "Đang tải file lên.",
    assembling: "Đang ghép file upload.",
    validating: "Đang kiểm tra file ingest.",
    ingesting: INGEST_WARNING,
    saving: "Đang lưu kết quả.",
    done: "Hoàn tất ingest.",
    error: "Ingest bị lỗi.",
  }[progress?.stage] || "Đang ingest file.";
}

function pollBackendIngestProgress(jobId, floor = 0) {
  let stopped = false;
  let timer = null;
  const tick = async () => {
    if (stopped || !jobId) return;
    try {
      const progress = await request(API.ingestProgress(jobId));
      const percent = progress.status === "error" ? (progress.percent || 0) : Math.max(floor, progress.percent || 0);
      setIngestPercent(percent, progress.status === "error" ? "error" : "");
      setUploadStatus(progressStatusText(progress));
      if (progress.status === "done" || progress.status === "error") return;
    } catch (_) {
      // The request may reach the server before the ingest handler creates the job.
    }
    if (!stopped) timer = window.setTimeout(tick, 800);
  };
  timer = window.setTimeout(tick, 250);
  return () => {
    stopped = true;
    if (timer) window.clearTimeout(timer);
  };
}

function resetUploadProgress() {
  setUploadStatus("");
  const box = $("ingestProgress");
  if (box) {
    box.hidden = true;
    box.classList.remove("error");
    const label = $("ingestProgressPercent");
    const fill = $("ingestProgressFill");
    if (label) label.textContent = "0%";
    if (fill) fill.style.width = "0%";
  }
}

function hasSelectedIngestFile() {
  const mode = $("ingestMode").value;
  if (mode === "recording") return Boolean(state.recordedFile);
  if (mode === "upload") return Boolean($("ingestFile").files[0]);
  return false;
}

function setIngestBusy(isBusy) {
  const submit = $("ingestSubmitBtn");
  const cancel = $("cancelIngestBtn");
  const close = $("closeImportBtn");
  if (submit) {
    submit.disabled = isBusy;
    submit.textContent = isBusy ? "Đang xử lý..." : "Ingest";
  }
  // Keep Cancel clickable while busy so the user can abort the in-flight ingest.
  if (cancel) {
    cancel.disabled = false;
    cancel.textContent = isBusy ? "Hủy ingest" : "Cancel";
  }
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

function clearSelectedUploadFile() {
  const input = $("ingestFile");
  if (input) input.value = "";
  const label = $("ingestFileLabel");
  if (label) label.textContent = "No file selected";
  clearFilePreview();
}

function setIngestMode(mode) {
  document.querySelectorAll("[data-ingest-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.ingestPanel !== mode;
  });
  setUploadStatus("");
  resetUploadProgress();
  if (mode !== "transcript") $("ingestText").value = "";
  if (mode !== "upload") clearSelectedUploadFile();
  if (mode !== "recording") resetRecording();
  if (mode === "recording") refreshRecordingSupport();
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

function stripExtension(value = "") {
  return value.replace(/\.[a-z0-9]{2,5}$/i, "");
}

function deriveMeetingGroup(meeting = {}) {
  if (meeting.group_title) return meeting.group_title;
  const base = stripExtension(meeting.title || meeting.source_file || "").trim();
  if (!base) return "Ungrouped";
  const split = base.split(/\s[-–—]\s|\/|:|\|/).map((part) => part.trim()).filter(Boolean);
  if (split.length > 1) return split[0];
  const cleaned = base.replace(/^\d{4}[-_]\d{2}[-_]\d{2}[\s_-]*/i, "").trim();
  return cleaned || base;
}

function groupMeetingsForSidebar(meetings) {
  const groups = new Map();
  meetings.forEach((meeting) => {
    const group = meeting.group_title || deriveMeetingGroup(meeting);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(meeting);
  });
  return [...groups.entries()];
}

function formatDateTimeSeconds(value) {
  if (!value) return "no date";
  const raw = String(value);
  const simple = raw.match(/^(\d{4}-\d{2}-\d{2})$/);
  if (simple) return `${simple[1]} 00:00:00`;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return fmtDate(raw);
  const yyyy = parsed.getFullYear();
  const mm = String(parsed.getMonth() + 1).padStart(2, "0");
  const dd = String(parsed.getDate()).padStart(2, "0");
  const hh = String(parsed.getHours()).padStart(2, "0");
  const mi = String(parsed.getMinutes()).padStart(2, "0");
  const ss = String(parsed.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}

function formatLocalDateTimeInput(date = new Date()) {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}`;
}

function meetingDateTime(meeting = {}) {
  const raw = meeting.date || meeting.created_at || "";
  return formatDateTimeSeconds(raw);
}

function meetingDurationLabel(meeting = {}) {
  return meeting.duration_sec ? fmtDuration(meeting.duration_sec) : "transcript";
}

function enableMeetingTitleEdit(input) {
  input.removeAttribute("readonly");
  input.classList.add("editing");
  input.focus();
  input.select();
}

function disableMeetingTitleEdit(input) {
  input.setAttribute("readonly", "");
  input.classList.remove("editing");
}

async function finishMeetingTitleEdit(input) {
  if (!input || input.hasAttribute("readonly")) return;
  disableMeetingTitleEdit(input);
  await updateMeetingName(Number(input.dataset.meetingTitle), input.value);
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

function renderLine(text, timestamp, detail = "", detailHtml = "") {
  return `
    <li class="line-item">
      <p>${escapeHtml(text)}</p>
      <div class="line-meta">${timestampButton(timestamp)}${detailHtml || (detail ? `<span>${escapeHtml(detail)}</span>` : "")}</div>
    </li>
  `;
}

function severityKey(severity = "") {
  const value = String(severity).toLowerCase();
  if (value.includes("cao") || value.includes("high")) return "high";
  if (value.includes("thấp") || value.includes("low")) return "low";
  return "medium";
}

function severityBadge(severity = "") {
  const label = severity || "trung bình";
  return `<span class="severity-badge severity-${severityKey(label)}">${escapeHtml(label)}</span>`;
}

function meetingDisplayId(meeting) {
  return meeting?.display_id || meeting?.id || "";
}

function meetingDisplayIdById(id) {
  const meeting = state.meetings.find((m) => Number(m.id) === Number(id));
  return meetingDisplayId(meeting) || id;
}

// Cited evidence shows "Họp #N" linking back to the source meeting, using the
// owner-scoped display number while keeping the database id for navigation.
function meetingNumberLabel(citation) {
  const id = citation?.meeting_id;
  if (!id) return "";
  const meeting = state.meetings.find((m) => Number(m.id) === Number(id));
  const title = citation.meeting_title || meeting?.title || "";
  return `#${meetingDisplayId(meeting) || id}${title ? ` · ${title}` : ""}`;
}

function citationChip(citation) {
  if (!citation?.meeting_id) return "";
  return `<button type="button" class="cite-chip" data-cite-meeting="${citation.meeting_id}" title="Mở cuộc họp">📍 Họp ${escapeHtml(meetingNumberLabel(citation))}</button>`;
}

function contradictionCites(c) {
  const oldChip = citationChip(c.old);
  const newChip = citationChip(c.new);
  if (!oldChip && !newChip) return "";
  const arrow = oldChip && newChip ? `<span class="cite-arrow">→</span>` : "";
  return `<span class="cite-row">${oldChip}${arrow}${newChip}</span>`;
}

function meetingInlineRef(citation) {
  return citation?.meeting_id ? `(meeting #${meetingDisplayIdById(citation.meeting_id)})` : "";
}

function contradictionText(c) {
  const subject = c.subject ? `${c.subject}: ` : "";
  const oldStatement = c.old?.statement || c.old?.quote || "";
  const newStatement = c.new?.statement || c.new?.quote || "";
  if (oldStatement && newStatement) {
    return `${subject}Đã thay đổi từ ${oldStatement} ${meetingInlineRef(c.old)} sang ${newStatement} ${meetingInlineRef(c.new)}`.replace(/\s+/g, " ").trim();
  }
  if (newStatement) {
    return `${subject}Hiện tại ghi nhận ${newStatement} ${meetingInlineRef(c.new)}`.replace(/\s+/g, " ").trim();
  }
  return `${subject}${c.explanation || "Có sự không nhất quán giữa các meeting."}`;
}

function renderStats() {
  $("meetingCount").textContent = state.stats.meetings ?? state.meetings.length;
  $("termCount").textContent = `${state.glossary.length} terms`;
}

function resizeGroupTitleInput(input) {
  if (!input) return;
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
}

function resizeGroupTitleInputs() {
  document.querySelectorAll("[data-group-title-input]").forEach(resizeGroupTitleInput);
}

function renderMeetings() {
  const q = state.librarySearch.trim().toLowerCase();
  const meetings = state.meetings.filter((m) => {
    const text = `${m.title || ""} ${m.summary || ""} ${m.date || ""} ${m.source_file || ""} ${deriveMeetingGroup(m)}`.toLowerCase();
    return (!q || text.includes(q)) && meetingMatchesTimeFilter(m);
  });
  const groups = groupMeetingsForSidebar(meetings);
  $("meetingList").innerHTML = groups.length ? groups.map(([group, groupMeetings]) => `
    <section class="group-folder" data-group-title="${escapeHtml(group)}">
      <div class="group-title" aria-label="${escapeHtml(group)} folder" data-group-name="${escapeHtml(group)}">
        <textarea class="group-title-input" rows="1" readonly data-group-title-input="${escapeHtml(group)}" aria-label="Double-click to rename group">${escapeHtml(group)}</textarea>
      </div>
      <div class="group-body">
        ${groupMeetings.map((m) => `
          <div class="meeting-card group-meeting ${m.id === state.activeId ? "active" : ""}" data-meeting-id="${m.id}" draggable="true">
            <div class="meeting-compact-title">
              <span class="status-dot ${m.can_play_audio ? "ready" : ""}"></span>
              <span class="meeting-num">#${meetingDisplayId(m)}</span>
              <textarea class="meeting-title-input" rows="2" readonly data-meeting-title="${m.id}" aria-label="Double-click to rename meeting">${escapeHtml(m.title || `Meeting #${meetingDisplayId(m)}`)}</textarea>
              <button class="meeting-delete" type="button" data-meeting-delete="${m.id}" aria-label="Delete meeting">x</button>
            </div>
            <div class="meeting-compact-meta"><span>${escapeHtml(meetingDateTime(m))}</span><span>${escapeHtml(meetingDurationLabel(m))}</span></div>
          </div>
        `).join("")}
      </div>
    </section>
  `).join("") : '<div class="meeting-card empty"><h3>No memory sources</h3><p>Use New meeting to ingest one.</p></div>';
  resizeGroupTitleInputs();

  document.querySelectorAll("[data-meeting-id]").forEach((el) => {
    el.addEventListener("click", (event) => {
      if (shouldIgnoreMeetingCardClick(event.target)) return;
      const readonlyTitle = event.target.closest("[data-meeting-title][readonly]");
      if (readonlyTitle) {
        scheduleMeetingTitleSelection(Number(el.dataset.meetingId));
        return;
      }
      selectMeeting(Number(el.dataset.meetingId));
    });
    el.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData("text/plain", el.dataset.meetingId);
      event.dataTransfer?.setData("application/x-meeting-id", el.dataset.meetingId);
      event.dataTransfer.effectAllowed = "move";
    });
  });
  document.querySelectorAll("[data-group-title]").forEach((folder) => {
    folder.addEventListener("dragover", (event) => {
      event.preventDefault();
      folder.classList.add("drag-over");
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    });
    folder.addEventListener("dragleave", () => folder.classList.remove("drag-over"));
    folder.addEventListener("drop", (event) => {
      event.preventDefault();
      folder.classList.remove("drag-over");
      const id = Number(event.dataTransfer?.getData("application/x-meeting-id") || event.dataTransfer?.getData("text/plain"));
      const group = folder.dataset.groupTitle || "";
      if (id && group) updateMeetingGroup(id, group).catch((e) => showToast(e.message));
    });
  });
  document.querySelectorAll("[data-group-title-input]").forEach((input) => {
    input.addEventListener("dblclick", (event) => {
      event.preventDefault();
      input.removeAttribute("readonly");
      input.focus();
      resizeGroupTitleInput(input);
      input.select();
    });
    input.addEventListener("input", () => resizeGroupTitleInput(input));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !input.hasAttribute("readonly")) {
        event.preventDefault();
        input.blur();
      }
    });
    input.addEventListener("blur", () => {
      if (input.hasAttribute("readonly")) return;
      const oldGroupTitle = input.dataset.groupTitleInput || "";
      const newGroupTitle = input.value;
      input.setAttribute("readonly", "");
      renameMeetingGroup(oldGroupTitle, newGroupTitle).catch((e) => showToast(e.message));
    });
  });
}

function scheduleMeetingTitleSelection(id) {
  if (meetingTitleClickTimer) window.clearTimeout(meetingTitleClickTimer);
  meetingTitleClickTimer = window.setTimeout(() => selectMeeting(id), 220);
}

function shouldIgnoreMeetingCardClick(target) {
  if (target.closest("button, input")) return true;
  return Boolean(target.closest("[data-meeting-title]:not([readonly])"));
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
  $("activeMeta").textContent = m ? `${formatDateTimeSeconds(m.date)} · ${fmtDuration(m.duration_sec)} · #${meetingDisplayId(m)}` : "No meeting selected";
  $("activeTitleInput").value = m ? (m.title || `Meeting #${meetingDisplayId(m)}`) : "Memoir";
  $("activeTitleInput").disabled = !m;
  $("exportBtn").disabled = !m;
  if (!m) closeExportMenu();
  resizeActiveTitle();
  renderExecutiveSummary(m);
  renderMeetingPlayer();
  renderDigest();
  renderMemory();
  renderEvidence();
}

function resizeActiveTitle() {
  $("activeTitleInput").style.height = "auto";
  $("activeTitleInput").style.height = `${$("activeTitleInput").scrollHeight}px`;
}

function fallbackSummaryLines(text = "") {
  return String(text)
    .replace(/\s+/g, " ")
    .split(/(?<=[.!?。])\s+|[;•]\s+|\n+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .slice(0, 3);
}

function summaryBriefLines(brief) {
  return [
    brief?.context,
    ...(brief?.decisions || []).slice(0, 2),
    brief?.risk,
    brief?.next_step,
  ]
    .map((line) => String(line || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function renderStructuredSummaryBrief(box, brief) {
  const lines = summaryBriefLines(brief);
  if (!lines.length) return false;
  const html = lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("");
  box.insertAdjacentHTML("beforeend", html);
  return true;
}

function renderFallbackSummary(box, meeting) {
  const rawSummary = meeting?.summary || "No executive summary yet.";
  fallbackSummaryLines(rawSummary).forEach((sentence) => {
    box.insertAdjacentHTML("beforeend", `<p>${escapeHtml(sentence)}</p>`);
  });
}

function renderExecutiveSummary(meeting) {
  const box = $("activeSummary");
  const label = meeting ? "Meeting summary" : "Summary";
  box.innerHTML = `<span class="summary-label">${escapeHtml(label)}</span>`;
  if (!meeting) {
    box.insertAdjacentHTML("beforeend", "<p>Load meetings or ingest a transcript to start building a cross-meeting decision memory layer.</p>");
    return;
  }
  if (!renderStructuredSummaryBrief(box, meeting.summary_brief)) {
    renderFallbackSummary(box, meeting);
  }
}

function renderMeetingPlayer() {
  const m = state.active;
  const audio = $("meetingAudio");
  const button = $("playerToggleBtn");
  const time = $("playerTime");
  const canPlay = Boolean(m?.id && m.can_play_audio);
  audio.pause();
  button.classList.remove("playing");
  time.textContent = "00:00";
  updatePlayerProgress(0, 0);
  if (!canPlay) {
    audio.removeAttribute("src");
    audio.load();
    button.disabled = true;
    return;
  }
  audio.src = API.audio(m.id);
  button.disabled = false;
}

function updatePlayerProgress(current, duration) {
  const percent = duration > 0 ? Math.max(0, Math.min(100, (current / duration) * 100)) : 0;
  $("playerProgressFill").style.width = `${percent}%`;
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
  const currentContradictions = activeContradictions();
  const currentResurfaced = activeResurfaced();
  const decisionRows = (m.decisions || []).map((d) => ({ text: d.text, timestamp: d.timestamp }));
  const contradictionRows = [
    ...currentContradictions.map((c) => ({
      text: contradictionText(c),
      timestamp: c.new?.timestamp || c.old?.timestamp,
      severity: c.severity,
      cites: contradictionCites(c),
    })),
    ...currentResurfaced.map((r) => ({
      text: `${r.subject}: ${r.explanation}`,
      timestamp: r.new?.timestamp || r.old?.timestamp,
      detail: r.kind || "Forgotten decision",
      cites: contradictionCites(r),
    })),
  ];
  $("decisions").innerHTML = listHtml(decisionRows, (d) => renderLine(d.text, d.timestamp));
  $("contradictionsForgotten").innerHTML = listHtml(contradictionRows, (r) => renderLine(r.text, r.timestamp, r.detail, `${r.severity ? severityBadge(r.severity) : ""}${r.cites || ""}`));
  $("risks").innerHTML = listHtml(m.risks, (x) => renderLine(x));
}

function actionsForActiveMeeting() {
  if (!state.activeId) return [];
  return state.actions.filter((a) => Number(a.meeting_id) === Number(state.activeId));
}

function renderMemory() {
  const activeActions = actionsForActiveMeeting();
  const openActions = activeActions.filter((a) => a.status !== "xong");
  const currentContradictions = activeContradictions();
  const currentResurfaced = activeResurfaced();
  $("decisionDriftCount").textContent = currentContradictions.length + currentResurfaced.length;
  $("contradictionCount").textContent = currentContradictions.length;
  $("openActionCount").textContent = openActions.length;
  const actions = importantActions(activeActions);
  $("allActions").innerHTML = listHtml(actions, (item) => {
    const owner = item.owner && item.owner !== "Unassigned" ? item.owner : "";
    return `
      <li class="${statusKey(item.status) === "completed" ? "action-completed" : ""}">
        <label class="action-check-row">
          ${renderActionCheckbox(item)}
          <span>
            <b>${escapeHtml(item.task)}</b>
            <span class="line-meta">
              ${timestampButton(item.timestamp)}
              <span>${escapeHtml(actionMetaText(item))}</span>
              <button type="button" class="assign-toggle icon-assign-toggle" data-assign-toggle data-action-id="${item.id}" aria-label="Assign owner">
                <img src="./assets/add-user.png?v=20260616" alt="" aria-hidden="true">
              </button>
            </span>
          </span>
        </label>
        <div class="assign-form" data-assign-form data-action-id="${item.id}" hidden>
          <input class="assign-owner" data-assign-owner type="text" placeholder="Người phụ trách" value="${escapeHtml(owner)}">
          <button type="button" class="assign-send" data-assign-owner-save data-action-id="${item.id}">Assign</button>
          <input class="assign-email" data-assign-email type="email" placeholder="email">
          <button type="button" class="assign-send" data-assign-send data-action-id="${item.id}">Send</button>
        </div>
      </li>
    `;
  });
}

function importantActions(actions) {
  const importantKeywords = [
    "deadline", "submit", "deploy", "build", "review", "budget", "ngân sách",
    "voting", "vote", "github", "docker", "security", "bảo mật", "password",
    "mật khẩu", "otp", "timeline", "release", "launch", "blocker", "risk",
  ];
  const lowSignalPatterns = [/user guide/i, /join group/i, /tham gia nhóm/i, /qr/i, /liên hệ hỗ trợ/i];
  const scored = actions.map((action) => {
    const text = `${action.task || ""} ${action.quote || ""}`.toLowerCase();
    const lowSignal = lowSignalPatterns.some((pattern) => pattern.test(text));
    const keywordScore = importantKeywords.filter((keyword) => text.includes(keyword)).length;
    const metadataScore = [action.deadline, action.owner && action.owner !== "Unassigned", action.timestamp].filter(Boolean).length;
    return { action, score: keywordScore * 3 + metadataScore - (lowSignal ? 3 : 0) };
  });
  const important = scored.filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  const deduped = dedupeActionsByIntent(important).map((item) => item.action);
  return deduped.length ? deduped.slice(0, 8) : dedupeActionsByIntent(actions.map((action) => ({ action, score: 0 }))).map((item) => item.action).slice(0, 8);
}

function actionMetaText(action) {
  const owner = action.owner && action.owner !== "Unassigned" ? action.owner : "";
  const deadline = action.deadline || "no deadline";
  return owner ? `${owner} · ${deadline}` : deadline;
}

function dedupeActionsByIntent(scoredActions) {
  const byIntent = new Map();
  scoredActions.forEach((item, index) => {
    const key = actionIntentKey(item.action);
    const existing = byIntent.get(key);
    if (!existing || item.score > existing.score) byIntent.set(key, { ...item, index });
  });
  return [...byIntent.values()].sort((a, b) => b.score - a.score || a.index - b.index);
}

function actionIntentKey(action) {
  const text = `${action.task || ""} ${action.quote || ""}`.toLowerCase();
  if (text.includes("password") || text.includes("mật khẩu")) return "account-password";
  return text
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(" ")
    .filter((word) => word.length > 2 && !["ngay", "khi", "sau", "lap", "tuc", "lan", "dau"].includes(word))
    .slice(0, 8)
    .join(" ");
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

function renderActionCheckbox(action) {
  return `
    <input class="action-check-input" type="checkbox" data-action-toggle data-action-id="${action.id}" ${statusKey(action.status) === "completed" ? "checked" : ""}>
  `;
}

function citationMatchesActiveMeeting(citation) {
  return Boolean(state.activeId && Number(citation?.meeting_id) === Number(state.activeId));
}

function activeContradictions() {
  return state.contradictions.filter((item) => citationMatchesActiveMeeting(item.old) || citationMatchesActiveMeeting(item.new));
}

function activeResurfaced() {
  return state.resurfaced.filter((item) => citationMatchesActiveMeeting(item.old) || citationMatchesActiveMeeting(item.new));
}

function collectEvidenceMentions() {
  const m = state.active || {};
  const mentions = [];
  const add = (quote, timestamp, label, meetingId = null) => {
    if (!quote || !timestamp) return;
    const cite = meetingId ? `${label} · Họp #${meetingId}` : label;
    mentions.push({ quote: String(quote), timestamp, label: cite });
  };
  (m.decisions || []).forEach((d) => add(d.quote || d.text, d.timestamp, "Decision"));
  (m.action_items || []).forEach((a) => add(a.quote || a.task, a.timestamp, "Action"));
  (m.facts || []).forEach((f) => add(f.quote || f.statement, f.timestamp, f.type));
  activeContradictions().forEach((c) => {
    add(c.new?.quote, c.new?.timestamp, "Contradiction", c.new?.meeting_id);
    add(c.old?.quote, c.old?.timestamp, "Contradiction", c.old?.meeting_id);
  });
  activeResurfaced().forEach((r) => {
    add(r.new?.quote, r.new?.timestamp, "Forgotten", r.new?.meeting_id);
    add(r.old?.quote, r.old?.timestamp, "Forgotten", r.old?.meeting_id);
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
  const lines = transcript.split(/\n+/).filter((line) => line.trim());
  const rows = lines.length ? lines : [transcript || "No transcript selected."];
  const filtered = rows.filter((line) => {
    if (!query) return true;
    return line.toLowerCase().includes(query.toLowerCase());
  });
  $("transcriptText").innerHTML = filtered.map((line) => `
    <div class="transcript-line">
      <div>${highlightQuery(line, query)}</div>
    </div>
  `).join("");
}

function renderEvidence() {
  const allFacts = state.active?.facts || [];
  const availableTypes = [...new Set(allFacts.map((f) => String(f.type || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  const selectedTypes = new Set(state.evidenceTypeFilter.filter((type) => availableTypes.includes(type)));
  if (selectedTypes.size !== state.evidenceTypeFilter.length) {
    state.evidenceTypeFilter = [...selectedTypes];
  }
  renderEvidenceFilterOptions(availableTypes, selectedTypes);
  const visibleFacts = selectedTypes.size
    ? allFacts.filter((f) => selectedTypes.has(String(f.type || "").trim()))
    : allFacts;
  $("facts").innerHTML = listHtml(visibleFacts, (f) => `
    <li class="line-item">
      <p><b>${escapeHtml(f.subject)}</b>: ${escapeHtml(f.statement)}</p>
      <div class="line-meta">${timestampButton(f.timestamp)}<span>${escapeHtml(f.type)}</span></div>
    </li>
  `);
  renderTranscriptEvidence();
}

function renderEvidenceFilterOptions(availableTypes, selectedTypes) {
  const button = $("evidenceFilterBtn");
  const menu = $("evidenceFilterMenu");
  const allInput = document.querySelector("[data-evidence-filter-all]");
  button.textContent = selectedTypes.size ? `Filter by: ${selectedTypes.size}` : "Filter by: All";
  button.disabled = !availableTypes.length;
  button.setAttribute("aria-expanded", String(!menu.hidden));
  if (allInput) allInput.checked = selectedTypes.size === 0;
  $("evidenceTypeOptions").innerHTML = availableTypes.map((type) => `
    <label class="evidence-filter-option">
      <input type="checkbox" value="${escapeHtml(type)}" data-evidence-filter-type ${selectedTypes.has(type) ? "checked" : ""}>
      <span>${escapeHtml(type)}</span>
    </label>
  `).join("");
}

function renderGlossary() {
  const filter = state.glossaryFilter.trim().toLowerCase();
  const sorted = [...state.glossary].sort((a, b) => {
    const diff = glossaryMentionCount(b.term) - glossaryMentionCount(a.term);
    return diff || String(a.term || "").localeCompare(String(b.term || ""));
  });
  const visibleTerms = sorted.filter((g) => glossaryMatchesFilter(g, filter));
  const visibleDraft = state.glossaryDraft
    .map((g, index) => ({ ...g, index }))
    .filter((g) => glossaryMatchesFilter(g, filter));
  $("editTermsBtn").hidden = state.glossaryEditing;
  $("cancelTermsBtn").hidden = !state.glossaryEditing;
  $("saveTermsBtn").hidden = !state.glossaryEditing;
  $("applyTermsBtn").hidden = !state.glossaryEditing;
  $("termEditorPanel").hidden = false;
  $("termEditList").hidden = !state.glossaryEditing;
  $("termAddRow").hidden = !state.glossaryEditing;
  $("glossaryList").hidden = state.glossaryEditing;
  $("glossaryList").innerHTML = visibleTerms.length ? visibleTerms.map((g) => `
    <div class="term">
      <span>${g.wrong ? `${escapeHtml(g.wrong)} -> ` : ""}<b>${escapeHtml(g.term)}</b></span>
    </div>
  `).join("") : `<div class="term">${filter ? "No matching terminology" : "No terminology yet"}</div>`;
  $("termEditList").innerHTML = state.glossaryEditing && visibleDraft.length ? visibleDraft.map((g) => `
    <div class="term is-editing">
      <input class="term-edit-input" value="${escapeHtml(g.term || "")}" data-term-index="${g.index}" aria-label="Edit ${escapeHtml(g.term || "terminology")}">
      <div class="term-actions">
        <button class="term-editor-btn" type="button" data-delete-term="${g.index}" aria-label="Delete ${escapeHtml(g.term || "terminology")}">×</button>
      </div>
    </div>
  `).join("") : (state.glossaryEditing ? `<div class="term">${filter ? "No matching terminology" : "No terminology yet"}</div>` : "");
  renderGlossaryPanelState();
  renderStats();
}

function glossaryMatchesFilter(item, filter) {
  if (!filter) return true;
  return `${item.term || ""} ${item.wrong || ""}`.toLowerCase().includes(filter);
}

function beginGlossaryEdit() {
  state.glossaryEditing = true;
  state.glossaryCollapsed = false;
  state.glossaryDraft = state.glossary.map((g) => ({ ...g }));
  renderGlossary();
}

function cancelGlossaryEdit() {
  state.glossaryEditing = false;
  state.glossaryDraft = [];
  $("newTermInput").value = "";
  renderGlossary();
}

function addGlossaryDraftTerm() {
  const input = $("newTermInput");
  const term = input.value.trim();
  if (!term) return;
  state.glossaryDraft.push({ id: null, term, wrong: null });
  input.value = "";
  renderGlossary();
  const inputs = document.querySelectorAll("#termEditList .term-edit-input");
  inputs[inputs.length - 1]?.focus();
}

async function saveGlossaryEdit({ exitEditing = true } = {}) {
  const cleanDraft = [];
  const seen = new Set();
  state.glossaryDraft.forEach((item) => {
    const term = String(item.term || "").trim();
    if (!term) return;
    const key = term.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    cleanDraft.push({ ...item, term, wrong: item.wrong || null });
  });

  const originalById = new Map(state.glossary.filter((g) => g.id).map((g) => [String(g.id), g]));
  const draftIds = new Set(cleanDraft.filter((g) => g.id).map((g) => String(g.id)));
  const requests = [];

  state.glossary.forEach((original) => {
    if (original.id && !draftIds.has(String(original.id))) {
      requests.push(request(API.glossaryItem(original.id), { method: "DELETE" }));
    }
  });

  cleanDraft.forEach((draft) => {
    const original = draft.id ? originalById.get(String(draft.id)) : null;
    const changed = original && (
      String(original.term || "").trim() !== draft.term ||
      String(original.wrong || "").trim() !== String(draft.wrong || "").trim()
    );
    if (changed && draft.id) {
      requests.push(request(API.glossaryItem(draft.id), { method: "DELETE" }));
    }
    if (!draft.id || changed) {
      requests.push(request(API.glossary, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          term: draft.term,
          wrong: changed ? String(original.term || "").trim() : (draft.wrong || null),
        }),
      }));
    }
  });

  await Promise.all(requests);
  state.glossary = await request(API.glossary);
  state.glossaryEditing = !exitEditing;
  state.glossaryDraft = exitEditing ? [] : state.glossary.map((g) => ({ ...g }));
  $("newTermInput").value = "";
  renderGlossary();
}

async function saveGlossaryAndApplySelected() {
  if (!state.activeId) throw new Error("Select a meeting before applying terminology.");
  await saveGlossaryEdit();
  const out = await request(API.applyGlossary(state.activeId), { method: "POST" });
  await loadBaseData();
  await selectMeeting(state.activeId, false);
  renderAll();
  showToast(out.changed ? "Refreshed meeting with updated terminology" : "Refreshed meeting analysis");
}

function glossaryMentionCount(term) {
  const clean = String(term || "").trim();
  if (!clean) return 0;
  const haystack = [
    state.active?.title || "",
    state.active?.summary || "",
    state.active?.transcript || "",
    ...(state.active?.key_points || []),
    ...(state.active?.decisions || []).map((item) => `${item.text || ""} ${item.quote || ""}`),
    ...(state.active?.action_items || []).map((item) => `${item.task || ""} ${item.quote || ""}`),
    ...(state.active?.facts || []).map((item) => `${item.subject || ""} ${item.statement || ""} ${item.quote || ""}`),
  ].join("\n");
  const pattern = new RegExp(clean.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
  return (haystack.match(pattern) || []).length;
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
  box.innerHTML = '<div class="suggested-empty">Terminology above is learned automatically.</div>';
}

function renderChat() {
  $("chatMessages").innerHTML = state.chat.map((msg) => `
    <div class="msg-row ${msg.role === "user" ? "user" : "assistant"}">
      ${msg.role === "assistant" ? '<img class="agent-avatar" src="./assets/mnemosyne-logo.png?v=20260616-logo" alt="" aria-hidden="true">' : ""}
      <div class="msg ${msg.role === "user" ? "user" : "assistant"}">
        <p>${escapeHtml(msg.text || "").replace(/\n/g, "<br>")}</p>
      </div>
    </div>
  `).join("");
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
}

function renderSuggestions() {
  const suggestions = [
    "Decision nào đã thay đổi so với cuộc họp trước?",
    "Có claim nào đang mâu thuẫn với lịch sử không?",
    "Ý tưởng nào từng bị bác nay được nhắc lại?",
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
  const [config, stats, meetings, actions, contradictions, resurfaced, glossary] = await Promise.allSettled([
    request(API.config),
    request(API.stats),
    request(API.meetings),
    request(API.actions),
    request(API.contradictions),
    request(API.resurfaced),
    request(API.glossary),
  ]);
  if (meetings.status === "rejected" && BOOTSTRAP_DATA?.meetings) {
    state.maxUploadBytes = BOOTSTRAP_DATA.config?.max_upload_bytes || MAX_UPLOAD_BYTES;
    state.uploadChunkBytes = BOOTSTRAP_DATA.config?.upload_chunk_bytes || DEFAULT_UPLOAD_CHUNK_BYTES;
    state.stats = BOOTSTRAP_DATA.stats || {};
    state.meetings = BOOTSTRAP_DATA.meetings || [];
    state.actions = BOOTSTRAP_DATA.actions || [];
    state.contradictions = BOOTSTRAP_DATA.contradictions || [];
    state.resurfaced = BOOTSTRAP_DATA.resurfaced || [];
    state.glossary = BOOTSTRAP_DATA.glossary || [];
    state.digest = BOOTSTRAP_DATA.digest || null;
    if (!state.activeId && state.meetings.length) {
      state.activeId = state.meetings[0].id;
      state.active = bootstrapMeetingDetail(state.activeId);
      await loadGlossarySuggestions(state.activeId);
    }
    renderAll();
    return;
  }
  const values = [config, stats, meetings, actions, contradictions, resurfaced, glossary].map((result) => {
    if (result.status === "rejected") throw result.reason;
    return result.value;
  });
  const [configData, statsData, meetingsData, actionsData, contradictionsData, resurfacedData, glossaryData] = values;
  state.maxUploadBytes = configData.max_upload_bytes || MAX_UPLOAD_BYTES;
  state.uploadChunkBytes = configData.upload_chunk_bytes || DEFAULT_UPLOAD_CHUNK_BYTES;
  state.stats = statsData;
  state.meetings = meetingsData;
  state.actions = actionsData;
  state.contradictions = contradictionsData;
  state.resurfaced = resurfacedData;
  state.glossary = glossaryData;
  state.digest = null;
  if (!state.activeId && meetingsData.length) {
    await selectMeeting(meetingsData[0].id, false);
  }
  renderAll();
}

async function selectMeeting(id, rerender = true) {
  state.activeId = id;
  try {
    state.active = await request(API.meeting(id));
  } catch (error) {
    const detail = bootstrapMeetingDetail(id);
    if (!detail) throw error;
    state.active = detail;
  }
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
    await autoLearnSuggestedTerms();
  } catch (_) {
    state.glossarySuggestions = BOOTSTRAP_DATA?.glossary_suggestions?.[String(id)] || [];
  }
}

async function autoLearnSuggestedTerms() {
  const existing = new Set(state.glossary.map((g) => String(g.term || "").toLowerCase()));
  const fresh = state.glossarySuggestions
    .sort((a, b) => Number(b.count || 0) - Number(a.count || 0))
    .map((item) => String(item.term || "").trim())
    .filter((term) => term && !existing.has(term.toLowerCase()));
  if (!fresh.length) return;
  await Promise.all(fresh.map((term) => request(API.glossary, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term, wrong: null }),
  })));
  state.glossary = await request(API.glossary);
  state.glossarySuggestions = [];
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
  renderAll();
}

async function updateMeetingGroup(id, groupTitle) {
  const clean = groupTitle.trim();
  if (!id || !clean) return;
  const out = await request(API.updateMeeting(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ group_title: clean }),
  });
  state.meetings = state.meetings.map((m) => (m.id === id ? { ...m, ...out } : m));
  if (state.activeId === id) {
    state.active = { ...state.active, ...out };
  }
  renderAll();
}

async function renameMeetingGroup(oldGroupTitle, newGroupTitle) {
  const oldClean = oldGroupTitle.trim();
  const newClean = newGroupTitle.trim();
  if (!oldClean || !newClean || oldClean === newClean) return;
  await request(API.renameGroup, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ old_group_title: oldClean, new_group_title: newClean }),
  });
  state.meetings = state.meetings.map((m) => {
    const current = m.group_title || deriveMeetingGroup(m);
    return current === oldClean ? { ...m, group_title: newClean } : m;
  });
  if (state.active) {
    const current = state.active.group_title || deriveMeetingGroup(state.active);
    if (current === oldClean) state.active = { ...state.active, group_title: newClean };
  }
  renderAll();
}

async function sendQuestion(question) {
  state.chat.push({ role: "user", text: question, citations: [] });
  renderChat();
  const answer = await request(API.ask, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, meeting_id: state.activeId }),
  });
  state.chat.push({ role: "assistant", text: answer.answer || "No answer.", citations: answer.citations || [] });
  renderChat();
}

function fmtRecClock(ms) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function setRecordingUi(active) {
  $("recordMicBtn").hidden = active;
  $("recordStopBtn").hidden = !active;
}

function canRecordMic() {
  return Boolean(
    window.isSecureContext &&
    window.MediaRecorder &&
    navigator.mediaDevices &&
    navigator.mediaDevices.getUserMedia
  );
}

function refreshRecordingSupport() {
  const button = $("recordMicBtn");
  const status = $("recordStatus");
  if (!button || !status) return false;
  const supported = canRecordMic();
  button.disabled = !supported;
  if (!supported) {
    status.textContent = window.isSecureContext
      ? "Trình duyệt không hỗ trợ ghi âm."
      : "Recording requires localhost or HTTPS.";
  } else if (!state.recorder || state.recorder.state === "inactive") {
    status.textContent = state.recordedFile
      ? "Recording saved. Press Ingest to upload."
      : "Ready to record from microphone.";
  }
  return supported;
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
  refreshRecordingSupport();
}

async function startRecording(mode) {
  if (!refreshRecordingSupport()) {
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
  const mode = $("ingestMode").value;
  const file = mode === "recording" ? state.recordedFile : (mode === "upload" ? $("ingestFile").files[0] : null);
  const text = mode === "transcript" ? $("ingestText").value.trim() : "";
  const jobId = makeClientJobId();
  if (!file && !text) throw new Error("Choose an upload, make a recording, or paste a transcript.");
  if (file && file.size === 0) throw new Error("Selected file is empty. Choose a different file.");
  if (file && file.size > state.maxUploadBytes) throw new Error(`Selected file is larger than ${formatUploadLimit()}. Split it or use a shorter clip.`);
  if (file) form.append("file", file);
  if (text) form.append("text", text);
  form.append("title", $("ingestTitle").value.trim());
  form.append("date", $("ingestDate").value);
  form.append("extract", $("extractAudio").checked ? "true" : "false");
  form.append("on_duplicate", "new");
  form.append("job_id", jobId);
  const signal = state.ingestAbort?.signal;
  resetUploadProgress();
  if (file) showIngestProgress();
  if (file) setIngestPercent(0);
  setUploadStatus(file ? INGEST_WARNING : "Đang chuẩn bị transcript. Giữ cửa sổ này mở.");
  await request(API.health, { signal });
  let out;
  if (file) {
    out = await chunkedIngestMeeting(file, text);
  } else {
    let stopProgress = null;
    try {
      out = await request(API.ingest, {
        method: "POST",
        body: form,
        signal,
      });
    } finally {
      if (stopProgress) stopProgress();
    }
  }
  if (file) setIngestPercent(100);
  $("importDialog").close();
  clearFilePreview();
  resetUploadProgress();
  resetRecording();
  showToast(`Ingested meeting #${out.display_id || out.meeting_id}`);
  await loadBaseData();
  await selectMeeting(out.meeting_id);
}

async function chunkedIngestMeeting(file, text) {
  const signal = state.ingestAbort?.signal;
  const session = await request(API.uploads, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      content_type: file.type || "application/octet-stream",
    }),
    signal,
  });
  const chunkSize = session.chunk_size || state.uploadChunkBytes || DEFAULT_UPLOAD_CHUNK_BYTES;
  const totalChunks = session.total_chunks || Math.ceil(file.size / chunkSize);
  const chunkLoaded = Array(totalChunks).fill(0);
  let nextIndex = 0;
  function uploadedChunkBytes() {
    return chunkLoaded.reduce((sum, value) => sum + value, 0);
  }
  setFileIngestProgress(0);
  async function uploadNextChunk() {
    const index = nextIndex;
    nextIndex += 1;
    if (index >= totalChunks) return;
    const start = index * chunkSize;
    const chunk = file.slice(start, Math.min(start + chunkSize, file.size));
    const chunkForm = new FormData();
    chunkForm.append("index", String(index));
    chunkForm.append("chunk", chunk, `${file.name}.part${index}`);
    await request(API.uploadChunk(session.upload_id), {
      method: "POST",
      body: chunkForm,
      signal,
      onUploadProgress: (loaded, total) => {
        const ratio = total > 0 ? loaded / total : 0;
        chunkLoaded[index] = Math.max(chunkLoaded[index], chunk.size * ratio);
        setFileIngestProgress((uploadedChunkBytes() / file.size) * 70);
      },
    });
    chunkLoaded[index] = chunk.size;
    setFileIngestProgress((uploadedChunkBytes() / file.size) * 70);
    await uploadNextChunk();
  }
  const workerCount = Math.min(CHUNK_UPLOAD_CONCURRENCY, totalChunks);
  const workers = Array.from({ length: workerCount }, () => uploadNextChunk());
  await Promise.all(workers);
  setFileIngestProgress(70);
  const completeForm = new FormData();
  if (text) completeForm.append("text", text);
  completeForm.append("title", $("ingestTitle").value.trim());
  completeForm.append("date", $("ingestDate").value);
  completeForm.append("extract", $("extractAudio").checked ? "true" : "false");
  completeForm.append("on_duplicate", "new");
  setUploadStatus(INGEST_WARNING);
  const stopProgress = pollBackendIngestProgress(session.job_id || session.upload_id, 70);
  try {
    return await request(API.uploadComplete(session.upload_id), { method: "POST", body: completeForm, signal });
  } finally {
    stopProgress();
  }
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

async function updateActionStatus(id, status, checkbox = null) {
  await request(API.action(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  state.actions = state.actions.map((action) => (Number(action.id) === Number(id) ? { ...action, status } : action));
  const row = checkbox?.closest("li");
  if (row) row.classList.toggle("action-completed", statusKey(status) === "completed");
  $("openActionCount").textContent = actionsForActiveMeeting().filter((action) => statusKey(action.status) !== "completed").length;
  showToast("Action status updated");
}

async function assignAction(id, owner, email, btn = null, notify = true) {
  const cleanEmail = email.trim();
  const cleanOwner = owner.trim() || cleanEmail;
  if (!cleanOwner) {
    showToast("Nhập người phụ trách hoặc email", "error");
    return;
  }
  if (notify && !cleanEmail) {
    showToast("Nhập email để gửi assignment", "error");
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const res = await request(API.assignAction(id), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner: cleanOwner, email: cleanEmail || null, notify }),
    });
    state.actions = state.actions.map((action) => (Number(action.id) === Number(id) ? { ...action, owner: res.owner } : action));
    renderMemory();
    showToast(res.sent ? `Đã giao cho ${res.owner} & gửi email tới ${cleanEmail}`
              : res.reason === "email_disabled" ? `Đã giao cho ${res.owner} (email gửi thất bại)`
              : res.reason === "no_email" ? `Đã giao cho ${res.owner} (thiếu email)`
              : `Đã giao cho ${res.owner}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function closeExportMenu() {
  const btn = $("exportBtn");
  const dd = $("exportDropdown");
  if (dd) dd.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function toggleExportMenu() {
  const btn = $("exportBtn");
  if (btn.disabled) return;
  const dd = $("exportDropdown");
  const open = dd.hidden;
  dd.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
}

async function exportReport(fmt) {
  if (!state.activeId) return;
  closeExportMenu();
  const btn = $("exportBtn");
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Đang tạo…";
  try {
    const res = await fetch(API.report(state.activeId, fmt));
    if (!res.ok) {
      let reason = `HTTP ${res.status}`;
      try { reason = (await res.json()).detail || reason; } catch (_) {}
      throw new Error(reason);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = /filename="?([^"]+)"?/.exec(disposition);
    const name = match ? match[1] : `meeting_${state.activeId}.${fmt}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(`Đã xuất ${name}`);
  } catch (err) {
    showToast(`Xuất ${fmt} thất bại: ${err.message}`, "error");
  } finally {
    btn.innerHTML = original;
    btn.disabled = !state.activeId;
  }
}

function bindEvents() {
  $("newMeetingBtn").addEventListener("click", () => {
    setIngestMode($("ingestMode").value || "upload");
    refreshRecordingSupport();
    if (!$("ingestDate").value) $("ingestDate").value = formatLocalDateTimeInput();
    $("importDialog").showModal();
  });
  $("toggleSidebarBtn").addEventListener("click", toggleSidebar);
  $("exportBtn").addEventListener("click", (e) => { e.stopPropagation(); toggleExportMenu(); });
  $("exportDropdown").querySelectorAll("[data-export]").forEach((opt) => {
    opt.addEventListener("click", () => exportReport(opt.dataset.export));
  });
  document.addEventListener("click", (e) => {
    if (!$("exportMenu").contains(e.target)) closeExportMenu();
  });
  $("closeImportBtn").addEventListener("click", () => {
    $("importDialog").close();
    clearFilePreview();
    resetUploadProgress();
    resetRecording();
  });
  $("cancelIngestBtn").addEventListener("click", () => {
    if (state.ingestAbort) {
      // An ingest is in flight — abort the upload/processing instead of just closing.
      state.ingestAbort.abort();
      return;
    }
    $("importDialog").close();
    clearFilePreview();
    resetUploadProgress();
    resetRecording();
  });
  $("ingestMode").addEventListener("change", (event) => setIngestMode(event.target.value));
  $("recordMicBtn").addEventListener("click", () => startRecording("mic"));
  $("recordStopBtn").addEventListener("click", stopRecording);
  $("ingestForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.ingestAbort = new AbortController();
    setIngestBusy(true);
    try {
      setBusy("Ingesting meeting...");
      await ingestMeeting();
    } catch (error) {
      if (error?.name === "AbortError") {
        $("importDialog").close();
        clearFilePreview();
        resetUploadProgress();
        resetRecording();
        showToast("Đã hủy ingest");
      } else {
        setUploadStatus(error.message);
        if (hasSelectedIngestFile()) setUploadProgress(0, "Upload interrupted", error.message, "error");
        showToast(error.message);
      }
    } finally {
      state.ingestAbort = null;
      setIngestBusy(false);
    }
  });
  $("ingestFile").addEventListener("change", () => {
    const file = $("ingestFile").files[0];
    $("ingestFileLabel").textContent = file ? `${file.name}` : "No file selected";
    updateFilePreview(file);
    if (file && file.size === 0) {
      setUploadStatus("This file is empty. Choose another file.");
    } else if (file && file.size > state.maxUploadBytes) {
      setUploadStatus(`This file is larger than ${formatUploadLimit()}. Split it before upload.`);
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
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.target.blur();
    }
  });
  $("activeTitleInput").addEventListener("input", resizeActiveTitle);
  $("activeTitleInput").addEventListener("blur", (event) => {
    updateMeetingName(state.activeId, event.target.value).catch((e) => showToast(e.message));
  });
  $("transcriptSearch").addEventListener("input", (event) => {
    state.transcriptSearch = event.target.value;
    renderTranscriptEvidence();
  });
  $("evidenceFilterBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = $("evidenceFilterMenu");
    menu.hidden = !menu.hidden;
    $("evidenceFilterBtn").setAttribute("aria-expanded", String(!menu.hidden));
  });
  $("evidenceFilterMenu").addEventListener("change", (event) => {
    if (event.target.matches("[data-evidence-filter-all]")) {
      state.evidenceTypeFilter = [];
      renderEvidence();
      return;
    }
    state.evidenceTypeFilter = [...document.querySelectorAll("[data-evidence-filter-type]:checked")]
      .map((input) => input.value);
    renderEvidence();
  });
  document.addEventListener("click", (event) => {
    if (!$("evidenceFilterControl").contains(event.target)) {
      $("evidenceFilterMenu").hidden = true;
      $("evidenceFilterBtn").setAttribute("aria-expanded", "false");
    }
  });
  $("reanalyzeBtn")?.addEventListener("click", () => reanalyzeActive().catch((e) => showToast(e.message)));
  document.querySelectorAll("[data-scroll-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = $(button.dataset.scrollTarget);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  $("playerToggleBtn").addEventListener("click", () => toggleMeetingPlayback());
  $("meetingAudio").addEventListener("play", () => $("playerToggleBtn").classList.add("playing"));
  $("meetingAudio").addEventListener("pause", () => $("playerToggleBtn").classList.remove("playing"));
  $("meetingAudio").addEventListener("ended", () => $("playerToggleBtn").classList.remove("playing"));
  $("meetingAudio").addEventListener("timeupdate", (event) => {
    $("playerTime").textContent = fmtClock(event.target.currentTime);
    updatePlayerProgress(event.target.currentTime, event.target.duration);
  });
  $("meetingAudio").addEventListener("loadedmetadata", (event) => {
    updatePlayerProgress(event.target.currentTime, event.target.duration);
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
    const ts = event.target.closest("[data-ts]");
    if (ts) {
      event.preventDefault();
      seekToTimestamp(ts.dataset.ts);
      return;
    }
    const cite = event.target.closest("[data-cite-meeting]");
    if (cite) {
      event.preventDefault();
      selectMeeting(Number(cite.dataset.citeMeeting)).catch((e) => showToast(e.message));
      return;
    }
    const toggle = event.target.closest("[data-action-toggle]");
    if (toggle) {
      updateActionStatus(Number(toggle.dataset.actionId), toggle.checked ? "completed" : "pending", toggle).catch((e) => showToast(e.message));
      return;
    }
    const assignToggle = event.target.closest("[data-assign-toggle]");
    if (assignToggle) {
      event.preventDefault();
      const form = assignToggle.closest("li")?.querySelector("[data-assign-form]");
      if (form) {
        form.hidden = !form.hidden;
        if (!form.hidden) form.querySelector("[data-assign-owner]")?.focus();
      }
      return;
    }
    const assignOwnerSave = event.target.closest("[data-assign-owner-save]");
    if (assignOwnerSave) {
      event.preventDefault();
      const form = assignOwnerSave.closest("[data-assign-form]");
      const owner = form?.querySelector("[data-assign-owner]")?.value || "";
      assignAction(Number(assignOwnerSave.dataset.actionId), owner, "", assignOwnerSave, false).catch((e) => showToast(e.message));
      return;
    }
    const assignSend = event.target.closest("[data-assign-send]");
    if (assignSend) {
      event.preventDefault();
      const form = assignSend.closest("[data-assign-form]");
      const owner = form?.querySelector("[data-assign-owner]")?.value || "";
      const email = form?.querySelector("[data-assign-email]")?.value || "";
      if (!email.trim()) {
        form?.querySelector("[data-assign-email]")?.focus();
      }
      assignAction(Number(assignSend.dataset.actionId), owner, email, assignSend, true).catch((e) => showToast(e.message));
    }
  });
  document.addEventListener("keydown", (event) => {
    const input = event.target.closest("[data-meeting-title]");
    if (input && event.key === "Enter" && !input.hasAttribute("readonly")) {
      event.preventDefault();
      input.blur();
    }
  });
  document.addEventListener("dblclick", (event) => {
    const input = event.target.closest("[data-meeting-title]");
    if (input && event.type === "dblclick") {
      event.preventDefault();
      if (meetingTitleClickTimer) window.clearTimeout(meetingTitleClickTimer);
      enableMeetingTitleEdit(input);
    }
  });
  document.addEventListener("blur", (event) => {
    const input = event.target.closest("[data-meeting-title]");
    if (input) {
      finishMeetingTitleEdit(input).catch((e) => showToast(e.message));
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
  $("chatInput").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    $("chatForm").requestSubmit();
  });
  $("toggleGlossaryBtn").addEventListener("click", () => {
    state.glossaryCollapsed = !state.glossaryCollapsed;
    renderGlossaryPanelState();
  });
  $("editTermsBtn").addEventListener("click", beginGlossaryEdit);
  $("cancelTermsBtn").addEventListener("click", cancelGlossaryEdit);
  $("saveTermsBtn").addEventListener("click", async () => {
    try {
      await saveGlossaryEdit({ exitEditing: false });
      showToast("Terminology saved");
    } catch (error) {
      alert(`Could not save terminology: ${error.message}`);
    }
  });
  $("applyTermsBtn").addEventListener("click", async () => {
    try {
      await saveGlossaryAndApplySelected();
    } catch (error) {
      alert(`Could not refresh meeting: ${error.message}`);
    }
  });
  $("addTermBtn").addEventListener("click", addGlossaryDraftTerm);
  $("newTermInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") addGlossaryDraftTerm();
  });
  $("termFilterInput").addEventListener("input", (event) => {
    state.glossaryFilter = event.target.value;
    renderGlossary();
  });
  $("termEditList").addEventListener("input", (event) => {
    const input = event.target.closest(".term-edit-input");
    if (!input) return;
    const index = Number(input.dataset.termIndex);
    if (!Number.isNaN(index) && state.glossaryDraft[index]) {
      state.glossaryDraft[index].term = input.value;
    }
  });
  $("termEditList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-term]");
    if (!button) return;
    const index = Number(button.dataset.deleteTerm);
    if (!Number.isNaN(index)) {
      state.glossaryDraft.splice(index, 1);
      renderGlossary();
    }
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
  setIngestMode($("ingestMode").value || "upload");
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
