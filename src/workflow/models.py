"""Versioned immutable records for persisted review/execution/rollback history."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    DirectorPlan,
    EditingExecutionPlan,
    PlanReference,
    TimelineProjectDocument,
    UserConfirmationRecord,
)
from plan_review import (
    PlanDiffDocument,
    PlanDiffRequest,
    PreviewClipState,
    PreviewProjectSettings,
    ProposedExecutionReference,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshotReference


WORKFLOW_VERSION = "1.0.0"
WorkflowVersion = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GENESIS_DIGEST = "sha256:" + ("0" * 64)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    )


class WorkflowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: WorkflowVersion = WORKFLOW_VERSION


class WorkflowError(WorkflowModel):
    code: StableId
    message: str = Field(min_length=1)
    retryable: bool = False
    recovery_action: str | None = Field(default=None, min_length=1)


class DirectorPlanVersionRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.plan-version"] = (
        "vistora.workflow.plan-version"
    )
    record_id: StableId
    project_id: StableId
    plan: DirectorPlan
    plan_ref: PlanReference
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def plan_reference_is_exact(self) -> DirectorPlanVersionRecord:
        if self.plan_ref != PlanReference.from_plan(self.plan):
            raise ValueError("Plan version record has a mismatched plan digest")
        return self


class ReviewSessionRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.review-session"] = (
        "vistora.workflow.review-session"
    )
    review_id: StableId
    project_id: StableId
    request: PlanDiffRequest
    diff: PlanDiffDocument
    diff_digest: Sha256Digest
    status: Literal["reviewed"] = "reviewed"
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def review_binding_is_exact(self) -> ReviewSessionRecord:
        if self.diff.digest() != self.diff_digest:
            raise ValueError("Review diff digest is mismatched")
        if self.diff.request_digest != self.request.digest():
            raise ValueError("Review diff crosses request content")
        if self.diff.plan_ref != PlanReference.from_plan(
            self.request.director_plan
        ):
            raise ValueError("Review diff crosses Director plan")
        if self.diff.execution_ref != ProposedExecutionReference.from_execution(
            self.request.proposed_execution
        ):
            raise ValueError("Review diff crosses proposed execution")
        if self.diff.snapshot_ref != self.request.snapshot_ref:
            raise ValueError("Review diff crosses snapshot")
        if self.diff.registry_ref != self.request.registry_ref:
            raise ValueError("Review diff crosses registry schemas")
        return self


class WorkflowConfirmationRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.confirmation"] = (
        "vistora.workflow.confirmation"
    )
    confirmation_record_id: StableId
    project_id: StableId
    review_id: StableId
    user_confirmation: UserConfirmationRecord
    proposed_execution_ref: ProposedExecutionReference
    diff_digest: Sha256Digest
    snapshot_ref: TimelineSnapshotReference
    registry_ref: RegistrySchemaReference
    decision: Literal["confirmed", "rejected"]
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def decision_is_immutable_and_consistent(
        self,
    ) -> WorkflowConfirmationRecord:
        if self.user_confirmation.decision != self.decision:
            raise ValueError("Workflow and user confirmation decisions differ")
        if self.user_confirmation.recorded_at != self.recorded_at:
            raise ValueError("Workflow confirmation timestamp differs")
        return self


class ConfirmedExecutionBinding(WorkflowModel):
    """Exact persisted and runtime binding required before atomic execution."""

    schema_name: Literal["vistora.workflow.confirmed-execution-binding"] = (
        "vistora.workflow.confirmed-execution-binding"
    )
    project_id: StableId
    workflow_revision: int = Field(ge=1)
    confirmation_record_id: StableId
    review_id: StableId
    plan_ref: PlanReference
    proposed_execution_ref: ProposedExecutionReference
    diff_digest: Sha256Digest
    snapshot_ref: TimelineSnapshotReference
    registry_ref: RegistrySchemaReference


class ProjectCheckpoint(WorkflowModel):
    schema_name: Literal["vistora.workflow.project-checkpoint"] = (
        "vistora.workflow.project-checkpoint"
    )
    checkpoint_id: StableId
    project_id: StableId
    project_revision: int = Field(ge=1)
    snapshot_ref: TimelineSnapshotReference
    timeline_document: TimelineProjectDocument
    checkpoint_digest: Sha256Digest
    created_at: AwareDatetime
    reason: str = Field(min_length=1)

    @staticmethod
    def _content_payload(
        *,
        project_id: str,
        project_revision: int,
        snapshot_ref: TimelineSnapshotReference,
        timeline_document: TimelineProjectDocument,
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "project_revision": project_revision,
            "snapshot_ref": snapshot_ref.model_dump(mode="json"),
            "timeline_document": timeline_document.model_dump(mode="json"),
        }

    @classmethod
    def create(
        cls,
        *,
        checkpoint_id: str,
        project_id: str,
        project_revision: int,
        snapshot_ref: TimelineSnapshotReference,
        timeline_document: TimelineProjectDocument,
        created_at: datetime,
        reason: str,
    ) -> ProjectCheckpoint:
        payload = cls._content_payload(
            project_id=project_id,
            project_revision=project_revision,
            snapshot_ref=snapshot_ref,
            timeline_document=timeline_document,
        )
        return cls(
            checkpoint_id=checkpoint_id,
            project_id=project_id,
            project_revision=project_revision,
            snapshot_ref=snapshot_ref,
            timeline_document=timeline_document,
            checkpoint_digest=digest_json(payload),
            created_at=created_at,
            reason=reason,
        )

    @model_validator(mode="after")
    def checkpoint_is_self_verifying(self) -> ProjectCheckpoint:
        if self.snapshot_ref.project_id != self.timeline_document.project_id:
            raise ValueError("Checkpoint snapshot/document project mismatch")
        if self.snapshot_ref.revision != self.timeline_document.revision:
            raise ValueError("Checkpoint snapshot/document revision mismatch")
        timeline_digest = digest_json(
            self.timeline_document.timeline.model_dump(mode="json")
        )
        if self.snapshot_ref.timeline_digest != timeline_digest:
            raise ValueError("Checkpoint timeline digest is mismatched")
        expected = digest_json(
            self._content_payload(
                project_id=self.project_id,
                project_revision=self.project_revision,
                snapshot_ref=self.snapshot_ref,
                timeline_document=self.timeline_document,
            )
        )
        if self.checkpoint_digest != expected:
            raise ValueError("Checkpoint integrity digest is mismatched")
        return self


class ExecutionStepHistory(WorkflowModel):
    schema_name: Literal["vistora.workflow.execution-step"] = (
        "vistora.workflow.execution-step"
    )
    sequence: int = Field(ge=1)
    request: AtomicToolRequestEnvelope
    result: AtomicToolResultEnvelope
    before_snapshot: TimelineSnapshotReference
    after_snapshot: TimelineSnapshotReference

    @model_validator(mode="after")
    def request_result_linkage_is_exact(self) -> ExecutionStepHistory:
        if (
            self.result.request_id != self.request.request_id
            or self.result.execution_id != self.request.execution_id
            or self.result.step_id != self.request.step_id
            or self.result.tool_name != self.request.tool_name
        ):
            raise ValueError("Execution step request/result linkage differs")
        return self


ExecutionStatus = Literal[
    "execution_pending",
    "running",
    "succeeded",
    "failed",
    "partial",
    "recovery_required",
]


class EditingExecutionRunRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.execution-run"] = (
        "vistora.workflow.execution-run"
    )
    run_record_id: StableId
    run_id: StableId
    project_id: StableId
    confirmation_record_id: StableId
    execution_plan: EditingExecutionPlan
    status: ExecutionStatus
    failure_policy: Literal["stop_on_failure"] = "stop_on_failure"
    steps: tuple[ExecutionStepHistory, ...] = ()
    start_checkpoint: ProjectCheckpoint
    latest_checkpoint: ProjectCheckpoint
    started_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    error: WorkflowError | None = None

    @model_validator(mode="after")
    def execution_state_is_consistent(
        self,
    ) -> EditingExecutionRunRecord:
        if self.execution_plan.project_id != self.project_id:
            raise ValueError("Execution run crosses project identity")
        if self.start_checkpoint.project_id != self.project_id:
            raise ValueError("Execution start checkpoint crosses project")
        if self.latest_checkpoint.project_id != self.project_id:
            raise ValueError("Execution latest checkpoint crosses project")
        sequences = [step.sequence for step in self.steps]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("Execution steps require contiguous sequence")
        if any(
            step.request.execution_id != self.execution_plan.execution_id
            for step in self.steps
        ):
            raise ValueError("Execution history crosses execution identity")
        terminal = self.status in {
            "succeeded",
            "failed",
            "partial",
            "recovery_required",
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("Execution terminal timestamp is inconsistent")
        if self.status in {"failed", "partial", "recovery_required"}:
            if self.error is None:
                raise ValueError("Failed execution state requires an error")
        elif self.error is not None:
            raise ValueError("Successful/nonterminal execution has an error")
        if self.updated_at < self.started_at:
            raise ValueError("Execution update precedes start")
        return self


class RollbackChange(WorkflowModel):
    change_id: StableId
    sequence: int = Field(ge=1)
    relation_type: Literal["restores", "removes", "modifies"]
    entity_kind: Literal["clip", "project_settings"]
    entity_id: str = Field(min_length=1)
    track_key: str | None = None
    before: PreviewClipState | None = None
    after: PreviewClipState | None = None
    before_project: PreviewProjectSettings | None = None
    after_project: PreviewProjectSettings | None = None
    provenance_state: Literal[
        "current",
        "legacy_unknown",
        "stale",
        "orphaned",
        "deleted",
        "unknown",
    ] = "unknown"

    @model_validator(mode="after")
    def before_after_is_typed(self) -> RollbackChange:
        if self.entity_kind == "clip":
            if self.before is None and self.after is None:
                raise ValueError("Rollback clip change requires before/after")
            if (
                self.before_project is not None
                or self.after_project is not None
            ):
                raise ValueError("Rollback clip cannot carry project settings")
        else:
            if self.before_project is None or self.after_project is None:
                raise ValueError(
                    "Project-settings rollback requires before and after"
                )
            if self.before is not None or self.after is not None:
                raise ValueError(
                    "Project-settings rollback cannot carry clip states"
                )
        return self


class RollbackProposal(WorkflowModel):
    schema_name: Literal["vistora.workflow.rollback-proposal"] = (
        "vistora.workflow.rollback-proposal"
    )
    proposal_id: StableId
    project_id: StableId
    source_run_id: StableId
    current_checkpoint: ProjectCheckpoint
    target_checkpoint: ProjectCheckpoint
    changes: tuple[RollbackChange, ...]
    limitations: tuple[str, ...] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def rollback_is_exact_and_ordered(self) -> RollbackProposal:
        if (
            self.current_checkpoint.project_id != self.project_id
            or self.target_checkpoint.project_id != self.project_id
        ):
            raise ValueError("Rollback checkpoint crosses project identity")
        sequences = [change.sequence for change in self.changes]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("Rollback changes require contiguous sequence")
        ids = [change.change_id for change in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("Rollback change IDs must be unique")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class RollbackReviewRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.rollback-review"] = (
        "vistora.workflow.rollback-review"
    )
    review_id: StableId
    project_id: StableId
    proposal: RollbackProposal
    proposal_digest: Sha256Digest
    status: Literal["reviewed"] = "reviewed"
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def proposal_digest_is_exact(self) -> RollbackReviewRecord:
        if self.proposal.project_id != self.project_id:
            raise ValueError("Rollback review crosses project")
        if self.proposal.digest() != self.proposal_digest:
            raise ValueError("Rollback proposal digest is mismatched")
        return self


class RollbackConfirmationRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.rollback-confirmation"] = (
        "vistora.workflow.rollback-confirmation"
    )
    confirmation_id: StableId
    project_id: StableId
    review_id: StableId
    proposal_id: StableId
    proposal_digest: Sha256Digest
    decision: Literal["confirmed", "rejected"]
    confirmed_by: str = Field(min_length=1)
    recorded_at: AwareDatetime

    def confirms(self, proposal: RollbackProposal) -> bool:
        return (
            self.decision == "confirmed"
            and self.project_id == proposal.project_id
            and self.proposal_id == proposal.proposal_id
            and self.proposal_digest == proposal.digest()
        )


class RollbackToolRequest(WorkflowModel):
    schema_name: Literal["vistora.workflow.rollback-tool-request"] = (
        "vistora.workflow.rollback-tool-request"
    )
    request_id: StableId
    rollback_run_id: StableId
    project_id: StableId
    proposal_id: StableId
    confirmation_id: StableId
    tool_name: Literal["VideoRestoreTimelineCheckpointSkill"] = (
        "VideoRestoreTimelineCheckpointSkill"
    )
    requested_at: AwareDatetime


class RollbackToolResult(WorkflowModel):
    schema_name: Literal["vistora.workflow.rollback-tool-result"] = (
        "vistora.workflow.rollback-tool-result"
    )
    result_id: StableId
    request_id: StableId
    rollback_run_id: StableId
    tool_name: Literal["VideoRestoreTimelineCheckpointSkill"] = (
        "VideoRestoreTimelineCheckpointSkill"
    )
    status: Literal["success", "error"]
    payload: dict[str, Any] = Field(default_factory=dict)
    error: WorkflowError | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def result_is_consistent(self) -> RollbackToolResult:
        if self.finished_at < self.started_at:
            raise ValueError("Rollback result finishes before it starts")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("Rollback result error state is inconsistent")
        return self


RollbackStatus = Literal[
    "rollback_pending",
    "running",
    "succeeded",
    "failed",
    "recovery_required",
]


class RollbackRunRecord(WorkflowModel):
    schema_name: Literal["vistora.workflow.rollback-run"] = (
        "vistora.workflow.rollback-run"
    )
    run_record_id: StableId
    rollback_run_id: StableId
    project_id: StableId
    rollback_confirmation_id: StableId
    proposal: RollbackProposal
    status: RollbackStatus
    request: RollbackToolRequest | None = None
    result: RollbackToolResult | None = None
    before_checkpoint: ProjectCheckpoint
    after_checkpoint: ProjectCheckpoint | None = None
    started_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    error: WorkflowError | None = None

    @model_validator(mode="after")
    def rollback_run_is_consistent(self) -> RollbackRunRecord:
        if self.proposal.project_id != self.project_id:
            raise ValueError("Rollback run crosses project")
        terminal = self.status in {
            "succeeded",
            "failed",
            "recovery_required",
        }
        if terminal != (self.finished_at is not None):
            raise ValueError("Rollback terminal timestamp is inconsistent")
        if self.status == "succeeded":
            if (
                self.result is None
                or self.result.status != "success"
                or self.after_checkpoint is None
                or self.error is not None
            ):
                raise ValueError("Successful rollback record is incomplete")
        if self.status in {"failed", "recovery_required"}:
            if self.error is None:
                raise ValueError("Failed rollback requires an error")
        return self


WorkflowRecord = Annotated[
    DirectorPlanVersionRecord
    | ReviewSessionRecord
    | WorkflowConfirmationRecord
    | EditingExecutionRunRecord
    | RollbackReviewRecord
    | RollbackConfirmationRecord
    | RollbackRunRecord,
    Field(discriminator="schema_name"),
]


class WorkflowLedgerEntry(WorkflowModel):
    schema_name: Literal["vistora.workflow.ledger-entry"] = (
        "vistora.workflow.ledger-entry"
    )
    sequence: int = Field(ge=1)
    entry_id: StableId
    previous_entry_digest: Sha256Digest
    record: WorkflowRecord
    recorded_at: AwareDatetime
    entry_digest: Sha256Digest

    @staticmethod
    def _payload(
        *,
        sequence: int,
        entry_id: str,
        previous_entry_digest: str,
        record: WorkflowRecord,
        recorded_at: datetime,
    ) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "entry_id": entry_id,
            "previous_entry_digest": previous_entry_digest,
            "record": record.model_dump(mode="json"),
            "recorded_at": recorded_at.isoformat(),
        }

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        entry_id: str,
        previous_entry_digest: str,
        record: WorkflowRecord,
        recorded_at: datetime,
    ) -> WorkflowLedgerEntry:
        payload = cls._payload(
            sequence=sequence,
            entry_id=entry_id,
            previous_entry_digest=previous_entry_digest,
            record=record,
            recorded_at=recorded_at,
        )
        return cls(
            **payload,
            entry_digest=digest_json(payload),
        )

    @model_validator(mode="after")
    def digest_is_exact(self) -> WorkflowLedgerEntry:
        expected = digest_json(
            self._payload(
                sequence=self.sequence,
                entry_id=self.entry_id,
                previous_entry_digest=self.previous_entry_digest,
                record=self.record,
                recorded_at=self.recorded_at,
            )
        )
        if self.entry_digest != expected:
            raise ValueError("Workflow ledger entry digest is mismatched")
        return self


class WorkflowLedger(WorkflowModel):
    schema_name: Literal["vistora.workflow-ledger"] = (
        "vistora.workflow-ledger"
    )
    project_id: StableId
    revision: int = Field(ge=0)
    migration_source: Literal["native", "legacy.workflow.v0"] = "native"
    entries: tuple[WorkflowLedgerEntry, ...] = ()
    integrity_digest: Sha256Digest

    @model_validator(mode="before")
    @classmethod
    def migrate_empty_v0(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and "schema_name" not in value
            and set(value).issubset({"project_id", "entries"})
        ):
            project_id = value.get("project_id")
            entries = value.get("entries", [])
            if entries:
                return value
            return {
                "schema_name": "vistora.workflow-ledger",
                "schema_version": WORKFLOW_VERSION,
                "project_id": project_id,
                "revision": 0,
                "migration_source": "legacy.workflow.v0",
                "entries": [],
                "integrity_digest": digest_json([]),
            }
        return value

    @classmethod
    def empty(cls, project_id: str) -> WorkflowLedger:
        return cls(
            project_id=project_id,
            revision=0,
            entries=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def chain_and_transitions_are_valid(self) -> WorkflowLedger:
        if self.revision != len(self.entries):
            raise ValueError("Workflow revision must equal entry count")
        previous = GENESIS_DIGEST
        ids: set[str] = set()
        plan_versions: dict[tuple[str, int], DirectorPlanVersionRecord] = {}
        reviews: dict[str, ReviewSessionRecord] = {}
        confirmations: dict[str, WorkflowConfirmationRecord] = {}
        confirmed_review_ids: set[str] = set()
        run_status: dict[str, ExecutionStatus] = {}
        executed_confirmations: dict[str, str] = {}
        rollback_reviews: dict[str, RollbackReviewRecord] = {}
        rollback_confirmations: dict[str, RollbackConfirmationRecord] = {}
        rollback_status: dict[str, RollbackStatus] = {}
        applied_rollback_confirmations: dict[str, str] = {}

        execution_transitions = {
            None: {"execution_pending"},
            "execution_pending": {"running", "recovery_required"},
            "running": {
                "running",
                "succeeded",
                "failed",
                "partial",
                "recovery_required",
            },
        }
        rollback_transitions = {
            None: {"rollback_pending"},
            "rollback_pending": {"running", "recovery_required"},
            "running": {"succeeded", "failed", "recovery_required"},
        }
        for index, entry in enumerate(self.entries, start=1):
            if entry.sequence != index:
                raise ValueError("Workflow sequence must be contiguous")
            if entry.previous_entry_digest != previous:
                raise ValueError("Workflow digest chain is broken")
            if entry.entry_id in ids:
                raise ValueError("Workflow entry IDs must be unique")
            ids.add(entry.entry_id)
            previous = entry.entry_digest
            record = entry.record
            if record.project_id != self.project_id:
                raise ValueError("Workflow record crosses ledger project")

            if isinstance(record, DirectorPlanVersionRecord):
                key = (record.plan.plan_id, record.plan.plan_version)
                if key in plan_versions:
                    raise ValueError("Plan version record is duplicated")
                previous_versions = [
                    version
                    for (plan_id, version) in plan_versions
                    if plan_id == record.plan.plan_id
                ]
                if previous_versions and record.plan.plan_version <= max(
                    previous_versions
                ):
                    raise ValueError("Plan versions must increase")
                plan_versions[key] = record
            elif isinstance(record, ReviewSessionRecord):
                if record.review_id in reviews:
                    raise ValueError("Review session is duplicated")
                plan_ref = record.diff.plan_ref
                if (
                    plan_ref.plan_id,
                    plan_ref.plan_version,
                ) not in plan_versions:
                    raise ValueError("Review has no persisted plan version")
                if any(
                    current.diff_digest == record.diff_digest
                    for current in reviews.values()
                ):
                    raise ValueError("Review diff is duplicated")
                reviews[record.review_id] = record
            elif isinstance(record, WorkflowConfirmationRecord):
                if record.confirmation_record_id in confirmations:
                    raise ValueError("Confirmation record is duplicated")
                review = reviews.get(record.review_id)
                if review is None:
                    raise ValueError("Confirmation has no review")
                if record.review_id in confirmed_review_ids:
                    raise ValueError("Review confirmation cannot be replayed")
                if (
                    record.user_confirmation.plan_ref != review.diff.plan_ref
                    or record.proposed_execution_ref
                    != review.diff.execution_ref
                    or record.diff_digest != review.diff_digest
                    or record.snapshot_ref != review.diff.snapshot_ref
                    or record.registry_ref != review.diff.registry_ref
                ):
                    raise ValueError("Confirmation binding differs from review")
                confirmations[record.confirmation_record_id] = record
                confirmed_review_ids.add(record.review_id)
            elif isinstance(record, EditingExecutionRunRecord):
                confirmation = confirmations.get(
                    record.confirmation_record_id
                )
                if (
                    confirmation is None
                    or confirmation.decision != "confirmed"
                ):
                    raise ValueError(
                        "Execution requires an exact confirmed review"
                    )
                used_by = executed_confirmations.get(
                    record.confirmation_record_id
                )
                if used_by is not None and used_by != record.run_id:
                    raise ValueError(
                        "Confirmation cannot be replayed in another execution"
                    )
                executed_confirmations[
                    record.confirmation_record_id
                ] = record.run_id
                prior = run_status.get(record.run_id)
                allowed = execution_transitions.get(prior, set())
                if record.status not in allowed:
                    raise ValueError(
                        f"Illegal execution transition {prior!r} -> "
                        f"{record.status!r}"
                    )
                run_status[record.run_id] = record.status
            elif isinstance(record, RollbackReviewRecord):
                if record.review_id in rollback_reviews:
                    raise ValueError("Rollback review is duplicated")
                terminal = run_status.get(record.proposal.source_run_id)
                if terminal not in {"succeeded", "failed", "partial"}:
                    raise ValueError(
                        "Rollback requires a terminal execution run"
                    )
                rollback_reviews[record.review_id] = record
            elif isinstance(record, RollbackConfirmationRecord):
                if record.confirmation_id in rollback_confirmations:
                    raise ValueError("Rollback confirmation is duplicated")
                review = rollback_reviews.get(record.review_id)
                if review is None or not (
                    record.proposal_id == review.proposal.proposal_id
                    and record.proposal_digest == review.proposal_digest
                ):
                    raise ValueError(
                        "Rollback confirmation differs from review"
                    )
                if any(
                    current.review_id == record.review_id
                    for current in rollback_confirmations.values()
                ):
                    raise ValueError(
                        "Rollback confirmation cannot be replayed"
                    )
                rollback_confirmations[record.confirmation_id] = record
            elif isinstance(record, RollbackRunRecord):
                confirmation = rollback_confirmations.get(
                    record.rollback_confirmation_id
                )
                if (
                    confirmation is None
                    or not confirmation.confirms(record.proposal)
                ):
                    raise ValueError(
                        "Rollback run requires exact confirmation"
                    )
                used_by = applied_rollback_confirmations.get(
                    record.rollback_confirmation_id
                )
                if (
                    used_by is not None
                    and used_by != record.rollback_run_id
                ):
                    raise ValueError(
                        "Rollback confirmation cannot be replayed"
                    )
                applied_rollback_confirmations[
                    record.rollback_confirmation_id
                ] = record.rollback_run_id
                prior = rollback_status.get(record.rollback_run_id)
                allowed = rollback_transitions.get(prior, set())
                if record.status not in allowed:
                    raise ValueError(
                        f"Illegal rollback transition {prior!r} -> "
                        f"{record.status!r}"
                    )
                rollback_status[record.rollback_run_id] = record.status

        expected_integrity = digest_json(
            [entry.entry_digest for entry in self.entries]
        )
        if self.integrity_digest != expected_integrity:
            raise ValueError("Workflow ledger integrity digest is mismatched")
        return self
