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

See [ARCHITECTURE.md](ARCHITECTURE.md) for the implemented runtime and responsibility contracts. The exact, user-approved O1–O32 definitions and evidence-based status are governed by [ROADMAP.md](ROADMAP.md) and [roadmap-status.json](roadmap-status.json); internal implementation batches never redefine or renumber those original items.

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

List the versioned production registry, durable registry digest, and every
registered skill's input/output schemas and declared runtime properties:

```powershell
python src/main.py list-skills
```

Start the interactive editing agent:

```powershell
python src/main.py chat
```

The `chat` command remains the legacy `OperatorAgent` compatibility path. Start
the separated production workflow instead with:

```powershell
python src/main.py studio --media-root C:\path\to\your\media
```

Then open `http://127.0.0.1:8765`. The production entry composes the
`DirectorAgent`, deterministic plan review, a separate explicit user decision,
the confirmed `EditingAgent`, workflow history, and reviewed rollback. Each
browser action carries an exact session/project/revision and a unique request
ID; duplicate, stale, cross-session, cross-project, non-loopback, and
CSRF-missing requests fail closed. Refresh and restart reload the append-only
Director, product-session, and workflow ledgers instead of repeating a
confirmation or execution.

The browser never calls a skill or timeline manager. Director dialogue can only
produce or revise a reviewed proposal. Persisting the review, confirming or
rejecting it, running the Editing Agent, and reviewing/confirming rollback are
separate product state transitions. With no observed material, the same entry
can review and independently confirm or reject a Director-authored material
requirements plan. It does not plan production or generate media.

Render a declarative timeline:

```powershell
python src/main.py render --config path\to\timeline.json --output output\result.mp4
```

Run one skill directly through the same validation and result-normalization
gateway:

```powershell
python src/main.py run-skill --name VideoClearTimelineSkill --params "{}"
```

`run-skill` is an explicitly acknowledged low-level compatibility interface,
not the confirmed product workflow. It still resolves only through the
production registry, validates the registered input and result schemas, applies
the declared side-effect policy, and prints a versioned
`vistora.atomic-tool-result` envelope. Use `studio` for Director review,
independent confirmation, workflow history, and rollback.

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

The preview provides an allowlisted material monitor, time ruler/timecode,
synchronized local playhead, deterministic video thumbnails,
timeline-aligned audio waveforms, any number of ordered video/audio lanes,
track role/state labels, a selected-clip inspector, zoom/horizontal
scrolling, and snapshot summary. The inspector reports opaque source
reference and ID, stable track and link-group IDs, source range, timeline
range/duration, playback properties, availability/analysis status, and
recorded origin/plan/step/evidence status. Legacy clips clearly report
unknown provenance rather than receiving fabricated history.

Media URLs and browser snapshot references contain only opaque IDs; configured absolute paths are redacted before the snapshot crosses the HTTP boundary. Paths are resolved only on the server against explicit roots after symlink resolution, and byte ranges are supported for browser playback. Thumbnail PNGs and normalized waveform peaks come from the separate versioned `media_analysis` read boundary. Results and artifacts use a bounded in-memory cache, so refresh and zoom reuse analysis without generating repository files. Missing, unreadable, unsupported, and decode-failed sources remain visible as explicit placeholders. The server binds only to a loopback interface.

For the current workspace only, a selected video or audio clip can be changed
through a detached manual draft: source in/out, timeline start, legacy list
order, split at an interior time, or lift/ripple removal. Every edit
explicitly chooses **current clip only** or **linked group**. The same draft
can link/unlink exact selected clip IDs and change track order,
enabled/muted/locked state. Locked tracks reject clip edits. Staging and
server-side validation do not write. The UI shows direct and consequential
before/after changes, supports undo/reset, and requires the explicit
**Confirm & apply** action. That action binds a user confirmation to the exact
proposal digest and dispatches one transactional atomic skill through the
registry. The browser never writes `TimelineManager` or media directly.
Manual apply is disabled for `--timeline` external documents, which remain
strictly read-only.

The same confirmed draft surface exposes bounded local audio controls: clip
gain in dB, clip mute/pan, linear fades, stable linear gain-envelope points,
and audio-track gain/mute/pan. A read-only **Analyze loudness** action measures
the exact selected range; suggested gain remains a draft until **Stage analyzed
gain** and the separate **Confirm & apply** action. Evidence is bound to clip
timing and the source hash, so changed or missing media fails closed.

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

