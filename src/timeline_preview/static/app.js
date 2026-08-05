"use strict";

const ui = {
  projectName: document.querySelector("#project-name"),
  snapshotMeta: document.querySelector("#snapshot-meta"),
  summaryStats: document.querySelector("#summary-stats"),
  previewTitle: document.querySelector("#preview-title"),
  previewVideo: document.querySelector("#preview-video"),
  previewImage: document.querySelector("#preview-image"),
  previewStatus: document.querySelector("#preview-status"),
  monitor: document.querySelector(".monitor"),
  subtitleOverlay: document.querySelector("#subtitle-overlay"),
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
  editSplitAt: document.querySelector("#edit-split-at"),
  editRemoveMode: document.querySelector("#edit-remove-mode"),
  editScope: document.querySelector("#edit-scope"),
  editSubtitleRipple: document.querySelector("#edit-subtitle-ripple"),
  editSubtitleTracks: document.querySelector("#edit-subtitle-tracks"),
  editLinkTarget: document.querySelector("#edit-link-target"),
  editTrackOrder: document.querySelector("#edit-track-order"),
  editTrackEnabled: document.querySelector("#edit-track-enabled"),
  editTrackMuted: document.querySelector("#edit-track-muted"),
  editTrackLocked: document.querySelector("#edit-track-locked"),
  editRipple: document.querySelector("#edit-ripple"),
  editFormMessage: document.querySelector("#edit-form-message"),
  stageRemove: document.querySelector("#stage-remove"),
  stageSplit: document.querySelector("#stage-split"),
  stageLink: document.querySelector("#stage-link"),
  stageUnlink: document.querySelector("#stage-unlink"),
  stageTrack: document.querySelector("#stage-track"),
  audioGain: document.querySelector("#audio-gain"),
  audioContentRole: document.querySelector("#audio-content-role"),
  audioPan: document.querySelector("#audio-pan"),
  audioFadeIn: document.querySelector("#audio-fade-in"),
  audioFadeOut: document.querySelector("#audio-fade-out"),
  audioMuted: document.querySelector("#audio-muted"),
  audioTrackGain: document.querySelector("#audio-track-gain"),
  audioTrackPan: document.querySelector("#audio-track-pan"),
  audioTrackMuted: document.querySelector("#audio-track-muted"),
  audioPointId: document.querySelector("#audio-point-id"),
  audioPointTime: document.querySelector("#audio-point-time"),
  audioPointGain: document.querySelector("#audio-point-gain"),
  audioDuckingId: document.querySelector("#audio-ducking-id"),
  audioDuckingKeys: document.querySelector("#audio-ducking-keys"),
  audioDuckingReduction: document.querySelector("#audio-ducking-reduction"),
  audioDuckingAttack: document.querySelector("#audio-ducking-attack"),
  audioDuckingRelease: document.querySelector("#audio-ducking-release"),
  audioAnalysisStatus: document.querySelector("#audio-analysis-status"),
  stageAudio: document.querySelector("#stage-audio"),
  stageTrackMix: document.querySelector("#stage-track-mix"),
  stageEnvelope: document.querySelector("#stage-envelope"),
  deleteEnvelope: document.querySelector("#delete-envelope"),
  clearEnvelope: document.querySelector("#clear-envelope"),
  analyzeLoudness: document.querySelector("#analyze-loudness"),
  applyLoudness: document.querySelector("#apply-loudness"),
  stageDucking: document.querySelector("#stage-ducking"),
  removeDucking: document.querySelector("#remove-ducking"),
  visualPositionX: document.querySelector("#visual-position-x"),
  visualPositionY: document.querySelector("#visual-position-y"),
  visualScaleX: document.querySelector("#visual-scale-x"),
  visualScaleY: document.querySelector("#visual-scale-y"),
  visualRotation: document.querySelector("#visual-rotation"),
  visualOpacity: document.querySelector("#visual-opacity"),
  visualAnchorX: document.querySelector("#visual-anchor-x"),
  visualAnchorY: document.querySelector("#visual-anchor-y"),
  visualCropLeft: document.querySelector("#visual-crop-left"),
  visualCropRight: document.querySelector("#visual-crop-right"),
  visualCropTop: document.querySelector("#visual-crop-top"),
  visualCropBottom: document.querySelector("#visual-crop-bottom"),
  visualFit: document.querySelector("#visual-fit"),
  visualFlipH: document.querySelector("#visual-flip-h"),
  visualFlipV: document.querySelector("#visual-flip-v"),
  colorExposure: document.querySelector("#color-exposure"),
  colorContrast: document.querySelector("#color-contrast"),
  colorSaturation: document.querySelector("#color-saturation"),
  colorTemperature: document.querySelector("#color-temperature"),
  colorTint: document.querySelector("#color-tint"),
  colorHighlights: document.querySelector("#color-highlights"),
  colorShadows: document.querySelector("#color-shadows"),
  colorGamma: document.querySelector("#color-gamma"),
  colorSharpen: document.querySelector("#color-sharpen"),
  colorBlur: document.querySelector("#color-blur"),
  colorToneCurve: document.querySelector("#color-tone-curve"),
  colorLutPreset: document.querySelector("#color-lut-preset"),
  visualCopyComponents: document.querySelector("#visual-copy-components"),
  visualCopyTargets: document.querySelector("#visual-copy-targets"),
  visualPreviewMode: document.querySelector("#visual-preview-mode"),
  visualFormMessage: document.querySelector("#visual-form-message"),
  stageTransform: document.querySelector("#stage-transform"),
  stageColor: document.querySelector("#stage-color"),
  resetVisual: document.querySelector("#reset-visual"),
  copyVisual: document.querySelector("#copy-visual"),
  automationEditPanel: document.querySelector("#automation-edit-panel"),
  automationProperty: document.querySelector("#automation-property"),
  automationTime: document.querySelector("#automation-time"),
  automationValue: document.querySelector("#automation-value"),
  automationInterpolation: document.querySelector("#automation-interpolation"),
  automationId: document.querySelector("#automation-id"),
  keyframeId: document.querySelector("#keyframe-id"),
  automationExisting: document.querySelector("#automation-existing"),
  automationCopyTargets: document.querySelector("#automation-copy-targets"),
  automationPoints: document.querySelector("#automation-points"),
  automationFormMessage: document.querySelector("#automation-form-message"),
  previousKeyframe: document.querySelector("#previous-keyframe"),
  nextKeyframe: document.querySelector("#next-keyframe"),
  stageKeyframe: document.querySelector("#stage-keyframe"),
  deleteKeyframe: document.querySelector("#delete-keyframe"),
  clearAutomation: document.querySelector("#clear-automation"),
  clearAllAutomation: document.querySelector("#clear-all-automation"),
  copyAutomation: document.querySelector("#copy-automation"),
  maskEditPanel: document.querySelector("#mask-edit-panel"),
  maskId: document.querySelector("#mask-id"),
  maskKind: document.querySelector("#mask-kind"),
  maskOperation: document.querySelector("#mask-operation"),
  maskX: document.querySelector("#mask-x"),
  maskY: document.querySelector("#mask-y"),
  maskWidth: document.querySelector("#mask-width"),
  maskHeight: document.querySelector("#mask-height"),
  maskFeather: document.querySelector("#mask-feather"),
  maskExpand: document.querySelector("#mask-expand"),
  maskOpacity: document.querySelector("#mask-opacity"),
  maskInvert: document.querySelector("#mask-invert"),
  maskPoints: document.querySelector("#mask-points"),
  maskAutomationProperty: document.querySelector("#mask-automation-property"),
  maskKeyframeTime: document.querySelector("#mask-keyframe-time"),
  maskKeyframeValue: document.querySelector("#mask-keyframe-value"),
  maskKeyframeInterpolation: document.querySelector("#mask-keyframe-interpolation"),
  blendMode: document.querySelector("#blend-mode"),
  cornerRadius: document.querySelector("#corner-radius"),
  shadowOpacity: document.querySelector("#shadow-opacity"),
  shadowBlur: document.querySelector("#shadow-blur"),
  shadowOffsetX: document.querySelector("#shadow-offset-x"),
  shadowOffsetY: document.querySelector("#shadow-offset-y"),
  glowStrength: document.querySelector("#glow-strength"),
  glowRadius: document.querySelector("#glow-radius"),
  maskCopyTargets: document.querySelector("#mask-copy-targets"),
  maskFormMessage: document.querySelector("#mask-form-message"),
  stageMask: document.querySelector("#stage-mask"),
  stageMaskKeyframe: document.querySelector("#stage-mask-keyframe"),
  removeMask: document.querySelector("#remove-mask"),
  copyMasks: document.querySelector("#copy-masks"),
  stageComposite: document.querySelector("#stage-composite"),
  transitionEditPanel: document.querySelector("#transition-edit-panel"),
  transitionToClip: document.querySelector("#transition-to-clip"),
  transitionKind: document.querySelector("#transition-kind"),
  transitionDuration: document.querySelector("#transition-duration"),
  transitionAlignment: document.querySelector("#transition-alignment"),
  transitionDirection: document.querySelector("#transition-direction"),
  transitionColor: document.querySelector("#transition-color"),
  transitionAudioPolicy: document.querySelector("#transition-audio-policy"),
  transitionAudioKind: document.querySelector("#transition-audio-kind"),
  transitionCopyTargets: document.querySelector("#transition-copy-targets"),
  transitionFormMessage: document.querySelector("#transition-form-message"),
  previewTransition: document.querySelector("#preview-transition"),
  stageTransition: document.querySelector("#stage-transition"),
  removeTransition: document.querySelector("#remove-transition"),
  copyTransition: document.querySelector("#copy-transition"),
  subtitleEditor: document.querySelector("#subtitle-editor"),
  subtitleTrackSelect: document.querySelector("#subtitle-track-select"),
  subtitleTrackKind: document.querySelector("#subtitle-track-kind"),
  subtitleTrackLanguage: document.querySelector("#subtitle-track-language"),
  subtitleTrackOrder: document.querySelector("#subtitle-track-order"),
  subtitleTrackEnabled: document.querySelector("#subtitle-track-enabled"),
  subtitleTrackLocked: document.querySelector("#subtitle-track-locked"),
  subtitleCreateTrack: document.querySelector("#subtitle-create-track"),
  subtitleStageTrack: document.querySelector("#subtitle-stage-track"),
  subtitleDeleteTrack: document.querySelector("#subtitle-delete-track"),
  subtitleCueId: document.querySelector("#subtitle-cue-id"),
  subtitleStart: document.querySelector("#subtitle-start"),
  subtitleEnd: document.querySelector("#subtitle-end"),
  subtitleLanguage: document.querySelector("#subtitle-language"),
  subtitleSpeaker: document.querySelector("#subtitle-speaker"),
  subtitleCueKind: document.querySelector("#subtitle-cue-kind"),
  subtitleText: document.querySelector("#subtitle-text"),
  subtitleWords: document.querySelector("#subtitle-words"),
  subtitleSplitAt: document.querySelector("#subtitle-split-at"),
  subtitleFont: document.querySelector("#subtitle-font"),
  subtitleFontSize: document.querySelector("#subtitle-font-size"),
  subtitleColor: document.querySelector("#subtitle-color"),
  subtitleOutlineColor: document.querySelector("#subtitle-outline-color"),
  subtitleBackgroundColor: document.querySelector("#subtitle-background-color"),
  subtitleAlignment: document.querySelector("#subtitle-alignment"),
  subtitlePosition: document.querySelector("#subtitle-position"),
  subtitleBold: document.querySelector("#subtitle-bold"),
  subtitleItalic: document.querySelector("#subtitle-italic"),
  subtitleAddCue: document.querySelector("#subtitle-add-cue"),
  subtitleUpdateCue: document.querySelector("#subtitle-update-cue"),
  subtitleSplitCue: document.querySelector("#subtitle-split-cue"),
  subtitleMergeNext: document.querySelector("#subtitle-merge-next"),
  subtitleDeleteCue: document.querySelector("#subtitle-delete-cue"),
  subtitleStageStyle: document.querySelector("#subtitle-stage-style"),
  subtitleImportFile: document.querySelector("#subtitle-import-file"),
  subtitleImport: document.querySelector("#subtitle-import"),
  subtitleDownloadSrt: document.querySelector("#subtitle-download-srt"),
  subtitleDownloadVtt: document.querySelector("#subtitle-download-vtt"),
  subtitleFormMessage: document.querySelector("#subtitle-form-message"),
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
  planReviewPanel: document.querySelector("#plan-review-panel"),
  planReviewMessage: document.querySelector("#plan-review-message"),
  planReviewStatus: document.querySelector("#plan-review-status"),
  planReviewSummary: document.querySelector("#plan-review-summary"),
  planReviewGroups: document.querySelector("#plan-review-groups"),
  reviewBack: document.querySelector("#review-back"),
  reviewReject: document.querySelector("#review-reject"),
  reviewReady: document.querySelector("#review-ready"),
  directorPanel: document.querySelector("#director-panel"),
  directorMessage: document.querySelector("#director-message"),
  directorStatus: document.querySelector("#director-status"),
  directorBrief: document.querySelector("#director-brief"),
  directorTurns: document.querySelector("#director-turns"),
  directorLimitations: document.querySelector("#director-limitations"),
  productPanel: document.querySelector("#product-panel"),
  productMessage: document.querySelector("#product-message"),
  productStatus: document.querySelector("#product-status"),
  productDialogue: document.querySelector("#product-dialogue"),
  productUserMessage: document.querySelector("#product-user-message"),
  productSend: document.querySelector("#product-send"),
  productSummary: document.querySelector("#product-summary"),
  productActions: document.querySelector("#product-actions"),
  workflowPanel: document.querySelector("#workflow-panel"),
  workflowMessage: document.querySelector("#workflow-message"),
  workflowStatus: document.querySelector("#workflow-status"),
  workflowHistory: document.querySelector("#workflow-history"),
  workflowActions: document.querySelector("#workflow-actions"),
  workflowLimitations: document.querySelector("#workflow-limitations"),
};

const state = {
  snapshot: null,
  media: {},
  pixelsPerSecond: Number(ui.zoom.value),
  playheadSeconds: 0,
  selected: null,
  selectedSubtitle: null,
  animationFrame: null,
  capabilities: {},
  analysis: {},
  analysisState: "idle",
  draftEdits: [],
  draftHistory: [],
  proposalId: null,
  proposalCreatedAt: null,
  review: null,
  applying: false,
  loudnessEvidence: null,
  visualPreviewMode: "applied",
  planReview: null,
  selectedPlanChange: null,
  director: null,
  product: null,
  productCsrf: null,
  productBusy: false,
  workflow: null,
  workflowBusy: false,
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

function planChanges() {
  return state.planReview?.diff?.changes || [];
}

function changesForClip(trackKey, clipId) {
  return planChanges().filter(
    (change) =>
      change.entity?.entity_kind === "clip" &&
      change.entity.track_key === trackKey &&
      change.entity.entity_id === clipId,
  );
}

function safeChangeState(stateValue) {
  if (!stateValue) {
    return "—";
  }
  if ("width" in stateValue && "height" in stateValue) {
    return `${stateValue.width}×${stateValue.height} · ${stateValue.fps} fps`;
  }
  if ("track_id" in stateValue && "gain_db" in stateValue) {
    return `${stateValue.gain_db} dB · pan ${stateValue.pan} · ` +
      `${stateValue.muted ? "muted" : "active"}`;
  }
  if ("transition_id" in stateValue) {
    return `${stateValue.kind.replaceAll("_", " ")} / ` +
      `${formatSeconds(stateValue.duration_seconds)} / ` +
      `${stateValue.from_clip_id} -> ${stateValue.to_clip_id}`;
  }
  return (
    `${formatSeconds(stateValue.timeline_start_seconds)}–` +
    `${formatSeconds(stateValue.timeline_end_seconds)} · ` +
    `${formatSeconds(stateValue.trim_in_seconds)}–` +
    `${formatSeconds(stateValue.trim_out_seconds)} source · ` +
    (stateValue.freeze_frame_source_time_seconds != null
      ? `freeze @ ${formatSeconds(stateValue.freeze_frame_source_time_seconds)} / ` +
        `${formatSeconds(stateValue.freeze_frame_duration_seconds)} · `
      : `${stateValue.speed_factor}× · `) +
    `audio ${stateValue.audio_gain_db ?? 0} dB · ` +
    `pan ${stateValue.audio_pan ?? 0} · ` +
    `${stateValue.audio_envelope?.length || 0} envelope points`
  );
}

function showPlanChangeDetails(change) {
  state.selectedPlanChange = change;
  const evidence = change.evidence?.length
    ? change.evidence
        .map((item) => {
          const range = item.locator_type === "media_time_range"
            ? ` ${formatSeconds(item.start_seconds)}–${formatSeconds(item.end_seconds)}`
            : " whole material";
          return `${item.evidence_id} / ${item.material_id}${range}`;
        })
        .join("; ")
    : "No source evidence attached";
  const provenance = change.current_provenance;
  ui.clipDetails.replaceChildren(
    detailRow("Proposed change", change.change_id),
    detailRow("Category", change.category.replaceAll("_", " ")),
    detailRow("Effect", `${change.effect_kind} · ${change.severity}`),
    detailRow("Plan operation", change.operation_id),
    detailRow("Execution step", change.step_id),
    detailRow("Atomic tool", change.tool_name),
    detailRow("Director rationale", change.director_rationale),
    detailRow("Expected effect", change.expected_effect),
    detailRow(
      "Before",
      safeChangeState(
        change.before || change.before_project || change.before_track_mix ||
          change.before_transition,
      ),
    ),
    detailRow(
      "After",
      safeChangeState(
        change.after || change.after_project || change.after_track_mix ||
          change.after_transition,
      ),
    ),
    detailRow("Reason", change.reason),
    detailRow("Source evidence", evidence),
    detailRow(
      "Current origin",
      provenance
        ? `${provenance.origin_kind.replaceAll("_", " ")} · ` +
          provenance.mapping_status.replaceAll("_", " ")
        : "New entity or no current provenance",
    ),
  );
}

function selectPlanChange(change) {
  document
    .querySelectorAll(".review-change.selected")
    .forEach((item) => item.classList.remove("selected"));
  const row = document.querySelector(
    `[data-change-id="${CSS.escape(change.change_id)}"]`,
  );
  row?.classList.add("selected");
  state.selectedPlanChange = change;
  const matching = document.querySelector(
    `.clip[data-track-key="${CSS.escape(change.entity.track_key || "")}"]` +
      `[data-clip-id="${CSS.escape(change.entity.entity_id)}"]`,
  );
  matching?.focus({ preventScroll: true });
  showPlanChangeDetails(change);
  renderTimeline();
}

function renderPlanReview() {
  const envelope = state.planReview;
  if (!envelope || envelope.review_state === "unavailable") {
    ui.planReviewPanel.hidden = true;
    return;
  }
  ui.planReviewPanel.hidden = false;
  ui.planReviewStatus.textContent = envelope.review_state;
  ui.planReviewStatus.className =
    `review-status ${envelope.review_state}`;
  ui.planReviewMessage.textContent = envelope.message;
  ui.planReviewSummary.replaceChildren();
  ui.planReviewGroups.replaceChildren();
  const diff = envelope.diff;
  const current = envelope.review_state === "current" && diff;
  ui.reviewReady.disabled = !current || diff.review_status === "blocked";
  if (!current) {
    ui.reviewReject.disabled = false;
    return;
  }
  ui.planReviewStatus.textContent = diff.review_status;
  ui.planReviewStatus.className = `review-status ${diff.review_status}`;
  const summaryItems = [
    ["Before / after", `${diff.summary.before_clip_count} → ${diff.summary.after_clip_count} clips`],
    ["Added", String(diff.summary.additions)],
    ["Removed", String(diff.summary.removals)],
    ["Changed", String(diff.summary.modifications)],
    ["Warnings", `${diff.summary.warnings} / ${diff.summary.blockers} blockers`],
  ];
  for (const [label, value] of summaryItems) {
    const item = document.createElement("div");
    item.append(textElement("dt", "", label), textElement("dd", "", value));
    ui.planReviewSummary.append(item);
  }
  const groups = [
    ["Added", (change) => change.category === "clip_addition"],
    ["Removed", (change) => change.category === "clip_removal"],
    [
      "Changed",
      (change) =>
        !["clip_addition", "clip_removal", "warning"].includes(
          change.category,
        ) && change.severity !== "blocker",
    ],
    [
      "Warnings",
      (change) =>
        change.category === "warning" ||
        ["warning", "blocker"].includes(change.severity),
    ],
  ];
  for (const [title, predicate] of groups) {
    const matching = diff.changes.filter(predicate);
    if (matching.length === 0) {
      continue;
    }
    const group = document.createElement("section");
    group.className = "review-group";
    group.append(textElement("h3", "", `${title} · ${matching.length}`));
    const rows = document.createElement("div");
    rows.className = "review-change-list";
    for (const change of matching) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = `review-change ${change.severity}`;
      row.dataset.changeId = change.change_id;
      row.append(
        textElement(
          "strong",
          "",
          change.after?.source_name ||
            change.before?.source_name ||
            change.entity.entity_id,
        ),
        textElement(
          "span",
          "",
          `${change.category.replaceAll("_", " ")} · ${change.reason}`,
        ),
        textElement(
          "small",
          "",
          `${change.operation_id} / ${change.step_id}`,
        ),
      );
      row.addEventListener("click", () => selectPlanChange(change));
      rows.append(row);
    }
    group.append(rows);
    ui.planReviewGroups.append(group);
  }
}

