# Vistora

Vistora is an early-stage, agent-driven video editing prototype. It represents edits as a declarative timeline and applies them through small, schema-validated editing skills backed by MoviePy and FFmpeg.

The current public baseline contains the editing runtime, versioned review/provenance/workflow contracts, and their reference interfaces. Generated media, local workspaces, model weights, credentials, and machine-specific investigation scripts are intentionally excluded.

## Architecture

- The agent layer translates an editing request into calls to registered skills.
- Each skill validates its input with a Pydantic model and performs one bounded editing operation.
- `TimelineManager` persists the active declarative timeline in the local workspace.
- `TimelineRenderer` is responsible for producing media from that timeline.
- `TimelineSnapshotService` exposes detached, immutable read models for inspection without changing timeline or media state.

The architecture keeps creative planning separate from execution: the production `DirectorAgent` maintains a versioned creative brief and produces a structured, reviewable proposal; a separate explicit user-confirmation action gates the constrained production `EditingAgent`; and only atomic tools mutate timeline or media state. The interactive `OperatorAgent` remains a compatibility prototype and is not part of the confirmed production path.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the implemented runtime, binding responsibility contracts, compatibility exceptions, and current-to-target gap register.

## Requirements

- Python 3.10 or newer
- FFmpeg and `ffprobe` available on `PATH`
- An OpenAI-compatible endpoint only when using interactive chat or the production Director adapter

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` in `.env` for the interactive agent. Never commit `.env`.

## Usage

List the registered atomic skills and their schemas:

```powershell
python src/main.py list-skills
```

Start the interactive editing agent:

```powershell
python src/main.py chat
```

Render a declarative timeline:

```powershell
python src/main.py render --config path\to\timeline.json --output output\result.mp4
```

Run one skill directly:

```powershell
python src/main.py run-skill --name VideoClearTimelineSkill --params "{}"
```

Read the current timeline without changing it:

```python
from timeline_query import TimelineSnapshotService

snapshot = TimelineSnapshotService.snapshot_current()
print(snapshot.model_dump_json(indent=2))
```

The `vistora.timeline-snapshot` output is versioned and deterministic. It includes project/revision identity, configured tracks and clips, source references, declared timing, aggregate duration/count fields, and detached clip provenance summaries when trace data exists. The service accepts a current `TimelineConfig`, legacy timeline JSON, or a versioned `TimelineProjectDocument`. It does not probe media, save state, render, or expose mutable source models. Add `src` to `PYTHONPATH` when invoking this library directly from the repository root.

Open the local snapshot-first visual timeline:

```powershell
python src/main.py preview --media-root C:\path\to\your\media
```

Then visit `http://127.0.0.1:8765`. Use `--timeline path\to\timeline.json` to inspect a specific legacy or versioned document instead of the current workspace, repeat `--media-root` for additional roots, or omit all media roots to disable browser media serving.

The preview provides an allowlisted material monitor, time ruler/timecode, synchronized local playhead, deterministic video thumbnails, timeline-aligned audio waveforms, video/audio lanes, data-only unsupported-track messaging, a selected-clip inspector, zoom/horizontal scrolling, and snapshot summary. The inspector reports opaque source reference and ID, media type, track, source range, timeline range/duration, playback properties, availability/analysis status, and recorded origin/plan/step/evidence status. Legacy clips clearly report unknown provenance rather than receiving fabricated history.

Media URLs and browser snapshot references contain only opaque IDs; configured absolute paths are redacted before the snapshot crosses the HTTP boundary. Paths are resolved only on the server against explicit roots after symlink resolution, and byte ranges are supported for browser playback. Thumbnail PNGs and normalized waveform peaks come from the separate versioned `media_analysis` read boundary. Results and artifacts use a bounded in-memory cache, so refresh and zoom reuse analysis without generating repository files. Missing, unreadable, unsupported, and decode-failed sources remain visible as explicit placeholders. The server binds only to a loopback interface.

For the current workspace only, a selected video clip can also be changed through a detached manual draft: source in/out, timeline start, list order, or removal. Staging and server-side validation do not write. The UI shows a before/after proposal, supports undo/reset (including restoring a staged removal), and requires the explicit **Confirm & apply** action. That action binds a user confirmation to the exact proposal digest and dispatches one transactional atomic skill through the registry. The browser never writes `TimelineManager` or media directly. Manual apply is disabled for `--timeline` external documents, which remain strictly read-only.

## Provenance and trace queries