The Agent deterministically gates each turn as `needs_clarification`,
`materials_incomplete`, `ready_for_material_requirements`, `ready_to_plan`,
`material_requirements_ready`, `proposal_ready`, `unsupported_next_stage`,
`withdrawn`, `model_error`, or `stale_context`. Every new brief carries a
frozen `MaterialStateAssessment` bound to the exact snapshot, brief digest,
and material-facts digest. It classifies the context as `materials_complete`,
`materials_incomplete`, or `no_materials`, with stable observed/unavailable/
selected/missing-evidence IDs and explicit reasons. Legacy brief records with
no assessment remain readable and are displayed as legacy unknown.

The Agent validates all model output against frozen schemas, rejects tool-call
payloads, unobserved evidence, unsafe paths, unavailable tools, workflow-only
tools, stale snapshots, and registry drift, and retries malformed structured
output only within a configured bound. The bundled OpenAI-compatible adapter
uses JSON-only responses and exposes no tool callback; tests and the reference
workflow use deterministic adapters with no external model call.

With complete existing material, a `proposal_ready` result includes an exact
`DirectorPlan`, proposed execution plan, and current step-8 diff review. An
incomplete set stops at `materials_incomplete` and stays in Director dialogue;
it cannot masquerade as either complete or empty. A separately recorded,
current review/execution shortfall instead gates a supplemental material
requirements proposal even when valid material already exists. With no
material facts, the
Director first completes the same creative brief and then may produce a
versioned `MaterialRequirementsPlan`: a reviewable list of required video,
audio, image, narration, or reference assets and why each is needed. Neither
result creates a confirmation, calls another Agent, executes tools, generates
media, exports, or rolls back.

## Initial and supplemental material requirements workflow

`src/material_requirements/` persists the Director's initial no-material or
supplemental-shortfall proposal,
read-only review, explicit confirmation/rejection, revision, and withdrawal in
a separate hash-chained sidecar. Each requirement records its purpose,
narrative position, type, duration/format specifications, continuity, required
and forbidden traits, acceptance criteria, priority, dependencies,
alternatives, and budget/deadline constraints. Unknown budget or deadline is
represented explicitly rather than guessed.

The initial plan is bound to one creative-brief version/digest and the exact
empty timeline snapshot/fact digest. A supplemental plan instead binds one
exact `MaterialShortfallReport`, including the project/snapshot, source plan,
review or confirmed execution, stable missing-requirement IDs, affected
entities, explicit evidence gaps and acceptance criteria. A requirements
revision produces deterministic
added/removed/changed items. Snapshot drift, changed brief/plan/review digest,
duplicate decision, stale revision, or ledger tampering fails closed. Planned
items are never exposed as observed materials or source evidence.

`src/material_feedback/` is the append-only O26 feedback-loop ledger. A
calling review or execution boundary must explicitly record a path-safe
shortfall; the Director cannot infer one from silence. The ledger then links
the exact supplemental requirements proposal, its independent confirmation,
the confirmed production plan/run and accepted catalog entries. Resolution
requires every reported requirement to map one-to-one to accepted material
whose requirements-plan, production-plan and run provenance all match. Stale
snapshots, duplicate or cross-project reports, missing stages, partial catalog
coverage, tampering and replay fail closed. Only resolved, accepted catalog
entries become ordinary observed Director evidence; nothing is automatically
inserted into the timeline.

The `studio` UI shows the requirements checklist and offers separate Review,
Confirm, Reject, and Withdraw actions. Confirmation only approves what
materials are required. It does not generate them: the separately confirmed
Creation Planning Agent described below plans production, while provider
execution remains separately confirmed and constrained.

## Creation Planning Agent

`src/creation_planning/` implements the constrained production-planning
boundary that follows an exact confirmed `MaterialRequirementsPlan`. Its
provider-neutral `CreationPlanningAgent` verifies the immutable material
confirmation, requirements plan/review/brief/snapshot digests, material-ledger
revision, and exact versioned capability registry before reasoning.
Unconfirmed, stale, mismatched, tampered, cross-project, or registry-drifted
requests fail closed.

A versioned `MaterialProductionPlan` maps every confirmed requirement item to
ordered production tasks. Tasks describe the production method, structured
prompt specification where generation is proposed, reference and continuity
anchors, capability requirements, media parameters, reproducibility settings,
dependency DAG and batch, known or explicitly unknown cost/time estimates,
quality gates, retry/alternative strategies, and path-safe delivery file
specifications. Unconfigured or unsupported capabilities remain visibly
blocked; the Agent cannot present them as available.

