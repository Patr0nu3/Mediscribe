"use strict";

const state = {
  sessions: [],
  inputFiles: [],
  recordings: [],
  sessionName: "",
  turns: [],
  speakers: [],
  diarization: [],
  activeTurnId: "",
  finished: false,
  dirty: false,
  selection: { turnId: "", wordIds: new Set(), anchorIndex: -1 },
  selectedTurnIds: new Set(),
  turnSelectionMode: false,
  lastSelectedTurnId: "",
  search: { query: "", matches: [], index: -1 },
  showBookmarkedOnly: false,
  unrelatedPending: "",
  deletePending: "",
  timelineScrub: { active: false, pointerId: null, time: null, wasPlaying: false, frame: 0 },
  waveform: null,
  raf: 0,
  jobPoll: 0,
  autosaveTimer: 0,
  saving: false,
  pendingAutosave: false,
  undoStack: [],
  redoStack: [],
  restoringHistory: false,
  textEditSnapshotTurnId: "",
  textEditRevision: null,
  pendingRevisionEvents: [],
  revisionBaseline: null,
  revisionData: null,
  revisionRestorePair: { before: null, after: null },
  roleMenuPlaybackSlow: false,
  pendingFocusTurnId: "",
  globalPlaybackRate: 1,
  dragPlaybackRate: null,
  wordRangeSelect: { pending: null, active: null, suppressClick: false },
  lastWordSelectionTurnId: "",
  textEditPlaybackSlow: false,
  pipelineRunning: false,
  currentJob: null,
  activeTab: "dashboard",
  selectedRecordingKey: "",
  activeJobId: 0,
  pipelineQueue: [],
  pipelineQueueActive: false,
  pipelineFiles: [],
  pipelineWorker: {},
  pipelineLog: [],
  pipelineLogFilter: "",
  pipelineSeenFinished: new Set(),
  lastFinishedJobId: 0,
  lastSpeakerChange: null,
  selectedRecordingKeys: new Set(),
  lastAutoCheckpointAt: 0,
  roleMenuPausedPlayback: false,
  playbackTurnHold: { turnId: "", until: 0 },
  reviewAutoScroll: {
    userPausedUntil: 0,
    textFocused: false,
    programmaticUntil: 0,
    pendingTurnId: "",
    pendingSince: 0,
    lastAutoTurnId: "",
  },
  settings: {
    roleMenuBehavior: "slow",
    slowPlaybackRate: 0.5,
    clickTurnPlays: true,
    wordClickPlays: true,
    followAudioTurn: true,
    textEditSlowsAudio: true,
    wordDragSlowsAudio: true,
    showMergeButtons: false,
    spaceTogglesPlayback: true,
    preservePitch: true,
    autosaveCheckpointMinutes: 5,
    visualLatencySec: 0.2,
    autoScrollDelaySec: 0.65,
  },
};

const els = {
  refreshSessions: document.getElementById("refreshSessions"),
  importAudioButton: document.getElementById("importAudioButton"),
  importAudioEmpty: document.getElementById("importAudioEmpty"),
  audioImport: document.getElementById("audioImport"),
  saveButton: document.getElementById("saveButton"),
  toggleFinished: document.getElementById("toggleFinished"),
  exportTranscript: document.getElementById("exportTranscript"),
  exportAllFinished: document.getElementById("exportAllFinished"),
  selectAllRecordings: document.getElementById("selectAllRecordings"),
  clearRecordingSelection: document.getElementById("clearRecordingSelection"),
  runSelectedRecordings: document.getElementById("runSelectedRecordings"),
  reprocessSelectedRecordings: document.getElementById("reprocessSelectedRecordings"),
  reprocessSelectedInProcessing: document.getElementById("reprocessSelectedInProcessing"),
  showRevisions: document.getElementById("showRevisions"),
  clearCache: document.getElementById("clearCache"),
  runInputFolder: document.getElementById("runInputFolder"),
  pipelinePanel: document.getElementById("pipelinePanel"),
  pipelineStatus: document.getElementById("pipelineStatus"),
  pipelineLanes: document.getElementById("pipelineLanes"),
  laneWorker: document.getElementById("laneWorker"),
  laneWorkerText: document.getElementById("laneWorkerText"),
  laneAudio: document.getElementById("laneAudio"),
  laneAudioText: document.getElementById("laneAudioText"),
  laneLlm: document.getElementById("laneLlm"),
  laneLlmText: document.getElementById("laneLlmText"),
  releaseWorker: document.getElementById("releaseWorker"),
  activeSpeaker: document.getElementById("activeSpeaker"),
  openSpeakerDialog: document.getElementById("openSpeakerDialog"),
  openBulkDialog: document.getElementById("openBulkDialog"),
  toggleTurnSelectionMode: document.getElementById("toggleTurnSelectionMode"),
  selectVisibleTurns: document.getElementById("selectVisibleTurns"),
  clearTurnSelection: document.getElementById("clearTurnSelection"),
  nextBookmark: document.getElementById("nextBookmark"),
  showBookmarks: document.getElementById("showBookmarks"),
  searchInput: document.getElementById("searchInput"),
  replaceInput: document.getElementById("replaceInput"),
  searchPrev: document.getElementById("searchPrev"),
  searchNext: document.getElementById("searchNext"),
  replaceOne: document.getElementById("replaceOne"),
  replaceAll: document.getElementById("replaceAll"),
  searchCount: document.getElementById("searchCount"),
  turnList: document.getElementById("turnList"),
  audio: document.getElementById("audioPlayer"),
  playPauseButton: document.getElementById("playPauseButton"),
  jumpBack10: document.getElementById("jumpBack10"),
  jumpForward10: document.getElementById("jumpForward10"),
  currentTimeLabel: document.getElementById("currentTimeLabel"),
  durationLabel: document.getElementById("durationLabel"),
  speedSlider: document.getElementById("speedSlider"),
  speedValue: document.getElementById("speedValue"),
  turnProgressCircle: document.getElementById("turnProgressCircle"),
  turnProgressText: document.getElementById("turnProgressText"),
  turnProgressLabel: document.getElementById("turnProgressLabel"),
  turnProgressHint: document.getElementById("turnProgressHint"),
  selectionRole: document.getElementById("selectionRole"),
  selectionRange: document.getElementById("selectionRange"),
  selectionFacts: document.getElementById("selectionFacts"),
  selectionFlags: document.getElementById("selectionFlags"),
  speakerSummary: document.getElementById("speakerSummary"),
  reviewSummaryTotals: document.getElementById("reviewSummaryTotals"),
  timeline: document.getElementById("timelineCanvas"),
  selectionMeta: document.getElementById("selectionMeta"),
  revisionPanel: document.getElementById("revisionPanel"),
  revisionList: document.getElementById("revisionList"),
  revisionBefore: document.getElementById("revisionBefore"),
  revisionAfter: document.getElementById("revisionAfter"),
  restoreRevisionBefore: document.getElementById("restoreRevisionBefore"),
  restoreRevisionAfter: document.getElementById("restoreRevisionAfter"),
  tabButtons: Array.from(document.querySelectorAll(".tab-button")),
  dashboardView: document.getElementById("dashboardView"),
  processingView: document.getElementById("processingView"),
  reviewView: document.getElementById("reviewView"),
  revisionsView: document.getElementById("revisionsView"),
  settingsView: document.getElementById("settingsView"),
  dashboardStats: document.getElementById("dashboardStats"),
  recordingTable: document.getElementById("recordingTable"),
  dashboardEmpty: document.getElementById("dashboardEmpty"),
  processingBacklogList: document.getElementById("processingBacklogList"),
  pipelineFileGrid: document.getElementById("pipelineFileGrid"),
  pipelineLogFilter: document.getElementById("pipelineLogFilter"),
  pipelineLogList: document.getElementById("pipelineLogList"),
  reviewRecordingName: document.getElementById("reviewRecordingName"),
  diffRecordingName: document.getElementById("diffRecordingName"),
  settingRoleMenuBehavior: document.getElementById("settingRoleMenuBehavior"),
  settingSlowSpeed: document.getElementById("settingSlowSpeed"),
  settingSlowSpeedValue: document.getElementById("settingSlowSpeedValue"),
  settingClickTurnPlays: document.getElementById("settingClickTurnPlays"),
  settingWordClickPlays: document.getElementById("settingWordClickPlays"),
  settingFollowAudioTurn: document.getElementById("settingFollowAudioTurn"),
  settingTextEditSlowsAudio: document.getElementById("settingTextEditSlowsAudio"),
  settingWordDragSlowsAudio: document.getElementById("settingWordDragSlowsAudio"),
  settingShowMergeButtons: document.getElementById("settingShowMergeButtons"),
  settingSpaceTogglesPlayback: document.getElementById("settingSpaceTogglesPlayback"),
  settingVisualLatency: document.getElementById("settingVisualLatency"),
  settingVisualLatencyValue: document.getElementById("settingVisualLatencyValue"),
  settingAutoScrollDelay: document.getElementById("settingAutoScrollDelay"),
  settingAutoScrollDelayValue: document.getElementById("settingAutoScrollDelayValue"),
  settingAutosaveMinutes: document.getElementById("settingAutosaveMinutes"),
  modalBackdrop: document.getElementById("modalBackdrop"),
  modalTitle: document.getElementById("modalTitle"),
  modalMessage: document.getElementById("modalMessage"),
  modalBody: document.getElementById("modalBody"),
  modalCancel: document.getElementById("modalCancel"),
  modalConfirm: document.getElementById("modalConfirm"),
};

// Backend stage keys in order (mediscribe_v2.pipeline.STAGES): lanes audio x4, llm x2.
const FILE_STAGES = ["Prepare", "Transcribe", "Diarize", "Fuse", "Roles", "Render"];
const FILE_STAGE_ESTIMATE_SECONDS = [10, 240, 120, 20, 90, 10];
const FILE_STATUS_LABELS = {
  queued: "Queued",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  awaiting_resume: "Awaiting resume",
};
const DEFAULT_SPEAKERS = ["Unknown"];
// Mirrors fuse.UNCERTAIN_THRESHOLD: words the fusion stage flagged as uncertain.
const LOW_WORD_CONFIDENCE = 0.45;
const WORD_RANGE_HOLD_MS = 90;
const WORD_RANGE_MOVE_TOLERANCE = 10;
const ROLE_LOCAL_BOUNDARY_GAP_SEC = 180;
const ROLE_LOCAL_DECAY_SEC = 75;
const ROLE_CYCLE_CONTEXT_SEC = ROLE_LOCAL_DECAY_SEC * 2;
const ROLE_GLOBAL_WEIGHT = 0.35;
const ROLE_LOCAL_WEIGHT = 1;
// Fixed horizontal overhead around a row's text: number/time/speaker columns,
// grid gaps, row + list padding, the speaker border, and the text element's own
// padding. Selection mode adds its checkbox column on top.
const TURN_ROW_TEXT_OVERHEAD_PX = 344;
const TURN_ROW_SELECTION_EXTRA_PX = 36;
const WORD_STRIP_TEXT_PADDING_PX = 11;
const TIMED_WORD_CLIPBOARD_TYPE = "application/x-mediscribe-words";
const SETTINGS_STORAGE_KEY = "mediscribe.review.settings.v1";
const AUTO_SCROLL_USER_COOLDOWN_MS = 3500;
const AUTO_SCROLL_TEXT_EXIT_COOLDOWN_MS = 1200;
const AUTO_SCROLL_TARGET_COOLDOWN_MS = 650;
const PROGRAMMATIC_SCROLL_GRACE_MS = 500;
const ACTIVE_TURN_SCROLL_FRACTION = 1 / 3;
// During playback the rAF loop runs at ~60 Hz; the word highlight updates every
// frame but the timeline canvas + progress circle only need ~15 Hz.
const TIMELINE_REDRAW_INTERVAL_MS = 66;
const SEARCH_REFRESH_DEBOUNCE_MS = 150;
// Browser-side waveform decoding expands compressed/PCM audio into a full
// Float32 buffer. Keep eager previews to short, modest files; long recordings
// retain the fully functional timeline/playback without paying that load cost.
const MAX_EAGER_WAVEFORM_DURATION_SEC = 10 * 60;
const MAX_EAGER_WAVEFORM_BYTES = 24 * 1024 * 1024;
const WAVEFORM_BUCKET_COUNT = 800;
const MAX_WAVEFORM_SAMPLES_PER_BUCKET = 256;

function showNotice(message, title = "Notice") {
  return showModal({ title, message, confirmText: "OK", cancelText: null });
}

function showErrorNotice(error) {
  const message = error && error.message ? error.message : String(error || "Request failed");
  return showNotice(message, "Error");
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}

function loadSettings() {
  try {
    const payload = JSON.parse(window.localStorage.getItem(SETTINGS_STORAGE_KEY) || "{}");
    if (payload && typeof payload === "object") {
      state.settings = {
        ...state.settings,
        ...payload,
        slowPlaybackRate: clampNumber(payload.slowPlaybackRate, 0.25, 1, state.settings.slowPlaybackRate),
        clickTurnPlays: payload.clickTurnPlays !== false,
        wordClickPlays: payload.wordClickPlays !== false,
        followAudioTurn: payload.followAudioTurn !== false,
        textEditSlowsAudio: payload.textEditSlowsAudio !== false,
        wordDragSlowsAudio: payload.wordDragSlowsAudio !== false,
        showMergeButtons: payload.showMergeButtons === true,
        spaceTogglesPlayback: payload.spaceTogglesPlayback !== false,
        autosaveCheckpointMinutes: Math.round(clampNumber(payload.autosaveCheckpointMinutes, 1, 30, 5)),
        visualLatencySec: clampNumber(payload.visualLatencySec, 0, 0.5, state.settings.visualLatencySec),
        autoScrollDelaySec: clampNumber(payload.autoScrollDelaySec, 0, 2, state.settings.autoScrollDelaySec),
      };
    }
  } catch {
    return;
  }
}

function saveSettings() {
  window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.settings));
}

function renderSettings() {
  if (!els.settingRoleMenuBehavior) return;
  els.settingRoleMenuBehavior.value = state.settings.roleMenuBehavior;
  els.settingSlowSpeed.value = String(state.settings.slowPlaybackRate);
  els.settingSlowSpeedValue.textContent = `${state.settings.slowPlaybackRate.toFixed(2)}x`;
  els.settingClickTurnPlays.checked = Boolean(state.settings.clickTurnPlays);
  els.settingWordClickPlays.checked = Boolean(state.settings.wordClickPlays);
  els.settingFollowAudioTurn.checked = Boolean(state.settings.followAudioTurn);
  els.settingTextEditSlowsAudio.checked = Boolean(state.settings.textEditSlowsAudio);
  els.settingWordDragSlowsAudio.checked = Boolean(state.settings.wordDragSlowsAudio);
  els.settingShowMergeButtons.checked = Boolean(state.settings.showMergeButtons);
  els.settingSpaceTogglesPlayback.checked = Boolean(state.settings.spaceTogglesPlayback);
  els.settingVisualLatency.value = String(state.settings.visualLatencySec);
  els.settingVisualLatencyValue.textContent = `${state.settings.visualLatencySec.toFixed(2)}s`;
  els.settingAutoScrollDelay.value = String(state.settings.autoScrollDelaySec);
  els.settingAutoScrollDelayValue.textContent = `${state.settings.autoScrollDelaySec.toFixed(2)}s`;
  els.settingAutosaveMinutes.value = String(state.settings.autosaveCheckpointMinutes);
}

function updateSetting(key, value) {
  state.settings[key] = value;
  saveSettings();
  renderSettings();
  if (key === "preservePitch") preservePitch();
  if (key === "visualLatencySec") {
    updateCurrentWordHighlight();
    drawTimeline();
  }
  if (key === "autoScrollDelaySec") {
    resetPlaybackAutoScrollTarget();
  }
  if (key === "showMergeButtons") {
    renderTurns({ scrollActive: false, scrollAnchorTurnId: state.activeTurnId });
  }
  if (key === "textEditSlowsAudio" && !value) {
    endTextEditPlayback();
  }
  if (key === "wordDragSlowsAudio") {
    applyEffectivePlaybackRate();
  }
  applyEffectivePlaybackRate();
}

function showModal({ title, message, confirmText = "Continue", cancelText = "Cancel", danger = false, build = null }) {
  return new Promise((resolve) => {
    els.modalTitle.textContent = title;
    els.modalMessage.textContent = message;
    els.modalBody.replaceChildren();
    if (typeof build === "function") build(els.modalBody);
    els.modalBody.hidden = els.modalBody.childElementCount === 0;
    els.modalConfirm.textContent = confirmText;
    // cancelText null -> a plain notice with one OK button.
    els.modalCancel.hidden = cancelText === null;
    els.modalCancel.textContent = cancelText === null ? "Cancel" : cancelText;
    els.modalConfirm.classList.toggle("modal-confirm-danger", danger);
    els.modalBackdrop.hidden = false;
    els.modalConfirm.focus({ preventScroll: true });

    const cleanup = (value) => {
      els.modalBackdrop.hidden = true;
      els.modalCancel.hidden = false;
      els.modalConfirm.classList.remove("modal-confirm-danger");
      els.modalConfirm.removeEventListener("click", onConfirm);
      els.modalCancel.removeEventListener("click", onCancel);
      els.modalBackdrop.removeEventListener("click", onBackdrop);
      window.removeEventListener("keydown", onKeydown);
      resolve(value);
    };
    const onConfirm = () => cleanup(true);
    const onCancel = () => cleanup(false);
    const onBackdrop = (event) => {
      if (event.target === els.modalBackdrop) cleanup(false);
    };
    const onKeydown = (event) => {
      if (event.key === "Escape") cleanup(false);
    };

    els.modalConfirm.addEventListener("click", onConfirm);
    els.modalCancel.addEventListener("click", onCancel);
    els.modalBackdrop.addEventListener("click", onBackdrop);
    window.addEventListener("keydown", onKeydown);
  });
}

function showFormModal({
  title,
  message,
  confirmText = "Apply",
  cancelText = "Cancel",
  danger = false,
  build,
  validate,
}) {
  return new Promise((resolve) => {
    els.modalTitle.textContent = title;
    els.modalMessage.textContent = message;
    els.modalBody.replaceChildren();
    els.modalBody.hidden = false;
    els.modalConfirm.textContent = confirmText;
    els.modalCancel.textContent = cancelText;
    els.modalConfirm.classList.toggle("modal-confirm-danger", danger);
    const context = build?.(els.modalBody) || {};
    els.modalBackdrop.hidden = false;
    const focusTarget = els.modalBody.querySelector("input, select, button") || els.modalConfirm;
    focusTarget.focus({ preventScroll: true });

    const cleanup = (value) => {
      els.modalBackdrop.hidden = true;
      els.modalConfirm.classList.remove("modal-confirm-danger");
      els.modalBody.replaceChildren();
      els.modalBody.hidden = true;
      els.modalConfirm.removeEventListener("click", onConfirm);
      els.modalCancel.removeEventListener("click", onCancel);
      els.modalBackdrop.removeEventListener("click", onBackdrop);
      window.removeEventListener("keydown", onKeydown);
      resolve(value);
    };
    const onConfirm = () => {
      const value = validate ? validate(context) : true;
      if (value === false) return;
      cleanup(value);
    };
    const onCancel = () => cleanup(false);
    const onBackdrop = (event) => {
      if (event.target === els.modalBackdrop) cleanup(false);
    };
    const onKeydown = (event) => {
      if (event.key === "Escape") cleanup(false);
      if (event.key === "Enter" && event.target?.tagName !== "TEXTAREA") {
        event.preventDefault();
        onConfirm();
      }
    };

    els.modalConfirm.addEventListener("click", onConfirm);
    els.modalCancel.addEventListener("click", onCancel);
    els.modalBackdrop.addEventListener("click", onBackdrop);
    window.addEventListener("keydown", onKeydown);
  });
}

function recordingHasProcessedFiles(recording) {
  return Boolean(recording?.hasSession || recording?.session?.has_editor || recording?.session?.has_debug || recording?.session?.has_aligned_json || recording?.session?.has_final);
}

async function confirmPipelineRun(recording) {
  if (recordingNeedsResume(recording)) return true;
  if (!recordingHasProcessedFiles(recording)) return true;
  const dirtyWarning = state.dirty ? " Unsaved editor changes may be discarded." : "";
  return showModal({
    title: "Rerun Analysis",
    message: `Rerun analysis for "${recording.name}"? Existing processed transcript files for this recording can be replaced.${dirtyWarning}`,
    confirmText: "Rerun",
    cancelText: "Cancel",
    danger: true,
  });
}

