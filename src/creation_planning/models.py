"""Versioned contracts for confirmed material-production planning."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from director import digest_json
from material_requirements import ConfirmedMaterialRequirements


CREATION_PLANNING_VERSION = "1.0.0"
Version = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GENESIS_DIGEST = "sha256:" + ("0" * 64)


class CreationPlanningModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: Version = CREATION_PLANNING_VERSION


class MaterialConfirmationReference(CreationPlanningModel):
    schema_name: Literal[
        "vistora.creation-planning.material-confirmation-reference"
    ] = "vistora.creation-planning.material-confirmation-reference"
    ledger_revision: int = Field(ge=1)
    confirmation_id: StableId
    requirements_plan_id: StableId
    requirements_plan_version: int = Field(ge=1)
    requirements_plan_digest: Digest
    requirements_review_digest: Digest
    brief_digest: Digest
    snapshot_digest: Digest

    @classmethod
    def from_confirmed(
        cls,
        confirmed: ConfirmedMaterialRequirements,
    ) -> MaterialConfirmationReference:
        proposal = confirmed.proposal
        return cls(
            ledger_revision=confirmed.ledger_revision,
            confirmation_id=confirmed.confirmation.confirmation_id,
            requirements_plan_id=proposal.plan.plan_id,
            requirements_plan_version=proposal.plan.plan_version,
            requirements_plan_digest=proposal.plan.digest(),
            requirements_review_digest=proposal.review.review_digest,
            brief_digest=proposal.plan.brief_ref.brief_digest,
            snapshot_digest=(
                proposal.plan.no_material_snapshot_ref.timeline_digest
            ),
        )


class CapabilityRequirement(CreationPlanningModel):
    capability_id: StableId
    capability_kind: Literal[
        "video_generation",
        "image_to_video_generation",
        "motion_graphics_generation",
        "image_generation",
        "audio_generation",
        "voice_synthesis",
        "music_generation",
        "capture",
        "manual_import",
        "asset_search",
        "user_material_request",
    ]
    required_features: tuple[str, ...] = ()
    availability: Literal[
        "available",
        "unconfigured",
        "unsupported",
        "unknown",
    ]
    limitation: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def availability_is_truthful(self) -> CapabilityRequirement:
        if self.availability == "available" and self.limitation is not None:
            raise ValueError("Available capability cannot carry a limitation")
        if self.availability != "available" and self.limitation is None:
            raise ValueError("Unavailable capability requires a limitation")
        if len(self.required_features) != len(set(self.required_features)):
            raise ValueError("Capability features must be unique")
        return self


class CapabilityRegistryReference(CreationPlanningModel):
    schema_name: Literal[
        "vistora.creation-planning.capability-registry-reference"
    ] = "vistora.creation-planning.capability-registry-reference"
    registry_id: StableId
    registry_revision: int = Field(ge=1)
    capabilities: tuple[CapabilityRequirement, ...] = Field(min_length=1)
    registry_digest: Digest

    @classmethod
    def create(
        cls,
        *,
        registry_id: str,
        registry_revision: int,
        capabilities: tuple[CapabilityRequirement, ...],
    ) -> CapabilityRegistryReference:
        ordered = tuple(sorted(capabilities, key=lambda item: item.capability_id))
        payload = [item.model_dump(mode="json") for item in ordered]
        return cls(
            registry_id=registry_id,
            registry_revision=registry_revision,
            capabilities=ordered,
            registry_digest=digest_json(payload),
        )

    @model_validator(mode="after")
    def registry_is_exact(self) -> CapabilityRegistryReference:
        ids = [item.capability_id for item in self.capabilities]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("Capabilities must be unique and ordered")
        if self.registry_digest != digest_json(
            [item.model_dump(mode="json") for item in self.capabilities]
        ):
            raise ValueError("Capability registry digest mismatched")
        return self


class PromptSpecification(CreationPlanningModel):
    subject: str = Field(min_length=1)
    scene: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    action: str = Field(min_length=1)
    lighting: str = Field(min_length=1)
    style: str = Field(min_length=1)
    negative_constraints: tuple[str, ...] = ()
    reference_asset_ids: tuple[StableId, ...] = ()
    continuity_anchor_ids: tuple[StableId, ...] = ()


class ProductionEstimate(CreationPlanningModel):
    status: Literal["known", "unknown"]
    value: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def estimate_shape(self) -> ProductionEstimate:
        if self.status == "known" and (
            self.value is None or self.unit is None
        ):
            raise ValueError("Known estimate requires value and unit")
        if self.status == "unknown" and (
            self.value is not None or self.unit is not None
        ):
            raise ValueError("Unknown estimate cannot invent a value")
        return self


class DeliveryFileSpecification(CreationPlanningModel):
    media_kind: Literal["video", "image", "audio"]
    container_or_extension: str = Field(min_length=1)
    mime_type: str = Field(min_length=3)
    filename_pattern: str = Field(min_length=1)

    @model_validator(mode="after")
    def file_spec_is_relative(self) -> DeliveryFileSpecification:
        value = self.filename_pattern
        if (
            value.startswith(("/", "\\"))
            or ":\\" in value
            or "../" in value
            or "..\\" in value
        ):
            raise ValueError("Delivery file pattern must be path-safe")
        return self


class ReproducibilityParameter(CreationPlanningModel):
    name: StableId
    value: str | int | float | bool


class MaterialProductionTask(CreationPlanningModel):
    task_id: StableId
    requirement_item_id: StableId
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    production_method: Literal[
        "generate",
        "capture",
        "import",
        "library_search",
        "manual",
    ]
    status: Literal["planned", "needs_user_input", "unsupported"]
    capability_ids: tuple[StableId, ...] = Field(min_length=1)
    prompt_spec: PromptSpecification | None = None
    reference_asset_ids: tuple[StableId, ...] = ()
    continuity_anchor_ids: tuple[StableId, ...] = ()
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    aspect_ratio: str | None = Field(default=None, min_length=1)
    fps: float | None = Field(default=None, gt=0)
    audio_parameters: tuple[str, ...] = ()
    seed: int | None = Field(default=None, ge=0)
    reproducibility_parameters: tuple[ReproducibilityParameter, ...] = ()
    dependency_task_ids: tuple[StableId, ...] = ()
    batch_id: StableId
    cost_estimate: ProductionEstimate
    time_estimate: ProductionEstimate
    quality_gates: tuple[str, ...] = Field(min_length=1)
    retry_strategy: tuple[str, ...] = Field(min_length=1)
    alternative_strategy: str = Field(min_length=1)
    delivery: DeliveryFileSpecification
    limitation: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def task_is_consistent(self) -> MaterialProductionTask:
        if (self.width is None) != (self.height is None):
            raise ValueError("Production width and height must be paired")
        if self.production_method == "generate" and self.prompt_spec is None:
            raise ValueError("Generated task requires a prompt specification")
        if self.production_method != "generate" and self.prompt_spec is not None:
            raise ValueError("Only generated tasks accept a prompt specification")
        if self.status == "planned" and self.limitation is not None:
            raise ValueError("Planned task cannot claim a limitation")
        if self.status != "planned" and self.limitation is None:
            raise ValueError("Blocked task requires a limitation")
        for values in (
            self.capability_ids,
            self.reference_asset_ids,
            self.continuity_anchor_ids,
            self.dependency_task_ids,
            self.quality_gates,
            self.retry_strategy,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Production task lists must be unique")
        parameter_names = [
            item.name for item in self.reproducibility_parameters
        ]
        if (
            parameter_names != sorted(parameter_names)
            or len(parameter_names) != len(set(parameter_names))
        ):
            raise ValueError(
                "Reproducibility parameters must be unique and ordered"
            )
        if self.task_id in self.dependency_task_ids:
            raise ValueError("Production task cannot depend on itself")
        return self


class MaterialProductionPlanDraft(CreationPlanningModel):
    rationale: str = Field(min_length=1)
    tasks: tuple[MaterialProductionTask, ...] = Field(min_length=1)
    delivery_summary: tuple[str, ...] = Field(min_length=1)
    global_quality_gates: tuple[str, ...] = Field(min_length=1)
    unresolved_questions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class CreationPlanningRequest(CreationPlanningModel):
    schema_name: Literal["vistora.creation-planning.request"] = (
        "vistora.creation-planning.request"
    )
    request_id: StableId
    material_confirmation_ref: MaterialConfirmationReference
    capability_registry_ref: CapabilityRegistryReference


class CreationPlanningReasoningOutput(CreationPlanningModel):
    schema_name: Literal["vistora.creation-planning.reasoning-output"] = (
        "vistora.creation-planning.reasoning-output"
    )
    outcome: Literal["proposal", "needs_user_input", "unsupported"]
    message: str = Field(min_length=1)
    material_confirmation_ref: MaterialConfirmationReference
    capability_registry_ref: CapabilityRegistryReference
    plan_draft: MaterialProductionPlanDraft | None = None

    @model_validator(mode="after")
    def output_shape(self) -> CreationPlanningReasoningOutput:
        if self.outcome == "proposal" and self.plan_draft is None:
            raise ValueError("Proposal outcome requires a production-plan draft")
        if self.outcome != "proposal" and self.plan_draft is not None:
            raise ValueError("Blocked outcome cannot include a production plan")
        return self


class MaterialProductionPlan(CreationPlanningModel):
    schema_name: Literal["vistora.material-production-plan"] = (
        "vistora.material-production-plan"
    )
    production_plan_id: StableId
    plan_version: int = Field(ge=1)
    material_confirmation_ref: MaterialConfirmationReference
    capability_registry_ref: CapabilityRegistryReference
    created_at: AwareDatetime
    rationale: str = Field(min_length=1)
    tasks: tuple[MaterialProductionTask, ...] = Field(min_length=1)
    delivery_summary: tuple[str, ...] = Field(min_length=1)
    global_quality_gates: tuple[str, ...] = Field(min_length=1)
    unresolved_questions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def plan_graph_is_exact(self) -> MaterialProductionPlan:
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Production task IDs must be unique")
        known = set(task_ids)
        for task in self.tasks:
            if not set(task.dependency_task_ids).issubset(known):
                raise ValueError("Production task dependency is unknown")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class MaterialProductionChange(CreationPlanningModel):
    change_id: StableId
    change_type: Literal["added", "removed", "changed"]
    task_id: StableId
    requirement_item_id: StableId
    before_digest: Digest | None = None
    after_digest: Digest | None = None
    summary: str = Field(min_length=1)


class MaterialProductionReview(CreationPlanningModel):
    schema_name: Literal["vistora.material-production-review"] = (
        "vistora.material-production-review"
    )
    review_id: StableId
    production_plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Digest
    material_confirmation_ref: MaterialConfirmationReference
    capability_registry_ref: CapabilityRegistryReference
    previous_plan_digest: Digest | None = None
    changes: tuple[MaterialProductionChange, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()
    review_digest: Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def review_is_exact(self) -> MaterialProductionReview:
        payload = self.model_dump(mode="json", exclude={"review_digest"})
        if self.review_digest != digest_json(payload):
            raise ValueError("Production review digest mismatched")
        return self


class MaterialProductionProposal(CreationPlanningModel):
    schema_name: Literal["vistora.material-production-proposal"] = (
        "vistora.material-production-proposal"
    )
    proposal_id: StableId
    plan: MaterialProductionPlan
    review: MaterialProductionReview
    created_at: AwareDatetime

    @model_validator(mode="after")
    def proposal_linkage(self) -> MaterialProductionProposal:
        if (
            self.review.production_plan_id != self.plan.production_plan_id
            or self.review.plan_version != self.plan.plan_version
            or self.review.plan_digest != self.plan.digest()
            or self.review.material_confirmation_ref
            != self.plan.material_confirmation_ref
            or self.review.capability_registry_ref
            != self.plan.capability_registry_ref
        ):
            raise ValueError("Production proposal linkage drifted")
        return self


class MaterialProductionConfirmation(CreationPlanningModel):
    schema_name: Literal["vistora.material-production-confirmation"] = (
        "vistora.material-production-confirmation"
    )
    confirmation_id: StableId
    production_plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Digest
    review_id: StableId
    review_digest: Digest
    material_confirmation_ref: MaterialConfirmationReference
    capability_registry_ref: CapabilityRegistryReference
    decision: Literal["confirmed", "rejected"]
    confirmed_by: StableId
    recorded_at: AwareDatetime

    @classmethod
    def for_proposal(
        cls,
        *,
        confirmation_id: str,
        proposal: MaterialProductionProposal,
        decision: Literal["confirmed", "rejected"],
        confirmed_by: str,
        recorded_at: datetime,
    ) -> MaterialProductionConfirmation:
        return cls(
            confirmation_id=confirmation_id,
            production_plan_id=proposal.plan.production_plan_id,
            plan_version=proposal.plan.plan_version,
            plan_digest=proposal.plan.digest(),
            review_id=proposal.review.review_id,
            review_digest=proposal.review.review_digest,
            material_confirmation_ref=proposal.plan.material_confirmation_ref,
            capability_registry_ref=proposal.plan.capability_registry_ref,
            decision=decision,
            confirmed_by=confirmed_by,
            recorded_at=recorded_at,
        )

    def validate_proposal(self, proposal: MaterialProductionProposal) -> None:
        if (
            self.production_plan_id != proposal.plan.production_plan_id
            or self.plan_version != proposal.plan.plan_version
            or self.plan_digest != proposal.plan.digest()
            or self.review_id != proposal.review.review_id
            or self.review_digest != proposal.review.review_digest
            or self.material_confirmation_ref
            != proposal.plan.material_confirmation_ref
            or self.capability_registry_ref
            != proposal.plan.capability_registry_ref
        ):
            raise ValueError("Production confirmation binding mismatched")


class CreationPlanningReport(CreationPlanningModel):
    schema_name: Literal["vistora.creation-planning.report"] = (
        "vistora.creation-planning.report"
    )
    report_id: StableId
    request_id: StableId
    status: Literal[
        "proposal_ready",
        "needs_user_input",
        "unsupported",
        "rejected",
        "model_error",
        "stale_context",
    ]
    message: str = Field(min_length=1)
    proposal: MaterialProductionProposal | None = None
    error_code: StableId | None = None
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def report_shape(self) -> CreationPlanningReport:
        if self.status == "proposal_ready" and self.proposal is None:
            raise ValueError("Ready report requires a proposal")
        if self.status != "proposal_ready" and self.proposal is not None:
            raise ValueError("Non-ready report cannot include a proposal")
        if self.status in {"model_error", "stale_context", "rejected"}:
            if self.error_code is None:
                raise ValueError("Error report requires an error code")
        elif self.error_code is not None:
            raise ValueError("Successful/blocked report cannot have error code")
        return self


class CreationPlanningEvent(CreationPlanningModel):
    schema_name: Literal["vistora.creation-planning.event"] = (
        "vistora.creation-planning.event"
    )
    sequence: int = Field(ge=1)
    event_id: StableId
    event_type: Literal[
        "proposal_recorded",
        "confirmed",
        "rejected",
        "withdrawn",
    ]
    proposal: MaterialProductionProposal | None = None
    confirmation: MaterialProductionConfirmation | None = None
    withdrawn_proposal_id: StableId | None = None
    recorded_at: AwareDatetime
    previous_event_digest: Digest
    event_digest: Digest

    @model_validator(mode="after")
    def event_shape(self) -> CreationPlanningEvent:
        if self.event_type == "proposal_recorded":
            valid = (
                self.proposal is not None
                and self.confirmation is None
                and self.withdrawn_proposal_id is None
            )
        elif self.event_type in {"confirmed", "rejected"}:
            valid = (
                self.proposal is None
                and self.confirmation is not None
                and self.withdrawn_proposal_id is None
                and self.confirmation.decision == self.event_type
            )
        else:
            valid = (
                self.proposal is None
                and self.confirmation is None
                and self.withdrawn_proposal_id is not None
            )
        if not valid:
            raise ValueError("Creation-planning event shape is invalid")
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Creation-planning event digest mismatched")
        return self


class CreationPlanningLedger(CreationPlanningModel):
    schema_name: Literal["vistora.creation-planning.ledger"] = (
        "vistora.creation-planning.ledger"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[CreationPlanningEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(
        cls,
        *,
        session_id: str,
        project_id: str,
    ) -> CreationPlanningLedger:
        return cls(
            session_id=session_id,
            project_id=project_id,
            revision=0,
            events=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def ledger_is_exact(self) -> CreationPlanningLedger:
        if self.revision != len(self.events):
            raise ValueError("Creation-planning revision is invalid")
        previous = GENESIS_DIGEST
        proposals: dict[str, MaterialProductionProposal] = {}
        decided: set[str] = set()
        withdrawn: set[str] = set()
        for index, event in enumerate(self.events, start=1):
            if event.sequence != index or event.previous_event_digest != previous:
                raise ValueError("Creation-planning ledger chain is broken")
            if event.proposal is not None:
                if event.proposal.proposal_id in proposals:
                    raise ValueError("Production proposal ID is duplicated")
                proposals[event.proposal.proposal_id] = event.proposal
            if event.confirmation is not None:
                matches = [
                    proposal
                    for proposal in proposals.values()
                    if proposal.review.review_id
                    == event.confirmation.review_id
                ]
                if len(matches) != 1:
                    raise ValueError("Production confirmation review is unknown")
                event.confirmation.validate_proposal(matches[0])
                if event.confirmation.review_id in decided:
                    raise ValueError("Production review was already decided")
                decided.add(event.confirmation.review_id)
            if event.withdrawn_proposal_id is not None:
                if (
                    event.withdrawn_proposal_id not in proposals
                    or event.withdrawn_proposal_id in withdrawn
                ):
                    raise ValueError("Production withdrawal is invalid")
                withdrawn.add(event.withdrawn_proposal_id)
            previous = event.event_digest
        if self.integrity_digest != digest_json(
            [event.event_digest for event in self.events]
        ):
            raise ValueError("Creation-planning integrity digest mismatched")
        return self


class ConfirmedMaterialProductionPlan(CreationPlanningModel):
    schema_name: Literal["vistora.confirmed-material-production-plan"] = (
        "vistora.confirmed-material-production-plan"
    )
    ledger_revision: int = Field(ge=1)
    proposal: MaterialProductionProposal
    confirmation: MaterialProductionConfirmation

    @model_validator(mode="after")
    def exact_confirmation(self) -> ConfirmedMaterialProductionPlan:
        self.confirmation.validate_proposal(self.proposal)
        if self.confirmation.decision != "confirmed":
            raise ValueError("Material production plan is not confirmed")
        return self


class CreationPlanningView(CreationPlanningModel):
    schema_name: Literal["vistora.creation-planning.history"] = (
        "vistora.creation-planning.history"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    state: Literal[
        "empty",
        "reviewable",
        "confirmed",
        "rejected",
        "withdrawn",
    ]
    proposals: tuple[dict[str, Any], ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()


def canonical_capability_digest(
    capabilities: tuple[CapabilityRequirement, ...],
) -> str:
    value = json.dumps(
        [item.model_dump(mode="json") for item in capabilities],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(value).hexdigest()