Vistora stores new provenance in an append-only `current_timeline.trace.json` sidecar beside the compatible legacy timeline. Versioned contracts link source evidence, a confirmed Director plan, its execution step, atomic request/result, and the clips or generated output affected by that result. Manual Apply records a separate truthful `user_manual` change; it never labels user-authored edits as Director intent. Trims and reorders preserve the original clip origin while recording the latest user change, and removals retain a queryable tombstone.

Legacy projects need no sidecar and continue to load and render unchanged. Missing history is reported as `legacy_unknown`; stale, orphaned, and deleted mappings are explicit, and the inspector surfaces a recorded live clip that is missing from the current timeline. Generated media outputs use a distinct `generated_media` relation rather than being mislabeled as source footage or a manual edit. Source evidence exposed to the browser contains only opaque material IDs, typed locators, bounded time ranges, and optional analysis-fact IDs—not filesystem paths.

```python
from contracts import PlanReference
from timeline_query import TimelineSnapshotService
from traceability.query import TraceabilityQuery
from traceability.store import TraceabilityStore

snapshot = TimelineSnapshotService.snapshot_current()
query = TraceabilityQuery(TraceabilityStore.load(), snapshot)
clips = query.plan_to_clips(PlanReference.from_plan(director_plan))
```

Provenance describes recorded history; the separate plan-review boundary below describes proposed, unapplied changes. The production Editing Agent consumes these existing workflow/provenance services but does not create Director intent.

## Production Director Agent and plan review

`src/agent/director_agent.py` implements the production creative boundary. It accepts natural-language turns through a provider-neutral structured-reasoning adapter, reads only a detached timeline/material/provenance/tool-schema context, and persists an append-only, hash-chained Director session ledger. Every creative-brief version records the objective, audience, platform, duration, style, narrative and pacing, required and forbidden elements, delivery requirements, selected materials and evidence, assumptions, open questions, and acceptance criteria.

The Agent deterministically gates each turn as `needs_clarification`, `needs_materials`, `ready_to_plan`, `proposal_ready`, `unsupported_next_stage`, `withdrawn`, `model_error`, or `stale_context`. It validates all model output against frozen schemas, rejects tool-call payloads, unobserved evidence, unsafe paths, unavailable tools, workflow-only tools, stale snapshots, and registry drift, and retries malformed structured output only within a configured bound. The bundled OpenAI-compatible adapter uses JSON-only responses and exposes no tool callback; tests and the reference workflow use deterministic adapters with no external model call.

This step supports the existing-material main path only. Missing material is reported honestly; no-material creative planning, media generation, AI packaging, and richer editing capabilities are not implemented. A `proposal_ready` result includes an exact `DirectorPlan`, proposed execution plan, and current step-8 diff review. It does not create a confirmation, call the Editing Agent, execute tools, export, or roll back.

`src/plan_review/` provides strict version `1.0.0` contracts and a deterministic read-only diff engine for the period before confirmation. A `PlanDiffRequest` binds an exact timeline snapshot ID/revision/digest, Director plan ID/version/digest, non-executable proposed execution-plan digest, and the exact registered tool-schema set. The engine validates proposed arguments with the current registry schemas, simulates supported semantics on detached clip data, and returns stable before/after changes, source-evidence links, provenance summaries, warnings, and net counts. Repeating the same request produces the same document and digest; snapshot or registry drift requires regeneration.

The current semantic adapters cover non-reverse video add (with supplied opaque media facts, including first-clip canvas adoption), safe clip property/speed modification, timeline clear/default-project reset, and export timeline effects. Proxy-generating reverse operations, timelapse output, the separate user-authored manual-edit tool, and registered tools without an adapter are blockers rather than fabricated previews. Export paths and configured source paths never cross the browser boundary.

Supply an exact versioned request fixture to the local UI:

```powershell
python src/main.py preview `
  --timeline path\to\the-bound-timeline.json `
  --plan-review path\to\plan-diff-request.json `
  --media-root C:\path\to\your\media
