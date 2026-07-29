"""Confirmed workflow application boundary for review, execution, and restore."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    EditingExecutionPlan,
    PlanReference,
    TimelineProjectDocument,
    ToolError,
    UserConfirmationRecord,
)
from core import timeline_manager
from plan_review import (
    PlanDiffRequest,
    PlanReviewService,
    PreviewClipState,
    PreviewProjectSettings,
    RegistrySchemaReference,
)
from timeline_query import (
    TimelineSnapshot,
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.recording import ConfirmedTraceRecorder

from .models import (
    ConfirmedExecutionBinding,
    DirectorPlanVersionRecord,
    EditingExecutionRunRecord,
    ExecutionStepHistory,
    ProjectCheckpoint,
    ReviewSessionRecord,
    RollbackChange,
    RollbackConfirmationRecord,
    RollbackProposal,
    RollbackReviewRecord,
    RollbackRunRecord,
    RollbackToolRequest,
    RollbackToolResult,
    WorkflowConfirmationRecord,
    WorkflowError,
    WorkflowLedger,
    digest_json,
)
from .store import WorkflowLedgerSession, WorkflowStore


Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]
SnapshotProvider = Callable[[], TimelineSnapshot]
TimelineProvider = Callable[[], Any]


class WorkflowApplicationError(ValueError):
    """A fail-closed workflow transition or freshness error."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _stable_id(prefix: str, value: Any) -> str:
    digest = digest_json(value).removeprefix("sha256:")
    return f"{prefix}_{digest[:24]}"


def _clip_state(track_key: str, clip: Any) -> PreviewClipState:
    return PreviewClipState(
        clip_id=clip.clip_id,
        track_key=track_key,
        order_index=clip.order_index,
        source_id=clip.source.source_id,
        source_name=clip.source.display_name,
        trim_in_seconds=clip.trim_in_seconds,
        trim_out_seconds=clip.trim_out_seconds,
        timeline_start_seconds=clip.timeline_start_seconds,
        timeline_end_seconds=clip.timeline_end_seconds,
        effective_duration_seconds=clip.effective_duration_seconds,
        speed_factor=clip.speed_factor,
        keep_audio=clip.keep_audio,
        reverse=clip.reverse,
        rotate_degrees=clip.rotate_degrees,
    )


def _clip_map(snapshot: TimelineSnapshot) -> dict[tuple[str, str], Any]:
    return {
        (track.track_key, clip.clip_id): clip
        for track in snapshot.tracks
        for clip in track.clips
    }


