"""Confirmed-plan material production orchestration and human acceptance."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from creation_planning import CreationPlanningService
from director import digest_json

from .adapters import AdapterRegistry
from .models import (
    AdapterJobUpdate,
    ArtifactDecision,
    MaterialCatalogEntry,
    MaterialProductionRunRequest,
    MaterialProductionView,
    ProductionCatalogState,
    ProductionDecisionState,
    ProductionJobRequest,
    ProductionJobState,
    ProductionPlanConfirmationReference,
    ProductionRunState,
    ProductionTaskInput,
    ProductionValidationState,
)
from .store import (
    MaterialCatalogStore,
    MaterialProductionStore,
    MaterialProductionStoreError,
)
from .validation import ArtifactValidator


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class MaterialProductionError(ValueError):
    pass


class MaterialProductionOrchestrator:
    """Only this application boundary submits adapters and catalogs artifacts."""

    def __init__(
        self,
        *,
        creation_planning: CreationPlanningService,
        adapters: AdapterRegistry,
        store: MaterialProductionStore,
        catalog: MaterialCatalogStore,
        staging_root: str | Path,
        project_id: str,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
    ) -> None:
        self.creation_planning = creation_planning
        self.adapters = adapters
        self.store = store
        self.catalog = catalog
        self.staging_root = Path(staging_root)
        self.project_id = project_id
        self.clock = clock
        self.id_factory = id_factory
        self.validator = ArtifactValidator(
            self.staging_root,
            clock=clock,
            id_factory=id_factory,
        )

    def prepare_request(
        self,
        *,
        request_id: str,
        production_confirmation_id: str,
        requested_by: str,
        task_inputs: tuple[ProductionTaskInput, ...] = (),
    ) -> MaterialProductionRunRequest:
        confirmed = self.creation_planning.confirmed(
            production_confirmation_id
        )
        return MaterialProductionRunRequest(
            request_id=request_id,
            plan_confirmation_ref=(
                ProductionPlanConfirmationReference.from_confirmed(confirmed)
            ),
            adapter_registry_ref=self.adapters.reference(),
            task_inputs=task_inputs,
            requested_by=requested_by,
            requested_at=self.clock(),
        )

    def _confirmed(self, request):
        exact = self.creation_planning.confirmed(
            request.plan_confirmation_ref.production_confirmation_id
        )
        if (
            ProductionPlanConfirmationReference.from_confirmed(exact)
            != request.plan_confirmation_ref
        ):
            raise MaterialProductionError(
                "Confirmed production plan changed; prepare a new run"
            )
        if self.adapters.reference() != request.adapter_registry_ref:
            raise MaterialProductionError(
                "Production adapter registry changed; prepare a new run"
            )
        return exact

    def _append(self, ledger, record):
        return self.store.append(
            ledger,
            event_id=self.id_factory("production_event"),
            record=record,
        )

    def start(self, request: MaterialProductionRunRequest):
        confirmed = self._confirmed(request)
        ledger = self.store.load(project_id=self.project_id)
        prior = [
            event.record
            for event in ledger.events
            if isinstance(event.record, ProductionRunState)
            and event.record.request.request_id == request.request_id
        ]
        if prior:
            if prior[0].request != request:
                raise MaterialProductionError(
                    "Production request ID replayed with different content"
                )
            return self.run(prior[0].run_id)
        run_id = self.id_factory("production_run")
        with self.store.exclusive(
            project_id=self.project_id,
            expected_revision=ledger.revision,
        ) as current:
            current = self._append(
                current,
                ProductionRunState(
                    run_id=run_id,
                    request=request,
                    status="pending",
                    message="The confirmed production run was recorded.",
                    recorded_at=self.clock(),
                ),
            )
            inputs = {item.task_id: item.input_token for item in request.task_inputs}
            latest_status: dict[str, str] = {}
            for task in confirmed.proposal.plan.tasks:
                dependency_states = [
                    latest_status.get(dependency)
                    for dependency in task.dependency_task_ids
                ]
                if any(
                    status not in {"succeeded"}
                    for status in dependency_states
                ):
                    current = self._record_blocked_job(
                        current,
                        run_id=run_id,
                        task=task,
                        code="production_dependency_blocked",
                        message="A production dependency did not succeed.",
                    )
                    latest_status[task.task_id] = "failed"
                    continue
                if task.status != "planned":
                    current = self._record_blocked_job(
                        current,
                        run_id=run_id,
                        task=task,
                        code="production_task_not_executable",
                        message=task.limitation or "Task is not executable.",
                    )
                    latest_status[task.task_id] = "failed"
                    continue
                adapter = self.adapters.select(task.capability_ids[0])
                if adapter is None:
                    current = self._record_blocked_job(
                        current,
                        run_id=run_id,
                        task=task,
                        code="production_adapter_unconfigured",
                        message=(
                            "No configured adapter provides the required "
                            "capability."
                        ),
                    )
                    latest_status[task.task_id] = "failed"
                    continue
                job = ProductionJobRequest(
                    job_id=self.id_factory("production_job"),
                    run_id=run_id,
                    task_id=task.task_id,
                    requirement_item_id=task.requirement_item_id,
                    adapter_id=adapter.capability().adapter_id,
                    capability_id=task.capability_ids[0],
                    attempt=1,
                    idempotency_key=self._job_key(
                        request,
                        task.task_id,
                        1,
                    ),
                    input_token=inputs.get(task.task_id),
                    requested_at=self.clock(),
                )
                try:
                    update = adapter.submit(
                        job,
                        staging_root=self.staging_root,
                    )
                except Exception:
                    update = AdapterJobUpdate(
                        job_id=job.job_id,
                        adapter_id=job.adapter_id,
                        provider_opaque_ref=f"failed_{job.job_id}",
                        status="recovery_required",
                        progress=0,
                        error_code="production_submit_uncertain",
                        message=(
                            "Adapter submission ended without a reliable "
                            "result; operator recovery is required."
                        ),
                        updated_at=self.clock(),
                    )
                current = self._append(
                    current,
                    ProductionJobState(request=job, update=update),
                )
                latest_status[task.task_id] = update.status
                if update.status == "succeeded":
                    current = self._validate_update(
                        current,
                        run_id=run_id,
                        task=task,
                        update=update,
                    )
            status = self._aggregate(current, run_id)
            current = self._append(
                current,
                ProductionRunState(
                    run_id=run_id,
                    request=request,
                    status=status,
                    message=self._status_message(status),
                    recorded_at=self.clock(),
                ),
            )
        return self.run(run_id)

    def _record_blocked_job(self, ledger, *, run_id, task, code, message):
        job = ProductionJobRequest(
            job_id=self.id_factory("production_job"),
            run_id=run_id,
            task_id=task.task_id,
            requirement_item_id=task.requirement_item_id,
            adapter_id="unconfigured_adapter",
            capability_id=task.capability_ids[0],
            attempt=1,
            idempotency_key=f"job_key_{digest_json([run_id, task.task_id])[7:31]}",
            requested_at=self.clock(),
        )
        update = AdapterJobUpdate(
            job_id=job.job_id,
            adapter_id=job.adapter_id,
            provider_opaque_ref=f"blocked_{job.job_id}",
            status="failed",
            progress=0,
            error_code=code,
            message=message,
            updated_at=self.clock(),
        )
        return self._append(
            ledger,
            ProductionJobState(request=job, update=update),
        )

    def _validate_update(self, ledger, *, run_id, task, update):
        for candidate in update.artifacts:
            validation = self.validator.validate(
                candidate,
                run_id=run_id,
                job_id=update.job_id,
                task=task,
            )
            ledger = self._append(
                ledger,
                ProductionValidationState(validation=validation),
            )
        return ledger

    def poll(self, run_id: str):
        ledger = self.store.load(project_id=self.project_id)
        run_request = self._run_request(ledger, run_id)
        confirmed = self._confirmed(run_request)
        tasks = {
            task.task_id: task for task in confirmed.proposal.plan.tasks
        }
        latest_jobs = self._latest_jobs(ledger, run_id)
        with self.store.exclusive(
            project_id=self.project_id,
            expected_revision=ledger.revision,
        ) as current:
            for state in latest_jobs.values():
                if state.update.status not in {
                    "submitted",
                    "running",
                    "rate_limited",
                    "needs_input",
                }:
                    continue
                adapter = self.adapters.adapters.get(
                    state.request.adapter_id
                )
                if adapter is None:
                    update = state.update.model_copy(
                        update={
                            "status": "recovery_required",
                            "error_code": "production_adapter_missing",
                            "message": (
                                "The original adapter is unavailable after "
                                "restart."
                            ),
                            "updated_at": self.clock(),
                        }
                    )
                else:
                    update = adapter.poll(
                        state.request,
                        provider_opaque_ref=(
                            state.update.provider_opaque_ref
                        ),
                        staging_root=self.staging_root,
                    )
                current = self._append(
                    current,
                    ProductionJobState(
                        request=state.request,
                        update=update,
                    ),
                )
                if update.status == "succeeded":
                    current = self._validate_update(
                        current,
                        run_id=run_id,
                        task=tasks[state.request.task_id],
                        update=update,
                    )
            status = self._aggregate(current, run_id)
            current = self._append(
                current,
                ProductionRunState(
                    run_id=run_id,
                    request=run_request,
                    status=status,
                    message=self._status_message(status),
                    recorded_at=self.clock(),
                ),
            )
        return self.run(run_id)

    def cancel(self, job_id: str):
        ledger = self.store.load(project_id=self.project_id)
        states = [
            event.record
            for event in ledger.events
            if isinstance(event.record, ProductionJobState)
            and event.record.request.job_id == job_id
        ]
        if not states:
            raise MaterialProductionError("Unknown production job")
        state = states[-1]
        if state.update.status in {
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        }:
            raise MaterialProductionError("Production job is already terminal")
        adapter = self.adapters.adapters.get(state.request.adapter_id)
        if adapter is None:
            raise MaterialProductionError("Production adapter is unavailable")
        update = adapter.cancel(
            state.request,
            provider_opaque_ref=state.update.provider_opaque_ref,
        )
        with self.store.exclusive(
            project_id=self.project_id,
            expected_revision=ledger.revision,
        ) as current:
            current = self._append(
                current,
                ProductionJobState(request=state.request, update=update),
            )
            run_request = self._run_request(
                current,
                state.request.run_id,
            )
            status = self._aggregate(current, state.request.run_id)
            current = self._append(
                current,
                ProductionRunState(
                    run_id=state.request.run_id,
                    request=run_request,
                    status=status,
                    message=self._status_message(status),
                    recorded_at=self.clock(),
                ),
            )
        return update

    def retry(self, job_id: str):
        ledger = self.store.load(project_id=self.project_id)
        states = [
            event.record
            for event in ledger.events
            if isinstance(event.record, ProductionJobState)
            and event.record.request.job_id == job_id
        ]
        if not states:
            raise MaterialProductionError("Unknown production job")
        prior = states[-1]
        retryable_statuses = {
            "failed",
            "timed_out",
            "rate_limited",
            "recovery_required",
            "cancelled",
            "needs_input",
        }
        rejected_success = False
        if prior.update.status == "succeeded":
            decisions = {
                event.record.decision.artifact_id:
                event.record.decision.decision
                for event in ledger.events
                if isinstance(event.record, ProductionDecisionState)
            }
            rejected_success = bool(prior.update.artifacts) and all(
                decisions.get(artifact.artifact_id) == "rejected"
                for artifact in prior.update.artifacts
            )
        if (
            prior.update.status not in retryable_statuses
            and not rejected_success
        ):
            raise MaterialProductionError("Production job is not retryable")
        adapter = self.adapters.adapters.get(prior.request.adapter_id)
        if adapter is None:
            raise MaterialProductionError("Production adapter is unavailable")
        request = prior.request.model_copy(
            update={
                "job_id": self.id_factory("production_job"),
                "attempt": prior.request.attempt + 1,
                "idempotency_key": f"job_key_{digest_json([prior.request.run_id, prior.request.task_id, prior.request.attempt + 1])[7:31]}",
                "requested_at": self.clock(),
            }
        )
        update = adapter.submit(request, staging_root=self.staging_root)
        run_request = self._run_request(ledger, request.run_id)
        confirmed = self._confirmed(run_request)
        task = next(
            item
            for item in confirmed.proposal.plan.tasks
            if item.task_id == request.task_id
        )
        with self.store.exclusive(
            project_id=self.project_id,
            expected_revision=ledger.revision,
        ) as current:
            current = self._append(
                current,
                ProductionJobState(request=request, update=update),
            )
            if update.status == "succeeded":
                current = self._validate_update(
                    current,
                    run_id=request.run_id,
                    task=task,
                    update=update,
                )
            status = self._aggregate(current, request.run_id)
            current = self._append(
                current,
                ProductionRunState(
                    run_id=request.run_id,
                    request=run_request,
                    status=status,
                    message=self._status_message(status),
                    recorded_at=self.clock(),
                ),
            )
        return update

    def decide_artifact(
        self,
        artifact_id: str,
        *,
        decision: str,
        decided_by: str,
        reason: str,
    ):
        if decision not in {"accepted", "rejected"}:
            raise MaterialProductionError("Invalid artifact decision")
        ledger = self.store.load(project_id=self.project_id)
        validations = [
            event.record.validation
            for event in ledger.events
            if isinstance(event.record, ProductionValidationState)
            and event.record.validation.artifact_id == artifact_id
        ]
        if not validations:
            raise MaterialProductionError("Artifact was not validated")
        validation = validations[-1]
        existing = [
            event.record.decision
            for event in ledger.events
            if isinstance(event.record, ProductionDecisionState)
            and event.record.decision.artifact_id == artifact_id
        ]
        if existing:
            raise MaterialProductionError("Artifact was already decided")
        if decision == "accepted" and not validation.passed:
            raise MaterialProductionError(
                "Failed artifact validation cannot be accepted"
            )
        artifact, job = self._artifact_and_job(ledger, artifact_id)
        decision_record = ArtifactDecision(
            decision_id=self.id_factory("artifact_decision"),
            artifact_id=artifact_id,
            validation_id=validation.validation_id,
            decision=decision,
            decided_by=decided_by,
            reason=reason,
            decided_at=self.clock(),
        )
        with self.store.exclusive(
            project_id=self.project_id,
            expected_revision=ledger.revision,
        ) as current:
            current = self._append(
                current,
                ProductionDecisionState(decision=decision_record),
            )
            entry = None
            if decision == "accepted":
                run_request = self._run_request(current, validation.run_id)
                confirmed = self._confirmed(run_request)
                task = next(
                    item
                    for item in confirmed.proposal.plan.tasks
                    if item.task_id == validation.task_id
                )
                staged = self.validator.resolve(artifact)
                catalog = self.catalog.load(project_id=self.project_id)
                entry = self._catalog_entry(
                    validation=validation,
                    decision=decision_record,
                    artifact=artifact,
                    job=job,
                    confirmed=confirmed,
                    task=task,
                )
                updated_catalog = self.catalog.register(
                    catalog,
                    entry=entry,
                    staged_path=staged,
                )
                current = self._append(
                    current,
                    ProductionCatalogState(entry=entry),
                )
            current = self._append(
                current,
                ProductionRunState(
                    run_id=validation.run_id,
                    request=self._run_request(current, validation.run_id),
                    status=self._post_decision_status(
                        current,
                        validation.run_id,
                    ),
                    message=(
                        "Accepted artifacts are registered in the catalog."
                        if decision == "accepted"
                        else "The artifact was rejected and not cataloged."
                    ),
                    recorded_at=self.clock(),
                ),
            )
        return decision_record, entry

    def _catalog_entry(
        self,
        *,
        validation,
        decision,
        artifact,
        job,
        confirmed,
        task,
    ):
        digest = validation.sha256
        assert digest is not None
        material_id = "source_" + digest[7:23]
        extension = Path(artifact.staging_relative_path).suffix.lower()
        relative = f"{material_id}/{material_id}{extension}"
        origin = {
            "generate": "generated",
            "import": "manual_import",
            "capture": "captured",
            "library_search": "library",
            "manual": "manual_import",
        }[task.production_method]
        return MaterialCatalogEntry(
            material_id=material_id,
            display_name=f"{task.title}{extension}",
            media_kind=task.delivery.media_kind,
            managed_relative_path=relative,
            artifact_sha256=digest,
            size_bytes=validation.size_bytes,
            mime_type=validation.mime_type,
            container=validation.container,
            video_codec=validation.video_codec,
            audio_codec=validation.audio_codec,
            duration_seconds=validation.duration_seconds,
            width=validation.width,
            height=validation.height,
            fps=validation.fps,
            has_audio=validation.has_audio,
            requirements_plan_id=(
                confirmed.proposal.plan.material_confirmation_ref
                .requirements_plan_id
            ),
            requirement_item_id=validation.requirement_item_id,
            production_plan_id=confirmed.proposal.plan.production_plan_id,
            production_task_id=validation.task_id,
            production_run_id=validation.run_id,
            production_job_id=validation.job_id,
            adapter_id=job.request.adapter_id,
            origin_kind=origin,
            license_status="unknown",
            usage_restrictions=(
                "User must verify license and usage rights before publishing.",
            ),
            cost_status=job.update.cost_status,
            cost_value=job.update.cost_value,
            cost_currency=job.update.cost_currency,
            quality_validation_id=validation.validation_id,
            accepted_decision_id=decision.decision_id,
            registered_at=self.clock(),
        )

    def run(self, run_id: str):
        view = self.view()
        matches = [run for run in view.runs if run["run_id"] == run_id]
        if not matches:
            raise MaterialProductionError("Unknown material-production run")
        return matches[-1]

    def view(self):
        ledger = self.store.load(project_id=self.project_id)
        catalog = self.catalog.load(project_id=self.project_id)
        runs = []
        latest_runs = {}
        latest_jobs = {}
        validations = {}
        decisions = {}
        for event in ledger.events:
            record = event.record
            if isinstance(record, ProductionRunState):
                latest_runs[record.run_id] = record
            elif isinstance(record, ProductionJobState):
                latest_jobs[record.request.job_id] = record
            elif isinstance(record, ProductionValidationState):
                validations[record.validation.artifact_id] = (
                    record.validation
                )
            elif isinstance(record, ProductionDecisionState):
                decisions[record.decision.artifact_id] = record.decision
        for run_id, record in sorted(latest_runs.items()):
            runs.append(
                {
                    "run_id": run_id,
                    "request_id": record.request.request_id,
                    "production_plan_id": (
                        record.request.plan_confirmation_ref.production_plan_id
                    ),
                    "status": record.status,
                    "message": record.message,
                }
            )
        jobs = tuple(
            {
                "job_id": state.request.job_id,
                "run_id": state.request.run_id,
                "task_id": state.request.task_id,
                "requirement_item_id": state.request.requirement_item_id,
                "adapter_id": state.request.adapter_id,
                "attempt": state.request.attempt,
                "status": state.update.status,
                "progress": state.update.progress,
                "cost_status": state.update.cost_status,
                "cost_value": state.update.cost_value,
                "cost_currency": state.update.cost_currency,
                "message": state.update.message,
                "error_code": state.update.error_code,
            }
            for _, state in sorted(latest_jobs.items())
        )
        artifacts = tuple(
            {
                "artifact_id": artifact_id,
                "run_id": validation.run_id,
                "job_id": validation.job_id,
                "task_id": validation.task_id,
                "requirement_item_id": validation.requirement_item_id,
                "passed": validation.passed,
                "size_bytes": validation.size_bytes,
                "mime_type": validation.mime_type,
                "duration_seconds": validation.duration_seconds,
                "width": validation.width,
                "height": validation.height,
                "fps": validation.fps,
                "has_audio": validation.has_audio,
                "issues": validation.issues,
                "decision": (
                    decisions[artifact_id].decision
                    if artifact_id in decisions
                    else None
                ),
            }
            for artifact_id, validation in sorted(validations.items())
        )
        state = (
            runs[-1]["status"] if runs else "empty"
        )
        if state == "pending":
            state = "running"
        return MaterialProductionView(
            project_id=self.project_id,
            ledger_revision=ledger.revision,
            catalog_revision=catalog.revision,
            state=state,
            runs=tuple(runs),
            jobs=jobs,
            artifacts=artifacts,
            catalog=tuple(
                {
                    "material_id": entry.material_id,
                    "display_name": entry.display_name,
                    "media_kind": entry.media_kind,
                    "duration_seconds": entry.duration_seconds,
                    "width": entry.width,
                    "height": entry.height,
                    "fps": entry.fps,
                    "has_audio": entry.has_audio,
                    "origin_kind": entry.origin_kind,
                    "requirement_item_id": entry.requirement_item_id,
                    "production_task_id": entry.production_task_id,
                    "production_run_id": entry.production_run_id,
                    "license_status": entry.license_status,
                    "usage_restrictions": entry.usage_restrictions,
                }
                for entry in catalog.entries
            ),
            capabilities=tuple(
                {
                    "capability_id": capability_id,
                    "adapter_id": capability.adapter_id,
                    "configured": capability.configured,
                    "execution_kind": capability.execution_kind,
                    "limitation": capability.limitation,
                }
                for capability in self.adapters.reference().adapters
                for capability_id in capability.capability_ids
            ),
        )

    @staticmethod
    def _job_key(request, task_id, attempt):
        return (
            "job_key_"
            + digest_json(
                {
                    "request": request.digest(),
                    "task": task_id,
                    "attempt": attempt,
                }
            )[7:31]
        )

    @staticmethod
    def _status_message(status):
        return {
            "running": "Production jobs are running or need input.",
            "awaiting_review": (
                "Validated artifacts await an explicit user decision."
            ),
            "partial": "Some production jobs failed or remain blocked.",
            "failed": "No production job produced a valid artifact.",
            "recovery_required": (
                "A production result is uncertain and needs recovery."
            ),
            "cancelled": "The production run was cancelled.",
            "succeeded": "Accepted artifacts are registered in the catalog.",
        }[status]

    def _aggregate(self, ledger, run_id):
        jobs = list(self._latest_jobs(ledger, run_id).values())
        if not jobs:
            return "failed"
        statuses = [item.update.status for item in jobs]
        if "recovery_required" in statuses:
            return "recovery_required"
        if any(
            status in {"submitted", "running", "rate_limited", "needs_input"}
            for status in statuses
        ):
            return "running"
        if all(status == "cancelled" for status in statuses):
            return "cancelled"
        validations = [
            event.record.validation
            for event in ledger.events
            if isinstance(event.record, ProductionValidationState)
            and event.record.validation.run_id == run_id
        ]
        passed = [item for item in validations if item.passed]
        failed_jobs = [
            status for status in statuses
            if status in {"failed", "timed_out", "cancelled"}
        ]
        if passed and failed_jobs:
            return "partial"
        if passed:
            return "awaiting_review"
        return "failed"

    @staticmethod
    def _post_decision_status(ledger, run_id):
        latest_jobs = (
            MaterialProductionOrchestrator._latest_jobs(ledger, run_id)
        )
        latest_job_ids = {
            state.request.job_id for state in latest_jobs.values()
        }
        validations = [
            event.record.validation
            for event in ledger.events
            if isinstance(event.record, ProductionValidationState)
            and event.record.validation.run_id == run_id
            and event.record.validation.job_id in latest_job_ids
            and event.record.validation.passed
        ]
        decisions = {
            event.record.decision.artifact_id: event.record.decision.decision
            for event in ledger.events
            if isinstance(event.record, ProductionDecisionState)
        }
        if not validations or any(
            item.artifact_id not in decisions for item in validations
        ):
            return "awaiting_review"
        has_failures = any(
            state.update.status
            in {
                "failed",
                "timed_out",
                "cancelled",
                "recovery_required",
            }
            for state in latest_jobs.values()
        )
        has_rejections = any(
            decisions[item.artifact_id] == "rejected"
            for item in validations
        )
        if has_failures or has_rejections:
            return "partial"
        return "succeeded"

    @staticmethod
    def _latest_jobs(ledger, run_id):
        latest = {}
        for event in ledger.events:
            if (
                isinstance(event.record, ProductionJobState)
                and event.record.request.run_id == run_id
            ):
                task_id = event.record.request.task_id
                known = latest.get(task_id)
                if (
                    known is None
                    or event.record.request.attempt
                    >= known.request.attempt
                ):
                    latest[task_id] = event.record
        return latest

    @staticmethod
    def _run_request(ledger, run_id):
        states = [
            event.record
            for event in ledger.events
            if isinstance(event.record, ProductionRunState)
            and event.record.run_id == run_id
        ]
        if not states:
            raise MaterialProductionError("Unknown material-production run")
        return states[0].request

    @staticmethod
    def _artifact_and_job(ledger, artifact_id):
        artifact = None
        for event in ledger.events:
            if isinstance(event.record, ProductionJobState):
                for candidate in event.record.update.artifacts:
                    if candidate.artifact_id == artifact_id:
                        artifact = candidate
        if artifact is None:
            raise MaterialProductionError("Unknown staged artifact")
        jobs = [
            event.record
            for event in ledger.events
            if isinstance(event.record, ProductionJobState)
            and event.record.request.job_id == artifact.job_id
        ]
        return artifact, jobs[-1]