```

The **方案审阅 / 变更预览** panel groups additions, removals, changes, and warnings; synchronizes rows with affected timeline clips and the evidence inspector; and marks stale, invalid, unsupported, or blocked proposals clearly. **Back**, **Reject locally**, and **Ready to confirm** still change browser view state only. They never create a confirmation.

For a current-workspace preview, the separate workflow panel can deliberately persist the exact review, record an explicit immutable confirmation or rejection, run the confirmed steps through the registered atomic-tool application boundary, and show execution/rollback history. External `--timeline` documents remain read-only. The preview can also display a browser-safe Director history projection supplied with `--director-history`; this display is read-only and never turns `proposal_ready` into confirmation. The browser workflow routes continue to use the same application service and do not bypass the Editing Agent's constraints.

## Persistent workflow ledger and rollback

`src/workflow/` implements strict frozen version `1.0.0` records for Director plan versions, exact review sessions, immutable user decisions, execution runs and per-step request/results, integrity-checked project checkpoints, and separately reviewed/confirmed rollback runs. Records are appended to `current_timeline.workflow.json` beside the current project. Each entry has a contiguous sequence, previous-entry digest, and content digest; the ledger has its own integrity digest. Writes use an exclusive project lock, optimistic revision guard, temporary file, `fsync`, and atomic replacement. Unsupported versions, broken chains, tampering, duplicate decisions, confirmation replay, stale snapshots, registry drift, and illegal transitions fail closed.

The ledger keeps one stable logical identity for the workspace while every review/checkpoint retains the exact timeline snapshot ID, revision, and digest it observed. This permits a second reviewed plan after a legacy content-derived `project_legacy_*` snapshot ID changes, without weakening freshness checks or changing legacy timeline JSON.

`WorkflowApplicationService` is the mutation-capable application boundary under the production Editing Agent. It regenerates the exact reviewed diff immediately before confirmation/execution, dispatches registered atomic requests in order, records every result and provenance effect, stops on the first failure, and records `failed`, `partial`, or `recovery_required` truthfully. A restart helper converts abandoned pending/running records to `recovery_required` rather than guessing success.

## Constrained Editing Agent

`src/agent/editing_agent.py` implements the production mechanical executor. `prepare_execution` resolves a frozen `vistora.workflow.confirmed-execution-binding` containing the exact ledger revision, plan reference, review/diff, proposed execution, snapshot, and registry-schema references. `execute` accepts only the versioned `vistora.editing-agent.execution-request`, rechecks that complete binding, and delegates the declared steps to `WorkflowApplicationService`. It cannot chat, infer creative choices, add or reorder operations, import timeline/rendering engines, or invoke a skill directly.

The returned `vistora.editing-agent.execution-report` is frozen and serializable. It identifies the confirmation, workflow revisions, execution run, exact ordered atomic request/result IDs, snapshot changes, and truthful terminal state. Rejected, stale, replayed, tampered, or concurrent requests produce a structured fail-closed report with no claimed run. Atomic failures remain `failed` or `partial`; interrupted runs are explicitly recovered as `recovery_required`.

Library use starts from an already persisted explicit confirmation:

```python
from agent import EditingAgent

agent = EditingAgent(workflow_service)
request = agent.prepare_execution(
    request_id="editing_request_001",
    confirmation_record_id=confirmation.confirmation_record_id,
)
report = agent.execute(request)
```

This API does not create reviews or confirmations. The caller must use the existing review and confirmation application actions first. `OperatorAgent` and the `chat` command remain legacy conversational/tool-calling compatibility paths; they do not gain or represent this confirmation gate.

Rollback is never automatic. The service first creates a deterministic proposal from the current exact checkpoint to the run's start checkpoint. Manual edits or other revision drift make the proposal unavailable or stale. A second immutable user decision is required before `VideoRestoreTimelineCheckpointSkill` atomically restores the validated timeline document. This restores timeline/project JSON only: generated/exported external media is neither deleted nor promised reversible, and original execution/provenance history remains append-only.

## Validation

The integration validation creates its own synthetic source clip and generated outputs under `tests/test_data/`:

```powershell
python tests/run_validation.py
```

Run the deterministic review → confirmation → recorded execution → rollback reference workflow:

```powershell
python -m pytest -q tests/test_reference_workflow.py
```

This reference runs a deterministic fake Director adapter through the production `DirectorAgent`, feeds its proposal into the read-only review boundary, records a separate explicit confirmation, and then exercises the production constrained Editing Agent.

Generated validation media and local runtime state are ignored by Git.

## Project status

Vistora is pre-alpha. Interfaces, schemas, rendering behavior, and hardware acceleration support may change. Review generated timelines and outputs before relying on them.

## Naming and compatibility

The product and public repository are named Vistora. Existing checkouts may still use an `AetherEdit` directory name; the directory name is not part of the runtime contract and does not need to be changed.

This naming release intentionally keeps existing Python module paths, `OperatorAgent`, and atomic skill identifiers such as `VideoAddClipSkill` unchanged. They are technical compatibility surfaces or domain terms rather than public product branding.

## Security and privacy

Treat source footage, generated proxies, timeline files, and model credentials as sensitive. Keep them in ignored local directories, inspect changes before committing, and avoid sharing `.env` or runtime workspaces.

## License

No open-source license has been selected for this repository yet. The source is publicly visible, but no reuse license is granted.
