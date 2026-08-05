"""Strict versioned contracts for pre-confirmation Director plan review."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts import (
    DirectorPlan,
    EditingStep,
    PlanReference,
    SourceEvidenceReference,
)
from timeline_query import (
    ClipColorSnapshot,
    ClipProvenanceSummary,
    ClipTransformSnapshot,
    EvidenceSummary,
    TimelineSnapshotReference,
)


PLAN_REVIEW_VERSION = "1.0.0"
PlanReviewVersion = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value).encode()).hexdigest()}"


class ReviewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: PlanReviewVersion = PLAN_REVIEW_VERSION


class ProposedEditingExecutionPlan(ReviewModel):
    """Non-executable exact step projection used only before confirmation."""

    schema_name: Literal["vistora.proposed-editing-execution-plan"] = (
        "vistora.proposed-editing-execution-plan"
    )
    proposal_execution_id: StableId
    project_id: StableId
    director_plan: DirectorPlan
    steps: tuple[EditingStep, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def steps_exactly_project_plan(self) -> ProposedEditingExecutionPlan:
        operations = {
            operation.operation_id: operation
            for operation in self.director_plan.operations
        }
        if len(self.steps) != len(operations):
            raise ValueError(
                "Proposed execution must contain every Director operation"
            )
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Proposed execution step IDs must be unique")
        source_ids = [step.source_operation_id for step in self.steps]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(
                "Proposed execution source operation IDs must be unique"
            )
        if tuple(source_ids) != tuple(operations):
            raise ValueError(
                "Proposed execution order must match the Director plan"
            )
        for step in self.steps:
            operation = operations.get(step.source_operation_id)
            if operation is None:
                raise ValueError(
                    f"Unknown Director operation: {step.source_operation_id}"
                )
            if step.step_id != operation.operation_id:
                raise ValueError(
                    "Proposed step ID must equal its source operation ID"
                )
            if (
                step.tool_name != operation.tool_name
                or step.arguments != operation.arguments
                or step.evidence_ids != operation.evidence_ids
            ):
                raise ValueError(
                    f"Proposed step {step.step_id} drifts from Director intent"
                )
        return self

    @classmethod
    def from_director_plan(
        cls,
        *,
        proposal_execution_id: str,
        project_id: str,
        director_plan: DirectorPlan,
    ) -> ProposedEditingExecutionPlan:
        return cls(
            proposal_execution_id=proposal_execution_id,
            project_id=project_id,
            director_plan=director_plan,
            steps=tuple(
                EditingStep(
                    step_id=operation.operation_id,
                    source_operation_id=operation.operation_id,
                    tool_name=operation.tool_name,
                    arguments=operation.arguments,
                    evidence_ids=operation.evidence_ids,
                )
                for operation in director_plan.operations
            ),
        )

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class ProposedExecutionReference(ReviewModel):
    proposal_execution_id: StableId
    execution_schema_version: Literal["1.0.0"] = "1.0.0"
    execution_digest: Sha256Digest

    @classmethod
    def from_execution(
        cls,
        execution: ProposedEditingExecutionPlan,
    ) -> ProposedExecutionReference:
        return cls(
            proposal_execution_id=execution.proposal_execution_id,
            execution_digest=execution.digest(),
        )


class RegistrySchemaReference(ReviewModel):
    """Exact durable registry used to validate a preview.

    ``registry_digest=None`` identifies a legacy schema-only reference. Such a
    record remains loadable but cannot compare equal to a current production
    registry reference, so confirmation/execution fail closed until review is
    regenerated.
    """

    schema_name: Literal["vistora.registry-schema-reference"] = (
        "vistora.registry-schema-reference"
    )
    registry_id: StableId = "registry_atomic_skills"
    registry_version: Literal["1.0.0"] = "1.0.0"
    registry_revision: int = Field(default=1, ge=1)
    tool_names: tuple[StableId, ...]
    schema_digest: Sha256Digest
    registry_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def registry_identity_is_unambiguous(
        self,
    ) -> RegistrySchemaReference:
        if not self.tool_names:
            raise ValueError("Registry schema reference cannot be empty")
        if len(self.tool_names) != len(set(self.tool_names)):
            raise ValueError("Registry tool names must be unique")
        if self.tool_names != tuple(sorted(self.tool_names)):
            raise ValueError("Registry tool names must use stable ordering")
        return self

    @classmethod
    def from_registry(
        cls,
        registry: Mapping[str, Any],
    ) -> RegistrySchemaReference:
        durable = getattr(registry, "reference", None)
        if durable is not None:
            return cls(
                registry_id=durable.registry_id,
                registry_version=durable.registry_version,
                registry_revision=durable.registry_revision,
                tool_names=durable.tool_names,
                schema_digest=durable.input_schema_digest,
                registry_digest=durable.registry_digest,
            )
        schemas = []
        for name, skill in sorted(registry.items()):
            input_model = getattr(skill, "input_model", None)
            if input_model is None:
                raise ValueError(
                    f"Registered tool {name!r} has no input schema"
                )
            if getattr(skill, "name", None) != name:
                raise ValueError(
                    f"Registered tool identity mismatch for {name!r}"
                )
            schemas.append(
                {
                    "name": name,
                    "parameters": input_model.model_json_schema(),
                }
            )
        return cls(
            tool_names=tuple(item["name"] for item in schemas),
            schema_digest=digest_json(schemas),
            registry_digest=None,
        )


class PreviewMaterialFact(ReviewModel):
    """Filesystem-free media facts supplied to the detached simulator."""

    material_id: Annotated[
        str,
        Field(pattern=r"^source_[0-9a-f]{16}$"),
    ]
    media_kind: Literal["video", "audio", "image"]
    duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def video_dimensions_are_complete(self) -> PreviewMaterialFact:
        if self.media_kind == "video" and (
            self.width is None or self.height is None
        ):
            raise ValueError("Video preview facts require width and height")
        if self.media_kind in {"video", "audio"} and self.duration_seconds is None:
            raise ValueError("Video/audio preview facts require duration")
        if self.media_kind == "image" and (
            self.width is None or self.height is None
        ):
            raise ValueError("Image preview facts require width and height")
        if (self.width is None) != (self.height is None):
            raise ValueError("Material width and height must be paired")
        return self


class PlanDiffRequest(ReviewModel):
    schema_name: Literal["vistora.plan-diff-request"] = (
        "vistora.plan-diff-request"
    )
    request_id: StableId
    snapshot_ref: TimelineSnapshotReference
    director_plan: DirectorPlan
    proposed_execution: ProposedEditingExecutionPlan
    registry_ref: RegistrySchemaReference
    material_facts: tuple[PreviewMaterialFact, ...] = ()

    @model_validator(mode="after")
    def linkage_is_exact(self) -> PlanDiffRequest:
        if (
            self.snapshot_ref.snapshot_id is None
            or self.snapshot_ref.timeline_digest is None
        ):
            raise ValueError(
                "Plan diff request requires an exact snapshot ID and digest"
            )
        if self.proposed_execution.director_plan != self.director_plan:
            raise ValueError(
                "Proposed execution crosses Director plan content"
            )
        if self.proposed_execution.project_id != self.snapshot_ref.project_id:
            raise ValueError(
                "Proposed execution crosses snapshot project identity"
            )
        material_ids = [fact.material_id for fact in self.material_facts]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("Preview material fact IDs must be unique")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class PreviewAudioDuckingState(ReviewModel):
    ducking_id: StableId
    key_track_ids: tuple[StableId, ...]
    key_timeline_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reduction_db: FiniteFloat
    attack_seconds: FiniteFloat
    release_seconds: FiniteFloat


class PreviewClipState(ReviewModel):
    clip_id: str = Field(min_length=1)
    visual_kind: Literal["video", "image", "sticker"] = "video"
    track_key: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    order_index: int = Field(ge=0)
    source_id: StableId
    source_name: str = Field(min_length=1)
    trim_in_seconds: FiniteFloat = Field(ge=0)
    trim_out_seconds: FiniteFloat = Field(gt=0)
    timeline_start_seconds: FiniteFloat = Field(ge=0)
    timeline_end_seconds: FiniteFloat = Field(ge=0)
    effective_duration_seconds: FiniteFloat = Field(ge=0)
    volume: FiniteFloat | None = None
    speed_factor: FiniteFloat = Field(gt=0)
    keep_audio: bool
    reverse: bool
    freeze_frame_source_time_seconds: FiniteFloat | None = None
    freeze_frame_duration_seconds: FiniteFloat | None = None
    rotate_degrees: int
    link_group_id: StableId | None = None
    audio_gain_db: FiniteFloat = 0
    audio_content_role: Literal[
        "unspecified", "dialogue", "voiceover", "background_music",
        "sound_effect", "ambience",
    ] = "unspecified"
    audio_muted: bool = False
    audio_pan: FiniteFloat = 0
    audio_fade_in_seconds: FiniteFloat = 0
    audio_fade_out_seconds: FiniteFloat = 0
    audio_envelope: tuple[tuple[str, FiniteFloat, FiniteFloat], ...] = ()
    loudness_analysis_id: StableId | None = None
    audio_ducking: PreviewAudioDuckingState | None = None
    transform: ClipTransformSnapshot = Field(default_factory=ClipTransformSnapshot)
    color: ClipColorSnapshot = Field(default_factory=ClipColorSnapshot)
    visual_automations: tuple[dict[str, Any], ...] = ()
    masks: tuple[dict[str, Any], ...] = ()
    composite: dict[str, Any] = Field(default_factory=lambda: {"blend_mode": "normal"})
    mask_digest: Sha256Digest = (
        "sha256:e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )
    automation_digest: Sha256Digest = (
        "sha256:e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )
    provisional: bool = False


class PreviewProjectSettings(ReviewModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)


class PreviewTrackMixState(ReviewModel):
    track_id: StableId
    gain_db: FiniteFloat
    muted: bool
    pan: FiniteFloat


class PreviewSubtitleCueState(ReviewModel):
    cue_id: StableId
    track_id: StableId
    cue_kind: Literal["subtitle", "title"] = "subtitle"
    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat = Field(gt=0)
    text: str = Field(min_length=1)
    language: str = Field(min_length=2)
    speaker: str | None = None
    enabled: bool
    style: dict[str, Any] | None = None
    words: tuple[dict[str, Any], ...] = ()


class PreviewSubtitleTrackState(ReviewModel):
    track_id: StableId
    kind: Literal["subtitle", "text"]
    role: str
    language: str
    order: int = Field(ge=0)
    enabled: bool
    locked: bool
    allow_overlaps: bool
    style: dict[str, Any]
    cue_count: int = Field(ge=0)


class PreviewTransitionState(ReviewModel):
    transition_id: StableId
    track_id: StableId
    from_clip_id: StableId
    to_clip_id: StableId
    media_type: Literal["video", "audio"]
    kind: str = Field(min_length=1)
    duration_seconds: FiniteFloat = Field(ge=0, le=10)
    alignment: Literal["centered", "start_at_cut", "end_at_cut"]
    direction: Literal["left", "right", "up", "down"] | None = None
    color: str | None = None
    enabled: bool
    audio_policy: Literal[
        "none", "linked_audio", "explicit_audio_transition"
    ]
    paired_transition_id: StableId | None = None


class ProposedEntityReference(ReviewModel):
    entity_kind: Literal[
        "clip", "track", "subtitle_track", "subtitle_cue", "transition", "project", "media_output", "none"
    ]
    entity_id: str = Field(min_length=1)
    track_key: str | None = None
    track_id: str | None = None


class PlanChange(ReviewModel):
    schema_name: Literal["vistora.plan-change"] = "vistora.plan-change"
    change_id: StableId
    sequence: int = Field(ge=1)
    category: Literal[
        "clip_addition",
        "clip_removal",
        "clip_trim",
        "clip_timing",
        "clip_reorder",
        "clip_speed",
        "clip_properties",
        "clip_freeze_frame",
        "clip_transform",
        "clip_color",
        "visual_automation",
        "clip_mask",
        "clip_composite",
        "clip_linkage",
        "clip_audio",
        "audio_envelope",
        "audio_ducking",
        "track_mix",
        "audio_analysis",
        "track_management",
        "subtitle_track",
        "subtitle_cue_addition",
        "subtitle_cue_removal",
        "subtitle_cue_change",
        "subtitle_import",
        "subtitle_export",
        "transition_addition",
        "transition_removal",
        "transition_change",
        "project_settings",
        "export_only",
        "media_output",
        "warning",
    ]
    effect_kind: Literal["direct", "consequential", "informational"]
    severity: Literal["info", "warning", "blocker"]
    operation_id: StableId
    step_id: StableId
    tool_name: StableId
    director_rationale: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    entity: ProposedEntityReference
    before: PreviewClipState | None = None
    after: PreviewClipState | None = None
    before_project: PreviewProjectSettings | None = None
    after_project: PreviewProjectSettings | None = None
    before_track_mix: PreviewTrackMixState | None = None
    after_track_mix: PreviewTrackMixState | None = None
    before_subtitle_cue: PreviewSubtitleCueState | None = None
    after_subtitle_cue: PreviewSubtitleCueState | None = None
    before_subtitle_track: PreviewSubtitleTrackState | None = None
    after_subtitle_track: PreviewSubtitleTrackState | None = None
    before_transition: PreviewTransitionState | None = None
    after_transition: PreviewTransitionState | None = None
    reason: str = Field(min_length=1)
    evidence: tuple[EvidenceSummary, ...] = ()
    current_provenance: ClipProvenanceSummary | None = None

    @model_validator(mode="after")
    def before_after_matches_category(self) -> PlanChange:
        if self.category == "clip_addition":
            if (
                self.entity.entity_kind != "clip"
                or self.before is not None
                or self.after is None
            ):
                raise ValueError(
                    "Clip addition requires only an after clip state"
                )
        if self.category == "clip_removal":
            if (
                self.entity.entity_kind != "clip"
                or self.before is None
                or self.after is not None
            ):
                raise ValueError(
                    "Clip removal requires only a before clip state"
                )
        if self.category.startswith("clip_") and self.category not in {
            "clip_addition",
            "clip_removal",
        }:
            if (
                self.entity.entity_kind != "clip"
                or self.before is None
                or self.after is None
            ):
                raise ValueError(
                    "Clip modification requires before and after states"
                )
        if self.category == "project_settings":
            if (
                self.entity.entity_kind != "project"
                or self.before_project is None
                or self.after_project is None
                or self.before is not None
                or self.after is not None
            ):
                raise ValueError(
                    "Project settings change requires project before/after"
                )
        elif (
            self.before_project is not None
            or self.after_project is not None
        ):
            raise ValueError(
                "Only project settings changes carry project before/after"
            )
        if self.category == "subtitle_cue_addition" and (
            self.entity.entity_kind != "subtitle_cue"
            or self.before_subtitle_cue is not None
            or self.after_subtitle_cue is None
        ):
            raise ValueError("Subtitle cue addition requires only an after state")
        if self.category == "subtitle_cue_removal" and (
            self.entity.entity_kind != "subtitle_cue"
            or self.before_subtitle_cue is None
            or self.after_subtitle_cue is not None
        ):
            raise ValueError("Subtitle cue removal requires only a before state")
        if self.category == "subtitle_cue_change" and (
            self.entity.entity_kind != "subtitle_cue"
            or self.before_subtitle_cue is None
            or self.after_subtitle_cue is None
        ):
            raise ValueError("Subtitle cue change requires before and after states")
        if self.category == "transition_addition" and (
            self.entity.entity_kind != "transition"
            or self.before_transition is not None
            or self.after_transition is None
        ):
            raise ValueError("Transition addition requires only an after state")
        if self.category == "transition_removal" and (
            self.entity.entity_kind != "transition"
            or self.before_transition is None
            or self.after_transition is not None
        ):
            raise ValueError("Transition removal requires only a before state")
        if self.category == "transition_change" and (
            self.entity.entity_kind != "transition"
            or self.before_transition is None
            or self.after_transition is None
        ):
            raise ValueError("Transition change requires before and after states")
        return self


class PlanStepPreview(ReviewModel):
    step_id: StableId
    operation_id: StableId
    tool_name: StableId
    status: Literal["previewed", "warning", "unsupported"]
    change_ids: tuple[StableId, ...] = ()
    message: str = Field(min_length=1)


class PlanDiffSummary(ReviewModel):
    total_changes: int = Field(ge=0)
    additions: int = Field(ge=0)
    removals: int = Field(ge=0)
    modifications: int = Field(ge=0)
    consequential: int = Field(ge=0)
    warnings: int = Field(ge=0)
    blockers: int = Field(ge=0)
    before_clip_count: int = Field(ge=0)
    after_clip_count: int = Field(ge=0)
    before_subtitle_cue_count: int = Field(default=0, ge=0)
    after_subtitle_cue_count: int = Field(default=0, ge=0)
    before_transition_count: int = Field(default=0, ge=0)
    after_transition_count: int = Field(default=0, ge=0)
    before_duration_seconds: FiniteFloat = Field(ge=0)
    after_duration_seconds: FiniteFloat = Field(ge=0)
    before_project: PreviewProjectSettings
    after_project: PreviewProjectSettings


class PlanDiffDocument(ReviewModel):
    schema_name: Literal["vistora.plan-diff"] = "vistora.plan-diff"
    diff_id: StableId
    request_digest: Sha256Digest
    snapshot_ref: TimelineSnapshotReference
    plan_ref: PlanReference
    execution_ref: ProposedExecutionReference
    registry_ref: RegistrySchemaReference
    review_status: Literal["ready", "warning", "blocked"]
    steps: tuple[PlanStepPreview, ...]
    changes: tuple[PlanChange, ...]
    summary: PlanDiffSummary

    @model_validator(mode="after")
    def structure_is_consistent(self) -> PlanDiffDocument:
        sequences = [change.sequence for change in self.changes]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError(
                "Plan changes must use contiguous deterministic sequence"
            )
        change_ids = [change.change_id for change in self.changes]
        if len(change_ids) != len(set(change_ids)):
            raise ValueError("Plan change IDs must be unique")
        known = set(change_ids)
        step_ids = [step.step_id for step in self.steps]
        operation_ids = [step.operation_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Plan diff step IDs must be unique")
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Plan diff operation IDs must be unique")
        change_by_id = {
            change.change_id: change for change in self.changes
        }
        flattened_change_ids: list[str] = []
        for step in self.steps:
            if len(step.change_ids) != len(set(step.change_ids)):
                raise ValueError("Step preview change IDs must be unique")
            if set(step.change_ids) - known:
                raise ValueError("Step preview references unknown changes")
            flattened_change_ids.extend(step.change_ids)
            for change_id in step.change_ids:
                change = change_by_id[change_id]
                if (
                    change.step_id != step.step_id
                    or change.operation_id != step.operation_id
                    or change.tool_name != step.tool_name
                ):
                    raise ValueError(
                        "Plan change crosses its proposed step identity"
                    )
        if flattened_change_ids != change_ids:
            raise ValueError(
                "Every plan change must belong to exactly one ordered step"
            )
        if self.summary.total_changes != len(self.changes):
            raise ValueError("Plan diff summary change count is inconsistent")
        blockers = sum(
            change.severity == "blocker" for change in self.changes
        )
        warnings = sum(
            change.severity == "warning" for change in self.changes
        )
        if (
            self.summary.blockers != blockers
            or self.summary.warnings != warnings
        ):
            raise ValueError("Plan diff warning summary is inconsistent")
        expected_status = (
            "blocked"
            if blockers
            else "warning"
            if warnings
            else "ready"
        )
        if self.review_status != expected_status:
            raise ValueError("Plan diff review status is inconsistent")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class PlanReviewEnvelope(ReviewModel):
    """Freshness wrapper returned to a browser without raw plan arguments."""

    schema_name: Literal["vistora.plan-review-envelope"] = (
        "vistora.plan-review-envelope"
    )
    review_state: Literal[
        "current",
        "stale",
        "invalid",
        "unavailable",
    ]
    diff: PlanDiffDocument | None = None
    diff_digest: Sha256Digest | None = None
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def state_has_expected_diff(self) -> PlanReviewEnvelope:
        if self.review_state == "current":
            if self.diff is None or self.diff_digest != self.diff.digest():
                raise ValueError("Current review requires an exact diff digest")
        elif self.diff is not None or self.diff_digest is not None:
            raise ValueError("Non-current review states cannot expose a diff")
        return self


def evidence_summaries(
    references: tuple[SourceEvidenceReference, ...],
) -> tuple[EvidenceSummary, ...]:
    return tuple(
        EvidenceSummary(
            evidence_id=evidence.evidence_id,
            material_id=evidence.material_id,
            locator_type=evidence.locator.locator_type,
            start_seconds=getattr(
                evidence.locator,
                "start_seconds",
                None,
            ),
            end_seconds=getattr(evidence.locator, "end_seconds", None),
            analysis_fact_id=evidence.analysis_fact_id,
        )
        for evidence in references
    )
