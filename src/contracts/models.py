from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Mapping

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from core.timeline import (
    AppliedLoudnessNormalization,
    ClipColorAdjustment,
    ClipTransform,
    SubtitleCue,
    SubtitleStyle,
    TimelineConfig,
    TimelineTransition,
    VisualAutomation,
    VisualKeyframe,
    VisualPropertyPath,
)


CONTRACT_VERSION = "1.0.0"
ContractVersion = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validated_json_object(value: dict[str, Any]) -> dict[str, Any]:
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must contain only JSON-serializable data") from exc
    return value


class ContractModel(BaseModel):
    """Strict, immutable-at-the-field-level base for versioned contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    schema_version: ContractVersion = CONTRACT_VERSION


class MediaTimeRangeLocator(ContractModel):
    """Bounded source-material time range used as creative evidence."""

    locator_type: Literal["media_time_range"] = "media_time_range"
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def range_is_forward(self) -> MediaTimeRangeLocator:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Evidence time range must be forward")
        return self


class WholeMaterialLocator(ContractModel):
    """Typed locator for evidence that applies to a whole material."""

    locator_type: Literal["whole_material"] = "whole_material"


SourceEvidenceLocator = Annotated[
    MediaTimeRangeLocator | WholeMaterialLocator,
    Field(discriminator="locator_type"),
]


class SourceEvidenceReference(ContractModel):
    """Opaque verifiable source evidence without a filesystem path."""

    evidence_id: StableId
    material_id: Annotated[
        str,
        Field(pattern=r"^source_[0-9a-f]{16}$"),
    ]
    locator: SourceEvidenceLocator
    analysis_fact_id: StableId | None = None
    analysis_fact_digest: Sha256Digest | None = None
    description: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def analysis_fact_reference_is_complete(
        self,
    ) -> SourceEvidenceReference:
        if (self.analysis_fact_id is None) != (
            self.analysis_fact_digest is None
        ):
            raise ValueError(
                "Analysis fact ID and digest must be provided together"
            )
        return self


class DirectorOperation(ContractModel):
    """One proposed atomic operation in a Director-authored creative plan."""

    operation_id: StableId
    tool_name: StableId
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)
    evidence_ids: tuple[StableId, ...] = ()

    _arguments_are_json = field_validator("arguments")(_validated_json_object)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> DirectorOperation:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Director operation evidence IDs must be unique")
        return self


class DirectorPlan(ContractModel):
    """A versioned creative plan authored by the production Director Agent."""

    schema_name: Literal["vistora.director-plan"] = "vistora.director-plan"
    plan_id: StableId
    plan_version: int = Field(ge=1)
    created_at: AwareDatetime = Field(default_factory=_utc_now)
    objective: str = Field(min_length=1)
    requirements: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    creative_direction: dict[str, Any] = Field(default_factory=dict)
    source_evidence: tuple[SourceEvidenceReference, ...] = ()
    operations: tuple[DirectorOperation, ...] = Field(min_length=1)
    outputs: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    _creative_direction_is_json = field_validator("creative_direction")(
        _validated_json_object
    )

    @model_validator(mode="after")
    def operation_ids_are_unique(self) -> DirectorPlan:
        operation_ids = [operation.operation_id for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Director operation IDs must be unique")
        evidence_ids = [
            evidence.evidence_id for evidence in self.source_evidence
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Director source evidence IDs must be unique")
        known_evidence = set(evidence_ids)
        for operation in self.operations:
            unknown = set(operation.evidence_ids) - known_evidence
            if unknown:
                raise ValueError(
                    f"Director operation {operation.operation_id} references "
                    f"unknown evidence IDs: {sorted(unknown)}"
                )
        return self

    def digest(self) -> str:
        """Return the canonical digest bound by a confirmation record."""

        payload = self.model_dump(mode="json")
        if not self.source_evidence:
            payload.pop("source_evidence", None)
        for operation in payload["operations"]:
            if not operation["evidence_ids"]:
                operation.pop("evidence_ids", None)
        encoded = _canonical_json(payload).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class PlanReference(ContractModel):
    """Stable reference to one immutable Director plan version and content."""

    plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Sha256Digest

    @classmethod
    def from_plan(cls, plan: DirectorPlan) -> PlanReference:
        return cls(
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            plan_digest=plan.digest(),
        )

    def matches(self, plan: DirectorPlan) -> bool:
        return self == self.from_plan(plan)


class UserConfirmationRecord(ContractModel):
    """Immutable record of a user's decision about one exact plan version."""

    schema_name: Literal["vistora.user-confirmation"] = (
        "vistora.user-confirmation"
    )
    confirmation_id: StableId
    plan_ref: PlanReference
    decision: Literal["confirmed", "rejected"]
    confirmed_by: str = Field(min_length=1)
    recorded_at: AwareDatetime = Field(default_factory=_utc_now)

    @classmethod
    def for_plan(
        cls,
        *,
        confirmation_id: str,
        plan: DirectorPlan,
        confirmed_by: str,
        decision: Literal["confirmed", "rejected"] = "confirmed",
        recorded_at: datetime | None = None,
    ) -> UserConfirmationRecord:
        values: dict[str, Any] = {
            "confirmation_id": confirmation_id,
            "plan_ref": PlanReference.from_plan(plan),
            "decision": decision,
            "confirmed_by": confirmed_by,
        }
        if recorded_at is not None:
            values["recorded_at"] = recorded_at
        return cls(**values)

    def confirms(self, plan: DirectorPlan) -> bool:
        return self.decision == "confirmed" and self.plan_ref.matches(plan)