function apiPath(path) {
  return path.split("/").map((part, index) => (index === 0 ? part : encodeURIComponent(part))).join("/");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function cleanText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function isDiarizationSpeaker(label) {
  return /^speaker[\s_-]*\d+$/i.test(cleanText(label));
}

function speakerLabel(label, fallback = "Unknown") {
  const text = cleanText(label);
  if (text && !isDiarizationSpeaker(text)) return text;
  return fallback;
}

function normalizeSpeakerList(speakers = []) {
  const seen = [];
  for (const label of [...DEFAULT_SPEAKERS, ...(Array.isArray(speakers) ? speakers : [])]) {
    const speaker = speakerLabel(label, "");
    if (speaker && !seen.includes(speaker)) seen.push(speaker);
  }
  return seen;
}

function speakerListFromValues(values = []) {
  const seen = [];
  for (const label of Array.isArray(values) ? values : []) {
    const speaker = speakerLabel(label, "");
    if (speaker && !seen.includes(speaker)) seen.push(speaker);
  }
  return seen;
}

function numberOr(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function fileStem(filename) {
  return cleanText(filename).replace(/\.[^.]+$/, "");
}

function recordingDisplayName(name) {
  return fileStem(name) || cleanText(name) || "Untitled recording";
}

function inputDisplayName(path, fallback = "Input folder") {
  const normalized = cleanText(path).replaceAll("\\", "/");
  const filename = normalized.split("/").filter(Boolean).pop() || "";
  return fileStem(filename) || filename || fallback;
}

function loadedAudioDisplayName(sessionName) {
  const recording = selectedRecording();
  const inputName = recording?.inputFile?.name || recording?.inputPath || "";
  return inputName ? inputDisplayName(inputName, recordingDisplayName(sessionName)) : recordingDisplayName(sessionName);
}

function recordingNameForInput(file) {
  const name = cleanText(file.stem)
    || fileStem(file.name)
    || fileStem(cleanText(file.path).split("/").pop());
  return name || "Untitled recording";
}

function sessionNameForRecording(session) {
  const name = String(session?.name ?? "");
  return cleanText(name) ? name : "";
}

function buildRecordings() {
  const byName = new Map();

  for (const file of state.inputFiles) {
    const name = recordingNameForInput(file);
    byName.set(name, {
      key: name,
      name,
      inputPath: file.path,
      inputFile: file,
      inputSize: Number(file.size) || 0,
      inputDurationSec: Number(file.duration_sec) || 0,
      session: null,
      hasInput: true,
      hasSession: false,
      modified: Number(file.modified) || 0,
    });
  }

  for (const session of state.sessions) {
    const name = sessionNameForRecording(session);
    if (!name) continue;
    const trimmedName = cleanText(name);
    const existingInputRecord = trimmedName !== name ? byName.get(trimmedName) : null;
    const record = byName.get(name) || (existingInputRecord && !existingInputRecord.session ? existingInputRecord : null) || {
      key: name,
      name,
      inputPath: "",
      inputFile: null,
      inputSize: 0,
      inputDurationSec: 0,
      session: null,
      hasInput: false,
      hasSession: false,
      modified: 0,
    };
    if (record.key !== name) {
      byName.delete(record.key);
      record.key = name;
      record.name = name;
    }
    record.session = session;
    record.hasSession = Boolean(session.has_editor || session.has_debug || session.has_aligned_json || session.has_final);
    record.hasInput = record.hasInput || Boolean(session.has_input);
    record.inputSize = record.inputSize || Number(session.audio_size) || 0;
    record.inputDurationSec = record.inputDurationSec || Number(session.audio_duration_sec) || 0;
    record.modified = Math.max(record.modified, Number(session.modified) || 0);
    byName.set(name, record);
  }

  // Rank purely by the last time the recording was modified (most recent first),
  // falling back to name for stable ordering when timestamps tie.
  return Array.from(byName.values()).sort((left, right) => {
    return right.modified - left.modified || left.name.localeCompare(right.name);
  });
}

function selectedRecording() {
  return state.recordings.find((recording) => recording.key === state.selectedRecordingKey) || null;
}

function finishedSessionCount() {
  const names = new Set(state.sessions.filter((session) => session.finished).map((session) => session.name));
  if (state.sessionName) {
    if (state.finished) {
      names.add(state.sessionName);
    } else {
      names.delete(state.sessionName);
    }
  }
  return names.size;
}

function selectedRecordings() {
  return state.recordings.filter((recording) => state.selectedRecordingKeys.has(recording.key));
}

function selectedFinishedRecordings() {
  return selectedRecordings().filter((recording) => recording.session?.finished);
}

function queuedInputPath(item) {
  return item?.inputPath || item?.input_path || "";
}

function normalizeInputPathForMatch(path) {
  return cleanText(path).replaceAll("\\", "/").replace(/^.*\/data\/input\//, "");
}

function inputPathMatches(candidatePath, inputPath) {
  const candidate = normalizeInputPathForMatch(candidatePath);
  const input = normalizeInputPathForMatch(inputPath);
  return Boolean(candidate && input && (candidate === input || candidate.endsWith(`/${input}`)));
}

function pipelineFileForRecording(recording) {
  if (!recording?.inputPath) return null;
  return state.pipelineFiles.find((file) => inputPathMatches(file.input_path, recording.inputPath)) || null;
}

function recordingIsRunning(recording) {
  return pipelineFileForRecording(recording)?.status === "running";
}

function recordingIsQueued(recording) {
  return pipelineFileForRecording(recording)?.status === "queued";
}

function recordingNeedsResume(recording) {
  return recording?.session?.state === "awaiting_resume";
}

function recordingCannotResume(recording) {
  return recording?.session?.state === "cannot_resume";
}

function recordingReviewOnly(recording) {
  return recording?.session?.state === "review_only";
}

function recordingReviewReady(recording) {
  return Boolean(recording?.hasSession && !recordingNeedsResume(recording) && !recordingCannotResume(recording));
}

function recordingNeedsPipeline(recording) {
  return Boolean(recording && recording.session?.state !== "error" && (
    (recording.hasInput && !recording.hasSession)
    || recordingNeedsResume(recording)
  ));
}

function recordingProcessingVisible(recording) {
  return recordingNeedsPipeline(recording) || recordingCannotResume(recording);
}

function unprocessedRecordings() {
  return state.recordings.filter((recording) => (
    recordingNeedsPipeline(recording)
    && recording.hasInput
    && !recordingIsRunning(recording)
    && !recordingIsQueued(recording)
  ));
}

function reprocessableRecordings(recordings = selectedRecordings()) {
  return recordings.filter((recording) => (
    recording?.hasInput
    && recording.session?.state !== "error"
    && !recordingCannotResume(recording)
    && !recordingIsRunning(recording)
    && !recordingIsQueued(recording)
  ));
}

// Selected recordings that have imported audio but still need the pipeline run
// (never processed, or awaiting resume) — i.e. the ones "Run Selected" will queue.
function runnableSelectedRecordings(recordings = selectedRecordings()) {
  return recordings.filter((recording) => (
    recordingNeedsPipeline(recording)
    && recording.hasInput
    && !recordingIsRunning(recording)
    && !recordingIsQueued(recording)
  ));
}

function pruneSelectedRecordings() {
  const validKeys = new Set(state.recordings.map((recording) => recording.key));
  state.selectedRecordingKeys = new Set(
    Array.from(state.selectedRecordingKeys).filter((key) => validKeys.has(key)),
  );
}

// Update only the selection-dependent controls. Unlike updateRecordingActions this
// does NOT rebuild the recordings table, so toggling a row checkbox keeps the
// dashboard scroll position instead of jumping back to the top.
function refreshSelectionControls() {
  pruneSelectedRecordings();
  const selectedCount = selectedRecordings().length;
  if (els.selectAllRecordings) els.selectAllRecordings.disabled = state.recordings.length === 0;
  if (els.clearRecordingSelection) els.clearRecordingSelection.disabled = selectedCount === 0;
  updateFinishedControls();
}

function toggleRecordingSelection(key, selected) {
  if (selected) state.selectedRecordingKeys.add(key);
  else state.selectedRecordingKeys.delete(key);
  refreshSelectionControls();
}

function formatDateTime(timestamp) {
  const seconds = Number(timestamp) || 0;
  if (!seconds) return "Not available";
  return new Date(seconds * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatFileSize(bytes) {
  const size = Number(bytes) || 0;
  if (!size) return "Unknown";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 || unitIndex === 0 ? Math.round(value) : value.toFixed(1)} ${units[unitIndex]}`;
}

function formatAudioLength(seconds) {
  const duration = Number(seconds) || 0;
  return duration > 0 ? formatTime(duration) : "Unknown";
}

// True when a recording has manual edits beyond the raw pipeline output: unsaved
// changes in the open session, a saved editor transcript, or recorded revisions.
function recordingHasEdits(recording) {
  if (!recording) return false;
  if (recording.name === state.sessionName && state.dirty) return true;
  const session = recording.session;
  return Boolean(session && (session.has_editor || session.has_revisions));
}

function recordingStatus(recording) {
  if (!recording) return "No recording";
  if (recording.session?.state === "error") return "Error";
  if (recordingCannotResume(recording)) return "Cannot resume";
  if (recordingIsRunning(recording)) return "Running";
  if (recordingIsQueued(recording)) return "Queued";
  if (recording.session?.state === "awaiting_resume") return "Awaiting resume";
  if (recording.session?.finished) return "Finished";
  if (recordingReviewOnly(recording)) return recordingHasEdits(recording) ? "Editing" : "Review only";
  if (recordingReviewReady(recording)) {
    if (recordingHasEdits(recording)) return "Editing";
    return recording.hasInput ? "Ready for review" : "Review only";
  }
  if (recording.hasInput) return "Needs pipeline";
  return "Inactive";
}

function statusClass(status) {
  return `status-${status.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function setActiveTab(tab, options = {}) {
  const allowedTabs = ["dashboard", "processing", "review", "revisions", "settings"];
  let nextTab = allowedTabs.includes(tab) ? tab : "dashboard";
  if ((nextTab === "review" || nextTab === "revisions") && !state.sessionName) {
    nextTab = "dashboard";
  }
  state.activeTab = nextTab;
  const views = {
    dashboard: els.dashboardView,
    processing: els.processingView,
    review: els.reviewView,
    revisions: els.revisionsView,
    settings: els.settingsView,
  };
  for (const [key, view] of Object.entries(views)) {
    if (view) view.hidden = key !== nextTab;
  }
  els.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === nextTab);
  });
  if (nextTab === "processing" && !state.jobPoll) {
    pollPipelineJob().catch(() => {});
  }
  if (nextTab === "review") {
    drawTimeline();
    // The session may have been rendered while this view was hidden (width 0),
    // leaving lines split against an estimated width; re-split when it differs.
    if (
      !options.skipTurnRender
      && state.turns.length
      && Math.abs(turnLineAvailableWidthPx() - (state.renderedLineWidthPx || 0)) > 8
    ) {
      renderTurns({ scrollActive: false, preserveScroll: true, scrollAnchorTurnId: state.activeTurnId });
    }
  } else if (nextTab === "revisions" && state.sessionName) {
    loadRevisionData().catch((error) => showErrorNotice(error));
  } else if (nextTab === "settings") {
    renderSettings();
  } else if (nextTab === "revisions") {
    state.revisionData = null;
    if (els.revisionBefore) els.revisionBefore.textContent = "Select a reviewed recording to see before/after changes.";
    if (els.revisionAfter) els.revisionAfter.textContent = "";
    if (els.revisionList) els.revisionList.replaceChildren();
  }
}

function updateTabAvailability() {
  els.tabButtons.forEach((button) => {
    const isSessionTab = button.dataset.tab === "review" || button.dataset.tab === "revisions";
    button.hidden = isSessionTab && !state.sessionName;
  });
  if (!state.sessionName && (state.activeTab === "review" || state.activeTab === "revisions")) {
    setActiveTab("dashboard");
  }
}

function uniqueId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function formatTime(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  const secs = Math.floor(safe % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function speakerColor(label) {
  const palette = {
    Clinician: "#157a6e",
    Clinician2: "#2f9e8f",
    Patient: "#4169a8",
    "Patient's Family": "#8a5a9e",
    "Medical Staff": "#99621e",
    Unknown: "#677483",
  };
  if (palette[label]) return palette[label];
  let hash = 0;
  for (const char of String(label || "Unknown")) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  const hue = hash % 360;
  return `hsl(${hue} 38% 43%)`;
}

function roleClass(label) {
  const normalized = cleanText(label).toLowerCase();
  if (normalized === "clinician") return "role-clinician";
  if (normalized === "clinician2" || normalized === "clinician 2") return "role-clinician2";
  if (normalized === "patient") return "role-patient";
  if (normalized === "patient's family" || normalized === "family") return "role-family";
  if (normalized === "medical staff" || normalized === "staff") return "role-staff";
  if (!normalized || normalized === "unknown") return "role-unknown";
  return "role-other";
}

function normalizeTurn(turn, index) {
  const start = numberOr(turn.start_sec, index);
  const end = Math.max(numberOr(turn.end_sec, start + 0.01), start + 0.01);
  const id = turn.id || `turn-${index}`;
  const text = cleanText(turn.text);
  const words = Array.isArray(turn.words) ? turn.words : [];
  return {
    id,
    label: speakerLabel(turn.label || turn.final_role || turn.assigned_role || turn.speaker || turn.raw_speaker),
    raw_speaker: cleanText(turn.raw_speaker || turn.speaker || ""),
    start_sec: start,
    end_sec: end,
    text,
    bookmarked: Boolean(turn.bookmarked),
    unclear_intro: Boolean(turn.unclear_intro),
    source: cleanText(turn.source) || "pipeline",
    timingReliable: turn.timingReliable ?? turn.timing_reliable ?? true,
    playbackRate: normalizePlaybackRate(turn.playbackRate ?? turn.playback_rate),
    text_provenance: turn.text_provenance && typeof turn.text_provenance === "object"
      ? { ...turn.text_provenance }
      : null,
    words: words.length ? words.map((word, wordIndex) => ({
      id: word.id || `${id}-w${wordIndex}`,
      text: cleanText(word.text || word.raw_text || word.word),
      start_sec: numberOr(word.start_sec, start),
      end_sec: Math.max(numberOr(word.end_sec, end), numberOr(word.start_sec, start) + 0.01),
      confidence: word.confidence,
      speaker: cleanText(word.speaker || ""),
      manual: Boolean(word.manual),
      timing_source: cleanText(word.timing_source || ""),
      copied_from_word_id: cleanText(word.copied_from_word_id || ""),
      inherited_from_word_id: cleanText(word.inherited_from_word_id || ""),
    })).filter((word) => word.text) : wordsFromText(text, start, end, id),
  };
}

function wordsFromText(text, start, end, turnId) {
  const tokens = cleanText(text).match(/\S+/g) || [];
  const duration = Math.max(0.01, end - start);
  const step = duration / Math.max(1, tokens.length);
  return tokens.map((token, index) => ({
    id: `${turnId}-w${index}-${Math.random().toString(36).slice(2, 5)}`,
    text: token,
    start_sec: Number((start + step * index).toFixed(3)),
    end_sec: Number((start + step * (index + 1)).toFixed(3)),
    manual: true,
    timing_source: "synthetic",
  }));
}

function wordToken(word) {
  return cleanText(word?.text || word?.raw_text || word?.word).toLowerCase();
}

function wordAlignmentPairs(existingWords, tokens) {
  const oldTokens = existingWords.map(wordToken);
  const newTokens = tokens.map((token) => cleanText(token).toLowerCase());
  const rows = oldTokens.length + 1;
  const cols = newTokens.length + 1;
  const table = Array.from({ length: rows }, () => Array(cols).fill(0));

  for (let row = oldTokens.length - 1; row >= 0; row -= 1) {
    for (let col = newTokens.length - 1; col >= 0; col -= 1) {
      table[row][col] = oldTokens[row] === newTokens[col]
        ? table[row + 1][col + 1] + 1
        : Math.max(table[row + 1][col], table[row][col + 1]);
    }
  }

  const pairs = [];
  let row = 0;
  let col = 0;
  while (row < oldTokens.length && col < newTokens.length) {
    if (oldTokens[row] === newTokens[col]) {
      pairs.push({ oldIndex: row, newIndex: col, word: existingWords[row] });
      row += 1;
      col += 1;
    } else if (table[row + 1][col] >= table[row][col + 1]) {
      row += 1;
    } else {
      col += 1;
    }
  }
  return pairs;
}

function matchExistingWords(existingWords, tokens) {
  const matches = new Map();
  for (const pair of wordAlignmentPairs(existingWords, tokens)) {
    matches.set(pair.newIndex, pair.word);
  }
  return matches;
}

function cloneTimedWord(word, token, overrides = {}) {
  return {
    ...word,
    ...overrides,
    text: token,
    start_sec: numberOr(overrides.start_sec ?? word.start_sec, numberOr(word.start_sec, 0)),
    end_sec: Math.max(
      numberOr(overrides.end_sec ?? word.end_sec, numberOr(word.end_sec, numberOr(word.start_sec, 0) + 0.01)),
      numberOr(overrides.start_sec ?? word.start_sec, numberOr(word.start_sec, 0)) + 0.01,
    ),
  };
}

function splitTimedInterval(tokens, startIndex, count, intervalStart, intervalEnd, turn, source, inheritedWords = []) {
  const start = numberOr(intervalStart, Number(turn.start_sec) || 0);
  const safeEnd = Math.max(numberOr(intervalEnd, start + 0.01), start + 0.01);
  const step = Math.max(0.01, (safeEnd - start) / Math.max(1, count));
  const words = [];
  for (let offset = 0; offset < count; offset += 1) {
    const wordStart = Number((start + step * offset).toFixed(3));
    const wordEnd = Number((offset === count - 1 ? safeEnd : Math.min(safeEnd, wordStart + step)).toFixed(3));
    const inherited = inheritedWords[Math.min(offset, inheritedWords.length - 1)] || inheritedWords[0] || null;
    words.push({
      id: uniqueId(`${turn.id}-w`),
      text: tokens[startIndex + offset],
      start_sec: wordStart,
      end_sec: Math.max(wordEnd, wordStart + 0.01),
      manual: true,
      timing_source: source,
      inherited_from_word_id: inherited?.id || "",
    });
  }
  return words;
}

function takePreferredWords(preferredWords, cursor, tokens, startIndex, count, turn) {
  if (!Array.isArray(preferredWords) || count <= 0 || cursor.index + count > preferredWords.length) {
    return null;
  }
  const candidate = preferredWords.slice(cursor.index, cursor.index + count);
  const tokensMatch = candidate.every((word, offset) => wordToken(word) === cleanText(tokens[startIndex + offset]).toLowerCase());
  if (!tokensMatch) return null;
  cursor.index += count;
  return candidate.map((word, offset) => cloneTimedWord(word, tokens[startIndex + offset], {
    id: uniqueId(`${turn.id}-w`),
    manual: true,
    timing_source: "pasted",
    copied_from_word_id: word.id || "",
  }));
}

function synthesizeInsertedWord(token, index, count, left, right, turn) {
  const start = Number(turn.start_sec) || 0;
  const end = Math.max(Number(turn.end_sec) || start + 0.01, start + 0.01);
  const leftBound = Number.isFinite(Number(left)) ? Number(left) : start;
  const rightBound = Number.isFinite(Number(right)) ? Number(right) : end;
  let wordStart;
  let wordEnd;
  if (rightBound > leftBound) {
    const step = Math.max(0.01, (rightBound - leftBound) / (count + 1));
    wordStart = Math.min(rightBound - 0.01, leftBound + step * (index + 1));
    wordEnd = Math.min(rightBound, wordStart + step);
  } else {
    wordStart = leftBound;
    wordEnd = wordStart + 0.01;
  }

  return {
    id: uniqueId(`${turn.id}-w`),
    text: token,
    start_sec: Number(wordStart.toFixed(3)),
    end_sec: Number(Math.max(wordEnd, wordStart + 0.01).toFixed(3)),
    manual: true,
    timing_source: "inserted",
  };
}

function syncWordsFromText(turn, options = {}) {
  const tokens = cleanText(turn.text).match(/\S+/g) || [];
  const existing = turn.words || [];
  if (!tokens.length) {
    if (existing.length) {
      turn.deletedWordSlots = [{ index: 0, words: existing.map((word) => ({ ...word })) }];
    }
    turn.words = [];
    return;
  }
  if (!existing.length) {
    const deletedSlot = Array.isArray(turn.deletedWordSlots)
      ? turn.deletedWordSlots.find((slot) => slot.index === 0 && Array.isArray(slot.words) && slot.words.length)
      : null;
    if (deletedSlot) {
      const firstDeleted = deletedSlot.words[0];
      const lastDeleted = deletedSlot.words[deletedSlot.words.length - 1];
      const intervalStart = numberOr(firstDeleted.start_sec, Number(turn.start_sec) || 0);
      const intervalEnd = Math.max(numberOr(lastDeleted.end_sec, intervalStart + 0.01), intervalStart + 0.01);
      turn.words = splitTimedInterval(tokens, 0, tokens.length, intervalStart, intervalEnd, turn, "inherited", deletedSlot.words);
      turn.deletedWordSlots = [];
    } else {
      turn.words = wordsFromText(turn.text, Number(turn.start_sec) || 0, Number(turn.end_sec) || 0, turn.id);
    }
    return;
  }

  const pairs = wordAlignmentPairs(existing, tokens);
  const nextWords = Array(tokens.length).fill(null);
  const carriedDeletedSlots = Array.isArray(turn.deletedWordSlots) ? turn.deletedWordSlots.slice() : [];
  const nextDeletedSlots = [];
  for (const pair of pairs) {
    nextWords[pair.newIndex] = cloneTimedWord(pair.word, tokens[pair.newIndex]);
  }

  const anchors = [
    { oldIndex: -1, newIndex: -1, word: null },
    ...pairs,
    { oldIndex: existing.length, newIndex: tokens.length, word: null },
  ];
  const preferredCursor = { index: 0 };

  for (let anchorIndex = 0; anchorIndex < anchors.length - 1; anchorIndex += 1) {
    const previous = anchors[anchorIndex];
    const next = anchors[anchorIndex + 1];
    const oldStart = previous.oldIndex + 1;
    const oldEnd = next.oldIndex;
    const newStart = previous.newIndex + 1;
    const newEnd = next.newIndex;
    const oldGap = existing.slice(oldStart, oldEnd);
    const newCount = Math.max(0, newEnd - newStart);
    if (!newCount) {
      if (oldGap.length) {
        nextDeletedSlots.push({ index: newStart, words: oldGap.map((word) => ({ ...word })) });
      }
      continue;
    }

    const pasted = takePreferredWords(options.preferredWords, preferredCursor, tokens, newStart, newCount, turn);
    if (pasted) {
      pasted.forEach((word, offset) => {
        nextWords[newStart + offset] = word;
      });
      continue;
    }

    if (oldGap.length) {
      const firstOld = oldGap[0];
      const lastOld = oldGap[oldGap.length - 1];
      const intervalStart = numberOr(firstOld.start_sec, Number(turn.start_sec) || 0);
      const intervalEnd = Math.max(numberOr(lastOld.end_sec, intervalStart + 0.01), intervalStart + 0.01);
      const inherited = splitTimedInterval(tokens, newStart, newCount, intervalStart, intervalEnd, turn, "inherited", oldGap);
      inherited.forEach((word, offset) => {
        nextWords[newStart + offset] = word;
      });
      continue;
    }

    if (!oldGap.length) {
      const deletedSlotIndex = carriedDeletedSlots.findIndex((slot) => slot.index === newStart && Array.isArray(slot.words) && slot.words.length);
      if (deletedSlotIndex >= 0) {
        const deletedWords = carriedDeletedSlots.splice(deletedSlotIndex, 1)[0].words;
        const firstDeleted = deletedWords[0];
        const lastDeleted = deletedWords[deletedWords.length - 1];
        const intervalStart = numberOr(firstDeleted.start_sec, Number(turn.start_sec) || 0);
        const intervalEnd = Math.max(numberOr(lastDeleted.end_sec, intervalStart + 0.01), intervalStart + 0.01);
        const inherited = splitTimedInterval(tokens, newStart, newCount, intervalStart, intervalEnd, turn, "inherited", deletedWords);
        inherited.forEach((word, offset) => {
          nextWords[newStart + offset] = word;
        });
        continue;
      }
    }

    const left = previous.word ? Number(previous.word.end_sec) : Number(turn.start_sec) || 0;
    const right = next.word ? Number(next.word.start_sec) : Math.max(Number(turn.end_sec) || left + 0.01, left + 0.01);
    for (let offset = 0; offset < newCount; offset += 1) {
      nextWords[newStart + offset] = synthesizeInsertedWord(tokens[newStart + offset], offset, newCount, left, right, turn);
    }
  }

  turn.words = nextWords.filter(Boolean);
  turn.deletedWordSlots = [...carriedDeletedSlots, ...nextDeletedSlots].slice(-20);
}

function textFromWords(words) {
  return words.map((word) => word.text).join(" ").replace(/\s+([,.;:!?])/g, "$1").trim();
}

function normalizePlaybackRate(value) {
  const rate = Number(value);
  if (!Number.isFinite(rate) || rate < 0.5 || rate > 2) return null;
  const stepped = Math.round(rate * 4) / 4;
  return Number(Math.max(0.5, Math.min(2, stepped)).toFixed(2));
}

function clonePayload(value) {
  return JSON.parse(JSON.stringify(value));
}

function revisionWords(words = []) {
  return (words || []).map((word) => ({
    id: word.id,
    text: word.text,
    start_sec: numberOr(word.start_sec, 0),
    end_sec: numberOr(word.end_sec, numberOr(word.start_sec, 0) + 0.01),
    manual: Boolean(word.manual),
    timing_source: cleanText(word.timing_source || ""),
    copied_from_word_id: cleanText(word.copied_from_word_id || ""),
    inherited_from_word_id: cleanText(word.inherited_from_word_id || ""),
  }));
}

function revisionTurnState(turn) {
  if (!turn) return {};
  return {
    id: turn.id,
    label: turn.label,
    start_sec: numberOr(turn.start_sec, 0),
    end_sec: numberOr(turn.end_sec, 0),
    text: turn.text,
    bookmarked: Boolean(turn.bookmarked),
    unclear_intro: Boolean(turn.unclear_intro),
    playbackRate: turn.playbackRate || null,
    timingReliable: turn.timingReliable !== false,
    words: revisionWords(turn.words),
  };
}

function revisionEditorState() {
  return {
    version: 1,
    name: state.sessionName,
    speakers: normalizeSpeakerList(state.speakers),
    finished: state.finished,
    turns: state.turns.map(revisionTurnState),
  };
}

function pushRevisionEvent(kind, before = {}, after = {}, meta = {}) {
  if (!state.sessionName) return;
  const turnIds = new Set();
  const wordIds = new Set();
  for (const payload of [before, after]) {
    const turns = Array.isArray(payload.turns) ? payload.turns : (payload.id ? [payload] : []);
    for (const turn of turns) {
      if (turn.id) turnIds.add(turn.id);
      for (const word of turn.words || []) {
        if (word.id) wordIds.add(word.id);
      }
    }
  }
  state.pendingRevisionEvents.push({
    event_id: uniqueId("revision"),
    created_at: new Date().toISOString(),
    session: state.sessionName,
    kind,
    audio_time_sec: currentAudioTime(),
    turn_ids: Array.from(turnIds),
    word_ids: Array.from(wordIds),
    before,
    after,
    meta,
  });
}

function snapshotState() {
  return {
    turns: clonePayload(state.turns),
    speakers: clonePayload(state.speakers),
    activeTurnId: state.activeTurnId,
    finished: state.finished,
    lastSpeakerChange: state.lastSpeakerChange ? { ...state.lastSpeakerChange } : null,
  };
}

function turnPatchSnapshot(startIndex, removeCount, turns, activeTurnId = state.activeTurnId) {
  return {
    type: "turn_patch",
    startIndex: Math.max(0, Number(startIndex) || 0),
    removeCount: Math.max(0, Number(removeCount) || 0),
    turns: clonePayload(turns || []),
    speakers: clonePayload(state.speakers),
    activeTurnId,
    finished: state.finished,
    lastSpeakerChange: state.lastSpeakerChange ? { ...state.lastSpeakerChange } : null,
  };
}

function inverseHistorySnapshot(snapshot) {
  if (snapshot?.type !== "turn_patch") return snapshotState();
  const startIndex = Math.max(0, Math.min(Number(snapshot.startIndex) || 0, state.turns.length));
  const removeCount = Math.max(0, Number(snapshot.removeCount) || 0);
  const currentTurns = state.turns.slice(startIndex, startIndex + removeCount);
  return turnPatchSnapshot(startIndex, (snapshot.turns || []).length, currentTurns);
}

function pushUndoSnapshot(snapshot) {
  if (state.restoringHistory) return;
  state.undoStack.push(snapshot);
  if (state.undoStack.length > 80) {
    state.undoStack.shift();
  }
  state.redoStack = [];
}

function recordUndo() {
  pushUndoSnapshot(snapshotState());
}

function recordTurnPatchUndo(startIndex, removeCount, turns, activeTurnId = state.activeTurnId) {
  pushUndoSnapshot(turnPatchSnapshot(startIndex, removeCount, turns, activeTurnId));
}

function turnsHaveSameOrder(leftTurns = [], rightTurns = []) {
  return leftTurns.length === rightTurns.length
    && leftTurns.every((turn, index) => turn.id && turn.id === rightTurns[index]?.id);
}

function changedTurnIds(beforeTurns = [], afterTurns = []) {
  const ids = [];
  beforeTurns.forEach((turn, index) => {
    if (JSON.stringify(revisionTurnState(turn)) !== JSON.stringify(revisionTurnState(afterTurns[index]))) {
      ids.push(afterTurns[index]?.id || turn.id);
    }
  });
  return ids.filter(Boolean);
}

function renderChangedTurnsPatch(beforeTurns = [], afterTurns = [], activeTurnId = "") {
  if (state.showBookmarkedOnly || !turnsHaveSameOrder(beforeTurns, afterTurns)) return false;
  const changedIds = changedTurnIds(beforeTurns, afterTurns);
  if (!changedIds.length) {
    setActiveTurn(activeTurnId || state.activeTurnId, { smooth: true });
    return true;
  }
  if (!changedIds.every((turnId) => turnRowForId(turnId))) return false;
  const scrollTarget = activeTurnId || changedIds[0];
  changedIds.forEach((turnId) => {
    const turn = turnById(turnId);
    if (turn) renderSingleTurnPatch(turn);
  });
  setActiveTurn(scrollTarget, { smooth: true });
  return true;
}

function restoreSnapshot(snapshot, label) {
  if (!snapshot) return;
  state.restoringHistory = true;
  const beforeTurns = state.turns.slice();
  let patchDetails = null;
  if (snapshot.type === "turn_patch") {
    const startIndex = Math.max(0, Math.min(Number(snapshot.startIndex) || 0, state.turns.length));
    const removeCount = Math.max(0, Number(snapshot.removeCount) || 0);
    const turns = clonePayload(snapshot.turns || []).map((turn, offset) => normalizeTurn(turn, startIndex + offset));
    state.turns.splice(startIndex, removeCount, ...turns);
    patchDetails = { startIndex, removeCount, insertedTurns: turns };
  } else {
    state.turns = clonePayload(snapshot.turns || []);
  }
  state.speakers = normalizeSpeakerList(snapshot.speakers);
  state.activeTurnId = snapshot.activeTurnId || state.turns[0]?.id || "";
  state.finished = Boolean(snapshot.finished);
  state.lastSpeakerChange = snapshot.lastSpeakerChange || null;
  state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  state.selectedTurnIds = new Set();
  state.lastSelectedTurnId = "";
  cancelWordRangeSelection();
  state.wordRangeSelect.suppressClick = false;
  state.textEditSnapshotTurnId = "";
  state.restoringHistory = false;
  refreshSearchMatches({ keepIndex: true });
  const patched = patchDetails
    ? (
      renderTurnPatchRestore(
        beforeTurns,
        patchDetails.startIndex,
        patchDetails.removeCount,
        patchDetails.insertedTurns,
        state.activeTurnId,
      )
      || renderChangedTurnsPatch(beforeTurns, state.turns, state.activeTurnId)
    )
    : renderChangedTurnsPatch(beforeTurns, state.turns, state.activeTurnId);
  if (!patched) {
    renderTurns({ scrollActive: true, focusTurnId: state.activeTurnId });
  }
  drawTimeline();
  markDirty(label || "Restored edit");
}

function undoEdit() {
  if (!state.undoStack.length) return;
  const snapshot = state.undoStack.pop();
  state.redoStack.push(inverseHistorySnapshot(snapshot));
  restoreSnapshot(snapshot, "Undo");
}

function redoEdit() {
  if (!state.redoStack.length) return;
  const snapshot = state.redoStack.pop();
  state.undoStack.push(inverseHistorySnapshot(snapshot));
  restoreSnapshot(snapshot, "Redo");
}

function scheduleAutosave(delay = 1800) {
  window.clearTimeout(state.autosaveTimer);
  if (!state.sessionName) return;
  state.autosaveTimer = window.setTimeout(() => {
    if (state.dirty) {
      saveSession({ auto: true }).catch((error) => showErrorNotice(error));
    }
  }, delay);
}

function markDirty() {
  invalidateWordIndex();
  scheduleReviewMetaRefresh();
  if (state.restoringHistory) return;
  state.dirty = true;
  if (state.saving) {
    state.pendingAutosave = true;
  }
  scheduleAutosave();
}

function beginTextRevision(turn) {
  state.textEditRevision = {
    turnId: turn.id,
    before: revisionTurnState(turn),
  };
}

function finishTextRevision(turn, kind = "text_edit", meta = {}) {
  const revision = state.textEditRevision;
  if (!revision || revision.turnId !== turn.id) return;
  state.textEditRevision = null;
  const after = revisionTurnState(turn);
  if (JSON.stringify(revision.before) !== JSON.stringify(after)) {
    pushRevisionEvent(kind, revision.before, after, meta);
  }
}

function currentTurn() {
  return state.turns.find((turn) => turn.id === state.activeTurnId) || null;
}

function turnById(turnId) {
  return state.turns.find((turn) => turn.id === turnId) || null;
}

function bookmarkedTurns() {
  return state.turns.filter((turn) => turn.bookmarked);
}

function visibleReviewTurns() {
  return state.showBookmarkedOnly ? bookmarkedTurns() : state.turns;
}

function selectedTurns() {
  const selected = state.turns.filter((turn) => state.selectedTurnIds.has(turn.id));
  if (selected.length !== state.selectedTurnIds.size) {
    state.selectedTurnIds = new Set(selected.map((turn) => turn.id));
  }
  return selected;
}

function patchTurnSelectionState(turnId) {
  const row = turnRowForId(turnId);
  if (!row) return;
  const selected = state.selectedTurnIds.has(turnId);
  row.classList.toggle("selected", selected);
  const checkbox = row.querySelector(".turn-select-checkbox");
  if (checkbox) checkbox.checked = selected;
}

function updateBulkControls() {
  const selected = selectedTurns();
  const count = selected.length;
  if (els.turnList) {
    els.turnList.classList.toggle("selection-mode", state.turnSelectionMode);
  }
  if (els.toggleTurnSelectionMode) {
    els.toggleTurnSelectionMode.disabled = !state.sessionName;
    els.toggleTurnSelectionMode.classList.toggle("active", state.turnSelectionMode);
    els.toggleTurnSelectionMode.textContent = state.turnSelectionMode ? "Selecting" : "Select";
  }
  [els.openBulkDialog, els.clearTurnSelection].forEach((control) => {
    if (control) control.disabled = count === 0 || !state.sessionName;
  });
  if (els.selectVisibleTurns) {
    els.selectVisibleTurns.hidden = !state.turnSelectionMode;
    els.selectVisibleTurns.disabled = !state.sessionName || visibleReviewTurns().length === 0;
  }
  if (els.clearTurnSelection) {
    els.clearTurnSelection.hidden = !state.turnSelectionMode;
  }
  if (els.openSpeakerDialog) els.openSpeakerDialog.disabled = !state.sessionName;
}

function updateBookmarkControls() {
  const count = bookmarkedTurns().length;
  els.nextBookmark.disabled = count === 0;
  if (els.showBookmarks) {
    els.showBookmarks.disabled = count === 0 && !state.showBookmarkedOnly;
    els.showBookmarks.textContent = state.showBookmarkedOnly ? "All Turns" : `Only Marks${count ? ` (${count})` : ""}`;
    els.showBookmarks.classList.toggle("active", state.showBookmarkedOnly);
  }
  updateBulkControls();
}

function updateFinishedControls() {
  const selectedCount = selectedRecordings().length;
  const selectedFinishedCount = selectedFinishedRecordings().length;
  const selectedReprocessCount = reprocessableRecordings().length;
  els.toggleFinished.disabled = !state.sessionName;
  els.toggleFinished.textContent = state.finished ? "Finished" : "Finish";
  els.toggleFinished.title = state.finished
    ? "Mark current transcript as unfinished"
    : "Mark current transcript as finished";
  els.toggleFinished.classList.toggle("active", state.finished);
  els.exportAllFinished.disabled = selectedFinishedCount === 0;
  els.exportAllFinished.textContent = selectedFinishedCount
    ? `Export Selected (${selectedFinishedCount})`
    : "Export Selected";
  els.clearCache.disabled = selectedCount === 0;
  els.clearCache.textContent = selectedCount ? `Clear Selected (${selectedCount})` : "Clear Selected";
  const selectedRunCount = runnableSelectedRecordings().length;
  if (els.runSelectedRecordings) {
    els.runSelectedRecordings.disabled = selectedRunCount === 0;
    els.runSelectedRecordings.textContent = selectedRunCount
      ? `Run Selected (${selectedRunCount})`
      : "Run Selected";
  }
  [els.reprocessSelectedRecordings, els.reprocessSelectedInProcessing].forEach((button) => {
    if (!button) return;
    button.disabled = selectedReprocessCount === 0;
    button.textContent = selectedReprocessCount
      ? `Reprocess Selected (${selectedReprocessCount})`
      : "Reprocess Selected";
  });
}

async function toggleFinished() {
  if (!state.sessionName) return;
  const before = { finished: state.finished };
  recordUndo();
  state.finished = !state.finished;
  pushRevisionEvent("finished_state", before, { finished: state.finished });
  markDirty();
  renderTurns({ scrollActive: false, scrollAnchorTurnId: state.activeTurnId });
  updateRecordingActions();
  await saveSession();
}

function toggleTurnBookmark(turnId = state.activeTurnId) {
  const turn = state.turns.find((candidate) => candidate.id === turnId);
  if (!turn) return;
  const wasBookmarked = Boolean(turn.bookmarked);
  const marksBeforeToggle = bookmarkedTurns();
  const markIndex = marksBeforeToggle.findIndex((candidate) => candidate.id === turn.id);
  const anchorTurnId = state.showBookmarkedOnly && wasBookmarked && marksBeforeToggle.length > 1
    ? marksBeforeToggle[markIndex + 1]?.id || marksBeforeToggle[markIndex - 1]?.id || turn.id
    : turn.id;
  const before = revisionTurnState(turn);
  const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
  recordTurnPatchUndo(index, 1, [turn], turn.id);
  turn.bookmarked = !turn.bookmarked;
  pushRevisionEvent("bookmark", before, revisionTurnState(turn));
  markDirty();
  if (state.showBookmarkedOnly && !turn.bookmarked && !bookmarkedTurns().length) {
    state.showBookmarkedOnly = false;
  }
  if (state.showBookmarkedOnly && !turn.bookmarked) {
    renderTurns({ scrollActive: false, scrollAnchorTurnId: anchorTurnId });
  } else if (!renderSingleTurnPatch(turn)) {
    renderTurns({ scrollActive: false, scrollAnchorTurnId: anchorTurnId });
  }
  drawTimeline();
}

// Flip the unrelated (non-medical) flag on a set of turns as one undoable edit.
// The export wraps each contiguous flagged run between "[Unrelated start]" and
// "[Unrelated end]" marker lines. Returns how many turns changed.
function setTurnsUnrelated(turns, flag, meta = {}) {
  const changed = turns.filter((turn) => Boolean(turn.unclear_intro) !== Boolean(flag));
  if (!changed.length) return 0;
  const before = { turns: changed.map(revisionTurnState) };
  recordUndo();
  for (const turn of changed) {
    turn.unclear_intro = Boolean(flag);
  }
  pushRevisionEvent("unrelated_mark", before, { turns: changed.map(revisionTurnState) }, {
    unrelated: Boolean(flag),
    ...meta,
  });
  markDirty();
  if (changed.length > 40 || !changed.every((turn) => renderSingleTurnPatch(turn))) {
    renderTurns({ scrollActive: false, scrollAnchorTurnId: changed[0].id });
  }
  return changed.length;
}

function clearUnrelatedPending(options = {}) {
  if (!state.unrelatedPending) return false;
  const pendingTurn = turnById(state.unrelatedPending);
  state.unrelatedPending = "";
  els.turnList.classList.remove("unrelated-pending-mode");
  if (pendingTurn) renderSingleTurnPatch(pendingTurn);
  return true;
}

// Start/end marking of an unrelated (non-medical) section, driven by N or the
// row pill: the first press sets the start turn, the next press on the end turn
// flags everything in between. Pressing on an already-marked turn unmarks its
// whole contiguous section instead.
function markUnrelatedSpan(turnId = state.activeTurnId) {
  const turn = turnById(turnId);
  if (!turn) return;
  clearDeletePending({ silent: true });
  if (state.unrelatedPending && !turnById(state.unrelatedPending)) {
    clearUnrelatedPending({ silent: true });
  }

  const pendingTurn = turnById(state.unrelatedPending);
  if (pendingTurn && pendingTurn.id === turn.id) {
    clearUnrelatedPending();
    return;
  }
  if (pendingTurn) {
    const startIndex = state.turns.findIndex((candidate) => candidate.id === pendingTurn.id);
    const endIndex = state.turns.findIndex((candidate) => candidate.id === turn.id);
    state.unrelatedPending = "";
    els.turnList.classList.remove("unrelated-pending-mode");
    const [from, to] = startIndex <= endIndex ? [startIndex, endIndex] : [endIndex, startIndex];
    const span = state.turns.slice(from, to + 1);
    const count = setTurnsUnrelated(span, true, {
      scope: "span",
      start_turn_id: pendingTurn.id,
      end_turn_id: turn.id,
    });
    renderSingleTurnPatch(pendingTurn);
    return;
  }

  if (turn.unclear_intro) {
    const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
    let from = index;
    let to = index;
    while (from > 0 && state.turns[from - 1].unclear_intro) from -= 1;
    while (to < state.turns.length - 1 && state.turns[to + 1].unclear_intro) to += 1;
    const run = state.turns.slice(from, to + 1);
    setTurnsUnrelated(run, false, { scope: "run" });
    return;
  }

  state.unrelatedPending = turn.id;
  els.turnList.classList.add("unrelated-pending-mode");
  renderSingleTurnPatch(turn);
}

function clearDeletePending(options = {}) {
  if (!state.deletePending) return false;
  const pendingTurn = turnById(state.deletePending);
  state.deletePending = "";
  els.turnList.classList.remove("delete-pending-mode");
  if (pendingTurn) renderSingleTurnPatch(pendingTurn);
  return true;
}

// Confirmation for destructive turn removal: shows the covered time span, the
// speaker mix, and each doomed turn's number, time, and text, so a mis-aimed
// span is caught before it deletes half the visit.
const DELETE_PREVIEW_MAX_ROWS = 40;
async function confirmTurnDeletion(turns) {
  if (!turns.length) return false;
  const first = turns[0];
  const last = turns[turns.length - 1];
  const spanEnd = Number(last.end_sec) || Number(last.start_sec) || 0;
  const turnIndexById = new Map(state.turns.map((candidate, index) => [candidate.id, index]));
  const confirmed = await showFormModal({
    title: `Delete ${turns.length} turn${turns.length === 1 ? "" : "s"}?`,
    message: `${formatTime(first.start_sec)} - ${formatTime(spanEnd)} · ${speakerCounts(turns)}`,
    confirmText: "Delete",
    danger: true,
    build: (body) => {
      const note = document.createElement("div");
      note.className = "modal-note";
      note.textContent = "Removed turns. Ctrl+Z restores them.";
      const list = document.createElement("div");
      list.className = "delete-preview";
      for (const doomed of turns.slice(0, DELETE_PREVIEW_MAX_ROWS)) {
        const row = document.createElement("div");
        row.className = "delete-preview-row";
        const meta = document.createElement("span");
        meta.className = "delete-preview-meta";
        const turnIndex = turnIndexById.get(doomed.id);
        meta.textContent = `#${turnIndex >= 0 ? turnIndex + 1 : "?"} · ${formatTime(doomed.start_sec)} · ${speakerLabel(doomed.label)}`;
        const text = document.createElement("span");
        text.className = "delete-preview-text";
        text.textContent = cleanText(doomed.text) || "(no text)";
        text.title = cleanText(doomed.text);
        row.append(meta, text);
        list.append(row);
      }
      if (turns.length > DELETE_PREVIEW_MAX_ROWS) {
        const more = document.createElement("div");
        more.className = "modal-note";
        more.textContent = `…and ${turns.length - DELETE_PREVIEW_MAX_ROWS} more turns not shown`;
        list.append(more);
      }
      body.append(note, list);
    },
  });
  return Boolean(confirmed);
}

// Two-press deletion of a span of turns, driven by X or the row pill: the first
// press picks the start turn, the next press on the end turn shows a
// confirmation listing everything in between, then deletes it (undoable with
// Ctrl+Z). Same interaction as marking unrelated, but the turns are removed
// instead of flagged.
async function deleteTurnSpan(turnId = state.activeTurnId) {
  const turn = turnById(turnId);
  if (!turn) return;
  clearUnrelatedPending({ silent: true });
  if (state.deletePending && !turnById(state.deletePending)) {
    clearDeletePending({ silent: true });
  }

  const pendingTurn = turnById(state.deletePending);
  if (pendingTurn && pendingTurn.id === turn.id) {
    clearDeletePending();
    return;
  }
  if (pendingTurn) {
    const startIndex = state.turns.findIndex((candidate) => candidate.id === pendingTurn.id);
    const endIndex = state.turns.findIndex((candidate) => candidate.id === turn.id);
    state.deletePending = "";
    els.turnList.classList.remove("delete-pending-mode");
    const [from, to] = startIndex <= endIndex ? [startIndex, endIndex] : [endIndex, startIndex];
    const span = state.turns.slice(from, to + 1);
    if (!(await confirmTurnDeletion(span))) {
      renderSingleTurnPatch(pendingTurn);
      return;
    }
    deleteTurns(span, {
      scope: "span",
      start_turn_id: pendingTurn.id,
      end_turn_id: turn.id,
    });
    return;
  }

  state.deletePending = turn.id;
  els.turnList.classList.add("delete-pending-mode");
  renderSingleTurnPatch(turn);
}

function goToNextBookmark() {
  const marks = bookmarkedTurns();
  if (!marks.length) {
    return;
  }
  const activeIndex = state.turns.findIndex((turn) => turn.id === state.activeTurnId);
  const next = marks.find((turn) => state.turns.indexOf(turn) > activeIndex) || marks[0];
  setActiveTurn(next.id);
}

function toggleBookmarkFilter() {
  const marks = bookmarkedTurns();
  if (!state.showBookmarkedOnly && !marks.length) {
    return;
  }
  state.showBookmarkedOnly = !state.showBookmarkedOnly;
  if (state.showBookmarkedOnly && !state.turns.find((turn) => turn.id === state.activeTurnId)?.bookmarked) {
    state.activeTurnId = marks[0]?.id || "";
  }
  renderTurns();
}

function removeTurnIfEmpty(turnId, options = {}) {
  const index = state.turns.findIndex((turn) => turn.id === turnId);
  if (index < 0) return false;
  const turn = state.turns[index];
  const hasText = cleanText(turn.text);
  const hasWords = (turn.words || []).some((word) => cleanText(word.text));
  if (hasText || hasWords) return false;

  const before = revisionTurnState(turn);
  recordUndo();
  const anchorTurnId = state.turns[index + 1]?.id || state.turns[index - 1]?.id || "";
  state.turns.splice(index, 1);
  if (state.activeTurnId === turnId) {
    state.activeTurnId = anchorTurnId;
  }
  if (state.selection.turnId === turnId) {
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  }
  pushRevisionEvent("delete_empty_turn", before, {});
  markDirty();
  if (options.render !== false) renderTurns({ scrollActive: false, scrollAnchorTurnId: anchorTurnId });
  return true;
}

function turnRowForId(turnId) {
  if (!turnId) return null;
  return els.turnList.querySelector(`.turn-row[data-turn-id="${CSS.escape(turnId)}"]`);
}

function topVisibleTurnRow() {
  const listRect = els.turnList.getBoundingClientRect();
  const rows = Array.from(els.turnList.querySelectorAll(".turn-row"));
  return rows.find((row) => row.getBoundingClientRect().bottom >= listRect.top) || rows[0] || null;
}

function captureTurnListScroll(anchorTurnId = "") {
  const anchorRow = turnRowForId(anchorTurnId) || topVisibleTurnRow();
  const listRect = els.turnList.getBoundingClientRect();
  const anchorRect = anchorRow?.getBoundingClientRect();
  return {
    top: els.turnList.scrollTop,
    left: els.turnList.scrollLeft,
    anchorTurnId: anchorRow?.dataset.turnId || "",
    anchorOffsetTop: anchorRect ? anchorRect.top - listRect.top : null,
  };
}

function restoreTurnListScroll(snapshot) {
  if (!snapshot) return;
  const previousBehavior = els.turnList.style.scrollBehavior;
  els.turnList.style.scrollBehavior = "auto";
  try {
    markProgrammaticTurnScroll();
    const anchorRow = turnRowForId(snapshot.anchorTurnId);
    if (anchorRow && snapshot.anchorOffsetTop != null) {
      const listRect = els.turnList.getBoundingClientRect();
      const anchorRect = anchorRow.getBoundingClientRect();
      els.turnList.scrollTop += anchorRect.top - listRect.top - snapshot.anchorOffsetTop;
    } else {
      els.turnList.scrollTop = snapshot.top;
    }
    const maxTop = Math.max(0, els.turnList.scrollHeight - els.turnList.clientHeight);
    const maxLeft = Math.max(0, els.turnList.scrollWidth - els.turnList.clientWidth);
    els.turnList.scrollTop = Math.min(Math.max(0, els.turnList.scrollTop), maxTop);
    els.turnList.scrollLeft = Math.min(Math.max(0, snapshot.left), maxLeft);
  } finally {
    els.turnList.style.scrollBehavior = previousBehavior;
  }
}

// Jump the turn list back to the top instantly (bypassing the CSS smooth
// scrolling). Opening a transcript must never inherit the scroll position left
// over from the previously reviewed one.
function resetTurnListScroll() {
  const previousBehavior = els.turnList.style.scrollBehavior;
  els.turnList.style.scrollBehavior = "auto";
  markProgrammaticTurnScroll();
  els.turnList.scrollTop = 0;
  els.turnList.scrollLeft = 0;
  els.turnList.style.scrollBehavior = previousBehavior;
  resetPlaybackAutoScrollTarget();
}

function resetPlaybackAutoScrollTarget() {
  state.reviewAutoScroll.pendingTurnId = "";
  state.reviewAutoScroll.pendingSince = 0;
  state.reviewAutoScroll.lastAutoTurnId = "";
}

function markProgrammaticTurnScroll() {
  state.reviewAutoScroll.programmaticUntil = performance.now() + PROGRAMMATIC_SCROLL_GRACE_MS;
}

function pauseAutoScrollForUser(ms = AUTO_SCROLL_USER_COOLDOWN_MS) {
  state.reviewAutoScroll.userPausedUntil = performance.now() + ms;
  resetPlaybackAutoScrollTarget();
}

function noteTurnListScroll() {
  if (performance.now() < state.reviewAutoScroll.programmaticUntil) return;
  pauseAutoScrollForUser();
}

function pauseAutoScrollForTextFocus() {
  state.reviewAutoScroll.textFocused = true;
  resetPlaybackAutoScrollTarget();
}

function resumeAutoScrollAfterTextFocus() {
  state.reviewAutoScroll.textFocused = false;
  pauseAutoScrollForUser(AUTO_SCROLL_TEXT_EXIT_COOLDOWN_MS);
}

function autoScrollTargetDelayMs() {
  return clampNumber(state.settings.autoScrollDelaySec, 0, 2, AUTO_SCROLL_TARGET_COOLDOWN_MS / 1000) * 1000;
}

function shouldAutoScrollPlayingTurn(turnId) {
  if (!turnId || state.activeTab !== "review") return false;
  const now = performance.now();
  const scroll = state.reviewAutoScroll;
  if (scroll.textFocused || now < scroll.userPausedUntil) return false;
  if (scroll.lastAutoTurnId === turnId) return false;
  if (scroll.pendingTurnId !== turnId) {
    scroll.pendingTurnId = turnId;
    scroll.pendingSince = now;
    return false;
  }
  if (now - scroll.pendingSince < autoScrollTargetDelayMs()) return false;
  scroll.lastAutoTurnId = turnId;
  return true;
}

function scrollTurnRowIntoFocus(row, options = {}) {
  if (!row) return;
  const listRect = els.turnList.getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  const rowCenter = rowRect.top - listRect.top + (rowRect.height / 2);
  const targetTop = els.turnList.scrollTop + rowCenter - (listRect.height * ACTIVE_TURN_SCROLL_FRACTION);
  const maxTop = Math.max(0, els.turnList.scrollHeight - els.turnList.clientHeight);
  els.turnList.scrollTo({
    top: Math.min(Math.max(0, targetTop), maxTop),
    behavior: options.smooth ? "smooth" : "auto",
  });
}

function setTurnSelected(turnId, selected, options = {}) {
  if (!turnId) return;
  if (options.range && state.lastSelectedTurnId) {
    const visible = visibleReviewTurns();
    const start = visible.findIndex((turn) => turn.id === state.lastSelectedTurnId);
    const end = visible.findIndex((turn) => turn.id === turnId);
    if (start >= 0 && end >= 0) {
      const [from, to] = start <= end ? [start, end] : [end, start];
      visible.slice(from, to + 1).forEach((turn) => state.selectedTurnIds.add(turn.id));
      visible.slice(from, to + 1).forEach((turn) => patchTurnSelectionState(turn.id));
      state.lastSelectedTurnId = turnId;
      updateBulkControls();
      return;
    }
  }
  if (selected) {
    state.selectedTurnIds.add(turnId);
    state.lastSelectedTurnId = turnId;
  } else {
    state.selectedTurnIds.delete(turnId);
  }
  patchTurnSelectionState(turnId);
  updateBulkControls();
}

function toggleTurnSelected(turnId, options = {}) {
  setTurnSelected(turnId, !state.selectedTurnIds.has(turnId), options);
}

function toggleTurnSelectionMode() {
  state.turnSelectionMode = !state.turnSelectionMode;
  updateBulkControls();
  // The checkbox column changes the text width, so re-split the lines.
  if (state.turns.length) {
    renderTurns({ scrollActive: false, preserveScroll: true, scrollAnchorTurnId: state.activeTurnId });
  }
}

function clearTurnSelection() {
  const selectedIds = Array.from(state.selectedTurnIds);
  state.selectedTurnIds = new Set();
  state.lastSelectedTurnId = "";
  selectedIds.forEach(patchTurnSelectionState);
  updateBulkControls();
}

function selectVisibleTurns() {
  const visible = visibleReviewTurns();
  visible.forEach((turn) => state.selectedTurnIds.add(turn.id));
  visible.forEach((turn) => patchTurnSelectionState(turn.id));
  state.lastSelectedTurnId = visible[visible.length - 1]?.id || state.lastSelectedTurnId;
  updateBulkControls();
}

function setActiveTurn(turnId, options = {}) {
  state.activeTurnId = turnId || "";
  const turn = currentTurn();
  if (turn) {
    els.activeSpeaker.value = speakerLabel(turn.label);
    if (options.seek) {
      setAudioTime(turn.start_sec);
    }
  }
  renderSelectionMeta(turn);
  // Only one row is ever "active", so track it instead of scanning every row
  // each call (this runs ~60x/sec during playback). createTurnRow never sets the
  // class, so a fresh lookup of the current row is the single source of truth.
  const previousRow = state.activeRowEl;
  const activeRow = turnId ? turnRowForId(turnId) : null;
  if (previousRow && previousRow !== activeRow) previousRow.classList.remove("active");
  if (activeRow) activeRow.classList.add("active");
  state.activeRowEl = activeRow;
  if (activeRow && options.scroll !== false) {
    markProgrammaticTurnScroll();
    scrollTurnRowIntoFocus(activeRow, { smooth: options.smooth });
  }
  drawTimeline();
  renderTurnProgress();
  applyEffectivePlaybackRate();
  updateBookmarkControls();
}

function renderSpeakerOptions(select, selected) {
  select.replaceChildren();
  const speakers = normalizeSpeakerList(state.speakers);
  const selectedSpeaker = speakerLabel(selected);
  state.speakers = speakers;
  for (const speaker of speakers) {
    const option = document.createElement("option");
    option.value = speaker;
    option.textContent = speaker;
    select.append(option);
  }
  if (selectedSpeaker && !speakers.includes(selectedSpeaker)) {
    const option = document.createElement("option");
    option.value = selectedSpeaker;
    option.textContent = selectedSpeaker;
    select.prepend(option);
  }
  select.value = selectedSpeaker || "Unknown";
}

function renderGlobalSpeakers() {
  renderSpeakerOptions(els.activeSpeaker, currentTurn()?.label || normalizeSpeakerList(state.speakers)[0] || "Unknown");
}

function refreshSpeakerSelectOptions() {
  renderGlobalSpeakers();
  document.querySelectorAll(".turn-speaker").forEach((select) => {
    const turn = turnById(select.closest(".turn-row")?.dataset.turnId);
    if (turn) renderSpeakerOptions(select, turn.label);
  });
}

function ensureSpeaker(label) {
  const speaker = speakerLabel(label);
  if (!state.speakers.includes(speaker)) {
    state.speakers.push(speaker);
  }
  state.speakers = normalizeSpeakerList(state.speakers);
  return speaker;
}

function changeTurnSpeaker(turn, nextLabel, options = {}) {
  if (!turn) return false;
  const previousLabel = speakerLabel(turn.label);
  const speaker = speakerLabel(nextLabel);
  const speakerKnown = state.speakers.includes(speaker);
  if (previousLabel === speaker && speakerKnown) return false;

  const before = revisionTurnState(turn);
  const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
  recordTurnPatchUndo(index, 1, [turn], turn.id);
  ensureSpeaker(speaker);
  if (previousLabel !== speaker) {
    turn.label = speaker;
    state.lastSpeakerChange = { turnId: turn.id, from: previousLabel, to: speaker };
  }
  els.activeSpeaker.value = speaker;
  pushRevisionEvent("speaker_change", before, revisionTurnState(turn), { from: previousLabel, to: speaker });
  markDirty();
  if (!speakerKnown) {
    refreshSpeakerSelectOptions();
  }
  if (!renderSingleTurnPatch(turn, { focusText: options.focusText })) {
    renderTurns({
      scrollActive: false,
      focusTurnId: options.focusText ? turn.id : "",
      scrollAnchorTurnId: turn.id,
    });
  }
  drawTimeline();
  return true;
}

function addSpeakerOnly(nextLabel) {
  const speaker = cleanText(nextLabel);
  if (!speaker) return false;
  if (isDiarizationSpeaker(speaker)) {
    return false;
  }
  const alreadyKnown = state.speakers.includes(speaker);
  if (!alreadyKnown) {
    recordUndo();
    ensureSpeaker(speaker);
    markDirty();
    refreshSpeakerSelectOptions();
  }
  return true;
}

function changeSpeakerScope(nextLabel, scope = "active") {
  const speaker = cleanText(nextLabel);
  if (!speaker) {
    return false;
  }
  if (isDiarizationSpeaker(speaker)) {
    return false;
  }
  const turn = currentTurn();
  if (scope === "add" || !turn) {
    return addSpeakerOnly(speaker);
  }
  if (scope === "active") {
    const changed = changeTurnSpeaker(turn, speaker);
    return changed;
  }

  const from = speakerLabel(turn.label);
  const activeIndex = state.turns.findIndex((candidate) => candidate.id === turn.id);
  const candidates = state.turns.filter((candidate, index) => {
    if (candidate.label !== from) return false;
    return scope === "after" ? index >= activeIndex : true;
  });
  const changedTurns = candidates.filter((candidate) => speakerLabel(candidate.label) !== speaker);
  if (!changedTurns.length) {
    return false;
  }

  const before = { turns: changedTurns.map(revisionTurnState) };
  const speakerKnown = state.speakers.includes(speaker);
  recordUndo();
  ensureSpeaker(speaker);
  for (const candidate of changedTurns) {
    candidate.label = speaker;
  }
  state.lastSpeakerChange = { turnId: turn.id, from, to: speaker };
  pushRevisionEvent("speaker_bulk_change", before, { turns: changedTurns.map(revisionTurnState) }, {
    from,
    to: speaker,
    scope,
  });
  markDirty();
  if (!speakerKnown) refreshSpeakerSelectOptions();
  renderTurns({ scrollActive: false, scrollAnchorTurnId: turn.id });
  drawTimeline();
  return true;
}

function applyBulkSpeakerToSelected(nextLabel) {
  const turns = selectedTurns();
  if (!turns.length) {
    return false;
  }
  const speaker = cleanText(nextLabel);
  if (!speaker) {
    return false;
  }
  if (isDiarizationSpeaker(speaker)) {
    return false;
  }
  const changedTurns = turns.filter((turn) => speakerLabel(turn.label) !== speaker);
  if (!changedTurns.length) {
    return false;
  }

  const before = { turns: changedTurns.map(revisionTurnState) };
  const speakerKnown = state.speakers.includes(speaker);
  recordUndo();
  ensureSpeaker(speaker);
  for (const turn of changedTurns) {
    turn.label = speaker;
  }
  pushRevisionEvent("speaker_bulk_change", before, { turns: changedTurns.map(revisionTurnState) }, {
    to: speaker,
    selected_count: turns.length,
  });
  markDirty();
  if (!speakerKnown) refreshSpeakerSelectOptions();
  renderTurns({ scrollActive: false, scrollAnchorTurnId: changedTurns[0]?.id || state.activeTurnId });
  drawTimeline();
  return true;
}

// Mark/unmark the selected turns as unrelated in one action (reuses unclear_intro).
function applyBulkNonClinicalToSelected(flag) {
  const turns = selectedTurns();
  if (!turns.length) {
    return false;
  }
  const count = setTurnsUnrelated(turns, Boolean(flag), { scope: "bulk", selected_count: turns.length });
  if (!count) {
    return false;
  }
  return true;
}

function deleteTurns(turns, meta = {}) {
  if (!turns.length) return false;
  const selectedIds = new Set(turns.map((turn) => turn.id));
  const firstIndex = state.turns.findIndex((turn) => selectedIds.has(turn.id));
  const before = { turns: turns.map(revisionTurnState) };
  recordUndo();
  state.turns = state.turns.filter((turn) => !selectedIds.has(turn.id));
  const anchorTurn = state.turns[Math.min(Math.max(0, firstIndex), Math.max(0, state.turns.length - 1))] || null;
  state.activeTurnId = selectedIds.has(state.activeTurnId) ? anchorTurn?.id || "" : state.activeTurnId;
  if (state.selection.turnId && selectedIds.has(state.selection.turnId)) {
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  }
  state.selectedTurnIds = new Set();
  state.lastSelectedTurnId = "";
  pushRevisionEvent("delete_turns", before, {}, meta);
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  renderTurns({ scrollActive: false, scrollAnchorTurnId: state.activeTurnId });
  drawTimeline();
  return true;
}

function speakerCounts(turns) {
  const counts = new Map();
  turns.forEach((turn) => counts.set(turn.label, (counts.get(turn.label) || 0) + 1));
  return Array.from(counts.entries())
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([speaker, count]) => `${speaker}: ${count}`)
    .join(", ");
}

function appendSpeakerSelect(parent, selected) {
  const select = document.createElement("select");
  select.className = "modal-field-control";
  renderSpeakerOptions(select, selected);
  parent.append(select);
  return select;
}

function speakerFromDialog(existingSelect, nameInput) {
  return cleanText(nameInput.value) || speakerLabel(existingSelect.value, "");
}

async function openSpeakerDialog() {
  if (!state.sessionName) return;
  const turn = currentTurn();
  const result = await showFormModal({
    title: "Speaker Action",
    message: turn
      ? `Active turn is ${speakerLabel(turn.label)} at ${formatTime(turn.start_sec)}.`
      : "Choose a speaker label to add.",
    confirmText: "Apply",
    build: (body) => {
      const summary = document.createElement("div");
      summary.className = "modal-note";
      summary.textContent = "Choose an existing speaker or type a new one, then choose how broadly to apply it.";

      const existingLabel = document.createElement("label");
      existingLabel.className = "modal-field";
      existingLabel.innerHTML = "<span>Existing speaker</span>";
      const existingSelect = appendSpeakerSelect(existingLabel, turn?.label || state.speakers[0] || "Unknown");

      const nameLabel = document.createElement("label");
      nameLabel.className = "modal-field";
      nameLabel.innerHTML = "<span>New speaker name</span>";
      const nameInput = document.createElement("input");
      nameInput.className = "modal-field-control";
      nameInput.type = "text";
      nameInput.placeholder = "Optional";
      nameLabel.append(nameInput);

      const scopeLabel = document.createElement("label");
      scopeLabel.className = "modal-field";
      scopeLabel.innerHTML = "<span>Action</span>";
      const scopeSelect = document.createElement("select");
      scopeSelect.className = "modal-field-control";
      [
        ["active", "Apply to active turn"],
        ["matching", "Apply to all turns with active turn's current speaker"],
        ["after", "Apply to matching turns from active turn onward"],
        ["add", "Add speaker only"],
      ].forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        scopeSelect.append(option);
      });
      if (!turn) scopeSelect.value = "add";
      scopeLabel.append(scopeSelect);

      body.append(summary, existingLabel, nameLabel, scopeLabel);
      return { existingSelect, nameInput, scopeSelect };
    },
    validate: ({ existingSelect, nameInput, scopeSelect }) => {
      const speaker = speakerFromDialog(existingSelect, nameInput);
      if (!speaker) {
        nameInput.focus();
        return false;
      }
      if (isDiarizationSpeaker(speaker)) {
        nameInput.focus();
        return false;
      }
      return { speaker, scope: scopeSelect.value };
    },
  });
  if (!result) return;
  changeSpeakerScope(result.speaker, result.scope);
}

async function openBulkDialog() {
  const turns = selectedTurns();
  if (!turns.length) {
    return;
  }
  const result = await showFormModal({
    title: "Bulk Change Selected Turns",
    message: `${turns.length} selected turn${turns.length === 1 ? "" : "s"}. ${speakerCounts(turns)}`,
    confirmText: "Apply",
    build: (body) => {
      const summary = document.createElement("div");
      summary.className = "modal-note";
      summary.textContent = "Bulk actions affect only the selected turns in the Review tab.";

      const actionLabel = document.createElement("label");
      actionLabel.className = "modal-field";
      actionLabel.innerHTML = "<span>Action</span>";
      const actionSelect = document.createElement("select");
      actionSelect.className = "modal-field-control";
      [
        ["speaker", "Change selected turns to speaker"],
        ["mark_non_clinical", "Mark selected turns unrelated (non-medical)"],
        ["mark_clinical", "Unmark unrelated for selected turns"],
        ["delete", "Delete selected turns"],
      ].forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        actionSelect.append(option);
      });
      actionLabel.append(actionSelect);

      const speakerLabelElement = document.createElement("label");
      speakerLabelElement.className = "modal-field";
      speakerLabelElement.innerHTML = "<span>Speaker</span>";
      const existingSelect = appendSpeakerSelect(speakerLabelElement, turns[0]?.label || currentTurn()?.label || "Unknown");

      const nameLabel = document.createElement("label");
      nameLabel.className = "modal-field";
      nameLabel.innerHTML = "<span>New speaker name</span>";
      const nameInput = document.createElement("input");
      nameInput.className = "modal-field-control";
      nameInput.type = "text";
      nameInput.placeholder = "Optional";
      nameLabel.append(nameInput);

      const updateDisabled = () => {
        const deleting = actionSelect.value === "delete";
        const speakerAction = actionSelect.value === "speaker";
        existingSelect.disabled = !speakerAction;
        nameInput.disabled = !speakerAction;
        els.modalConfirm.textContent = deleting ? "Delete" : "Apply";
        els.modalConfirm.classList.toggle("modal-confirm-danger", deleting);
      };
      actionSelect.addEventListener("change", updateDisabled);
      updateDisabled();

      body.append(summary, actionLabel, speakerLabelElement, nameLabel);
      return { actionSelect, existingSelect, nameInput };
    },
    validate: ({ actionSelect, existingSelect, nameInput }) => {
      if (actionSelect.value === "delete") return { action: "delete" };
      if (actionSelect.value === "mark_non_clinical") return { action: "mark_non_clinical" };
      if (actionSelect.value === "mark_clinical") return { action: "mark_clinical" };
      const speaker = speakerFromDialog(existingSelect, nameInput);
      if (!speaker) {
        nameInput.focus();
        return false;
      }
      if (isDiarizationSpeaker(speaker)) {
        nameInput.focus();
        return false;
      }
      return { action: "speaker", speaker };
    },
  });
  if (!result) return;
  if (result.action === "delete") {
    if (await confirmTurnDeletion(turns)) deleteTurns(turns, { scope: "bulk" });
  } else if (result.action === "mark_non_clinical") {
    applyBulkNonClinicalToSelected(true);
  } else if (result.action === "mark_clinical") {
    applyBulkNonClinicalToSelected(false);
  } else {
    applyBulkSpeakerToSelected(result.speaker);
  }
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function searchRegex() {
  const query = cleanText(els.searchInput.value);
  if (!query) return null;
  return new RegExp(escapeRegExp(query), "gi");
}

function refreshSearchMatches(options = {}) {
  const query = cleanText(els.searchInput.value);
  state.search.query = query;
  state.search.matches = [];
  if (!query) {
    state.search.index = -1;
    updateSearchCount();
    return;
  }

  const regex = searchRegex();
  for (const turn of state.turns) {
    const text = turn.text || "";
    let match;
    while ((match = regex.exec(text)) !== null) {
      state.search.matches.push({ turnId: turn.id, index: match.index, length: match[0].length });
      if (match[0].length === 0) regex.lastIndex += 1;
    }
  }

  if (!state.search.matches.length) {
    state.search.index = -1;
  } else if (!options.keepIndex || state.search.index < 0 || state.search.index >= state.search.matches.length) {
    state.search.index = 0;
  }
  updateSearchCount();
}

// Debounced variant for per-keystroke editing: a full match rescan over every
// turn on each character is wasted work while the user is still typing.
let searchRefreshTimer = null;
function scheduleSearchRefresh() {
  window.clearTimeout(searchRefreshTimer);
  searchRefreshTimer = window.setTimeout(() => {
    refreshSearchMatches({ keepIndex: true });
  }, SEARCH_REFRESH_DEBOUNCE_MS);
}

function updateSearchCount() {
  const total = state.search.matches.length;
  els.searchCount.hidden = total === 0;
  els.searchCount.textContent = total ? `${state.search.index + 1}/${total}` : "";
  els.searchPrev.disabled = !total;
  els.searchNext.disabled = !total;
  els.replaceOne.disabled = !total;
  els.replaceAll.disabled = !total;
}

function searchHitTurnIds() {
  return new Set(state.search.matches.map((match) => match.turnId));
}

function currentSearchMatch() {
  if (state.search.index < 0) return null;
  return state.search.matches[state.search.index] || null;
}

function goToSearchMatch(delta) {
  if (!state.search.matches.length) return;
  state.search.index = (state.search.index + delta + state.search.matches.length) % state.search.matches.length;
  updateSearchCount();
  const match = currentSearchMatch();
  if (match) {
    setActiveTurn(match.turnId, { smooth: true });
    renderTurns();
  }
}

function replaceCurrentMatch() {
  const match = currentSearchMatch();
  if (!match) return;
  const turn = state.turns.find((candidate) => candidate.id === match.turnId);
  if (!turn) return;
  const before = revisionTurnState(turn);
  recordUndo();
  const replacement = els.replaceInput.value || "";
  turn.text = `${turn.text.slice(0, match.index)}${replacement}${turn.text.slice(match.index + match.length)}`;
  delete turn.editorLineTexts;
  syncWordsFromText(turn);
  pushRevisionEvent("replace_one", before, revisionTurnState(turn), {
    search: state.search.query,
    replacement,
  });
  markDirty();
  refreshSearchMatches();
  renderTurns({ scrollActive: false });
}

function replaceAllMatches() {
  const regex = searchRegex();
  if (!regex) return;
  let changed = 0;
  const beforeTurns = [];
  recordUndo();
  for (const turn of state.turns) {
    regex.lastIndex = 0;
    const nextText = turn.text.replace(regex, () => {
      changed += 1;
      return els.replaceInput.value || "";
    });
    if (nextText !== turn.text) {
      beforeTurns.push(revisionTurnState(turn));
      turn.text = nextText;
      delete turn.editorLineTexts;
      syncWordsFromText(turn);
    }
  }
  if (!changed) {
    state.undoStack.pop();
    return;
  }
  const changedIds = new Set(beforeTurns.map((turn) => turn.id));
  pushRevisionEvent("replace_all", { turns: beforeTurns }, {
    turns: state.turns.filter((turn) => changedIds.has(turn.id)).map(revisionTurnState),
  }, {
    search: state.search.query,
    replacement: els.replaceInput.value || "",
    count: changed,
  });
  markDirty();
  refreshSearchMatches();
  renderTurns({ scrollActive: false });
}

// A shared canvas context configured with the page font: line wrapping and the
// word-strip gaps measure real rendered pixel widths instead of guessing from
// average character counts (which left wide lines a fifth empty).
let cachedTextMeasureContext = null;
function textMeasureContext() {
  if (!cachedTextMeasureContext) {
    const context = document.createElement("canvas").getContext("2d");
    const bodyStyle = window.getComputedStyle(document.body);
    context.font = `${bodyStyle.fontWeight} ${bodyStyle.fontSize} ${bodyStyle.fontFamily}`;
    // An invalid shorthand is silently ignored, leaving the default 10px
    // sans-serif and over-packing every line; verify the size stuck.
    if (!String(context.font).includes(bodyStyle.fontSize)) {
      context.font = `${bodyStyle.fontSize} sans-serif`;
    }
    cachedTextMeasureContext = context;
  }
  return cachedTextMeasureContext;
}

let cachedTurnTextMetrics = null;
function turnTextMetrics() {
  if (!cachedTurnTextMetrics) {
    cachedTurnTextMetrics = {
      spaceWidthPx: textMeasureContext().measureText(" ").width || 3.5,
    };
  }
  return cachedTurnTextMetrics;
}

function turnLineAvailableWidthPx() {
  // While the Review tab is hidden the list measures 0 wide; estimate from the
  // window minus the timeline panel so the first render is close, and rely on
  // setActiveTab("review") re-splitting against the real width once visible.
  const measured = Number(els.turnList?.clientWidth) || 0;
  const width = Math.max(320, measured || (window.innerWidth || 960) - 430);
  const overhead = TURN_ROW_TEXT_OVERHEAD_PX + (state.turnSelectionMode ? TURN_ROW_SELECTION_EXTRA_PX : 0);
  return Math.max(180, width - overhead);
}

function splitLineTextByLimit(text, availablePx = turnLineAvailableWidthPx()) {
  const tokens = cleanText(text).match(/\S+/g) || [];
  if (!tokens.length) return [""];
  const context = textMeasureContext();
  // A few px of slack: the text element is nowrap with hidden overflow, so an
  // over-estimate would clip the line's last characters.
  const maxWidth = availablePx - 6;
  const lines = [];
  let current = "";
  for (const token of tokens) {
    const next = current ? `${current} ${token}` : token;
    if (current && context.measureText(next).width > maxWidth) {
      lines.push(current);
      current = token;
    } else {
      current = next;
    }
  }
  if (current || !lines.length) lines.push(current);
  return lines;
}

function autoTurnLineTexts(turn) {
  const text = cleanText(turn.text);
  return splitLineTextByLimit(text);
}

function turnLineTexts(turn) {
  const explicit = Array.isArray(turn.editorLineTexts)
    ? turn.editorLineTexts.map((line) => cleanText(line))
    : [];
  return explicit.length ? explicit.flatMap((line) => splitLineTextByLimit(line)) : autoTurnLineTexts(turn);
}

function turnLineSegments(turn) {
  const lines = turnLineTexts(turn);
  const words = Array.isArray(turn.words) ? turn.words : [];
  let cursor = 0;
  return lines.map((lineText, lineIndex) => {
    const tokenCount = (cleanText(lineText).match(/\S+/g) || []).length;
    const wordStart = Math.min(cursor, words.length);
    const wordEnd = Math.min(words.length, wordStart + tokenCount);
    cursor = wordEnd;
    return {
      lineIndex,
      text: lineText,
      wordStart,
      wordEnd,
    };
  });
}

function lineTextElementsForBody(body) {
  return Array.from(body.querySelectorAll(".turn-line-text"));
}

function updateTurnFromLineElements(turn, body, syncOptions = {}) {
  if (!body) return;
  const lineTexts = lineTextElementsForBody(body).map((element) => element.textContent || "");
  // Only turns with explicit Shift+Enter breaks keep per-line structure.
  // Persisting the automatic wrap boundaries here froze them as if manual, so
  // later wraps could only split lines and never re-balance words across them.
  if (Array.isArray(turn.editorLineTexts)) {
    turn.editorLineTexts = lineTexts;
  }
  turn.text = cleanText(lineTexts.join(" "));
  syncWordsFromText(turn, syncOptions);
}

function textContentRect(element) {
  if (!element || !element.firstChild || !cleanText(element.textContent)) return null;
  const range = document.createRange();
  range.selectNodeContents(element);
  const rect = range.getBoundingClientRect();
  return rect.width > 0 ? rect : null;
}

function wordStripContentRect(strip) {
  const chips = Array.from(strip?.querySelectorAll(".word-chip") || []);
  if (!chips.length) return null;
  const first = chips[0].getBoundingClientRect();
  const last = chips[chips.length - 1].getBoundingClientRect();
  return {
    left: first.left,
    right: last.right,
    width: Math.max(0, last.right - first.left),
  };
}

const pendingWordStripAlignments = new Map();
let wordStripAlignmentFrame = 0;

function queueWordStripAlignment(textElement, strip) {
  const content = strip?.querySelector(".word-strip-content");
  if (!textElement || !strip || !content) return;
  pendingWordStripAlignments.set(strip, { textElement, strip, content });
  if (wordStripAlignmentFrame) return;

  wordStripAlignmentFrame = requestAnimationFrame(() => {
    wordStripAlignmentFrame = 0;
    const entries = Array.from(pendingWordStripAlignments.values())
      .filter(({ textElement: text, strip: wordStrip }) => text.isConnected && wordStrip.isConnected);
    pendingWordStripAlignments.clear();

    // Reset all transforms, then perform every geometry read before any offset
    // write. This keeps a large transcript to one layout pass instead of one
    // forced layout per rendered line.
    for (const entry of entries) {
      entry.content.style.setProperty("--word-strip-offset", "0px");
    }
    const measurements = entries.map((entry) => ({
      ...entry,
      textRect: textContentRect(entry.textElement),
      stripRect: wordStripContentRect(entry.strip),
    }));
    for (const { content: stripContent, textRect, stripRect } of measurements) {
      if (!textRect || !stripRect || !stripRect.width) continue;
      const maxOffset = WORD_STRIP_TEXT_PADDING_PX - 1;
      const offset = clampNumber(textRect.left - stripRect.left, -maxOffset, maxOffset, 0);
      stripContent.style.setProperty("--word-strip-offset", `${offset.toFixed(2)}px`);
    }
  });
}

function alignWordStripToText(textElement, strip) {
  // Initial rows are built off-DOM. Their visible subset is aligned by the row
  // observer after insertion; measuring every hidden row defeats CSS containment.
  if (!textElement?.isConnected || !strip?.isConnected) return;
  queueWordStripAlignment(textElement, strip);
}

const visibleTurnRows = new Set();
let turnRowVisibilityObserver = null;

function alignTurnRowWordStrips(row) {
  row?.querySelectorAll(".turn-line").forEach((line) => {
    alignWordStripToText(
      line.querySelector(".turn-line-text"),
      line.querySelector(".word-timing-strip"),
    );
  });
}

function ensureTurnRowVisibilityObserver() {
  if (turnRowVisibilityObserver || typeof IntersectionObserver !== "function") {
    return turnRowVisibilityObserver;
  }
  turnRowVisibilityObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting && entry.target.isConnected && entry.target.parentElement === els.turnList) {
        visibleTurnRows.add(entry.target);
        alignTurnRowWordStrips(entry.target);
      } else {
        visibleTurnRows.delete(entry.target);
      }
    }
  }, {
    root: els.turnList,
    rootMargin: "240px 0px",
  });
  return turnRowVisibilityObserver;
}