The Agent can only propose a read-only production plan. A separate
hash-chained `*.creation-planning.json` ledger records plan versions,
deterministic task changes, explicit confirmation/rejection, and withdrawal.
The `studio` entry presents these steps after material-requirements
confirmation. Neither the Agent nor its decision service calls an external
generation provider, writes media, changes the timeline, invokes the Editing
Agent, or changes the Director's definition of what is required and why.

## Material production, validation, and catalog

`src/material_production/` provides a constrained `MaterialProductionAgent`
that consumes only an exact confirmed `MaterialProductionPlan` and delegates
to the production orchestrator; it cannot add tasks or interpret creative
intent. A versioned adapter registry freezes configured
capabilities and request/result schemas before a run. The provider-neutral
job boundary supports submit, poll, cancel, retry, idempotency, progress,
explicit cost-known/unknown state, terminal failure, timeout, partial result,
and `recovery_required`. The single default production factory publishes
explicit capabilities for AI image, video, voice, music and general audio
generation, asset search, local capture, user material requests, and manual
import. No online or paid provider is configured. Manual import is also
unconfigured until an embedding application supplies a secure opaque-token
resolver. A user-material request is the sole always-local action: it records
`needs_input` without creating or importing media. The UI shows every
configured/unconfigured state and never pretends that generation, search,
capture, or import succeeded.

Provider results first enter an ignored, project-scoped staging directory.
Vistora verifies path confinement, task/requirement linkage, file size and
hash, MIME/container/codecs, duration, dimensions, frame rate, and audio
metadata with `ffprobe`, then performs a complete decode check. Invalid results
cannot enter the catalog. Valid
results still require a separate explicit Accept or Reject action. Acceptance
creates two deterministic managed derivatives without modifying the source: a
normalized local transcode and a bounded preview proxy (video, audio, and image
profiles are explicit). It also records a unified technical analysis, stable
technical/workflow tags, and a digest-bound per-check quality report.
Acceptance atomically publishes the original and both derivatives into the
managed catalog and appends their versioned provenance, production IDs,
quality result, license/usage status, and cost state. Legacy catalogs are
verified against their original digest and project deterministically with empty
enrichment fields; Vistora never fabricates historical analysis. Browser
payloads contain only opaque `source_*` and
`material://source_*` identities, never staging or managed filesystem paths.

Only accepted catalog entries become observed Director material on a later
turn. They are not automatically placed on the timeline. The Director must
re-evaluate the real catalog evidence and propose a normal edit; review,
independent user confirmation, and the constrained Editing Agent remain
mandatory. Only registered insertion tools (`VideoAddClipSkill` and
`VideoInsertOverwriteClipSkill`) resolve an accepted catalog URI at the
atomic mutation boundary.

The `studio` surface displays capability configuration, the production queue,
attempts, progress,
failure/recovery status, validated artifacts, explicit acceptance controls,
catalog records, and “Return to Director.” Deterministic fake image/video/
audio generation is used only by tests and reference workflows. Real online AI provider
adapters, credentials, mature cost enforcement, complex AI packaging/effects,
and richer editing skills are not implemented.

## AI packaging task model (O27)

`src/effect_workflow/` defines the first provider-neutral cloud-AI packaging
planning boundary. A frozen `EffectIntent` binds one exact Director plan and
its observed source evidence. A versioned `EffectProductionPlan` contains
stable tasks with an exact shot, track, clip and timeline range; typed object,
mask, tracking and style references; a structured prompt; capability/model
requirements; white-listed parameters; output role; optional cost/time caps;
and explicit acceptance criteria. Review resolves every target against the
detached current snapshot and rejects stale ranges, evidence/source drift or
missing/stale masks.

The separate hash-chained effect ledger records deterministic task-level
reviews and immutable explicit confirmation or rejection. It invokes no
provider, creates no job or artifact, and cannot mutate the timeline. Its
public view always reports `not_configured` at this stage. O28 will add the
approved high-value capability adapters; O29 will define confirmed timeline
fill-back; O30 will add candidate/progress/retry/cache lifecycle. No real or
paid AI provider and no credential is configured or implied by O27.

`src/plan_review/` provides strict version `1.0.0` contracts and a deterministic read-only diff engine for the period before confirmation. A `PlanDiffRequest` binds an exact timeline snapshot ID/revision/digest, Director plan ID/version/digest, non-executable proposed execution-plan digest, and the exact registered tool-schema set. The engine validates proposed arguments with the current registry schemas, simulates supported semantics on detached clip data, and returns stable before/after changes, source-evidence links, provenance summaries, warnings, and net counts. Repeating the same request produces the same document and digest; snapshot or registry drift requires regeneration.