class EditingStep(ContractModel):
    """Mechanical tool dispatch copied from one Director operation."""

    step_id: StableId
    source_operation_id: StableId
    tool_name: StableId
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[StableId, ...] = ()

    _arguments_are_json = field_validator("arguments")(_validated_json_object)

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> EditingStep:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Editing step evidence IDs must be unique")
        return self


class EditingExecutionPlan(ContractModel):
    """A constrained Editing Agent handoff for one confirmed Director plan."""

    schema_name: Literal["vistora.editing-execution-plan"] = (
        "vistora.editing-execution-plan"
    )
    execution_id: StableId
    project_id: StableId
    director_plan: DirectorPlan
    confirmation: UserConfirmationRecord | None = None
    steps: tuple[EditingStep, ...] = Field(min_length=1)
    created_at: AwareDatetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def require_exact_confirmed_plan(self) -> EditingExecutionPlan:
        if self.confirmation is None:
            raise ValueError("Editing execution requires a user confirmation")
        if not self.confirmation.confirms(self.director_plan):
            raise ValueError(
                "User confirmation must confirm this exact plan ID, version, "
                "and digest"
            )

        operations = {
            operation.operation_id: operation
            for operation in self.director_plan.operations
        }
        source_ids = [step.source_operation_id for step in self.steps]
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Editing step IDs must be unique")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Each Director operation may be referenced once")
        if set(source_ids) != set(operations):
            raise ValueError(
                "Editing steps must reference every Director operation exactly once"
            )

        for step in self.steps:
            operation = operations[step.source_operation_id]
            if step.tool_name != operation.tool_name:
                raise ValueError(
                    f"Editing step {step.step_id} changes the confirmed tool"
                )
            if _canonical_json(step.arguments) != _canonical_json(
                operation.arguments
            ):
                raise ValueError(
                    f"Editing step {step.step_id} changes confirmed arguments"
                )
            if step.evidence_ids != operation.evidence_ids:
                raise ValueError(
                    f"Editing step {step.step_id} changes confirmed evidence"
                )
        return self

    @classmethod
    def from_confirmed_plan(
        cls,
        *,
        execution_id: str,
        project_id: str,
        director_plan: DirectorPlan,
        confirmation: UserConfirmationRecord,
    ) -> EditingExecutionPlan:
        steps = tuple(
            EditingStep(
                step_id=operation.operation_id,
                source_operation_id=operation.operation_id,
                tool_name=operation.tool_name,
                arguments=operation.arguments,
                evidence_ids=operation.evidence_ids,
            )
            for operation in director_plan.operations
        )
        return cls(
            execution_id=execution_id,
            project_id=project_id,
            director_plan=director_plan,
            confirmation=confirmation,
            steps=steps,
        )


class ManualSubtitleRipplePolicy(ContractModel):
    schema_name: Literal["vistora.manual-subtitle-ripple-policy"] = (
        "vistora.manual-subtitle-ripple-policy"
    )
    mode: Literal["none", "selected_subtitle_tracks", "all_unlocked"] = "none"
    selected_track_ids: tuple[StableId, ...] = ()

    @model_validator(mode="after")
    def exact_selection(self) -> "ManualSubtitleRipplePolicy":
        if self.mode == "selected_subtitle_tracks" and not self.selected_track_ids:
            raise ValueError("Selected subtitle ripple requires track IDs")
        if self.mode != "selected_subtitle_tracks" and self.selected_track_ids:
            raise ValueError("Only selected subtitle ripple accepts track IDs")
        if len(self.selected_track_ids) != len(set(self.selected_track_ids)):
            raise ValueError("Subtitle ripple track IDs must be unique")
        if self.selected_track_ids != tuple(sorted(self.selected_track_ids)):
            raise ValueError("Subtitle ripple track IDs must use stable ordering")
        return self


