"""Production constrained Editing Agent over the confirmed workflow boundary.

This module deliberately contains no dialogue, planning, timeline, renderer, or
skill-registry implementation. It accepts one exact persisted confirmation
binding and delegates execution to WorkflowApplicationService.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from timeline_query import TimelineSnapshotReference
from workflow import (
    ConfirmedExecutionBinding,
    EditingExecutionRunRecord,
    WorkflowApplicationError,
    WorkflowApplicationService,
    WorkflowConcurrencyError,
    WorkflowError,
    WorkflowIntegrityError,
    WorkflowStoreError,
)


EDITING_AGENT_VERSION = "1.0.0"
EditingAgentVersion = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]


class EditingAgentModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: EditingAgentVersion = EDITING_AGENT_VERSION


class EditingAgentExecutionRequest(EditingAgentModel):
    """One exact, non-creative request to consume a confirmed workflow gate."""

    schema_name: Literal["vistora.editing-agent.execution-request"] = (
        "vistora.editing-agent.execution-request"
    )
    request_id: StableId
    binding: ConfirmedExecutionBinding
    requested_at: AwareDatetime


class EditingAgentStepReport(EditingAgentModel):
    schema_name: Literal["vistora.editing-agent.step-report"] = (
        "vistora.editing-agent.step-report"
    )
    sequence: int = Field(ge=1)
    step_id: StableId
    tool_name: StableId
    atomic_request_id: StableId
    atomic_result_id: StableId
    status: Literal["success", "error"]
    before_snapshot: TimelineSnapshotReference
    after_snapshot: TimelineSnapshotReference
    error: WorkflowError | None = None

    @model_validator(mode="after")
    def error_matches_status(self) -> EditingAgentStepReport:
        if self.status == "success" and self.error is not None:
            raise ValueError("Successful Editing Agent step cannot have an error")
        if self.status == "error" and self.error is None:
            raise ValueError("Failed Editing Agent step requires an error")
        return self


EditingAgentStatus = Literal[
    "rejected",
    "succeeded",
    "failed",
    "partial",
    "recovery_required",
]


class EditingAgentExecutionReport(EditingAgentModel):
    """Truthful terminal report for one attempted constrained execution."""

    schema_name: Literal["vistora.editing-agent.execution-report"] = (
        "vistora.editing-agent.execution-report"
    )
    report_id: StableId
    request_id: StableId
    binding: ConfirmedExecutionBinding
    project_id: StableId
    confirmation_record_id: StableId
    disposition: Literal["rejected", "executed"]
    status: EditingAgentStatus
    workflow_revision_before: int = Field(ge=1)
    workflow_revision_after: int | None = Field(default=None, ge=1)
    run_record_id: StableId | None = None
    run_id: StableId | None = None
    execution_id: StableId | None = None
    steps: tuple[EditingAgentStepReport, ...] = ()
    start_snapshot: TimelineSnapshotReference | None = None
    latest_snapshot: TimelineSnapshotReference | None = None
    error: WorkflowError | None = None
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def report_is_truthful(self) -> EditingAgentExecutionReport:
        if (
            self.project_id != self.binding.project_id
            or self.confirmation_record_id
            != self.binding.confirmation_record_id
            or self.workflow_revision_before
            != self.binding.workflow_revision
        ):
            raise ValueError("Editing Agent report crosses its request binding")
        run_fields = (
            self.run_record_id,
            self.run_id,
            self.execution_id,
            self.start_snapshot,
            self.latest_snapshot,
        )
        if self.disposition == "rejected":
            if self.status != "rejected" or any(
                item is not None for item in run_fields
            ):
                raise ValueError("Rejected report cannot claim an execution run")
            if self.steps or self.error is None:
                raise ValueError("Rejected report requires only a typed error")
            return self
        if self.status == "rejected" or any(
            item is None for item in run_fields
        ):
            raise ValueError("Executed report requires exact run linkage")
        if self.workflow_revision_after is None:
            raise ValueError("Executed report requires final workflow revision")
        if self.status == "succeeded":
            if self.error is not None:
                raise ValueError("Successful report cannot have an error")
            if any(step.status != "success" for step in self.steps):
                raise ValueError("Successful report contains a failed step")
        elif self.error is None:
            raise ValueError("Non-success execution report requires an error")
        return self


class EditingAgentRecoveryReport(EditingAgentModel):
    """Structured restart-recovery result; it never guesses execution success."""

    schema_name: Literal["vistora.editing-agent.recovery-report"] = (
        "vistora.editing-agent.recovery-report"
    )
    report_id: StableId
    project_id: StableId
    workflow_revision_before: int = Field(ge=0)
    workflow_revision_after: int = Field(ge=0)
    recovered_run_ids: tuple[StableId, ...] = ()
    status: Literal["no_interruption", "recovery_required"]
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def recovery_status_is_exact(self) -> EditingAgentRecoveryReport:
        expected = (
            "recovery_required"
            if self.recovered_run_ids
            else "no_interruption"
        )
        if self.status != expected:
            raise ValueError("Recovery report status does not match recovered runs")
        return self


Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _workflow_error(exc: Exception) -> WorkflowError:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if isinstance(exc, WorkflowIntegrityError):
        return WorkflowError(
            code="workflow_integrity_failed",
            message=message,
            recovery_action=(
                "Inspect or restore the append-only workflow ledger before retrying."
            ),
        )
    if isinstance(exc, WorkflowConcurrencyError):
        return WorkflowError(
            code="workflow_concurrency_conflict",
            message=message,
            retryable=True,
            recovery_action="Retry after the active workflow operation finishes.",
        )
    if "already been used" in lowered:
        code = "confirmation_replay_rejected"
    elif "snapshot drifted" in lowered:
        code = "snapshot_stale"
    elif "registry/schema drifted" in lowered:
        code = "registry_schema_stale"
    elif "plan diff drifted" in lowered:
        code = "review_diff_stale"
    elif "binding changed" in lowered:
        code = "execution_binding_stale"
    elif "confirmation" in lowered:
        code = "confirmation_gate_rejected"
    else:
        code = "workflow_execution_rejected"
    return WorkflowError(
        code=code,
        message=message,
        retryable=code in {
            "snapshot_stale",
            "registry_schema_stale",
            "review_diff_stale",
            "execution_binding_stale",
        },
        recovery_action=(
            "Regenerate review and obtain a new explicit confirmation."
            if code.endswith("_stale")
            else None
        ),
    )


class EditingAgent:
    """Constrained executor with no dialogue, inference, or mutation access."""

    def __init__(
        self,
        workflow: WorkflowApplicationService,
        *,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _random_id,
    ) -> None:
        self._workflow = workflow
        self._clock = clock
        self._id_factory = id_factory

    def prepare_execution(
        self,
        *,
        request_id: str,
        confirmation_record_id: str,
    ) -> EditingAgentExecutionRequest:
        """Create a frozen request only after all current bindings validate."""

        binding = self._workflow.confirmed_execution_binding(
            confirmation_record_id
        )
        return EditingAgentExecutionRequest(
            request_id=request_id,
            binding=binding,
            requested_at=self._clock(),
        )

    def execute(
        self,
        request: EditingAgentExecutionRequest,
    ) -> EditingAgentExecutionReport:
        """Execute exactly the confirmed steps or return a fail-closed report."""

        binding = request.binding
        try:
            current = self._workflow.confirmed_execution_binding(
                binding.confirmation_record_id
            )
            if current != binding:
                raise WorkflowApplicationError(
                    "Confirmed execution binding changed before dispatch"
                )
            run = self._workflow.run_confirmed_execution(
                binding.confirmation_record_id,
                expected_binding=binding,
            )
            revision_after = self._workflow.store.load(
                binding.project_id
            ).revision
            return self._report_from_run(
                request,
                run,
                revision_after=revision_after,
            )
        except (
            WorkflowApplicationError,
            WorkflowStoreError,
        ) as exc:
            return EditingAgentExecutionReport(
                report_id=self._id_factory("editing_report"),
                request_id=request.request_id,
                binding=binding,
                project_id=binding.project_id,
                confirmation_record_id=binding.confirmation_record_id,
                disposition="rejected",
                status="rejected",
                workflow_revision_before=binding.workflow_revision,
                error=_workflow_error(exc),
                finished_at=self._clock(),
            )

    def recover_interrupted_runs(
        self,
        project_id: str,
    ) -> EditingAgentRecoveryReport:
        """Mark abandoned nonterminal runs recovery-required after restart."""

        before = self._workflow.store.load(project_id)
        previous_latest = self._latest_runs(before)
        after = self._workflow.recover_interrupted_runs(project_id)
        latest = self._latest_runs(after)
        recovered = tuple(
            sorted(
                run_id
                for run_id, record in latest.items()
                if record.status == "recovery_required"
                and previous_latest.get(run_id) is not None
                and previous_latest[run_id].status
                in {"execution_pending", "running"}
            )
        )
        return EditingAgentRecoveryReport(
            report_id=self._id_factory("editing_recovery_report"),
            project_id=project_id,
            workflow_revision_before=before.revision,
            workflow_revision_after=after.revision,
            recovered_run_ids=recovered,
            status=(
                "recovery_required" if recovered else "no_interruption"
            ),
            finished_at=self._clock(),
        )

    @staticmethod
    def _latest_runs(ledger: Any) -> dict[str, EditingExecutionRunRecord]:
        latest: dict[str, EditingExecutionRunRecord] = {}
        for entry in ledger.entries:
            record = entry.record
            if isinstance(record, EditingExecutionRunRecord):
                latest[record.run_id] = record
        return latest

    def _report_from_run(
        self,
        request: EditingAgentExecutionRequest,
        run: EditingExecutionRunRecord,
        *,
        revision_after: int,
    ) -> EditingAgentExecutionReport:
        steps = tuple(
            EditingAgentStepReport(
                sequence=step.sequence,
                step_id=step.request.step_id,
                tool_name=step.request.tool_name,
                atomic_request_id=step.request.request_id,
                atomic_result_id=step.result.result_id,
                status=step.result.status,
                before_snapshot=step.before_snapshot,
                after_snapshot=step.after_snapshot,
                error=(
                    WorkflowError(
                        code=step.result.error.code,
                        message=step.result.error.message,
                    )
                    if step.result.error is not None
                    else None
                ),
            )
            for step in run.steps
        )
        return EditingAgentExecutionReport(
            report_id=self._id_factory("editing_report"),
            request_id=request.request_id,
            binding=request.binding,
            project_id=run.project_id,
            confirmation_record_id=run.confirmation_record_id,
            disposition="executed",
            status=run.status,
            workflow_revision_before=request.binding.workflow_revision,
            workflow_revision_after=revision_after,
            run_record_id=run.run_record_id,
            run_id=run.run_id,
            execution_id=run.execution_plan.execution_id,
            steps=steps,
            start_snapshot=run.start_checkpoint.snapshot_ref,
            latest_snapshot=run.latest_checkpoint.snapshot_ref,
            error=run.error,
            finished_at=run.finished_at or self._clock(),
        )


__all__ = [
    "EDITING_AGENT_VERSION",
    "EditingAgent",
    "EditingAgentExecutionReport",
    "EditingAgentExecutionRequest",
    "EditingAgentRecoveryReport",
    "EditingAgentStepReport",
]