async function loadPlanReview() {
  try {
    const response = await fetch("/api/plan-review", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await response.json();
    if (
      !response.ok ||
      payload.schema_name !== "vistora.plan-review-envelope" ||
      payload.schema_version !== "1.0.0"
    ) {
      throw new Error("The plan-review endpoint returned an invalid contract.");
    }
    state.planReview = payload;
  } catch (error) {
    state.planReview = {
      review_state: "invalid",
      message: error instanceof Error ? error.message : String(error),
    };
  }
  state.selectedPlanChange = null;
  renderPlanReview();
  renderTimeline();
}

function workflowButton(label, action, className = "") {
  const button = textElement("button", `button ${className}`.trim(), label);
  button.type = "button";
  button.disabled = state.workflowBusy;
  button.addEventListener("click", action);
  return button;
}

function workflowEvent(title, status, details) {
  const article = document.createElement("article");
  article.className = "workflow-event";
  article.append(
    textElement("strong", "", title),
    textElement("span", `workflow-event-status ${status}`, status),
  );
  for (const detail of details) {
    article.append(textElement("small", "", detail));
  }
  return article;
}

function renderDirector() {
  const history = state.director;
  ui.directorPanel.hidden = !history ||
    history.schema_name === "vistora.director-history-unavailable";
  if (ui.directorPanel.hidden) {
    return;
  }
  ui.directorStatus.textContent = history.latest_status;
  ui.directorStatus.className =
    `review-status ${history.latest_status}`;
  ui.directorMessage.textContent =
    `Append-only Director revision ${history.ledger_revision} · ` +
    `${history.integrity_digest.slice(0, 20)}…`;
  ui.directorBrief.replaceChildren();
  const brief = history.latest_brief;
  if (brief) {
    const values = [
      ["Readiness", brief.readiness],
      ["Brief version", `v${brief.brief_version}`],
      ["Objective", brief.objective || "Unresolved"],
      ["Audience", brief.audience || "Unresolved"],
      ["Platform", brief.platform || "Unresolved"],
      [
        "Duration",
        brief.target_duration_seconds == null
          ? "Unresolved"
          : formatSeconds(brief.target_duration_seconds),
      ],
      ["Style", brief.style || "Unresolved"],
      ["Pacing", brief.pacing || "Unresolved"],
      [
        "Material state",
        brief.material_state?.state?.replaceAll("_", " ") || "legacy unknown",
      ],
      ["Materials", `${brief.material_ids.length} observed`],
      ["Evidence", `${brief.evidence_ids.length} bound`],
    ];
    for (const [label, value] of values) {
      ui.directorBrief.append(detailRow(label, value));
    }
    ui.directorBrief.append(
      detailRow("Reason", brief.readiness_reasons.join(" ")),
    );
    if (brief.material_state?.reasons?.length) {
      ui.directorBrief.append(
        detailRow("Material evidence", brief.material_state.reasons.join(" ")),
      );
    }
  }
  ui.directorTurns.replaceChildren();
  for (const turn of history.turns) {
    const details = [
      `brief v${turn.brief_version}`,
      turn.assistant_message,
      ...turn.clarification_questions.map(
        (question) => `Question: ${question}`,
      ),
    ];
    if (turn.error) {
      details.push(`${turn.error.code}: ${turn.error.message}`);
    }
    ui.directorTurns.append(
      workflowEvent(
        `Director turn ${turn.turn_index}`,
        turn.status,
        details,
      ),
    );
  }
  for (const proposal of history.proposals) {
    ui.directorTurns.append(
      workflowEvent(
        `Proposal ${proposal.plan_id} v${proposal.plan_version}`,
        proposal.review_status || proposal.review_state,
        [
          proposal.plan_digest,
          proposal.diff_digest || "No review diff",
          "Awaiting a separate explicit user decision.",
        ],
      ),
    );
  }
  for (const proposal of history.material_requirements || []) {
    ui.directorTurns.append(
      workflowEvent(
        `Material requirements ${proposal.plan_id} v${proposal.plan_version}`,
        "reviewable",
        [
          `${proposal.item_count} required material item(s)`,
          proposal.plan_digest,
          proposal.review_digest,
          "Planned materials are not existing evidence.",
        ],
      ),
    );
  }
  ui.directorLimitations.replaceChildren(
    ...history.limitations.map((item) => textElement("li", "", item)),
  );
}

function latest(items) {
  return items && items.length ? items[items.length - 1] : null;
}

function productTarget(action, view) {
  const directorProposal = latest(view.director?.proposals);
  const workflow = view.workflow || {};
  const review = latest(workflow.reviews);
  const confirmation = [...(workflow.confirmations || [])]
    .reverse().find((item) => item.decision === "confirmed");
  const execution = latest(workflow.executions);
  const rollbackReview = latest(workflow.rollback_reviews);
  const rollbackConfirmation = [...(workflow.rollback_confirmations || [])]
    .reverse().find((item) => item.decision === "confirmed");
  const material = view.material_requirements || {};
  const materialProposal = latest(material.proposals);
  const materialConfirmation = [...(material.decisions || [])]
    .reverse().find((item) => item.decision === "confirmed");
  const creation = view.creation_planning || {};
  const productionProposal = latest(creation.proposals);
  const productionConfirmation = [...(creation.decisions || [])]
    .reverse().find((item) => item.decision === "confirmed");
  const production = view.material_production || {};
  const productionRun = latest(production.runs);
  const activeJob = [...(production.jobs || [])].reverse().find(
    (item) => ["submitted", "running", "needs_input", "rate_limited"]
      .includes(item.status),
  );
  const retryableJob = [...(production.jobs || [])].reverse().find(
    (item) =>
      ["failed", "timed_out", "cancelled", "recovery_required"]
        .includes(item.status) ||
      (
        item.status === "succeeded" &&
        (production.artifacts || []).some(
          (artifact) =>
            artifact.job_id === item.job_id &&
            artifact.decision === "rejected",
        )
      ),
  );
  const reviewArtifact = [...(production.artifacts || [])].reverse().find(
    (item) => item.passed && !item.decision,
  );
  return {
    persist_review: directorProposal?.proposal_id,
    confirm: review?.review_id,
    reject: review?.review_id,
    execute: confirmation?.confirmation_record_id,
    rollback_review: execution?.run_id,
    rollback_confirm: rollbackReview?.review_id,
    rollback_reject: rollbackReview?.review_id,
    rollback_apply: rollbackConfirmation?.confirmation_id,
    persist_material_review: materialProposal?.proposal_id ||
      latest(view.director?.material_requirements)?.proposal_id,
    confirm_materials: materialProposal?.review_id,
    reject_materials: materialProposal?.review_id,
    withdraw_materials: materialProposal?.proposal_id,
    plan_material_production: materialConfirmation?.confirmation_id,
    confirm_production_plan: productionProposal?.review_id,
    reject_production_plan: productionProposal?.review_id,
    withdraw_production_plan: productionProposal?.proposal_id,
    start_material_production: productionConfirmation?.confirmation_id,
    poll_material_production: productionRun?.run_id,
    cancel_material_job: activeJob?.job_id,
    retry_material_job: retryableJob?.job_id || activeJob?.job_id,
    accept_material_artifact: reviewArtifact?.artifact_id,
    reject_material_artifact: reviewArtifact?.artifact_id,
    return_to_director: productionRun?.run_id,
  }[action] || null;
}

function productActionLabel(action) {
  return {
    persist_review: "Persist exact review",
    confirm: "Explicitly confirm",
    reject: "Reject proposal",
    execute: "Run confirmed Editing Agent",
    rollback_review: "Review timeline restore",
    rollback_confirm: "Confirm timeline restore",
    rollback_reject: "Reject timeline restore",
    rollback_apply: "Apply confirmed restore",
    persist_material_review: "Review material requirements",
    confirm_materials: "Confirm material requirements",
    reject_materials: "Reject material requirements",
    withdraw_materials: "Withdraw material proposal",
    plan_material_production: "Plan how to produce materials",
    confirm_production_plan: "Confirm production plan",
    reject_production_plan: "Reject production plan",
    withdraw_production_plan: "Withdraw production plan",
    start_material_production: "Start confirmed material production",
    poll_material_production: "Refresh production jobs",
    cancel_material_job: "Cancel selected job",
    retry_material_job: "Retry selected job",
    accept_material_artifact: "Accept validated material",
    reject_material_artifact: "Reject material",
    return_to_director: "Return to Director",
  }[action] || action;
}

function renderProduct() {
  const view = state.product;
  ui.productPanel.hidden = !view;
  if (!view) {
    return;
  }
  ui.productStatus.textContent = view.state;
  ui.productStatus.className = `review-status ${view.state}`;
  ui.productMessage.textContent =
    `Session ${view.session_id} · revision ${view.revision}`;
  ui.productSummary.replaceChildren(
    workflowEvent(
      "Exact state machine",
      view.state,
      [
        `Project ${view.project_id}`,
        `Director ${view.director.latest_status}`,
        `Workflow ${view.workflow.state}`,
        ...(view.latest_result
          ? [`Latest result ${JSON.stringify(view.latest_result)}`]
          : []),
      ],
    ),
  );
  const materialProposal = latest(
    view.material_requirements?.proposals ||
      view.director?.material_requirements ||
      [],
  );
  if (materialProposal) {
    ui.productSummary.append(
      workflowEvent(
        `Material requirements v${materialProposal.plan_version}`,
        view.material_requirements?.state || "reviewable",
        [
          ...materialProposal.items.map(
            (item) =>
              `${item.priority} · ${item.asset_type} · ${item.purpose}`,
          ),
          "Planned items remain non-existent until a later production stage.",
        ],
      ),
    );
  }
  const productionProposal = latest(view.creation_planning?.proposals || []);
  if (productionProposal) {
    ui.productSummary.append(
      workflowEvent(
        `Material production plan v${productionProposal.plan_version}`,
        view.creation_planning?.state || "reviewable",
        [
          ...productionProposal.tasks.map(
            (task) =>
              `${task.status} / ${task.method} / ${task.title}`,
          ),
          ...(productionProposal.warnings || []),
          "This plan does not invoke providers or create media.",
        ],
      ),
    );
  }
  const production = view.material_production;
  if (production) {
    for (const run of production.runs || []) {
      ui.productSummary.append(
        workflowEvent(
          `Material production run ${run.run_id}`,
          run.status,
          [
            run.message,
            `Production plan ${run.production_plan_id}`,
          ],
        ),
      );
    }
    for (const job of production.jobs || []) {
      ui.productSummary.append(
        workflowEvent(
          `Job ${job.task_id} / attempt ${job.attempt}`,
          job.status,
          [
            `Adapter ${job.adapter_id}`,
            `${Math.round(job.progress * 100)}% / cost ${job.cost_status}`,
            job.message,
            ...(job.error_code ? [`Error ${job.error_code}`] : []),
          ],
        ),
      );
    }
    for (const artifact of production.artifacts || []) {
      ui.productSummary.append(
        workflowEvent(
          `Artifact ${artifact.artifact_id}`,
          artifact.decision || (artifact.passed ? "validated" : "invalid"),
          [
            `${artifact.mime_type || "unknown"} / ${artifact.size_bytes || 0} bytes`,
            `${artifact.width || "?"}x${artifact.height || "?"} / ${artifact.duration_seconds || "?"}s`,
            ...(artifact.issues || []),
            "Acceptance is required before this becomes Director-observable.",
          ],
        ),
      );
    }
    for (const material of production.catalog || []) {
      ui.productSummary.append(
        workflowEvent(
          `Catalog material ${material.material_id}`,
          "accepted",
          [
            `${material.media_kind} / ${material.display_name}`,
            `Origin ${material.origin_kind} / requirement ${material.requirement_item_id}`,
            `License ${material.license_status}`,
            ...(material.usage_restrictions || []),
          ],
        ),
      );
    }
  }
  ui.productActions.replaceChildren();
  for (const action of view.allowed_actions) {
    if (action === "director_turn") {
      continue;
    }
    const target = productTarget(action, view);
    const button = workflowButton(
      productActionLabel(action),
      () => productPost(action, target),
      action.includes("reject") ? "" : "confirm",
    );
    button.disabled = state.productBusy || !target;
    ui.productActions.append(button);
  }
  ui.productSend.disabled = state.productBusy ||
    !view.allowed_actions.includes("director_turn");
}

async function loadProduct() {
  try {
    const response = await fetch("/api/product", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(
        payload.error?.message || `Product HTTP ${response.status}.`,
      );
    }
    if (payload.schema_name === "vistora.product-entry-unavailable") {
      state.product = null;
      state.productCsrf = null;
    } else {
      state.product = payload.view;
      state.productCsrf = payload.csrf_token;
    }
  } catch (error) {
    state.product = null;
    state.productCsrf = null;
    ui.productPanel.hidden = false;
    ui.productStatus.textContent = "error";
    ui.productMessage.textContent =
      error instanceof Error ? error.message : String(error);
  }
  renderProduct();
}

async function productPost(action, targetId = null, userMessage = null) {
  if (state.productBusy || !state.product || !state.productCsrf) {
    return;
  }
  state.productBusy = true;
  renderProduct();
  try {
    const requestId = newStableId("product_request");
    const payload = {
      schema_name: "vistora.product-entry-command",
      schema_version: "1.0.0",
      request_id: requestId,
      session_id: state.product.session_id,
      project_id: state.product.project_id,
      expected_revision: state.product.revision,
      action,
      actor_id: "local_user",
      user_message: userMessage,
      target_id: targetId,
    };
    const response = await fetch("/api/product/actions", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Vistora-CSRF": state.productCsrf,
      },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(
        body.error?.message || `Product HTTP ${response.status}.`,
      );
    }
    state.product = body.view;
    await loadDirector();
    await loadPlanReview();
    await loadWorkflow();
  } catch (error) {
    ui.productMessage.textContent =
      error instanceof Error ? error.message : String(error);
  } finally {
    state.productBusy = false;
    renderProduct();
  }
}

async function loadDirector() {
  try {
    const response = await fetch("/api/director", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(
        payload.error?.message || `Director HTTP ${response.status}.`,
      );
    }
    state.director = payload;
  } catch (error) {
    state.director = {
      schema_name: "vistora.director-history",
      latest_status: "error",
      ledger_revision: 0,
      integrity_digest: "sha256:unavailable",
      latest_brief: null,
      turns: [],
      proposals: [],
      limitations: [],
    };
    ui.directorMessage.textContent =
      error instanceof Error ? error.message : String(error);
  }
  renderDirector();
}

function renderWorkflow() {
  const history = state.workflow;
  ui.workflowPanel.hidden = !history ||
    history.schema_name === "vistora.workflow-history-unavailable";
  if (ui.workflowPanel.hidden) {
    return;
  }
  ui.workflowStatus.textContent = history.state;
  ui.workflowStatus.className = `review-status ${history.state}`;
  ui.workflowMessage.textContent =
    `Append-only revision ${history.ledger_revision} · ` +
    `${history.integrity_digest.slice(0, 20)}…`;
  ui.workflowHistory.replaceChildren();
  for (const plan of history.plan_versions) {
    ui.workflowHistory.append(
      workflowEvent(
        `Plan ${plan.plan_id} v${plan.plan_version}`,
        "drafted",
        [plan.plan_digest, plan.recorded_at],
      ),
    );
  }
  for (const review of history.reviews) {
    ui.workflowHistory.append(
      workflowEvent(
        `Review ${review.review_id}`,
        review.review_status,
        [
          `snapshot r${review.snapshot_revision}`,
          review.diff_digest,
        ],
      ),
    );
  }
  for (const confirmation of history.confirmations) {
    ui.workflowHistory.append(
      workflowEvent(
        `Decision ${confirmation.confirmation_record_id}`,
        confirmation.decision,
        [
          `review ${confirmation.review_id}`,
          `by ${confirmation.confirmed_by}`,
        ],
      ),
    );
  }
  for (const execution of history.executions) {
    const details = [
      execution.status_history.join(" → "),
      `result revision ${execution.resulting_project_revision}`,
      `${execution.steps.length} recorded step(s)`,
    ];
    if (execution.error) {
      details.push(`${execution.error.code}: ${execution.error.message}`);
    }
    ui.workflowHistory.append(
      workflowEvent(
        `Execution ${execution.run_id}`,
        execution.status,
        details,
      ),
    );
    for (const step of execution.steps) {
      ui.workflowHistory.append(
        workflowEvent(
          `↳ ${step.step_id}`,
          step.status,
          [
            step.tool_name,
            `${step.request_id} → ${step.result_id}`,
          ],
        ),
      );
    }
  }
  for (const review of history.rollback_reviews) {
    ui.workflowHistory.append(
      workflowEvent(
        `Rollback review ${review.review_id}`,
        "reviewed",
        [
          `${review.change_count} timeline change(s)`,
          `source execution ${review.source_run_id}`,
        ],
      ),
    );
  }
  for (const rollback of history.rollbacks) {
    const details = [
      rollback.status_history.join(" → "),
      "External media files unchanged",
    ];
    if (rollback.error) {
      details.push(`${rollback.error.code}: ${rollback.error.message}`);
    }
    ui.workflowHistory.append(
      workflowEvent(
        `Rollback ${rollback.rollback_run_id}`,
        rollback.status,
        details,
      ),
    );
  }
  if (ui.workflowHistory.childElementCount === 0) {
    ui.workflowHistory.append(
      textElement(
        "p",
        "muted",
        "No persisted workflow records for this project yet.",
      ),
    );
  }

  ui.workflowLimitations.replaceChildren(
    ...history.limitations.map((item) => textElement("li", "", item)),
  );
  ui.workflowActions.replaceChildren();
  const lastReview = history.reviews.at(-1);
  const decisionForReview = history.confirmations.find(
    (item) => item.review_id === lastReview?.review_id,
  );
  const lastConfirmed = [...history.confirmations]
    .reverse()
    .find((item) => item.decision === "confirmed");
  const executionForConfirmation = history.executions.find(
    (item) =>
      item.confirmation_record_id ===
      lastConfirmed?.confirmation_record_id,
  );
  const rollbackReviewForExecution = history.rollback_reviews.find(
    (item) => item.source_run_id === executionForConfirmation?.run_id,
  );
  const rollbackDecision = history.rollback_confirmations.find(
    (item) => item.review_id === rollbackReviewForExecution?.review_id,
  );
  const rollbackRun = history.rollbacks.find(
    (item) =>
      item.source_run_id === rollbackReviewForExecution?.source_run_id,
  );

  if (!lastReview && state.planReview?.review_state === "current") {
    ui.workflowActions.append(
      workflowButton("Persist exact review", () =>
        workflowPost("/api/workflow/reviews", {}), "confirm"),
    );
  } else if (lastReview && !decisionForReview) {
    ui.workflowActions.append(
      workflowButton("Persist rejection", () =>
        workflowPost("/api/workflow/confirmations", {
          review_id: lastReview.review_id,
          confirmed_by: "local_user",
          decision: "rejected",
        }), "danger"),
      workflowButton("Explicitly confirm", () =>
        workflowPost("/api/workflow/confirmations", {
          review_id: lastReview.review_id,
          confirmed_by: "local_user",
          decision: "confirmed",
        }), "confirm"),
    );
  } else if (
    lastConfirmed &&
    !executionForConfirmation
  ) {
    ui.workflowActions.append(
      workflowButton("Run confirmed execution", () =>
        workflowPost("/api/workflow/executions", {
          confirmation_record_id: lastConfirmed.confirmation_record_id,
        }), "confirm"),
    );
  } else if (
    executionForConfirmation?.rollback_available &&
    !rollbackReviewForExecution
  ) {
    ui.workflowActions.append(
      workflowButton("Generate rollback review", () =>
        workflowPost("/api/workflow/rollbacks/reviews", {
          source_run_id: executionForConfirmation.run_id,
        })),
    );
  } else if (rollbackReviewForExecution && !rollbackDecision) {
    ui.workflowActions.append(
      workflowButton("Reject rollback", () =>
        workflowPost("/api/workflow/rollbacks/confirmations", {
          review_id: rollbackReviewForExecution.review_id,
          confirmed_by: "local_user",
          decision: "rejected",
        }), "danger"),
      workflowButton("Confirm timeline restore", () =>
        workflowPost("/api/workflow/rollbacks/confirmations", {
          review_id: rollbackReviewForExecution.review_id,
          confirmed_by: "local_user",
          decision: "confirmed",
        }), "confirm"),
    );
  } else if (
    rollbackDecision?.decision === "confirmed" &&
    !rollbackRun
  ) {
    ui.workflowActions.append(
      workflowButton("Apply confirmed restore", () =>
        workflowPost("/api/workflow/rollbacks/runs", {
          confirmation_id: rollbackDecision.confirmation_id,
        }), "confirm"),
    );
  }
}