The current semantic adapters cover non-reverse legacy video add (with supplied
opaque media facts, including first-clip canvas adoption), safe legacy clip
property/speed modification, exact-ID
split/trim/move/insert/overwrite/lift/ripple-delete/playback-property,
declarative reverse, and freeze-frame
operations across arbitrary video/audio tracks, explicit current-only versus
linked-group effects, clip/track audio mixing, linear gain envelopes,
read-only loudness analysis with explicit evidenced gain application, track
management, link/unlink, bounded visual keyframe curves, validated clip masks,
bounded compositing declarations, timeline clear/default
project reset, and export timeline effects. Ripple, linked members, and
overwrite-retained sides are shown as consequential changes. Locked-track
proposals fail closed. Legacy proxy-generating add/modify operations, timelapse output,
and registered tools without an adapter are blockers rather than fabricated
previews. Export paths and configured source paths never cross the browser
boundary.

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

## Atomic skill registry and execution gateway

`src/atomic_runtime/` is the single production composition root for the
forty existing atomic skills. A fresh immutable `AtomicSkillRegistry` carries an
explicit ID, semantic version, revision, deterministic input-schema digest, and
full descriptor digest. Every frozen `SkillDescriptor` declares the stable
skill version, exact input and output schemas, timeline/media/file/external
side effects, mutation status, actual transactionality, replay safety, preview
support, rollback/compensation state, and required capabilities. No plugin
discovery or new editing operation is implied.

Director context, detached plan review, confirmation/workflow persistence,
Editing Agent execution, local product entry, preview manual edits, rollback,
and the CLI all bind to this same durable production registry. Registry or
descriptor drift invalidates an older review/confirmation before dispatch.
Legacy schema-only sidecars remain readable, but cannot silently satisfy a
new durable production binding; the review must be regenerated. The old
module-level `SKILLS` name is only a mutable compatibility view for
`OperatorAgent` and historical integrations.

`AtomicExecutionGateway` is the production dispatch boundary. It revalidates
the exact registry, project and confirmation references, input schema and
declared side-effect policy; resolves only registered `BaseSkill`
implementations; validates and normalizes result payloads; redacts absolute
paths and exception details; and provides request-scoped idempotent replay.
The metadata intentionally records that several legacy tools are only
best-effort and that external exports/generated files are not generally
transactional or reversible.

## Core timeline edit skills

`src/timeline_edit/` defines the detached deterministic edit engine and shared
same-directory durable transaction used by the professional core edit
foundation. Versioned exact-`clip_id` tools cover split, source trim with
optional ripple, explicit move with optional per-track ripple,
insert/overwrite, lift/ripple remove, playback properties (speed, declarative
reverse, volume/mute, embedded audio, rotation), and a versioned video-only
freeze frame with an exact source time and hold duration. `TimelineManageTrackSkill` adds,
updates, removes empty tracks, or changes deterministic order; the separate
`TimelineSetClipLinkSkill` explicitly links/unlinks exact clip references.
All operate on any configured video/audio track, return structured
direct/consequential effect lists, and are exposed exclusively through the
production registry and `AtomicExecutionGateway`.

Timeline schema `2.0.0` gives every track a stable ID, video/audio kind, role,
unique order, enabled, muted, and locked state. Any number of video/audio
tracks is supported. Legacy fixed `video`/`audio` JSON is migrated
deterministically at load time and remains renderable. Locked tracks fail
closed for manual and confirmed Agent mutations. A clip may carry only an
explicit stable `link_group_id`; link membership is never inferred from file
paths or approximate timing.

Every core clip edit declares `edit_scope=current_clip` (safe default) or
`edit_scope=linked_group`. Linked split/move/trim/remove/property operations
apply only to the exact group members, validate every affected track first,
and report the selected clip as direct and linked members/ripple neighbors as
consequential. Insert can assign an explicit group ID, but creating multiple
linked source clips still requires separate reviewed requests. Unlink is a
separate structured and confirmed operation.

Overwrite preserves every uncovered left/right interval; split copies
source/playback properties while issuing a stable new clip ID. Workflow trace
records correlate creates/modifies/deletes and tombstones to exact confirmed
steps. Split/overwrite descendants inherit recorded origin/evidence rather
than fabricating provenance. A failed durable write or confirmed trace append
restores the prior timeline bytes.

