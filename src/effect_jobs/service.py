"""O30 effect job lifecycle without timeline mutation authority."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from effect_workflow import EffectExecutionReport

from .models import (
    EffectAttemptRequest,
    EffectAttemptState,
    EffectCacheRecord,
    EffectCandidateRecord,
    EffectCandidateSelection,
    EffectJobCost,
    EffectJobLedger,
    EffectJobView,
    EffectRedoScope,
)


class EffectJobError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _new(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class EffectJobLifecycleService:
    """Append-only lifecycle for exact O28 requests and human candidate choices."""

    def __init__(self, *, store, project_id, executor=None, clock=_now, id_factory=_new):
        self.store = store
        self.project_id = project_id
        self.executor = executor
        self.clock = clock
        self.id_factory = id_factory

    def _load(self):
        return self.store.load(project_id=self.project_id)

    def _append(self, record, *, expected_revision):
        with self.store.exclusive(
            project_id=self.project_id, expected_revision=expected_revision
        ) as ledger:
            return self.store.append(
                ledger, record, event_id=self.id_factory("effect_event")
            )

    @staticmethod
    def _attempt_states(ledger, attempt_id=None):
        values = [
            event.record
            for event in ledger.events
            if isinstance(event.record, EffectAttemptState)
            and (attempt_id is None or event.record.attempt.attempt_id == attempt_id)
        ]
        return values

    @staticmethod
    def _candidates(ledger, task_id=None):
        return [
            event.record
            for event in ledger.events
            if isinstance(event.record, EffectCandidateRecord)
            and (task_id is None or event.record.task_id == task_id)
        ]

    @staticmethod
    def _selections(ledger, task_id=None):
        return [
            event.record
            for event in ledger.events
            if isinstance(event.record, EffectCandidateSelection)
            and (task_id is None or event.record.task_id == task_id)
        ]

    @staticmethod
    def _active_cache(ledger, cache_key):
        state = None
        for event in ledger.events:
            record = event.record
            if isinstance(record, EffectCacheRecord) and record.cache_key == cache_key:
                state = record
        return state if state is not None and state.status == "active" else None

    def begin(
        self,
        execution_request,
        *,
        task_id,
        idempotency_key,
        expected_revision,
        reason="initial",
        base_candidate_id=None,
        redo_scope: EffectRedoScope | None = None,
    ):
        if execution_request.binding.project_id != self.project_id:
            raise EffectJobError("Effect job request crosses project")
        ledger = self._load()
        for state in self._attempt_states(ledger):
            if state.attempt.idempotency_key == idempotency_key:
                probe = {
                    "execution_request": execution_request,
                    "task_id": task_id,
                    "reason": reason,
                    "base_candidate_id": base_candidate_id,
                    "redo_scope": redo_scope,
                }
                actual = {key: getattr(state.attempt, key) for key in probe}
                if actual != probe:
                    raise EffectJobError("Effect job idempotency key was replayed with drift")
                return state, ledger
        candidates = self._candidates(ledger, task_id)
        if reason == "partial_redo":
            base = next((item for item in candidates if item.candidate_id == base_candidate_id), None)
            if base is None:
                raise EffectJobError("Partial redo references an unknown candidate")
        attempt_number = 1 + max(
            (item.attempt.attempt_number for item in self._attempt_states(ledger)
             if item.attempt.task_id == task_id),
            default=0,
        )
        if reason == "initial" and attempt_number != 1:
            reason = "retry"
        attempt = EffectAttemptRequest(
            attempt_id=self.id_factory("effect_attempt"),
            execution_request=execution_request,
            task_id=task_id,
            attempt_number=attempt_number,
            reason=reason,
            base_candidate_id=base_candidate_id,
            redo_scope=redo_scope,
            idempotency_key=idempotency_key,
            requested_at=self.clock(),
        )
        cached = self._active_cache(ledger, attempt.cache_key())
        if cached is not None:
            state = EffectAttemptState(
                attempt=attempt,
                status="cached",
                progress=1,
                stage="cache_reused",
                candidate_id=cached.candidate_id,
                message="A validated candidate was reused from the exact request cache.",
                recorded_at=self.clock(),
            )
        else:
            state = EffectAttemptState(
                attempt=attempt,
                status="running",
                progress=0,
                stage="queued",
                message="Effect attempt is queued for the configured adapter.",
                recorded_at=self.clock(),
            )
        return state, self._append(state, expected_revision=expected_revision)

    def progress(self, attempt_id, *, progress, stage, cost=None, expected_revision):
        ledger = self._load()
        states = self._attempt_states(ledger, attempt_id)
        if not states or states[-1].status != "running":
            raise EffectJobError("Only a running effect attempt can report progress")
        if progress < states[-1].progress or progress >= 1:
            raise EffectJobError("Effect progress must increase and remain below completion")
        record = states[-1].model_copy(update={
            "progress": progress,
            "stage": stage,
            "cost": cost or states[-1].cost,
            "message": "Effect provider reported bounded progress.",
            "recorded_at": self.clock(),
        })
        return record, self._append(record, expected_revision=expected_revision)

    def complete(self, attempt_id, report: EffectExecutionReport, *, cost=None, expected_revision):
        ledger = self._load()
        states = self._attempt_states(ledger, attempt_id)
        if not states or states[-1].status != "running":
            raise EffectJobError("Only a running effect attempt can complete")
        attempt = states[-1].attempt
        if (
            report.execution_request_id != attempt.execution_request.execution_request_id
            or report.request_digest != attempt.execution_request.digest()
            or report.binding != attempt.execution_request.binding
        ):
            raise EffectJobError("Effect result does not bind the exact attempt request")
        task_report = next((item for item in report.tasks if item.task_id == attempt.task_id), None)
        if task_report is None:
            raise EffectJobError("Effect result omitted the attempted task")
        if task_report.status != "ready_for_review":
            failed = EffectAttemptState(
                attempt=attempt,
                status="failed",
                progress=states[-1].progress,
                stage="failed",
                cost=cost or states[-1].cost,
                error_code=task_report.error_code or "effect_job_failed",
                message=task_report.message,
                recorded_at=self.clock(),
            )
            return failed, self._append(failed, expected_revision=expected_revision)
        candidate_version = len(self._candidates(ledger, attempt.task_id)) + 1
        candidate = EffectCandidateRecord(
            candidate_id=self.id_factory("effect_candidate"),
            task_id=attempt.task_id,
            candidate_version=candidate_version,
            attempt_id=attempt.attempt_id,
            artifact=task_report.artifact,
            cache_key=attempt.cache_key(),
            cost=cost or states[-1].cost,
            created_at=self.clock(),
        )
        ledger = self._append(candidate, expected_revision=expected_revision)
        finished = EffectAttemptState(
            attempt=attempt,
            status="succeeded",
            progress=1,
            stage="awaiting_human_review",
            cost=candidate.cost,
            candidate_id=candidate.candidate_id,
            message="Candidate is isolated and awaits explicit human selection.",
            recorded_at=self.clock(),
        )
        ledger = self._append(finished, expected_revision=ledger.revision)
        cache = EffectCacheRecord(
            cache_id=self.id_factory("effect_cache"),
            cache_key=candidate.cache_key,
            candidate_id=candidate.candidate_id,
            task_id=candidate.task_id,
            status="active",
            reason="Validated exact-request candidate cache.",
            recorded_at=self.clock(),
        )
        ledger = self._append(cache, expected_revision=ledger.revision)
        return finished, ledger

    def submit(self, execution_request, *, task_id, idempotency_key, expected_revision, **kwargs):
        if self.executor is None:
            raise EffectJobError("No effect execution adapter boundary is configured")
        state, ledger = self.begin(
            execution_request,
            task_id=task_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            **kwargs,
        )
        if state.status == "cached":
            return state, ledger
        return self.complete(
            state.attempt.attempt_id,
            self.executor.execute(execution_request),
            expected_revision=ledger.revision,
        )

    def cancel(self, attempt_id, *, expected_revision):
        ledger = self._load()
        states = self._attempt_states(ledger, attempt_id)
        if not states or states[-1].status != "running":
            raise EffectJobError("Only a running effect attempt can be cancelled")
        record = states[-1].model_copy(update={
            "status": "cancelled", "stage": "cancelled",
            "message": "Effect attempt was cancelled before candidate acceptance.",
            "recorded_at": self.clock(),
        })
        return record, self._append(record, expected_revision=expected_revision)

    def recover_interrupted(self, *, expected_revision):
        ledger = self._load()
        latest = {}
        for state in self._attempt_states(ledger):
            latest[state.attempt.attempt_id] = state
        for state in sorted(latest.values(), key=lambda item: item.attempt.attempt_id):
            if state.status == "running":
                record = state.model_copy(update={
                    "status": "recovery_required", "stage": "restart_detected",
                    "error_code": "effect_job_interrupted",
                    "message": "Restart interrupted the attempt; explicit retry is required.",
                    "recorded_at": self.clock(),
                })
                ledger = self._append(record, expected_revision=ledger.revision)
        return ledger

    def invalidate_cache(self, cache_key, *, reason, expected_revision):
        ledger = self._load()
        active = self._active_cache(ledger, cache_key)
        if active is None:
            raise EffectJobError("Effect cache entry is not active")
        record = EffectCacheRecord(
            cache_id=self.id_factory("effect_cache"),
            cache_key=active.cache_key,
            candidate_id=active.candidate_id,
            task_id=active.task_id,
            status="invalidated",
            reason=reason,
            recorded_at=self.clock(),
        )
        return record, self._append(record, expected_revision=expected_revision)

    def select(self, candidate_id, *, action, actor_id, reason, expected_revision):
        ledger = self._load()
        candidate = next((item for item in self._candidates(ledger) if item.candidate_id == candidate_id), None)
        if candidate is None:
            raise EffectJobError("Effect selection references an unknown candidate")
        current = next(
            (item.selected_candidate_id for item in reversed(self._selections(ledger, candidate.task_id))
             if item.selected_candidate_id is not None),
            None,
        )
        if action == "accept" and current is not None:
            raise EffectJobError("Effect task already has a selected candidate")
        if action in {"replace", "rollback"} and current is None:
            raise EffectJobError("Effect replacement or rollback requires a current selection")
        if action == "rollback" and candidate.candidate_version >= next(
            item.candidate_version for item in self._candidates(ledger) if item.candidate_id == current
        ):
            raise EffectJobError("Effect rollback must select an earlier candidate version")
        record = EffectCandidateSelection(
            selection_id=self.id_factory("effect_selection"),
            task_id=candidate.task_id,
            action=action,
            candidate_id=candidate.candidate_id,
            previous_candidate_id=current if action in {"replace", "rollback"} else None,
            selected_candidate_id=None if action == "reject" else candidate.candidate_id,
            actor_id=actor_id,
            reason=reason,
            recorded_at=self.clock(),
        )
        return record, self._append(record, expected_revision=expected_revision)

    @staticmethod
    def project_view(ledger: EffectJobLedger):
        latest_attempts = {}
        candidates = []
        selections = []
        caches = {}
        for event in ledger.events:
            record = event.record
            if isinstance(record, EffectAttemptState):
                latest_attempts[record.attempt.attempt_id] = record
            elif isinstance(record, EffectCandidateRecord):
                candidates.append(record)
            elif isinstance(record, EffectCandidateSelection):
                selections.append(record)
            elif isinstance(record, EffectCacheRecord):
                caches[record.cache_key] = record
        statuses = {item.status for item in latest_attempts.values()}
        candidate_status = {item.candidate_id: "pending" for item in candidates}
        for item in selections:
            if item.action == "reject":
                candidate_status[item.candidate_id] = "rejected"
            elif item.action in {"replace", "rollback"}:
                candidate_status[item.previous_candidate_id] = "superseded"
                candidate_status[item.candidate_id] = "accepted"
            else:
                candidate_status[item.candidate_id] = "accepted"
        state = (
            "running" if "running" in statuses else
            "recovery_required" if "recovery_required" in statuses else
            "selected" if any(item.selected_candidate_id for item in selections) else
            "awaiting_review" if candidates else
            "failed" if statuses & {"failed", "cancelled"} else "empty"
        )
        return EffectJobView(
            project_id=ledger.project_id,
            revision=ledger.revision,
            state=state,
            attempts=tuple({
                "attempt_id": item.attempt.attempt_id,
                "task_id": item.attempt.task_id,
                "attempt_number": item.attempt.attempt_number,
                "reason": item.attempt.reason,
                "status": item.status,
                "progress": item.progress,
                "stage": item.stage,
                "cost": item.cost.model_dump(mode="json"),
                "candidate_id": item.candidate_id,
                "error_code": item.error_code,
                "message": item.message,
            } for item in sorted(latest_attempts.values(), key=lambda value: value.attempt.attempt_id)),
            candidates=tuple({
                "candidate_id": item.candidate_id,
                "task_id": item.task_id,
                "candidate_version": item.candidate_version,
                "artifact_id": item.artifact.artifact_id,
                "capability_id": item.artifact.capability_id,
                "output_role": item.artifact.output_role,
                "media_kind": item.artifact.media_kind,
                "content_digest": item.artifact.content_digest,
                "cost": item.cost.model_dump(mode="json"),
                "review_status": candidate_status[item.candidate_id],
            } for item in candidates),
            selections=tuple(item.model_dump(mode="json") for item in selections),
            cache_entries=tuple({
                "cache_id": item.cache_id, "cache_key": item.cache_key,
                "candidate_id": item.candidate_id, "task_id": item.task_id,
                "status": item.status, "reason": item.reason,
            } for item in sorted(caches.values(), key=lambda value: value.cache_key)),
        )

    def view(self):
        return self.project_view(self._load())
