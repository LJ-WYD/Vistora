# Vistora V1 engineering acceptance

This document summarizes the implemented engineering baseline. The immutable
task definitions remain exclusively in [ROADMAP.md](ROADMAP.md); machine-
verified status, remote commits, implementation paths and test evidence remain
in [roadmap-status.json](roadmap-status.json).

## Original O1–O32 capability matrix

| Original item | Implemented V1 evidence | Status |
| --- | --- | --- |
| O1 | `ARCHITECTURE.md`, architecture boundary tests | complete |
| O2 | `contracts`, version/schema round-trip tests | complete |
| O3 | deterministic material→Director→confirmation→Editing→export reference | complete |
| O4 | `timeline_query` detached snapshots | complete |
| O5 | loopback multi-track timeline/player UI | complete |
| O6 | `media_analysis` thumbnails, waveforms and inspector | complete |
| O7 | `traceability` bidirectional evidence/entity queries | complete |
| O8 | `plan_review` deterministic detached diff | complete |
| O9 | `workflow` plan/confirmation/execution/checkpoint/rollback ledger | complete |
| O10 | `atomic_runtime` registry and gateway | complete |
| O11 | exact-ID timeline skills, multi-track, reverse and freeze | complete |
| O12 | visual transform and atomic multi-spec export | complete |
| O13 | subtitle/text tracks, words, titles, images and stickers | complete |
| O14 | audio roles, envelope, ducking and loudness normalization | complete |
| O15 | color/tone curve/LUT and bounded compositing | complete |
| O16 | transitions, visual keyframes and masks | complete |
| O17 | registry-aware Director plans and constrained EditingAgent | complete |
| O18 | confirmed manual draft/diff/user-revision path | complete |
| O19 | production Director dialogue/brief/readiness entry | complete |
| O20 | complete/incomplete/absent material state | complete |
| O21 | confirmed material-requirements plans | complete |
| O22 | constrained CreationPlanningAgent | complete |
| O23 | provider-neutral material production agent/adapters | complete |
| O24 | staged validation, proxy/transcode, analysis, tags, QC and catalog | complete |
| O25 | accepted catalog material returns to Director | complete |
| O26 | audited missing-material feedback loop | complete |
| O27 | versioned AI packaging intent/task/review/confirmation | complete |
| O28 | ten high-value provider-neutral capability boundaries | complete |
| O29 | accepted effect artifact→catalog→confirmed atomic timeline fillback | complete |
| O30 | candidates, cost/progress, retry/redo, selection/rollback and cache | complete |
| O31 | nine-check finished-media automatic QC | complete |
| O32 | version compare, brand/preferences, confirmed multi-spec delivery manifest | validation pending |

## Deterministic acceptance coverage

- Existing-material entry: Director brief and evidence → reviewed plan →
  explicit confirmation → EditingAgent/gateway → multi-track edits and export →
  O31 QC → history and rollback.
- No-material entry: Director material requirements → explicit confirmation →
  CreationPlanningAgent → explicit confirmation → deterministic fake production
  → validation/acceptance/catalog → Director re-evaluation → reviewed edit →
  explicit confirmation → EditingAgent.
- AI packaging entry: structured effect intent → explicit review/confirmation →
  unavailable, deterministic-test or manual-import adapter truthfully reported →
  human candidate acceptance → catalog → Director review → confirmed atomic
  fillback. No real online provider is called by acceptance tests.
- Delivery entry: exact project version + versioned brand/preferences → reviewed
  multi-spec plan → explicit confirmation → EditingAgent registered export →
  per-output QC → immutable manifest.

## Explicit limitations

- Production ships with no configured paid/online AI provider and no embedded
  credentials. Deterministic fake adapters are tests, not claimed generation.
- No third-party plugin/VST/OFX host, arbitrary scripts/filters, mature HDR
  pipeline, advanced secondary color system, denoise/source separation or
  commercial deployment/installer is claimed.
- Candidate rollback changes an audited selection; it does not delete external
  artifacts. Timeline rollback restores project state and does not delete
  exports or provider artifacts.
- O31 black/freeze detection is threshold-based. Burned subtitle visual safety
  relies on explicit subtitle review evidence.
- O32 is local create-new MP4 delivery. Cloud upload, platform publishing and
  overwriting existing user files are intentionally absent.
- The legacy direct `render` CLI remains a documented compatibility exception;
  the production product path uses review, confirmation and EditingAgent.