`VideoModifyClipSkill` and index-based manual/order fields remain explicit
legacy compatibility surfaces. Property-only edits can use
`VideoSetClipPropertiesSkill` without generating a reverse proxy.
`VideoSetClipFreezeFrameSkill` stores no proxy or still file, carries no
embedded audio, and is rendered from the exact bounded source frame. Legacy
`VideoModifyClipSkill` retains its best-effort proxy behavior only for
compatibility.

`VideoExportVariantsSkill` is the bounded multi-spec export boundary. One
confirmed request names two to eight stably ordered variants, each with an
explicit even-sized canvas, frame rate, and create-new MP4 destination. Every
variant is rendered against the same immutable timeline state with exact canvas
enforcement, staged beside its destination, hashed, and published only after all
renders succeed. Existing files are never overwritten; a failed set removes its
staging files and reports failure rather than success. Detached review lists each
canvas/FPS result without exposing output paths or rendering media. The older
`VideoExportSkill` remains compatible and unchanged.
Linked A/V and arbitrary video/audio track foundations are implemented.
Automatic link inference, linked-source ingest as one operation,
transcription/ASR, motion tracking, denoise/de-reverb/source separation, plugin hosting, AI audio
providers, complex mastering, and effects remain unimplemented.

## Local audio editing and mix policy

`ClipAudioSettings` and `TrackMixSettings` are strict frozen version `1.0.0`
attachments to the compatible timeline-v2 model. Legacy `volume` remains a
linear pre-gain and `keep_audio` still controls embedded video audio; with no
new settings, old timelines load and render equivalently. New clip/track gain
uses `-60..+24 dB`, pan uses `-1..+1`, and fades/envelope points use clip-local
post-speed timeline seconds. The existing `speed_factor` remains the shared
video/embedded-audio rate; independent audio rate is accepted only for an
audio-track clip.

Audio clips also carry an explicit semantic role: `dialogue`, `voiceover`,
`background_music`, `sound_effect`, `ambience`, or the legacy-safe
`unspecified`. `AudioApplyDuckingSkill` uses only exact confirmed speech-key
and target track IDs. It deterministically bakes attack/reduction/release
points over declared dialogue/voice-over timeline occupancy, records the key
timeline digest, and can remove only its own generated points. It never
guesses from signal energy and never overwrites a manual or different
envelope. Loudness remains a separate read-only analysis followed by explicit
confirmed gain application.

Final multitrack export converts active sources to stereo, applies legacy and
dB gain, mute, equal-power pan, fades and linear envelope automation, then
mixes without hidden normalization. A deterministic `0.95` peak limiter and
48 kHz stereo output policy protect the combined bus. Browser waveforms are a
read-only approximation; FFmpeg export is authoritative.

## Subtitle and text tracks

Timeline schema `2.0.0` now carries optional first-class `subtitle_tracks`
without changing existing video/audio track or clip JSON. Frozen subtitle
track/cue/style contracts use stable IDs, millisecond timing, deterministic
order, explicit overlap policy, language/speaker metadata, enabled/locked
state, and a controlled logical-font style. Subtitle cues are never modeled
as video clips. Legacy projects with no subtitle field load and render as
before; the read-only snapshot is version `11.0.0` and includes detached subtitle
track/cue counts, cue kind, and optional word-level timing state.

`SubtitleManageTrackSkill`, `SubtitleEditCueSkill`,
`SubtitleImportSkill`, and `SubtitleExportSidecarSkill` are registered
production tools. They cover track lifecycle, add/batch-add/update,
split/merge/move/trim/ripple-shift/delete, controlled styling, read-only
UTF-8 SRT/WebVTT import, and atomic cue-level sidecar export. SRT/WebVTT cannot
carry Vistora word evidence, so word timings remain in the project contract
while exported cue timing and text are deterministic. Locked tracks accept only
an explicit reviewed unlock. Media ripple defaults to `none`; moving captions
requires the reviewed `selected_subtitle_tracks` or `all_unlocked` policy, and
locked subtitle tracks never move.

Optional frozen `SubtitleWord` records bind stable word IDs, exact absolute
timeline ranges, text, and optional confidence to a cue. Word ranges must be
sorted, non-overlapping, unique within a track, and contained by their cue;
split/trim reject cuts through a word while move/ripple shift the word evidence
with its cue. `text` tracks contain explicit `title` cues and reuse the same
safe static style/burn boundary without pretending to be video clips.

