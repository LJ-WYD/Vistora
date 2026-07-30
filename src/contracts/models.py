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

from core.timeline import TimelineConfig


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


class ManualClipUpdate(ContractModel):
    """User-authored timing/order replacement for one existing video clip."""

    operation_id: StableId
    kind: Literal["update"] = "update"
    track_key: Literal["video"] = "video"
    clip_id: str = Field(min_length=1)
    trim_in_seconds: float = Field(ge=0, allow_inf_nan=False)
    trim_out_seconds: float = Field(gt=0, allow_inf_nan=False)
    timeline_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    order_index: int = Field(ge=0)

    @model_validator(mode="after")
    def trim_range_is_valid(self) -> ManualClipUpdate:
        if self.trim_out_seconds <= self.trim_in_seconds:
            raise ValueError("Manual clip trim-out must be after trim-in")
        return self


class ManualClipRemove(ContractModel):
    """User-authored removal of one existing video clip."""

    operation_id: StableId
    kind: Literal["remove"] = "remove"
    track_key: Literal["video"] = "video"
    clip_id: str = Field(min_length=1)


ManualEditOperation = Annotated[
    ManualClipUpdate | ManualClipRemove,
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
        clip_targets = [(edit.track_key, edit.clip_id) for edit in self.edits]
        if len(clip_targets) != len(set(clip_targets)):
            raise ValueError(
                "A manual proposal may edit each clip at most once"
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
    track_key: Literal["video"]
    clip_id: str = Field(min_length=1)
    action: Literal["update", "remove"]
    before: dict[str, Any]
    after: dict[str, Any] | None

    _before_is_json = field_validator("before")(_validated_json_object)
    _after_is_json = field_validator("after")(
        lambda value: (
            None if value is None else _validated_json_object(value)
        )
    )


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
            legacy_keys = {"width", "height", "fps", "tracks"}
            if wrapper_keys.intersection(value):
                return value
            if not set(value).issubset(legacy_keys):
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