class ManualClipUpdate(ContractModel):
    """User-authored timing/order replacement for one existing video clip."""

    operation_id: StableId
    kind: Literal["update"] = "update"
    track_key: str = Field("video", min_length=1)
    track_id: StableId | None = None
    clip_id: str = Field(min_length=1)
    trim_in_seconds: float = Field(ge=0, allow_inf_nan=False)
    trim_out_seconds: float = Field(gt=0, allow_inf_nan=False)
    timeline_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    order_index: int = Field(ge=0)
    ripple: bool = False
    subtitle_ripple: ManualSubtitleRipplePolicy = Field(
        default_factory=ManualSubtitleRipplePolicy
    )
    edit_scope: Literal["current_clip", "linked_group"] = "current_clip"

    @model_validator(mode="after")
    def trim_range_is_valid(self) -> ManualClipUpdate:
        if self.trim_out_seconds <= self.trim_in_seconds:
            raise ValueError("Manual clip trim-out must be after trim-in")
        return self


class ManualClipRemove(ContractModel):
    """User-authored removal of one existing video clip."""

    operation_id: StableId
    kind: Literal["remove"] = "remove"
    track_key: str = Field("video", min_length=1)
    track_id: StableId | None = None
    clip_id: str = Field(min_length=1)
    mode: Literal["lift", "ripple"] = "lift"
    edit_scope: Literal["current_clip", "linked_group"] = "current_clip"
    subtitle_ripple: ManualSubtitleRipplePolicy = Field(
        default_factory=ManualSubtitleRipplePolicy
    )


class ManualClipSplit(ContractModel):
    """User-authored split of one exact existing video clip."""

    operation_id: StableId
    kind: Literal["split"] = "split"
    track_key: str = Field("video", min_length=1)
    track_id: StableId | None = None
    clip_id: str = Field(min_length=1)
    split_at_seconds: float = Field(gt=0, allow_inf_nan=False)
    right_clip_id: StableId
    edit_scope: Literal["current_clip", "linked_group"] = "current_clip"


class ManualClipReference(ContractModel):
    track_key: str = Field(min_length=1)
    track_id: StableId
    clip_id: str = Field(min_length=1)


class ManualClipLink(ContractModel):
    """User-authored explicit link/unlink operation; never inferred."""

    operation_id: StableId
    kind: Literal["link"] = "link"
    action: Literal["link", "unlink"]
    members: tuple[ManualClipReference, ...] = Field(min_length=1)
    link_group_id: StableId | None = None

    @model_validator(mode="after")
    def link_is_explicit(self) -> "ManualClipLink":
        if self.action == "link" and (
            len(self.members) < 2 or self.link_group_id is None
        ):
            raise ValueError("Link requires two members and link_group_id")
        if self.action == "unlink" and self.link_group_id is not None:
            raise ValueError("Unlink does not accept link_group_id")
        return self


class ManualTrackManage(ContractModel):
    """Small manual track-state/reorder proposal."""

    operation_id: StableId
    kind: Literal["manage_track"] = "manage_track"
    track_key: str = Field(min_length=1)
    track_id: StableId
    action: Literal["update", "reorder"]
    role: str | None = Field(default=None, min_length=1, max_length=80)
    order: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    muted: bool | None = None
    locked: bool | None = None

    @model_validator(mode="after")
    def management_fields(self) -> "ManualTrackManage":
        if self.action == "reorder" and self.order is None:
            raise ValueError("Track reorder requires order")
        if self.action == "update" and all(
            value is None
            for value in (
                self.role,
                self.order,
                self.enabled,
                self.muted,
                self.locked,
            )
        ):
            raise ValueError("Track update requires a property")
        return self