Accepted catalog images, or an explicitly configured local source at the
confirmed low-level boundary, can be added with `VideoInsertGraphicSkill` as
an `image` or alpha-bearing `sticker` clip. Static graphics have a declared
timeline duration, are silent, use speed 1, reject reverse/freeze and non-cut
transitions, and render as bounded looped image inputs on exact video tracks.
Insert/overwrite remains detached-reviewable and transactionally persisted;
browser payloads expose only opaque source references and allowlisted media
routes, never absolute paths.

The loopback timeline shows deterministic subtitle lanes, cue details, a
current-time approximate overlay, safe SRT/WebVTT parsing/download, and a
compact draft editor. Browser edits remain detached until structured diff
and explicit confirmation, then use `VideoApplyManualEditsSkill` through the
registry/gateway. Final `VideoExportSkill` can burn selected subtitle tracks
through a generated, escaped ASS file and controlled logical-font fallback;
temporary files are removed and FFmpeg export is authoritative. No arbitrary
font path, filter, or script is accepted.

ASR/automatic word timing, translation, AI copy editing, karaoke highlighting,
animated title templates, arbitrary graphic upload, and general motion graphics
remain out of scope. Word timings are imported or authored evidence, not
inferred by this feature.

## Picture transform, bounded SDR color, and packaging

Every video clip now has optional frozen `ClipTransform`, version `2.0.0`
`ClipColorAdjustment`, and version `2.0.0` `ClipCompositeSettings` state.
Versions `1.0.0` of the color/composite records remain accepted for legacy
projects; missing fields receive neutral defaults. Neutral state preserves timeline-v2 JSON
and its render result. Transform coordinates are normalized to the output
canvas: position is the anchor's canvas location, scale is relative to the
selected contain/fill/stretch fit, rotation is clockwise degrees, crop values
are source-edge fractions, and opacity is composited bottom-to-top by track
order. Crop and flip precede fit/scale; rotation and opacity precede overlay.

The bounded SDR color pipeline applies exposure/brightness, gamma, contrast,
and saturation; then an optional stable master tone curve; then an optional
path-free 17-point RGB 1D LUT; then temperature/tint/highlights/shadows; and
finally either a small sharpen or blur. Inputs reject NaN, infinity, unsafe
ranges, unordered or duplicate curve points, invalid LUT grids, simultaneous
sharpen and blur, raw filters, scripts, and paths. The LUT presets are stored
inline with their exact values and digest-bearing project state; this is not
arbitrary `.cube` import, secondary grading, or an HDR pipeline.

The same confirmed compositing boundary supports normalized rounded corners,
bounded black shadow, blurred source-color glow, and deterministic `normal`,
`multiply`, or `screen` layering. These effects are built only from validated
fields. A timeline that combines first-version transitions with non-normal
blend, shadow, or glow fails before export and must be re-reviewed; the current
transition graph does not pretend that combination is exact.

`VideoSetClipTransformSkill`, `VideoSetClipColorSkill`, and
`VideoCopyClipVisualSkill` are production-registry tools. They target exact
video clip IDs, reject locked/non-video targets, copy only to explicitly named
clips, never spread through linked audio, and use the shared atomic timeline
transaction. Detached review, confirmation/workflow, Editing Agent, trace,
rollback, snapshot v11, Director context, and the manual draft UI carry the
same visual state and digest. Browser video/CSS preview is labeled an
approximation; final FFmpeg export is authoritative. Thumbnail analysis can
request original or applied mode, and its cache key binds the complete visual
digest and canvas settings.

Visual keyframes for the bounded properties above are implemented by the
separate automation system below. Clip masks are implemented by the bounded
mask system below. Tracking, arbitrary LUT-file import, secondary color, HDR,
blend modes beyond normal/multiply/screen, animated titles, and AI effects
remain unimplemented.

## Deterministic video and audio transitions

Timeline schema `2.0.0` now carries an optional mapping of frozen version
`1.0.0` `TimelineTransition` entities. Every transition has a stable ID and
binds an exact track ID plus exact adjacent `from_clip_id`/`to_clip_id`; index,
path, and fuzzy-time lookup are forbidden. The first video set is cut,
cross-dissolve, fade-through-controlled black/white, four-direction wipe, and
four-direction slide/push. Audio supports equal-power, linear, and controlled
fade-out/in crossfades. Duration, centered/start/end alignment, direction,
color, enabled state, and an explicit `none`/`linked_audio`/
`explicit_audio_transition` policy are strict schema fields. Linked audio is
represented by a reciprocal audio transition entity, never a hidden edit.