function observeTurnRow(row) {
  const observer = ensureTurnRowVisibilityObserver();
  if (observer) {
    observer.observe(row);
    return;
  }
  // Compatibility fallback for browsers without IntersectionObserver.
  requestAnimationFrame(() => alignTurnRowWordStrips(row));
}

function unobserveTurnRow(row) {
  if (!row) return;
  turnRowVisibilityObserver?.unobserve(row);
  visibleTurnRows.delete(row);
}

function resetTurnRowObservation() {
  turnRowVisibilityObserver?.disconnect();
  visibleTurnRows.clear();
}

function alignAllWordStrips() {
  for (const row of visibleTurnRows) alignTurnRowWordStrips(row);
}

// Redistribute the word bars from the lines as they exist in the DOM: while
// typing, the visible line texts are the source of truth (they may differ from
// the computed re-split until the next rewrap), so counting tokens per DOM line
// keeps every bar under the line that actually shows its word.
function rerenderTurnLineBars(body, turn) {
  const words = turn.words || [];
  let cursor = 0;
  body.querySelectorAll(".turn-line").forEach((line) => {
    const text = line.querySelector(".turn-line-text");
    const strip = line.querySelector(".word-timing-strip");
    if (!text || !strip) return;
    const wordStart = Math.min(cursor, words.length);
    const wordEnd = Math.min(words.length, wordStart + tokenCount(text.textContent || ""));
    cursor = wordEnd;
    renderWordStrip(strip, turn, { words: words.slice(wordStart, wordEnd), wordOffset: wordStart });
    alignWordStripToText(text, strip);
  });
}

