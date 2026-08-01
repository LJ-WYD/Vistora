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
  editSplitAt: document.querySelector("#edit-split-at"),
  editRemoveMode: document.querySelector("#edit-remove-mode"),
  editScope: document.querySelector("#edit-scope"),
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
  return (
    `${formatSeconds(stateValue.timeline_start_seconds)}–` +
    `${formatSeconds(stateValue.timeline_end_seconds)} · ` +
    `${formatSeconds(stateValue.trim_in_seconds)}–` +
    `${formatSeconds(stateValue.trim_out_seconds)} source · ` +
    `${stateValue.speed_factor}×`
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
      safeChangeState(change.before || change.before_project),
    ),
    detailRow(
      "After",
      safeChangeState(change.after || change.after_project),
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
      ["Materials", `${brief.material_ids.length} observed`],
      ["Evidence", `${brief.evidence_ids.length} bound`],
    ];
    for (const [label, value] of values) {
      ui.directorBrief.append(detailRow(label, value));
    }
    ui.directorBrief.append(
      detailRow("Reason", brief.readiness_reasons.join(" ")),
    );
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

function existingDraftForClip(clipId) {
  return state.draftEdits.find((edit) => edit.clip_id === clipId) || null;
}

function showManualEditor(track, clip) {
  const applyEnabled = state.capabilities.manual_edit_apply === true;
  ui.manualEditDisabled.hidden = applyEnabled;
  ui.manualEditor.hidden = !applyEnabled;
  if (!applyEnabled) {
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
  if (change.action === "create") {
    return [
      `Create at ${formatSeconds(change.after.timeline_start_seconds)}`,
      `${formatSeconds(change.after.trim_in_seconds)} → ` +
        formatSeconds(change.after.trim_out_seconds),
      change.after.source_name,
    ];
  }
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
    return `clip:${value.track_id || value.track_key}/${value.clip_id}`;
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
      availability?.content_type || `${track.kind} · unavailable`,
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
      `${clip.speed_factor}× · ${clip.reverse ? "reverse" : "forward"} · ` +
        `${clip.rotate_degrees}°`,
    ),
    detailRow(
      "Media access",
      availability?.available
        ? `Allowlisted · ${availability.content_type}`
        : "Unavailable or outside allowlisted roots",
    ),
    detailRow("Visualization", analysisStatusLabel(analysis)),
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

function audioWaveform(result) {
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
  return svg;
}

function clipVisualization(track, clip) {
  const result = analysisFor(track, clip);
  if (track.kind === "video") {
    return videoThumbnailStrip(result);
  }
  if (track.kind === "audio") {
    return audioWaveform(result);
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
    const response = await fetch("/api/analysis", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
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
    state.analysis = {};
    state.analysisState = "idle";
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
    showOrphanedProvenance();
    ui.manualEditor.hidden = true;
    ui.manualEditDisabled.hidden = true;
    resetDraft({ keepSuccess: preserveSuccess });
    renderSummary();
    renderTimeline();
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