class ManualClipAudio(ContractModel):
    """User-authored exact clip audio-property proposal."""

    operation_id: StableId
    kind: Literal["clip_audio"] = "clip_audio"
    track_key: str = Field(min_length=1)
    track_id: StableId
    clip_id: StableId
    gain_db: float | None = Field(default=None, ge=-60, le=24)
    muted: bool | None = None
    pan: float | None = Field(default=None, ge=-1, le=1)
    fade_in_seconds: float | None = Field(default=None, ge=0)
    fade_out_seconds: float | None = Field(default=None, ge=0)
    playback_rate: float | None = Field(default=None, gt=0, le=16)
    normalization_evidence: AppliedLoudnessNormalization | None = None

    @model_validator(mode="after")
    def has_change(self) -> "ManualClipAudio":
        if all(
            value is None
            for value in (
                self.gain_db,
                self.muted,
                self.pan,
                self.fade_in_seconds,
                self.fade_out_seconds,
                self.playback_rate,
                self.normalization_evidence,
            )
        ):
            raise ValueError("Manual clip audio edit requires a property")
        return self


class ManualClipVisual(ContractModel):
    """Detached visual edit for one exact video clip only."""

    operation_id: StableId
    kind: Literal["clip_visual"] = "clip_visual"
    track_key: str = Field(min_length=1)
    track_id: StableId
    clip_id: StableId
    action: Literal["set", "reset"] = "set"
    transform: ClipTransform | None = None
    color: ClipColorAdjustment | None = None
    components: Literal["transform", "color", "both"] = "both"

    @model_validator(mode="after")
    def exact_visual_payload(self) -> "ManualClipVisual":
        if self.action == "reset":
            if self.transform is not None or self.color is not None:
                raise ValueError("Visual reset accepts no property payload")
            return self
        if self.components in {"transform", "both"} and self.transform is None:
            raise ValueError("Visual set requires transform values")
        if self.components in {"color", "both"} and self.color is None:
            raise ValueError("Visual set requires color values")
        if self.components == "transform" and self.color is not None:
            raise ValueError("Transform-only edit cannot include color")
        if self.components == "color" and self.transform is not None:
            raise ValueError("Color-only edit cannot include transform")
        return self


class ManualCopyClipVisual(ContractModel):
    """Explicit user-authored visual copy with no link-group expansion."""

    operation_id: StableId
    kind: Literal["copy_clip_visual"] = "copy_clip_visual"
    source_track_id: StableId
    source_clip_id: StableId
    targets: tuple[ManualClipReference, ...] = Field(min_length=1, max_length=32)
    components: Literal["transform", "color", "both"] = "both"

    @model_validator(mode="after")
    def stable_targets(self) -> "ManualCopyClipVisual":
        identities = tuple((item.track_id, item.clip_id) for item in self.targets)
        if len(identities) != len(set(identities)):
            raise ValueError("Visual copy targets must be unique")
        if identities != tuple(sorted(identities)):
            raise ValueError("Visual copy targets must use stable ordering")
        if (self.source_track_id, self.source_clip_id) in identities:
            raise ValueError("Visual copy source cannot be a target")
        return self


class ManualTrackMix(ContractModel):
    operation_id: StableId
    kind: Literal["track_mix"] = "track_mix"
    track_key: str = Field(min_length=1)
    track_id: StableId
    gain_db: float | None = Field(default=None, ge=-60, le=24)
    muted: bool | None = None
    pan: float | None = Field(default=None, ge=-1, le=1)

    @model_validator(mode="after")
    def has_change(self) -> "ManualTrackMix":
        if self.gain_db is None and self.muted is None and self.pan is None:
            raise ValueError("Manual track mix edit requires a property")
        return self


class ManualVolumeEnvelope(ContractModel):
    operation_id: StableId
    kind: Literal["volume_envelope"] = "volume_envelope"
    track_key: str = Field(min_length=1)
    track_id: StableId
    clip_id: StableId
    action: Literal["upsert", "delete", "clear"]
    point_id: StableId | None = None
    offset_seconds: float | None = Field(default=None, ge=0)
    gain_db: float | None = Field(default=None, ge=-60, le=24)

    @model_validator(mode="after")
    def action_fields(self) -> "ManualVolumeEnvelope":
        if self.action == "upsert" and (
            self.point_id is None
            or self.offset_seconds is None
            or self.gain_db is None
        ):
            raise ValueError("Envelope upsert requires complete point fields")
        if self.action == "delete" and self.point_id is None:
            raise ValueError("Envelope delete requires point_id")
        if self.action == "clear" and any(
            value is not None
            for value in (self.point_id, self.offset_seconds, self.gain_db)
        ):
            raise ValueError("Envelope clear does not accept point fields")
        return self