async function loadWorkflow() {
  try {
    const response = await fetch("/api/workflow", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(
        payload.error?.message || `Workflow HTTP ${response.status}.`,
      );
    }
    state.workflow = payload;
  } catch (error) {
    state.workflow = null;
    ui.workflowPanel.hidden = false;
    ui.workflowStatus.textContent = "error";
    ui.workflowStatus.className = "review-status invalid";
    ui.workflowMessage.textContent =
      error instanceof Error ? error.message : String(error);
  }
  renderWorkflow();
}

async function workflowPost(route, payload) {
  if (state.workflowBusy) {
    return;
  }
  state.workflowBusy = true;
  renderWorkflow();
  ui.workflowMessage.textContent = "Recording explicit workflow transition…";
  try {
    const response = await fetch(route, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(
        body.error?.message || `Workflow HTTP ${response.status}.`,
      );
    }
    state.workflow = body.history;
    await loadPreview();
  } catch (error) {
    ui.workflowStatus.textContent = "rejected";
    ui.workflowStatus.className = "review-status invalid";
    ui.workflowMessage.textContent =
      error instanceof Error ? error.message : String(error);
  } finally {
    state.workflowBusy = false;
    renderWorkflow();
  }
}

function analysisKey(trackKey, clipId) {
  return `${trackKey}\n${clipId}`;
}

function analysisFor(track, clip) {
  return state.analysis[analysisKey(track.track_key, clip.clip_id)] || null;
}

function analysisStatusLabel(result) {
  if (!result) {
    return state.analysisState === "loading"
      ? "Analysis loading"
      : "Analysis unavailable";
  }
  if (result.status === "ready" && result.media_kind === "video") {
    return `Ready · ${result.thumbnails.length} deterministic frames`;
  }
  if (result.status === "ready" && result.media_kind === "audio") {
    return `Ready · ${result.waveform.length} aligned peak bins`;
  }
  const labels = {
    source_unavailable: "Source missing, unreadable, or not allowlisted",
    unsupported_media_type: "Unsupported media type",
    media_kind_mismatch: "Media type does not match the track",
    analysis_failed: "Media decoding failed",
  };
  return labels[result.status_code] || "Analysis unavailable";
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

function existingDraftForClip(clipId, kinds = null) {
  return state.draftEdits.find(
    (edit) =>
      edit.clip_id === clipId && (!kinds || kinds.includes(edit.kind)),
  ) || null;
}

function subtitleStyleFromUi() {
  return {
    schema_name: "vistora.subtitle-style",
    schema_version: "1.0.0",
    font_family: ui.subtitleFont.value,
    fallback_families: [ui.subtitleFont.value],
    font_size: readFiniteInput(ui.subtitleFontSize, "Subtitle font size"),
    color: ui.subtitleColor.value.trim().toUpperCase(),
    outline_color: ui.subtitleOutlineColor.value.trim().toUpperCase(),
    background_color: ui.subtitleBackgroundColor.value.trim().toUpperCase(),
    outline_width: 2,
    alignment: ui.subtitleAlignment.value,
    position: ui.subtitlePosition.value,
    safe_margin_x: 0.05,
    safe_margin_y: 0.08,
    bold: ui.subtitleBold.checked,
    italic: ui.subtitleItalic.checked,
  };
}

function populateSubtitleStyle(style = null) {
  const value = style || {
    font_family: "sans",
    font_size: 42,
    color: "#FFFFFFFF",
    outline_color: "#000000FF",
    background_color: "#00000000",
    alignment: "center",
    position: "bottom",
    bold: false,
    italic: false,
  };
  ui.subtitleFont.value = value.font_family;
  ui.subtitleFontSize.value = String(value.font_size);
  ui.subtitleColor.value = value.color;
  ui.subtitleOutlineColor.value = value.outline_color;
  ui.subtitleBackgroundColor.value = value.background_color;
  ui.subtitleAlignment.value = value.alignment;
  ui.subtitlePosition.value = value.position;
  ui.subtitleBold.checked = value.bold;
  ui.subtitleItalic.checked = value.italic;
}

function showSubtitleEditor(track = null, cue = null) {
  const enabled = state.capabilities.manual_edit_apply === true;
  ui.subtitleEditor.hidden = !enabled;
  ui.manualEditor.hidden = true;
  ui.manualEditDisabled.hidden = enabled;
  if (!enabled) return;
  state.selectedSubtitle = track ? {track, cue} : null;
  ui.subtitleTrackSelect.replaceChildren();
  for (const item of state.snapshot.subtitle_tracks || []) {
    const option = document.createElement("option");
    option.value = item.track_id;
    option.textContent = `${item.track_id} · ${item.language}`;
    option.selected = item.track_id === track?.track_id;
    ui.subtitleTrackSelect.append(option);
  }
  if (track) {
    ui.subtitleTrackKind.value = track.kind;
    ui.subtitleTrackLanguage.value = track.language;
    ui.subtitleTrackOrder.value = String(track.order_index);
    ui.subtitleTrackEnabled.checked = track.enabled;
    ui.subtitleTrackLocked.checked = track.locked;
  } else {
    ui.subtitleTrackKind.value = "subtitle";
    ui.subtitleTrackLanguage.value = "und";
    ui.subtitleTrackOrder.value = String(state.snapshot.subtitle_track_count || 0);
    ui.subtitleTrackEnabled.checked = true;
    ui.subtitleTrackLocked.checked = false;
  }
  ui.subtitleCueId.value = cue?.cue_id || newStableId("cue");
  ui.subtitleStart.value = String(cue?.start_seconds ?? state.playheadSeconds);
  ui.subtitleEnd.value = String(cue?.end_seconds ?? (state.playheadSeconds + 2));
  ui.subtitleSplitAt.value = String(
    cue ? (cue.start_seconds + cue.end_seconds) / 2 : state.playheadSeconds + 1,
  );
  ui.subtitleText.value = cue?.text || "";
  ui.subtitleCueKind.value = cue?.cue_kind || (track?.kind === "text" ? "title" : "subtitle");
  ui.subtitleWords.value = cue?.words?.length
    ? JSON.stringify(cue.words.map((word) => ({
        schema_name: "vistora.subtitle-word",
        schema_version: "1.0.0",
        word_id: word.word_id,
        start_seconds: word.start_seconds,
        end_seconds: word.end_seconds,
        text: word.text,
        confidence: word.confidence,
      })), null, 2)
    : "";
  ui.subtitleLanguage.value = cue?.language || track?.language || "und";
  ui.subtitleSpeaker.value = cue?.speaker || "";
  populateSubtitleStyle(cue?.style || track?.style);
  const locked = track?.locked === true;
  for (const control of [
    ui.subtitleDeleteTrack,
    ui.subtitleAddCue,
    ui.subtitleUpdateCue,
    ui.subtitleSplitCue,
    ui.subtitleMergeNext,
    ui.subtitleDeleteCue,
    ui.subtitleStageStyle,
    ui.subtitleImport,
  ]) control.disabled = locked || (!track && control !== ui.subtitleCreateTrack);
  ui.subtitleStageTrack.disabled = !track;
  ui.subtitleCreateTrack.disabled = false;
  ui.subtitleDownloadSrt.disabled = !track;
  ui.subtitleDownloadVtt.disabled = !track;
  ui.subtitleFormMessage.classList.remove("error");
  ui.subtitleFormMessage.textContent = locked
    ? "This subtitle track is locked. Stage an unlock first."
    : "Subtitle changes stay detached until review and explicit confirmation.";
}

function showSubtitleDetails(track, cue) {
  ui.clipDetails.replaceChildren(
    detailRow("Cue ID", cue.cue_id),
    detailRow("Cue kind", cue.cue_kind),
    detailRow("Track", `${track.track_id} · ${track.kind} · ${track.role}`),
    detailRow("Timeline", `${formatSeconds(cue.start_seconds)} → ${formatSeconds(cue.end_seconds)}`),
    detailRow("Duration", formatSeconds(cue.duration_seconds)),
    detailRow("Language", cue.language),
    detailRow("Speaker", cue.speaker || "Not specified"),
    detailRow("Text", cue.text),
    detailRow(
      "Word timing",
      cue.word_count
        ? `${cue.word_count} timed words · ${cue.words.map((word) => word.text).join(" ")}`
        : "No word-level timing",
    ),
    detailRow("State", `${cue.enabled ? "enabled" : "disabled"} · ${track.locked ? "track locked" : "editable draft"}`),
    detailRow("Style", `${cue.style?.font_family || track.style.font_family} · ${cue.style?.font_size || track.style.font_size}px · ${cue.style?.position || track.style.position}`),
    detailRow("Preview", "Browser overlay is approximate; burned export is authoritative."),
  );
}

function selectSubtitleCue(track, cue, element) {
  document.querySelectorAll(".clip.selected").forEach((item) => item.classList.remove("selected"));
  element?.classList.add("selected");
  state.selected = null;
  state.selectedSubtitle = {track, cue, element};
  state.playheadSeconds = cue.start_seconds;
  updatePlayhead();
  showSubtitleDetails(track, cue);
  showSubtitleEditor(track, cue);
  clearPreview("Subtitle cue selected. Browser text overlay is an approximate preview; final burn-in is export exact.");
  ui.previewTitle.textContent = cue.text.split("\n")[0];
}

function showManualEditor(track, clip) {
  const applyEnabled = state.capabilities.manual_edit_apply === true;
  ui.manualEditDisabled.hidden = applyEnabled;
  ui.manualEditor.hidden = !applyEnabled;
  if (!applyEnabled) {
    return;
  }
  ui.subtitleEditor.hidden = true;
  const existing = existingDraftForClip(
    clip.clip_id,
    ["update", "remove", "split"],
  );
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
    Math.max(0, track.clip_count - 1),
  );
  ui.editSplitAt.value = String(
    existing?.kind === "split"
      ? existing.split_at_seconds
      : (
          clip.timeline_start_seconds
          + clip.timeline_end_seconds
        ) / 2,
  );
  ui.editRemoveMode.value =
    existing?.kind === "remove" ? existing.mode : "lift";
  ui.editRipple.checked =
    existing?.kind === "update" ? existing.ripple === true : false;
  ui.editScope.value = existing?.edit_scope || "current_clip";
  const subtitleRipple = existing?.subtitle_ripple || {
    mode: "none",
    selected_track_ids: [],
  };
  ui.editSubtitleRipple.value = subtitleRipple.mode;
  ui.editSubtitleTracks.replaceChildren();
  for (const subtitleTrack of state.snapshot.subtitle_tracks || []) {
    const option = document.createElement("option");
    option.value = subtitleTrack.track_id;
    option.textContent =
      `${subtitleTrack.track_id} · ${subtitleTrack.language}` +
      (subtitleTrack.locked ? " · locked" : "");
    option.selected = subtitleRipple.selected_track_ids.includes(
      subtitleTrack.track_id,
    );
    option.disabled = subtitleTrack.locked;
    ui.editSubtitleTracks.append(option);
  }
  ui.editSubtitleTracks.disabled = subtitleRipple.mode !== "selected_subtitle_tracks";
  ui.editLinkTarget.replaceChildren();
  for (const candidateTrack of state.snapshot.tracks) {
    for (const candidateClip of candidateTrack.clips) {
      if (candidateClip.clip_id === clip.clip_id) {
        continue;
      }
      const option = document.createElement("option");
      option.value = JSON.stringify({
        track_key: candidateTrack.track_key,
        track_id: candidateTrack.track_id,
        clip_id: candidateClip.clip_id,
      });
      option.textContent =
        `${candidateTrack.track_id} · ${candidateClip.clip_id}`;
      ui.editLinkTarget.append(option);
    }
  }
  ui.stageLink.disabled = ui.editLinkTarget.options.length === 0;
  ui.stageUnlink.disabled = !clip.link_group_id;
  ui.editTrackOrder.value = String(track.order_index);
  ui.editTrackEnabled.checked = track.enabled;
  ui.editTrackMuted.checked = track.muted;
  ui.editTrackLocked.checked = track.locked;
  const audioDraft = existingDraftForClip(clip.clip_id, ["clip_audio"]);
  ui.audioGain.value = String(audioDraft?.gain_db ?? clip.audio_gain_db ?? 0);
  ui.audioContentRole.value =
    audioDraft?.content_role ?? clip.audio_content_role ?? "unspecified";
  ui.audioPan.value = String(audioDraft?.pan ?? clip.audio_pan ?? 0);
  ui.audioFadeIn.value = String(
    audioDraft?.fade_in_seconds ?? clip.audio_fade_in_seconds ?? 0,
  );
  ui.audioFadeOut.value = String(
    audioDraft?.fade_out_seconds ?? clip.audio_fade_out_seconds ?? 0,
  );
  ui.audioMuted.checked = audioDraft?.muted ?? clip.audio_muted ?? false;
  const trackMixDraft = state.draftEdits.find(
    (edit) => edit.kind === "track_mix" && edit.track_id === track.track_id,
  );
  ui.audioTrackGain.value = String(
    trackMixDraft?.gain_db ?? track.mix_gain_db ?? 0,
  );
  ui.audioTrackPan.value = String(
    trackMixDraft?.pan ?? track.mix_pan ?? 0,
  );
  ui.audioTrackMuted.checked =
    trackMixDraft?.muted ?? track.mix_muted ?? false;
  ui.audioPointId.value = newStableId("envelope");
  ui.audioPointTime.value = "0";
  ui.audioPointGain.value = "0";
  ui.audioDuckingKeys.replaceChildren();
  for (const candidate of state.snapshot.tracks) {
    const exposesAudio = candidate.kind === "audio" ||
      candidate.clips.some((item) => item.keep_audio);
    if (!exposesAudio || candidate.track_id === track.track_id) continue;
    const option = document.createElement("option");
    option.value = candidate.track_id;
    option.textContent = `${candidate.track_id} · ${candidate.role}`;
    option.selected = candidate.clips.some((item) =>
      ["dialogue", "voiceover"].includes(item.audio_content_role),
    );
    ui.audioDuckingKeys.append(option);
  }
  ui.audioDuckingId.value = clip.audio_ducking?.ducking_id || "duck_main";
  ui.audioDuckingReduction.value = String(clip.audio_ducking?.reduction_db ?? -12);
  ui.audioDuckingAttack.value = String(clip.audio_ducking?.attack_seconds ?? 0.15);
  ui.audioDuckingRelease.value = String(clip.audio_ducking?.release_seconds ?? 0.35);
  state.loudnessEvidence = null;
  ui.applyLoudness.disabled = true;
  ui.audioAnalysisStatus.textContent =
    clip.loudness_analysis_id
      ? `Applied evidence: ${clip.loudness_analysis_id}`
      : "No loudness analysis has been run.";
  for (const control of [
    ui.stageAudio,
    ui.stageTrackMix,
    ui.stageEnvelope,
    ui.deleteEnvelope,
    ui.clearEnvelope,
    ui.analyzeLoudness,
    ui.stageDucking,
    ui.removeDucking,
  ]) {
    control.disabled = track.locked;
  }
  ui.stageTrackMix.disabled = track.locked || track.kind !== "audio";
  const hasAudioComponent = track.kind === "audio" || clip.keep_audio;
  ui.stageAudio.disabled = track.locked || !hasAudioComponent;
  ui.stageEnvelope.disabled = track.locked || !hasAudioComponent;
  ui.deleteEnvelope.disabled = track.locked || !hasAudioComponent;
  ui.clearEnvelope.disabled = track.locked || !hasAudioComponent;
  ui.analyzeLoudness.disabled = track.locked || !hasAudioComponent;
  ui.stageDucking.disabled = track.locked || track.kind !== "audio" ||
    ui.audioDuckingKeys.options.length === 0;
  ui.removeDucking.disabled = track.locked || track.kind !== "audio" ||
    !clip.audio_ducking;
  const visualDraft = existingDraftForClip(clip.clip_id, ["clip_visual"]);
  const transform = visualDraft?.transform || clip.transform;
  const color = visualDraft?.color || clip.color;
  for (const [control, value] of [
    [ui.visualPositionX, transform.position_x],
    [ui.visualPositionY, transform.position_y],
    [ui.visualScaleX, transform.scale_x],
    [ui.visualScaleY, transform.scale_y],
    [ui.visualRotation, transform.rotation_degrees],
    [ui.visualOpacity, transform.opacity],
    [ui.visualAnchorX, transform.anchor_x],
    [ui.visualAnchorY, transform.anchor_y],
    [ui.visualCropLeft, transform.crop_left],
    [ui.visualCropRight, transform.crop_right],
    [ui.visualCropTop, transform.crop_top],
    [ui.visualCropBottom, transform.crop_bottom],
    [ui.colorExposure, color.exposure],
    [ui.colorContrast, color.contrast],
    [ui.colorSaturation, color.saturation],
    [ui.colorTemperature, color.temperature],
    [ui.colorTint, color.tint],
    [ui.colorHighlights, color.highlights],
    [ui.colorShadows, color.shadows],
    [ui.colorGamma, color.gamma],
    [ui.colorSharpen, color.sharpen],
    [ui.colorBlur, color.blur],
  ]) control.value = String(value);
  ui.visualFit.value = transform.fit;
  ui.visualFlipH.checked = transform.flip_horizontal;
  ui.visualFlipV.checked = transform.flip_vertical;
  ui.colorToneCurve.value = color.tone_curve?.points
    ?.map((point) => `${point.input},${point.output}`).join("\n") || "";
  ui.colorLutPreset.value = color.lut?.lut_id?.replace("lut_builtin_", "") || "none";
  ui.visualPreviewMode.value = state.visualPreviewMode;
  ui.visualCopyTargets.replaceChildren();
  for (const candidateTrack of state.snapshot.tracks) {
    if (candidateTrack.kind !== "video") continue;
    for (const candidateClip of candidateTrack.clips) {
      if (candidateClip.clip_id === clip.clip_id) continue;
      const option = document.createElement("option");
      option.value = JSON.stringify({
        track_key: candidateTrack.track_key,
        track_id: candidateTrack.track_id,
        clip_id: candidateClip.clip_id,
      });
      option.textContent = `${candidateTrack.track_id} / ${candidateClip.clip_id}`;
      option.disabled = candidateTrack.locked;
      ui.visualCopyTargets.append(option);
    }
  }
  const visualDisabled = track.locked || track.kind !== "video";
  for (const control of [
    ui.stageTransform, ui.stageColor, ui.resetVisual, ui.copyVisual,
  ]) control.disabled = visualDisabled;
  ui.copyVisual.disabled = visualDisabled || ui.visualCopyTargets.options.length === 0;
  ui.visualFormMessage.classList.remove("error");
  ui.visualFormMessage.textContent = track.locked
    ? "Locked tracks reject visual changes."
    : track.kind !== "video"
      ? "Visual properties apply only to video/image clips."
      : `Visual digest ${clip.visual_digest.slice(0, 23)}… · export exact.`;
  const automations = clip.visual_automations || [];
  ui.automationExisting.replaceChildren();
  const noneCurve = document.createElement("option");
  noneCurve.value = "";
  noneCurve.textContent = "New curve";
  ui.automationExisting.append(noneCurve);
  for (const automation of automations) {
    const option = document.createElement("option");
    option.value = automation.automation_id;
    option.textContent = `${automation.property_path} · ${automation.keyframes.length}`;
    ui.automationExisting.append(option);
  }
  ui.automationId.value = newStableId("automation");
  ui.keyframeId.value = newStableId("keyframe");
  ui.automationTime.value = Math.min(
    clip.effective_duration_seconds,
    Math.max(0, state.currentTime - clip.timeline_start_seconds),
  ).toFixed(3);
  ui.automationCopyTargets.replaceChildren();
  for (const candidateTrack of state.snapshot.tracks) {
    if (candidateTrack.kind !== "video") continue;
    for (const candidateClip of candidateTrack.clips) {
      if (candidateClip.clip_id === clip.clip_id) continue;
      const option = document.createElement("option");
      option.value = JSON.stringify({
        track_key: candidateTrack.track_key,
        track_id: candidateTrack.track_id,
        clip_id: candidateClip.clip_id,
      });
      option.textContent = `${candidateTrack.track_id} / ${candidateClip.clip_id}`;
      option.disabled = candidateTrack.locked;
      ui.automationCopyTargets.append(option);
    }
  }
  ui.automationPoints.replaceChildren();
  for (const automation of automations) {
    for (const point of automation.keyframes) {
      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = "automation-point-chip";
      marker.textContent = `${automation.property_path} @ ${point.offset_seconds}s`;
      marker.addEventListener("click", () => {
        ui.automationExisting.value = automation.automation_id;
        ui.automationProperty.value = automation.property_path;
        ui.automationId.value = automation.automation_id;
        ui.keyframeId.value = point.keyframe_id;
        ui.automationTime.value = String(point.offset_seconds);
        ui.automationValue.value = String(point.value);
        ui.automationInterpolation.value = point.interpolation;
      });
      ui.automationPoints.append(marker);
    }
  }
  const automationDisabled = track.locked || track.kind !== "video";
  for (const control of [
    ui.stageKeyframe, ui.deleteKeyframe, ui.clearAutomation,
    ui.clearAllAutomation, ui.copyAutomation,
  ]) control.disabled = automationDisabled;
  ui.deleteKeyframe.disabled = automationDisabled || automations.length === 0;
  ui.clearAutomation.disabled = automationDisabled || automations.length === 0;
  ui.clearAllAutomation.disabled = automationDisabled || automations.length === 0;
  ui.copyAutomation.disabled = automationDisabled || automations.length === 0 ||
    ui.automationCopyTargets.options.length === 0;
  ui.automationFormMessage.classList.toggle("error", automationDisabled);
  ui.automationFormMessage.textContent = track.locked
    ? "Locked tracks reject keyframe changes."
    : track.kind !== "video"
      ? "Visual keyframes apply only to video/image clips."
      : `${automations.length} curve(s) · ${clip.automation_digest.slice(0, 23)}…`;
  const masks = clip.masks || [];
  const selectedMask = masks[0] || null;
  ui.maskId.value = selectedMask?.mask_id || newStableId("mask");
  ui.maskKind.value = selectedMask?.kind || "rectangle";
  ui.maskOperation.value = selectedMask?.operation || "add";
  ui.maskX.value = String(selectedMask?.position_x ?? 0.5);
  ui.maskY.value = String(selectedMask?.position_y ?? 0.5);
  ui.maskWidth.value = String(selectedMask?.width ?? 0.5);
  ui.maskHeight.value = String(selectedMask?.height ?? 0.5);
  ui.maskFeather.value = String(selectedMask?.feather ?? 0);
  ui.maskExpand.value = String(selectedMask?.expand ?? 0);
  ui.maskOpacity.value = String(selectedMask?.opacity ?? 1);
  ui.maskInvert.checked = Boolean(selectedMask?.invert);
  ui.maskPoints.value = (selectedMask?.points || [])
    .map((point) => `${point.x},${point.y}`).join("\n");
  ui.maskKeyframeTime.value = Math.min(
    clip.effective_duration_seconds,
    Math.max(0, state.currentTime - clip.timeline_start_seconds),
  ).toFixed(3);
  ui.blendMode.value = clip.composite?.blend_mode || "normal";
  ui.cornerRadius.value = String(clip.composite?.corner_radius ?? 0);
  ui.shadowOpacity.value = String(clip.composite?.shadow_opacity ?? 0);
  ui.shadowBlur.value = String(clip.composite?.shadow_blur ?? 0);
  ui.shadowOffsetX.value = String(clip.composite?.shadow_offset_x ?? 0);
  ui.shadowOffsetY.value = String(clip.composite?.shadow_offset_y ?? 0);
  ui.glowStrength.value = String(clip.composite?.glow_strength ?? 0);
  ui.glowRadius.value = String(clip.composite?.glow_radius ?? 0);
  ui.maskCopyTargets.replaceChildren();
  for (const candidateTrack of state.snapshot.tracks) {
    if (candidateTrack.kind !== "video") continue;
    for (const candidateClip of candidateTrack.clips) {
      if (candidateClip.clip_id === clip.clip_id) continue;
      const option = document.createElement("option");
      option.value = JSON.stringify({
        track_key: candidateTrack.track_key,
        track_id: candidateTrack.track_id,
        clip_id: candidateClip.clip_id,
      });
      option.textContent = `${candidateTrack.track_id} / ${candidateClip.clip_id}`;
      option.disabled = candidateTrack.locked;
      ui.maskCopyTargets.append(option);
    }
  }
  for (const control of [
    ui.stageMask, ui.stageMaskKeyframe, ui.removeMask,
    ui.copyMasks, ui.stageComposite,
  ]) control.disabled = visualDisabled;
  ui.removeMask.disabled = visualDisabled || !selectedMask;
  ui.copyMasks.disabled = visualDisabled || !masks.length || !ui.maskCopyTargets.options.length;
  ui.maskFormMessage.classList.toggle("error", visualDisabled);
  ui.maskFormMessage.textContent = track.locked
    ? "Locked tracks reject mask and compositing changes."
    : track.kind !== "video"
      ? "Masks apply only to video/image clips."
      : `${masks.length} mask(s) · ${clip.mask_digest.slice(0, 23)}…`;
  const orderedClips = [...track.clips].sort(
    (left, right) =>
      left.timeline_start_seconds - right.timeline_start_seconds ||
      left.clip_id.localeCompare(right.clip_id),
  );
  const selectedIndex = orderedClips.findIndex(
    (item) => item.clip_id === clip.clip_id,
  );
  const nextClip = orderedClips[selectedIndex + 1] || null;
  const exactCut = Boolean(nextClip) &&
    Math.abs(clip.timeline_end_seconds - nextClip.timeline_start_seconds) <= 1e-6;
  const existingTransition = (state.snapshot.transitions || []).find(
    (item) =>
      item.media_type === "video" &&
      item.track_id === track.track_id &&
      item.from_clip_id === clip.clip_id &&
      item.to_clip_id === nextClip?.clip_id,
  ) || null;
  ui.transitionToClip.replaceChildren();
  if (nextClip && exactCut) {
    const option = document.createElement("option");
    option.value = nextClip.clip_id;
    option.textContent = nextClip.clip_id;
    ui.transitionToClip.append(option);
  }
  ui.transitionCopyTargets.replaceChildren();
  for (const candidateTrack of state.snapshot.tracks) {
    if (candidateTrack.kind !== "video" || candidateTrack.role !== "primary") continue;
    const candidates = [...candidateTrack.clips].sort(
      (left, right) => left.timeline_start_seconds - right.timeline_start_seconds || left.clip_id.localeCompare(right.clip_id),
    );
    for (let index = 0; index + 1 < candidates.length; index += 1) {
      const left = candidates[index];
      const right = candidates[index + 1];
      if (left.clip_id === clip.clip_id && right.clip_id === nextClip?.clip_id) continue;
      if (Math.abs(left.timeline_end_seconds - right.timeline_start_seconds) > 1e-6) continue;
      const option = document.createElement("option");
      option.value = JSON.stringify({
        track_id: candidateTrack.track_id,
        from_clip_id: left.clip_id,
        to_clip_id: right.clip_id,
      });
      option.textContent = `${candidateTrack.track_id} / ${left.clip_id} -> ${right.clip_id}`;
      option.disabled = candidateTrack.locked;
      ui.transitionCopyTargets.append(option);
    }
  }
  if (existingTransition) {
    ui.transitionKind.value = existingTransition.kind;
    ui.transitionDuration.value = String(existingTransition.duration_seconds);
    ui.transitionAlignment.value = existingTransition.alignment;
    ui.transitionDirection.value = existingTransition.direction || "left";
    ui.transitionColor.value = existingTransition.color || "#000000";
    ui.transitionAudioPolicy.value = existingTransition.audio_policy;
    const audioPair = (state.snapshot.transitions || []).find(
      (item) => item.transition_id === existingTransition.paired_transition_id,
    );
    ui.transitionAudioKind.value = audioPair?.kind || "audio_equal_power";
  } else {
    ui.transitionKind.value = "cross_dissolve";
    ui.transitionDuration.value = "0.5";
    ui.transitionAlignment.value = "centered";
    ui.transitionDirection.value = "left";
    ui.transitionColor.value = "#000000";
    ui.transitionAudioPolicy.value = "none";
    ui.transitionAudioKind.value = "audio_equal_power";
  }
  const transitionDisabled =
    track.locked || track.kind !== "video" || track.role !== "primary" || !exactCut;
  ui.stageTransition.disabled = transitionDisabled;
  ui.previewTransition.disabled = true;
  ui.removeTransition.disabled = transitionDisabled || !existingTransition;
  ui.copyTransition.disabled = transitionDisabled || !existingTransition ||
    ui.transitionCopyTargets.options.length === 0;
  ui.transitionFormMessage.classList.toggle("error", transitionDisabled);
  ui.transitionFormMessage.textContent = track.locked
    ? "Locked tracks reject transition changes."
    : track.role !== "primary" || track.kind !== "video"
      ? "First-version video transitions require a primary video track."
      : !exactCut
        ? "The selected clip has no exact adjacent cut."
        : existingTransition
          ? `${existingTransition.kind.replaceAll("_", " ")} / ${existingTransition.duration_seconds}s / ${existingTransition.alignment}`
          : "No transition exists at this exact cut.";
  ui.clipEditForm.querySelector('button[type="submit"]').disabled =
    track.locked;
  ui.stageRemove.disabled = track.locked;
  ui.stageSplit.disabled = track.locked;
  ui.stageLink.disabled =
    track.locked || ui.editLinkTarget.options.length === 0;
  ui.stageUnlink.disabled = track.locked || !clip.link_group_id;
  ui.editFormMessage.classList.remove("error");
  ui.editFormMessage.textContent =
    track.locked
      ? "This track is locked. Only a confirmed unlock proposal may edit it."
      : "Changes remain detached until you review and confirm them.";
}