`TimelineAddTransitionSkill`, `TimelineUpdateTransitionSkill`,
`TimelineRemoveTransitionSkill`, and `TimelineCopyTransitionSkill` are
production-registry tools. They require exact same-track adjacency, reject
locked tracks, validate speed-adjusted incoming/outgoing source handles from
read-only media facts, require both sources of an audio transition to expose
an observed audio stream, and use the shared atomic timeline transaction. Copy
accepts only an explicit stable target-cut list. Split transfers an outgoing
transition to the new right clip; trim/move/ripple/remove/overwrite and speed
changes remove any structurally invalid transition and expose its transition
ID as a consequential tombstone instead of leaving an orphan.

Detached Director review uses the same engine and registry validation but
never dispatches a skill. Snapshot v11 exposes path-free stable transition
state and counts. Confirmed workflow and manual edits record transition
creates/modifies/deletes in provenance; rollback restores the prior project
document. The loopback timeline shows compact cut markers and a transition
panel whose add/update/remove/copy actions remain local draft data until
structured review and explicit confirmation. Its bounded CSS/video animation
is labeled an approximation; final export remains authoritative.

Final export uses a fixed, argument-list FFmpeg graph: visual properties and
basic SDR color are applied to each handled source segment, primary-track
video transitions are composed with controlled `xfade`, audio pairs use
controlled `acrossfade`, tracks are layered/mixed in stable order, subtitles
remain separate, and the existing limiter/final format policy runs last. Old
timelines with no transitions stay on the prior rendering paths and remain
output-equivalent. Version-one video transitions intentionally support the
primary video role only; overlay-track transitions are rejected as
unsupported rather than rendered incorrectly. Source-handle extension never
changes canonical clip trim or placement.

Transition speed curves, tracking, 3D/plugin/VST/OFX transitions,
arbitrary filter strings, and AI effects are not implemented.

## Visual keyframes and parameter animation

Each video/image clip may carry frozen version `1.0.0` `VisualAutomation`
curves with stable automation/keyframe IDs, an exact clip ID, a whitelisted
property path, clip-local post-speed timeline seconds, finite bounded values,
and deterministic ordering. The supported paths are position, axis/uniform
scale, rotation, opacity, four crop edges, and exposure, contrast, saturation,
temperature, tint, and gamma. Arbitrary property paths, expressions, scripts,
Bezier data, and non-finite values are rejected.

Interpolation is fixed and seek-safe: `hold`, `linear`, quadratic `ease_in`,
quadratic `ease_out`, and smoothstep `ease_in_out`. The interpolation on the
left keyframe defines its outgoing segment. Before the first and after the
last keyframe the frozen static transform/color value is the baseline; one
keyframe applies only at its exact local time. A curve therefore overrides one
static property only inside its explicit range and never creates a second
hidden state.

Five production registry tools create/update/delete a keyframe, replace or
clear a curve, and copy selected curves to explicitly named video clips. They
reject locked/non-video targets and never spread through linked audio.
Split samples the boundary and rebases the right curve; trim samples and keeps
the retained interval; speed rescales clip-local offsets to preserve the same
source-relative phase; move/ripple keep local times; remove records automation
tombstones. Every consequential curve change is included in detached review,
confirmed trace, and checkpoint rollback.

Final export evaluates validated FFmpeg expressions from absolute clip-local
time before transition composition, track layering, subtitle burn-in, and
final format conversion. This makes sequential and random-seek frame requests
independent of evaluation history. Applied thumbnail requests bind the exact
timeline sample time and automation digest into the cache key. Browser CSS
preview is intentionally approximate; final FFmpeg export is authoritative.
Snapshot v11 exposes fully detached curve/keyframe data and a stable automation
digest. The compact UI supports previous/next keyframe navigation and detached
upsert/delete/clear/copy proposals, all behind structured diff and explicit
confirmation.

This first version does not provide path animation or motion tracking,
speed-remapping curves, per-word subtitle animation, custom Bezier/expression
editing, 3D, particles, plugins, or AI motion effects.

## Masks and bounded compositing

Original O16 now includes frozen version `1.0.0` rectangle, ellipse, and
convex-polygon clip masks. Every mask and polygon point has a stable ID; masks
support an ordered `add`/`subtract`/`intersect` set, invert, bounded opacity,
feather, expand, normalized position/scale/rotation, and enabled state. Mask
automation reuses the fixed seek-safe interpolation rules for a controlled
property whitelist only. Arbitrary paths, expressions, filters, scripts,
concave/self-intersecting polygons, and non-finite values are rejected.