function setCaretOffset(element, offset = 0) {
  element.focus({ preventScroll: true });
  const selection = window.getSelection();
  if (!selection) return;
  const textNode = element.firstChild && element.firstChild.nodeType === Node.TEXT_NODE
    ? element.firstChild
    : element.appendChild(document.createTextNode(""));
  const safeOffset = Math.max(0, Math.min(textNode.textContent.length, offset));
  const range = document.createRange();
  range.setStart(textNode, safeOffset);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function turnOffsetFromLineCaret(element) {
  const body = element.closest(".turn-body");
  const lineElements = body ? lineTextElementsForBody(body) : [element];
  const lineIndex = lineElements.indexOf(element);
  const previousLength = lineElements
    .slice(0, Math.max(0, lineIndex))
    .reduce((total, line) => total + cleanText(line.textContent).length + 1, 0);
  return previousLength + getCaretOffset(element);
}

function turnWordSplitIndexForLine(lineElements, lineIndex, offset) {
  const beforeLineCount = lineElements
    .slice(0, Math.max(0, lineIndex))
    .reduce((total, line) => total + tokenCount(line.textContent || ""), 0);
  const currentText = lineElements[lineIndex]?.textContent || "";
  return beforeLineCount + tokenCount(currentText.slice(0, offset));
}

function textSplitAtLineCaret(element) {
  const body = element.closest(".turn-body");
  if (!body) return null;
  const lineElements = lineTextElementsForBody(body);
  const lineIndex = lineElements.indexOf(element);
  if (lineIndex < 0) return null;
  const offset = getCaretOffset(element);
  const lineTexts = lineElements.map((line) => line.textContent || "");
  const currentText = lineTexts[lineIndex] || "";
  return {
    body,
    lineElements,
    lineIndex,
    offset,
    before: cleanText([...lineTexts.slice(0, lineIndex), currentText.slice(0, offset)].join(" ")),
    after: cleanText([currentText.slice(offset), ...lineTexts.slice(lineIndex + 1)].join(" ")),
    wordSplitIndex: turnWordSplitIndexForLine(lineElements, lineIndex, offset),
  };
}

function renderTurnLine(body, turn, segment) {
  const line = document.createElement("div");
  line.className = "turn-line";
  line.dataset.lineIndex = String(segment.lineIndex);

  const text = document.createElement("div");
  text.className = "turn-text turn-line-text";
  text.contentEditable = "true";
  text.spellcheck = true;
  text.textContent = segment.text || "";
  text.dataset.lineIndex = String(segment.lineIndex);
  text.dataset.wordStart = String(segment.wordStart);
  text.dataset.wordEnd = String(segment.wordEnd);

  const wordStrip = document.createElement("div");
  wordStrip.className = "word-strip word-timing-strip";
  renderWordStrip(wordStrip, turn, {
    words: turn.words.slice(segment.wordStart, segment.wordEnd),
    wordOffset: segment.wordStart,
  });

  text.addEventListener("click", (event) => event.stopPropagation());
  text.addEventListener("focus", () => {
    pauseAutoScrollForTextFocus();
    setActiveTurn(turn.id, { scroll: false });
    if (rewrapFocusTurnId === turn.id) {
      // Continuation of the same edit after a live rewrap; keep the current
      // undo snapshot and revision instead of starting new ones.
      rewrapFocusTurnId = "";
      beginTextEditPlayback();
      return;
    }
    state.textEditSnapshotTurnId = "";
    beginTextRevision(turn);
    beginTextEditPlayback();
  });
  text.addEventListener("input", (event) => {
    if (state.textEditSnapshotTurnId !== turn.id) {
      const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
      recordTurnPatchUndo(index, 1, [turn], turn.id);
      state.textEditSnapshotTurnId = turn.id;
    }
    if (!state.textEditRevision || state.textEditRevision.turnId !== turn.id) {
      beginTextRevision(turn);
    }
    updateTurnFromLineElements(turn, body);
    scheduleSearchRefresh();
    if (maybeRewrapTurnLines(body, turn, text, event)) {
      markDirty();
      return;
    }
    rerenderTurnLineBars(body, turn);
    markDirty();
  });
  text.addEventListener("paste", (event) => onTurnPaste(event, turn, text, body));
  text.addEventListener("blur", () => {
    if (text.dataset.skipBlurSync === "true") {
      delete text.dataset.skipBlurSync;
      state.textEditSnapshotTurnId = "";
      endTextEditPlayback();
      resumeAutoScrollAfterTextFocus();
      return;
    }
    state.textEditSnapshotTurnId = "";
    updateTurnFromLineElements(turn, body);
    finishTextRevision(turn);
    endTextEditPlayback();
    resumeAutoScrollAfterTextFocus();
    renderTurnLines(body, turn);
    removeTurnIfEmpty(turn.id);
  });
  text.addEventListener("keydown", (event) => onTurnKeydown(event, turn, text));

  line.append(text, wordStrip);
  body.append(line);
  alignWordStripToText(text, wordStrip);
}

function renderTurnLines(body, turn) {
  body.replaceChildren();
  const segments = turnLineSegments(turn);
  const safeSegments = segments.length ? segments : [{ lineIndex: 0, text: "", wordStart: 0, wordEnd: 0 }];
  safeSegments.forEach((segment, index) => renderTurnLine(body, turn, { ...segment, lineIndex: index }));
}

// Set when a live rewrap re-focuses the caret's new line element, so the focus
// handler continues the in-progress edit instead of starting a fresh undo
// snapshot and revision.
let rewrapFocusTurnId = "";

function cleanedCaretOffset(element) {
  const raw = element.textContent || "";
  return cleanText(raw.slice(0, getCaretOffset(element))).length;
}

// Re-split the turn's lines while the user types, so an overlong line flows
// into the next one immediately (word-processor style) instead of growing
// off-screen until blur. Returns true when the body was re-rendered.
function maybeRewrapTurnLines(body, turn, element, event) {
  if (event?.isComposing) return false;
  const lineElements = lineTextElementsForBody(body);
  const domLines = lineElements.map((line) => cleanText(line.textContent));
  const computedLines = turnLineTexts(turn);
  if (computedLines.length === domLines.length && computedLines.every((line, index) => line === domLines[index])) {
    return false;
  }
  // Defer while the character before the caret is whitespace: rewrapping
  // normalizes spaces, which would swallow the separator being typed.
  const raw = element.textContent || "";
  const rawOffset = getCaretOffset(element);
  if (rawOffset > 0 && /\s/.test(raw[rawOffset - 1] || "")) return false;

  const lineIndex = Math.max(0, lineElements.indexOf(element));
  const globalOffset = domLines
    .slice(0, lineIndex)
    .reduce((total, line) => total + line.length + 1, 0) + cleanedCaretOffset(element);

  renderTurnLines(body, turn);

  const nextLines = lineTextElementsForBody(body);
  let remaining = globalOffset;
  let target = nextLines[0] || null;
  for (let index = 0; index < nextLines.length; index += 1) {
    const length = cleanText(nextLines[index].textContent).length;
    target = nextLines[index];
    if (remaining <= length || index === nextLines.length - 1) break;
    remaining -= length + 1;
  }
  if (target) {
    rewrapFocusTurnId = turn.id;
    setCaretOffset(target, Math.max(0, remaining));
  }
  return true;
}

function createTurnRow(turn, context = {}) {
  const hitTurnIds = context.hitTurnIds || new Set();
  const activeMatch = context.activeMatch || null;
  const turnIndex = context.turnIndexById?.get(turn.id) ?? state.turns.findIndex((candidate) => candidate.id === turn.id);
  const row = document.createElement("div");
  row.className = `turn-row ${roleClass(turn.label)}`;
  if (turn.bookmarked) row.classList.add("bookmarked");
  if (turn.unclear_intro) row.classList.add("unrelated");
  if (state.unrelatedPending === turn.id) row.classList.add("unrelated-pending");
  if (state.deletePending === turn.id) row.classList.add("delete-pending");
  if (state.selectedTurnIds.has(turn.id)) row.classList.add("selected");
  if (hitTurnIds.has(turn.id)) row.classList.add("search-hit");
  if (activeMatch?.turnId === turn.id) row.classList.add("active-search-hit");
  row.dataset.turnId = turn.id;
  row.style.setProperty("--speaker-color", speakerColor(turn.label));
  row.addEventListener("click", (event) => {
    if (event.target.closest("button, select, input, .turn-text, .word-strip")) return;
    setActiveTurn(turn.id, { scroll: false });
    if (state.turnSelectionMode) {
      toggleTurnSelected(turn.id, { range: event.shiftKey });
      return;
    }
    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      toggleTurnSelected(turn.id, { range: event.shiftKey });
      return;
    }
    if (state.settings.clickTurnPlays) playTurn(turn);
  });
  row.addEventListener("dragover", onRowDragOver);
  row.addEventListener("dragleave", () => row.classList.remove("drop-target"));
  row.addEventListener("drop", (event) => onDropWords(event, turn.id, turn.words.length));

  const turnNumber = document.createElement("button");
  turnNumber.type = "button";
  turnNumber.className = "turn-number";
  turnNumber.textContent = turnIndex >= 0 ? String(turnIndex + 1) : "";
  turnNumber.title = turnIndex >= 0 ? `Turn ${turnIndex + 1}` : "Turn";
  turnNumber.addEventListener("click", (event) => {
    event.stopPropagation();
    setActiveTurn(turn.id);
    if (state.settings.clickTurnPlays) playTurn(turn);
  });

  const selectCheckbox = document.createElement("input");
  selectCheckbox.type = "checkbox";
  selectCheckbox.className = "turn-select-checkbox";
  selectCheckbox.title = "Select turn for bulk editing";
  selectCheckbox.checked = state.selectedTurnIds.has(turn.id);
  selectCheckbox.addEventListener("click", (event) => {
    event.stopPropagation();
    setTurnSelected(turn.id, selectCheckbox.checked, { range: event.shiftKey });
  });

  // Quiet corner affordances instead of per-row button columns: the flags only
  // surface on hover (or while set), so the row keeps its width for text.
  const flags = document.createElement("div");
  flags.className = "turn-flags";
  const markFlag = document.createElement("button");
  markFlag.type = "button";
  markFlag.className = `turn-flag mark-flag${turn.bookmarked ? " active" : ""}`;
  markFlag.textContent = "mark";
  markFlag.title = turn.bookmarked ? "Remove bookmark (M)" : "Bookmark this turn (M)";
  markFlag.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleTurnBookmark(turn.id);
  });
  const isPendingStart = state.unrelatedPending === turn.id;
  const unrelatedFlag = document.createElement("button");
  unrelatedFlag.type = "button";
  unrelatedFlag.className = `turn-flag unrelated-flag${turn.unclear_intro ? " active" : ""}${isPendingStart ? " pending" : ""}`;
  // Two labels so entering "choose the end turn" mode swaps every pill's text
  // via a container class without re-rendering the whole list.
  const defaultLabel = document.createElement("span");
  defaultLabel.className = "flag-label-default";
  defaultLabel.textContent = "unrelated";
  const pendingLabel = document.createElement("span");
  pendingLabel.className = "flag-label-pending";
  pendingLabel.textContent = isPendingStart ? "cancel" : "end here";
  unrelatedFlag.append(defaultLabel, pendingLabel);
  unrelatedFlag.title = isPendingStart
    ? "Unrelated section starts here - click again (or Esc) to cancel"
    : turn.unclear_intro
      ? "Unmark this unrelated section (N)"
      : "Mark the start of an unrelated (non-medical) section (N)";
  unrelatedFlag.addEventListener("click", (event) => {
    event.stopPropagation();
    markUnrelatedSpan(turn.id);
  });
  const isDeletePendingStart = state.deletePending === turn.id;
  const deleteFlag = document.createElement("button");
  deleteFlag.type = "button";
  deleteFlag.className = `turn-flag delete-flag${isDeletePendingStart ? " pending" : ""}`;
  const deleteDefaultLabel = document.createElement("span");
  deleteDefaultLabel.className = "flag-label-default";
  deleteDefaultLabel.textContent = "delete";
  const deletePendingLabel = document.createElement("span");
  deletePendingLabel.className = "flag-label-pending";
  deletePendingLabel.textContent = isDeletePendingStart ? "cancel" : "end here";
  deleteFlag.append(deleteDefaultLabel, deletePendingLabel);
  deleteFlag.title = isDeletePendingStart
    ? "Deletion starts here - click again (or Esc) to cancel"
    : "Delete turns from here (X). Undo with Ctrl+Z";
  deleteFlag.addEventListener("click", (event) => {
    event.stopPropagation();
    deleteTurnSpan(turn.id);
  });
  flags.append(markFlag, unrelatedFlag, deleteFlag);

  const timeButton = document.createElement("button");
  timeButton.className = "time-button";
  timeButton.textContent = formatTime(turn.start_sec);
  timeButton.title = "Play turn";
  timeButton.addEventListener("click", (event) => {
    event.stopPropagation();
    playTurn(turn);
  });

  const speakerSelect = document.createElement("select");
  speakerSelect.className = "turn-speaker";
  renderSpeakerOptions(speakerSelect, turn.label);
  speakerSelect.addEventListener("change", () => {
    setActiveTurn(turn.id, { scroll: false });
    changeTurnSpeaker(turn, speakerSelect.value);
  });
  bindRoleMenuSpeed(speakerSelect);

  const speakerCell = document.createElement("div");
  speakerCell.className = "speaker-cell";
  speakerCell.append(speakerSelect);
  if (state.settings.showMergeButtons) {
    const mergeUpButton = document.createElement("button");
    mergeUpButton.type = "button";
    mergeUpButton.className = "turn-merge-button icon-button";
    mergeUpButton.textContent = "↑ Merge";
    mergeUpButton.setAttribute("aria-label", "Merge up");
    mergeUpButton.title = "Merge this turn into the previous turn";
    mergeUpButton.disabled = turnIndex <= 0;
    mergeUpButton.addEventListener("click", (event) => {
      event.stopPropagation();
      mergeTurnUp(turn.id);
    });

    const mergeDownButton = document.createElement("button");
    mergeDownButton.type = "button";
    mergeDownButton.className = "turn-merge-button icon-button";
    mergeDownButton.textContent = "↓ Merge";
    mergeDownButton.setAttribute("aria-label", "Merge down");
    mergeDownButton.title = "Merge the next turn into this turn";
    mergeDownButton.disabled = turnIndex < 0 || turnIndex >= state.turns.length - 1;
    mergeDownButton.addEventListener("click", (event) => {
      event.stopPropagation();
      mergeTurnDown(turn.id);
    });

    const mergeActions = document.createElement("div");
    mergeActions.className = "turn-merge-actions";
    mergeActions.append(mergeUpButton, mergeDownButton);
    speakerCell.append(mergeActions);
  }

  const body = document.createElement("div");
  body.className = "turn-body";
  renderTurnLines(body, turn);
  row.append(turnNumber, selectCheckbox, timeButton, speakerCell, body, flags);
  return row;
}

function focusTurnRowText(row) {
  const target = row?.querySelector(".turn-line-text");
  if (target) setCaretOffset(target, 0);
}

function renderSplitTurnPatch(sourceTurn, newTurn, options = {}) {
  if (state.showBookmarkedOnly) return false;
  const oldRow = turnRowForId(sourceTurn.id);
  const nextNode = oldRow?.nextElementSibling;
  if (!oldRow || !nextNode) return false;

  const context = {
    hitTurnIds: searchHitTurnIds(),
    activeMatch: currentSearchMatch(),
    turnIndexById: new Map(state.turns.map((turn, index) => [turn.id, index])),
  };
  const sourceRow = createTurnRow(sourceTurn, context);
  const newRow = createTurnRow(newTurn, context);
  unobserveTurnRow(oldRow);
  oldRow.replaceWith(sourceRow);
  appendTurnListNode(newRow, nextNode);
  observeTurnRow(sourceRow);
  observeTurnRow(newRow);
  state.pendingFocusTurnId = "";
  setActiveTurn(options.activeTurnId || newTurn.id, { scroll: false });
  if (options.focusText !== false) {
    focusTurnRowText(options.focusTurnId === sourceTurn.id ? sourceRow : newRow);
  }
  updateFinishedControls();
  return true;
}

function renderSingleTurnPatch(turn, options = {}) {
  const oldRow = turnRowForId(turn?.id);
  if (!oldRow) return false;
  const context = {
    hitTurnIds: searchHitTurnIds(),
    activeMatch: currentSearchMatch(),
    turnIndexById: new Map(state.turns.map((candidate, index) => [candidate.id, index])),
  };
  const row = createTurnRow(turn, context);
  unobserveTurnRow(oldRow);
  oldRow.replaceWith(row);
  observeTurnRow(row);
  if (turn.id === state.activeTurnId) {
    setActiveTurn(turn.id, { scroll: false });
  } else {
    patchTurnSelectionState(turn.id);
    updateBookmarkControls();
  }
  if (options.focusText) focusTurnRowText(row);
  updateFinishedControls();
  return true;
}

function removeTurnRowPatch(removedTurn) {
  const row = turnRowForId(removedTurn?.id);
  if (!row) return false;
  unobserveTurnRow(row);
  row.remove();
  updateFinishedControls();
  return true;
}

function renderWordMovePatch(sourceTurn, targetTurn, options = {}) {
  if (state.showBookmarkedOnly) return false;
  if (!turnRowForId(targetTurn?.id)) return false;
  if (sourceTurn !== targetTurn && !turnRowForId(sourceTurn?.id)) return false;

  const scrollSnapshot = captureTurnListScroll(state.activeTurnId || targetTurn.id);
  if (sourceTurn === targetTurn) {
    const patched = renderSingleTurnPatch(targetTurn);
    restoreTurnListScroll(scrollSnapshot);
    return patched;
  }

  if (options.sourceRemoved) {
    if (!removeTurnRowPatch(sourceTurn)) return false;
  } else if (!renderSingleTurnPatch(sourceTurn)) {
    return false;
  }

  const patchedTarget = renderSingleTurnPatch(targetTurn);
  restoreTurnListScroll(scrollSnapshot);
  return patchedTarget;
}

function renderTurnPatchRestore(beforeTurns, startIndex, removeCount, insertedTurns, activeTurnId = "") {
  if (state.showBookmarkedOnly) return false;
  const removedTurns = beforeTurns.slice(startIndex, startIndex + removeCount);
  if (!removedTurns.length || !insertedTurns.length) return false;
  const scrollSnapshot = captureTurnListScroll(activeTurnId || insertedTurns[0]?.id);
  let patched = false;
  if (
    removedTurns.length === 1
    && insertedTurns.length === 2
    && removedTurns[0]?.id === insertedTurns[0]?.id
  ) {
    patched = renderSplitTurnPatch(insertedTurns[0], insertedTurns[1], {
      activeTurnId,
      focusText: false,
    });
  } else if (
    removedTurns.length === 2
    && insertedTurns.length === 1
    && removedTurns[0]?.id === insertedTurns[0]?.id
  ) {
    patched = renderMergeTurnPatch(insertedTurns[0], removedTurns[1]);
  }
  if (!patched) return false;
  restoreTurnListScroll(scrollSnapshot);
  setActiveTurn(activeTurnId || insertedTurns[0]?.id, { smooth: true });
  return true;
}

function renderMergeTurnPatch(keptTurn, removedTurn, options = {}) {
  if (state.showBookmarkedOnly) return false;
  const keptRow = turnRowForId(keptTurn?.id);
  const removedRow = turnRowForId(removedTurn?.id);
  if (!keptRow || !removedRow) return false;
  if (!(keptRow.compareDocumentPosition(removedRow) & Node.DOCUMENT_POSITION_FOLLOWING)) return false;

  let node = keptRow.nextSibling;
  while (node && node !== removedRow) {
    const nextNode = node.nextSibling;
    node.remove();
    node = nextNode;
  }
  if (node !== removedRow) return false;
  unobserveTurnRow(removedRow);
  removedRow.remove();

  const context = {
    hitTurnIds: searchHitTurnIds(),
    activeMatch: currentSearchMatch(),
    turnIndexById: new Map(state.turns.map((turn, index) => [turn.id, index])),
  };
  const row = createTurnRow(keptTurn, context);
  unobserveTurnRow(keptRow);
  keptRow.replaceWith(row);
  observeTurnRow(row);
  state.pendingFocusTurnId = "";
  setActiveTurn(keptTurn.id, { scroll: false });
  if (options.focusText) focusTurnRowText(row);
  updateFinishedControls();
  return true;
}

function syncSplitPlaybackToTurn(turn, wasPlaying) {
  setActiveTurn(turn?.id || "", { scroll: false });
  if (!turn || !els.audio.src) {
    drawTimeline();
    return;
  }
  if (!wasPlaying) {
    document.querySelectorAll(".word-chip.current").forEach((chip) => chip.classList.remove("current"));
    renderTurnProgress();
    drawTimeline();
    return;
  }
  state.playbackTurnHold = {
    turnId: turn.id,
    until: performance.now() + Math.max(140, state.settings.visualLatencySec * 1000 + 100),
  };
  setAudioTime(turn.start_sec);
  startTimelineLoop();
  playAudio().catch(() => {});
}

function renderTurns(options = {}) {
  invalidateWordIndex();
  scheduleReviewMetaRefresh();
  state.renderedLineWidthPx = turnLineAvailableWidthPx();
  const preserveScroll = options.preserveScroll === true || options.scrollActive === false;
  const anchorTurnId = options.scrollAnchorTurnId || options.focusTurnId || state.activeTurnId;
  const scrollSnapshot = preserveScroll ? captureTurnListScroll(anchorTurnId) : null;
  resetTurnRowObservation();
  els.turnList.replaceChildren();
  renderGlobalSpeakers();
  const hitTurnIds = searchHitTurnIds();
  const activeMatch = currentSearchMatch();

  if (!state.turns.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No recording is open. Choose one on the Dashboard, or import audio and run the pipeline first.";
    els.turnList.append(empty);
    updateBookmarkControls();
    updateFinishedControls();
    restoreTurnListScroll(scrollSnapshot);
    return;
  }

  const visibleTurns = visibleReviewTurns();
  if (!visibleTurns.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No bookmarked turns yet.";
    els.turnList.append(empty);
    updateBookmarkControls();
    updateFinishedControls();
    restoreTurnListScroll(scrollSnapshot);
    return;
  }

  const renderContext = {
    hitTurnIds,
    activeMatch,
    turnIndexById: new Map(state.turns.map((turn, index) => [turn.id, index])),
  };

  const fragment = document.createDocumentFragment();
  const rows = [];
  for (const turn of visibleTurns) {
    const row = createTurnRow(turn, renderContext);
    rows.push(row);
    fragment.append(row);
  }
  els.turnList.append(fragment);
  for (const row of rows) observeTurnRow(row);

  appendFinishedMarker();

  const activeTurnId = visibleTurns.some((turn) => turn.id === state.activeTurnId)
    ? state.activeTurnId
    : visibleTurns[0]?.id;
  setActiveTurn(activeTurnId || "", { scroll: options.scrollActive !== false });
  restoreTurnListScroll(scrollSnapshot);
  const focusTurnId = options.focusTurnId || state.pendingFocusTurnId;
  if (focusTurnId) {
    state.pendingFocusTurnId = "";
    const focusTarget = els.turnList.querySelector(`.turn-row[data-turn-id="${CSS.escape(focusTurnId)}"] .turn-line-text`);
    if (focusTarget) {
      focusTarget.focus({ preventScroll: true });
    }
  }
  restoreTurnListScroll(scrollSnapshot);
  updateFinishedControls();
}

function appendFinishedMarker() {
  const marker = document.createElement("div");
  marker.className = `finished-marker${state.finished ? " done" : ""}`;

  const text = document.createElement("span");
  text.textContent = state.finished ? "This transcript is marked finished." : "This transcript is not finished yet.";

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = state.finished ? "Reopen" : "Mark Finished";
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleFinished().catch((error) => showErrorNotice(error));
  });

  marker.append(text, button);
  els.turnList.append(marker);
}

function appendTurnListNode(node, beforeNode = null) {
  if (beforeNode && beforeNode.parentElement === els.turnList) {
    els.turnList.insertBefore(node, beforeNode);
  } else {
    els.turnList.append(node);
  }
}

