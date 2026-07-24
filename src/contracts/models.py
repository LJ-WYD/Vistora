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


class DirectorOperation(ContractModel):
    """One proposed atomic operation in a Director-authored creative plan."""

    operation_id: StableId
    tool_name: StableId
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    expected_effect: str = Field(min_length=1)

    _arguments_are_json = field_validator("arguments")(_validated_json_object)


class DirectorPlan(ContractModel):
    """A versioned creative plan authored by the future Director Agent."""

    schema_name: Literal["vistora.director-plan"] = "vistora.director-plan"
    plan_id: StableId
    plan_version: int = Field(ge=1)
    created_at: AwareDatetime = Field(default_factory=_utc_now)
    objective: str = Field(min_length=1)
    requirements: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    creative_direction: dict[str, Any] = Field(default_factory=dict)
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
        return self

    def digest(self) -> str:
        """Return the canonical digest bound by a confirmation record."""

        payload = self.model_dump(mode="json")
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

    _arguments_are_json = field_validator("arguments")(_validated_json_object)


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
    requested_at: AwareDatetime = Field(default_factory=_utc_now)

    _arguments_are_json = field_validator("arguments")(_validated_json_object)

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
        return cls(
            request_id=request_id,
            execution_id=execution_plan.execution_id,
            project_id=execution_plan.project_id,
            confirmation_id=execution_plan.confirmation.confirmation_id,
            plan_ref=PlanReference.from_plan(execution_plan.director_plan),
            step_id=step.step_id,
            tool_name=step.tool_name,
            arguments=step.arguments,
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
    status: Literal["success", "error"]
    payload: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime = Field(default_factory=_utc_now)

    _payload_is_json = field_validator("payload")(_validated_json_object)

    @model_validator(mode="after")
    def result_state_is_consistent(self) -> AtomicToolResultEnvelope:
        if self.finished_at < self.started_at:
            raise ValueError("Tool result cannot finish before it starts")
        if self.status == "success" and self.error is not None:
            raise ValueError("Successful tool results cannot include an error")
        if self.status == "error" and self.error is None:
            raise ValueError("Failed tool results must include an error")
        return self