Four registry-revision-8 atomic tools upsert/remove one mask, replace the
ordered mask set, copy selected masks to explicit clip IDs, or set/reset the
bounded compositing declaration. They reject locked and non-video tracks,
never propagate through linked audio, and use the shared atomic project-state
transaction. Split and trim rebase mask curves deterministically, copy issues
new mask/curve/keyframe IDs, and remove emits truthful mask tombstones.
Detached plan/manual review, explicit confirmation, gateway execution,
snapshot v11, provenance, and rollback share the same state.

Final FFmpeg export generates its alpha expression only from validated mask
fields and composites masked clips in deterministic track order. The browser
uses a clearly approximate CSS preview; exported pixels are authoritative.
The model reserves `multiply` and `screen` declarations for review, but the
current renderer rejects them as unsupported instead of pretending to render
them. Freeform paths, automatic tracking, matte media, rotoscoping, advanced
blend modes, and arbitrary mask-point animation remain unimplemented.

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

## Provider-neutral AI packaging capabilities

Original O28 registers ten explicit high-value packaging capabilities:
background replacement, object removal, localized inpainting, stylization,
frame interpolation, generative transition, generative B-roll, AI voice, AI
music, and AI sound effects. Each capability declares its accepted output
role, required structured O27 task fields, modality, and human acceptance
dimensions. The registry and execution request are frozen, versioned, bound to
the exact confirmed O27 plan/review/snapshot and have deterministic digests.

The production composition contains only truthful `not_configured` provider
adapters. It performs no online or paid request and accepts no credentials.
Tests can explicitly compose a deterministic fixture adapter, while a local
manual-import adapter accepts only server-side opaque tokens and copies the
approved artifact into isolated staging. Both paths produce reviewable
artifact records; every creative acceptance dimension remains pending human
review. Nothing is automatically accepted, cataloged, or written to the
timeline. O29 owns the later confirmed timeline-fillback boundary, and O30
owns candidate/version/progress/retry lifecycle.

The local product view lists all ten capabilities as `not_configured` unless
an application composition explicitly supplies a safe adapter. Run the
focused deterministic contract and dispatch regression with:

```powershell
python -m pytest -q tests/test_effect_capabilities.py
```

## Accepted AI result timeline fillback

Original O29 adds a read-only `EffectFillbackCompiler`. It accepts one exact
O28 execution report, one immutable human artifact acceptance, the matching
validated catalog entry, and one explicit placement. It compiles those facts
into a normal structured `DirectorPlan` and step-8 `PlanDiffRequest`; it does
not create confirmation or execute anything.

Three honest timeline mappings are supported: timed video/audio as a standard
clip, an alpha-validated catalog image as a transparent layer, and catalog
video/image on an explicit non-primary effects/overlay/graphics track as an
effect layer. The compiler uses only opaque `material://source_...` references,
rejects locked/mismatched tracks, duplicate clip IDs, stale reports, catalog
digest drift, unverified alpha, and overlong placement. The normal workflow
then provides review, independent user confirmation, constrained EditingAgent
dispatch through existing registered atomic tools, provenance, checkpoints,
and rollback. Rollback restores project state but does not delete the accepted
external artifact.

Run the deterministic standard-clip/transparent/effect-layer compilation and
confirmed fillback regression with:

```powershell
python -m pytest -q tests/test_effect_fillback.py
```

## Validation

The integration validation creates its own synthetic source clip and generated outputs under `tests/test_data/`:

```powershell
python tests/run_validation.py
```

Run the deterministic no-material → production → catalog → Director review →
confirmation → recorded execution → rollback reference workflow:

```powershell
python -m pytest -q tests/test_reference_workflow.py
```

The multi-track reference also creates an exact cut, reviews and confirms a
reciprocal dissolve/equal-power pair, exports it through the Editing Agent and
registry gateway, verifies transition provenance, and restores the original
timeline checkpoint.

Run the focused deterministic transition contract, review, confirmed manual
application, render, pixel, audio and ffprobe regression:

```powershell
python -m pytest -q tests/test_transitions.py
```

Run the original O16 mask contract, detached review, confirmed gateway/manual
application, trace, transaction rollback, and real pixel regression:

```powershell
python -m pytest -q tests/test_masks.py
```

This reference first confirms Director material requirements and a
CreationPlanningAgent plan, uses a test-only deterministic provider, validates
and explicitly accepts the artifact into the catalog, and only then returns
the observed material to the Director. Its final proposal enters read-only
review, a separate explicit confirmation, and the constrained Editing Agent.
It performs no external model/provider call.

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