class ManualSubtitleTrack(ContractModel):
    operation_id: StableId
    kind: Literal["subtitle_track"] = "subtitle_track"
    action: Literal["create", "update", "delete"]
    track_id: StableId
    track_kind: Literal["subtitle", "text"] | None = None
    role: str | None = Field(default=None, min_length=1, max_length=80)
    language: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    order: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    locked: bool | None = None
    allow_overlaps: bool | None = None
    style: SubtitleStyle | None = None

    @model_validator(mode="after")
    def action_fields(self) -> "ManualSubtitleTrack":
        values = (self.track_kind, self.role, self.language, self.order, self.enabled, self.locked, self.allow_overlaps, self.style)
        if self.action == "create" and self.track_kind is None:
            raise ValueError("Manual subtitle track create requires track_kind")
        if self.action == "update" and all(value is None for value in values):
            raise ValueError("Manual subtitle track update requires a property")
        if self.action == "delete" and any(value is not None for value in values):
            raise ValueError("Manual subtitle track delete accepts only track_id")
        return self


class ManualSubtitleCue(ContractModel):
    operation_id: StableId
    kind: Literal["subtitle_cue"] = "subtitle_cue"
    action: Literal[
        "add", "batch_add", "update", "split", "merge", "move", "trim",
        "ripple_shift", "delete", "set_style",
    ]
    track_id: StableId
    cue_id: StableId | None = None
    cues: tuple[SubtitleCue, ...] = ()
    text: str | None = Field(default=None, min_length=1, max_length=4096)
    language: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    speaker: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    split_at_seconds: float | None = Field(default=None, gt=0)
    right_cue_id: StableId | None = None
    merge_cue_ids: tuple[StableId, ...] = ()
    merged_cue_id: StableId | None = None
    timeline_start_seconds: float | None = Field(default=None, ge=0)
    anchor_seconds: float | None = Field(default=None, ge=0)
    delta_seconds: float | None = None
    style: SubtitleStyle | None = None

    @model_validator(mode="after")
    def action_fields(self) -> "ManualSubtitleCue":
        if self.action == "add" and len(self.cues) != 1:
            raise ValueError("Manual subtitle add requires one cue")
        if self.action == "batch_add" and not self.cues:
            raise ValueError("Manual subtitle batch add requires cues")
        if self.action in {"update", "split", "move", "trim", "delete", "set_style"} and self.cue_id is None:
            raise ValueError(f"Manual subtitle {self.action} requires cue_id")
        if self.action == "split" and (self.split_at_seconds is None or self.right_cue_id is None):
            raise ValueError("Manual subtitle split requires point and output ID")
        if self.action == "merge" and len(self.merge_cue_ids) < 2:
            raise ValueError("Manual subtitle merge requires two cues")
        if self.action == "move" and self.timeline_start_seconds is None:
            raise ValueError("Manual subtitle move requires timeline start")
        if self.action == "trim" and (self.start_seconds is None or self.end_seconds is None):
            raise ValueError("Manual subtitle trim requires a range")
        if self.action == "ripple_shift" and (self.anchor_seconds is None or self.delta_seconds is None):
            raise ValueError("Manual subtitle ripple requires anchor and delta")
        if self.action == "set_style" and self.style is None:
            raise ValueError("Manual subtitle style edit requires style")
        return self


class ManualTransitionCopyTarget(ContractModel):
    transition_id: StableId
    track_id: StableId
    from_clip_id: StableId
    to_clip_id: StableId
    paired_transition_id: StableId | None = None
    paired_track_id: StableId | None = None
    paired_from_clip_id: StableId | None = None
    paired_to_clip_id: StableId | None = None


class ManualTransitionEdit(ContractModel):
    """User-authored transition proposal; execution remains confirmed/atomic."""

    operation_id: StableId
    kind: Literal["transition"] = "transition"
    action: Literal["add", "update", "remove", "copy"]
    transition: TimelineTransition | None = None
    paired_transition: TimelineTransition | None = None
    transition_id: StableId | None = None
    source_transition_id: StableId | None = None
    targets: tuple[ManualTransitionCopyTarget, ...] = ()

    @model_validator(mode="after")
    def exact_action_payload(self) -> "ManualTransitionEdit":
        if self.action in {"add", "update"} and self.transition is None:
            raise ValueError("Transition add/update requires transition payload")
        if self.action == "remove" and self.transition_id is None:
            raise ValueError("Transition remove requires transition_id")
        if self.action == "copy" and (
            self.source_transition_id is None or not self.targets
        ):
            raise ValueError("Transition copy requires source and targets")
        if self.action != "copy" and self.targets:
            raise ValueError("Only transition copy accepts targets")
        return self