function renderWordStrip(container, turn, options = {}) {
  container.replaceChildren();
  container.dataset.turnId = turn.id;
  const content = document.createElement("span");
  content.className = "word-strip-content";
  container.append(content);
  const words = Array.isArray(options.words) ? options.words : turn.words;
  const wordOffset = Number(options.wordOffset) || 0;
  words.forEach((word, index) => {
    const globalIndex = wordOffset + index;
    const chip = document.createElement("span");
    chip.className = "word-chip inline-word";
    chip.textContent = word.text;
    chip.title = word.text;
    chip.setAttribute("aria-label", word.text);
    chip.draggable = true;
    chip.dataset.turnId = turn.id;
    chip.dataset.wordId = word.id;
    chip.dataset.wordIndex = String(globalIndex);
    const spaceGap = `${turnTextMetrics().spaceWidthPx.toFixed(2)}px`;
    const wordGap = index > 0 ? spaceGap : "0px";
    const nextWordGap = index < words.length - 1 ? spaceGap : "0px";
    chip.style.setProperty("--word-gap", wordGap);
    chip.style.setProperty("--next-word-gap", nextWordGap);
    const selected = state.selection.turnId === turn.id && state.selection.wordIds.has(word.id);
    if (selected) {
      chip.classList.add("selected");
    }
    if (state.search.query && word.text.toLowerCase().includes(state.search.query.toLowerCase())) {
      chip.classList.add("search-word");
    }
    chip.addEventListener("pointerdown", (event) => onWordPointerDown(event, turn, globalIndex));
    chip.addEventListener("pointerup", (event) => onWordPointerUp(event, turn, globalIndex));
    chip.addEventListener("click", (event) => onWordClick(event, turn, globalIndex));
    chip.addEventListener("dragstart", (event) => onWordDragStart(event, turn, globalIndex));
    chip.addEventListener("dragover", (event) => {
      event.stopPropagation();
      event.preventDefault();
      chip.classList.toggle("drop-before", dropWordIndex(event, chip, globalIndex) === globalIndex);
      chip.classList.toggle("drop-after", dropWordIndex(event, chip, globalIndex) === globalIndex + 1);
    });
    chip.addEventListener("dragleave", () => clearWordDropMarker(chip));
    chip.addEventListener("dragend", endWordDrag);
    chip.addEventListener("drop", (event) => {
      clearWordDropMarker(chip);
      onDropWords(event, turn.id, dropWordIndex(event, chip, globalIndex));
    });
    content.append(chip);
  });
}

function timedWordGapPx(turn, index) {
  return timedWordGapPxInList(turn, turn?.words || [], index);
}

function timedWordGapPxInList(turn, words, index) {
  if (index <= 0 || !words?.[index] || !words[index - 1]) return 0;
  if (turn.timingReliable === false) return 5;
  const currentStart = Number(words[index].start_sec);
  const previousEnd = Number(words[index - 1].end_sec);
  if (!Number.isFinite(currentStart) || !Number.isFinite(previousEnd)) return 5;
  const gapSec = Math.max(0, currentStart - previousEnd);
  return Math.max(5, Math.min(34, Math.round(5 + gapSec * 34)));
}

function selectedChipWords() {
  if (!state.selection.turnId || !state.selection.wordIds.size) return [];
  const turn = turnById(state.selection.turnId);
  if (!turn) return [];
  return turn.words.filter((word) => state.selection.wordIds.has(word.id));
}

function selectedSingleWordRef() {
  if (!state.selection.turnId || state.selection.wordIds.size !== 1) return null;
  const turn = turnById(state.selection.turnId);
  if (!turn) return null;
  const wordId = Array.from(state.selection.wordIds)[0];
  const index = turn.words.findIndex((word) => word.id === wordId);
  if (index < 0) return null;
  return { turn, index, word: turn.words[index] };
}

function wordRefFromChip(chip) {
  if (!chip) return null;
  const turn = turnById(chip.dataset.turnId);
  if (!turn) return null;
  const wordId = chip.dataset.wordId || "";
  let index = turn.words.findIndex((word) => word.id === wordId);
  if (index < 0) {
    index = Number(chip.dataset.wordIndex);
  }
  if (!Number.isInteger(index) || index < 0 || index >= turn.words.length) return null;
  const word = turn.words[index];
  if (wordId && word.id !== wordId) return null;
  return { turn, index, word };
}

function hoveredWordBarRef() {
  return wordRefFromChip(document.querySelector(".word-chip:hover"));
}

function clearWordSelection() {
  const previousTurnId = state.selection.turnId;
  state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  syncWordSelectionClasses(previousTurnId);
}

function selectSingleWord(turn, index) {
  const word = turn?.words?.[index];
  if (!turn || !word) return false;
  state.selection = { turnId: turn.id, wordIds: new Set([word.id]), anchorIndex: index };
  syncWordSelectionClasses(turn.id);
  return true;
}

function wordSpans(text) {
  return Array.from(String(text || "").matchAll(/\S+/g)).map((match) => ({
    start: match.index,
    end: match.index + match[0].length,
  }));
}

function textTokens(text) {
  return cleanText(text).match(/\S+/g) || [];
}

function tokenCount(text) {
  return textTokens(text).length;
}

function wordsMatchText(words = [], text = "") {
  const tokens = textTokens(text);
  return tokens.length === words.length && tokens.every((token, index) => wordToken(words[index]) === cleanText(token).toLowerCase());
}

function selectionOffsetsInElement(element) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!element.contains(range.commonAncestorContainer)) return null;

  const startRange = range.cloneRange();
  startRange.selectNodeContents(element);
  startRange.setEnd(range.startContainer, range.startOffset);

  const endRange = range.cloneRange();
  endRange.selectNodeContents(element);
  endRange.setEnd(range.endContainer, range.endOffset);

  return {
    start: startRange.toString().length,
    end: endRange.toString().length,
    text: range.toString(),
    range,
  };
}

function selectedTurnTextWords(turn, element) {
  const offsets = selectionOffsetsInElement(element);
  if (!offsets || !cleanText(offsets.text)) return [];
  const spans = wordSpans(element.textContent || "");
  const wordStart = Number(element.dataset.wordStart) || 0;
  return (turn.words || []).slice(wordStart, wordStart + spans.length).filter((word, index) => {
    const span = spans[index];
    return span && span.end > offsets.start && span.start < offsets.end;
  });
}

function writeTimedWordsClipboard(event, words, text) {
  if (!event.clipboardData || !words.length) return false;
  const plain = text || textFromWords(words);
  event.clipboardData.setData("text/plain", plain);
  event.clipboardData.setData(TIMED_WORD_CLIPBOARD_TYPE, JSON.stringify({
    version: 1,
    session: state.sessionName,
    words: revisionWords(words),
  }));
  event.preventDefault();
  return true;
}

function onEditorCopy(event) {
  const chipWords = selectedChipWords();
  if (chipWords.length && writeTimedWordsClipboard(event, chipWords)) return;

  const activeElement = document.activeElement;
  const textElement = activeElement?.closest?.(".turn-text");
  const row = textElement?.closest?.(".turn-row");
  const turn = row ? turnById(row.dataset.turnId) : null;
  if (!turn || !textElement) return;

  const selectedWords = selectedTurnTextWords(turn, textElement);
  if (selectedWords.length) {
    writeTimedWordsClipboard(event, selectedWords, window.getSelection()?.toString() || textFromWords(selectedWords));
  }
}

function timedWordsFromClipboard(clipboardData) {
  const rawPayload = clipboardData?.getData(TIMED_WORD_CLIPBOARD_TYPE);
  if (!rawPayload) return [];
  try {
    const payload = JSON.parse(rawPayload);
    return Array.isArray(payload.words) ? payload.words.filter((word) => cleanText(word.text)) : [];
  } catch {
    return [];
  }
}

function insertTextAtSelection(element, text) {
  const offsets = selectionOffsetsInElement(element);
  const original = element.textContent || "";
  const selectedRange = offsets?.range;
  if (!selectedRange) {
    element.textContent = cleanText(`${original} ${text}`);
    return;
  }

  const beforeChar = offsets.start > 0 ? original[offsets.start - 1] : "";
  const afterChar = offsets.end < original.length ? original[offsets.end] : "";
  const prefix = beforeChar && /\S/.test(beforeChar) ? " " : "";
  const suffix = afterChar && /\S/.test(afterChar) ? " " : "";
  const inserted = document.createTextNode(`${prefix}${text}${suffix}`);
  selectedRange.deleteContents();
  selectedRange.insertNode(inserted);
  selectedRange.setStartAfter(inserted);
  selectedRange.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(selectedRange);
  element.normalize();
}

function onTurnPaste(event, turn, element, body = null) {
  const pastedWords = timedWordsFromClipboard(event.clipboardData);
  if (!pastedWords.length) return;

  event.preventDefault();
  const before = revisionTurnState(turn);
  if (state.textEditSnapshotTurnId !== turn.id) {
    const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
    recordTurnPatchUndo(index, 1, [turn], turn.id);
    state.textEditSnapshotTurnId = turn.id;
  }
  insertTextAtSelection(element, textFromWords(pastedWords));
  if (body) {
    updateTurnFromLineElements(turn, body, { preferredWords: pastedWords });
  } else {
    turn.text = cleanText(element.textContent);
    syncWordsFromText(turn, { preferredWords: pastedWords });
  }
  refreshSearchMatches({ keepIndex: true });
  // Pasted text can overflow the line; rewrap right away instead of hiding it
  // behind the nowrap clip until the next render.
  if (body && !maybeRewrapTurnLines(body, turn, element, null)) {
    rerenderTurnLineBars(body, turn);
  }
  const after = revisionTurnState(turn);
  pushRevisionEvent("paste", before, after, { word_count: pastedWords.length });
  state.textEditRevision = { turnId: turn.id, before: after };
  markDirty();
}

function clearPendingWordRangeSelection() {
  const pending = state.wordRangeSelect.pending;
  if (pending?.timer) {
    window.clearTimeout(pending.timer);
  }
  state.wordRangeSelect.pending = null;
}

function suppressNextWordClick() {
  state.wordRangeSelect.suppressClick = true;
  window.setTimeout(() => {
    state.wordRangeSelect.suppressClick = false;
  }, 250);
}

function setWordRangeSelectionMode(turnId, active) {
  wordSelectionStripsForTurn(turnId).forEach((strip) => {
    strip.classList.toggle("selecting", active);
    strip.querySelectorAll(".word-chip").forEach((chip) => {
      chip.draggable = !active;
    });
  });
}

function wordSelectionStripsForTurn(turnId) {
  if (!turnId) return [];
  return Array.from(document.querySelectorAll(`.word-strip[data-turn-id="${CSS.escape(turnId)}"]`));
}

function clearWordSelectionClassesForTurn(turnId) {
  wordSelectionStripsForTurn(turnId).forEach((strip) => {
    strip.querySelectorAll(".word-chip.selected").forEach((chip) => {
      chip.classList.remove("selected");
    });
  });
}

function syncWordSelectionClasses(turnId = state.selection.turnId) {
  clearWordSelectionClassesForTurn(state.lastWordSelectionTurnId);
  clearWordSelectionClassesForTurn(turnId);
  if (!state.selection.turnId) {
    state.lastWordSelectionTurnId = "";
    return;
  }
  wordSelectionStripsForTurn(state.selection.turnId).forEach((strip) => {
    const chips = Array.from(strip.querySelectorAll(".word-chip"));
    chips.forEach((chip, index) => {
      const selected = state.selection.wordIds.has(chip.dataset.wordId);
      if (!selected) return;
      chip.classList.add("selected");
    });
  });
  state.lastWordSelectionTurnId = state.selection.turnId;
}

function selectWordRange(turn, anchorIndex, focusIndex) {
  const start = Math.min(anchorIndex, focusIndex);
  const end = Math.max(anchorIndex, focusIndex);
  state.selection = {
    turnId: turn.id,
    wordIds: new Set(turn.words.slice(start, end + 1).map((word) => word.id)),
    anchorIndex,
  };
  syncWordSelectionClasses(turn.id);
}

function beginWordRangeSelection(pending) {
  const turn = turnById(pending.turnId);
  if (!turn || !turn.words[pending.anchorIndex]) {
    clearPendingWordRangeSelection();
    return;
  }
  state.wordRangeSelect.pending = null;
  state.wordRangeSelect.active = {
    turnId: turn.id,
    anchorIndex: pending.anchorIndex,
    lastIndex: pending.anchorIndex,
    pointerId: pending.pointerId,
  };
  setActiveTurn(turn.id, { scroll: false });
  selectWordRange(turn, pending.anchorIndex, pending.anchorIndex);
  setWordRangeSelectionMode(turn.id, true);
}

function onWordPointerDown(event, turn, index) {
  if (event.button !== 0 || event.shiftKey || event.ctrlKey || event.metaKey) return;
  clearPendingWordRangeSelection();
  const pending = {
    turnId: turn.id,
    anchorIndex: index,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startedAt: performance.now(),
    timer: 0,
  };
  pending.timer = window.setTimeout(() => {
    if (state.wordRangeSelect.pending === pending) {
      beginWordRangeSelection(pending);
    }
  }, WORD_RANGE_HOLD_MS);
  state.wordRangeSelect.pending = pending;
}

function onWordPointerUp(event, turn, index) {
  const pending = state.wordRangeSelect.pending;
  if (!pending || event.pointerId !== pending.pointerId || pending.turnId !== turn.id) return;
  event.preventDefault();
  event.stopPropagation();
  clearPendingWordRangeSelection();
  suppressNextWordClick();
  activateWordBar(turn, index);
}

function wordChipFromPoint(clientX, clientY) {
  const element = document.elementFromPoint(clientX, clientY);
  return element?.closest?.(".word-chip") || null;
}

function onWordRangePointerMove(event) {
  const active = state.wordRangeSelect.active;
  if (active) {
    if (event.pointerId !== active.pointerId) return;
    event.preventDefault();
    const chip = wordChipFromPoint(event.clientX, event.clientY);
    if (!chip || chip.dataset.turnId !== active.turnId) return;
    const index = Number(chip.dataset.wordIndex);
    if (!Number.isInteger(index) || index === active.lastIndex) return;
    const turn = turnById(active.turnId);
    if (!turn) return;
    active.lastIndex = index;
    selectWordRange(turn, active.anchorIndex, index);
    return;
  }

  const pending = state.wordRangeSelect.pending;
  if (!pending || event.pointerId !== pending.pointerId) return;
  const distance = Math.hypot(event.clientX - pending.startX, event.clientY - pending.startY);
  if (distance > WORD_RANGE_MOVE_TOLERANCE) {
    clearPendingWordRangeSelection();
  }
}

function finishWordRangeSelection(event) {
  const active = state.wordRangeSelect.active;
  if (!active || event.pointerId !== active.pointerId) {
    const pending = state.wordRangeSelect.pending;
    if (pending && event.pointerId === pending.pointerId) clearPendingWordRangeSelection();
    return;
  }
  setWordRangeSelectionMode(active.turnId, false);
  state.wordRangeSelect.active = null;
  suppressNextWordClick();
  const count = state.selection.turnId === active.turnId ? state.selection.wordIds.size : 0;
  if (count > 1) {
  }
}

function cancelWordRangeSelection(options = {}) {
  clearPendingWordRangeSelection();
  if (state.wordRangeSelect.active) {
    setWordRangeSelectionMode(state.wordRangeSelect.active.turnId, false);
    state.wordRangeSelect.active = null;
  }
  if (options.suppressClick) {
    suppressNextWordClick();
  }
}

function clearWordDropMarker(chip) {
  chip.classList.remove("drop-before", "drop-after");
}

function dropWordIndex(event, chip, index) {
  const rect = chip.getBoundingClientRect();
  const midpoint = rect.left + rect.width / 2;
  return event.clientX > midpoint ? index + 1 : index;
}

function activateWordBar(turn, index) {
  setActiveTurn(turn.id, { scroll: false });
  selectSingleWord(turn, index);
  const seekTime = turn.timingReliable === false
    ? turn.start_sec
    : numberOr(turn.words[index]?.start_sec, turn.start_sec);
  setAudioTime(seekTime);
  if (state.settings.wordClickPlays && els.audio.src) {
    playAudio().catch(() => {});
  }
  drawTimeline();
}

function onWordClick(event, turn, index) {
  event.stopPropagation();
  if (state.wordRangeSelect.suppressClick) {
    state.wordRangeSelect.suppressClick = false;
    event.preventDefault();
    return;
  }
  activateWordBar(turn, index);
}

function onWordDragStart(event, turn, index) {
  event.stopPropagation();
  const pending = state.wordRangeSelect.pending;
  if (
    pending
    && pending.turnId === turn.id
    && pending.anchorIndex === index
    && performance.now() - pending.startedAt < WORD_RANGE_HOLD_MS
  ) {
    event.preventDefault();
    return;
  }
  if (state.wordRangeSelect.active) {
    event.preventDefault();
    return;
  }
  clearPendingWordRangeSelection();
  beginWordDrag();
  event.currentTarget?.classList?.add("dragging");
  if (state.selection.turnId !== turn.id || !state.selection.wordIds.has(turn.words[index].id)) {
    state.selection = { turnId: turn.id, wordIds: new Set([turn.words[index].id]), anchorIndex: index };
    syncWordSelectionClasses(turn.id);
  }
  const payload = {
    sourceTurnId: turn.id,
    wordIds: Array.from(state.selection.wordIds),
  };
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("application/json", JSON.stringify(payload));
  event.dataTransfer.setData("text/plain", selectedChipWords().map((word) => word.text).join(" "));
}

function onTurnDragStart(event, turn) {
  event.stopPropagation();
  const wordIds = turn.words.map((word) => word.id);
  if (!wordIds.length) {
    event.preventDefault();
    return;
  }
  beginWordDrag();
  state.selection = { turnId: turn.id, wordIds: new Set(wordIds), anchorIndex: 0 };
  syncWordSelectionClasses(turn.id);
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("application/json", JSON.stringify({ sourceTurnId: turn.id, wordIds }));
}

function beginWordDrag() {
  if (state.dragPlaybackRate === null) {
    state.dragPlaybackRate = Number(els.audio.playbackRate) || effectivePlaybackRate();
  }
  document.body.classList.add("word-drag-active");
  if (state.settings.wordDragSlowsAudio) {
    applyPlaybackRate(state.settings.slowPlaybackRate);
  }
}

function endWordDrag() {
  if (state.dragPlaybackRate === null) return;
  state.dragPlaybackRate = null;
  document.body.classList.remove("word-drag-active");
  document.querySelectorAll(".word-chip.dragging").forEach((chip) => chip.classList.remove("dragging"));
  applyEffectivePlaybackRate();
}

function beginTextEditPlayback() {
  if (!state.settings.textEditSlowsAudio) return;
  if (state.textEditPlaybackSlow) return;
  state.textEditPlaybackSlow = true;
  applyEffectivePlaybackRate();
}

function endTextEditPlayback() {
  if (!state.textEditPlaybackSlow) return;
  state.textEditPlaybackSlow = false;
  applyEffectivePlaybackRate();
}

function beginRoleMenuPlayback() {
  if (state.roleMenuPlaybackSlow) return;
  if (state.settings.roleMenuBehavior === "pause") {
    state.roleMenuPausedPlayback = !audioIsPaused();
    if (state.roleMenuPausedPlayback) pauseAudio();
    state.roleMenuPlaybackSlow = true;
    return;
  }
  if (state.settings.roleMenuBehavior === "none") return;
  state.roleMenuPlaybackSlow = true;
  applyEffectivePlaybackRate();
}

function endRoleMenuPlayback() {
  if (!state.roleMenuPlaybackSlow) return;
  state.roleMenuPlaybackSlow = false;
  if (state.settings.roleMenuBehavior === "pause") {
    if (state.roleMenuPausedPlayback && els.audio.src) playAudio().catch(() => {});
    state.roleMenuPausedPlayback = false;
    return;
  }
  applyEffectivePlaybackRate();
}

function bindRoleMenuSpeed(select) {
  select.addEventListener("pointerdown", beginRoleMenuPlayback);
  select.addEventListener("focus", beginRoleMenuPlayback);
  select.addEventListener("blur", endRoleMenuPlayback);
  select.addEventListener("change", () => window.setTimeout(endRoleMenuPlayback, 0));
}

function onRowDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add("drop-target");
}

function onDropWords(event, targetTurnId, insertIndex) {
  event.stopPropagation();
  event.preventDefault();
  document.querySelectorAll(".drop-target").forEach((row) => row.classList.remove("drop-target"));
  document.querySelectorAll(".word-chip.drop-before, .word-chip.drop-after").forEach(clearWordDropMarker);
  let payload;
  try {
    payload = JSON.parse(event.dataTransfer.getData("application/json"));
  } catch {
    return;
  }
  moveWords(payload.sourceTurnId, targetTurnId, payload.wordIds, insertIndex);
  endWordDrag();
}

function moveWords(sourceTurnId, targetTurnId, wordIds, insertIndex) {
  const source = state.turns.find((turn) => turn.id === sourceTurnId);
  const target = state.turns.find((turn) => turn.id === targetTurnId);
  if (!source || !target || !Array.isArray(wordIds) || !wordIds.length) return;

  const selected = new Set(wordIds);
  const sourceWordsBeforeMove = source.words.slice();
  const moved = sourceWordsBeforeMove.filter((word) => selected.has(word.id));
  if (!moved.length) return;

  const before = { turns: [revisionTurnState(source), ...(source === target ? [] : [revisionTurnState(target)])] };
  recordUndo();
  const beforeOrder = source === target ? sourceWordsBeforeMove.map((word) => word.id).join("\u0000") : "";
  const removedBeforeTarget = source === target
    ? sourceWordsBeforeMove.filter((word, index) => selected.has(word.id) && index < insertIndex).length
    : 0;
  source.words = sourceWordsBeforeMove.filter((word) => !selected.has(word.id));

  let targetIndex = Math.max(0, Math.min(insertIndex - removedBeforeTarget, target.words.length));

  target.words.splice(targetIndex, 0, ...moved);
  if (source === target && target.words.map((word) => word.id).join("\u0000") === beforeOrder) {
    state.undoStack.pop();
    return;
  }
  source.text = textFromWords(source.words);
  target.text = textFromWords(target.words);
  delete source.editorLineTexts;
  delete target.editorLineTexts;
  refreshTurnTiming(source);
  refreshTurnTiming(target);
  reconcileTurnNeighbors(source.id);
  reconcileTurnNeighbors(target.id);
  pushRevisionEvent("word_move", before, {
    turns: [revisionTurnState(source), ...(source === target ? [] : [revisionTurnState(target)])],
  }, {
    source_turn_id: sourceTurnId,
    target_turn_id: targetTurnId,
    insert_index: targetIndex,
    moved_word_count: moved.length,
  });
  if (moved.length) {
    state.selection = { turnId: target.id, wordIds: new Set([moved[0].id]), anchorIndex: targetIndex };
  }
  markDirty();
  const sourceRemoved = source !== target && removeTurnIfEmpty(source.id, { render: false });
  if (!renderWordMovePatch(source, target, { sourceRemoved })) {
    renderTurns({ scrollActive: false, scrollAnchorTurnId: target.id });
  }
}

function refreshTurnTiming(turn) {
  // Derive the turn boundary from its words. Filter to *finite* times only --
  // `Number(word.start_sec) || turn.start_sec` used to fall back to the stale
  // turn time whenever a word legitimately started at 0 (falsy) or had a missing
  // time, silently dragging boundaries to the old position after an edit.
  const starts = turn.words
    .map((word) => Number(word.start_sec))
    .filter((value) => Number.isFinite(value));
  const ends = turn.words
    .map((word) => Number(word.end_sec))
    .filter((value) => Number.isFinite(value));
  if (starts.length) turn.start_sec = Math.min(...starts);
  if (ends.length) turn.end_sec = Math.max(...ends);
  // A turn must never invert; keep a hair of width so boundary markers stay ordered.
  if (!(Number(turn.end_sec) > Number(turn.start_sec))) {
    turn.end_sec = (Number(turn.start_sec) || 0) + 0.01;
  }
}

// Keep the shared boundary between two adjacent turns consistent: the earlier
// turn must not end after the later one starts. Word-level times can overlap
// (diarization noise, edits), which makes the turn-level boundary marker --
// rendered at the later turn's start -- appear to jump backwards. Snap both
// sides to the midpoint so neither turn swallows the other.
function reconcileBoundary(prevTurn, nextTurn) {
  if (!prevTurn || !nextTurn) return;
  const prevStart = Number(prevTurn.start_sec);
  const prevEnd = Number(prevTurn.end_sec);
  const nextStart = Number(nextTurn.start_sec);
  if (!Number.isFinite(prevEnd) || !Number.isFinite(nextStart)) return;
  if (prevEnd <= nextStart) return;
  const boundary = Number(((prevEnd + nextStart) / 2).toFixed(3));
  prevTurn.end_sec = Math.max(Number.isFinite(prevStart) ? prevStart + 0.01 : boundary, boundary);
  nextTurn.start_sec = boundary;
  if (!(Number(nextTurn.end_sec) > Number(nextTurn.start_sec))) {
    nextTurn.end_sec = boundary + 0.01;
  }
}

// Reconcile the boundaries on both sides of the turn with this id (it may have
// moved, so look it up fresh). Safe no-op if the turn is gone.
function reconcileTurnNeighbors(turnId) {
  const index = state.turns.findIndex((candidate) => candidate.id === turnId);
  if (index < 0) return;
  if (index > 0) reconcileBoundary(state.turns[index - 1], state.turns[index]);
  if (index < state.turns.length - 1) reconcileBoundary(state.turns[index], state.turns[index + 1]);
}

function moveWordBoundaryToAdjacentTurn(turn, index, direction) {
  const sourceIndex = state.turns.findIndex((candidate) => candidate.id === turn?.id);
  const targetIndex = direction === "up" ? sourceIndex - 1 : sourceIndex + 1;
  if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= state.turns.length) {
    return false;
  }

  const source = state.turns[sourceIndex];
  const target = state.turns[targetIndex];
  const sourceWords = source.words.slice();
  const safeIndex = Math.max(0, Math.min(index, sourceWords.length - 1));
  const moved = direction === "up" ? sourceWords.slice(0, safeIndex + 1) : sourceWords.slice(safeIndex);
  if (!moved.length) return false;
  const sourceWillBeRemoved = moved.length === sourceWords.length;

  const beforeTurns = sourceIndex < targetIndex ? [source, target] : [target, source];
  const before = { turns: beforeTurns.map(revisionTurnState) };
  recordTurnPatchUndo(Math.min(sourceIndex, targetIndex), sourceWillBeRemoved ? 1 : 2, beforeTurns, source.id);

  const selectedWordId = sourceWords[safeIndex].id;
  if (direction === "up") {
    target.words = [...(target.words || []), ...moved];
    source.words = sourceWords.slice(safeIndex + 1);
  } else {
    target.words = [...moved, ...(target.words || [])];
    source.words = sourceWords.slice(0, safeIndex);
  }

  source.text = textFromWords(source.words);
  target.text = textFromWords(target.words);
  delete source.editorLineTexts;
  delete target.editorLineTexts;
  if (source.words.length) refreshTurnTiming(source);
  refreshTurnTiming(target);

  const sourceRemoved = source.words.length === 0;
  if (sourceRemoved) {
    state.turns.splice(sourceIndex, 1);
    state.selectedTurnIds.delete(source.id);
  }
  reconcileTurnNeighbors(target.id);
  if (!sourceRemoved) reconcileTurnNeighbors(source.id);

  const targetSelectedIndex = target.words.findIndex((word) => word.id === selectedWordId);
  state.activeTurnId = target.id;
  state.selection = {
    turnId: target.id,
    wordIds: new Set([selectedWordId]),
    anchorIndex: targetSelectedIndex,
  };
  pushRevisionEvent("word_boundary_move", before, {
    turns: beforeTurns
      .filter((candidate) => !sourceRemoved || candidate.id !== source.id)
      .map(revisionTurnState),
  }, {
    direction,
    selected_word_id: selectedWordId,
    moved_word_count: moved.length,
  });
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  if (!renderWordMovePatch(source, target, { sourceRemoved })) {
    renderTurns({ scrollActive: true, scrollAnchorTurnId: target.id, focusTurnId: target.id });
  }
  syncWordSelectionClasses(target.id);
  setActiveTurn(target.id, { smooth: true });
  return true;
}

function localConversationSpeakers(contextTurn = null) {
  const index = state.turns.findIndex((turn) => turn.id === contextTurn?.id);
  if (index < 0) return [];
  const focusTime = turnCenterSec(state.turns[index]);
  const labels = [];
  const addLabel = (turn) => {
    if (Math.abs(turnCenterSec(turn) - focusTime) > ROLE_CYCLE_CONTEXT_SEC) return;
    const label = speakerLabel(turn?.label, "");
    if (label && !labels.includes(label)) labels.push(label);
  };
  addLabel(state.turns[index]);
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (turnGapSec(state.turns[cursor], state.turns[cursor + 1]) > ROLE_LOCAL_BOUNDARY_GAP_SEC) break;
    if (Math.abs(turnCenterSec(state.turns[cursor]) - focusTime) > ROLE_CYCLE_CONTEXT_SEC) break;
    addLabel(state.turns[cursor]);
  }
  for (let cursor = index + 1; cursor < state.turns.length; cursor += 1) {
    if (turnGapSec(state.turns[cursor - 1], state.turns[cursor]) > ROLE_LOCAL_BOUNDARY_GAP_SEC) break;
    if (Math.abs(turnCenterSec(state.turns[cursor]) - focusTime) > ROLE_CYCLE_CONTEXT_SEC) break;
    addLabel(state.turns[cursor]);
  }
  return labels;
}

function roleCandidates(current = "", contextTurn = null) {
  const selected = speakerLabel(current, "");
  const localSpeakers = localConversationSpeakers(contextTurn);
  if (contextTurn) {
    return speakerListFromValues([...localSpeakers, selected]);
  }
  const usedSpeakers = speakerListFromValues(state.turns.map((turn) => turn.label));
  const usedSpeakerSet = new Set(usedSpeakers);
  return speakerListFromValues([
    ...state.speakers,
    ...state.turns.map((turn) => turn.label),
    selected,
  ]).filter((speaker) => (
    speaker === selected
    || usedSpeakerSet.has(speaker)
    || !DEFAULT_SPEAKERS.includes(speaker)
  ));
}

function turnCenterSec(turn) {
  const start = Number(turn?.start_sec) || 0;
  const end = Number(turn?.end_sec) || start;
  return (start + end) / 2;
}

function turnGapSec(left, right) {
  if (!left || !right) return Number.POSITIVE_INFINITY;
  return Math.max(0, (Number(right.start_sec) || 0) - (Number(left.end_sec) || 0));
}

function globalSpeakerScores(candidates) {
  const scores = new Map(candidates.map((speaker) => [speaker, 0]));
  let total = 0;
  state.turns.forEach((turn) => {
    const label = speakerLabel(turn.label, "");
    if (!label || !scores.has(label)) return;
    scores.set(label, scores.get(label) + 1);
    total += 1;
  });
  if (!total) return scores;
  scores.forEach((count, speaker) => {
    scores.set(speaker, (count / total) * ROLE_GLOBAL_WEIGHT);
  });
  return scores;
}

function addLocalSpeakerScore(scores, focusTime, turn) {
  const label = speakerLabel(turn?.label, "");
  if (!label || !scores.has(label)) return;
  const distance = Math.abs(turnCenterSec(turn) - focusTime);
  const weight = Math.exp(-distance / ROLE_LOCAL_DECAY_SEC) * ROLE_LOCAL_WEIGHT;
  scores.set(label, scores.get(label) + weight);
}

function localSpeakerScores(contextTurn, candidates) {
  const scores = new Map(candidates.map((speaker) => [speaker, 0]));
  const index = state.turns.findIndex((turn) => turn.id === contextTurn?.id);
  if (index < 0) return scores;
  const focusTime = turnCenterSec(state.turns[index]);

  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    if (turnGapSec(state.turns[cursor], state.turns[cursor + 1]) > ROLE_LOCAL_BOUNDARY_GAP_SEC) break;
    addLocalSpeakerScore(scores, focusTime, state.turns[cursor]);
  }
  for (let cursor = index + 1; cursor < state.turns.length; cursor += 1) {
    if (turnGapSec(state.turns[cursor - 1], state.turns[cursor]) > ROLE_LOCAL_BOUNDARY_GAP_SEC) break;
    addLocalSpeakerScore(scores, focusTime, state.turns[cursor]);
  }
  return scores;
}

