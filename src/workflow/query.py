"""Deterministic browser-safe workflow history projection."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Literal

from pydantic import Field

from .models import (
    DirectorPlanVersionRecord,
    EditingExecutionRunRecord,
    RollbackConfirmationRecord,
    RollbackReviewRecord,
    RollbackRunRecord,
    WorkflowConfirmationRecord,
    WorkflowLedger,
    WorkflowModel,
)


_WINDOWS_PATH = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s\"']+")
_POSIX_PATH = re.compile(r"(?<![\w:])/(?:[^/\s]+/)+[^/\s\"']+")


def _safe_text(value: str) -> str:
    return _POSIX_PATH.sub(
        "[redacted-path]",
        _WINDOWS_PATH.sub("[redacted-path]", value),
    )


class WorkflowHistoryView(WorkflowModel):
    schema_name: Literal["vistora.workflow-history"] = (
        "vistora.workflow-history"
    )
    project_id: str = Field(min_length=3)
    ledger_revision: int = Field(ge=0)
    integrity_digest: str
    state: Literal["empty", "active", "recovery_required"]
    plan_versions: tuple[dict[str, Any], ...] = ()
    reviews: tuple[dict[str, Any], ...] = ()
    confirmations: tuple[dict[str, Any], ...] = ()
    executions: tuple[dict[str, Any], ...] = ()
    rollback_reviews: tuple[dict[str, Any], ...] = ()
    rollback_confirmations: tuple[dict[str, Any], ...] = ()
    rollbacks: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = (
        "Timeline/project-state rollback only; external media is not removed.",
        "Production Director runtime remains absent.",
        "Browser workflow actions use the application service directly.",
    )


class WorkflowHistoryQuery:
    """Collapse append-only status events without exposing tool arguments."""

    @staticmethod
    def project(ledger: WorkflowLedger) -> WorkflowHistoryView:
        plan_versions = []
        reviews = []
        confirmations = []
        execution_events: dict[str, list[EditingExecutionRunRecord]] = (
            defaultdict(list)
        )
        rollback_reviews = []
        rollback_confirmations = []
        rollback_events: dict[str, list[RollbackRunRecord]] = defaultdict(
            list
        )

        for entry in ledger.entries:
            record = entry.record
            if isinstance(record, DirectorPlanVersionRecord):
                plan_versions.append(
                    {
                        "record_id": record.record_id,
                        "plan_id": record.plan.plan_id,
                        "plan_version": record.plan.plan_version,
                        "plan_digest": record.plan_ref.plan_digest,
                        "recorded_at": record.recorded_at.isoformat(),
                    }
                )
            elif record.schema_name == "vistora.workflow.review-session":
                reviews.append(
                    {
                        "review_id": record.review_id,
                        "plan_id": record.diff.plan_ref.plan_id,
                        "plan_version": record.diff.plan_ref.plan_version,
                        "diff_digest": record.diff_digest,
                        "review_status": record.diff.review_status,
                        "snapshot_revision": record.diff.snapshot_ref.revision,
                        "snapshot_digest": (
                            record.diff.snapshot_ref.timeline_digest
                        ),
                        "recorded_at": record.recorded_at.isoformat(),
                    }
                )
            elif isinstance(record, WorkflowConfirmationRecord):
                confirmations.append(
                    {
                        "confirmation_record_id": (
                            record.confirmation_record_id
                        ),
                        "review_id": record.review_id,
                        "decision": record.decision,
                        "confirmed_by": record.user_confirmation.confirmed_by,
                        "recorded_at": record.recorded_at.isoformat(),
                        "diff_digest": record.diff_digest,
                    }
                )
            elif isinstance(record, EditingExecutionRunRecord):
                execution_events[record.run_id].append(record)
            elif isinstance(record, RollbackReviewRecord):
                rollback_reviews.append(
                    {
                        "review_id": record.review_id,
                        "proposal_id": record.proposal.proposal_id,
                        "source_run_id": record.proposal.source_run_id,
                        "proposal_digest": record.proposal_digest,
                        "change_count": len(record.proposal.changes),
                        "limitations": record.proposal.limitations,
                        "recorded_at": record.recorded_at.isoformat(),
                    }
                )
            elif isinstance(record, RollbackConfirmationRecord):
                rollback_confirmations.append(
                    {
                        "confirmation_id": record.confirmation_id,
                        "review_id": record.review_id,
                        "decision": record.decision,
                        "confirmed_by": record.confirmed_by,
                        "recorded_at": record.recorded_at.isoformat(),
                    }
                )
            elif isinstance(record, RollbackRunRecord):
                rollback_events[record.rollback_run_id].append(record)

        executions = []
        for run_id, events in execution_events.items():
            latest = events[-1]
            executions.append(
                {
                    "run_id": run_id,
                    "confirmation_record_id": (
                        latest.confirmation_record_id
                    ),
                    "execution_id": latest.execution_plan.execution_id,
                    "status": latest.status,
                    "status_history": tuple(
                        event.status for event in events
                    ),
                    "started_at": latest.started_at.isoformat(),
                    "finished_at": (
                        latest.finished_at.isoformat()
                        if latest.finished_at
                        else None
                    ),
                    "resulting_project_revision": (
                        latest.latest_checkpoint.project_revision
                    ),
                    "steps": tuple(
                        {
                            "sequence": step.sequence,
                            "step_id": step.request.step_id,
                            "tool_name": step.request.tool_name,
                            "request_id": step.request.request_id,
                            "result_id": step.result.result_id,
                            "status": step.result.status,
                            "before_revision": (
                                step.before_snapshot.revision
                            ),
                            "after_revision": step.after_snapshot.revision,
                        }
                        for step in latest.steps
                    ),
                    "error": (
                        None
                        if latest.error is None
                        else {
                            "code": latest.error.code,
                            "message": _safe_text(latest.error.message),
                            "recovery_action": (
                                None
                                if latest.error.recovery_action is None
                                else _safe_text(
                                    latest.error.recovery_action
                                )
                            ),
                        }
                    ),
                    "rollback_available": latest.status
                    in {"succeeded", "failed", "partial"},
                }
            )

        rollbacks = []
        for run_id, events in rollback_events.items():
            latest = events[-1]
            rollbacks.append(
                {
                    "rollback_run_id": run_id,
                    "source_run_id": latest.proposal.source_run_id,
                    "proposal_id": latest.proposal.proposal_id,
                    "status": latest.status,
                    "status_history": tuple(
                        event.status for event in events
                    ),
                    "started_at": latest.started_at.isoformat(),
                    "finished_at": (
                        latest.finished_at.isoformat()
                        if latest.finished_at
                        else None
                    ),
                    "restored_project_revision": (
                        latest.after_checkpoint.project_revision
                        if latest.after_checkpoint
                        else None
                    ),
                    "external_artifacts_changed": False,
                    "error": (
                        None
                        if latest.error is None
                        else {
                            "code": latest.error.code,
                            "message": _safe_text(latest.error.message),
                        }
                    ),
                }
            )

        recovery = any(
            item["status"] == "recovery_required"
            for item in (*executions, *rollbacks)
        )
        return WorkflowHistoryView(
            project_id=ledger.project_id,
            ledger_revision=ledger.revision,
            integrity_digest=ledger.integrity_digest,
            state=(
                "empty"
                if not ledger.entries
                else "recovery_required"
                if recovery
                else "active"
            ),
            plan_versions=tuple(plan_versions),
            reviews=tuple(reviews),
            confirmations=tuple(confirmations),
            executions=tuple(executions),
            rollback_reviews=tuple(rollback_reviews),
            rollback_confirmations=tuple(rollback_confirmations),
            rollbacks=tuple(rollbacks),
        )