function selectedSubtitleTrackIds() {
  return Array.from(ui.editSubtitleTracks.selectedOptions)
    .map((option) => option.value)
    .sort();
}

function subtitleRipplePayload() {
  const mode = ui.editSubtitleRipple.value;
  return {
    schema_version: "1.0.0",
    mode,
    selected_track_ids:
      mode === "selected_subtitle_tracks" ? selectedSubtitleTrackIds() : [],
  };
}

function visualTransformFromUi() {
  const transform = {
    schema_name: "vistora.clip-transform",
    schema_version: "1.0.0",
    position_x: readFiniteInput(ui.visualPositionX, "Position X"),
    position_y: readFiniteInput(ui.visualPositionY, "Position Y"),
    scale_x: readFiniteInput(ui.visualScaleX, "Scale X"),
    scale_y: readFiniteInput(ui.visualScaleY, "Scale Y"),
    rotation_degrees: readFiniteInput(ui.visualRotation, "Rotation"),
    opacity: readFiniteInput(ui.visualOpacity, "Opacity"),
    anchor_x: readFiniteInput(ui.visualAnchorX, "Anchor X"),
    anchor_y: readFiniteInput(ui.visualAnchorY, "Anchor Y"),
    crop_left: readFiniteInput(ui.visualCropLeft, "Crop left"),
    crop_right: readFiniteInput(ui.visualCropRight, "Crop right"),
    crop_top: readFiniteInput(ui.visualCropTop, "Crop top"),
    crop_bottom: readFiniteInput(ui.visualCropBottom, "Crop bottom"),
    fit: ui.visualFit.value,
    flip_horizontal: ui.visualFlipH.checked,
    flip_vertical: ui.visualFlipV.checked,
  };
  if (transform.crop_left + transform.crop_right >= 0.99) {
    throw new Error("Horizontal crop must retain at least 1%.");
  }
  if (transform.crop_top + transform.crop_bottom >= 0.99) {
    throw new Error("Vertical crop must retain at least 1%.");
  }
  return transform;
}

function toneCurveFromUi() {
  const text = ui.colorToneCurve.value.trim();
  if (!text) return null;
  const points = text.split(/\r?\n/).filter(Boolean).map((line, index) => {
    const values = line.split(",").map((value) => Number(value.trim()));
    if (values.length !== 2 || values.some((value) => !Number.isFinite(value))) {
      throw new Error("Each master curve line must contain finite input,output values.");
    }
    return {
      schema_name: "vistora.tone-curve-point",
      schema_version: "1.0.0",
      point_id: `tone_point_${String(index).padStart(2, "0")}`,
      input: values[0],
      output: values[1],
    };
  });
  if (points.length < 2 || points.length > 17 || points[0].input !== 0 ||
      points.at(-1).input !== 1) {
    throw new Error("Master curve needs 2-17 ordered points with exact 0 and 1 endpoints.");
  }
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    if (point.input < 0 || point.input > 1 || point.output < 0 || point.output > 1 ||
        (index > 0 && point.input <= points[index - 1].input)) {
      throw new Error("Master curve inputs must increase and all values must stay within 0-1.");
    }
  }
  return {
    schema_name: "vistora.tone-curve",
    schema_version: "1.0.0",
    curve_id: "tone_curve_manual",
    points,
  };
}

function lutPresetFromUi() {
  const preset = ui.colorLutPreset.value;
  if (preset === "none") return null;
  const base = Array.from({length: 17}, (_, index) => index / 16);
  const clamp = (value) => Math.max(0, Math.min(1, value));
  const channels = {
    warm: [base.map((value) => clamp(value * 1.05 + 0.015)), base, base.map((value) => value * 0.92)],
    cool: [base.map((value) => value * 0.92), base, base.map((value) => clamp(value * 1.05 + 0.015))],
    film: [base.map((value) => clamp(0.04 + value * 0.92)), base.map((value) => clamp(0.03 + value * 0.94)), base.map((value) => clamp(0.05 + value * 0.9))],
  }[preset];
  if (!channels) throw new Error("Unknown bounded LUT preset.");
  return {
    schema_name: "vistora.color-lut-1d",
    schema_version: "1.0.0",
    lut_id: `lut_builtin_${preset}`,
    title: `${preset[0].toUpperCase()}${preset.slice(1)} built-in 1D LUT`,
    red: channels[0], green: channels[1], blue: channels[2], strength: 1,
  };
}

function visualColorFromUi() {
  const color = {
    schema_name: "vistora.clip-color-adjustment",
    schema_version: "2.0.0",
    exposure: readFiniteInput(ui.colorExposure, "Exposure"),
    contrast: readFiniteInput(ui.colorContrast, "Contrast"),
    saturation: readFiniteInput(ui.colorSaturation, "Saturation"),
    temperature: readFiniteInput(ui.colorTemperature, "Temperature"),
    tint: readFiniteInput(ui.colorTint, "Tint"),
    highlights: readFiniteInput(ui.colorHighlights, "Highlights"),
    shadows: readFiniteInput(ui.colorShadows, "Shadows"),
    gamma: readFiniteInput(ui.colorGamma, "Gamma"),
    sharpen: readFiniteInput(ui.colorSharpen, "Sharpen"),
    blur: readFiniteInput(ui.colorBlur, "Blur"),
    tone_curve: toneCurveFromUi(),
    lut: lutPresetFromUi(),
  };
  if (color.sharpen > 0 && color.blur > 0) {
    throw new Error("Sharpen and blur cannot be active together.");
  }
  return color;
}