class ManualVisualAutomationEdit(ContractModel):
    """User-authored keyframe proposal; never a Director decision."""

    operation_id: StableId
    kind: Literal["visual_automation"] = "visual_automation"
    action: Literal[
        "upsert_keyframe",
        "delete_keyframe",
        "replace_curve",
        "clear_curve",
        "clear_all",
        "copy",
    ]
    track_key: str = Field(min_length=1)
    track_id: StableId
    clip_id: StableId
    automation_id: StableId | None = None
    property_path: VisualPropertyPath | None = None
    keyframe: VisualKeyframe | None = None
    keyframe_id: StableId | None = None
    automation: VisualAutomation | None = None
    targets: tuple[ManualClipReference, ...] = ()
    property_paths: tuple[VisualPropertyPath, ...] = ()

    @model_validator(mode="after")
    def exact_automation_action(self) -> "ManualVisualAutomationEdit":
        if self.action == "upsert_keyframe" and any(
            value is None
            for value in (self.automation_id, self.property_path, self.keyframe)
        ):
            raise ValueError("Keyframe upsert requires curve, property, and keyframe")
        if self.action == "delete_keyframe" and (
            self.automation_id is None or self.keyframe_id is None
        ):
            raise ValueError("Keyframe delete requires curve and keyframe IDs")
        if self.action == "replace_curve" and self.automation is None:
            raise ValueError("Curve replacement requires exact automation")
        if self.action == "clear_curve" and (
            (self.automation_id is None) == (self.property_path is None)
        ):
            raise ValueError("Curve clear requires exactly one selector")
        if self.action == "copy" and not self.targets:
            raise ValueError("Automation copy requires explicit target clips")
        if self.action != "copy" and (self.targets or self.property_paths):
            raise ValueError("Only automation copy accepts target selections")
        identities = tuple((item.track_id, item.clip_id) for item in self.targets)
        if len(identities) != len(set(identities)) or identities != tuple(sorted(identities)):
            raise ValueError("Automation copy targets must be stable and unique")
        if len(self.property_paths) != len(set(self.property_paths)) or self.property_paths != tuple(sorted(self.property_paths)):
            raise ValueError("Automation property selectors must be stable and unique")
        return self


ManualEditOperation = Annotated[
    ManualClipUpdate
    | ManualClipRemove
    | ManualClipSplit
    | ManualClipLink
    | ManualTrackManage
    | ManualClipAudio
    | ManualClipVisual
    | ManualCopyClipVisual
    | ManualTrackMix
    | ManualVolumeEnvelope
    | ManualSubtitleTrack
    | ManualSubtitleCue
    | ManualTransitionEdit
    | ManualVisualAutomationEdit,
    Field(discriminator="kind"),
]


class ManualEditProposal(ContractModel):
    """Detached user-authored edit proposal; it is not a Director plan."""

    schema_name: Literal["vistora.manual-edit-proposal"] = (
        "vistora.manual-edit-proposal"
    )
    proposal_id: StableId
    authored_by: str = Field(min_length=1)
    base_project_id: StableId
    base_revision: int = Field(ge=1)
    base_timeline_digest: Sha256Digest
    edits: tuple[ManualEditOperation, ...] = Field(min_length=1, max_length=32)
    created_at: AwareDatetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def edit_targets_are_unique(self) -> ManualEditProposal:
        operation_ids = [edit.operation_id for edit in self.edits]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Manual edit operation IDs must be unique")
        clip_targets = [
            (edit.track_key, edit.clip_id)
            for edit in self.edits
            if isinstance(
                edit,
                (ManualClipUpdate, ManualClipRemove, ManualClipSplit),
            )
        ]
        if len(clip_targets) != len(set(clip_targets)):
            raise ValueError(
                "A manual proposal may edit each clip at most once"
            )
        transition_targets: list[str] = []
        for edit in self.edits:
            if not isinstance(edit, ManualTransitionEdit):
                continue
            if edit.action in {"add", "update"}:
                transition_targets.append(edit.transition.transition_id)
                if edit.paired_transition is not None:
                    transition_targets.append(
                        edit.paired_transition.transition_id
                    )
            elif edit.action == "remove":
                transition_targets.append(edit.transition_id)
            else:
                transition_targets.extend(
                    target.transition_id for target in edit.targets
                )
                transition_targets.extend(
                    target.paired_transition_id
                    for target in edit.targets
                    if target.paired_transition_id is not None
                )
        if len(transition_targets) != len(set(transition_targets)):
            raise ValueError(
                "A manual proposal may target each transition at most once"
            )
        return self

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = _canonical_json(payload).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ManualEditProposalReference(ContractModel):
    """Stable reference to exact user-authored proposal content."""

    proposal_id: StableId
    proposal_digest: Sha256Digest

    @classmethod
    def from_proposal(
        cls,
        proposal: ManualEditProposal,
    ) -> ManualEditProposalReference:
        return cls(
            proposal_id=proposal.proposal_id,
            proposal_digest=proposal.digest(),
        )

    def matches(self, proposal: ManualEditProposal) -> bool:
        return self == self.from_proposal(proposal)