function roleCycleOrder(current = "", contextTurn = null) {
  const selected = speakerLabel(current);
  const candidates = roleCandidates(selected, contextTurn);
  const globalScores = globalSpeakerScores(candidates);
  const localScores = localSpeakerScores(contextTurn, candidates);
  return candidates
    .map((speaker, index) => ({
      speaker,
      index,
      score: (globalScores.get(speaker) || 0) + (localScores.get(speaker) || 0),
    }))
    .sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      return left.index - right.index;
    })
    .map((entry) => entry.speaker);
}

function speakerCycle(current, reverse = false, contextTurn = null) {
  const selected = speakerLabel(current);
  const order = roleCycleOrder(selected, contextTurn);
  if (!order.length) return selected || "Unknown";
  const index = order.indexOf(selected);
  if (index < 0) return order[0] || selected || "Unknown";
  const direction = reverse ? -1 : 1;
  return order[(index + direction + order.length) % order.length] || selected || "Unknown";
}

function cycleTurnSpeaker(turn, reverse = false, options = {}) {
  if (options.fromShortcut) endRoleMenuPlayback();
  changeTurnSpeaker(turn, speakerCycle(turn.label, reverse, turn), { focusText: options.focusText === true });
}

// Recommend the speaker for a segment split off from `turn`. Each call is independent:
// it re-reads the current transcript and returns the most likely *other* speaker here,
// rather than advancing a cycle. So repeated splits flip toward the conversational
// partner (clinician -> patient, patient -> clinician) instead of drifting to Unknown.
function recommendedSplitSpeaker(turn) {
  const current = speakerLabel(turn?.label);
  const order = roleCycleOrder(current, turn);
  const real = order.find((speaker) => speaker && speaker !== current && speaker !== "Unknown");
  const other = real || order.find((speaker) => speaker && speaker !== current);
  return other || current || "Unknown";
}

function getCaretOffset(element) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return 0;
  const range = selection.getRangeAt(0);
  if (!element.contains(range.commonAncestorContainer)) return cleanText(element.textContent).length;
  const clone = range.cloneRange();
  clone.selectNodeContents(element);
  clone.setEnd(range.startContainer, range.startOffset);
  return clone.toString().length;
}

function splitTurnLineAtCaret(turn, element) {
  const body = element.closest(".turn-body");
  if (!body) return;
  const lineElements = lineTextElementsForBody(body);
  const lineIndex = lineElements.indexOf(element);
  if (lineIndex < 0) return;
  const offset = getCaretOffset(element);
  const currentText = element.textContent || "";
  const before = currentText.slice(0, offset);
  const after = currentText.slice(offset);
  if (state.textEditSnapshotTurnId !== turn.id) {
    const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
    recordTurnPatchUndo(index, 1, [turn], turn.id);
    state.textEditSnapshotTurnId = turn.id;
  }
  if (!state.textEditRevision || state.textEditRevision.turnId !== turn.id) {
    beginTextRevision(turn);
  }
  const nextLines = lineElements.map((line) => line.textContent || "");
  nextLines.splice(Math.max(0, lineIndex), 1, before, after);
  turn.editorLineTexts = nextLines;
  turn.text = cleanText(nextLines.join(" "));
  syncWordsFromText(turn);
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  renderTurnLines(body, turn);
  const target = lineTextElementsForBody(body)[lineIndex + 1];
  if (target) setCaretOffset(target, 0);
}

function mergeTurnLineUp(turn, element) {
  const body = element.closest(".turn-body");
  if (!body) return false;
  const lineElements = lineTextElementsForBody(body);
  const lineIndex = lineElements.indexOf(element);
  if (lineIndex <= 0) return false;
  if (state.textEditSnapshotTurnId !== turn.id) {
    const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
    recordTurnPatchUndo(index, 1, [turn], turn.id);
    state.textEditSnapshotTurnId = turn.id;
  }
  if (!state.textEditRevision || state.textEditRevision.turnId !== turn.id) {
    beginTextRevision(turn);
  }
  const nextLines = lineElements.map((line) => line.textContent || "");
  const previousLength = cleanText(nextLines[lineIndex - 1]).length;
  nextLines[lineIndex - 1] = cleanText(`${nextLines[lineIndex - 1]} ${nextLines[lineIndex]}`);
  nextLines.splice(lineIndex, 1);
  turn.editorLineTexts = nextLines;
  turn.text = cleanText(nextLines.join(" "));
  syncWordsFromText(turn);
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  renderTurnLines(body, turn);
  const target = lineTextElementsForBody(body)[lineIndex - 1];
  if (target) setCaretOffset(target, previousLength);
  return true;
}

function onTurnKeydown(event, turn, element) {
  if (event.key === "Tab") {
    event.preventDefault();
    event.stopPropagation();
    element.blur();
    setActiveTurn(turn.id, { scroll: false });
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    event.stopPropagation();
    element.dataset.skipBlurSync = "true";
    if (event.shiftKey) {
      splitTurnLineAtCaret(turn, element);
    } else {
      splitTurnAtLineCaret(turn, element);
    }
    return;
  }
  if (event.key === "Backspace" && getCaretOffset(element) === 0) {
    if (mergeTurnLineUp(turn, element)) {
      event.preventDefault();
      return;
    }
    const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
    if (index > 0) {
      event.preventDefault();
      mergeTurnUp(turn.id);
    }
  }
}

function splitTurnAtBoundary(turn, split, options = {}) {
  const index = state.turns.findIndex((candidate) => candidate.id === turn.id);
  if (index < 0) return;
  const before = cleanText(split.before);
  const after = cleanText(split.after);
  if (!before && !after) return;

  const wasPlaying = !audioIsPaused();
  const beforeState = revisionTurnState(turn);
  recordTurnPatchUndo(index, 2, [turn], turn.id);
  const originalWords = clonePayload(turn.words || []);
  const wordSplitIndex = Math.max(0, Math.min(originalWords.length, Number(split.wordSplitIndex) || 0));
  const beforeWords = originalWords.slice(0, wordSplitIndex);
  const afterWords = originalWords.slice(wordSplitIndex);
  const originalEnd = Number(turn.end_sec) || (Number(turn.start_sec) || 0) + 0.01;
  const originalStart = Number(turn.start_sec) || 0;
  const firstAfterStart = Number(afterWords[0]?.start_sec);
  const lastBeforeEnd = Number(beforeWords[beforeWords.length - 1]?.end_sec);
  const splitTime = Number(
    (
      Number.isFinite(firstAfterStart)
        ? firstAfterStart
        : Number.isFinite(lastBeforeEnd)
          ? lastBeforeEnd
          : ((originalStart + originalEnd) / 2)
    ).toFixed(3),
  );
  const safeSplitTime = Math.max(originalStart, Math.min(originalEnd, splitTime));
  const newStart = afterWords.length
    ? Math.max(originalStart, Number(afterWords[0].start_sec) || safeSplitTime)
    : safeSplitTime;
  const newEnd = afterWords.length
    ? Math.max(newStart + 0.01, Number(afterWords[afterWords.length - 1].end_sec) || originalEnd)
    : originalEnd;
  turn.text = before;
  turn.words = beforeWords;
  delete turn.editorLineTexts;
  turn.end_sec = beforeWords.length
    ? Math.max(originalStart + 0.01, Number(beforeWords[beforeWords.length - 1].end_sec) || safeSplitTime)
    : Math.max(originalStart + 0.01, safeSplitTime);
  if (!wordsMatchText(beforeWords, before)) {
    syncWordsFromText(turn);
  }

  const followingStart = Number(state.turns[index + 1]?.start_sec);
  const fallbackEnd = Number((newStart + 0.5).toFixed(3));
  const emptyTurnEnd = Number.isFinite(followingStart) && followingStart > newStart
    ? followingStart
    : fallbackEnd;
  const newTurn = normalizeTurn(
    {
      id: uniqueId("turn"),
      label: recommendedSplitSpeaker(turn),
      raw_speaker: turn.raw_speaker,
      start_sec: newStart,
      end_sec: Math.max(newStart + 0.01, after ? newEnd : emptyTurnEnd),
      text: after,
      words: afterWords,
    },
    index + 1,
  );
  if (!wordsMatchText(afterWords, after)) {
    syncWordsFromText(newTurn);
  }
  const focusText = options.focusText !== false;
  state.turns.splice(index + 1, 0, newTurn);
  // Keep the new internal boundary (turn -> newTurn) and the seams with the
  // neighbours consistent before the row is rendered and the revision snapshot taken.
  reconcileTurnNeighbors(newTurn.id);
  reconcileTurnNeighbors(turn.id);
  state.activeTurnId = newTurn.id;
  state.pendingFocusTurnId = focusText ? newTurn.id : "";
  pushRevisionEvent("split_turn", beforeState, { turns: [revisionTurnState(turn), revisionTurnState(newTurn)] }, {
    offset: split.offset,
  });
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  if (!renderSplitTurnPatch(turn, newTurn, { focusText })) {
    renderTurns({ scrollActive: false, focusTurnId: focusText ? newTurn.id : "", scrollAnchorTurnId: turn.id });
  }
  syncSplitPlaybackToTurn(newTurn, wasPlaying);
}

function splitTurnAtLineCaret(turn, element) {
  const split = textSplitAtLineCaret(element);
  if (!split) {
    splitTurnAtOffset(turn);
    return;
  }
  splitTurnAtBoundary(turn, {
    before: split.before,
    after: split.after,
    offset: turnOffsetFromLineCaret(element),
    wordSplitIndex: split.wordSplitIndex,
  });
}

function splitTurnAtOffset(turn, offset = null) {
  const text = turn.text;
  const splitOffset = Math.max(0, Math.min(text.length, offset == null ? Math.floor(text.length / 2) : offset));
  splitTurnAtBoundary(turn, {
    before: text.slice(0, splitOffset),
    after: text.slice(splitOffset),
    offset: splitOffset,
    wordSplitIndex: tokenCount(text.slice(0, splitOffset)),
  });
}

function splitTurnAtWordIndex(turn, index) {
  if (!turn?.words?.length) return false;
  const wordSplitIndex = Math.max(0, Math.min(Number(index) || 0, turn.words.length - 1));
  const beforeWords = turn.words.slice(0, wordSplitIndex);
  const afterWords = turn.words.slice(wordSplitIndex);
  splitTurnAtBoundary(turn, {
    before: textFromWords(beforeWords),
    after: textFromWords(afterWords),
    offset: textFromWords(beforeWords).length,
    wordSplitIndex,
  }, { focusText: false });
  return true;
}

function mergeTurnUp(turnId) {
  const index = state.turns.findIndex((turn) => turn.id === turnId);
  if (index <= 0) return;
  const previous = state.turns[index - 1];
  const current = state.turns[index];
  const before = { turns: [revisionTurnState(previous), revisionTurnState(current)] };
  recordTurnPatchUndo(index - 1, 1, [previous, current], current.id);
  previous.text = cleanText(`${previous.text} ${current.text}`);
  delete previous.editorLineTexts;
  previous.words = [...previous.words, ...current.words];
  refreshTurnTiming(previous);
  state.turns.splice(index, 1);
  state.selectedTurnIds.delete(current.id);
  if (state.selection.turnId === current.id) {
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  }
  reconcileTurnNeighbors(previous.id);
  state.activeTurnId = previous.id;
  state.pendingFocusTurnId = previous.id;
  pushRevisionEvent("merge_turn", before, revisionTurnState(previous));
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  if (!renderMergeTurnPatch(previous, current, { focusText: true })) {
    renderTurns({ scrollActive: false, focusTurnId: previous.id, scrollAnchorTurnId: previous.id });
  }
}

function mergeTurnDown(turnId) {
  const index = state.turns.findIndex((turn) => turn.id === turnId);
  if (index < 0 || index >= state.turns.length - 1) return;
  const current = state.turns[index];
  const next = state.turns[index + 1];
  const before = { turns: [revisionTurnState(current), revisionTurnState(next)] };
  recordTurnPatchUndo(index, 1, [current, next], current.id);
  current.text = cleanText(`${current.text} ${next.text}`);
  delete current.editorLineTexts;
  current.words = [...current.words, ...next.words];
  refreshTurnTiming(current);
  state.turns.splice(index + 1, 1);
  state.selectedTurnIds.delete(next.id);
  if (state.selection.turnId === next.id) {
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  }
  reconcileTurnNeighbors(current.id);
  state.activeTurnId = current.id;
  state.pendingFocusTurnId = current.id;
  pushRevisionEvent("merge_turn", before, revisionTurnState(current));
  refreshSearchMatches({ keepIndex: true });
  markDirty();
  if (!renderMergeTurnPatch(current, next, { focusText: true })) {
    renderTurns({ scrollActive: false, focusTurnId: current.id, scrollAnchorTurnId: current.id });
  }
}

function currentAudioTime() {
  return Number(els.audio.currentTime) || 0;
}

function visualAudioTime() {
  const time = currentAudioTime();
  return audioIsPaused() ? time : Math.max(0, time - state.settings.visualLatencySec);
}

function setAudioTime(time) {
  const duration = timelineDuration();
  const safeTime = Math.max(0, Math.min(duration, Number(time) || 0));
  els.audio.currentTime = safeTime;
}

function audioIsPaused() {
  return els.audio.paused;
}

async function playAudio() {
  await els.audio.play();
}

function pauseAudio() {
  els.audio.pause();
  updateTransportLabels();
}

function playTurn(turn) {
  if (!turn) return;
  setActiveTurn(turn.id, { scroll: false });
  if (!els.audio.src) return;
  setAudioTime(turn.start_sec);
  playAudio().catch(() => {});
}

function preservePitch() {
  const enabled = Boolean(state.settings.preservePitch);
  els.audio.preservesPitch = enabled;
  els.audio.mozPreservesPitch = enabled;
  els.audio.webkitPreservesPitch = enabled;
}

function applyPlaybackRate(rate) {
  const safeRate = normalizePlaybackRate(rate) || 1;
  preservePitch();
  els.audio.playbackRate = safeRate;
}

function timedWords(turn) {
  if (!turn || turn.timingReliable === false) return [];
  return (turn.words || [])
    .filter((word) => cleanText(word.text) && Number.isFinite(Number(word.start_sec)) && Number.isFinite(Number(word.end_sec)))
    .sort((left, right) => Number(left.start_sec) - Number(right.start_sec));
}

function wordAtTime(turn, time) {
  const words = timedWords(turn);
  if (!words.length || time < Number(words[0].start_sec)) return null;

  let current = null;
  for (const word of words) {
    const start = Number(word.start_sec);
    if (time < start) break;
    current = word;
  }
  if (!current) return null;

  const lastWordEnd = Number(words[words.length - 1].end_sec);
  return time <= lastWordEnd + 0.4 ? current : null;
}

// The audio loop calls globalWordAtTime ~60x/sec; scanning every turn/word each
// frame was O(n*m). Cache a start-sorted, flattened word index instead and binary
// search it. The index is invalidated by markDirty()/renderTurns() on any edit;
// playback itself never mutates words, so it is rebuilt at most once per edit.
function invalidateWordIndex() {
  state.wordIndex = null;
}

function buildWordIndex() {
  const entries = [];
  for (const turn of state.turns) {
    for (const word of timedWords(turn)) {
      entries.push({ start: Number(word.start_sec), end: Number(word.end_sec), turn, word });
    }
  }
  entries.sort((left, right) => left.start - right.start);
  // Prefix max-end lets the backward scan stop the instant no earlier word can
  // still reach `time`, so a lookup is O(log n) on tidy (non-overlapping) data.
  const maxEnd = new Array(entries.length);
  let running = -Infinity;
  for (let i = 0; i < entries.length; i += 1) {
    running = Math.max(running, entries[i].end);
    maxEnd[i] = running;
  }
  state.wordIndex = { entries, maxEnd };
  return state.wordIndex;
}

