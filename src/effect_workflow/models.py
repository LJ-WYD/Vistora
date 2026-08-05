"""Provider-neutral contracts for reviewed AI packaging work."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from contracts import PlanReference, SourceEvidenceReference
from director import digest_json
from timeline_query import TimelineSnapshotReference


VERSION = "1.0.0"
Version = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(min_length=3, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
GENESIS_DIGEST = "sha256:" + ("0" * 64)
_PATH = re.compile(r"(?i)(?:[a-z]:\\|file://|/(?:Users|home|tmp|var)/)")
_SECRET = re.compile(
    r"(?i)(?:sk-[a-z0-9]{20,}|ghp_[a-z0-9]{20,}|api[_-]?key\s*[:=])"
)


class EffectModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Version = VERSION


class EffectTimeRange(EffectModel):
    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat = Field(gt=0)

    @model_validator(mode="after")
    def positive_range(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Effect time range must have positive duration")
        return self


class EffectObjectTarget(EffectModel):
    object_id: StableId
    description: str = Field(min_length=1, max_length=500)
    source_evidence_ids: tuple[StableId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_is_unique(self):
        if self.source_evidence_ids != tuple(sorted(set(self.source_evidence_ids))):
            raise ValueError("Object evidence IDs must be unique and ordered")
        return self


class EffectMaskReference(EffectModel):
    clip_id: StableId
    mask_id: StableId
    mask_digest: Digest


class EffectTrackingReference(EffectModel):
    analysis_id: StableId
    source_material_id: StableId
    source_digest: Digest
    analysis_digest: Digest
    status: Literal["ready", "stale", "failed"]


class EffectStyleReference(EffectModel):
    style_reference_id: StableId
    evidence: SourceEvidenceReference
    purpose: str = Field(min_length=1, max_length=500)


class EffectPromptSpecification(EffectModel):
    subject: str = Field(min_length=1, max_length=2000)
    scene: str = Field(min_length=1, max_length=2000)
    action: str = Field(min_length=1, max_length=2000)
    camera: str = Field(min_length=1, max_length=1000)
    lighting: str = Field(min_length=1, max_length=1000)
    style: str = Field(min_length=1, max_length=1000)
    negative_constraints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def prompt_is_safe(self):
        values = (
            self.subject,
            self.scene,
            self.action,
            self.camera,
            self.lighting,
            self.style,
            *self.negative_constraints,
        )
        if any(_PATH.search(value) or _SECRET.search(value) for value in values):
            raise ValueError("Effect prompt contains a path or secret")
        if len(self.negative_constraints) != len(set(self.negative_constraints)):
            raise ValueError("Negative constraints must be unique")
        return self


class EffectModelRequirement(EffectModel):
    capability_id: StableId
    modality: Literal["video", "image", "audio", "multimodal"]
    required_features: tuple[StableId, ...] = Field(min_length=1)
    preferred_model_class: str | None = Field(default=None, min_length=1)
    provider_id: None = None

    @model_validator(mode="after")
    def capabilities_are_ordered(self):
        if self.required_features != tuple(sorted(set(self.required_features))):
            raise ValueError("Required model features must be unique and ordered")
        return self


class EffectParameter(EffectModel):
    name: StableId
    value: str = Field(min_length=1, max_length=500)


class EffectIntent(EffectModel):
    schema_name: Literal["vistora.effect-intent"] = "vistora.effect-intent"
    intent_id: StableId
    project_id: StableId
    director_plan_ref: PlanReference
    rationale: str = Field(min_length=1, max_length=2000)
    desired_outcome: str = Field(min_length=1, max_length=2000)
    source_evidence: tuple[SourceEvidenceReference, ...] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def intent_evidence_is_unique(self):
        ids = [item.evidence_id for item in self.source_evidence]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("Effect intent evidence must be unique and ordered")
        return self

    def digest(self):
        return digest_json(self.model_dump(mode="json"))


class EffectTask(EffectModel):
    schema_name: Literal["vistora.effect-task"] = "vistora.effect-task"
    task_id: StableId
    intent_id: StableId
    capability_id: StableId
    shot_id: StableId
    track_id: StableId
    clip_id: StableId
    timeline_range: EffectTimeRange
    object_target: EffectObjectTarget
    mask_ref: EffectMaskReference | None = None
    tracking_ref: EffectTrackingReference | None = None
    style_references: tuple[EffectStyleReference, ...] = ()
    prompt: EffectPromptSpecification
    model_requirement: EffectModelRequirement
    parameters: tuple[EffectParameter, ...] = ()
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    output_role: Literal["video_clip", "transparent_layer", "effect_layer"]
    cost_limit: FiniteFloat | None = Field(default=None, ge=0)
    time_limit_seconds: FiniteFloat | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def task_is_exact(self):
        if self.capability_id != self.model_requirement.capability_id:
            raise ValueError("Effect capability and model requirement drifted")
        if self.tracking_ref is not None and self.tracking_ref.status != "ready":
            raise ValueError("Effect task cannot bind stale/failed tracking")
        style_ids = [item.style_reference_id for item in self.style_references]
        if style_ids != sorted(style_ids) or len(style_ids) != len(set(style_ids)):
            raise ValueError("Style references must be unique and ordered")
        parameter_names = [item.name for item in self.parameters]
        if parameter_names != sorted(parameter_names) or len(parameter_names) != len(set(parameter_names)):
            raise ValueError("Effect parameters must be unique and ordered")
        if len(self.acceptance_criteria) != len(set(self.acceptance_criteria)):
            raise ValueError("Effect acceptance criteria must be unique")
        evidence_ids = {
            reference.evidence.evidence_id for reference in self.style_references
        }
        if not set(self.object_target.source_evidence_ids).isdisjoint(evidence_ids):
            raise ValueError("Object and style evidence roles are ambiguous")
        return self


class EffectProductionPlan(EffectModel):
    schema_name: Literal["vistora.effect-production-plan"] = (
        "vistora.effect-production-plan"
    )
    effect_plan_id: StableId
    plan_version: int = Field(ge=1)
    intent: EffectIntent
    snapshot_ref: TimelineSnapshotReference
    tasks: tuple[EffectTask, ...] = Field(min_length=1)
    global_acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def plan_is_exact(self):
        if self.intent.project_id != self.snapshot_ref.project_id:
            raise ValueError("Effect plan crosses project")
        task_ids = [task.task_id for task in self.tasks]
        if task_ids != sorted(task_ids) or len(task_ids) != len(set(task_ids)):
            raise ValueError("Effect task IDs must be unique and ordered")
        if any(task.intent_id != self.intent.intent_id for task in self.tasks):
            raise ValueError("Effect task crosses intent")
        evidence_ids = {item.evidence_id for item in self.intent.source_evidence}
        for task in self.tasks:
            used = set(task.object_target.source_evidence_ids) | {
                item.evidence.evidence_id for item in task.style_references
            }
            if not used.issubset(evidence_ids):
                raise ValueError("Effect task references unbound evidence")
        encoded = self.model_dump_json()
        if _PATH.search(encoded) or _SECRET.search(encoded):
            raise ValueError("Effect plan contains a path or secret")
        return self

    def digest(self):
        return digest_json(self.model_dump(mode="json"))


class EffectPlanChange(EffectModel):
    change_id: StableId
    change_type: Literal["added", "removed", "changed"]
    task_id: StableId
    before_digest: Digest | None = None
    after_digest: Digest | None = None
    summary: str = Field(min_length=1)


class EffectPlanReview(EffectModel):
    schema_name: Literal["vistora.effect-plan-review"] = (
        "vistora.effect-plan-review"
    )
    review_id: StableId
    effect_plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Digest
    snapshot_ref: TimelineSnapshotReference
    changes: tuple[EffectPlanChange, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    review_digest: Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def review_is_exact(self):
        payload = self.model_dump(mode="json", exclude={"review_digest"})
        if self.review_digest != digest_json(payload):
            raise ValueError("Effect review digest mismatched")
        return self


class EffectPlanConfirmation(EffectModel):
    schema_name: Literal["vistora.effect-plan-confirmation"] = (
        "vistora.effect-plan-confirmation"
    )
    confirmation_id: StableId
    effect_plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Digest
    review_id: StableId
    review_digest: Digest
    snapshot_ref: TimelineSnapshotReference
    decision: Literal["confirmed", "rejected"]
    confirmed_by: StableId
    recorded_at: AwareDatetime


class EffectPlanEvent(EffectModel):
    schema_name: Literal["vistora.effect-plan-event"] = "vistora.effect-plan-event"
    sequence: int = Field(ge=1)
    event_id: StableId
    event_type: Literal["reviewed", "confirmed", "rejected"]
    plan: EffectProductionPlan | None = None
    review: EffectPlanReview | None = None
    confirmation: EffectPlanConfirmation | None = None
    recorded_at: AwareDatetime
    previous_event_digest: Digest
    event_digest: Digest

    @model_validator(mode="after")
    def event_is_exact(self):
        if self.event_type == "reviewed":
            if self.plan is None or self.review is None or self.confirmation is not None:
                raise ValueError("Reviewed effect event payload is invalid")
            if (
                self.review.effect_plan_id != self.plan.effect_plan_id
                or self.review.plan_version != self.plan.plan_version
                or self.review.plan_digest != self.plan.digest()
                or self.review.snapshot_ref != self.plan.snapshot_ref
            ):
                raise ValueError("Effect review linkage drifted")
        elif self.confirmation is None or self.plan is not None or self.review is not None:
            raise ValueError("Effect decision event payload is invalid")
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Effect event digest mismatched")
        return self


class EffectPlanLedger(EffectModel):
    schema_name: Literal["vistora.effect-plan-ledger"] = "vistora.effect-plan-ledger"
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[EffectPlanEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, *, project_id: str):
        return cls(project_id=project_id, revision=0, events=(), integrity_digest=digest_json([]))

    @model_validator(mode="after")
    def ledger_is_exact(self):
        if self.revision != len(self.events):
            raise ValueError("Effect ledger revision is invalid")
        previous = GENESIS_DIGEST
        reviews: dict[str, EffectPlanReview] = {}
        decided: set[str] = set()
        for sequence, event in enumerate(self.events, start=1):
            if event.sequence != sequence or event.previous_event_digest != previous:
                raise ValueError("Effect ledger digest chain is broken")
            previous = event.event_digest
            if event.review is not None:
                if event.review.review_id in reviews:
                    raise ValueError("Effect review is duplicated")
                reviews[event.review.review_id] = event.review
            else:
                confirmation = event.confirmation
                assert confirmation is not None
                review = reviews.get(confirmation.review_id)
                if review is None or confirmation.review_id in decided:
                    raise ValueError("Effect decision is unknown or duplicated")
                if (
                    confirmation.effect_plan_id != review.effect_plan_id
                    or confirmation.plan_version != review.plan_version
                    or confirmation.plan_digest != review.plan_digest
                    or confirmation.review_digest != review.review_digest
                    or confirmation.snapshot_ref != review.snapshot_ref
                ):
                    raise ValueError("Effect confirmation binding drifted")
                decided.add(confirmation.review_id)
        if self.integrity_digest != digest_json([item.event_digest for item in self.events]):
            raise ValueError("Effect ledger integrity digest mismatched")
        return self


class EffectPlanView(EffectModel):
    schema_name: Literal["vistora.effect-plan-view"] = "vistora.effect-plan-view"
    project_id: StableId
    revision: int = Field(ge=0)
    state: Literal["empty", "reviewable", "confirmed", "rejected"]
    plans: tuple[dict[str, Any], ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    provider_status: Literal["not_configured"] = "not_configured"
    limitation: str = "O27 defines tasks and confirmation only; it invokes no provider."