function approximateVisualPreview(clip, transform = clip?.transform, color = clip?.color) {
  if (!clip || !transform || !color || state.visualPreviewMode === "original") {
    ui.previewVideo.style.transform = "";
    ui.previewVideo.style.transformOrigin = "";
    ui.previewVideo.style.opacity = "";
    ui.previewVideo.style.clipPath = "";
    ui.previewVideo.style.objectFit = "contain";
    ui.previewVideo.style.filter = "";
    ui.previewVideo.style.borderRadius = "";
    return;
  }
  const flipX = transform.flip_horizontal ? -1 : 1;
  const flipY = transform.flip_vertical ? -1 : 1;
  ui.previewVideo.style.transformOrigin =
    `${transform.anchor_x * 100}% ${transform.anchor_y * 100}%`;
  ui.previewVideo.style.transform =
    `translate(${(transform.position_x - 0.5) * 100}%, ` +
    `${(transform.position_y - 0.5) * 100}%) ` +
    `scale(${transform.scale_x * flipX}, ${transform.scale_y * flipY}) ` +
    `rotate(${transform.rotation_degrees}deg)`;
  ui.previewVideo.style.opacity = String(transform.opacity);
  ui.previewVideo.style.objectFit =
    transform.fit === "stretch" ? "fill" : transform.fit === "fill" ? "cover" : "contain";
  ui.previewVideo.style.clipPath =
    `inset(${transform.crop_top * 100}% ${transform.crop_right * 100}% ` +
    `${transform.crop_bottom * 100}% ${transform.crop_left * 100}%)`;
  const previewMask = (clip.masks || []).find(
    (item) => item.enabled && item.operation === "add" && !item.invert,
  );
  if (previewMask?.kind === "ellipse") {
    ui.previewVideo.style.clipPath =
      `ellipse(${(previewMask.width || 0.5) * 50}% ` +
      `${(previewMask.height || 0.5) * 50}% at ` +
      `${previewMask.position_x * 100}% ${previewMask.position_y * 100}%)`;
  } else if (previewMask?.kind === "rectangle") {
    const left = (previewMask.position_x - (previewMask.width || 0.5) / 2) * 100;
    const top = (previewMask.position_y - (previewMask.height || 0.5) / 2) * 100;
    const right = 100 - (previewMask.position_x + (previewMask.width || 0.5) / 2) * 100;
    const bottom = 100 - (previewMask.position_y + (previewMask.height || 0.5) / 2) * 100;
    ui.previewVideo.style.clipPath = `inset(${top}% ${right}% ${bottom}% ${left}%)`;
  } else if (previewMask?.kind === "polygon") {
    ui.previewVideo.style.clipPath = `polygon(${previewMask.points.map(
      (point) => `${point.x * 100}% ${point.y * 100}%`,
    ).join(",")})`;
  }
  const composite = clip.composite || {};
  ui.previewVideo.style.borderRadius = `${(composite.corner_radius || 0) * 50}%`;
  const effects = [
    `brightness(${Math.pow(2, color.exposure)})`,
    `contrast(${1 + color.contrast})`,
    `saturate(${1 + color.saturation})`,
    `blur(${color.blur}px)`,
  ];
  if ((composite.shadow_opacity || 0) > 0) {
    effects.push(
      `drop-shadow(${(composite.shadow_offset_x || 0) * 100}px ` +
      `${(composite.shadow_offset_y || 0) * 100}px ` +
      `${composite.shadow_blur || 0}px rgb(0 0 0 / ${composite.shadow_opacity}))`,
    );
  }
  if ((composite.glow_strength || 0) > 0) {
    effects.push(
      `drop-shadow(0 0 ${composite.glow_radius || 0}px ` +
      `rgb(255 255 255 / ${composite.glow_strength}))`,
    );
  }
  ui.previewVideo.style.filter = effects.join(" ");
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
  if (change.target_kind === "automation") {
    const beforeCurves = change.before?.visual_automations || [];
    const afterCurves = change.after?.visual_automations || [];
    const beforeById = new Map(beforeCurves.map((curve) => [curve.automation_id, curve]));
    const afterById = new Map(afterCurves.map((curve) => [curve.automation_id, curve]));
    const curveIds = [...new Set([...beforeById.keys(), ...afterById.keys()])].sort();
    const lines = [];
    for (const curveId of curveIds) {
      const before = beforeById.get(curveId);
      const after = afterById.get(curveId);
      if (JSON.stringify(before) === JSON.stringify(after)) continue;
      if (!before) {
        lines.push(`Create ${after.property_path} · ${after.keyframes.length} keyframe(s)`);
      } else if (!after) {
        lines.push(`Remove ${before.property_path} · ${before.keyframes.length} keyframe(s)`);
      } else {
        lines.push(
          `${after.property_path}: ${before.keyframes.length} → ` +
          `${after.keyframes.length} keyframe(s) · values/interpolation updated`,
        );
      }
    }
    return lines.length ? lines : ["Visual automation metadata updated"];
  }
  if (change.target_kind === "mask") {
    const beforeMasks = change.before?.masks || [];
    const afterMasks = change.after?.masks || [];
    return [
      `Masks: ${beforeMasks.length} → ${afterMasks.length}`,
      "Mask definitions/keyframes digest changed",
    ];
  }
  if (change.target_kind === "composite") {
    return [
      `Blend: ${change.before?.composite?.blend_mode || "normal"} → ` +
      `${change.after?.composite?.blend_mode || "normal"}`,
    ];
  }
  if (change.action === "create") {
    if (change.target_kind === "transition") {
      return [
        `Create ${change.after.kind.replaceAll("_", " ")}`,
        `${formatSeconds(change.after.duration_seconds)} / ${change.after.alignment}`,
        `${change.after.from_clip_id} -> ${change.after.to_clip_id}`,
      ];
    }
    if (change.target_kind === "subtitle_track") {
      return [`Create ${change.after.kind} track`, change.after.language || "und"];
    }
    if (change.target_kind === "subtitle_cue") {
      return [
        `${formatSeconds(change.after.start_seconds)} → ${formatSeconds(change.after.end_seconds)}`,
        change.after.text,
      ];
    }
    return [
      `Create at ${formatSeconds(change.after.timeline_start_seconds)}`,
      `${formatSeconds(change.after.trim_in_seconds)} → ` +
        formatSeconds(change.after.trim_out_seconds),
      change.after.source_name,
    ];
  }
  if (change.action === "remove") {
    if (change.target_kind === "transition") {
      return [
        `Remove ${change.before.kind.replaceAll("_", " ")}`,
        `${change.before.from_clip_id} -> ${change.before.to_clip_id}`,
      ];
    }
    if (change.target_kind === "subtitle_track") {
      return [`Delete subtitle track`, `${change.before.cues?.length || 0} cues`];
    }
    if (change.target_kind === "subtitle_cue") {
      return [
        `${formatSeconds(change.before.start_seconds)} → ${formatSeconds(change.before.end_seconds)}`,
        change.before.text,
      ];
    }
    return [
      `Remove from order ${change.before.order_index}`,
      `${formatSeconds(change.before.timeline_start_seconds)} → ` +
        formatSeconds(change.before.timeline_end_seconds),
      change.before.source_name,
    ];
  }
  const labels = {
    kind: "Transition type",
    duration_seconds: "Transition duration",
    alignment: "Transition alignment",
    parameters: "Transition parameters",
    audio_policy: "Audio policy",
    trim_in_seconds: "Source in",
    trim_out_seconds: "Source out",
    timeline_start_seconds: "Timeline start",
    order_index: "Order",
    audio_gain_db: "Clip gain",
    audio_muted: "Clip mute",
    audio_pan: "Clip pan",
    audio_fade_in_seconds: "Fade in",
    audio_fade_out_seconds: "Fade out",
    audio_envelope: "Gain envelope",
    mix_gain_db: "Track gain",
    mix_muted: "Track mix mute",
    mix_pan: "Track pan",
    text: "Text",
    start_seconds: "Start",
    end_seconds: "End",
    language: "Language",
    speaker: "Speaker",
    style: "Style",
    locked: "Locked",
    enabled: "Enabled",
  };
  const lines = [];
  for (const [field, label] of Object.entries(labels)) {
    if (JSON.stringify(change.before[field]) !== JSON.stringify(change.after[field])) {
      const timeField = [
        "trim_in_seconds",
        "trim_out_seconds",
        "timeline_start_seconds",
        "audio_fade_in_seconds",
        "audio_fade_out_seconds",
        "start_seconds",
        "end_seconds",
      ].includes(field);
      const display = (value) =>
        Array.isArray(value)
          ? `${value.length} point${value.length === 1 ? "" : "s"}`
          : timeField
            ? formatSeconds(value)
            : String(value);
      const before = display(change.before[field]);
      const after = display(change.after[field]);
      lines.push(`${label}: ${before} → ${after}`);
    }
  }
  if (
    change.before.mix && change.after.mix &&
    JSON.stringify(change.before.mix) !== JSON.stringify(change.after.mix)
  ) {
    const before = change.before.mix;
    const after = change.after.mix;
    lines.push(
      `Track mix: ${before.gain_db} dB / pan ${before.pan} / ` +
      `${before.muted ? "muted" : "active"} → ` +
      `${after.gain_db} dB / pan ${after.pan} / ` +
      `${after.muted ? "muted" : "active"}`,
    );
  }
  for (const [field, label] of [["transform", "Picture transform"], ["color", "Color adjustment"]]) {
    if (
      change.before[field] && change.after[field] &&
      JSON.stringify(change.before[field]) !== JSON.stringify(change.after[field])
    ) {
      const changed = Object.keys(change.after[field]).filter(
        (key) => change.before[field][key] !== change.after[field][key] &&
          !["schema_name", "schema_version"].includes(key),
      );
      lines.push(`${label}: ${changed.join(", ") || "reset"}`);
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
  const identity = (value) => {
    if (value.kind === "link") {
      return `link:${value.members
        .map((member) => `${member.track_id}/${member.clip_id}`)
        .sort()
        .join("|")}`;
    }
    if (value.kind === "manage_track") {
      return `track:${value.track_id}`;
    }
    if (value.kind === "track_mix") {
      return `track_mix:${value.track_id}`;
    }
    if (value.kind === "volume_envelope") {
      return `envelope:${value.track_id}/${value.clip_id}/${value.point_id || value.action}`;
    }
    if (value.kind === "audio_ducking") {
      return `ducking:${value.action}/${value.ducking_id}/${value.target_track_ids.join(",")}`;
    }
    if (value.kind === "subtitle_track") {
      return `subtitle_track:${value.track_id}`;
    }
    if (value.kind === "subtitle_cue") {
      const target = value.cue_id || value.merged_cue_id || value.operation_id;
      return `subtitle_cue:${value.track_id}/${value.action}/${target}`;
    }
    if (value.kind === "clip_visual") {
      return `visual:${value.track_id}/${value.clip_id}`;
    }
    if (value.kind === "copy_clip_visual") {
      return `visual_copy:${value.source_track_id}/${value.source_clip_id}`;
    }
    if (value.kind === "transition") {
      return `transition:${value.transition?.transition_id || value.transition_id || value.source_transition_id}`;
    }
    if (value.kind === "visual_automation") {
      return `automation:${value.track_id}/${value.clip_id}/${value.automation_id || value.property_path || value.action}/${value.keyframe?.keyframe_id || value.keyframe_id || value.action}`;
    }
    const domain = value.kind === "clip_audio" ? "audio" : "timing";
    return `clip:${domain}:${value.track_id || value.track_key}/${value.clip_id}`;
  };
  state.draftHistory.push(cloneEdits(state.draftEdits));
  state.draftEdits = state.draftEdits.filter(
    (current) => identity(current) !== identity(edit),
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
    [
      "Contents",
      `${snapshot.track_count} media + ${snapshot.subtitle_track_count || 0} text tracks / ` +
        `${snapshot.clip_count} clips + ${snapshot.subtitle_cue_count || 0} cues + ` +
        `${snapshot.transition_count || 0} transitions`,
    ],
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

function provenanceDetailRows(provenanceValue) {
  const provenance = provenanceValue || {
    origin_kind: "legacy_unknown",
    latest_change_origin: "legacy_unknown",
    mapping_status: "legacy_unknown",
    evidence: [],
  };
  const originLabel = provenance.origin_kind.replaceAll("_", " ");
  const mappingLabel = provenance.mapping_status.replaceAll("_", " ");
  const planLabel = provenance.plan_id
    ? `${provenance.plan_id} v${provenance.plan_version}`
    : "No recorded Director plan";
  const stepLabel = provenance.step_id
    ? `${provenance.source_operation_id} / ${provenance.step_id}`
    : "No recorded execution step";
  const evidenceLabel = provenance.evidence?.length
    ? provenance.evidence.map((item) => {
        const range = item.locator_type === "media_time_range"
          ? ` ${formatSeconds(item.start_seconds)}–${formatSeconds(item.end_seconds)}`
          : " whole material";
        return `${item.evidence_id} / ${item.material_id}${range}`;
      }).join("; ")
    : "No recorded source evidence";
  return [
    detailRow("Origin", `${originLabel} · ${mappingLabel}`),
    detailRow(
      "Latest change",
      provenance.latest_change_origin.replaceAll("_", " "),
    ),
    detailRow("Director plan", planLabel),
    detailRow("Operation / step", stepLabel),
    detailRow("Source evidence", evidenceLabel),
    detailRow(
      "Execution",
      provenance.execution_status
        ? `${provenance.execution_status} · ${provenance.request_id} / ` +
          provenance.result_id
        : "No recorded confirmed execution",
    ),
  ];
}

function showDetails(track, clip) {
  const availability = state.media[clip.source.source_id];
  const analysis = analysisFor(track, clip);
  ui.clipDetails.replaceChildren(
    detailRow("Clip ID", clip.clip_id),
    detailRow(
      "Track",
      `${track.track_id} · ${track.kind} · ${track.role}`,
    ),
    detailRow("Link group", clip.link_group_id || "Not linked"),
    detailRow(
      "Media type",
      `${clip.visual_kind || track.kind} · ${availability?.content_type || "unavailable"}`,
    ),
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
      clip.freeze_frame_source_time_seconds != null
        ? `freeze @ ${formatSeconds(clip.freeze_frame_source_time_seconds)} · ` +
          `${formatSeconds(clip.freeze_frame_duration_seconds)} hold · silent`
        : `${clip.speed_factor}× · ${clip.reverse ? "reverse" : "forward"} · ` +
          `${clip.rotate_degrees}°`,
    ),
    detailRow(
      "Clip audio",
      ["image", "sticker"].includes(clip.visual_kind)
        ? "Silent static graphic"
        : `${clip.audio_content_role || "unspecified"} · ` +
          `${clip.audio_gain_db ?? 0} dB · pan ${clip.audio_pan ?? 0} · ` +
          `${clip.audio_muted || !clip.keep_audio ? "muted" : "active"}`,
    ),
    detailRow(
      "Fades / envelope",
      `${formatSeconds(clip.audio_fade_in_seconds ?? 0)} in · ` +
        `${formatSeconds(clip.audio_fade_out_seconds ?? 0)} out · ` +
        `${clip.audio_envelope?.length || 0} linear points`,
    ),
    detailRow(
      "Track mix",
      `${track.mix_gain_db ?? 0} dB · pan ${track.mix_pan ?? 0} · ` +
        `${track.mix_muted ? "muted" : "active"}`,
    ),
    detailRow(
      "Loudness evidence",
      clip.loudness_analysis_id || "Not applied",
    ),
    detailRow(
      "Automatic ducking",
      clip.audio_ducking
        ? `${clip.audio_ducking.ducking_id} · ${clip.audio_ducking.reduction_db} dB · key ${clip.audio_ducking.key_track_ids.join(", ")}`
        : "Not applied",
    ),
    detailRow(
      "Picture transform",
      `pos ${clip.transform.position_x},${clip.transform.position_y} · ` +
      `scale ${clip.transform.scale_x}×${clip.transform.scale_y} · ` +
      `${clip.transform.rotation_degrees}° · opacity ${clip.transform.opacity} · ` +
      clip.transform.fit,
    ),
    detailRow(
      "Color adjustment",
      `exp ${clip.color.exposure} · con ${clip.color.contrast} · ` +
      `sat ${clip.color.saturation} · temp ${clip.color.temperature} · ` +
      `tint ${clip.color.tint} · gamma ${clip.color.gamma}`,
    ),
    detailRow("Visual digest", clip.visual_digest),
    detailRow(
      "Visual automation",
      `${clip.visual_automations?.length || 0} curves · ${clip.automation_digest}`,
    ),
    detailRow(
      "Masks / composite",
      `${clip.masks?.length || 0} masks · ${clip.composite?.blend_mode || "normal"} · ` +
        `${clip.mask_digest}`,
    ),
    detailRow(
      "Media access",
      availability?.available
        ? `Allowlisted · ${availability.content_type}`
        : "Unavailable or outside allowlisted roots",
    ),
    detailRow(
      "Visualization",
      ["image", "sticker"].includes(clip.visual_kind)
        ? "Allowlisted static graphic preview"
        : analysisStatusLabel(analysis),
    ),
    ...provenanceDetailRows(clip.provenance),
  );
}

function showOrphanedProvenance() {
  const issues = state.snapshot?.orphaned_provenance || [];
  if (issues.length === 0) {
    return;
  }
  const issue = issues[0];
  ui.clipDetails.replaceChildren(
    detailRow(
      "Status",
      "Recorded clip is missing from the current timeline.",
    ),
    detailRow("Missing clip", `${issue.track_key} / ${issue.clip_id}`),
    detailRow(
      "Mapping",
      `${issue.provenance.mapping_status} · trace revision ` +
        issue.trace_revision,
    ),
    ...provenanceDetailRows(issue.provenance),
    ...(issues.length > 1
      ? [detailRow("Other missing mappings", String(issues.length - 1))]
      : []),
  );
}

function clearPreview(message) {
  ui.previewVideo.pause();
  ui.previewVideo.removeAttribute("src");
  ui.previewVideo.load();
  ui.previewImage.removeAttribute("src");
  ui.previewImage.hidden = true;
  ui.monitor.classList.remove("has-media", "has-image");
  ui.previewTitle.textContent = "Preview unavailable";
  ui.previewStatus.textContent = message;
  approximateVisualPreview(null);
  ui.previewTransition.disabled = true;
}

function selectClip(track, clip, element) {
  document
    .querySelectorAll(".clip.selected")
    .forEach((item) => item.classList.remove("selected"));
  element.classList.add("selected");
  state.selected = { track, clip, element };
  state.selectedSubtitle = null;
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

  if (["image", "sticker"].includes(clip.visual_kind)) {
    ui.previewVideo.pause();
    ui.previewVideo.removeAttribute("src");
    ui.previewVideo.load();
    ui.previewImage.src = availability.url;
    ui.previewImage.hidden = false;
    ui.monitor.classList.remove("has-media");
    ui.monitor.classList.add("has-image");
    approximateVisualPreview(clip);
    ui.previewTransition.disabled = true;
    ui.previewStatus.textContent =
      `${clip.visual_kind === "sticker" ? "Sticker" : "Image"} preview uses the allowlisted source; ` +
      "the timeline duration is deterministic and final export is authoritative.";
    return;
  }

  const desiredSource = new URL(availability.url, window.location.href).href;
  if (ui.previewVideo.src !== desiredSource) {
    ui.previewVideo.src = availability.url;
    ui.previewVideo.load();
  }
  ui.monitor.classList.add("has-media");
  ui.monitor.classList.remove("has-image");
  ui.previewImage.hidden = true;
  approximateVisualPreview(clip);
  ui.previewTransition.disabled = ui.stageTransition.disabled;
  ui.previewStatus.textContent =
    "Previewing allowlisted media. Playback updates the local playhead only.";

  const seekToTrim = () => {
    const safeTime = Math.max(
      0,
      clip.freeze_frame_source_time_seconds ?? clip.trim_in_seconds,
    );
    if (Number.isFinite(ui.previewVideo.duration)) {
      ui.previewVideo.currentTime = Math.min(
        safeTime,
        ui.previewVideo.duration,
      );
    } else {
      ui.previewVideo.currentTime = safeTime;
    }
    if (clip.freeze_frame_source_time_seconds != null) {
      ui.previewVideo.pause();
      ui.previewVideo.playbackRate = 1;
      ui.previewStatus.textContent =
        "Freeze-frame preview is pinned to the reviewed source frame; final export uses the exact hold duration.";
    } else if (clip.speed_factor >= 0.25 && clip.speed_factor <= 4) {
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

function analysisPlaceholder(result) {
  const placeholder = document.createElement("div");
  placeholder.className = "analysis-placeholder";
  placeholder.textContent = analysisStatusLabel(result);
  return placeholder;
}

function videoThumbnailStrip(result) {
  if (!result || result.status !== "ready") {
    return analysisPlaceholder(result);
  }
  const strip = document.createElement("div");
  strip.className = "thumbnail-strip";
  for (const thumbnail of result.thumbnails) {
    const image = document.createElement("img");
    image.alt = "";
    image.draggable = false;
    image.loading = "lazy";
    image.src =
      `/analysis/thumbnail/${result.analysis_id}/` +
      thumbnail.artifact_id;
    strip.append(image);
  }
  return strip;
}

function audioWaveform(result, clip) {
  if (!result || result.status !== "ready") {
    return analysisPlaceholder(result);
  }
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.classList.add("waveform");
  svg.setAttribute("viewBox", "0 0 100 40");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(namespace, "path");
  const count = Math.max(1, result.waveform.length);
  const commands = result.waveform.map((peak, index) => {
    const x = ((index + 0.5) / count) * 100;
    const top = 20 - Math.max(-1, Math.min(1, peak.maximum)) * 17;
    const bottom = 20 - Math.max(-1, Math.min(1, peak.minimum)) * 17;
    return `M${x.toFixed(3)} ${top.toFixed(3)}V${bottom.toFixed(3)}`;
  });
  path.setAttribute("d", commands.join(""));
  svg.append(path);
  if (clip.audio_envelope?.length) {
    const envelope = document.createElementNS(namespace, "polyline");
    envelope.classList.add("gain-envelope");
    const duration = Math.max(0.001, clip.effective_duration_seconds);
    const values = clip.audio_envelope.map((point) => {
      const x = Math.max(0, Math.min(100, (point[1] / duration) * 100));
      const y = 36 - ((Math.max(-60, Math.min(24, point[2])) + 60) / 84) * 32;
      return `${x.toFixed(3)},${y.toFixed(3)}`;
    });
    envelope.setAttribute("points", values.join(" "));
    svg.append(envelope);
  }
  return svg;
}

function clipVisualization(track, clip) {
  if (track.kind === "video" && ["image", "sticker"].includes(clip.visual_kind)) {
    const availability = state.media[clip.source.source_id];
    if (!availability?.available) return analysisPlaceholder(null);
    const image = document.createElement("img");
    image.className = "static-graphic-thumbnail";
    image.alt = "";
    image.draggable = false;
    image.loading = "lazy";
    image.src = availability.url;
    return image;
  }
  const result = analysisFor(track, clip);
  if (track.kind === "video") {
    return videoThumbnailStrip(result);
  }
  if (track.kind === "audio") {
    return audioWaveform(result, clip);
  }
  return analysisPlaceholder(null);
}

function renderTimeline() {
  const snapshot = state.snapshot;
  const hasProposedClips = planChanges().some(
    (change) => change.category === "clip_addition",
  );
  const isEmpty = snapshot.empty && !hasProposedClips;
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
      textElement("strong", "", track.track_id),
      textElement(
        "span",
        "",
        `${track.clip_count} clip${track.clip_count === 1 ? "" : "s"} · ` +
          formatSeconds(track.duration_seconds),
      ),
    );
    const flags = [
      track.kind,
      track.role,
      !track.enabled ? "disabled" : "",
      track.muted ? "muted" : "",
      track.locked ? "locked" : "",
    ].filter(Boolean);
    label.append(copy, textElement("span", "track-kind", flags.join(" · ")));
    ui.trackLabels.append(label);

    const lane = document.createElement("div");
    lane.className = `track-lane ${track.kind}`;
    lane.style.width = `${width}px`;
    lane.style.setProperty("--grid-size", `${state.pixelsPerSecond}px`);
    lane.dataset.trackKey = track.track_key;
    lane.dataset.trackId = track.track_id;
    if (!track.enabled) {
      lane.classList.add("disabled");
    }
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
      block.dataset.trackKey = track.track_key;
      block.dataset.trackId = track.track_id;
      if (clip.link_group_id) {
        block.dataset.linkGroupId = clip.link_group_id;
        block.classList.add("linked");
      }
      block.title =
        `${clip.clip_id}\n${clipLabel(clip)}\n${clip.source.value}`;
      block.setAttribute(
        "aria-label",
        `${clip.clip_id}, ${track.kind} clip, ${clipLabel(clip)}`,
      );
      const copy = document.createElement("span");
      copy.className = "clip-copy";
      copy.append(
        textElement("strong", "", clip.source.display_name),
        textElement("span", "", clipLabel(clip)),
      );
      block.append(clipVisualization(track, clip), copy);
      for (const automation of clip.visual_automations || []) {
        for (const point of automation.keyframes) {
          const marker = document.createElement("span");
          marker.className = "visual-keyframe-marker";
          marker.style.left = `${Math.max(0, Math.min(100, point.offset_seconds / Math.max(clip.effective_duration_seconds, 0.001) * 100))}%`;
          marker.title = `${automation.property_path} · ${point.offset_seconds}s · ${point.interpolation}`;
          block.append(marker);
        }
      }
      if (
        state.selected?.track.track_key === track.track_key &&
        state.selected?.clip.clip_id === clip.clip_id
      ) {
        block.classList.add("selected");
        state.selected = { track, clip, element: block };
      }
      const proposedChanges = changesForClip(track.track_key, clip.clip_id);
      if (proposedChanges.length > 0) {
        block.classList.add("plan-affected");
        if (
          proposedChanges.some(
            (change) => change.category === "clip_removal",
          )
        ) {
          block.classList.add("plan-removed");
        }
        block.append(
          textElement(
            "span",
            "plan-change-count",
            String(proposedChanges.length),
          ),
        );
      }
      if (
        state.selectedPlanChange?.entity.entity_id === clip.clip_id &&
        state.selectedPlanChange?.entity.track_key === track.track_key
      ) {
        block.classList.add("plan-change-selected");
      }
      block.addEventListener("click", (event) => {
        event.stopPropagation();
        selectClip(track, clip, block);
      });
      lane.append(block);
    });
    for (const transition of (snapshot.transitions || []).filter(
      (item) => item.track_id === track.track_id && item.media_type === track.kind,
    )) {
      const incoming = track.clips.find(
        (item) => item.clip_id === transition.to_clip_id,
      );
      if (!incoming) continue;
      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = `transition-marker ${transition.media_type}`;
      marker.style.left =
        `${incoming.timeline_start_seconds * state.pixelsPerSecond}px`;
      marker.dataset.transitionId = transition.transition_id;
      marker.title =
        `${transition.kind.replaceAll("_", " ")} / ` +
        `${formatSeconds(transition.duration_seconds)} / ${transition.alignment}`;
      marker.setAttribute(
        "aria-label",
        `${transition.kind} transition from ${transition.from_clip_id} to ${transition.to_clip_id}`,
      );
      marker.textContent = transition.kind === "cut" ? "|" : "X";
      marker.addEventListener("click", (event) => {
        event.stopPropagation();
        const outgoing = track.clips.find(
          (item) => item.clip_id === transition.from_clip_id,
        );
        const outgoingElement = lane.querySelector(
          `[data-clip-id="${CSS.escape(transition.from_clip_id)}"]`,
        );
        if (outgoing && outgoingElement) {
          selectClip(track, outgoing, outgoingElement);
          ui.transitionFormMessage.textContent = marker.title;
        }
      });
      lane.append(marker);
    }
    for (const change of planChanges().filter(
      (item) =>
        item.category === "clip_addition" &&
        item.after?.track_key === track.track_key,
    )) {
      const clip = change.after;
      const ghost = document.createElement("button");
      ghost.type = "button";
      ghost.className = "clip proposed-clip";
      ghost.dataset.clipId = clip.clip_id;
      ghost.dataset.trackKey = track.track_key;
      ghost.style.left =
        `${clip.timeline_start_seconds * state.pixelsPerSecond}px`;
      ghost.style.width =
        `${Math.max(28, clip.effective_duration_seconds * state.pixelsPerSecond)}px`;
      ghost.setAttribute(
        "aria-label",
        `Proposed addition ${clip.source_name}, ${safeChangeState(clip)}`,
      );
      ghost.append(
        textElement("strong", "", `+ ${clip.source_name}`),
        textElement("span", "", "Proposed · not applied"),
      );
      if (state.selectedPlanChange?.change_id === change.change_id) {
        ghost.classList.add("plan-change-selected");
      }
      ghost.addEventListener("click", (event) => {
        event.stopPropagation();
        selectPlanChange(change);
      });
      lane.append(ghost);
    }
    ui.trackLanes.append(lane);
  });

  (snapshot.subtitle_tracks || []).forEach((track) => {
    const label = document.createElement("button");
    label.type = "button";
    label.className = "track-label-row subtitle-track-label";
    const copy = document.createElement("div");
    copy.className = "track-label-copy";
    copy.append(
      textElement("strong", "", track.track_id),
      textElement(
        "span",
        "",
        `${track.cue_count} cue${track.cue_count === 1 ? "" : "s"} · ` +
          formatSeconds(track.duration_seconds),
      ),
    );
    const flags = [
      track.kind,
      track.language,
      !track.enabled ? "disabled" : "",
      track.locked ? "locked" : "",
    ].filter(Boolean);
    label.append(copy, textElement("span", "track-kind", flags.join(" · ")));
    label.addEventListener("click", () => showSubtitleEditor(track, null));
    ui.trackLabels.append(label);

    const lane = document.createElement("div");
    lane.className = `track-lane ${track.kind}`;
    lane.style.width = `${width}px`;
    lane.style.setProperty("--grid-size", `${state.pixelsPerSecond}px`);
    lane.dataset.trackKey = track.track_key;
    lane.dataset.trackId = track.track_id;
    if (!track.enabled) lane.classList.add("disabled");
    for (const cue of track.cues) {
      const block = document.createElement("button");
      block.type = "button";
      block.className = "clip subtitle";
      block.classList.toggle("title", cue.cue_kind === "title");
      block.style.left = `${cue.start_seconds * state.pixelsPerSecond}px`;
      block.style.width = `${Math.max(28, cue.duration_seconds * state.pixelsPerSecond)}px`;
      block.dataset.clipId = cue.cue_id;
      block.dataset.trackKey = track.track_key;
      block.dataset.trackId = track.track_id;
      block.title = `${cue.cue_id}\n${formatSeconds(cue.start_seconds)} → ${formatSeconds(cue.end_seconds)}\n${cue.text}`;
      block.setAttribute("aria-label", `${cue.cue_id}, ${cue.cue_kind} cue, ${cue.text}`);
      block.append(
        textElement("strong", "", `${cue.cue_kind === "title" ? "TITLE · " : ""}${cue.text}`),
        textElement("span", "", `${formatSeconds(cue.start_seconds)} → ${formatSeconds(cue.end_seconds)}${cue.word_count ? ` · ${cue.word_count} words` : ""}`),
      );
      if (
        state.selectedSubtitle?.track.track_id === track.track_id &&
        state.selectedSubtitle?.cue?.cue_id === cue.cue_id
      ) {
        block.classList.add("selected");
        state.selectedSubtitle = {track, cue, element: block};
      }
      block.addEventListener("click", (event) => {
        event.stopPropagation();
        selectSubtitleCue(track, cue, block);
      });
      lane.append(block);
    }
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

async function loadAnalysis() {
  const expectedSnapshotId = state.snapshot?.snapshot_id;
  if (!expectedSnapshotId) {
    return;
  }
  state.analysis = {};
  state.analysisState = "loading";
  renderTimeline();
  try {
    const response = await fetch(
      `/api/analysis?mode=${encodeURIComponent(state.visualPreviewMode)}`,
      {
      headers: { Accept: "application/json" },
      cache: "no-store",
      },
    );
    const payload = await response.json();
    if (
      !response.ok ||
      payload.schema_name !== "vistora.media-analysis-collection" ||
      payload.schema_version !== "1.0.0" ||
      payload.snapshot_id !== expectedSnapshotId ||
      !Array.isArray(payload.results)
    ) {
      throw new Error("The media analysis response was invalid.");
    }
    if (state.snapshot?.snapshot_id !== expectedSnapshotId) {
      return;
    }
    const next = {};
    for (const result of payload.results) {
      if (
        result.snapshot_id !== expectedSnapshotId ||
        !["video", "audio"].includes(result.media_kind)
      ) {
        throw new Error("A media analysis result was invalid.");
      }
      next[analysisKey(result.track_key, result.clip_id)] = result;
    }
    state.analysis = next;
    state.analysisState = "ready";
  } catch (error) {
    state.analysis = {};
    state.analysisState = "error";
    console.warn(
      error instanceof Error ? error.message : String(error),
    );
  }
  renderTimeline();
  if (state.selected) {
    showDetails(state.selected.track, state.selected.clip);
  }
}

function rgbaCss(value) {
  if (!/^#[0-9A-Fa-f]{8}$/.test(value || "")) return "transparent";
  const red = Number.parseInt(value.slice(1, 3), 16);
  const green = Number.parseInt(value.slice(3, 5), 16);
  const blue = Number.parseInt(value.slice(5, 7), 16);
  const alpha = Number.parseInt(value.slice(7, 9), 16) / 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha.toFixed(3)})`;
}

function updateSubtitleOverlay() {
  const active = [];
  for (const track of state.snapshot?.subtitle_tracks || []) {
    if (!track.enabled) continue;
    for (const cue of track.cues) {
      if (
        cue.enabled &&
        state.playheadSeconds >= cue.start_seconds &&
        state.playheadSeconds < cue.end_seconds
      ) active.push({track, cue});
    }
  }
  if (active.length === 0) {
    ui.subtitleOverlay.hidden = true;
    ui.subtitleOverlay.textContent = "";
    return;
  }
  active.sort((left, right) =>
    left.track.order_index - right.track.order_index ||
    left.cue.order_index - right.cue.order_index,
  );
  const {track, cue} = active.at(-1);
  const style = cue.style || track.style;
  ui.subtitleOverlay.textContent = active.map((item) => item.cue.text).join("\n");
  ui.subtitleOverlay.style.fontFamily =
    style.font_family === "serif"
      ? "Georgia, serif"
      : style.font_family === "monospace"
        ? "Consolas, monospace"
        : "Arial, sans-serif";
  ui.subtitleOverlay.style.fontSize = `${Math.max(12, Math.min(54, style.font_size / 1.5))}px`;
  ui.subtitleOverlay.style.color = rgbaCss(style.color);
  ui.subtitleOverlay.style.background = rgbaCss(style.background_color);
  ui.subtitleOverlay.style.fontWeight = style.bold ? "800" : "700";
  ui.subtitleOverlay.style.fontStyle = style.italic ? "italic" : "normal";
  ui.subtitleOverlay.style.textAlign = style.alignment;
  ui.subtitleOverlay.style.top = style.position === "top" ? "8%" : style.position === "middle" ? "45%" : "auto";
  ui.subtitleOverlay.style.bottom = style.position === "bottom" ? "8%" : "auto";
  ui.subtitleOverlay.hidden = false;
}

function updatePlayhead() {
  ui.timecode.textContent = timecode(state.playheadSeconds);
  const x = Math.max(0, state.playheadSeconds * state.pixelsPerSecond);
  ui.playhead.style.transform = `translateX(${x}px)`;
  updateSubtitleOverlay();
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
    state.analysis = {};
    state.analysisState = "idle";
    ui.modeBadgeLabel.textContent = state.capabilities.manual_edit_apply === true
      ? "Review + confirm"
      : "Read only";
    ui.timelineHelp.textContent = state.capabilities.manual_edit_apply === true
      ? "Click a clip to inspect it. Drafts stay local and do not write until Confirm & apply."
      : "Click a clip to inspect it. Preview interactions only move the local playhead; project data is unchanged.";
    state.selected = null;
    state.selectedSubtitle = null;
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
    showOrphanedProvenance();
    ui.manualEditor.hidden = true;
    ui.subtitleEditor.hidden = true;
    ui.manualEditDisabled.hidden = true;
    resetDraft({ keepSuccess: preserveSuccess });
    renderSummary();
    renderTimeline();
    if (state.capabilities.manual_edit_apply === true) {
      showSubtitleEditor(state.snapshot.subtitle_tracks?.[0] || null, null);
    }
    ui.previewStatus.textContent = state.snapshot.empty
      ? "This snapshot is empty. No media preview is available."
      : "Select a video clip to preview allowlisted local media.";
    if (!state.snapshot.empty && state.capabilities.media_analysis === true) {
      await loadAnalysis();
    }
    await loadPlanReview();
    await loadDirector();
    await loadProduct();
    await loadWorkflow();
  } catch (error) {
    showFatal(error instanceof Error ? error.message : String(error));
  }
}

ui.productDialogue?.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = ui.productUserMessage.value.trim();
  if (!message) {
    ui.productMessage.textContent = "Describe the request before sending.";
    return;
  }
  productPost("director_turn", null, message).then(() => {
    ui.productUserMessage.value = "";
  });
});

function readFiniteInput(input, label) {
  input.removeAttribute("aria-invalid");
  const value = Number(input.value);
  if (!Number.isFinite(value)) {
    input.setAttribute("aria-invalid", "true");
    throw new Error(`${label} must be a finite number.`);
  }
  return value;
}

function currentSubtitleTrack() {
  const trackId = ui.subtitleTrackSelect.value;
  return (state.snapshot?.subtitle_tracks || []).find(
    (track) => track.track_id === trackId,
  ) || null;
}

function subtitleMessage(message, error = false) {
  ui.subtitleFormMessage.classList.toggle("error", error);
  ui.subtitleFormMessage.textContent = message;
}

function subtitleCuePayload() {
  const start = readFiniteInput(ui.subtitleStart, "Subtitle start");
  const end = readFiniteInput(ui.subtitleEnd, "Subtitle end");
  const text = ui.subtitleText.value.trim();
  if (end <= start) throw new Error("Subtitle end must be after start.");
  if (!text) throw new Error("Subtitle text cannot be empty.");
  let words = [];
  const rawWords = ui.subtitleWords.value.trim();
  if (rawWords) {
    try {
      words = JSON.parse(rawWords);
    } catch {
      throw new Error("Word timings must be valid JSON.");
    }
    if (!Array.isArray(words)) throw new Error("Word timings must be a JSON array.");
    let previousEnd = start;
    const identifiers = new Set();
    words = words.map((word, index) => {
      if (!word || typeof word !== "object" || Array.isArray(word)) {
        throw new Error(`Word timing ${index + 1} must be an object.`);
      }
      const wordStart = Number(word.start_seconds);
      const wordEnd = Number(word.end_seconds);
      const wordText = String(word.text || "").trim();
      const wordId = String(word.word_id || "").trim();
      if (!/^[A-Za-z][A-Za-z0-9._:-]*$/.test(wordId) || identifiers.has(wordId)) {
        throw new Error(`Word timing ${index + 1} needs a unique stable word_id.`);
      }
      if (!Number.isFinite(wordStart) || !Number.isFinite(wordEnd) ||
          wordStart < start || wordEnd > end || wordEnd <= wordStart || wordStart < previousEnd) {
        throw new Error(`Word timing ${index + 1} is outside the cue or overlaps.`);
      }
      if (!wordText) throw new Error(`Word timing ${index + 1} text cannot be empty.`);
      identifiers.add(wordId);
      previousEnd = wordEnd;
      return {
        schema_name: "vistora.subtitle-word",
        schema_version: "1.0.0",
        word_id: wordId,
        start_seconds: wordStart,
        end_seconds: wordEnd,
        text: wordText,
        confidence: word.confidence == null ? null : Number(word.confidence),
      };
    });
  }
  return {
    schema_name: "vistora.subtitle-cue",
    schema_version: "1.0.0",
    cue_id: ui.subtitleCueId.value.trim(),
    cue_kind: ui.subtitleCueKind.value,
    start_seconds: start,
    end_seconds: end,
    text,
    language: ui.subtitleLanguage.value.trim() || "und",
    speaker: ui.subtitleSpeaker.value.trim() || null,
    enabled: true,
    settings: [],
    style: null,
    words,
  };
}

ui.editSubtitleRipple.addEventListener("change", () => {
  ui.editSubtitleTracks.disabled =
    ui.editSubtitleRipple.value !== "selected_subtitle_tracks";
});

ui.subtitleTrackSelect.addEventListener("change", () => {
  const track = currentSubtitleTrack();
  showSubtitleEditor(track, null);
});

ui.subtitleCreateTrack.addEventListener("click", () => {
  const trackKind = ui.subtitleTrackKind.value;
  const trackId = newStableId(trackKind);
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_subtitle_track"),
    kind: "subtitle_track",
    action: "create",
    track_id: trackId,
    track_kind: trackKind,
    role: trackKind === "text" ? "titles" : "captions",
    language: ui.subtitleTrackLanguage.value.trim() || "und",
    order: Number(ui.subtitleTrackOrder.value || 0),
    enabled: true,
    locked: false,
    allow_overlaps: false,
    style: subtitleStyleFromUi(),
  });
  subtitleMessage(`${trackKind === "text" ? "Title" : "Subtitle"} track ${trackId} staged. Apply it before adding cues.`);
});

ui.subtitleStageTrack.addEventListener("click", () => {
  const track = currentSubtitleTrack();
  if (!track) return subtitleMessage("Select a subtitle track first.", true);
  const edit = {
    schema_version: "1.0.0",
    operation_id: newStableId("manual_subtitle_track"),
    kind: "subtitle_track",
    action: "update",
    track_id: track.track_id,
    locked: ui.subtitleTrackLocked.checked,
  };
  if (!track.locked) {
    edit.language = ui.subtitleTrackLanguage.value.trim() || "und";
    edit.order = Number(ui.subtitleTrackOrder.value);
    edit.enabled = ui.subtitleTrackEnabled.checked;
    edit.style = subtitleStyleFromUi();
  }
  stageEdit(edit);
  subtitleMessage("Subtitle track settings staged for review.");
});

ui.subtitleDeleteTrack.addEventListener("click", () => {
  const track = currentSubtitleTrack();
  if (!track) return subtitleMessage("Select a subtitle track first.", true);
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_subtitle_track"),
    kind: "subtitle_track",
    action: "delete",
    track_id: track.track_id,
  });
  subtitleMessage("Subtitle track deletion staged. Cues remain until confirmation.");
});

ui.subtitleAddCue.addEventListener("click", () => {
  try {
    const track = currentSubtitleTrack();
    if (!track || track.locked) throw new Error("Select an unlocked subtitle track.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_subtitle_cue"),
      kind: "subtitle_cue",
      action: "add",
      track_id: track.track_id,
      cues: [subtitleCuePayload()],
    });
    subtitleMessage("New cue staged; no project write has occurred.");
  } catch (error) { subtitleMessage(error.message || String(error), true); }
});

ui.subtitleUpdateCue.addEventListener("click", () => {
  try {
    const track = currentSubtitleTrack();
    const cue = state.selectedSubtitle?.cue;
    if (!track || !cue || track.locked) throw new Error("Select an editable subtitle cue.");
    const value = subtitleCuePayload();
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_subtitle_cue"),
      kind: "subtitle_cue",
      action: "update",
      track_id: track.track_id,
      cue_id: cue.cue_id,
      text: value.text,
      language: value.language,
      speaker: value.speaker,
      start_seconds: value.start_seconds,
      end_seconds: value.end_seconds,
      cue_kind: value.cue_kind,
      words: value.words,
    });
    subtitleMessage("Cue text and timing staged for review.");
  } catch (error) { subtitleMessage(error.message || String(error), true); }
});

ui.subtitleSplitCue.addEventListener("click", () => {
  try {
    const track = currentSubtitleTrack();
    const cue = state.selectedSubtitle?.cue;
    if (!track || !cue || track.locked) throw new Error("Select an editable subtitle cue.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_subtitle_cue"),
      kind: "subtitle_cue",
      action: "split",
      track_id: track.track_id,
      cue_id: cue.cue_id,
      split_at_seconds: readFiniteInput(ui.subtitleSplitAt, "Subtitle split point"),
      right_cue_id: newStableId("cue"),
    });
    subtitleMessage("Cue split staged for review.");
  } catch (error) { subtitleMessage(error.message || String(error), true); }
});

ui.subtitleMergeNext.addEventListener("click", () => {
  const track = currentSubtitleTrack();
  const cue = state.selectedSubtitle?.cue;
  const index = track?.cues.findIndex((item) => item.cue_id === cue?.cue_id) ?? -1;
  const next = index >= 0 ? track.cues[index + 1] : null;
  if (!track || !cue || !next || track.locked) {
    return subtitleMessage("Select an unlocked cue with an adjacent next cue.", true);
  }
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_subtitle_cue"),
    kind: "subtitle_cue",
    action: "merge",
    track_id: track.track_id,
    merge_cue_ids: [cue.cue_id, next.cue_id],
    merged_cue_id: cue.cue_id,
  });
  subtitleMessage("Adjacent cue merge staged for review.");
});

ui.subtitleDeleteCue.addEventListener("click", () => {
  const track = currentSubtitleTrack();
  const cue = state.selectedSubtitle?.cue;
  if (!track || !cue || track.locked) return subtitleMessage("Select an editable cue.", true);
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_subtitle_cue"),
    kind: "subtitle_cue",
    action: "delete",
    track_id: track.track_id,
    cue_id: cue.cue_id,
  });
  subtitleMessage("Cue deletion staged for review.");
});

ui.subtitleStageStyle.addEventListener("click", () => {
  try {
    const track = currentSubtitleTrack();
    const cue = state.selectedSubtitle?.cue;
    if (!track || !cue || track.locked) throw new Error("Select an editable cue.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_subtitle_cue"),
      kind: "subtitle_cue",
      action: "set_style",
      track_id: track.track_id,
      cue_id: cue.cue_id,
      style: subtitleStyleFromUi(),
    });
    subtitleMessage("Controlled cue style staged for review.");
  } catch (error) { subtitleMessage(error.message || String(error), true); }
});

ui.subtitleImport.addEventListener("click", async () => {
  const track = currentSubtitleTrack();
  const file = ui.subtitleImportFile.files?.[0];
  if (!track || track.locked || !file) {
    return subtitleMessage("Choose a file and an unlocked subtitle track.", true);
  }
  try {
    const content = await file.text();
    const extension = file.name.toLowerCase().endsWith(".vtt") ? "vtt" : "srt";
    const response = await fetch("/api/subtitles/parse", {
      method: "POST",
      headers: {Accept: "application/json", "Content-Type": "application/json"},
      body: JSON.stringify({content, format: extension, language: track.language}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error?.message || "Subtitle parsing failed.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_subtitle_import"),
      kind: "subtitle_cue",
      action: "batch_add",
      track_id: track.track_id,
      cues: payload.cues,
    });
    subtitleMessage(`${payload.cue_count} parsed cues staged; the source file was not modified.`);
  } catch (error) { subtitleMessage(error.message || String(error), true); }
});

function downloadSubtitles(format) {
  const track = currentSubtitleTrack();
  if (!track) return subtitleMessage("Select a subtitle track first.", true);
  const query = new URLSearchParams({format, track_id: track.track_id});
  const anchor = document.createElement("a");
  anchor.href = `/api/subtitles/export?${query}`;
  anchor.download = `vistora-${track.track_id}.${format}`;
  anchor.click();
  subtitleMessage(`Prepared a detached ${format.toUpperCase()} download.`);
}

ui.subtitleDownloadSrt.addEventListener("click", () => downloadSubtitles("srt"));
ui.subtitleDownloadVtt.addEventListener("click", () => downloadSubtitles("vtt"));

function stageVisualEdit(components) {
  if (!state.selected || state.selected.track.locked || state.selected.track.kind !== "video") {
    throw new Error("Select an unlocked video clip.");
  }
  const existing = existingDraftForClip(state.selected.clip.clip_id, ["clip_visual"]);
  const edit = {
    schema_version: "1.0.0",
    operation_id: existing?.operation_id || newStableId("manual_visual"),
    kind: "clip_visual",
    action: "set",
    track_key: state.selected.track.track_key,
    track_id: state.selected.track.track_id,
    clip_id: state.selected.clip.clip_id,
    // The draft represents the complete visual state.  Keeping both halves in
    // one proposal prevents a later color click from discarding a staged
    // transform (or vice versa) before confirmation.
    components: "both",
    transform: visualTransformFromUi(),
    color: visualColorFromUi(),
  };
  stageEdit(edit);
  ui.visualFormMessage.classList.remove("error");
  ui.visualFormMessage.textContent = `${components} staged locally for review.`;
}

ui.stageTransform.addEventListener("click", () => {
  try { stageVisualEdit("transform"); }
  catch (error) {
    ui.visualFormMessage.classList.add("error");
    ui.visualFormMessage.textContent = error.message || String(error);
  }
});

ui.stageColor.addEventListener("click", () => {
  try { stageVisualEdit("color"); }
  catch (error) {
    ui.visualFormMessage.classList.add("error");
    ui.visualFormMessage.textContent = error.message || String(error);
  }
});

ui.resetVisual.addEventListener("click", () => {
  if (!state.selected || state.selected.track.locked || state.selected.track.kind !== "video") return;
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_visual_reset"),
    kind: "clip_visual",
    action: "reset",
    track_key: state.selected.track.track_key,
    track_id: state.selected.track.track_id,
    clip_id: state.selected.clip.clip_id,
    components: "both",
  });
  ui.visualFormMessage.textContent = "Neutral transform and color reset staged.";
});

ui.copyVisual.addEventListener("click", () => {
  try {
    if (!state.selected || state.selected.track.locked) throw new Error("Select an unlocked source clip.");
    const targets = Array.from(ui.visualCopyTargets.selectedOptions)
      .map((option) => JSON.parse(option.value))
      .sort((left, right) =>
        `${left.track_id}/${left.clip_id}`.localeCompare(`${right.track_id}/${right.clip_id}`),
      );
    if (!targets.length) throw new Error("Select at least one explicit target clip.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_visual_copy"),
      kind: "copy_clip_visual",
      source_track_id: state.selected.track.track_id,
      source_clip_id: state.selected.clip.clip_id,
      targets,
      components: ui.visualCopyComponents.value,
    });
    ui.visualFormMessage.textContent = `Visual copy staged for ${targets.length} explicit target(s).`;
  } catch (error) {
    ui.visualFormMessage.classList.add("error");
    ui.visualFormMessage.textContent = error.message || String(error);
  }
});

function selectedAutomationCurve() {
  if (!state.selected) return null;
  const identity = ui.automationExisting.value;
  return (state.selected.clip.visual_automations || []).find(
    (item) => item.automation_id === identity,
  ) || null;
}

function automationMessage(message, error = false) {
  ui.automationFormMessage.classList.toggle("error", error);
  ui.automationFormMessage.textContent = message;
}

ui.automationExisting.addEventListener("change", () => {
  const curve = selectedAutomationCurve();
  if (!curve) {
    ui.automationId.value = newStableId("automation");
    ui.keyframeId.value = newStableId("keyframe");
    return;
  }
  ui.automationId.value = curve.automation_id;
  ui.automationProperty.value = curve.property_path;
  const point = curve.keyframes[0];
  ui.keyframeId.value = point.keyframe_id;
  ui.automationTime.value = String(point.offset_seconds);
  ui.automationValue.value = String(point.value);
  ui.automationInterpolation.value = point.interpolation;
});

function navigateKeyframe(direction) {
  const curve = selectedAutomationCurve();
  if (!curve) return automationMessage("Select an existing curve first.", true);
  const current = readFiniteInput(ui.automationTime, "Keyframe time");
  const ordered = [...curve.keyframes].sort(
    (left, right) => left.offset_seconds - right.offset_seconds,
  );
  const candidates = direction < 0
    ? ordered.filter((point) => point.offset_seconds < current - 1e-6).reverse()
    : ordered.filter((point) => point.offset_seconds > current + 1e-6);
  const point = candidates[0] || (direction < 0 ? ordered[0] : ordered.at(-1));
  ui.keyframeId.value = point.keyframe_id;
  ui.automationTime.value = String(point.offset_seconds);
  ui.automationValue.value = String(point.value);
  ui.automationInterpolation.value = point.interpolation;
}

ui.previousKeyframe.addEventListener("click", () => navigateKeyframe(-1));
ui.nextKeyframe.addEventListener("click", () => navigateKeyframe(1));

ui.stageKeyframe.addEventListener("click", () => {
  try {
    if (!state.selected || state.selected.track.locked || state.selected.track.kind !== "video") {
      throw new Error("Select an unlocked video clip.");
    }
    const clip = state.selected.clip;
    const offset = readFiniteInput(ui.automationTime, "Keyframe time");
    if (offset < 0 || offset > clip.effective_duration_seconds + 1e-6) {
      throw new Error("Keyframe time must be inside the selected clip.");
    }
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_keyframe"),
      kind: "visual_automation",
      action: "upsert_keyframe",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: clip.clip_id,
      automation_id: ui.automationId.value.trim(),
      property_path: ui.automationProperty.value,
      keyframe: {
        schema_name: "vistora.visual-keyframe",
        schema_version: "1.0.0",
        keyframe_id: ui.keyframeId.value.trim(),
        offset_seconds: offset,
        value: readFiniteInput(ui.automationValue, "Keyframe value"),
        interpolation: ui.automationInterpolation.value,
      },
    });
    automationMessage("Keyframe staged locally; review is required.");
  } catch (error) { automationMessage(error.message || String(error), true); }
});

ui.deleteKeyframe.addEventListener("click", () => {
  try {
    if (!state.selected || !selectedAutomationCurve()) throw new Error("Select an existing curve.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_keyframe_delete"),
      kind: "visual_automation",
      action: "delete_keyframe",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: state.selected.clip.clip_id,
      automation_id: ui.automationId.value.trim(),
      keyframe_id: ui.keyframeId.value.trim(),
    });
    automationMessage("Keyframe deletion staged locally.");
  } catch (error) { automationMessage(error.message || String(error), true); }
});

ui.clearAutomation.addEventListener("click", () => {
  try {
    if (!state.selected || !selectedAutomationCurve()) throw new Error("Select an existing curve.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_curve_clear"),
      kind: "visual_automation",
      action: "clear_curve",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: state.selected.clip.clip_id,
      automation_id: ui.automationId.value.trim(),
    });
    automationMessage("Curve clear staged locally.");
  } catch (error) { automationMessage(error.message || String(error), true); }
});

ui.clearAllAutomation.addEventListener("click", () => {
  if (!state.selected) return;
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_automation_clear_all"),
    kind: "visual_automation",
    action: "clear_all",
    track_key: state.selected.track.track_key,
    track_id: state.selected.track.track_id,
    clip_id: state.selected.clip.clip_id,
  });
  automationMessage("All visual curves staged for removal.");
});

ui.copyAutomation.addEventListener("click", () => {
  try {
    if (!state.selected) throw new Error("Select a source clip.");
    const targets = Array.from(ui.automationCopyTargets.selectedOptions)
      .map((option) => JSON.parse(option.value))
      .sort((left, right) => `${left.track_id}/${left.clip_id}`.localeCompare(`${right.track_id}/${right.clip_id}`));
    if (!targets.length) throw new Error("Select explicit target clips.");
    const curve = selectedAutomationCurve();
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_automation_copy"),
      kind: "visual_automation",
      action: "copy",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: state.selected.clip.clip_id,
      targets,
      property_paths: curve ? [curve.property_path] : [],
    });
    automationMessage(`Automation copy staged for ${targets.length} explicit target(s).`);
  } catch (error) { automationMessage(error.message || String(error), true); }
});

function maskMessage(message, error = false) {
  ui.maskFormMessage.classList.toggle("error", error);
  ui.maskFormMessage.textContent = message;
}

function maskFromUi(automations = []) {
  const kind = ui.maskKind.value;
  const maskId = ui.maskId.value.trim();
  if (!/^[A-Za-z][A-Za-z0-9._:-]{2,159}$/.test(maskId)) {
    throw new Error("Mask ID must be a stable safe identifier.");
  }
  const points = kind === "polygon"
    ? ui.maskPoints.value.split(/\r?\n/).filter((line) => line.trim()).map((line, index) => {
      const values = line.split(",").map((item) => Number(item.trim()));
      if (values.length !== 2 || values.some((value) => !Number.isFinite(value))) {
        throw new Error("Polygon points must use one finite x,y pair per line.");
      }
      return {schema_name: "vistora.mask-point", schema_version: "1.0.0", point_id: `maskpoint_${maskId}_${index}`, x: values[0], y: values[1]};
    })
    : [];
  return {
    schema_name: "vistora.clip-mask",
    schema_version: "1.0.0",
    mask_id: maskId,
    kind,
    operation: ui.maskOperation.value,
    enabled: true,
    invert: ui.maskInvert.checked,
    opacity: readFiniteInput(ui.maskOpacity, "Mask opacity"),
    feather: readFiniteInput(ui.maskFeather, "Mask feather"),
    expand: readFiniteInput(ui.maskExpand, "Mask expand"),
    position_x: readFiniteInput(ui.maskX, "Mask position X"),
    position_y: readFiniteInput(ui.maskY, "Mask position Y"),
    scale_x: 1,
    scale_y: 1,
    rotation_degrees: 0,
    width: kind === "polygon" ? null : readFiniteInput(ui.maskWidth, "Mask width"),
    height: kind === "polygon" ? null : readFiniteInput(ui.maskHeight, "Mask height"),
    points,
    automations,
  };
}

function stageMaskEdit(edit) {
  if (!state.selected || state.selected.track.locked || state.selected.track.kind !== "video") {
    throw new Error("Select an unlocked video clip.");
  }
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_mask"),
    kind: "clip_mask",
    track_key: state.selected.track.track_key,
    track_id: state.selected.track.track_id,
    clip_id: state.selected.clip.clip_id,
    ...edit,
  });
}

ui.stageMask.addEventListener("click", () => {
  try {
    stageMaskEdit({action: "upsert", mask: maskFromUi()});
    maskMessage("Mask staged locally; review and confirmation are required.");
  } catch (error) { maskMessage(error.message || String(error), true); }
});

ui.stageMaskKeyframe.addEventListener("click", () => {
  try {
    if (!state.selected) throw new Error("Select a clip first.");
    const time = readFiniteInput(ui.maskKeyframeTime, "Mask keyframe time");
    if (time < 0 || time > state.selected.clip.effective_duration_seconds + 1e-6) {
      throw new Error("Mask keyframe time must be inside the selected clip.");
    }
    const property = ui.maskAutomationProperty.value;
    const existingMask = (state.selected.clip.masks || []).find((item) => item.mask_id === ui.maskId.value.trim());
    const automations = [...(existingMask?.automations || [])];
    const curveIndex = automations.findIndex((item) => item.property_path === property);
    const curve = curveIndex >= 0 ? {...automations[curveIndex]} : {
      schema_name: "vistora.mask-automation", schema_version: "1.0.0",
      automation_id: newStableId("maskauto"), mask_id: ui.maskId.value.trim(),
      property_path: property, enabled: true, keyframes: [],
    };
    const points = [...curve.keyframes];
    const occupied = points.findIndex((point) => Math.abs(point.offset_seconds - time) <= 1e-6);
    const point = {
      schema_name: "vistora.visual-keyframe", schema_version: "1.0.0",
      keyframe_id: occupied >= 0 ? points[occupied].keyframe_id : newStableId("maskkey"),
      offset_seconds: time,
      value: readFiniteInput(ui.maskKeyframeValue, "Mask keyframe value"),
      interpolation: ui.maskKeyframeInterpolation.value,
    };
    if (occupied >= 0) points[occupied] = point; else points.push(point);
    curve.keyframes = points.sort((left, right) => left.offset_seconds - right.offset_seconds || left.keyframe_id.localeCompare(right.keyframe_id));
    if (curveIndex >= 0) automations[curveIndex] = curve; else automations.push(curve);
    automations.sort((left, right) => left.property_path.localeCompare(right.property_path) || left.automation_id.localeCompare(right.automation_id));
    stageMaskEdit({action: "upsert", mask: maskFromUi(automations)});
    maskMessage("Mask keyframe staged locally; review is required.");
  } catch (error) { maskMessage(error.message || String(error), true); }
});

ui.removeMask.addEventListener("click", () => {
  try {
    stageMaskEdit({action: "remove", mask_id: ui.maskId.value.trim()});
    maskMessage("Mask removal staged locally.");
  } catch (error) { maskMessage(error.message || String(error), true); }
});

ui.copyMasks.addEventListener("click", () => {
  try {
    const targets = Array.from(ui.maskCopyTargets.selectedOptions)
      .map((option) => JSON.parse(option.value))
      .sort((left, right) => `${left.track_id}/${left.clip_id}`.localeCompare(`${right.track_id}/${right.clip_id}`));
    if (!targets.length) throw new Error("Select explicit target clips.");
    stageMaskEdit({action: "copy", targets, mask_ids: [], replace_existing: false});
    maskMessage(`Mask copy staged for ${targets.length} explicit target(s).`);
  } catch (error) { maskMessage(error.message || String(error), true); }
});

ui.stageComposite.addEventListener("click", () => {
  try {
    const composite = {
      schema_name: "vistora.clip-composite-settings",
      schema_version: "2.0.0",
      blend_mode: ui.blendMode.value,
      corner_radius: readFiniteInput(ui.cornerRadius, "Rounded corners"),
      shadow_opacity: readFiniteInput(ui.shadowOpacity, "Shadow opacity"),
      shadow_blur: readFiniteInput(ui.shadowBlur, "Shadow blur"),
      shadow_offset_x: readFiniteInput(ui.shadowOffsetX, "Shadow offset X"),
      shadow_offset_y: readFiniteInput(ui.shadowOffsetY, "Shadow offset Y"),
      glow_strength: readFiniteInput(ui.glowStrength, "Glow strength"),
      glow_radius: readFiniteInput(ui.glowRadius, "Glow radius"),
    };
    const isDefault = composite.blend_mode === "normal" &&
      composite.corner_radius === 0 && composite.shadow_opacity === 0 &&
      composite.shadow_blur === 0 && composite.shadow_offset_x === 0 &&
      composite.shadow_offset_y === 0 && composite.glow_strength === 0 &&
      composite.glow_radius === 0;
    stageMaskEdit({
      action: isDefault ? "reset_composite" : "set_composite",
      composite: isDefault ? null : composite,
    });
    maskMessage("Bounded packaging staged; review is required before application.");
  } catch (error) { maskMessage(error.message || String(error), true); }
});

ui.visualPreviewMode.addEventListener("change", () => {
  state.visualPreviewMode = ui.visualPreviewMode.value;
  if (state.selected) approximateVisualPreview(state.selected.clip);
  loadAnalysis();
});

for (const control of [
  ui.visualPositionX, ui.visualPositionY, ui.visualScaleX, ui.visualScaleY,
  ui.visualRotation, ui.visualOpacity, ui.visualAnchorX, ui.visualAnchorY,
  ui.visualCropLeft, ui.visualCropRight, ui.visualCropTop, ui.visualCropBottom,
  ui.visualFit, ui.visualFlipH, ui.visualFlipV, ui.colorExposure,
  ui.colorContrast, ui.colorSaturation, ui.colorTemperature, ui.colorTint,
  ui.colorHighlights, ui.colorShadows, ui.colorGamma, ui.colorSharpen,
  ui.colorBlur, ui.colorToneCurve, ui.colorLutPreset,
]) {
  control.addEventListener("input", () => {
    if (!state.selected) return;
    try {
      approximateVisualPreview(
        state.selected.clip,
        visualTransformFromUi(),
        visualColorFromUi(),
      );
      ui.visualFormMessage.classList.remove("error");
      ui.visualFormMessage.textContent = "Approximate local preview only; not staged or written.";
    } catch (error) {
      ui.visualFormMessage.classList.add("error");
      ui.visualFormMessage.textContent = error.message || String(error);
    }
  });
}

ui.clipEditForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!state.selected || state.selected.track.locked) {
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
      orderIndex >= state.selected.track.clip_count
    ) {
      throw new Error(
        `Clip order must be an integer from 0 to ` +
          `${Math.max(0, state.selected.track.clip_count - 1)}.`,
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
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: state.selected.clip.clip_id,
      trim_in_seconds: trimIn,
      trim_out_seconds: trimOut,
      timeline_start_seconds: timelineStart,
      order_index: orderIndex,
      ripple: ui.editRipple.checked,
      subtitle_ripple: subtitleRipplePayload(),
      edit_scope: ui.editScope.value,
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
  if (!state.selected || state.selected.track.locked) {
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
    track_key: state.selected.track.track_key,
    track_id: state.selected.track.track_id,
    clip_id: state.selected.clip.clip_id,
    mode: ui.editRemoveMode.value,
    edit_scope: ui.editScope.value,
    subtitle_ripple: subtitleRipplePayload(),
  });
  ui.manualEditor.hidden = true;
});

ui.stageSplit.addEventListener("click", () => {
  if (!state.selected || state.selected.track.locked) {
    return;
  }
  try {
    const splitAt = readFiniteInput(ui.editSplitAt, "Split time");
    const clip = state.selected.clip;
    if (
      splitAt <= clip.timeline_start_seconds ||
      splitAt >= clip.timeline_end_seconds
    ) {
      throw new Error("Split time must be inside the selected clip.");
    }
    const existing = existingDraftForClip(clip.clip_id);
    stageEdit({
      schema_version: "1.0.0",
      operation_id:
        existing?.kind === "split"
          ? existing.operation_id
          : newStableId("manual_split"),
      kind: "split",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: clip.clip_id,
      split_at_seconds: splitAt,
      right_clip_id:
        existing?.kind === "split"
          ? existing.right_clip_id
          : newStableId("clip"),
      edit_scope: ui.editScope.value,
    });
    ui.editFormMessage.classList.remove("error");
    ui.editFormMessage.textContent =
      "Split staged locally. Review both resulting clip changes below.";
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent =
      error instanceof Error ? error.message : String(error);
  }
});

ui.stageLink.addEventListener("click", () => {
  if (!state.selected || !ui.editLinkTarget.value) {
    return;
  }
  const target = JSON.parse(ui.editLinkTarget.value);
  const selected = state.selected;
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_link"),
    kind: "link",
    action: "link",
    members: [
      {
        track_key: selected.track.track_key,
        track_id: selected.track.track_id,
        clip_id: selected.clip.clip_id,
      },
      target,
    ],
    link_group_id: newStableId("link"),
  });
  ui.editFormMessage.classList.remove("error");
  ui.editFormMessage.textContent =
    "Explicit clip link staged locally for review.";
});

ui.stageUnlink.addEventListener("click", () => {
  if (!state.selected || !state.selected.clip.link_group_id) {
    return;
  }
  const members = [];
  for (const track of state.snapshot.tracks) {
    for (const clip of track.clips) {
      if (clip.link_group_id === state.selected.clip.link_group_id) {
        members.push({
          track_key: track.track_key,
          track_id: track.track_id,
          clip_id: clip.clip_id,
        });
      }
    }
  }
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_unlink"),
    kind: "link",
    action: "unlink",
    members,
  });
  ui.editFormMessage.classList.remove("error");
  ui.editFormMessage.textContent =
    "Explicit linked group unlink staged locally for review.";
});

ui.stageTrack.addEventListener("click", () => {
  if (!state.selected) {
    return;
  }
  try {
    const order = readFiniteInput(ui.editTrackOrder, "Track order");
    if (
      !Number.isInteger(order) ||
      order < 0 ||
      order >= state.snapshot.track_count
    ) {
      throw new Error(
        `Track order must be an integer from 0 to ` +
          `${Math.max(0, state.snapshot.track_count - 1)}.`,
      );
    }
    const track = state.selected.track;
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_track"),
      kind: "manage_track",
      track_key: track.track_key,
      track_id: track.track_id,
      action: "update",
      order,
      enabled: ui.editTrackEnabled.checked,
      muted: ui.editTrackMuted.checked,
      locked: ui.editTrackLocked.checked,
    });
    ui.editFormMessage.classList.remove("error");
    ui.editFormMessage.textContent =
      "Track settings staged locally. No write occurs before confirmation.";
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent =
      error instanceof Error ? error.message : String(error);
  }
});

ui.stageAudio.addEventListener("click", () => {
  if (!state.selected || state.selected.track.locked) return;
  try {
    const clip = state.selected.clip;
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_audio"),
      kind: "clip_audio",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: clip.clip_id,
      gain_db: readFiniteInput(ui.audioGain, "Clip gain"),
      content_role: ui.audioContentRole.value,
      muted: ui.audioMuted.checked,
      pan: readFiniteInput(ui.audioPan, "Clip pan"),
      fade_in_seconds: readFiniteInput(ui.audioFadeIn, "Fade in"),
      fade_out_seconds: readFiniteInput(ui.audioFadeOut, "Fade out"),
    });
    ui.editFormMessage.classList.remove("error");
    ui.editFormMessage.textContent =
      "Clip audio settings staged. No timeline write has occurred.";
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent = error.message || String(error);
  }
});

function stageDuckingAction(action) {
  if (!state.selected || state.selected.track.locked) return;
  try {
    const track = state.selected.track;
    if (track.kind !== "audio") {
      throw new Error("Ducking targets must be an explicit audio track.");
    }
    const duckingId = ui.audioDuckingId.value.trim();
    const keyTrackIds = [...ui.audioDuckingKeys.selectedOptions]
      .map((option) => option.value).sort();
    const edit = {
      schema_version: "1.0.0",
      operation_id: newStableId("manual_ducking"),
      kind: "audio_ducking",
      action,
      ducking_id: duckingId,
      key_track_ids: action === "apply" ? keyTrackIds : [],
      target_track_ids: [track.track_id],
      reduction_db: readFiniteInput(ui.audioDuckingReduction, "Ducking reduction"),
      attack_seconds: readFiniteInput(ui.audioDuckingAttack, "Ducking attack"),
      release_seconds: readFiniteInput(ui.audioDuckingRelease, "Ducking release"),
    };
    if (!duckingId) throw new Error("Ducking pass ID is required.");
    if (action === "apply" && keyTrackIds.length === 0) {
      throw new Error("Select at least one declared speech key track.");
    }
    stageEdit(edit);
    ui.editFormMessage.classList.remove("error");
    ui.editFormMessage.textContent =
      `${action === "apply" ? "Ducking" : "Ducking removal"} staged. ` +
      "No timeline write has occurred.";
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent = error.message || String(error);
  }
}

ui.stageDucking.addEventListener("click", () => stageDuckingAction("apply"));
ui.removeDucking.addEventListener("click", () => stageDuckingAction("remove"));

ui.stageTrackMix.addEventListener("click", () => {
  if (!state.selected || state.selected.track.locked) return;
  try {
    const track = state.selected.track;
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_track_mix"),
      kind: "track_mix",
      track_key: track.track_key,
      track_id: track.track_id,
      gain_db: readFiniteInput(ui.audioTrackGain, "Track gain"),
      muted: ui.audioTrackMuted.checked,
      pan: readFiniteInput(ui.audioTrackPan, "Track pan"),
    });
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent = error.message || String(error);
  }
});

function stageEnvelopeAction(action) {
  if (!state.selected || state.selected.track.locked) return;
  try {
    const pointId = ui.audioPointId.value.trim();
    const edit = {
      schema_version: "1.0.0",
      operation_id: newStableId("manual_envelope"),
      kind: "volume_envelope",
      track_key: state.selected.track.track_key,
      track_id: state.selected.track.track_id,
      clip_id: state.selected.clip.clip_id,
      action,
    };
    if (action !== "clear") edit.point_id = pointId;
    if (action === "upsert") {
      edit.offset_seconds = readFiniteInput(ui.audioPointTime, "Point time");
      edit.gain_db = readFiniteInput(ui.audioPointGain, "Point gain");
    }
    stageEdit(edit);
  } catch (error) {
    ui.editFormMessage.classList.add("error");
    ui.editFormMessage.textContent = error.message || String(error);
  }
}

ui.stageEnvelope.addEventListener("click", () => stageEnvelopeAction("upsert"));
ui.deleteEnvelope.addEventListener("click", () => stageEnvelopeAction("delete"));
ui.clearEnvelope.addEventListener("click", () => stageEnvelopeAction("clear"));

ui.analyzeLoudness.addEventListener("click", async () => {
  if (!state.selected || state.selected.track.locked) return;
  ui.analyzeLoudness.disabled = true;
  ui.audioAnalysisStatus.textContent = "Analyzing exact selected audio range…";
  try {
    const response = await fetch("/api/audio/loudness/analyze", {
      method: "POST",
      headers: {Accept: "application/json", "Content-Type": "application/json"},
      body: JSON.stringify({
        schema_name: "vistora.loudness-analysis-request",
        schema_version: "1.0.0",
        track_id: state.selected.track.track_id,
        clip_id: state.selected.clip.clip_id,
        target_lufs: -16,
        max_true_peak_dbfs: -1,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error?.message || "Analysis failed");
    state.loudnessEvidence = payload;
    ui.audioAnalysisStatus.textContent =
      `${payload.integrated_lufs.toFixed(2)} LUFS / ` +
      `${payload.true_peak_dbfs.toFixed(2)} dBTP; suggested ` +
      `${payload.recommended_gain_db.toFixed(2)} dB` +
      `${payload.cached ? " (cached)" : ""}.`;
    ui.applyLoudness.disabled = false;
  } catch (error) {
    state.loudnessEvidence = null;
    ui.applyLoudness.disabled = true;
    ui.audioAnalysisStatus.textContent = error.message || String(error);
  } finally {
    ui.analyzeLoudness.disabled = false;
  }
});

ui.applyLoudness.addEventListener("click", () => {
  if (!state.selected || !state.loudnessEvidence) return;
  const evidence = state.loudnessEvidence;
  stageEdit({
    schema_version: "1.0.0",
    operation_id: newStableId("manual_loudness_apply"),
    kind: "clip_audio",
    track_key: state.selected.track.track_key,
    track_id: state.selected.track.track_id,
    clip_id: state.selected.clip.clip_id,
    gain_db: evidence.recommended_gain_db,
    normalization_evidence: {
      schema_version: "1.0.0",
      analysis_id: evidence.analysis_id,
      analyzed_clip_digest: evidence.analyzed_clip_digest,
      source_sha256: evidence.source_sha256,
      integrated_lufs: evidence.integrated_lufs,
      true_peak_dbfs: evidence.true_peak_dbfs,
      target_lufs: evidence.target_lufs,
      max_true_peak_dbfs: evidence.max_true_peak_dbfs,
      applied_gain_db: evidence.recommended_gain_db,
    },
  });
  ui.audioGain.value = String(evidence.recommended_gain_db);
  ui.audioAnalysisStatus.textContent += " Gain staged; explicit confirmation remains required.";
});

function selectedTransitionCut() {
  if (!state.selected) throw new Error("Select an outgoing primary video clip.");
  const {track, clip} = state.selected;
  if (track.locked || track.kind !== "video" || track.role !== "primary") {
    throw new Error("Select an unlocked primary video track.");
  }
  const next = track.clips.find(
    (item) => item.clip_id === ui.transitionToClip.value,
  );
  if (!next || Math.abs(clip.timeline_end_seconds - next.timeline_start_seconds) > 1e-6) {
    throw new Error("Transition target must be the exact adjacent cut.");
  }
  return {track, from: clip, to: next};
}

function currentVideoTransition(cut) {
  return (state.snapshot.transitions || []).find(
    (item) => item.media_type === "video" &&
      item.track_id === cut.track.track_id &&
      item.from_clip_id === cut.from.clip_id &&
      item.to_clip_id === cut.to.clip_id,
  ) || null;
}

ui.previewTransition.addEventListener("click", () => {
  try {
    selectedTransitionCut();
    if (!ui.previewVideo.getAttribute("src")) {
      throw new Error("Select an available outgoing source before previewing.");
    }
    const kind = ui.transitionKind.value;
    const direction = ui.transitionDirection.value;
    const duration = Math.max(120, Math.min(1500, Number(ui.transitionDuration.value) * 1000));
    let frames = [{opacity: 1}, {opacity: 0.15}, {opacity: 1}];
    if (kind === "wipe") {
      const starts = {
        left: "inset(0 0 0 100%)", right: "inset(0 100% 0 0)",
        up: "inset(100% 0 0 0)", down: "inset(0 0 100% 0)",
      };
      frames = [{clipPath: starts[direction]}, {clipPath: "inset(0 0 0 0)"}];
    } else if (kind === "slide") {
      const offsets = {left: "100%", right: "-100%", up: "0, 100%", down: "0, -100%"};
      const start = direction === "left" || direction === "right"
        ? `translateX(${offsets[direction]})` : `translate(${offsets[direction]})`;
      frames = [{transform: start}, {transform: "translate(0, 0)"}];
    } else if (kind === "cut") {
      frames = [{opacity: 1}, {opacity: 1}];
    }
    ui.previewVideo.animate(frames, {duration, easing: "linear"});
    ui.transitionFormMessage.classList.remove("error");
    ui.transitionFormMessage.textContent =
      "Controlled browser approximation played; final FFmpeg export is authoritative.";
  } catch (error) {
    ui.transitionFormMessage.classList.add("error");
    ui.transitionFormMessage.textContent = error.message || String(error);
  }
});

function transitionPayload(identity, cut, pairIdentity = null) {
  const kind = ui.transitionKind.value;
  const duration = kind === "cut"
    ? 0
    : readFiniteInput(ui.transitionDuration, "Transition duration");
  if (kind !== "cut" && duration < 0.04) {
    throw new Error("Non-cut transitions require at least 0.04 seconds.");
  }
  const parameters = {
    schema_name: "vistora.transition-parameters",
    schema_version: "1.0.0",
    direction: ["wipe", "slide"].includes(kind)
      ? ui.transitionDirection.value : null,
    color: kind === "fade_color" ? ui.transitionColor.value : null,
  };
  const audioPolicy = kind === "cut" ? "none" : ui.transitionAudioPolicy.value;
  return {
    schema_name: "vistora.timeline-transition",
    schema_version: "1.0.0",
    transition_id: identity,
    track_id: cut.track.track_id,
    from_clip_id: cut.from.clip_id,
    to_clip_id: cut.to.clip_id,
    kind,
    duration_seconds: duration,
    alignment: ui.transitionAlignment.value,
    parameters,
    enabled: true,
    audio_policy: audioPolicy,
    paired_transition_id: audioPolicy === "none" ? null : pairIdentity,
  };
}

function pairedAudioPayload(identity, videoIdentity, cut, duration, alignment) {
  if (!cut.from.keep_audio || !cut.to.keep_audio) {
    throw new Error("Linked audio transition requires active audio on both clips.");
  }
  return {
    schema_name: "vistora.timeline-transition",
    schema_version: "1.0.0",
    transition_id: identity,
    track_id: cut.track.track_id,
    from_clip_id: cut.from.clip_id,
    to_clip_id: cut.to.clip_id,
    kind: ui.transitionAudioKind.value,
    duration_seconds: duration,
    alignment,
    parameters: {
      schema_name: "vistora.transition-parameters",
      schema_version: "1.0.0",
      direction: null,
      color: null,
    },
    enabled: true,
    audio_policy: "none",
    paired_transition_id: videoIdentity,
  };
}

ui.stageTransition.addEventListener("click", () => {
  try {
    const cut = selectedTransitionCut();
    const existing = currentVideoTransition(cut);
    const videoIdentity = existing?.transition_id || newStableId("transition");
    const existingPair = (state.snapshot.transitions || []).find(
      (item) => item.transition_id === existing?.paired_transition_id,
    );
    const pairIdentity = ui.transitionAudioPolicy.value === "none"
      ? null : existingPair?.transition_id || newStableId("transition_audio");
    const transition = transitionPayload(videoIdentity, cut, pairIdentity);
    const paired = pairIdentity
      ? pairedAudioPayload(
          pairIdentity,
          videoIdentity,
          cut,
          transition.duration_seconds,
          transition.alignment,
        )
      : null;
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_transition"),
      kind: "transition",
      action: existing ? "update" : "add",
      transition,
      paired_transition: paired,
      transition_id: null,
      source_transition_id: null,
      targets: [],
    });
    ui.transitionFormMessage.classList.remove("error");
    ui.transitionFormMessage.textContent =
      "Transition staged locally; media handles are validated before confirmation.";
  } catch (error) {
    ui.transitionFormMessage.classList.add("error");
    ui.transitionFormMessage.textContent = error.message || String(error);
  }
});

ui.removeTransition.addEventListener("click", () => {
  try {
    const cut = selectedTransitionCut();
    const existing = currentVideoTransition(cut);
    if (!existing) throw new Error("No transition exists at this cut.");
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_transition_remove"),
      kind: "transition",
      action: "remove",
      transition: null,
      paired_transition: null,
      transition_id: existing.transition_id,
      source_transition_id: null,
      targets: [],
    });
    ui.transitionFormMessage.textContent =
      "Transition and its explicit audio pair are staged for removal.";
  } catch (error) {
    ui.transitionFormMessage.classList.add("error");
    ui.transitionFormMessage.textContent = error.message || String(error);
  }
});

ui.copyTransition.addEventListener("click", () => {
  try {
    const cut = selectedTransitionCut();
    const existing = currentVideoTransition(cut);
    if (!existing) throw new Error("Select a cut with an existing transition.");
    const selectedTargets = Array.from(ui.transitionCopyTargets.selectedOptions)
      .map((option) => JSON.parse(option.value))
      .sort((left, right) =>
        `${left.track_id}/${left.from_clip_id}`.localeCompare(
          `${right.track_id}/${right.from_clip_id}`,
        ),
      );
    if (!selectedTargets.length) throw new Error("Select explicit target cuts.");
    const paired = Boolean(existing.paired_transition_id);
    const targets = selectedTargets.map((target) => {
      const transitionId = newStableId("transition");
      return {
        schema_version: "1.0.0",
        ...target,
        transition_id: transitionId,
        paired_transition_id: paired ? newStableId("transition_audio") : null,
        paired_track_id: paired ? target.track_id : null,
        paired_from_clip_id: paired ? target.from_clip_id : null,
        paired_to_clip_id: paired ? target.to_clip_id : null,
      };
    }).sort((left, right) => left.transition_id.localeCompare(right.transition_id));
    stageEdit({
      schema_version: "1.0.0",
      operation_id: newStableId("manual_transition_copy"),
      kind: "transition",
      action: "copy",
      transition: null,
      paired_transition: null,
      transition_id: null,
      source_transition_id: existing.transition_id,
      targets,
    });
    ui.transitionFormMessage.textContent =
      `${targets.length} explicit transition copy target(s) staged.`;
  } catch (error) {
    ui.transitionFormMessage.classList.add("error");
    ui.transitionFormMessage.textContent = error.message || String(error);
  }
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

ui.reviewBack.addEventListener("click", () => {
  state.selectedPlanChange = null;
  ui.planReviewMessage.textContent =
    state.planReview?.message || "Returned to the timeline snapshot.";
  renderPlanReview();
  renderTimeline();
  if (state.selected) {
    showDetails(state.selected.track, state.selected.clip);
  }
});

ui.reviewReject.addEventListener("click", () => {
  ui.planReviewMessage.textContent =
    "Rejected in this browser view only. No rejection record was created.";
  ui.planReviewStatus.textContent = "local reject";
});

ui.reviewReady.addEventListener("click", () => {
  ui.planReviewMessage.textContent =
    "Marked ready in this browser view only. No confirmation was created.";
  ui.planReviewStatus.textContent = "ready locally";
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