function globalWordAtTime(time) {
  const index = state.wordIndex || buildWordIndex();
  const { entries, maxEnd } = index;
  if (!entries.length) return null;
  let lo = 0;
  let hi = entries.length - 1;
  let idx = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (entries[mid].start <= time) {
      idx = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  // Walk back from the latest-starting word at or before `time`; the first word
  // that covers `time` has the greatest start (matching the old tie-break).
  for (let i = idx; i >= 0; i -= 1) {
    if (maxEnd[i] < time) break;
    const entry = entries[i];
    if (time >= entry.start && time <= entry.end) {
      return { turn: entry.turn, word: entry.word };
    }
  }
  return null;
}

function turnAtTime(time) {
  return state.turns.find((turn) => {
    const start = Number(turn.start_sec) || 0;
    const end = Number(turn.end_sec) || start;
    return time >= start && time <= end;
  }) || globalWordAtTime(time)?.turn || null;
}

function activePlaybackTurnIndex() {
  const activeIndex = state.turns.findIndex((turn) => turn.id === state.activeTurnId);
  if (activeIndex >= 0) return activeIndex;
  const timedTurn = turnAtTime(currentAudioTime());
  const timedIndex = state.turns.findIndex((turn) => turn.id === timedTurn?.id);
  return timedIndex >= 0 ? timedIndex : 0;
}

function playRelativeTurn(delta) {
  if (!state.turns.length) return false;
  const index = Math.max(0, Math.min(state.turns.length - 1, activePlaybackTurnIndex() + delta));
  const turn = state.turns[index];
  setActiveTurn(turn.id, { smooth: true });
  if (els.audio.src) {
    setAudioTime(turn.start_sec);
    playAudio().catch(() => {});
  }
  return true;
}

function selectPlaybackTurn() {
  const turn = turnAtTime(currentAudioTime()) || currentTurn();
  if (!turn) return false;
  setActiveTurn(turn.id, { smooth: true });
  return true;
}

function hoveredTurn() {
  const row = document.querySelector(".turn-row:hover");
  return row ? turnById(row.dataset.turnId) : null;
}

function selectHoveredTurn() {
  const turn = hoveredTurn();
  if (!turn) return false;
  setActiveTurn(turn.id, { scroll: false });
  return true;
}

function effectivePlaybackRate() {
  if (state.dragPlaybackRate !== null) return state.settings.slowPlaybackRate;
  if (state.textEditPlaybackSlow) return state.settings.slowPlaybackRate;
  if (state.roleMenuPlaybackSlow && state.settings.roleMenuBehavior === "slow") return state.settings.slowPlaybackRate;
  return state.globalPlaybackRate || 1;
}

function applyEffectivePlaybackRate() {
  applyPlaybackRate(effectivePlaybackRate());
  const rate = effectivePlaybackRate();
  if (els.speedValue) els.speedValue.textContent = `${rate.toFixed(2)}x`;
}

function setGlobalPlaybackRate(rate) {
  state.globalPlaybackRate = normalizePlaybackRate(rate) || 1;
  if (els.speedSlider) els.speedSlider.value = String(state.globalPlaybackRate);
  applyEffectivePlaybackRate();
}

async function loadSessions() {
  const payload = await fetchJson("/api/sessions");
  if (payload.role_options) DEFAULT_SPEAKERS.splice(0, DEFAULT_SPEAKERS.length, ...payload.role_options);
  state.sessions = payload.sessions || [];
  return state.sessions;
}

async function loadSession(name, options = {}) {
  if (!name) return;
  cancelWaveformDecode();
  const payload = await fetchJson(`/api/session/${encodeURIComponent(name)}`);
  if (payload.role_options) DEFAULT_SPEAKERS.splice(0, DEFAULT_SPEAKERS.length, ...payload.role_options);
  state.sessionName = payload.name;
  state.speakers = normalizeSpeakerList(payload.speakers);
  state.turns = (payload.turns || []).map(normalizeTurn);
  state.diarization = payload.diarization || [];
  state.activeTurnId = state.turns[0]?.id || "";
  state.finished = Boolean(payload.finished);
  state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  state.selectedTurnIds = new Set();
  state.lastSelectedTurnId = "";
  state.unrelatedPending = "";
  els.turnList.classList.remove("unrelated-pending-mode");
  cancelWordRangeSelection();
  state.wordRangeSelect.suppressClick = false;
  state.dirty = false;
  state.pendingAutosave = false;
  state.undoStack = [];
  state.redoStack = [];
  state.textEditSnapshotTurnId = "";
  state.textEditRevision = null;
  state.pendingRevisionEvents = [];
  state.revisionBaseline = revisionEditorState();
  state.revisionData = null;
  state.revisionRestorePair = { before: null, after: null };
  state.lastAutoCheckpointAt = Date.now();
  state.roleMenuPlaybackSlow = false;
  state.showBookmarkedOnly = false;
  state.waveform = null;
  if (options.activeTab) {
    // Make Review measurable before its one full render. Previously an explicit
    // Open rendered while hidden, then rendered the whole transcript again once
    // the tab became visible and its real width was known.
    setActiveTab(options.activeTab, { skipTurnRender: true });
  }

  state.selectedRecordingKey = payload.name;
  let waveformRequest = null;
  if (payload.audio?.available && payload.audio.url) {
    const audioVersion = encodeURIComponent(cleanText(payload.audio.version) || payload.name);
    els.audio.src = `${payload.audio.url}?v=${audioVersion}`;
    waveformRequest = {
      url: els.audio.src,
      durationSec: Number(payload.duration_sec) || 0,
      sizeBytes: Number(payload.audio.size_bytes) || 0,
    };
  } else {
    els.audio.removeAttribute("src");
  }

  refreshSearchMatches();
  renderTurns();
  resetTurnListScroll();
  drawTimeline();
  updateRecordingActions();
  updateTabAvailability();
  if (waveformRequest) scheduleWaveformDecode(waveformRequest);
}

async function saveSession(options = {}) {
  if (!state.sessionName) return;
  window.clearTimeout(state.autosaveTimer);
  state.saving = true;
  state.pendingAutosave = false;
  const revisionEvents = state.pendingRevisionEvents.slice();
  const now = Date.now();
  const autoCheckpointIntervalMs = Math.max(1, state.settings.autosaveCheckpointMinutes) * 60 * 1000;
  const shouldCheckpoint = options.auto === true
    ? now - state.lastAutoCheckpointAt >= autoCheckpointIntervalMs
    : true;
  let payload;
  try {
    payload = await fetchJson(`/api/session/${encodeURIComponent(state.sessionName)}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        speakers: normalizeSpeakerList(state.speakers),
        finished: state.finished,
        turns: state.turns,
        baseline: state.revisionBaseline,
        revision_events: revisionEvents,
        checkpoint: shouldCheckpoint,
        checkpoint_kind: options.auto === true ? "autosave" : "manual",
      }),
    });
  } finally {
    state.saving = false;
  }
  if (shouldCheckpoint) state.lastAutoCheckpointAt = now;
  state.pendingRevisionEvents = state.pendingRevisionEvents.slice(revisionEvents.length);
  if (state.pendingAutosave) {
    state.dirty = true;
    state.pendingAutosave = false;
    scheduleAutosave();
  } else {
    state.dirty = false;
  }
  state.revisionData = null;
  const stamp = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const session = state.sessions.find((candidate) => candidate.name === state.sessionName);
  if (session) session.finished = state.finished;
  updateRecordingActions();
  return payload;
}

function revisionStateLines(snapshot) {
  const turns = Array.isArray(snapshot?.turns) ? snapshot.turns : [];
  return turns.map((turn) => `${formatTime(turn.start_sec)} ${speakerLabel(turn.label)}: ${turn.text || ""}`);
}

function computeLineDiff(beforeLines, afterLines) {
  const m = beforeLines.length;
  const n = afterLines.length;
  const table = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i -= 1) {
    for (let j = n - 1; j >= 0; j -= 1) {
      table[i][j] = beforeLines[i] === afterLines[j]
        ? table[i + 1][j + 1] + 1
        : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }

  const rows = [];
  let i = 0;
  let j = 0;
  let beforeNumber = 1;
  let afterNumber = 1;
  while (i < m || j < n) {
    if (i < m && j < n && beforeLines[i] === afterLines[j]) {
      rows.push({ type: "same", beforeNumber: beforeNumber++, afterNumber: afterNumber++, before: beforeLines[i++], after: afterLines[j++] });
    } else if (j < n && (i >= m || table[i][j + 1] >= table[i + 1][j])) {
      rows.push({ type: "added", beforeNumber: "", afterNumber: afterNumber++, before: "", after: afterLines[j++] });
    } else if (i < m) {
      rows.push({ type: "removed", beforeNumber: beforeNumber++, afterNumber: "", before: beforeLines[i++], after: "" });
    }
  }
  return rows;
}

function revisionSnapshotRestorable(snapshot) {
  return Boolean(snapshot && Array.isArray(snapshot.turns));
}

function setRevisionRestorePair(before, after) {
  state.revisionRestorePair = { before: before || null, after: after || null };
  if (els.restoreRevisionBefore) {
    els.restoreRevisionBefore.disabled = !revisionSnapshotRestorable(before);
  }
  if (els.restoreRevisionAfter) {
    els.restoreRevisionAfter.disabled = !revisionSnapshotRestorable(after);
  }
}

function restoreRevisionSnapshot(snapshot, side = "selected") {
  if (!revisionSnapshotRestorable(snapshot)) return;
  const beforeState = revisionEditorState();
  recordUndo();
  state.restoringHistory = true;
  state.speakers = normalizeSpeakerList(snapshot.speakers);
  state.turns = clonePayload(snapshot.turns || []).map(normalizeTurn);
  state.finished = Boolean(snapshot.finished);
  state.activeTurnId = state.turns[0]?.id || "";
  state.lastSpeakerChange = null;
  state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
  state.selectedTurnIds = new Set();
  state.lastSelectedTurnId = "";
  cancelWordRangeSelection();
  state.wordRangeSelect.suppressClick = false;
  state.textEditSnapshotTurnId = "";
  state.textEditRevision = null;
  state.restoringHistory = false;
  const afterState = revisionEditorState();
  pushRevisionEvent("revision_restore", beforeState, afterState, { side });
  refreshSearchMatches({ keepIndex: true });
  renderTurns({ scrollActive: false });
  drawTimeline();
  markDirty(`Restored ${side} diff state`);
  updateRecordingActions();
  setActiveTab("review");
}

function restoreSelectedRevisionSide(side) {
  const snapshot = side === "before" ? state.revisionRestorePair.before : state.revisionRestorePair.after;
  restoreRevisionSnapshot(snapshot, side === "before" ? "left" : "right");
}

function showRevisionPair(before, after) {
  setRevisionRestorePair(before, after);
  const beforeLines = revisionStateLines(before);
  const afterLines = revisionStateLines(after);
  const rows = computeLineDiff(beforeLines, afterLines);
  els.revisionBefore.replaceChildren();
  els.revisionAfter.replaceChildren();

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "diff-empty";
    empty.textContent = "No text to compare.";
    els.revisionBefore.append(empty.cloneNode(true));
    els.revisionAfter.append(empty);
    return;
  }

  for (const row of rows) {
    const beforeRow = document.createElement("div");
    beforeRow.className = `diff-row ${row.type}`;
    beforeRow.innerHTML = `<span class="diff-line-number"></span><span class="diff-marker"></span><span class="diff-text"></span>`;
    beforeRow.querySelector(".diff-line-number").textContent = String(row.beforeNumber);
    beforeRow.querySelector(".diff-marker").textContent = row.type === "removed" ? "-" : " ";
    beforeRow.querySelector(".diff-text").textContent = row.before;

    const afterRow = document.createElement("div");
    afterRow.className = `diff-row ${row.type}`;
    afterRow.innerHTML = `<span class="diff-line-number"></span><span class="diff-marker"></span><span class="diff-text"></span>`;
    afterRow.querySelector(".diff-line-number").textContent = String(row.afterNumber);
    afterRow.querySelector(".diff-marker").textContent = row.type === "added" ? "+" : " ";
    afterRow.querySelector(".diff-text").textContent = row.after;

    els.revisionBefore.append(beforeRow);
    els.revisionAfter.append(afterRow);
  }
}

function renderRevisionPanel() {
  if (!els.revisionPanel) return;
  const snapshots = state.revisionData?.snapshots || {};
  const checkpoints = Array.isArray(snapshots.checkpoints) ? snapshots.checkpoints : [];
  els.revisionList.replaceChildren();

  const latestButton = document.createElement("button");
  latestButton.type = "button";
  latestButton.className = "revision-item";
  latestButton.innerHTML = "<strong>Baseline to Latest</strong><span>Current saved transcript</span>";
  latestButton.addEventListener("click", () => showRevisionPair(snapshots.baseline, snapshots.latest));
  els.revisionList.append(latestButton);

  checkpoints.slice().reverse().forEach((checkpoint, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "revision-item";
    const label = checkpoint.created_at ? new Date(checkpoint.created_at).toLocaleString() : `Checkpoint ${checkpoints.length - index}`;
    const kind = checkpoint.kind === "autosave" ? "Autosave" : "Manual save";
    button.innerHTML = "<strong></strong><span></span>";
    button.querySelector("strong").textContent = kind;
    button.querySelector("span").textContent = label;
    button.addEventListener("click", () => showRevisionPair(checkpoint.before, checkpoint.after));
    els.revisionList.append(button);
  });

  if (snapshots.baseline || snapshots.latest) {
    showRevisionPair(snapshots.baseline, snapshots.latest);
  } else {
    setRevisionRestorePair(null, null);
    els.revisionBefore.textContent = "No saved revision baseline yet.";
    els.revisionAfter.textContent = "Save the session to create revision snapshots.";
  }
}

async function loadRevisionData() {
  if (!state.sessionName) return;
  state.revisionData = await fetchJson(`/api/session/${encodeURIComponent(state.sessionName)}/revisions`);
  renderRevisionPanel();
}

async function toggleRevisionPanel() {
  if (!els.revisionPanel || !state.sessionName) return;
  setActiveTab("revisions");
  await loadRevisionData();
}

function setPipelineStatus(text) {
  els.pipelineStatus.textContent = text;
}

function formatElapsedSeconds(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
  }
  return minutes ? `${minutes}m ${String(rest).padStart(2, "0")}s` : `${rest}s`;
}

function fileIsActive(file) {
  return file?.status === "queued" || file?.status === "running";
}

function fileStageFraction(file) {
  if (file?.status !== "running" || !file.stage_number) return 0;
  const started = Number(file.stage_started) || 0;
  if (!started) return 0.08;
  const elapsed = Math.max(0, Date.now() / 1000 - started);
  const estimate = FILE_STAGE_ESTIMATE_SECONDS[file.stage_number - 1] || 90;
  return Math.min(0.9, Math.max(0.08, elapsed / estimate));
}

function fileProgressPercent(file) {
  const total = Math.max(1, Number(file?.stage_total) || FILE_STAGES.length);
  if (file?.status === "succeeded") return 100;
  const stage = Number(file?.stage_number) || 0;
  const completed = Math.max(0, stage - (file?.status === "running" ? 1 : 0));
  return Math.min(100, Math.round(((completed + fileStageFraction(file)) / total) * 100));
}

function fileElapsed(file) {
  const start = Number(file?.started) || Number(file?.queued_at) || 0;
  if (!start) return "";
  const end = Number(file?.finished) || Date.now() / 1000;
  return formatElapsedSeconds(end - start);
}

function fileStatusText(file) {
  if (!file) return "";
  if (file.status === "running") {
    if (!file.stage_number) return file.stage_label || "Starting";
    return `${file.stage_number}/${file.stage_total} ${FILE_STAGES[file.stage_number - 1] || file.stage_label}`;
  }
  return FILE_STATUS_LABELS[file.status] || file.status;
}

function activePipelineFiles() {
  return state.pipelineFiles.filter(fileIsActive);
}

function pipelineSummaryText() {
  const files = state.pipelineFiles;
  const running = files.filter((file) => file.status === "running").length;
  const queued = files.filter((file) => file.status === "queued").length;
  if (!running && !queued) {
    const failed = files.filter((file) => file.status === "failed").length;
    if (files.length && failed) return `Pipeline idle (${failed} failed)`;
    return "Pipeline idle";
  }
  const parts = [];
  if (running) parts.push(`${running} running`);
  if (queued) parts.push(`${queued} queued`);
  return `Pipeline: ${parts.join(", ")}`;
}

function renderLanes() {
  if (!els.pipelineLanes) return;
  const worker = state.pipelineWorker || {};
  const running = state.pipelineFiles.filter((file) => file.status === "running");
  const audio = running.find((file) => file.lane === "audio");
  const llm = running.filter((file) => file.lane === "llm");
  const starting = running.filter((file) => !file.lane);

  if (worker.alive) {
    const models = Array.isArray(worker.models) ? worker.models : [];
    els.laneWorkerText.textContent = models.length ? "Loaded" : "Loading";
    els.laneWorkerText.title = models.join(", ");
    els.laneWorker.classList.add("lane-active");
  } else {
    els.laneWorkerText.textContent = worker.last_exit?.reason ? "Released" : "Not loaded";
    els.laneWorkerText.title = worker.last_exit?.reason || "";
    els.laneWorker.classList.remove("lane-active");
  }
  if (audio) {
    els.laneAudioText.textContent = `${audio.name} · ${fileStatusText(audio)}`;
    els.laneAudio.classList.add("lane-active");
  } else if (starting.length) {
    els.laneAudioText.textContent = `${starting[0].name} · starting`;
    els.laneAudio.classList.add("lane-active");
  } else {
    els.laneAudioText.textContent = "Idle";
    els.laneAudio.classList.remove("lane-active");
  }
  if (llm.length) {
    const width = Number(worker.llm_concurrency) || llm.length;
    els.laneLlmText.textContent = `${llm.map((file) => `${file.name} · ${fileStatusText(file)}`).join("  |  ")}  (${llm.length}/${width})`;
    els.laneLlm.classList.add("lane-active");
  } else {
    els.laneLlmText.textContent = "Idle";
    els.laneLlm.classList.remove("lane-active");
  }
  if (els.releaseWorker) {
    els.releaseWorker.disabled = !worker.alive || running.length > 0 || activePipelineFiles().length > 0;
  }
}

function recordingForPipelineFile(file) {
  return state.recordings.find((recording) => inputPathMatches(file.input_path, recording.inputPath)) || null;
}

function renderFileCard(file) {
  const card = document.createElement("div");
  card.className = `file-card status-${file.status}${file.lane ? ` lane-${file.lane}` : ""}`;
  card.setAttribute("role", "listitem");
  card.dataset.file = file.name;

  const head = document.createElement("div");
  head.className = "file-card-head";
  const name = document.createElement("strong");
  name.textContent = file.name;
  name.title = file.input_path || file.name;
  const pill = document.createElement("span");
  pill.className = "file-pill";
  pill.textContent = FILE_STATUS_LABELS[file.status] || file.status;
  if (file.status === "running" && file.lane) pill.textContent += ` · ${file.lane === "llm" ? "LLM" : "Audio"}`;
  head.append(name, pill);

  const track = document.createElement("div");
  track.className = "file-stage-track";
  const total = Math.max(1, Number(file.stage_total) || FILE_STAGES.length);
  for (let index = 1; index <= total; index += 1) {
    const segment = document.createElement("span");
    segment.className = "file-stage";
    segment.title = FILE_STAGES[index - 1] || `Stage ${index}`;
    if (file.status === "succeeded" || index < file.stage_number) {
      segment.classList.add("done");
    } else if (index === file.stage_number) {
      segment.classList.add(file.status === "failed" ? "failed" : file.status === "running" ? "active" : "done");
      if (file.status === "running") segment.style.setProperty("--stage-fraction", `${Math.round(fileStageFraction(file) * 100)}%`);
    }
    track.append(segment);
  }

  const meta = document.createElement("div");
  meta.className = "file-card-meta";
  const stageText = document.createElement("span");
  stageText.textContent = fileStatusText(file);
  const elapsed = document.createElement("span");
  elapsed.textContent = fileElapsed(file);
  meta.append(stageText, elapsed);
  card.append(head, track, meta);

  const stats = file.stats || {};
  if (file.status === "succeeded" && Object.keys(stats).length) {
    const line = document.createElement("div");
    line.className = "file-card-stats";
    const parts = [];
    if (stats.turns != null) parts.push(`${stats.turns} turns`);
    if (stats.people != null) parts.push(`${stats.people} people`);
    if (stats.department) parts.push(String(stats.department));
    line.textContent = parts.join(" · ");
    card.append(line);
  }
  if (file.error) {
    const error = document.createElement("div");
    error.className = "file-card-error";
    error.textContent = file.error;
    card.append(error);
  }

  const recording = recordingForPipelineFile(file);
  if (file.status === "succeeded" && recording && recordingReviewReady(recording)) {
    const open = document.createElement("button");
    open.type = "button";
    open.className = "file-card-action";
    open.textContent = "Open";
    open.addEventListener("click", () => {
      state.selectedRecordingKey = recording.key;
      openSelectedRecording({ tab: "review" }).catch((error) => showErrorNotice(error));
    });
    card.append(open);
  } else if ((file.status === "failed" || file.status === "awaiting_resume") && recording?.hasInput) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "file-card-action";
    retry.textContent = file.status === "awaiting_resume" ? "Resume" : "Retry";
    retry.addEventListener("click", () => {
      runPipeline(recording.inputPath).catch((error) => setPipelineStatus(error.message));
    });
    card.append(retry);
  }
  card.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    state.pipelineLogFilter = state.pipelineLogFilter === file.name ? "" : file.name;
    renderPipelineLog();
    renderPipelineFiles();
  });
  if (state.pipelineLogFilter === file.name) card.classList.add("selected");
  return card;
}

function renderPipelineFiles() {
  if (!els.pipelineFileGrid) return;
  els.pipelineFileGrid.replaceChildren();
  const files = state.pipelineFiles.slice().reverse();
  if (!files.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact";
    empty.textContent = "No files queued";
    els.pipelineFileGrid.append(empty);
    return;
  }
  for (const file of files) {
    els.pipelineFileGrid.append(renderFileCard(file));
  }
}

function renderPipelineLog() {
  if (!els.pipelineLogList) return;
  if (els.pipelineLogFilter) {
    const names = Array.from(new Set(state.pipelineFiles.map((file) => file.name)));
    const current = els.pipelineLogFilter.value;
    els.pipelineLogFilter.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "All files";
    els.pipelineLogFilter.append(all);
    for (const name of names) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      els.pipelineLogFilter.append(option);
    }
    els.pipelineLogFilter.value = names.includes(state.pipelineLogFilter) ? state.pipelineLogFilter : "";
    if (els.pipelineLogFilter.value !== current && !names.includes(state.pipelineLogFilter)) state.pipelineLogFilter = "";
  }
  els.pipelineLogList.replaceChildren();
  const filter = state.pipelineLogFilter;
  const lines = state.pipelineLog.filter((entry) => !filter || entry.file === filter || (!entry.file && !filter)).slice(-160);
  if (!lines.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact";
    empty.textContent = filter ? `No log lines for ${filter} yet.` : "No activity";
    els.pipelineLogList.append(empty);
    return;
  }
  const stuckToBottom = els.pipelineLogList.scrollHeight - els.pipelineLogList.scrollTop - els.pipelineLogList.clientHeight < 40;
  for (const entry of lines) {
    const logLine = document.createElement("div");
    logLine.className = "pipeline-log-line";
    logLine.textContent = filter ? String(entry.line).replace(`[${filter}] `, "") : entry.line;
    els.pipelineLogList.append(logLine);
  }
  if (stuckToBottom || filter) els.pipelineLogList.scrollTop = els.pipelineLogList.scrollHeight;
}

async function loadInputFiles() {
  const payload = await fetchJson("/api/input-files");
  state.inputFiles = payload.files || [];
  return state.inputFiles;
}

function updateCurrentRecordingLabels() {
  const name = state.sessionName || selectedRecording()?.name || "";
  const label = name ? recordingDisplayName(name) : "No recording loaded";
  if (els.reviewRecordingName) els.reviewRecordingName.textContent = label;
  if (els.diffRecordingName) {
    els.diffRecordingName.textContent = name
      ? `Manual revision history for ${recordingDisplayName(name)}`
      : "Select a reviewed recording from the Dashboard to inspect changes.";
  }
}

function dashboardStats() {
  const total = state.recordings.length;
  const ready = state.recordings.filter((recording) => recordingReviewReady(recording) && !recording.session?.finished).length;
  const finished = state.recordings.filter((recording) => recording.session?.finished).length;
  const needsPipeline = state.recordings.filter((recording) => recordingProcessingVisible(recording)).length;
  return [
    ["Total", total],
    ["Needs pipeline", needsPipeline],
    ["Ready", ready],
    ["Finished", finished],
  ];
}

function renderDashboard() {
  if (!els.recordingTable) return;
  els.dashboardStats.replaceChildren();
  for (const [label, value] of dashboardStats()) {
    const item = document.createElement("div");
    item.className = "stat-pill";
    item.innerHTML = `<span></span><strong></strong>`;
    item.querySelector("span").textContent = label;
    item.querySelector("strong").textContent = String(value);
    els.dashboardStats.append(item);
  }

  els.recordingTable.replaceChildren();
  els.dashboardEmpty.hidden = state.recordings.length > 0;
  els.recordingTable.hidden = state.recordings.length === 0;
  if (!state.recordings.length) return;

  const header = document.createElement("div");
  header.className = "recording-row recording-header";
  ["Select", "Recording", "State", "Length", "Size", "Imported", "Last Edit", "Next Step", "Action"].forEach((label) => {
    const cell = document.createElement("div");
    cell.textContent = label;
    header.append(cell);
  });
  els.recordingTable.append(header);

  for (const recording of state.recordings) {
    const row = document.createElement("div");
    row.className = "recording-row";
    row.dataset.recordingKey = recording.key;
    if (recording.name === state.sessionName) row.classList.add("selected");

    const status = recordingStatus(recording);
    const nextStep = recording.session?.state === "error"
      ? "Remove broken state or restore files"
      : recordingCannotResume(recording)
      ? "Remove or restore audio"
      : recording.session?.state === "awaiting_resume"
      ? "Await resume"
      : recording.session?.finished
      ? "Finished"
      : recordingReviewReady(recording)
        ? "Open recording"
        : recording.hasInput
          ? "Run analysis"
          : "Missing audio";
    const imported = recording.inputFile ? formatDateTime(recording.inputFile.modified) : "No input";
    const lastEdit = recording.session ? formatDateTime(recording.session.modified) : "No edits";
    const audioLength = formatAudioLength(recording.inputDurationSec);
    const audioSize = formatFileSize(recording.inputSize);

    const nameCell = document.createElement("div");
    nameCell.className = "recording-name-cell";
    nameCell.innerHTML = `<strong></strong>`;
    nameCell.querySelector("strong").textContent = recording.name;

    const statusCell = document.createElement("div");
    const badge = document.createElement("span");
    badge.className = `status-badge ${statusClass(status)}`;
    badge.textContent = status;
    statusCell.append(badge);

    const lengthCell = document.createElement("div");
    lengthCell.textContent = audioLength;
    const sizeCell = document.createElement("div");
    sizeCell.textContent = audioSize;
    const importedCell = document.createElement("div");
    importedCell.textContent = imported;
    const editedCell = document.createElement("div");
    editedCell.textContent = lastEdit;
    const reviewCell = document.createElement("div");
    reviewCell.textContent = nextStep;

    const selectCell = document.createElement("div");
    selectCell.className = "recording-select-cell";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedRecordingKeys.has(recording.key);
    checkbox.title = `Select ${recording.name}`;
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => toggleRecordingSelection(recording.key, checkbox.checked));
    selectCell.append(checkbox);

    const actions = document.createElement("div");
    actions.className = "recording-actions";
    const actionButton = document.createElement("button");
    let secondaryActionButton = null;
    actionButton.type = "button";
    if (recording.session?.state === "error") {
      actionButton.textContent = "Remove";
      actionButton.className = "danger-button";
      actionButton.addEventListener("click", (event) => {
        event.stopPropagation();
        clearRecordings([recording]).catch((error) => showErrorNotice(error));
      });
    } else if (recordingCannotResume(recording)) {
      actionButton.textContent = "Remove";
      actionButton.className = "danger-button";
      actionButton.addEventListener("click", (event) => {
        event.stopPropagation();
        clearRecordings([recording]).catch((error) => showErrorNotice(error));
      });
    } else if (recordingNeedsResume(recording)) {
      actionButton.textContent = recordingIsQueued(recording) ? "Queued" : recordingIsRunning(recording) ? "Running" : "Resume";
      actionButton.disabled = !recording.hasInput || recordingIsQueued(recording) || recordingIsRunning(recording);
      actionButton.addEventListener("click", (event) => {
        event.stopPropagation();
        state.selectedRecordingKey = recording.key;
        runSelectedPipeline().catch((error) => setPipelineStatus(error.message));
      });
    } else if (recordingReviewReady(recording)) {
      actionButton.textContent = "Open";
      actionButton.disabled = false;
      actionButton.addEventListener("click", (event) => {
        event.stopPropagation();
        state.selectedRecordingKey = recording.key;
        openSelectedRecording({ tab: "review" }).catch((error) => showErrorNotice(error));
      });
      if (recording.hasInput && !recordingIsQueued(recording) && !recordingIsRunning(recording)) {
        const reprocessButton = document.createElement("button");
        reprocessButton.type = "button";
        reprocessButton.textContent = "Reprocess";
        reprocessButton.addEventListener("click", (event) => {
          event.stopPropagation();
          reprocessRecordings([recording]).catch((error) => setPipelineStatus(error.message));
        });
        secondaryActionButton = reprocessButton;
      }
    } else {
      actionButton.textContent = recordingIsQueued(recording) ? "Queued" : recordingIsRunning(recording) ? "Running" : "Process";
      actionButton.disabled = !recording.hasInput || recordingIsQueued(recording) || recordingIsRunning(recording);
      actionButton.addEventListener("click", (event) => {
        event.stopPropagation();
        state.selectedRecordingKey = recording.key;
        runSelectedPipeline().catch((error) => setPipelineStatus(error.message));
      });
    }
    actions.append(actionButton);
    if (secondaryActionButton) actions.append(secondaryActionButton);

    row.append(selectCell, nameCell, statusCell, lengthCell, sizeCell, importedCell, editedCell, reviewCell, actions);
    row.addEventListener("click", () => {
      state.selectedRecordingKey = recording.key;
      if (recordingCannotResume(recording)) {
        updateRecordingActions();
        setActiveTab("processing");
      } else if (recordingNeedsResume(recording)) {
        openSelectedRecording({ tab: "processing" }).catch((error) => showErrorNotice(error));
      } else if (recordingReviewReady(recording)) {
        openSelectedRecording({ tab: "review" }).catch((error) => showErrorNotice(error));
      } else {
        updateRecordingActions();
      }
    });
    els.recordingTable.append(row);
  }
}

function renderProcessing() {
  if (!els.processingBacklogList || !els.pipelineFileGrid || !els.pipelineLogList) return;
  els.processingBacklogList.replaceChildren();
  const backlog = state.recordings.filter((recording) => recordingProcessingVisible(recording));
  if (!backlog.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact";
    empty.textContent = "No recordings to process";
    els.processingBacklogList.append(empty);
  } else {
    for (const recording of backlog) {
      const item = document.createElement("div");
      item.className = "queue-item backlog-item";
      item.innerHTML = `<div><strong></strong></div>`;
      item.querySelector("strong").textContent = recording.name;
      const runButton = document.createElement("button");
      runButton.type = "button";
      if (recordingCannotResume(recording)) {
        runButton.textContent = "Remove";
        runButton.className = "danger-button";
        runButton.addEventListener("click", () => {
          clearRecordings([recording]).catch((error) => showErrorNotice(error));
        });
      } else {
        runButton.textContent = recordingIsQueued(recording)
          ? "Queued"
          : recordingIsRunning(recording)
            ? "Running"
            : recordingNeedsResume(recording)
              ? "Resume"
              : "Queue";
        runButton.disabled = !recording.hasInput || recordingIsQueued(recording) || recordingIsRunning(recording);
        runButton.addEventListener("click", () => {
          state.selectedRecordingKey = recording.key;
          runSelectedPipeline().catch((error) => setPipelineStatus(error.message));
        });
      }
      item.append(runButton);
      els.processingBacklogList.append(item);
    }
  }
  renderLanes();
  renderPipelineFiles();
  renderPipelineLog();
}

function updateRecordingActions() {
  const recording = selectedRecording();
  pruneSelectedRecordings();
  const selectedCount = selectedRecordings().length;
  const unprocessedCount = unprocessedRecordings().length;
  els.runInputFolder.disabled = unprocessedCount === 0;
  els.runInputFolder.textContent = unprocessedCount
    ? `Run All Unprocessed (${unprocessedCount})`
    : "Run All Unprocessed";
  els.saveButton.disabled = !state.sessionName;
  els.toggleFinished.disabled = !state.sessionName;
  els.exportTranscript.disabled = !state.sessionName;
  els.showRevisions.disabled = !state.sessionName;
  els.selectAllRecordings.disabled = state.recordings.length === 0;
  els.clearRecordingSelection.disabled = selectedCount === 0;
  els.importAudioButton.disabled = false;
  els.refreshSessions.disabled = refreshBusyCount > 0;
  els.activeSpeaker.disabled = !state.sessionName;
  els.openSpeakerDialog.disabled = !state.sessionName;
  els.openBulkDialog.disabled = !state.sessionName || selectedTurns().length === 0;
  updateFinishedControls();
  updateCurrentRecordingLabels();
  updateTabAvailability();
  renderDashboard();
  renderProcessing();
}

function renderRecordings(preferredKey = "") {
  state.recordings = buildRecordings();
  if (!state.recordings.length) {
    state.selectedRecordingKey = "";
    updateRecordingActions();
    return;
  }
  const preferred = preferredKey || state.sessionName || state.selectedRecordingKey;
  const fallback = state.recordings.find((recording) => recordingReviewReady(recording)) || state.recordings[0];
  state.selectedRecordingKey = state.recordings.some((recording) => recording.key === preferred) ? preferred : fallback.key;
  updateRecordingActions();
}

let refreshBusyCount = 0;

function setRefreshBusy(busy) {
  if (!els.refreshSessions) return;
  els.refreshSessions.disabled = busy;
  els.refreshSessions.classList.toggle("refreshing", busy);
  els.refreshSessions.textContent = busy ? "Refreshing" : "Refresh";
}

// Run one listing loader, retrying briefly: a transient failure must not blank
// the dashboard or force the user to hammer the Refresh button.
async function loadListing(loader) {
  let lastError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return { ok: true, value: await loader() };
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => window.setTimeout(resolve, 300 * (attempt + 1)));
    }
  }
  return { ok: false, error: lastError };
}

async function refreshRecordings(options = {}) {
  const preferredKey = options.preferredKey || state.sessionName || state.selectedRecordingKey;
  refreshBusyCount += 1;
  setRefreshBusy(true);
  try {
    const [sessionsResult, inputsResult] = await Promise.all([
      loadListing(loadSessions),
      loadListing(loadInputFiles),
    ]);
    // Loaders store into state on success; render whatever we have so a partial
    // failure degrades to stale-but-visible data instead of an empty dashboard.
    renderRecordings(preferredKey);

    const failure = [sessionsResult, inputsResult].find((result) => !result.ok);
    if (failure) {
      await showNotice(`Refresh failed: ${failure.error?.message || "request failed"}. Press Refresh to retry.`, "Error");
      return;
    }

    const recording = selectedRecording();
    if (options.openSelected !== false && recordingReviewReady(recording) && !state.dirty) {
      await loadSession(recording.name);
      return;
    }

    if (!state.turns.length) renderTurns();
    if (!state.dirty) {
      const errorCount = state.recordings.filter((candidate) => candidate.session?.state === "error").length;
    }
  } finally {
    refreshBusyCount -= 1;
    if (refreshBusyCount <= 0) {
      refreshBusyCount = 0;
      setRefreshBusy(false);
    }
  }
}

async function openSelectedRecording(options = {}) {
  const recording = selectedRecording();
  updateRecordingActions();
  if (!recording) {
    return;
  }
  if (recordingCannotResume(recording)) {
    state.sessionName = "";
    state.turns = [];
    state.speakers = normalizeSpeakerList([]);
    state.diarization = [];
    state.activeTurnId = "";
    state.finished = false;
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
    state.selectedTurnIds = new Set();
    state.lastSelectedTurnId = "";
    state.showBookmarkedOnly = false;
    state.dirty = false;
    els.audio.removeAttribute("src");
    renderTurns();
    updateCurrentRecordingLabels();
    updateTabAvailability();
    setActiveTab("processing");
    return;
  }
  if (recordingNeedsResume(recording)) {
    state.sessionName = "";
    state.turns = [];
    state.speakers = normalizeSpeakerList([]);
    state.diarization = [];
    state.activeTurnId = "";
    state.finished = false;
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
    state.selectedTurnIds = new Set();
    state.lastSelectedTurnId = "";
    state.showBookmarkedOnly = false;
    state.dirty = false;
    els.audio.removeAttribute("src");
    renderTurns();
    updateCurrentRecordingLabels();
    updateTabAvailability();
    setActiveTab("processing");
    return;
  }
  if (state.dirty && recording.name !== state.sessionName) {
    const discard = await showModal({
      title: "Discard Unsaved Changes",
      message: "Open another recording and discard the current unsaved editor changes?",
      confirmText: "Discard",
      cancelText: "Stay",
      danger: true,
    });
    if (!discard) {
      state.selectedRecordingKey = state.sessionName;
      updateRecordingActions();
      return;
    }
  }
  if (!recordingReviewReady(recording)) {
    state.sessionName = "";
    state.turns = [];
    state.speakers = normalizeSpeakerList([]);
    state.diarization = [];
    state.activeTurnId = "";
    state.finished = false;
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
    state.selectedTurnIds = new Set();
    state.lastSelectedTurnId = "";
    state.showBookmarkedOnly = false;
    state.dirty = false;
    els.audio.removeAttribute("src");
    renderTurns();
    updateCurrentRecordingLabels();
    updateTabAvailability();
    if (options.tab) setActiveTab(options.tab);
    return;
  }
  await loadSession(recording.name, { activeTab: options.tab });
  if (options.tab && state.activeTab !== options.tab) setActiveTab(options.tab);
}

function renderPipelineJob(job) {
  state.currentJob = job || null;
  state.pipelineRunning = activePipelineFiles().length > 0;
  setPipelineStatus(pipelineSummaryText());
  updateRecordingActions();
  renderProcessing();

  // A page opened while files are in flight must keep tracking them even
  // though this session never called runPipeline.
  if (state.pipelineRunning && !state.jobPoll) {
    startJobPolling();
  }
  if (!state.pipelineRunning && state.jobPoll) {
    window.clearInterval(state.jobPoll);
    state.jobPoll = 0;
  }
}

function renderPipelineStatus(payload = {}) {
  state.pipelineQueue = Array.isArray(payload.queue) ? payload.queue : [];
  state.pipelineFiles = Array.isArray(payload.files) ? payload.files : [];
  state.pipelineWorker = payload.worker || {};
  state.pipelineLog = Array.isArray(payload.log) ? payload.log : [];

  // Refresh the recordings table once per newly finished file so a transcript
  // becomes openable the moment its LLM lane completes, not when the batch ends.
  let newlyFinished = 0;
  for (const file of state.pipelineFiles) {
    if (fileIsActive(file)) continue;
    const key = `${file.name}:${file.finished || 0}`;
    if (!state.pipelineSeenFinished.has(key)) {
      state.pipelineSeenFinished.add(key);
      if (file.finished) newlyFinished += 1;
    }
  }
  const lastFinished = payload.last_finished;
  if (lastFinished?.id && lastFinished.id !== state.lastFinishedJobId) {
    state.lastFinishedJobId = lastFinished.id;
    newlyFinished += 1;
  }
  if (newlyFinished) {
    refreshRecordings({ openSelected: false }).catch((error) => showErrorNotice(error));
  }
  renderPipelineJob(payload.job || null);
}

function recordingsMissingSessions() {
  return unprocessedRecordings();
}

async function pollPipelineJob() {
  const payload = await fetchJson("/api/pipeline/job");
  renderPipelineStatus(payload);
}

function startJobPolling() {
  window.clearInterval(state.jobPoll);
  state.jobPoll = window.setInterval(() => {
    pollPipelineJob().catch((error) => setPipelineStatus(error.message));
  }, 1000);
}

async function runPipeline(inputPath, options = {}) {
  const reprocess = options.reprocess === true;
  setActiveTab("processing");
  setPipelineStatus(reprocess ? "Starting reprocess" : "Starting pipeline");
  const payload = await fetchJson("/api/pipeline/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_path: inputPath || "", reprocess }),
  });
  state.activeJobId = payload.job?.id || 0;
  renderPipelineStatus(payload);
  if (payload.queued) {
    setPipelineStatus(`Queued ${payload.queued.name || "recording"}${payload.queued.reprocess ? " for reprocess" : ""}`);
  } else if (payload.already_queued) {
    setPipelineStatus("Recording is already queued");
  } else if (payload.already_running) {
    setPipelineStatus("Recording is already running");
  }
  startJobPolling();
}

async function releasePipelineWorker() {
  const payload = await fetchJson("/api/pipeline/worker/release", { method: "POST" });
  state.pipelineWorker = payload.worker || {};
  renderLanes();
  setPipelineStatus(payload.released ? "Models released" : "No resident models to release");
}

function resumeLabelFor(recording) {
  if (recordingCannotResume(recording)) return "resume pipeline";
  return recordingNeedsResume(recording) ? "resume pipeline" : "run pipeline";
}

async function runSelectedPipeline() {
  const recording = selectedRecording();
  if (recordingCannotResume(recording)) {
    setPipelineStatus("Cannot resume because the input audio is absent");
    return;
  }
  if (!recording?.hasInput) {
    setPipelineStatus(`Cannot ${resumeLabelFor(recording)} without input audio`);
    return;
  }
  if (!(await confirmPipelineRun(recording))) return;
  await runPipeline(recording.inputPath);
}

async function confirmReprocessRecordings(recordings) {
  const processedCount = recordings.filter(recordingHasProcessedFiles).length;
  if (!processedCount && !state.dirty) return true;
  const names = recordings.slice(0, 3).map((recording) => recording.name).join(", ");
  const extra = recordings.length > 3 ? ` and ${recordings.length - 3} more` : "";
  const dirtyWarning = state.dirty ? " Unsaved editor changes may be discarded." : "";
  return showModal({
    title: recordings.length === 1 ? "Reprocess Recording" : "Reprocess Recordings",
    message: `Reprocess ${recordings.length} selected recording${recordings.length === 1 ? "" : "s"} (${names}${extra})? Existing transcript artifacts for ${processedCount} recording${processedCount === 1 ? "" : "s"} will be replaced.${dirtyWarning}`,
    confirmText: "Reprocess",
    cancelText: "Cancel",
    danger: processedCount > 0,
  });
}

async function reprocessRecordings(recordings = selectedRecordings()) {
  const candidates = reprocessableRecordings(recordings);
  if (!candidates.length) {
    setPipelineStatus("Select recordings with input audio to reprocess");
    return;
  }
  if (!(await confirmReprocessRecordings(candidates))) return;
  setActiveTab("processing");
  for (const recording of candidates) {
    await runPipeline(recording.inputPath, { reprocess: true });
  }
  setPipelineStatus(`Queued ${candidates.length} recording${candidates.length === 1 ? "" : "s"} for reprocess`);
}

async function runAllUnprocessed() {
  const candidates = unprocessedRecordings();
  if (!candidates.length) {
    setPipelineStatus("No unprocessed audio to run");
    return;
  }
  setActiveTab("processing");
  for (const recording of candidates) {
    await runPipeline(recording.inputPath);
  }
  setPipelineStatus(`Queued ${candidates.length} unprocessed recording${candidates.length === 1 ? "" : "s"}`);
}

async function runSelectedUnprocessed() {
  const candidates = runnableSelectedRecordings();
  if (!candidates.length) {
    setPipelineStatus("Select imported audio that still needs diarization");
    return;
  }
  setActiveTab("processing");
  for (const recording of candidates) {
    await runPipeline(recording.inputPath);
  }
  setPipelineStatus(`Queued ${candidates.length} selected recording${candidates.length === 1 ? "" : "s"} for analysis`);
}

async function uploadAudioFile(file, { allowDuplicate = false } = {}) {
  const query = `filename=${encodeURIComponent(file.name)}${allowDuplicate ? "&allow_duplicate=1" : ""}`;
  const payload = await fetchJson(`/api/input-files/upload?${query}`, {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  return payload.file || {};
}

// Ask which byte-identical uploads should be stored anyway, naming the recording
// each one matches. Resolves to the confirmed files (empty when the user declines).
async function confirmDuplicateImports(duplicates) {
  if (!duplicates.length) return [];
  const chosen = new Set(duplicates.map((entry) => entry.file));
  const confirmed = await showModal({
    title: "Audio Already Imported",
    message: `${duplicates.length === 1 ? "This file is" : "These files are"} byte-identical to audio already in the input folder. Tick the ones to import again as separate recordings.`,
    confirmText: "Import Ticked",
    cancelText: "Skip All",
    build: (body) => {
      for (const entry of duplicates) {
        const existing = entry.existing;
        const row = document.createElement("label");
        row.className = "modal-note modal-duplicate";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = true;
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) chosen.add(entry.file);
          else chosen.delete(entry.file);
        });
        const text = document.createElement("span");
        const uploaded = document.createElement("strong");
        uploaded.textContent = entry.file.name;
        const detail = document.createElement("span");
        const imported = existing.modified ? `, imported ${formatDateTime(existing.modified)}` : "";
        detail.textContent = ` matches ${existing.name || recordingNameForInput(existing)} (${formatFileSize(existing.size)}${imported})`;
        text.append(uploaded, detail);
        row.append(checkbox, text);
        body.append(row);
      }
    },
  });
  if (!confirmed) return [];
  return duplicates.map((entry) => entry.file).filter((file) => chosen.has(file));
}

async function uploadAudioFiles(files) {
  const audioFiles = Array.from(files || []);
  if (!audioFiles.length) return;

  let lastImported = null;
  const duplicates = [];
  for (const file of audioFiles) {
    const info = await uploadAudioFile(file);
    if (info.duplicate) duplicates.push({ file, existing: info });
    else lastImported = info;
  }

  for (const file of await confirmDuplicateImports(duplicates)) {
    lastImported = await uploadAudioFile(file, { allowDuplicate: true });
  }

  const preferredKey = lastImported ? recordingNameForInput(lastImported) : "";
  await refreshRecordings({ preferredKey, openSelected: false });
}

async function exportTranscript() {
  if (!state.sessionName) {
    return;
  }
  if (state.dirty) {
    await saveSession();
  }
  const link = document.createElement("a");
  link.href = `/api/session/${encodeURIComponent(state.sessionName)}/final-transcript?v=${Date.now()}`;
  link.download = `${state.sessionName}_aligned_transcript.txt`;
  document.body.append(link);
  link.click();
  link.remove();
}

async function exportAllFinished() {
  if (state.dirty) {
    await saveSession();
  }
  await loadSessions();
  updateRecordingActions();
  const finished = selectedFinishedRecordings();
  const count = finished.length;
  if (!count) {
    return;
  }

  const link = document.createElement("a");
  const names = finished.map((recording) => recording.name).join(",");
  link.href = `/api/sessions/final-transcripts.zip?names=${encodeURIComponent(names)}&v=${Date.now()}`;
  link.download = "mediscribe_selected_aligned_transcripts.zip";
  document.body.append(link);
  link.click();
  link.remove();
}

async function clearRecordings(recordings = selectedRecordings()) {
  const selected = recordings.filter(Boolean);
  if (!selected.length) {
    return;
  }
  const confirmed = await showModal({
    title: "Clear Recording Data",
    message: `Delete the imported audio, working files, and transcript for ${selected.length} selected recording${selected.length === 1 ? "" : "s"}?`,
    confirmText: "Clear Selected",
    cancelText: "Cancel",
    danger: true,
  });
  if (!confirmed) {
    return;
  }
  const names = selected.map((recording) => recording.name);
  const payload = await fetchJson("/api/cache/clear-selected", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: "DELETE", names }),
  });
  if (names.includes(state.sessionName)) {
    state.sessionName = "";
    state.turns = [];
    state.speakers = [];
    state.diarization = [];
    state.activeTurnId = "";
    state.finished = false;
    state.selection = { turnId: "", wordIds: new Set(), anchorIndex: -1 };
    state.selectedTurnIds = new Set();
    state.lastSelectedTurnId = "";
    els.audio.removeAttribute("src");
  }
  state.selectedRecordingKeys = new Set();
  state.pipelineQueue = [];
  state.pipelineQueueActive = false;
  state.search = { query: "", matches: [], index: -1 };
  state.undoStack = [];
  state.redoStack = [];
  state.lastSpeakerChange = null;
  state.showBookmarkedOnly = false;
  state.dirty = false;
  els.searchInput.value = "";
  els.replaceInput.value = "";
  await refreshRecordings({ openSelected: false });
  const removed = payload.removed || {};
}

async function clearCache() {
  await clearRecordings(selectedRecordings());
}

let waveformLoadGeneration = 0;
let waveformAbortController = null;
let waveformIdleHandle = 0;
let waveformIdleIsTimeout = false;

function cancelWaveformDecode() {
  waveformLoadGeneration += 1;
  if (waveformAbortController) waveformAbortController.abort();
  waveformAbortController = null;
  if (waveformIdleHandle) {
    if (waveformIdleIsTimeout) window.clearTimeout(waveformIdleHandle);
    else window.cancelIdleCallback?.(waveformIdleHandle);
  }
  waveformIdleHandle = 0;
  waveformIdleIsTimeout = false;
}

function scheduleWaveformDecode({ url, durationSec = 0, sizeBytes = 0 }) {
  cancelWaveformDecode();
  state.waveform = null;
  if (
    durationSec > MAX_EAGER_WAVEFORM_DURATION_SEC
    || sizeBytes > MAX_EAGER_WAVEFORM_BYTES
  ) {
    drawTimeline();
    return;
  }

  const generation = waveformLoadGeneration;
  const start = () => {
    waveformIdleHandle = 0;
    waveformIdleIsTimeout = false;
    if (generation !== waveformLoadGeneration) return;
    decodeWaveform(url, { generation });
  };
  if (typeof window.requestIdleCallback === "function") {
    waveformIdleHandle = window.requestIdleCallback(start, { timeout: 1500 });
  } else {
    waveformIdleIsTimeout = true;
    waveformIdleHandle = window.setTimeout(start, 0);
  }
}

async function decodeWaveform(url, { generation = waveformLoadGeneration } = {}) {
  const controller = new AbortController();
  waveformAbortController = controller;
  let audioContext = null;
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`Waveform audio request failed (${response.status})`);
    const arrayBuffer = await response.arrayBuffer();
    if (generation !== waveformLoadGeneration) return;
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    if (generation !== waveformLoadGeneration) return;
    const channel = audioBuffer.getChannelData(0);
    const sampleCount = Math.min(WAVEFORM_BUCKET_COUNT, Math.max(1, channel.length));
    const blockSize = Math.max(1, Math.ceil(channel.length / sampleCount));
    const stride = Math.max(1, Math.ceil(blockSize / MAX_WAVEFORM_SAMPLES_PER_BUCKET));
    const peaks = [];
    for (let i = 0; i < sampleCount; i += 1) {
      let peak = 0;
      const start = i * blockSize;
      const end = Math.min(channel.length, start + blockSize);
      for (let j = start; j < end; j += stride) {
        peak = Math.max(peak, Math.abs(channel[j]));
      }
      peaks.push(peak);
    }
    if (generation !== waveformLoadGeneration) return;
    state.waveform = peaks;
    drawTimeline();
  } catch (error) {
    if (error?.name === "AbortError" || generation !== waveformLoadGeneration) return;
    state.waveform = null;
    drawTimeline();
  } finally {
    if (waveformAbortController === controller) waveformAbortController = null;
    if (typeof audioContext?.close === "function") audioContext.close().catch(() => {});
  }
}

function timelineDuration() {
  return Math.max(
    Number(els.audio.duration) || 0,
    ...state.turns.map((turn) => Number(turn.end_sec) || 0),
    ...state.diarization.map((segment) => Number(segment.end_sec) || 0),
    1,
  );
}

function renderTurnProgress() {
  const turn = currentTurn();
  const index = turn ? state.turns.findIndex((candidate) => candidate.id === turn.id) : -1;
  const total = state.turns.length;
  const current = index >= 0 ? index + 1 : 0;
  // Runs ~15x/sec during playback; the DOM only changes when the position does.
  const key = `${current}/${total}`;
  if (state.turnProgressKey === key) return;
  state.turnProgressKey = key;
  const percent = total ? (current / total) * 100 : 0;
  els.turnProgressCircle.style.setProperty("--turn-progress", `${percent}%`);
  els.turnProgressText.textContent = total ? key : "0/0";
  if (!total) {
    els.turnProgressLabel.textContent = "No transcript loaded";
    if (els.turnProgressHint) els.turnProgressHint.textContent = "Open a recording from the Dashboard";
  } else if (!current) {
    els.turnProgressLabel.textContent = "No turn selected";
    if (els.turnProgressHint) els.turnProgressHint.textContent = "Click a turn or press Play";
  } else {
    const after = total - current;
    els.turnProgressLabel.textContent = `Turn ${current} of ${total}`;
    if (els.turnProgressHint) {
      els.turnProgressHint.textContent = after ? `${after} ${after === 1 ? "turn" : "turns"} follow` : "Last turn of the transcript";
    }
  }
}

// The selected-turn card and the speaker legend. Both are cheap, but edits
// arrive at keystroke rate and setActiveTurn runs during playback, so the
// legend is rebuilt once per frame at most and the card only when the active
// turn (or, after an edit, its content) changes.
function scheduleReviewMetaRefresh() {
  if (state.reviewMetaRefreshRaf || typeof requestAnimationFrame !== "function") return;
  state.reviewMetaRefreshRaf = requestAnimationFrame(() => {
    state.reviewMetaRefreshRaf = 0;
    state.selectionMetaTurnId = "";
    renderSelectionMeta(currentTurn());
    renderReviewSummary();
  });
}

function formatDurationShort(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  if (safe >= 60) return `${Math.floor(safe / 60)} min ${Math.round(safe % 60)} s`;
  return safe >= 10 ? `${Math.round(safe)} s` : `${safe.toFixed(1)} s`;
}

function renderSelectionMeta(turn) {
  if (!els.selectionMeta || !els.selectionFacts) return;
  if (!turn) {
    state.selectionMetaTurnId = "";
    els.selectionMeta.hidden = true;
    return;
  }
  if (turn.id === state.selectionMetaTurnId && !els.selectionMeta.hidden) return;
  state.selectionMetaTurnId = turn.id;
  els.selectionMeta.hidden = false;
  const label = speakerLabel(turn.label);
  els.selectionRole.textContent = label;
  els.selectionRole.style.setProperty("--speaker-color", speakerColor(label));
  els.selectionRange.textContent = `${formatTime(turn.start_sec)} – ${formatTime(turn.end_sec)}`;

  const facts = [
    ["Length", formatDurationShort(turn.end_sec - turn.start_sec)],
    ["Words", String(turn.words.length)],
  ];
  const scores = turn.words.map((word) => Number(word.confidence)).filter(Number.isFinite);
  if (scores.length) {
    const mean = scores.reduce((sum, value) => sum + value, 0) / scores.length;
    const low = scores.filter((value) => value < LOW_WORD_CONFIDENCE).length;
    facts.push(["Confidence", `${Math.round(mean * 100)}%`, low ? `${low} low` : ""]);
  }
  els.selectionFacts.replaceChildren(...facts.map(([term, value, note]) => {
    const item = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    if (note) {
      const small = document.createElement("small");
      small.textContent = ` ${note}`;
      small.title = `${note.split(" ")[0]} words under ${Math.round(LOW_WORD_CONFIDENCE * 100)}% speaker confidence`;
      dd.append(small);
    }
    item.append(dt, dd);
    return item;
  }));
  if (facts.length > 2) {
    els.selectionFacts.children[2].title = "Mean confidence that these words belong to this speaker (from the fusion stage)";
  }

  const flags = [];
  if (turn.bookmarked) flags.push(["marked", "Marked (M)"]);
  if (turn.unclear_intro) flags.push(["unrelated", "Unrelated section"]);
  // Every saved turn carries source "editor", so only word-level manual
  // flags tell an edited turn from an untouched one.
  if (turn.words.some((word) => word.manual)) flags.push(["edited", "Words edited"]);
  if (turn.timingReliable === false) flags.push(["", "Timing estimated"]);
  els.selectionFlags.hidden = !flags.length;
  els.selectionFlags.replaceChildren(...flags.map(([kind, text]) => {
    const chip = document.createElement("span");
    chip.className = `selection-flag${kind ? ` ${kind}` : ""}`;
    chip.textContent = text;
    return chip;
  }));
}

function renderReviewSummary() {
  if (!els.speakerSummary) return;
  const totals = new Map();
  let marks = 0;
  let unrelated = 0;
  let totalSeconds = 0;
  for (const turn of state.turns) {
    const label = speakerLabel(turn.label);
    const seconds = Math.max(0, turn.end_sec - turn.start_sec);
    const entry = totals.get(label) || { label, turns: 0, seconds: 0 };
    entry.turns += 1;
    entry.seconds += seconds;
    totals.set(label, entry);
    totalSeconds += seconds;
    if (turn.bookmarked) marks += 1;
    if (turn.unclear_intro) unrelated += 1;
  }
  if (!state.turns.length) {
    if (els.reviewSummaryTotals) els.reviewSummaryTotals.textContent = "";
    const empty = document.createElement("div");
    empty.className = "speaker-summary-empty";
    empty.textContent = "No transcript loaded.";
    els.speakerSummary.replaceChildren(empty);
    return;
  }
  const parts = [`${state.turns.length} turns`];
  if (marks) parts.push(`${marks} marked`);
  if (unrelated) parts.push(`${unrelated} unrelated`);
  if (els.reviewSummaryTotals) els.reviewSummaryTotals.textContent = parts.join(" · ");

  const rows = Array.from(totals.values()).sort((a, b) => b.seconds - a.seconds || b.turns - a.turns);
  els.speakerSummary.replaceChildren(...rows.map((entry) => {
    const share = totalSeconds ? (entry.seconds / totalSeconds) * 100 : 0;
    const row = document.createElement("div");
    row.className = "speaker-row";
    row.style.setProperty("--speaker-color", speakerColor(entry.label));
    row.title = `${entry.label}: ${entry.turns} ${entry.turns === 1 ? "turn" : "turns"}, ${formatDurationShort(entry.seconds)} of speech`;
    const dot = document.createElement("span");
    dot.className = "speaker-row-dot";
    const name = document.createElement("span");
    name.className = "speaker-row-name";
    name.textContent = entry.label;
    const stats = document.createElement("span");
    stats.className = "speaker-row-stats";
    stats.textContent = `${entry.turns} ${entry.turns === 1 ? "turn" : "turns"} · ${Math.round(share)}%`;
    const bar = document.createElement("span");
    bar.className = "speaker-row-bar";
    const fill = document.createElement("i");
    fill.style.width = `${Math.max(0, Math.min(100, share))}%`;
    bar.append(fill);
    row.append(dot, name, stats, bar);
    return row;
  }));
}

function updateTransportLabels() {
  if (els.playPauseButton) {
    els.playPauseButton.textContent = audioIsPaused() ? "Play" : "Pause";
  }
  if (els.currentTimeLabel) {
    els.currentTimeLabel.textContent = formatTime(timelineDisplayTime());
  }
  if (els.durationLabel) {
    els.durationLabel.textContent = formatTime(timelineDuration());
  }
}

function jumpAudio(seconds) {
  if (!els.audio.src) return;
  const duration = timelineDuration();
  setAudioTime(Math.max(0, Math.min(duration, currentAudioTime() + seconds)));
  drawTimeline();
  updateTransportLabels();
}

function timelineScrubTime() {
  return Number.isFinite(state.timelineScrub.time) ? state.timelineScrub.time : null;
}

function timelineDisplayTime() {
  const scrubTime = timelineScrubTime();
  return scrubTime == null ? visualAudioTime() : scrubTime;
}

function timelineTimeFromPointer(event) {
  const rect = els.timeline.getBoundingClientRect();
  const pad = 14;
  const innerWidth = Math.max(1, rect.width - pad * 2);
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left - pad) / innerWidth));
  return ratio * timelineDuration();
}

function scheduleTimelineScrubDraw() {
  if (state.timelineScrub.frame) return;
  state.timelineScrub.frame = requestAnimationFrame(() => {
    state.timelineScrub.frame = 0;
    drawTimeline();
  });
}

function previewTimelineScrub(event) {
  state.timelineScrub.time = timelineTimeFromPointer(event);
  scheduleTimelineScrubDraw();
}

function beginTimelineScrub(event) {
  if (event.button !== 0) return;
  event.preventDefault();
  state.timelineScrub.active = true;
  state.timelineScrub.pointerId = event.pointerId;
  state.timelineScrub.wasPlaying = !audioIsPaused();
  if (state.timelineScrub.wasPlaying) pauseAudio();
  els.timeline.setPointerCapture?.(event.pointerId);
  previewTimelineScrub(event);
}

function moveTimelineScrub(event) {
  if (!state.timelineScrub.active || event.pointerId !== state.timelineScrub.pointerId) return;
  event.preventDefault();
  previewTimelineScrub(event);
}

function finishTimelineScrub(event) {
  if (!state.timelineScrub.active || event.pointerId !== state.timelineScrub.pointerId) return;
  event.preventDefault();
  previewTimelineScrub(event);
  const time = timelineScrubTime();
  const wasPlaying = state.timelineScrub.wasPlaying;
  if (state.timelineScrub.frame) {
    cancelAnimationFrame(state.timelineScrub.frame);
  }
  state.timelineScrub = { active: false, pointerId: null, time: null, wasPlaying: false, frame: 0 };
  els.timeline.releasePointerCapture?.(event.pointerId);
  if (time != null) {
    setAudioTime(time);
    const turn = turnAtTime(time);
    if (turn) setActiveTurn(turn.id, { scroll: false });
  }
  drawTimeline();
  if (wasPlaying && els.audio.src) playAudio().catch(() => {});
}

function drawTimeline() {
  const canvas = els.timeline;
  if (!canvas) {
    updateTransportLabels();
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const width = rect.width;
  const height = rect.height;
  const duration = timelineDuration();
  const pad = 14;
  const innerWidth = Math.max(1, width - pad * 2);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "#68717b";
  ctx.font = "11px system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText("0:00", pad, 16);
  const endLabel = formatTime(duration);
  ctx.fillText(endLabel, Math.max(pad, width - pad - ctx.measureText(endLabel).width), 16);

  if (state.waveform) {
    const mid = Math.max(54, Math.floor(height * 0.42));
    const amp = Math.max(24, Math.min(46, height * 0.28));
    ctx.beginPath();
    state.waveform.forEach((peak, index) => {
      const x = pad + (index / Math.max(1, state.waveform.length - 1)) * innerWidth;
      const y = mid - peak * amp;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    state.waveform.slice().reverse().forEach((peak, index) => {
      const x = pad + ((state.waveform.length - 1 - index) / Math.max(1, state.waveform.length - 1)) * innerWidth;
      const y = mid + peak * amp;
      ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(103, 116, 131, 0.16)";
    ctx.fill();
  } else {
    ctx.fillStyle = "rgba(103, 116, 131, 0.12)";
    ctx.fillRect(pad, Math.floor(height * 0.42), innerWidth, 2);
  }

  const bandY = Math.max(92, height - 32);
  for (const turn of bookmarkedTurns()) {
    const x = pad + ((Number(turn.start_sec) || 0) / duration) * innerWidth;
    ctx.fillStyle = "#a35c00";
    ctx.beginPath();
    ctx.moveTo(x, bandY - 14);
    ctx.lineTo(x - 5, bandY - 4);
    ctx.lineTo(x + 5, bandY - 4);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(x - 1, bandY - 4, 2, 26);
  }

  const currentTime = timelineDisplayTime();
  const playheadX = pad + (currentTime / duration) * innerWidth;
  ctx.fillStyle = "#a35c00";
  ctx.beginPath();
  ctx.arc(playheadX, Math.max(26, Math.floor(height * 0.42)), 5, 0, Math.PI * 2);
  ctx.fill();
  updateTransportLabels();
}

function updateCurrentWordHighlight() {
  const time = visualAudioTime();
  // Only the previously-highlighted chip can carry "current"; clear it directly
  // instead of querying the whole DOM each frame.
  if (state.currentWordChip) {
    state.currentWordChip.classList.remove("current");
    state.currentWordChip = null;
  }

  const selectedWord = selectedSingleWordRef();
  if (selectedWord && !audioIsPaused() && currentAudioTime() > Number(selectedWord.turn.end_sec) + 0.02) {
    clearWordSelection();
  }

  const holdActive = state.playbackTurnHold.turnId && performance.now() < state.playbackTurnHold.until;
  const heldTurn = holdActive ? turnById(state.playbackTurnHold.turnId) : null;
  if (!holdActive && state.playbackTurnHold.turnId) {
    state.playbackTurnHold = { turnId: "", until: 0 };
  }

  const timedMatch = heldTurn
    ? { turn: heldTurn, word: heldTurn.words[0] || null }
    : globalWordAtTime(time);
  const activeByTime = heldTurn || timedMatch?.turn || state.turns.find((turn) => turn.timingReliable !== false && time >= turn.start_sec && time <= turn.end_sec);
  if (state.settings.followAudioTurn && activeByTime) {
    const shouldScroll = shouldAutoScrollPlayingTurn(activeByTime.id);
    if (state.activeTurnId !== activeByTime.id || shouldScroll) {
      setActiveTurn(activeByTime.id, { smooth: true, scroll: shouldScroll });
    }
  }

  const highlightedWord = timedMatch?.word || null;
  if (highlightedWord) {
    const selector = `.word-chip[data-word-id="${CSS.escape(highlightedWord.id)}"]`;
    const chip = document.querySelector(selector);
    if (chip) {
      chip.classList.add("current");
      state.currentWordChip = chip;
    }
  }

  applyEffectivePlaybackRate();
  // The canvas + progress circle only need ~15 Hz; the word highlight above runs
  // every frame. Always redraw on the final (paused) frame so nothing is stale.
  const now = performance.now();
  if (audioIsPaused() || now - (state.lastTimelineRedraw || 0) >= TIMELINE_REDRAW_INTERVAL_MS) {
    state.lastTimelineRedraw = now;
    renderTurnProgress();
    drawTimeline();
  }
}

function startTimelineLoop() {
  cancelAnimationFrame(state.raf);
  const tick = () => {
    updateCurrentWordHighlight();
    if (!audioIsPaused()) {
      state.raf = requestAnimationFrame(tick);
    }
  };
  tick();
}

els.tabButtons.forEach((button) => {
  button.addEventListener("click", () => setActiveTab(button.dataset.tab));
});
els.refreshSessions.addEventListener("click", () => {
  refreshRecordings({ openSelected: false }).catch((error) => showErrorNotice(error));
  // Also re-fetch the job/queue snapshot: stale queue state is what freezes
  // badges and selection buttons, and it lives outside refreshRecordings.
  pollPipelineJob().catch((error) => setPipelineStatus(error.message));
});
els.importAudioButton.addEventListener("click", () => els.audioImport.click());
els.importAudioEmpty?.addEventListener("click", () => els.audioImport.click());
els.selectAllRecordings.addEventListener("click", () => {
  state.selectedRecordingKeys = new Set(state.recordings.map((recording) => recording.key));
  updateRecordingActions();
});
els.clearRecordingSelection.addEventListener("click", () => {
  state.selectedRecordingKeys = new Set();
  updateRecordingActions();
});
els.runSelectedRecordings.addEventListener("click", () => {
  runSelectedUnprocessed().catch((error) => setPipelineStatus(error.message));
});
els.reprocessSelectedRecordings.addEventListener("click", () => {
  reprocessRecordings().catch((error) => setPipelineStatus(error.message));
});
els.reprocessSelectedInProcessing.addEventListener("click", () => {
  reprocessRecordings().catch((error) => setPipelineStatus(error.message));
});
els.audioImport.addEventListener("change", () => {
  uploadAudioFiles(els.audioImport.files)
    .catch((error) => showErrorNotice(error))
    .finally(() => {
      els.audioImport.value = "";
    });
});
els.runInputFolder.addEventListener("click", () => {
  runAllUnprocessed().catch((error) => setPipelineStatus(error.message));
});
els.releaseWorker?.addEventListener("click", () => {
  releasePipelineWorker().catch((error) => setPipelineStatus(error.message));
});
els.pipelineLogFilter?.addEventListener("change", () => {
  state.pipelineLogFilter = els.pipelineLogFilter.value;
  renderPipelineLog();
  renderPipelineFiles();
});
els.saveButton.addEventListener("click", () => saveSession().catch((error) => showErrorNotice(error)));
els.toggleFinished.addEventListener("click", () => toggleFinished().catch((error) => showErrorNotice(error)));
els.exportTranscript.addEventListener("click", () => exportTranscript().catch((error) => showErrorNotice(error)));
els.exportAllFinished.addEventListener("click", () => exportAllFinished().catch((error) => showErrorNotice(error)));
els.showRevisions.addEventListener("click", () => toggleRevisionPanel().catch((error) => showErrorNotice(error)));
els.restoreRevisionBefore.addEventListener("click", () => restoreSelectedRevisionSide("before"));
els.restoreRevisionAfter.addEventListener("click", () => restoreSelectedRevisionSide("after"));
els.clearCache.addEventListener("click", () => clearCache().catch((error) => showErrorNotice(error)));
els.nextBookmark.addEventListener("click", goToNextBookmark);
els.showBookmarks.addEventListener("click", toggleBookmarkFilter);
els.openSpeakerDialog.addEventListener("click", () => openSpeakerDialog().catch((error) => showErrorNotice(error)));
els.openBulkDialog.addEventListener("click", () => openBulkDialog().catch((error) => showErrorNotice(error)));
els.toggleTurnSelectionMode.addEventListener("click", toggleTurnSelectionMode);
els.selectVisibleTurns.addEventListener("click", selectVisibleTurns);
els.clearTurnSelection.addEventListener("click", clearTurnSelection);
els.searchInput.addEventListener("input", () => {
  refreshSearchMatches();
  renderTurns({ scrollActive: false });
});
els.searchPrev.addEventListener("click", () => goToSearchMatch(-1));
els.searchNext.addEventListener("click", () => goToSearchMatch(1));
els.replaceOne.addEventListener("click", replaceCurrentMatch);
els.replaceAll.addEventListener("click", replaceAllMatches);
els.activeSpeaker.addEventListener("change", () => {
  const turn = currentTurn();
  if (!turn) return;
  changeTurnSpeaker(turn, els.activeSpeaker.value);
});
bindRoleMenuSpeed(els.activeSpeaker);
if (els.speedSlider) {
  els.speedSlider.addEventListener("input", () => setGlobalPlaybackRate(els.speedSlider.value));
}
if (els.playPauseButton) {
  els.playPauseButton.addEventListener("click", () => {
    if (!els.audio.src) return;
    if (audioIsPaused()) playAudio().catch(() => {});
    else pauseAudio();
    updateTransportLabels();
  });
}
if (els.jumpBack10) els.jumpBack10.addEventListener("click", () => jumpAudio(-10));
if (els.jumpForward10) els.jumpForward10.addEventListener("click", () => jumpAudio(10));
els.settingRoleMenuBehavior.addEventListener("change", () => {
  updateSetting("roleMenuBehavior", els.settingRoleMenuBehavior.value);
});
els.settingSlowSpeed.addEventListener("input", () => {
  updateSetting("slowPlaybackRate", clampNumber(els.settingSlowSpeed.value, 0.25, 1, 0.5));
});
els.settingClickTurnPlays.addEventListener("change", () => {
  updateSetting("clickTurnPlays", els.settingClickTurnPlays.checked);
});
els.settingWordClickPlays.addEventListener("change", () => {
  updateSetting("wordClickPlays", els.settingWordClickPlays.checked);
});
els.settingFollowAudioTurn.addEventListener("change", () => {
  updateSetting("followAudioTurn", els.settingFollowAudioTurn.checked);
});
els.settingTextEditSlowsAudio.addEventListener("change", () => {
  updateSetting("textEditSlowsAudio", els.settingTextEditSlowsAudio.checked);
});
els.settingWordDragSlowsAudio.addEventListener("change", () => {
  updateSetting("wordDragSlowsAudio", els.settingWordDragSlowsAudio.checked);
});
els.settingShowMergeButtons.addEventListener("change", () => {
  updateSetting("showMergeButtons", els.settingShowMergeButtons.checked);
});
els.settingSpaceTogglesPlayback.addEventListener("change", () => {
  updateSetting("spaceTogglesPlayback", els.settingSpaceTogglesPlayback.checked);
});
els.settingVisualLatency.addEventListener("input", () => {
  updateSetting("visualLatencySec", clampNumber(els.settingVisualLatency.value, 0, 0.5, 0.2));
});
els.settingAutoScrollDelay.addEventListener("input", () => {
  updateSetting("autoScrollDelaySec", clampNumber(els.settingAutoScrollDelay.value, 0, 2, 0.65));
});
els.settingAutosaveMinutes.addEventListener("change", () => {
  updateSetting("autosaveCheckpointMinutes", Math.round(clampNumber(els.settingAutosaveMinutes.value, 1, 30, 5)));
});
els.audio.addEventListener("play", startTimelineLoop);
els.audio.addEventListener("play", updateTransportLabels);
els.audio.addEventListener("pause", () => {
  cancelAnimationFrame(state.raf);
  updateTransportLabels();
});
els.audio.addEventListener("timeupdate", updateCurrentWordHighlight);
els.audio.addEventListener("loadedmetadata", () => {
  drawTimeline();
  updateTransportLabels();
});
document.addEventListener("copy", onEditorCopy);
let resizeRewrapTimer = 0;
window.addEventListener("resize", () => {
  drawTimeline();
  alignAllWordStrips();
  // Line lengths are pixel-fit to the list width, so re-split after resizing
  // settles (skipped while a text line is being edited to not steal the caret).
  window.clearTimeout(resizeRewrapTimer);
  resizeRewrapTimer = window.setTimeout(() => {
    if (!state.turns.length || isTextEntryTarget(document.activeElement)) return;
    renderTurns({ scrollActive: false, preserveScroll: true, scrollAnchorTurnId: state.activeTurnId });
  }, 250);
});
if (els.timeline) {
  els.timeline.addEventListener("pointerdown", beginTimelineScrub);
  els.timeline.addEventListener("pointermove", moveTimelineScrub);
  els.timeline.addEventListener("pointerup", finishTimelineScrub);
  els.timeline.addEventListener("pointercancel", finishTimelineScrub);
}
els.turnList.addEventListener("scroll", noteTurnListScroll, { passive: true });
document.addEventListener("pointermove", onWordRangePointerMove, { passive: false });
document.addEventListener("pointerup", finishWordRangeSelection);
document.addEventListener("pointercancel", (event) => finishWordRangeSelection(event));

function isTextEntryTarget(target) {
  const element = target?.closest?.("input, textarea, [contenteditable='true']");
  if (!element) return false;
  if (element.isContentEditable) return true;
  const type = String(element.type || "").toLowerCase();
  return !["checkbox", "radio", "range", "button", "submit"].includes(type);
}

function shouldSpaceTogglePlayback(event) {
  return state.settings.spaceTogglesPlayback
    && event.code === "Space"
    && !event.ctrlKey
    && !event.metaKey
    && !event.altKey
    && !isTextEntryTarget(event.target);
}

function togglePlaybackFromShortcut() {
  if (audioIsPaused()) playAudio().catch(() => {});
  else pauseAudio();
}

function handleHoveredWordShortcut(event) {
  if (state.activeTab !== "review" || isTextEntryTarget(event.target)) return false;
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.repeat) return false;
  const key = event.key.toLowerCase();
  if (key !== "a" && key !== "d" && key !== "s") return false;
  const ref = hoveredWordBarRef();
  if (!ref) return false;
  event.preventDefault();
  event.stopPropagation();
  if (key === "s") {
    splitTurnAtWordIndex(ref.turn, ref.index);
  } else {
    moveWordBoundaryToAdjacentTurn(ref.turn, ref.index, key === "a" ? "up" : "down");
  }
  return true;
}

function handleTurnPlaybackShortcut(event) {
  if (state.activeTab !== "review" || isTextEntryTarget(event.target)) return false;
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.repeat) return false;
  const key = event.key.toLowerCase();
  if (key !== "q" && key !== "e" && key !== "w") return false;
  event.preventDefault();
  event.stopPropagation();
  if (key === "q") return playRelativeTurn(-1);
  if (key === "e") return playRelativeTurn(1);
  return selectHoveredTurn();
}

// Bookmark / unrelated / delete shortcuts target the hovered turn, falling back
// to the active one, so a mouse-over plus one key acts on a turn without any
// row buttons.
function handleTurnFlagShortcut(event) {
  if (state.activeTab !== "review" || isTextEntryTarget(event.target)) return false;
  if (!els.modalBackdrop.hidden) return false;
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.repeat) return false;
  const key = event.key.toLowerCase();
  if (key !== "m" && key !== "n" && key !== "x") return false;
  const turn = hoveredTurn() || currentTurn();
  if (!turn) return false;
  event.preventDefault();
  event.stopPropagation();
  if (key === "m") toggleTurnBookmark(turn.id);
  else if (key === "n") markUnrelatedSpan(turn.id);
  else deleteTurnSpan(turn.id);
  return true;
}

function handleReviewTabShortcut(event) {
  if (event.key !== "Tab") return false;
  if (state.activeTab !== "review" || event.ctrlKey || event.metaKey || event.altKey) return false;
  if (isTextEntryTarget(event.target)) return false;
  const turn = currentTurn();
  if (!turn) return false;
  event.preventDefault();
  event.stopPropagation();
  // Swallow OS key auto-repeat: a press switches exactly one speaker.
  if (event.repeat) return true;
  cycleTurnSpeaker(turn, event.shiftKey, { fromShortcut: true });
  return true;
}

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && els.modalBackdrop.hidden
      && (clearUnrelatedPending() || clearDeletePending())) {
    event.preventDefault();
    return;
  }
  if (handleHoveredWordShortcut(event)) return;
  if (handleTurnPlaybackShortcut(event)) return;
  if (handleTurnFlagShortcut(event)) return;
  if (handleReviewTabShortcut(event)) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (event.shiftKey) redoEdit();
    else undoEdit();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
    event.preventDefault();
    redoEdit();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveSession().catch((error) => showErrorNotice(error));
  }
  if (shouldSpaceTogglePlayback(event)) {
    event.preventDefault();
    event.stopPropagation();
    if (!event.repeat) togglePlaybackFromShortcut();
  }
});

window.addEventListener("keyup", (event) => {
  if (!shouldSpaceTogglePlayback(event)) return;
  event.preventDefault();
  event.stopPropagation();
}, true);

window.addEventListener("beforeunload", (event) => {
  if (!state.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});

loadSettings();
renderSettings();
preservePitch();
setGlobalPlaybackRate(1);
setActiveTab("dashboard");
updateTabAvailability();
refreshSearchMatches();
renderPipelineJob(null);
refreshRecordings({ openSelected: false }).catch((error) => showErrorNotice(error));
pollPipelineJob().catch((error) => setPipelineStatus(error.message));
