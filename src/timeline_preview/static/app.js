"use strict";

const ui = {
  projectName: document.querySelector("#project-name"),
  snapshotMeta: document.querySelector("#snapshot-meta"),
  summaryStats: document.querySelector("#summary-stats"),
  previewTitle: document.querySelector("#preview-title"),
  previewVideo: document.querySelector("#preview-video"),
  previewStatus: document.querySelector("#preview-status"),
  monitor: document.querySelector(".monitor"),
  timecode: document.querySelector("#timecode"),
  clipDetails: document.querySelector("#clip-details"),
  zoom: document.querySelector("#zoom"),
  zoomValue: document.querySelector("#zoom-value"),
  empty: document.querySelector("#timeline-empty"),
  scroll: document.querySelector("#timeline-scroll"),
  content: document.querySelector("#timeline-content"),
  ruler: document.querySelector("#ruler"),
  trackLabels: document.querySelector("#track-labels"),
  trackLanes: document.querySelector("#track-lanes"),
  playhead: document.querySelector("#playhead"),
  fatalError: document.querySelector("#fatal-error"),
  fatalErrorMessage: document.querySelector("#fatal-error-message"),
  manualEditor: document.querySelector("#manual-editor"),
  manualEditDisabled: document.querySelector("#manual-edit-disabled"),
  clipEditForm: document.querySelector("#clip-edit-form"),
  editTrimIn: document.querySelector("#edit-trim-in"),
  editTrimOut: document.querySelector("#edit-trim-out"),
  editTimelineStart: document.querySelector("#edit-timeline-start"),
  editOrder: document.querySelector("#edit-order"),
  editFormMessage: document.querySelector("#edit-form-message"),
  stageRemove: document.querySelector("#stage-remove"),
  draftPanel: document.querySelector("#draft-panel"),
  draftState: document.querySelector("#draft-state"),
  draftChanges: document.querySelector("#draft-changes"),
  draftMessage: document.querySelector("#draft-message"),
  undoDraft: document.querySelector("#undo-draft"),
  resetDraft: document.querySelector("#reset-draft"),
  applyDraft: document.querySelector("#apply-draft"),
  applySuccess: document.querySelector("#apply-success"),
  applySuccessMessage: document.querySelector("#apply-success-message"),
  modeBadgeLabel: document.querySelector("#mode-badge-label"),
  timelineHelp: document.querySelector("#timeline-help"),
};

const state = {
  snapshot: null,
  media: {},
  pixelsPerSecond: Number(ui.zoom.value),
  playheadSeconds: 0,
  selected: null,
  animationFrame: null,
  capabilities: {},
  draftEdits: [],
  draftHistory: [],
  proposalId: null,
  proposalCreatedAt: null,
  review: null,
  applying: false,
};

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  return element;
}

function labelWidth() {
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue("--label-width")
    .trim();
  return Number.parseFloat(value) || 176;
}

function formatSeconds(seconds, precision = 2) {
  return `${Number(seconds).toFixed(precision)}s`;
}

