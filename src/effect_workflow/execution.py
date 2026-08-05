"""Confirmed, provider-neutral dispatch boundary for O28 effect capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from director import digest_json

from .capabilities import (
    EffectAdapterRegistry,
    EffectAdapterRegistryReference,
    EffectAdapterRequest,
    EffectAdapterResult,
    EffectArtifactCandidate,
    EffectCapabilityId,
)
from .models import Digest, EffectModel, EffectPlanConfirmation, EffectProductionPlan, StableId
from .service import EffectPlanService


class EffectExecutionError(ValueError):
    pass


class EffectExecutionBinding(EffectModel):
    schema_name: Literal["vistora.effect-execution-binding"] = (
        "vistora.effect-execution-binding"
    )
    project_id: StableId
    confirmation_id: StableId
    effect_plan_id: StableId
    effect_plan_version: int = Field(ge=1)
    effect_plan_digest: Digest
    review_id: StableId
    review_digest: Digest
    snapshot_digest: Digest
    snapshot_revision: int = Field(ge=0)
    adapter_registry_id: StableId
    adapter_registry_revision: int = Field(ge=1)
    adapter_registry_digest: Digest

    @classmethod
    def create(cls, plan, confirmation, registry_ref):
        if (
            confirmation.decision != "confirmed"
            or confirmation.effect_plan_id != plan.effect_plan_id
            or confirmation.plan_version != plan.plan_version
            or confirmation.plan_digest != plan.digest()
            or confirmation.snapshot_ref != plan.snapshot_ref
        ):
            raise ValueError("Effect confirmation does not bind the exact plan")
        return cls(
            project_id=plan.intent.project_id,
            confirmation_id=confirmation.confirmation_id,
            effect_plan_id=plan.effect_plan_id,
            effect_plan_version=plan.plan_version,
            effect_plan_digest=plan.digest(),
            review_id=confirmation.review_id,
            review_digest=confirmation.review_digest,
            snapshot_digest=plan.snapshot_ref.timeline_digest,
            snapshot_revision=plan.snapshot_ref.revision,
            adapter_registry_id=registry_ref.registry_id,
            adapter_registry_revision=registry_ref.registry_revision,
            adapter_registry_digest=registry_ref.registry_digest,
        )


class EffectTaskInput(EffectModel):
    task_id: StableId
    input_token: StableId


class EffectExecutionRequest(EffectModel):
    schema_name: Literal["vistora.effect-execution-request"] = (
        "vistora.effect-execution-request"
    )
    execution_request_id: StableId
    binding: EffectExecutionBinding
    task_ids: tuple[StableId, ...] = Field(min_length=1)
    task_inputs: tuple[EffectTaskInput, ...] = ()
    requested_by: StableId

    @model_validator(mode="after")
    def exact(self):
        if self.task_ids != tuple(sorted(set(self.task_ids))):
            raise ValueError("Effect execution task IDs must be unique and ordered")
        input_ids = [item.task_id for item in self.task_inputs]
        if input_ids != sorted(set(input_ids)) or not set(input_ids).issubset(self.task_ids):
            raise ValueError("Effect execution task inputs are ambiguous")
        return self

    def digest(self):
        return digest_json(self.model_dump(mode="json"))


class EffectAcceptanceCheck(EffectModel):
    dimension: StableId
    status: Literal["pending_human_review"] = "pending_human_review"
    message: str = Field(min_length=1, max_length=300)


class EffectTaskExecutionReport(EffectModel):
    schema_name: Literal["vistora.effect-task-execution-report"] = (
        "vistora.effect-task-execution-report"
    )
    task_id: StableId
    job_id: StableId
    capability_id: EffectCapabilityId
    adapter_id: StableId | None = None
    status: Literal[
        "ready_for_review",
        "not_configured",
        "needs_manual_input",
        "failed",
    ]
    artifact: EffectArtifactCandidate | None = None
    acceptance_checks: tuple[EffectAcceptanceCheck, ...] = ()
    fillback_status: Literal["blocked", "human_acceptance_required"]
    error_code: StableId | None = None
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def truthful(self):
        if self.status == "ready_for_review":
            if (
                self.artifact is None
                or not self.acceptance_checks
                or self.fillback_status != "human_acceptance_required"
                or self.error_code is not None
            ):
                raise ValueError("Reviewable effect result requires a pending artifact")
        elif (
            self.artifact is not None
            or self.acceptance_checks
            or self.fillback_status != "blocked"
            or self.error_code is None
        ):
            raise ValueError("Blocked effect result cannot claim an artifact")
        return self


class EffectExecutionReport(EffectModel):
    schema_name: Literal["vistora.effect-execution-report"] = (
        "vistora.effect-execution-report"
    )
    execution_request_id: StableId
    request_digest: Digest
    binding: EffectExecutionBinding
    status: Literal["awaiting_human_review", "blocked", "partial", "failed"]
    tasks: tuple[EffectTaskExecutionReport, ...] = Field(min_length=1)
    timeline_mutated: Literal[False] = False
    provider_calls_are_test_only: bool
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def aggregate_is_truthful(self):
        statuses = {item.status for item in self.tasks}
        if self.status == "awaiting_human_review" and statuses != {"ready_for_review"}:
            raise ValueError("Effect report success aggregate is false")
        if self.status == "blocked" and "ready_for_review" in statuses:
            raise ValueError("Blocked effect report contains a reviewable artifact")
        if self.status == "partial" and (
            "ready_for_review" not in statuses or statuses == {"ready_for_review"}
        ):
            raise ValueError("Partial effect report aggregate is false")
        return self


class EffectCapabilityExecutionService:
    """Runs exact confirmed O27 tasks without timeline or provider authority."""

    def __init__(
        self,
        *,
        plans: EffectPlanService,
        adapters: EffectAdapterRegistry,
        staging_root: str | Path,
    ):
        self.plans = plans
        self.adapters = adapters
        self.staging_root = Path(staging_root)

    def prepare(self, *, execution_request_id, confirmation_id, requested_by, task_inputs=()):
        plan, confirmation = self.plans.confirmed(confirmation_id)
        reference = self.adapters.reference()
        return EffectExecutionRequest(
            execution_request_id=execution_request_id,
            binding=EffectExecutionBinding.create(plan, confirmation, reference),
            task_ids=tuple(sorted(task.task_id for task in plan.tasks)),
            task_inputs=tuple(sorted(task_inputs, key=lambda item: item.task_id)),
            requested_by=requested_by,
        )

    def _exact(self, request):
        plan, confirmation = self.plans.confirmed(request.binding.confirmation_id)
        expected = EffectExecutionBinding.create(plan, confirmation, self.adapters.reference())
        if expected != request.binding:
            raise EffectExecutionError("Effect execution binding is stale or tampered")
        exact_ids = tuple(sorted(task.task_id for task in plan.tasks))
        if request.task_ids != exact_ids:
            raise EffectExecutionError("Effect execution omits or invents tasks")
        return plan, confirmation

    @staticmethod
    def _validate_capability(task, descriptor):
        if task.output_role not in descriptor.accepted_output_roles:
            raise EffectExecutionError("Effect output role is unsupported for the capability")
        for field in descriptor.required_task_fields:
            value = getattr(task, field, None)
            if value is None or value == ():
                raise EffectExecutionError(f"Effect task is missing required {field}")

    @staticmethod
    def _job_id(request, task):
        token = digest_json([request.digest(), task.task_id])[7:31]
        return f"effect_job_{token}"

    def execute(self, request: EffectExecutionRequest):
        plan, confirmation = self._exact(request)
        inputs = {item.task_id: item.input_token for item in request.task_inputs}
        capability_map = {
            item.capability_id: item for item in self.adapters.reference().capabilities
        }
        reports = []
        test_only = False
        for task in plan.tasks:
            descriptor = capability_map.get(task.capability_id)
            if descriptor is None:
                reports.append(self._blocked(request, task, "effect_capability_unknown", "The effect capability is not registered."))
                continue
            try:
                self._validate_capability(task, descriptor)
            except EffectExecutionError as exc:
                reports.append(self._blocked(request, task, "effect_task_invalid", str(exc)))
                continue
            adapter = self.adapters.select(task.capability_id)
            if adapter is None:
                reports.append(self._blocked(request, task, "effect_provider_not_configured", "No provider or manual-import adapter is configured for this capability.", status="not_configured"))
                continue
            adapter_descriptor = adapter.descriptor()
            test_only = test_only or adapter_descriptor.execution_kind == "local_deterministic_test"
            job_id = self._job_id(request, task)
            adapter_request = EffectAdapterRequest(
                job_id=job_id,
                execution_request_id=request.execution_request_id,
                project_id=request.binding.project_id,
                confirmation_id=confirmation.confirmation_id,
                task=task,
                idempotency_key=f"effect_key_{digest_json([request.digest(), task.task_id])[7:31]}",
                input_token=inputs.get(task.task_id),
            )
            try:
                result = adapter.submit(adapter_request, staging_root=self.staging_root)
                result = EffectAdapterResult.model_validate(result)
                if (
                    result.job_id != job_id
                    or result.adapter_id != adapter_descriptor.adapter_id
                    or result.capability_id != task.capability_id
                ):
                    raise ValueError("Effect adapter result linkage drifted")
            except Exception:
                reports.append(self._blocked(request, task, "effect_adapter_failed", "The effect adapter failed without a safe result."))
                continue
            if result.status != "succeeded":
                status = "not_configured" if result.status == "not_configured" else "needs_manual_input" if result.status == "needs_manual_input" else "failed"
                reports.append(self._blocked(request, task, result.error_code or "effect_adapter_failed", result.message, status=status, adapter_id=result.adapter_id))
                continue
            reports.append(EffectTaskExecutionReport(
                task_id=task.task_id,
                job_id=job_id,
                capability_id=task.capability_id,
                adapter_id=result.adapter_id,
                status="ready_for_review",
                artifact=result.artifact,
                acceptance_checks=tuple(
                    EffectAcceptanceCheck(
                        dimension=dimension,
                        message="Creative acceptance requires explicit human review.",
                    )
                    for dimension in descriptor.acceptance_dimensions
                ),
                fillback_status="human_acceptance_required",
                message="Artifact is isolated in staging; O29 timeline fillback has not occurred.",
            ))
        statuses = {item.status for item in reports}
        if statuses == {"ready_for_review"}:
            status = "awaiting_human_review"
        elif "ready_for_review" in statuses:
            status = "partial"
        elif statuses <= {"not_configured", "needs_manual_input"}:
            status = "blocked"
        else:
            status = "failed"
        return EffectExecutionReport(
            execution_request_id=request.execution_request_id,
            request_digest=request.digest(),
            binding=request.binding,
            status=status,
            tasks=tuple(reports),
            provider_calls_are_test_only=test_only,
            message=(
                "Effect artifacts await explicit human acceptance; no timeline mutation occurred."
                if status in {"awaiting_human_review", "partial"}
                else "Effect execution produced no reviewable artifact."
            ),
        )

    def _blocked(self, request, task, code, message, *, status="failed", adapter_id=None):
        return EffectTaskExecutionReport(
            task_id=task.task_id,
            job_id=self._job_id(request, task),
            capability_id=task.capability_id,
            adapter_id=adapter_id,
            status=status,
            fillback_status="blocked",
            error_code=code,
            message=message,
        )