class ManualEditConfirmationRecord(ContractModel):
    """Explicit user decision bound to an exact manual edit proposal."""

    schema_name: Literal["vistora.manual-edit-confirmation"] = (
        "vistora.manual-edit-confirmation"
    )
    confirmation_id: StableId
    proposal_ref: ManualEditProposalReference
    decision: Literal["confirmed", "rejected"]
    confirmed_by: str = Field(min_length=1)
    recorded_at: AwareDatetime = Field(default_factory=_utc_now)

    @classmethod
    def for_proposal(
        cls,
        *,
        confirmation_id: str,
        proposal: ManualEditProposal,
        confirmed_by: str,
        decision: Literal["confirmed", "rejected"] = "confirmed",
        recorded_at: datetime | None = None,
    ) -> ManualEditConfirmationRecord:
        values: dict[str, Any] = {
            "confirmation_id": confirmation_id,
            "proposal_ref": ManualEditProposalReference.from_proposal(
                proposal
            ),
            "decision": decision,
            "confirmed_by": confirmed_by,
        }
        if recorded_at is not None:
            values["recorded_at"] = recorded_at
        return cls(**values)

    def confirms(self, proposal: ManualEditProposal) -> bool:
        return (
            self.decision == "confirmed"
            and self.proposal_ref.matches(proposal)
        )


class ManualEditChange(ContractModel):
    """Reviewable before/after diff for one manual edit operation."""

    operation_id: StableId
    target_kind: Literal[
        "clip", "track", "subtitle_track", "subtitle_cue", "transition", "automation"
    ] = "clip"
    track_key: str = Field(min_length=1)
    track_id: StableId | None = None
    clip_id: str = Field(min_length=1)
    action: Literal["update", "remove", "create"]
    effect_kind: Literal["direct", "consequential"] = "direct"
    before: dict[str, Any] | None
    after: dict[str, Any] | None

    _before_is_json = field_validator("before")(
        lambda value: (
            None if value is None else _validated_json_object(value)
        )
    )
    _after_is_json = field_validator("after")(
        lambda value: (
            None if value is None else _validated_json_object(value)
        )
    )

    @model_validator(mode="after")
    def before_after_match_action(self) -> ManualEditChange:
        valid = (
            self.action == "create"
            and self.before is None
            and self.after is not None
        ) or (
            self.action == "remove"
            and self.before is not None
            and self.after is None
        ) or (
            self.action == "update"
            and self.before is not None
            and self.after is not None
        )
        if not valid:
            raise ValueError(
                "Manual change before/after values do not match its action"
            )
        return self


class ManualEditReview(ContractModel):
    """Validated diff for a proposal against one exact snapshot."""

    schema_name: Literal["vistora.manual-edit-review"] = (
        "vistora.manual-edit-review"
    )
    proposal_ref: ManualEditProposalReference
    snapshot_id: StableId
    changes: tuple[ManualEditChange, ...] = Field(min_length=1)