function timecode(seconds) {
  const fps = Math.max(1, state.snapshot?.fps || 30);
  const totalFrames = Math.max(0, Math.round(seconds * fps));
  const frames = totalFrames % fps;
  const totalSeconds = Math.floor(totalFrames / fps);
  const secs = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  return [hours, minutes, secs, frames]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function formatRulerTime(seconds) {
  if (seconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return (
      `${hours}:${String(minutes).padStart(2, "0")}:` +
      String(secs).padStart(2, "0")
    );
  }
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return (
    `${String(minutes).padStart(2, "0")}:` +
    String(secs).padStart(2, "0")
  );
}

function detailRow(label, value) {
  const row = document.createElement("div");
  row.append(
    textElement("dt", "", label),
    textElement("dd", "", value),
  );
  return row;
}

function newStableId(prefix) {
  const value =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().replaceAll("-", "")
      : `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `${prefix}_${value}`;
}

function initializeProposalIdentity() {
  state.proposalId = newStableId("manual_proposal");
  state.proposalCreatedAt = new Date().toISOString();
}

function cloneEdits(edits) {
  return JSON.parse(JSON.stringify(edits));
}

function existingDraftForClip(clipId) {
  return state.draftEdits.find((edit) => edit.clip_id === clipId) || null;
}

function showManualEditor(track, clip) {
  const applyEnabled = state.capabilities.manual_edit_apply === true;
  ui.manualEditDisabled.hidden = applyEnabled;
  ui.manualEditor.hidden = !applyEnabled || track.kind !== "video";
  if (!applyEnabled || track.kind !== "video") {
    return;
  }
  const existing = existingDraftForClip(clip.clip_id);
  if (existing?.kind === "remove") {
    ui.manualEditor.hidden = true;
    return;
  }
  ui.editTrimIn.value = String(
    existing?.trim_in_seconds ?? clip.trim_in_seconds,
  );
  ui.editTrimOut.value = String(
    existing?.trim_out_seconds ?? clip.trim_out_seconds,
  );
  ui.editTimelineStart.value = String(
    existing?.timeline_start_seconds ?? clip.timeline_start_seconds,
  );
  ui.editOrder.value = String(existing?.order_index ?? clip.order_index);
  ui.editOrder.max = String(
    Math.max(0, state.snapshot.video_clip_count - 1),
  );
  ui.editFormMessage.classList.remove("error");
  ui.editFormMessage.textContent =
    "Changes remain detached until you review and confirm them.";
}

function proposalPayload() {
  if (!state.proposalId) {
    initializeProposalIdentity();
  }
  return {
    schema_name: "vistora.manual-edit-proposal",
    schema_version: "1.0.0",
    proposal_id: state.proposalId,
    authored_by: "local_user",
    base_project_id: state.snapshot.project_id,
    base_revision: state.snapshot.revision,
    base_timeline_digest: state.snapshot.timeline_digest,
    edits: cloneEdits(state.draftEdits),
    created_at: state.proposalCreatedAt,
  };
}

function setDraftState(label, kind = "") {
  ui.draftState.textContent = label;
  ui.draftState.className = `draft-state ${kind}`.trim();
}

function changedFieldLines(change) {
  if (change.action === "remove") {
    return [
      `Remove from order ${change.before.order_index}`,
      `${formatSeconds(change.before.timeline_start_seconds)} → ` +
        formatSeconds(change.before.timeline_end_seconds),
      change.before.source_name,
    ];
  }
  const labels = {
    trim_in_seconds: "Source in",
    trim_out_seconds: "Source out",
    timeline_start_seconds: "Timeline start",
    order_index: "Order",
  };
  const lines = [];
  for (const [field, label] of Object.entries(labels)) {
    if (change.before[field] !== change.after[field]) {
      const before =
        field === "order_index"
          ? change.before[field]
          : formatSeconds(change.before[field]);
      const after =
        field === "order_index"
          ? change.after[field]
          : formatSeconds(change.after[field]);
      lines.push(`${label}: ${before} → ${after}`);
    }
  }
  return lines;
}

function renderDraftReview() {
  const changes = state.review?.changes || [];
  ui.draftChanges.replaceChildren();
  for (const change of changes) {
    const card = document.createElement("article");
    card.className = "change-card";
    const header = document.createElement("div");
    header.className = "change-card-header";
    header.append(
      textElement("strong", "", change.clip_id),
      textElement(
        "span",
        `change-action ${change.action}`,
        change.action,
      ),
    );
    const lines = document.createElement("div");
    lines.className = "change-lines";
    for (const line of changedFieldLines(change)) {
      lines.append(textElement("span", "", line));
    }
    card.append(header, lines);
    ui.draftChanges.append(card);
  }
}

async function validateDraft() {
  ui.applySuccess.hidden = true;
  if (state.draftEdits.length === 0) {
    state.review = null;
    ui.draftPanel.hidden = true;
    ui.draftChanges.replaceChildren();
    ui.draftMessage.textContent = "";
    ui.applyDraft.disabled = true;
    return;
  }
  ui.draftPanel.hidden = false;
  ui.applyDraft.disabled = true;
  setDraftState("Validating");
  ui.draftMessage.classList.remove("error");
  ui.draftMessage.textContent =
    "Checking the detached proposal against the current snapshot…";
  try {
    const response = await fetch("/api/manual-edits/validate", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ proposal: proposalPayload() }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(
        payload.error?.message ||
          `Validation failed with HTTP ${response.status}.`,
      );
    }
    if (payload.persisted !== false || !payload.review) {
      throw new Error("Manual edit review returned an invalid contract.");
    }
    state.review = payload.review;
    renderDraftReview();
    setDraftState("Ready to confirm", "valid");
    ui.draftMessage.textContent =
      "Validated only. The timeline has not been written.";
    ui.applyDraft.disabled = false;
  } catch (error) {
    state.review = null;
    ui.draftChanges.replaceChildren();
    setDraftState("Needs attention", "error");
    ui.draftMessage.classList.add("error");
    ui.draftMessage.textContent =
      error instanceof Error ? error.message : String(error);
    ui.applyDraft.disabled = true;
  }
}

function stageEdit(edit) {
  state.draftHistory.push(cloneEdits(state.draftEdits));
  state.draftEdits = state.draftEdits.filter(
    (current) => current.clip_id !== edit.clip_id,
  );
  state.draftEdits.push(edit);
  validateDraft();
}

function resetDraft({ keepSuccess = false } = {}) {
  state.draftEdits = [];
  state.draftHistory = [];
  state.review = null;
  initializeProposalIdentity();
  ui.draftPanel.hidden = true;
  ui.draftChanges.replaceChildren();
  ui.draftMessage.textContent = "";
  ui.applyDraft.disabled = true;
  if (!keepSuccess) {
    ui.applySuccess.hidden = true;
  }
  if (state.selected) {
    showManualEditor(state.selected.track, state.selected.clip);
  }
}

function renderSummary() {
  const snapshot = state.snapshot;
  ui.projectName.textContent = snapshot.project_id;
  ui.snapshotMeta.textContent =
    `Revision ${snapshot.revision} · ${snapshot.schema_name} ` +
    `v${snapshot.schema_version} · ${snapshot.migration_source}`;
  ui.summaryStats.replaceChildren();
  const stats = [
    ["Duration", timecode(snapshot.duration_seconds)],
    ["Canvas", `${snapshot.width}×${snapshot.height}`],
    ["Frame rate", `${snapshot.fps} fps`],
    ["Contents", `${snapshot.track_count} tracks / ${snapshot.clip_count} clips`],
  ];
  for (const [label, value] of stats) {
    const wrapper = document.createElement("div");
    wrapper.append(
      textElement("dt", "", label),
      textElement("dd", "", value),
    );
    ui.summaryStats.append(wrapper);
  }
}

function showDetails(track, clip) {
  const availability = state.media[clip.source.source_id];
  ui.clipDetails.replaceChildren(
    detailRow("Clip ID", clip.clip_id),
    detailRow("Track", `${track.track_key} · ${track.kind}`),
    detailRow(
      "Timeline",
      `${formatSeconds(clip.timeline_start_seconds)} → ` +
        formatSeconds(clip.timeline_end_seconds),
    ),
    detailRow(
      "Duration",
      `${formatSeconds(clip.effective_duration_seconds)} effective · ` +
        `${formatSeconds(clip.declared_source_duration_seconds)} source`,
    ),
    detailRow(
      "Source trim",
      `${formatSeconds(clip.trim_in_seconds)} → ` +
        formatSeconds(clip.trim_out_seconds),
    ),
    detailRow("Source name", clip.source.display_name),
    detailRow("Source reference", clip.source.value),
    detailRow("Source ID", clip.source.source_id),
    detailRow(
      "Playback",
      `${clip.speed_factor}× · ${clip.reverse ? "reverse" : "forward"} · ` +
        `${clip.rotate_degrees}°`,
    ),
    detailRow(
      "Media access",
      availability?.available
        ? `Allowlisted · ${availability.content_type}`
        : "Unavailable or outside allowlisted roots",
    ),
  );
}

function clearPreview(message) {
  ui.previewVideo.pause();
  ui.previewVideo.removeAttribute("src");
  ui.previewVideo.load();
  ui.monitor.classList.remove("has-media");
  ui.previewTitle.textContent = "Preview unavailable";
  ui.previewStatus.textContent = message;
}

function selectClip(track, clip, element) {
  document
    .querySelectorAll(".clip.selected")
    .forEach((item) => item.classList.remove("selected"));
  element.classList.add("selected");
  state.selected = { track, clip, element };
  state.playheadSeconds = Math.max(0, clip.timeline_start_seconds);
  updatePlayhead();
  showDetails(track, clip);
  showManualEditor(track, clip);
  ui.previewTitle.textContent = clip.source.display_name;

  const availability = state.media[clip.source.source_id];
  if (track.kind !== "video") {
    clearPreview(
      track.kind === "audio"
        ? "Audio lane selected. The preview monitor currently presents video material only."
        : "This track type is data-only; no unsupported semantics are inferred.",
    );
    return;
  }
  if (!availability?.available) {
    clearPreview(
      "This source is missing, unsupported, or outside the explicitly allowlisted media roots.",
    );
    return;
  }

  const desiredSource = new URL(availability.url, window.location.href).href;
  if (ui.previewVideo.src !== desiredSource) {
    ui.previewVideo.src = availability.url;
    ui.previewVideo.load();
  }
  ui.monitor.classList.add("has-media");
  ui.previewStatus.textContent =
    "Previewing allowlisted media. Playback updates the local playhead only.";

  const seekToTrim = () => {
    const safeTime = Math.max(0, clip.trim_in_seconds);
    if (Number.isFinite(ui.previewVideo.duration)) {
      ui.previewVideo.currentTime = Math.min(
        safeTime,
        ui.previewVideo.duration,
      );
    } else {
      ui.previewVideo.currentTime = safeTime;
    }
    if (clip.speed_factor >= 0.25 && clip.speed_factor <= 4) {
      ui.previewVideo.playbackRate = clip.speed_factor;
    } else {
      ui.previewVideo.playbackRate = 1;
      ui.previewStatus.textContent =
        `Configured speed ${clip.speed_factor}× is outside browser preview ` +
        "limits; timeline timing remains visible.";
    }
  };
  if (ui.previewVideo.readyState >= 1) {
    seekToTrim();
  } else {
    ui.previewVideo.addEventListener("loadedmetadata", seekToTrim, {
      once: true,
    });
  }
}

function timelineDuration() {
  return Math.max(10, state.snapshot?.duration_seconds || 0);
}

function contentWidth() {
  const viewportWidth = Math.max(
    720,
    ui.scroll.clientWidth - labelWidth(),
  );
  return Math.max(
    viewportWidth,
    Math.ceil(timelineDuration() * state.pixelsPerSecond + 48),
  );
}

function chooseTickInterval() {
  const desiredSeconds = 90 / state.pixelsPerSecond;
  const intervals = [0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  return (
    intervals.find((interval) => interval >= desiredSeconds) ||
    intervals.at(-1)
  );
}

function renderRuler(width) {
  ui.ruler.replaceChildren();
  ui.ruler.style.width = `${width}px`;
  const interval = chooseTickInterval();
  const limit = timelineDuration() + interval;
  for (let second = 0; second <= limit; second += interval) {
    const tick = document.createElement("div");
    tick.className = "ruler-tick";
    tick.style.left = `${second * state.pixelsPerSecond}px`;
    tick.append(textElement("span", "", formatRulerTime(second)));
    ui.ruler.append(tick);
  }
}

function clipLabel(clip) {
  return (
    `${formatSeconds(clip.timeline_start_seconds)} → ` +
    `${formatSeconds(clip.timeline_end_seconds)} · ` +
    formatSeconds(clip.effective_duration_seconds)
  );
}

function renderTimeline() {
  const snapshot = state.snapshot;
  const isEmpty = snapshot.empty;
  ui.empty.hidden = !isEmpty;
  ui.scroll.hidden = isEmpty;
  if (isEmpty) {
    return;
  }

  const width = contentWidth();
  ui.content.style.width = `${width + labelWidth()}px`;
  ui.trackLabels.replaceChildren();
  ui.trackLanes.replaceChildren();
  renderRuler(width);

  snapshot.tracks.forEach((track) => {
    const label = document.createElement("div");
    label.className = "track-label-row";
    const copy = document.createElement("div");
    copy.className = "track-label-copy";
    copy.append(
      textElement("strong", "", track.track_key),
      textElement(
        "span",
        "",
        `${track.clip_count} clip${track.clip_count === 1 ? "" : "s"} · ` +
          formatSeconds(track.duration_seconds),
      ),
    );
    label.append(copy, textElement("span", "track-kind", track.kind));
    ui.trackLabels.append(label);

    const lane = document.createElement("div");
    lane.className = `track-lane ${track.kind}`;
    lane.style.width = `${width}px`;
    lane.style.setProperty("--grid-size", `${state.pixelsPerSecond}px`);
    lane.dataset.trackKey = track.track_key;
    if (track.kind === "other") {
      lane.classList.add("unsupported");
      lane.append(
        textElement(
          "span",
          "unsupported-message",
          "Unsupported track type · snapshot data only",
        ),
      );
    }

    track.clips.forEach((clip) => {
      const block = document.createElement("button");
      block.type = "button";
      block.className = `clip ${track.kind}`;
      block.style.left =
        `${Math.max(0, clip.timeline_start_seconds) * state.pixelsPerSecond}px`;
      block.style.width =
        `${Math.max(28, clip.effective_duration_seconds * state.pixelsPerSecond)}px`;
      block.dataset.clipId = clip.clip_id;
      block.title =
        `${clip.clip_id}\n${clipLabel(clip)}\n${clip.source.value}`;
      block.setAttribute(
        "aria-label",
        `${clip.clip_id}, ${track.kind} clip, ${clipLabel(clip)}`,
      );
      block.append(
        textElement("strong", "", clip.source.display_name),
        textElement("span", "", clipLabel(clip)),
      );
      if (
        state.selected?.track.track_key === track.track_key &&
        state.selected?.clip.clip_id === clip.clip_id
      ) {
        block.classList.add("selected");
        state.selected = { track, clip, element: block };
      }
      block.addEventListener("click", (event) => {
        event.stopPropagation();
        selectClip(track, clip, block);
      });
      lane.append(block);
    });
    ui.trackLanes.append(lane);
  });

  ui.trackLanes.onclick = (event) => {
    const bounds = ui.trackLanes.getBoundingClientRect();
    const seconds =
      (event.clientX - bounds.left + ui.scroll.scrollLeft) /
      state.pixelsPerSecond;
    state.playheadSeconds = Math.max(
      0,
      Math.min(seconds, timelineDuration()),
    );
    updatePlayhead();
  };
  updatePlayhead();
}

function updatePlayhead() {
  ui.timecode.textContent = timecode(state.playheadSeconds);
  const x = Math.max(0, state.playheadSeconds * state.pixelsPerSecond);
  ui.playhead.style.transform = `translateX(${x}px)`;
}

function syncPlayheadFromMedia() {
  if (!state.selected || ui.previewVideo.paused) {
    state.animationFrame = null;
    return;
  }
  const clip = state.selected.clip;
  if (ui.previewVideo.currentTime >= clip.trim_out_seconds) {
    ui.previewVideo.pause();
    ui.previewVideo.currentTime = clip.trim_out_seconds;
  }
  const sourceOffset = Math.max(
    0,
    ui.previewVideo.currentTime - clip.trim_in_seconds,
  );
  state.playheadSeconds = Math.min(
    clip.timeline_end_seconds,
    clip.timeline_start_seconds + sourceOffset / clip.speed_factor,
  );
  updatePlayhead();
  state.animationFrame = window.requestAnimationFrame(syncPlayheadFromMedia);
}

function showFatal(message) {
  ui.fatalErrorMessage.textContent = message;
  ui.fatalError.hidden = false;
  ui.projectName.textContent = "Snapshot unavailable";
  ui.snapshotMeta.textContent = "The local preview could not load timeline data.";
  ui.previewStatus.textContent = message;
}

async function loadPreview({ preserveSuccess = false } = {}) {
  try {
    const response = await fetch("/api/snapshot", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`Snapshot request failed with HTTP ${response.status}.`);
    }
    const payload = await response.json();
    if (!payload.read_only || !payload.snapshot) {
      throw new Error("The preview endpoint returned an invalid contract.");
    }
    state.snapshot = payload.snapshot;
    state.media = payload.media || {};
    state.capabilities = payload.capabilities || {};
    ui.modeBadgeLabel.textContent = state.capabilities.manual_edit_apply === true
      ? "Review + confirm"
      : "Read only";
    ui.timelineHelp.textContent = state.capabilities.manual_edit_apply === true
      ? "Click a clip to inspect it. Drafts stay local and do not write until Confirm & apply."
      : "Click a clip to inspect it. Preview interactions only move the local playhead; project data is unchanged.";
    state.selected = null;
    ui.previewVideo.pause();
    ui.previewVideo.removeAttribute("src");
    ui.previewVideo.load();
    ui.monitor.classList.remove("has-media");
    ui.previewTitle.textContent = "No clip selected";
    ui.clipDetails.replaceChildren(
      detailRow(
        "Status",
        "Select a clip to inspect its immutable snapshot data.",
      ),
    );
    ui.manualEditor.hidden = true;
    ui.manualEditDisabled.hidden = true;
    resetDraft({ keepSuccess: preserveSuccess });
    renderSummary();
    renderTimeline();
    ui.previewStatus.textContent = state.snapshot.empty
      ? "This snapshot is empty. No media preview is available."
      : "Select a video clip to preview allowlisted local media.";
  } catch (error) {
    showFatal(error instanceof Error ? error.message : String(error));
  }
}

function readFiniteInput(input, label) {
  input.removeAttribute("aria-invalid");
  const value = Number(input.value);
  if (!Number.isFinite(value)) {
    input.setAttribute("aria-invalid", "true");
    throw new Error(`${label} must be a finite number.`);
  }
  return value;
}

ui.clipEditForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.selected || state.selected.track.kind !== "video") {
    return;
  }
  try {
    const trimIn = readFiniteInput(ui.editTrimIn, "Source in");
    const trimOut = readFiniteInput(ui.editTrimOut, "Source out");
    const timelineStart = readFiniteInput(
      ui.editTimelineStart,
      "Timeline start",
    );
    const orderIndex = readFiniteInput(ui.editOrder, "Clip order");
    if (trimIn < 0 || trimOut <= trimIn) {
      throw new Error("Source out must be greater than source in.");
    }
    if (timelineStart < 0) {
      throw new Error("Timeline start cannot be negative.");
    }
    if (
      !Number.isInteger(orderIndex) ||
      orderIndex < 0 ||
      orderIndex >= state.snapshot.video_clip_count
    ) {
      throw new Error(
        `Clip order must be an integer from 0 to ` +
          `${Math.max(0, state.snapshot.video_clip_count - 1)}.`,
      );
    }
    const existing = existingDraftForClip(state.selected.clip.clip_id);
    stageEdit({
      schema_version: "1.0.0",
      operation_id:
        existing?.kind === "update"
          ? existing.operation_id
          : newStableId("manual_update"),
      kind: "update",
      track_key: "video",
      clip_id: state.selected.clip.clip_id,
      trim_in_seconds: trimIn,
      trim_out_seconds: trimOut,
      timeline_start_seconds: timelineStart,
      order_index: orderIndex,
    });
    ui.editFormMessage.classList.remove("error");
    ui.editFormMessage.textContent =
      "Change staged locally. Review the proposal below.";
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent =
      error instanceof Error ? error.message : String(error);
  }
});

ui.stageRemove.addEventListener("click", () => {
  if (!state.selected || state.selected.track.kind !== "video") {
    return;
  }
  const existing = existingDraftForClip(state.selected.clip.clip_id);
  stageEdit({
    schema_version: "1.0.0",
    operation_id:
      existing?.kind === "remove"
        ? existing.operation_id
        : newStableId("manual_remove"),
    kind: "remove",
    track_key: "video",
    clip_id: state.selected.clip.clip_id,
  });
  ui.manualEditor.hidden = true;
});

ui.undoDraft.addEventListener("click", () => {
  if (state.draftHistory.length === 0) {
    return;
  }
  state.draftEdits = state.draftHistory.pop();
  state.review = null;
  if (state.selected) {
    showManualEditor(state.selected.track, state.selected.clip);
  }
  validateDraft();
});

ui.resetDraft.addEventListener("click", () => {
  resetDraft();
});

ui.applyDraft.addEventListener("click", async () => {
  if (
    state.applying ||
    !state.review ||
    state.draftEdits.length === 0
  ) {
    return;
  }
  state.applying = true;
  ui.applyDraft.disabled = true;
  setDraftState("Applying");
  ui.draftMessage.classList.remove("error");
  ui.draftMessage.textContent =
    "Dispatching the confirmed proposal through the atomic skill registry…";
  const proposal = proposalPayload();
  const confirmationId = newStableId("manual_confirmation");
  const confirmation = {
    schema_name: "vistora.manual-edit-confirmation",
    schema_version: "1.0.0",
    confirmation_id: confirmationId,
    proposal_ref: state.review.proposal_ref,
    decision: "confirmed",
    confirmed_by: "local_user",
    recorded_at: new Date().toISOString(),
  };
  try {
    const response = await fetch("/api/manual-edits/apply", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ proposal, confirmation }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(
        payload.error?.message ||
          `Apply failed with HTTP ${response.status}.`,
      );
    }
    if (
      payload.confirmation_id !== confirmationId ||
      payload.tool_name !== "VideoApplyManualEditsSkill"
    ) {
      throw new Error("Manual edit apply returned an invalid trace contract.");
    }
    await loadPreview({ preserveSuccess: true });
    ui.applySuccessMessage.textContent =
      `${payload.application_id} · ${payload.tool_name}`;
    ui.applySuccess.hidden = false;
  } catch (error) {
    setDraftState("Apply failed", "error");
    ui.draftMessage.classList.add("error");
    ui.draftMessage.textContent =
      error instanceof Error ? error.message : String(error);
    ui.applyDraft.disabled = false;
  } finally {
    state.applying = false;
  }
});

ui.zoom.addEventListener("input", () => {
  state.pixelsPerSecond = Number(ui.zoom.value);
  ui.zoomValue.textContent = `${state.pixelsPerSecond} px/s`;
  if (state.snapshot && !state.snapshot.empty) {
    renderTimeline();
  }
});

ui.previewVideo.addEventListener("play", () => {
  if (state.animationFrame === null) {
    state.animationFrame = window.requestAnimationFrame(syncPlayheadFromMedia);
  }
});

ui.previewVideo.addEventListener("pause", () => {
  if (state.animationFrame !== null) {
    window.cancelAnimationFrame(state.animationFrame);
    state.animationFrame = null;
  }
});

ui.previewVideo.addEventListener("error", () => {
  if (ui.previewVideo.getAttribute("src")) {
    ui.previewStatus.textContent =
      "The allowlisted source could not be decoded by this browser.";
  }
});

window.addEventListener("resize", () => {
  if (state.snapshot && !state.snapshot.empty) {
    renderTimeline();
  }
});

initializeProposalIdentity();
loadPreview();