class WorkflowApplicationService:
    """Persist exact review decisions and dispatch only confirmed atomic tools."""

    def __init__(
        self,
        *,
        store: WorkflowStore,
        registry: Mapping[str, Any],
        snapshot_provider: SnapshotProvider = (
            TimelineSnapshotService.snapshot_current
        ),
        timeline_provider: TimelineProvider = (
            timeline_manager.TimelineManager.get_current_timeline
        ),
        clock: Clock = _utc_now,
        id_factory: IdFactory = _random_id,
    ) -> None:
        self.store = store
        self.registry = registry
        self.snapshot_provider = snapshot_provider
        self.timeline_provider = timeline_provider
        self.clock = clock
        self.id_factory = id_factory

    @classmethod
    def for_current_project(
        cls,
        registry: Mapping[str, Any],
    ) -> WorkflowApplicationService:
        return cls(
            store=WorkflowStore.for_project_file(
                timeline_manager.PROJECT_FILE
            ),
            registry=registry,
        )

    def _append(
        self,
        session: WorkflowLedgerSession,
        record: Any,
    ) -> None:
        now = self.clock()
        session.append(
            record,
            entry_id=self.id_factory("entry"),
            recorded_at=now,
        )

    def _current(self, exact: TimelineSnapshotReference) -> TimelineSnapshot:
        current = self.snapshot_provider()
        if TimelineSnapshotReference.from_snapshot(current) != exact:
            raise WorkflowApplicationError(
                "Timeline snapshot drifted; regenerate the workflow review"
            )
        return current

    def _registry(self, exact: RegistrySchemaReference) -> None:
        if RegistrySchemaReference.from_registry(self.registry) != exact:
            raise WorkflowApplicationError(
                "Atomic registry/schema drifted; regenerate the workflow review"
            )

    def _checkpoint(
        self,
        ledger: WorkflowLedger,
        *,
        project_id: str,
        reason: str,
        snapshot: TimelineSnapshot | None = None,
        checkpoint_id: str | None = None,
        created_at: datetime | None = None,
    ) -> ProjectCheckpoint:
        snapshot = snapshot or self.snapshot_provider()
        document = TimelineProjectDocument.model_validate(
            self.timeline_provider()
        )
        current_ref = TimelineSnapshotReference.from_snapshot(snapshot)
        verified = TimelineSnapshotService.snapshot(
            document,
            expected_reference=current_ref,
        )
        if TimelineSnapshotReference.from_snapshot(verified) != current_ref:
            raise WorkflowApplicationError(
                "Checkpoint document differs from current snapshot"
            )
        revisions = []
        for entry in ledger.entries:
            record = entry.record
            for candidate in (
                getattr(record, "start_checkpoint", None),
                getattr(record, "latest_checkpoint", None),
                getattr(record, "before_checkpoint", None),
                getattr(record, "after_checkpoint", None),
                getattr(
                    getattr(record, "proposal", None),
                    "current_checkpoint",
                    None,
                ),
                getattr(
                    getattr(record, "proposal", None),
                    "target_checkpoint",
                    None,
                ),
            ):
                if candidate is not None:
                    revisions.append(candidate.project_revision)
        return ProjectCheckpoint.create(
            checkpoint_id=checkpoint_id or self.id_factory("checkpoint"),
            project_id=project_id,
            project_revision=max(revisions, default=0) + 1,
            snapshot_ref=current_ref,
            timeline_document=document,
            created_at=created_at or self.clock(),
            reason=reason,
        )

    @staticmethod
    def _records(ledger: WorkflowLedger, kind: type) -> list[Any]:
        return [
            entry.record
            for entry in ledger.entries
            if isinstance(entry.record, kind)
        ]

    def confirmed_execution_binding(
        self,
        confirmation_record_id: str,
    ) -> ConfirmedExecutionBinding:
        """Resolve and revalidate the exact immutable execution gate."""

        ledger = self.store.load()
        confirmations = {
            record.confirmation_record_id: record
            for record in self._records(
                ledger,
                WorkflowConfirmationRecord,
            )
        }
        confirmation = confirmations.get(confirmation_record_id)
        if confirmation is None or confirmation.decision != "confirmed":
            raise WorkflowApplicationError(
                "Execution requires an exact persisted confirmation"
            )
        if any(
            record.confirmation_record_id == confirmation_record_id
            for record in self._records(
                ledger,
                EditingExecutionRunRecord,
            )
        ):
            raise WorkflowApplicationError(
                "Confirmation has already been used for an execution run"
            )
        reviews = {
            record.review_id: record
            for record in self._records(ledger, ReviewSessionRecord)
        }
        review = reviews.get(confirmation.review_id)
        if review is None:
            raise WorkflowApplicationError(
                "Confirmation references a missing review"
            )
        plan_ref = PlanReference.from_plan(review.request.director_plan)
        if confirmation.user_confirmation.plan_ref != plan_ref:
            raise WorkflowApplicationError(
                "Confirmation crosses the reviewed Director plan"
            )
        if confirmation.proposed_execution_ref != review.diff.execution_ref:
            raise WorkflowApplicationError(
                "Confirmation crosses the reviewed execution proposal"
            )
        if confirmation.diff_digest != review.diff_digest:
            raise WorkflowApplicationError(
                "Confirmation crosses the reviewed plan diff"
            )
        if confirmation.snapshot_ref != review.diff.snapshot_ref:
            raise WorkflowApplicationError(
                "Confirmation crosses the reviewed timeline snapshot"
            )
        if confirmation.registry_ref != review.diff.registry_ref:
            raise WorkflowApplicationError(
                "Confirmation crosses the reviewed registry schemas"
            )

        self._current(confirmation.snapshot_ref)
        self._registry(confirmation.registry_ref)
        regenerated = PlanReviewService.review(
            review.request,
            self.snapshot_provider(),
            self.registry,
        )
        if regenerated.diff_digest != confirmation.diff_digest:
            raise WorkflowApplicationError(
                "Plan diff drifted immediately before execution"
            )
        return ConfirmedExecutionBinding(
            project_id=confirmation.project_id,
            workflow_revision=ledger.revision,
            confirmation_record_id=confirmation.confirmation_record_id,
            review_id=review.review_id,
            plan_ref=plan_ref,
            proposed_execution_ref=confirmation.proposed_execution_ref,
            diff_digest=confirmation.diff_digest,
            snapshot_ref=confirmation.snapshot_ref,
            registry_ref=confirmation.registry_ref,
        )

    def record_review(self, request: PlanDiffRequest) -> ReviewSessionRecord:
        snapshot = self._current(request.snapshot_ref)
        self._registry(request.registry_ref)
        envelope = PlanReviewService.review(
            request,
            snapshot,
            self.registry,
        )
        if (
            envelope.review_state != "current"
            or envelope.diff is None
            or envelope.diff_digest is None
        ):
            raise WorkflowApplicationError(envelope.message)
        if envelope.diff.review_status == "blocked":
            raise WorkflowApplicationError(
                "Blocked plan diffs cannot become persisted reviews"
            )
        logical_project_id = (
            self.store.load().project_id
            if self.store.path.exists()
            else request.snapshot_ref.project_id
        )
        now = self.clock()
        plan_record = DirectorPlanVersionRecord(
            record_id=self.id_factory("plan_record"),
            project_id=logical_project_id,
            plan=request.director_plan,
            plan_ref=PlanReference.from_plan(request.director_plan),
            recorded_at=now,
        )
        review = ReviewSessionRecord(
            review_id=self.id_factory("review"),
            project_id=logical_project_id,
            request=request,
            diff=envelope.diff,
            diff_digest=envelope.diff_digest,
            recorded_at=now,
        )
        with self.store.exclusive(
            project_id=logical_project_id
        ) as session:
            known = {
                (record.plan.plan_id, record.plan.plan_version): record
                for record in self._records(
                    session.ledger,
                    DirectorPlanVersionRecord,
                )
            }
            key = (
                request.director_plan.plan_id,
                request.director_plan.plan_version,
            )
            if key in known:
                if known[key].plan_ref != plan_record.plan_ref:
                    raise WorkflowApplicationError(
                        "Persisted plan version content has drifted"
                    )
            else:
                self._append(session, plan_record)
            self._append(session, review)
        return review

    def confirm_review(
        self,
        review_id: str,
        *,
        confirmed_by: str,
        decision: Literal["confirmed", "rejected"],
    ) -> WorkflowConfirmationRecord:
        ledger = self.store.load()
        reviews = {
            record.review_id: record
            for record in self._records(ledger, ReviewSessionRecord)
        }
        review = reviews.get(review_id)
        if review is None:
            raise WorkflowApplicationError("Unknown workflow review")
        self._current(review.diff.snapshot_ref)
        self._registry(review.diff.registry_ref)
        regenerated = PlanReviewService.review(
            review.request,
            self.snapshot_provider(),
            self.registry,
        )
        if (
            regenerated.review_state != "current"
            or regenerated.diff_digest != review.diff_digest
        ):
            raise WorkflowApplicationError(
                "Reviewed plan diff drifted before confirmation"
            )
        now = self.clock()
        user = UserConfirmationRecord.for_plan(
            confirmation_id=self.id_factory("confirmation"),
            plan=review.request.director_plan,
            confirmed_by=confirmed_by,
            decision=decision,
            recorded_at=now,
        )
        record = WorkflowConfirmationRecord(
            confirmation_record_id=self.id_factory(
                "workflow_confirmation"
            ),
            project_id=review.project_id,
            review_id=review.review_id,
            user_confirmation=user,
            proposed_execution_ref=review.diff.execution_ref,
            diff_digest=review.diff_digest,
            snapshot_ref=review.diff.snapshot_ref,
            registry_ref=review.diff.registry_ref,
            decision=decision,
            recorded_at=now,
        )
        self.store.append(
            record,
            entry_id=self.id_factory("entry"),
            recorded_at=now,
            expected_revision=ledger.revision,
        )
        return record

    def run_confirmed_execution(
        self,
        confirmation_record_id: str,
        *,
        expected_binding: ConfirmedExecutionBinding | None = None,
    ) -> EditingExecutionRunRecord:
        binding = self.confirmed_execution_binding(confirmation_record_id)
        if expected_binding is not None and binding != expected_binding:
            raise WorkflowApplicationError(
                "Confirmed execution binding changed before dispatch"
            )
        ledger = self.store.load(binding.project_id)
        confirmations = {
            record.confirmation_record_id: record
            for record in self._records(
                ledger,
                WorkflowConfirmationRecord,
            )
        }
        confirmation = confirmations.get(confirmation_record_id)
        if confirmation is None:
            raise WorkflowApplicationError(
                "Confirmed execution binding disappeared before dispatch"
            )
        reviews = {
            record.review_id: record
            for record in self._records(ledger, ReviewSessionRecord)
        }
        review = reviews[confirmation.review_id]

        with self.store.exclusive(
            project_id=ledger.project_id,
            expected_revision=binding.workflow_revision,
        ) as session:
            current_binding = ConfirmedExecutionBinding(
                project_id=confirmation.project_id,
                workflow_revision=session.ledger.revision,
                confirmation_record_id=confirmation.confirmation_record_id,
                review_id=review.review_id,
                plan_ref=PlanReference.from_plan(
                    review.request.director_plan
                ),
                proposed_execution_ref=confirmation.proposed_execution_ref,
                diff_digest=confirmation.diff_digest,
                snapshot_ref=confirmation.snapshot_ref,
                registry_ref=confirmation.registry_ref,
            )
            if current_binding != binding:
                raise WorkflowApplicationError(
                    "Confirmed execution binding changed before dispatch"
                )
            self._current(confirmation.snapshot_ref)
            self._registry(confirmation.registry_ref)
            regenerated = PlanReviewService.review(
                review.request,
                self.snapshot_provider(),
                self.registry,
            )
            if regenerated.diff_digest != confirmation.diff_digest:
                raise WorkflowApplicationError(
                    "Plan diff drifted immediately before execution"
                )
            execution = EditingExecutionPlan.from_confirmed_plan(
                execution_id=(
                    review.request.proposed_execution.proposal_execution_id
                ),
                project_id=confirmation.project_id,
                director_plan=review.request.director_plan,
                confirmation=confirmation.user_confirmation,
            ).model_copy(update={"created_at": self.clock()})
            now = self.clock()
            run_id = self.id_factory("execution_run")
            start = self._checkpoint(
                session.ledger,
                project_id=confirmation.project_id,
                reason=f"before execution {run_id}",
            )
            pending = EditingExecutionRunRecord(
                run_record_id=self.id_factory("run_record"),
                run_id=run_id,
                project_id=confirmation.project_id,
                confirmation_record_id=confirmation_record_id,
                execution_plan=execution,
                status="execution_pending",
                start_checkpoint=start,
                latest_checkpoint=start,
                started_at=now,
                updated_at=now,
            )
            self._append(session, pending)
            running = pending.model_copy(
                update={
                    "run_record_id": self.id_factory("run_record"),
                    "status": "running",
                    "updated_at": self.clock(),
                }
            )
            self._append(session, running)

            histories: list[ExecutionStepHistory] = []
            latest = start
            failure: WorkflowError | None = None
            for sequence, step in enumerate(execution.steps, start=1):
                before = self.snapshot_provider()
                request = AtomicToolRequestEnvelope.from_execution_plan(
                    request_id=self.id_factory("atomic_request"),
                    execution_plan=execution,
                    step_id=step.step_id,
                ).model_copy(update={"requested_at": self.clock()})
                started = self.clock()
                try:
                    validated = request.validate_against_registry(
                        self.registry
                    )
                    payload = self.registry[request.tool_name].execute(
                        validated.model_dump(mode="python")
                    )
                    result = AtomicToolResultEnvelope(
                        result_id=self.id_factory("atomic_result"),
                        request_id=request.request_id,
                        execution_id=request.execution_id,
                        step_id=request.step_id,
                        tool_name=request.tool_name,
                        status="success",
                        payload=payload,
                        started_at=started,
                        finished_at=self.clock(),
                    )
                except Exception as exc:
                    result = AtomicToolResultEnvelope(
                        result_id=self.id_factory("atomic_result"),
                        request_id=request.request_id,
                        execution_id=request.execution_id,
                        step_id=request.step_id,
                        tool_name=request.tool_name,
                        status="error",
                        error=ToolError(
                            code="atomic_dispatch_failed",
                            message=str(exc),
                        ),
                        started_at=started,
                        finished_at=self.clock(),
                    )
                after = self.snapshot_provider()
                history = ExecutionStepHistory(
                    sequence=sequence,
                    request=request,
                    result=result,
                    before_snapshot=TimelineSnapshotReference.from_snapshot(
                        before
                    ),
                    after_snapshot=TimelineSnapshotReference.from_snapshot(
                        after
                    ),
                )
                histories.append(history)
                try:
                    ConfirmedTraceRecorder.record(
                        execution,
                        request,
                        result,
                        before,
                        after,
                    )
                except Exception as exc:
                    failure = WorkflowError(
                        code="trace_persistence_failed",
                        message=str(exc),
                        recovery_action=(
                            "Inspect timeline and trace sidecars before "
                            "continuing."
                        ),
                    )
                latest = self._checkpoint(
                    session.ledger,
                    project_id=confirmation.project_id,
                    reason=(
                        f"after execution {run_id} step {sequence}"
                    ),
                    snapshot=after,
                )
                running = running.model_copy(
                    update={
                        "run_record_id": self.id_factory("run_record"),
                        "steps": tuple(histories),
                        "latest_checkpoint": latest,
                        "updated_at": self.clock(),
                    }
                )
                self._append(session, running)
                if result.status == "error":
                    failure = WorkflowError(
                        code="atomic_dispatch_failed",
                        message=result.error.message,
                        recovery_action=(
                            "Review recorded step history and create a "
                            "separate rollback proposal if safe."
                        ),
                    )
                if failure is not None:
                    break

            finished = self.clock()
            if failure is None:
                status = "succeeded"
            elif latest.snapshot_ref != start.snapshot_ref:
                status = "partial"
            elif failure.code == "trace_persistence_failed":
                status = "recovery_required"
            else:
                status = "failed"
            terminal = running.model_copy(
                update={
                    "run_record_id": self.id_factory("run_record"),
                    "status": status,
                    "steps": tuple(histories),
                    "latest_checkpoint": latest,
                    "updated_at": finished,
                    "finished_at": finished,
                    "error": failure,
                }
            )
            self._append(session, terminal)
            return terminal

    def recover_interrupted_runs(self, project_id: str) -> WorkflowLedger:
        ledger = self.store.load(project_id)
        with self.store.exclusive(
            project_id=project_id,
            expected_revision=ledger.revision,
        ) as session:
            execution_latest: dict[str, EditingExecutionRunRecord] = {}
            rollback_latest: dict[str, RollbackRunRecord] = {}
            for entry in session.ledger.entries:
                if isinstance(entry.record, EditingExecutionRunRecord):
                    execution_latest[entry.record.run_id] = entry.record
                elif isinstance(entry.record, RollbackRunRecord):
                    rollback_latest[
                        entry.record.rollback_run_id
                    ] = entry.record
            for record in execution_latest.values():
                if record.status in {"execution_pending", "running"}:
                    now = self.clock()
                    recovered = record.model_copy(
                        update={
                            "run_record_id": self.id_factory("run_record"),
                            "status": "recovery_required",
                            "updated_at": now,
                            "finished_at": now,
                            "error": WorkflowError(
                                code="interrupted_execution",
                                message=(
                                    "Execution ended without a terminal "
                                    "record and requires inspection."
                                ),
                                recovery_action=(
                                    "Inspect the latest checkpoint before "
                                    "creating a rollback proposal."
                                ),
                            ),
                        }
                    )
                    self._append(session, recovered)
            for record in rollback_latest.values():
                if record.status in {"rollback_pending", "running"}:
                    now = self.clock()
                    recovered = record.model_copy(
                        update={
                            "run_record_id": self.id_factory("run_record"),
                            "status": "recovery_required",
                            "updated_at": now,
                            "finished_at": now,
                            "error": WorkflowError(
                                code="interrupted_rollback",
                                message=(
                                    "Rollback ended without a terminal record"
                                ),
                                recovery_action=(
                                    "Inspect current timeline and checkpoint "
                                    "integrity."
                                ),
                            ),
                        }
                    )
                    self._append(session, recovered)
            return session.ledger

    def propose_rollback(self, source_run_id: str) -> RollbackReviewRecord:
        ledger = self.store.load()
        runs = [
            record
            for record in self._records(
                ledger,
                EditingExecutionRunRecord,
            )
            if record.run_id == source_run_id
        ]
        if not runs or runs[-1].status not in {
            "succeeded",
            "failed",
            "partial",
        }:
            raise WorkflowApplicationError(
                "Rollback requires a completed execution run"
            )
        source = runs[-1]
        current = self._current(source.latest_checkpoint.snapshot_ref)
        if any(
            record.proposal.source_run_id == source_run_id
            for record in self._records(ledger, RollbackReviewRecord)
        ):
            raise WorkflowApplicationError(
                "Execution run already has a persisted rollback review"
            )
        with self.store.exclusive(
            project_id=ledger.project_id,
            expected_revision=ledger.revision,
        ) as session:
            deterministic_time = source.finished_at
            if deterministic_time is None:
                raise WorkflowApplicationError(
                    "Rollback source run has no terminal timestamp"
                )
            current_ref = TimelineSnapshotReference.from_snapshot(current)
            checkpoint_id = _stable_id(
                "checkpoint",
                {
                    "source_run_id": source_run_id,
                    "current": current_ref.model_dump(mode="json"),
                    "target": source.start_checkpoint.checkpoint_digest,
                },
            )
            current_checkpoint = self._checkpoint(
                session.ledger,
                project_id=ledger.project_id,
                reason=f"rollback review for {source_run_id}",
                snapshot=current,
                checkpoint_id=checkpoint_id,
                created_at=deterministic_time,
            )
            target_snapshot = TimelineSnapshotService.snapshot(
                source.start_checkpoint.timeline_document
            )
            current_clips = _clip_map(current)
            target_clips = _clip_map(target_snapshot)
            changes: list[RollbackChange] = []
            for sequence, key in enumerate(
                sorted(current_clips.keys() | target_clips.keys()),
                start=1,
            ):
                before_clip = current_clips.get(key)
                after_clip = target_clips.get(key)
                if before_clip == after_clip:
                    continue
                changes.append(
                    RollbackChange(
                        change_id=_stable_id(
                            "rollback_change",
                            {
                                "source_run_id": source_run_id,
                                "track_key": key[0],
                                "entity_id": key[1],
                                "before": (
                                    None
                                    if before_clip is None
                                    else _clip_state(
                                        key[0],
                                        before_clip,
                                    ).model_dump(mode="json")
                                ),
                                "after": (
                                    None
                                    if after_clip is None
                                    else _clip_state(
                                        key[0],
                                        after_clip,
                                    ).model_dump(mode="json")
                                ),
                            },
                        ),
                        sequence=len(changes) + 1,
                        relation_type=(
                            "restores"
                            if before_clip is None
                            else "removes"
                            if after_clip is None
                            else "modifies"
                        ),
                        entity_kind="clip",
                        entity_id=key[1],
                        track_key=key[0],
                        before=(
                            None
                            if before_clip is None
                            else _clip_state(key[0], before_clip)
                        ),
                        after=(
                            None
                            if after_clip is None
                            else _clip_state(key[0], after_clip)
                        ),
                        provenance_state=(
                            "legacy_unknown"
                            if (
                                before_clip is not None
                                and before_clip.provenance.origin_kind
                                == "legacy_unknown"
                            )
                            else "current"
                        ),
                    )
                )
            current_project = PreviewProjectSettings(
                width=current.width,
                height=current.height,
                fps=current.fps,
            )
            target_project = PreviewProjectSettings(
                width=target_snapshot.width,
                height=target_snapshot.height,
                fps=target_snapshot.fps,
            )
            if current_project != target_project:
                changes.append(
                    RollbackChange(
                        change_id=_stable_id(
                            "rollback_change",
                            {
                                "source_run_id": source_run_id,
                                "before": current_project.model_dump(
                                    mode="json"
                                ),
                                "after": target_project.model_dump(
                                    mode="json"
                                ),
                            },
                        ),
                        sequence=len(changes) + 1,
                        relation_type="modifies",
                        entity_kind="project_settings",
                        entity_id="timeline_project_settings",
                        before_project=current_project,
                        after_project=target_project,
                    )
                )
            proposal_id = _stable_id(
                "rollback_proposal",
                {
                    "source_run_id": source_run_id,
                    "current": current_checkpoint.checkpoint_digest,
                    "target": source.start_checkpoint.checkpoint_digest,
                    "changes": [
                        change.model_dump(
                            mode="json",
                            exclude={"change_id"},
                        )
                        for change in changes
                    ],
                },
            )
            proposal = RollbackProposal(
                proposal_id=proposal_id,
                project_id=ledger.project_id,
                source_run_id=source_run_id,
                current_checkpoint=current_checkpoint,
                target_checkpoint=source.start_checkpoint,
                changes=tuple(changes),
                limitations=(
                    "Restores timeline/project JSON only.",
                    "Does not delete or reverse generated/exported media files.",
                    "Any manual edit after execution makes this proposal stale.",
                ),
                created_at=deterministic_time,
            )
            review = RollbackReviewRecord(
                review_id=self.id_factory("rollback_review"),
                project_id=ledger.project_id,
                proposal=proposal,
                proposal_digest=proposal.digest(),
                recorded_at=self.clock(),
            )
            self._append(session, review)
            return review

    def confirm_rollback(
        self,
        review_id: str,
        *,
        confirmed_by: str,
        decision: Literal["confirmed", "rejected"],
    ) -> RollbackConfirmationRecord:
        ledger = self.store.load()
        reviews = {
            record.review_id: record
            for record in self._records(ledger, RollbackReviewRecord)
        }
        review = reviews.get(review_id)
        if review is None:
            raise WorkflowApplicationError("Unknown rollback review")
        self._current(review.proposal.current_checkpoint.snapshot_ref)
        record = RollbackConfirmationRecord(
            confirmation_id=self.id_factory("rollback_confirmation"),
            project_id=ledger.project_id,
            review_id=review.review_id,
            proposal_id=review.proposal.proposal_id,
            proposal_digest=review.proposal_digest,
            decision=decision,
            confirmed_by=confirmed_by,
            recorded_at=self.clock(),
        )
        self.store.append(
            record,
            entry_id=self.id_factory("entry"),
            recorded_at=self.clock(),
            expected_revision=ledger.revision,
        )
        return record

    def apply_rollback(
        self,
        rollback_confirmation_id: str,
    ) -> RollbackRunRecord:
        ledger = self.store.load()
        confirmations = {
            record.confirmation_id: record
            for record in self._records(
                ledger,
                RollbackConfirmationRecord,
            )
        }
        confirmation = confirmations.get(rollback_confirmation_id)
        if confirmation is None or confirmation.decision != "confirmed":
            raise WorkflowApplicationError(
                "Rollback requires an exact persisted confirmation"
            )
        if any(
            record.rollback_confirmation_id == rollback_confirmation_id
            for record in self._records(ledger, RollbackRunRecord)
        ):
            raise WorkflowApplicationError(
                "Rollback confirmation has already been applied"
            )
        reviews = {
            record.review_id: record
            for record in self._records(ledger, RollbackReviewRecord)
        }
        review = reviews[confirmation.review_id]
        proposal = review.proposal
        skill = self.registry.get("VideoRestoreTimelineCheckpointSkill")
        if skill is None:
            raise WorkflowApplicationError(
                "Timeline checkpoint restore tool is not registered"
            )
        with self.store.exclusive(
            project_id=ledger.project_id,
            expected_revision=ledger.revision,
        ) as session:
            current = self._current(
                proposal.current_checkpoint.snapshot_ref
            )
            before = self._checkpoint(
                session.ledger,
                project_id=ledger.project_id,
                reason=f"before rollback {proposal.proposal_id}",
                snapshot=current,
            )
            now = self.clock()
            run_id = self.id_factory("rollback_run")
            pending = RollbackRunRecord(
                run_record_id=self.id_factory("run_record"),
                rollback_run_id=run_id,
                project_id=ledger.project_id,
                rollback_confirmation_id=confirmation.confirmation_id,
                proposal=proposal,
                status="rollback_pending",
                before_checkpoint=before,
                started_at=now,
                updated_at=now,
            )
            self._append(session, pending)
            request = RollbackToolRequest(
                request_id=self.id_factory("rollback_request"),
                rollback_run_id=run_id,
                project_id=ledger.project_id,
                proposal_id=proposal.proposal_id,
                confirmation_id=confirmation.confirmation_id,
                requested_at=self.clock(),
            )
            running = pending.model_copy(
                update={
                    "run_record_id": self.id_factory("run_record"),
                    "status": "running",
                    "request": request,
                    "updated_at": self.clock(),
                }
            )
            self._append(session, running)
            started = self.clock()
            try:
                validated = skill.input_model.model_validate(
                    {
                        "proposal": proposal,
                        "confirmation": confirmation,
                    }
                )
                payload = skill.execute(
                    validated.model_dump(mode="python")
                )
                result = RollbackToolResult(
                    result_id=self.id_factory("rollback_result"),
                    request_id=request.request_id,
                    rollback_run_id=run_id,
                    status="success",
                    payload=payload,
                    started_at=started,
                    finished_at=self.clock(),
                )
                after_snapshot = self.snapshot_provider()
                after = self._checkpoint(
                    session.ledger,
                    project_id=ledger.project_id,
                    reason=f"after rollback {proposal.proposal_id}",
                    snapshot=after_snapshot,
                )
                finished = self.clock()
                terminal = running.model_copy(
                    update={
                        "run_record_id": self.id_factory("run_record"),
                        "status": "succeeded",
                        "result": result,
                        "after_checkpoint": after,
                        "updated_at": finished,
                        "finished_at": finished,
                    }
                )
            except Exception as exc:
                after_snapshot = self.snapshot_provider()
                changed = (
                    TimelineSnapshotReference.from_snapshot(after_snapshot)
                    != before.snapshot_ref
                )
                error = WorkflowError(
                    code=(
                        "rollback_state_uncertain"
                        if changed
                        else "rollback_failed"
                    ),
                    message=str(exc),
                    recovery_action=(
                        "Inspect timeline and checkpoint integrity before "
                        "continuing."
                    ),
                )
                result = RollbackToolResult(
                    result_id=self.id_factory("rollback_result"),
                    request_id=request.request_id,
                    rollback_run_id=run_id,
                    status="error",
                    error=error,
                    started_at=started,
                    finished_at=self.clock(),
                )
                finished = self.clock()
                terminal = running.model_copy(
                    update={
                        "run_record_id": self.id_factory("run_record"),
                        "status": (
                            "recovery_required" if changed else "failed"
                        ),
                        "result": result,
                        "updated_at": finished,
                        "finished_at": finished,
                        "error": error,
                    }
                )
            self._append(session, terminal)
            return terminal