class TimelineProjectDocument(ContractModel):
    """Versioned project envelope with deterministic legacy timeline migration."""

    schema_name: Literal["vistora.timeline-project"] = "vistora.timeline-project"
    project_id: StableId
    revision: int = Field(default=1, ge=1)
    timeline: TimelineConfig
    migration_source: Literal["native", "legacy.timeline.v0"] = "native"

    @model_validator(mode="before")
    @classmethod
    def wrap_legacy_timeline(cls, value: Any) -> Any:
        if isinstance(value, TimelineConfig):
            legacy_data = value.model_dump(mode="json")
        elif isinstance(value, dict):
            wrapper_keys = {
                "schema_name",
                "schema_version",
                "project_id",
                "revision",
                "timeline",
                "migration_source",
            }
            legacy_keys = {
                "width", "height", "fps", "tracks", "subtitle_tracks",
                "transitions",
            }
            if {
                "project_id",
                "timeline",
                "migration_source",
            }.intersection(value):
                return value
            if not set(value).issubset(legacy_keys | {"schema_version"}):
                return value
            legacy_data = value
        else:
            return value

        timeline = TimelineConfig.model_validate(legacy_data)
        canonical = _canonical_json(timeline.model_dump(mode="json"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return {
            "schema_name": "vistora.timeline-project",
            "schema_version": CONTRACT_VERSION,
            "project_id": f"project_legacy_{digest[:16]}",
            "revision": 1,
            "timeline": timeline,
            "migration_source": "legacy.timeline.v0",
        }


class AtomicToolRequestEnvelope(ContractModel):
    """Traceable request for one atomic tool mutation boundary."""

    schema_name: Literal["vistora.atomic-tool-request"] = (
        "vistora.atomic-tool-request"
    )
    request_id: StableId
    execution_id: StableId
    project_id: StableId
    confirmation_id: StableId
    plan_ref: PlanReference
    step_id: StableId
    tool_name: StableId
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: tuple[SourceEvidenceReference, ...] = ()
    requested_at: AwareDatetime = Field(default_factory=_utc_now)

    _arguments_are_json = field_validator("arguments")(_validated_json_object)

    @model_validator(mode="after")
    def evidence_references_are_unique(
        self,
    ) -> AtomicToolRequestEnvelope:
        evidence_ids = [
            evidence.evidence_id for evidence in self.evidence_refs
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Atomic request evidence IDs must be unique")
        return self

    @classmethod
    def from_execution_plan(
        cls,
        *,
        request_id: str,
        execution_plan: EditingExecutionPlan,
        step_id: str,
    ) -> AtomicToolRequestEnvelope:
        matching_steps = [
            step for step in execution_plan.steps if step.step_id == step_id
        ]
        if len(matching_steps) != 1:
            raise ValueError(f"Unknown or duplicate execution step: {step_id}")
        step = matching_steps[0]
        evidence_by_id = {
            evidence.evidence_id: evidence
            for evidence in execution_plan.director_plan.source_evidence
        }
        return cls(
            request_id=request_id,
            execution_id=execution_plan.execution_id,
            project_id=execution_plan.project_id,
            confirmation_id=execution_plan.confirmation.confirmation_id,
            plan_ref=PlanReference.from_plan(execution_plan.director_plan),
            step_id=step.step_id,
            tool_name=step.tool_name,
            arguments=step.arguments,
            evidence_refs=tuple(
                evidence_by_id[evidence_id]
                for evidence_id in step.evidence_ids
            ),
        )

    def validate_against_registry(
        self,
        registry: Mapping[str, Any],
    ) -> BaseModel:
        """Validate arguments with an existing BaseSkill input model."""

        skill = registry.get(self.tool_name)
        if skill is None:
            raise ValueError(f"Unknown atomic tool: {self.tool_name}")
        input_model = getattr(skill, "input_model", None)
        if not isinstance(input_model, type) or not issubclass(
            input_model, BaseModel
        ):
            raise TypeError(
                f"Registered tool {self.tool_name} has no Pydantic input model"
            )
        return input_model.model_validate(self.arguments)


class ToolError(ContractModel):
    """Structured atomic tool failure."""

    code: StableId
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    _details_are_json = field_validator("details")(_validated_json_object)


class AtomicToolResultEnvelope(ContractModel):
    """Traceable result corresponding to one atomic tool request."""

    schema_name: Literal["vistora.atomic-tool-result"] = (
        "vistora.atomic-tool-result"
    )
    result_id: StableId
    request_id: StableId
    execution_id: StableId
    step_id: StableId
    tool_name: StableId
    status: Literal["success", "error", "partial", "recovery_required"]
    payload: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    registry_digest: Sha256Digest | None = None
    replayed: bool = False
    started_at: AwareDatetime
    finished_at: AwareDatetime = Field(default_factory=_utc_now)

    _payload_is_json = field_validator("payload")(_validated_json_object)

    @model_validator(mode="after")
    def result_state_is_consistent(self) -> AtomicToolResultEnvelope:
        if self.finished_at < self.started_at:
            raise ValueError("Tool result cannot finish before it starts")
        if self.status == "success" and self.error is not None:
            raise ValueError("Successful tool results cannot include an error")
        if self.status != "success" and self.error is None:
            raise ValueError("Non-success tool results must include an error")
        return self
