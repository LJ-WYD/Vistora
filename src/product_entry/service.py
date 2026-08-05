"""Constrained composition of Director, review, confirmation, and Editing."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from agent import DirectorAgent, EditingAgent
from creation_planning import (
    CreationPlanningAgent,
    CreationPlanningService,
)
from director import DirectorHistoryQuery, DirectorStore
from material_requirements import MaterialRequirementsService
from material_feedback import MaterialFeedbackService
from material_production import MaterialProductionAgent, MaterialProductionOrchestrator
from workflow import WorkflowApplicationService, WorkflowHistoryQuery

from .models import (
    ProductEntryCommand,
    ProductEntryResponse,
    ProductEntryView,
)
from .store import (
    ProductEntryConcurrencyError,
    ProductEntryIntegrityError,
    ProductEntryStore,
)


Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]
_PATH = re.compile(r"(?:[A-Za-z]:\\|file://|/(?:Users|home)/)")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class ProductEntryError(ValueError):
    pass


class ProductionEntryService:
    """One product state machine; no direct timeline or skill dependency."""

    def __init__(
        self,
        *,
        director: DirectorAgent,
        director_store: DirectorStore,
        workflow: WorkflowApplicationService,
        editing_agent: EditingAgent,
        store: ProductEntryStore,
        session_id: str,
        project_id: str,
        material_requirements: MaterialRequirementsService | None = None,
        creation_planning_agent: CreationPlanningAgent | None = None,
        creation_planning: CreationPlanningService | None = None,
        material_production: MaterialProductionOrchestrator | None = None,
        material_production_agent: MaterialProductionAgent | None = None,
        material_feedback: MaterialFeedbackService | None = None,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _random_id,
    ) -> None:
        self.director = director
        self.director_store = director_store
        self.workflow = workflow
        self.editing_agent = editing_agent
        self.store = store
        self.session_id = session_id
        self.project_id = project_id
        self.material_requirements = material_requirements
        self.creation_planning_agent = creation_planning_agent
        self.creation_planning = creation_planning
        self.material_production = material_production
        self.material_feedback = material_feedback
        self.material_production_agent = material_production_agent or (
            MaterialProductionAgent(
                material_production,
                clock=clock,
                id_factory=id_factory,
            )
            if material_production is not None
            else None
        )
        self.clock = clock
        self.id_factory = id_factory

    def view(self) -> ProductEntryView:
        ledger = self.store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        director_ledger = self.director_store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        director = DirectorHistoryQuery.project(director_ledger).model_dump(
            mode="json"
        )
        workflow_ledger = self.workflow.store.load(
            None if self.workflow.store.path.exists() else self.project_id
        )
        workflow = WorkflowHistoryQuery.project(workflow_ledger).model_dump(
            mode="json"
        )
        material_view = (
            self.material_requirements.view().model_dump(mode="json")
            if self.material_requirements is not None
            else None
        )
        creation_view = (
            self.creation_planning.view().model_dump(mode="json")
            if self.creation_planning is not None
            else None
        )
        production_view = (
            self.material_production.view().model_dump(mode="json")
            if self.material_production is not None
            else None
        )
        feedback_view = (
            self.material_feedback.view().model_dump(mode="json")
            if self.material_feedback is not None
            else None
        )
        state, allowed = self._state(
            ledger,
            director,
            workflow,
            material_view,
            creation_view,
            production_view,
        )
        latest = ledger.events[-1].result if ledger.events else None
        review = self._latest_review(director_ledger)
        view = ProductEntryView(
            session_id=self.session_id,
            project_id=self.project_id,
            revision=ledger.revision,
            state=state,
            director=director,
            review=review,
            workflow=workflow,
            material_requirements=material_view,
            creation_planning=creation_view,
            material_production=production_view,
            material_feedback=feedback_view,
            latest_result=latest,
            allowed_actions=allowed,
        )
        if _PATH.search(view.model_dump_json()):
            raise ProductEntryIntegrityError(
                "Product view contains an absolute path"
            )
        return view

    def director_history(self):
        ledger = self.director_store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        return DirectorHistoryQuery.project(ledger)

    def latest_review_request(self):
        ledger = self.director_store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        for entry in reversed(ledger.entries):
            proposal = entry.record.report.proposal
            if proposal is not None:
                return proposal.review_request
        raise ProductEntryError("No Director proposal is ready for review")

    @staticmethod
    def _latest_review(director_ledger) -> dict[str, Any] | None:
        for entry in reversed(director_ledger.entries):
            proposal = entry.record.report.proposal
            if proposal is not None:
                return proposal.review.model_dump(mode="json")
        return None

    @staticmethod
    def _state(
        ledger,
        director: dict,
        workflow: dict,
        material_view: dict | None,
        creation_view: dict | None,
        production_view: dict | None,
    ):
        if ledger.events:
            latest = ledger.events[-1]
            mapping = {
                "persist_review": "reviewed",
                "confirm": "confirmed",
                "reject": "rejected",
                "execute": latest.status,
                "rollback_review": "rollback_reviewed",
                "rollback_confirm": "rollback_confirmed",
                "rollback_reject": "rollback_rejected",
                "rollback_apply": (
                    "rolled_back" if latest.status == "succeeded" else latest.status
                ),
                "persist_material_review": "material_reviewed",
                "confirm_materials": "materials_confirmed",
                "reject_materials": "materials_rejected",
                "withdraw_materials": "materials_withdrawn",
                "plan_material_production": latest.status,
                "confirm_production_plan": "production_plan_confirmed",
                "reject_production_plan": "production_plan_rejected",
                "withdraw_production_plan": "production_plan_withdrawn",
                "start_material_production": latest.status,
                "poll_material_production": latest.status,
                "cancel_material_job": latest.status,
                "retry_material_job": latest.status,
                "accept_material_artifact": latest.status,
                "reject_material_artifact": latest.status,
                "return_to_director": "returned_to_director",
            }
            state = mapping.get(latest.action)
            if state is not None:
                allowed = {
                    "reviewed": ("confirm", "reject"),
                    "confirmed": ("execute",),
                    "succeeded": ("rollback_review", "director_turn"),
                    "failed": ("rollback_review", "director_turn"),
                    "partial": ("rollback_review",),
                    "recovery_required": ("rollback_review",),
                    "rollback_reviewed": (
                        "rollback_confirm",
                        "rollback_reject",
                    ),
                    "rollback_confirmed": ("rollback_apply",),
                    "rolled_back": ("director_turn",),
                    "rejected": ("director_turn",),
                    "rollback_rejected": ("director_turn",),
                    "material_reviewed": (
                        "confirm_materials",
                        "reject_materials",
                        "withdraw_materials",
                    ),
                    "materials_rejected": ("director_turn",),
                    "materials_withdrawn": ("director_turn",),
                    "materials_confirmed": (
                        "plan_material_production",
                    ),
                    "production_plan_ready": (
                        "confirm_production_plan",
                        "reject_production_plan",
                        "withdraw_production_plan",
                    ),
                    "production_plan_needs_input": (
                        "plan_material_production",
                    ),
                    "production_plan_unsupported": (
                        "plan_material_production",
                    ),
                    "production_plan_rejected": (
                        "plan_material_production",
                    ),
                    "production_plan_withdrawn": (
                        "plan_material_production",
                    ),
                    "production_plan_confirmed": (
                        ("start_material_production",)
                        if production_view is not None
                        else ()
                    ),
                    "material_production_running": (
                        "poll_material_production",
                        "cancel_material_job",
                    ),
                    "material_awaiting_review": (
                        "accept_material_artifact",
                        "reject_material_artifact",
                    ),
                    "material_production_partial": (
                        "accept_material_artifact",
                        "reject_material_artifact",
                        "retry_material_job",
                    ),
                    "material_production_failed": (
                        "retry_material_job",
                    ),
                    "material_production_recovery_required": (
                        "retry_material_job",
                    ),
                    "material_production_cancelled": (
                        "retry_material_job",
                    ),
                    "material_production_succeeded": (
                        "return_to_director",
                    ),
                    "returned_to_director": ("director_turn",),
                }.get(state, ())
                if state == "materials_confirmed" and creation_view is None:
                    allowed = ()
                if (
                    state == "material_production_partial"
                    and production_view is not None
                ):
                    reviewable = any(
                        item.get("passed") and not item.get("decision")
                        for item in production_view.get("artifacts", ())
                    )
                    rejected_jobs = {
                        item.get("job_id")
                        for item in production_view.get("artifacts", ())
                        if item.get("decision") == "rejected"
                    }
                    retryable = any(
                        item.get("status")
                        in {
                            "failed",
                            "timed_out",
                            "cancelled",
                            "recovery_required",
                        }
                        or (
                            item.get("status") == "succeeded"
                            and item.get("job_id") in rejected_jobs
                        )
                        for item in production_view.get("jobs", ())
                    )
                    allowed = (
                        (
                            "accept_material_artifact",
                            "reject_material_artifact",
                        )
                        if reviewable
                        else ()
                    ) + (("retry_material_job",) if retryable else ())
                return state, allowed
        status = director.get("latest_status", "empty")
        if status == "material_requirements_ready":
            return "material_requirements_ready", (
                "director_turn",
                "persist_material_review",
            )
        if status == "proposal_ready":
            return "proposal_ready", ("director_turn", "persist_review")
        if status in {
            "needs_clarification", "needs_materials", "materials_incomplete"
        }:
            return status, ("director_turn",)
        if status in {"model_error", "stale_context"}:
            return "error", ("director_turn",)
        return "dialogue", ("director_turn",)

    def command(self, command: ProductEntryCommand) -> ProductEntryResponse:
        if command.session_id != self.session_id:
            raise ProductEntryError("Command crosses product session")
        if command.project_id != self.project_id:
            raise ProductEntryError("Command crosses product project")
        existing = self.store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        for event in existing.events:
            if event.request_id == command.request_id:
                if event.request_digest != command.content_digest():
                    raise ProductEntryError(
                        "Request ID was replayed with different content"
                    )
                return ProductEntryResponse(
                    request_id=command.request_id,
                    replayed=True,
                    view=self.view(),
                )
        with self.store.exclusive(
            session_id=self.session_id,
            project_id=self.project_id,
            expected_revision=command.expected_revision,
        ) as ledger:
            current = self.view()
            if command.action not in current.allowed_actions:
                raise ProductEntryError(
                    f"Action {command.action} is illegal from {current.state}"
                )
            status, target_id, result = self._perform(command)
            self.store.append(
                ledger,
                command,
                event_id=self.id_factory("product_event"),
                status=status,
                target_id=target_id,
                result=result,
                recorded_at=self.clock(),
            )
        return ProductEntryResponse(
            request_id=command.request_id,
            view=self.view(),
        )

    def _perform(
        self,
        command: ProductEntryCommand,
    ) -> tuple[str, str | None, dict[str, Any]]:
        if command.action == "director_turn":
            report = self.director.converse(
                session_id=self.session_id,
                turn_id=self.id_factory("director_turn"),
                user_message=command.user_message or "",
            )
            return report.status, report.report_id, {
                "report_id": report.report_id,
                "status": report.status,
                "brief_version": report.brief.brief_version,
                "proposal_id": (
                    report.proposal.proposal_id
                    if report.proposal
                    else (
                        report.material_requirements.proposal_id
                        if report.material_requirements
                        else None
                    )
                ),
            }
        if command.action == "persist_material_review":
            if self.material_requirements is None:
                raise ProductEntryError(
                    "Material requirements workflow is unavailable"
                )
            director_ledger = self.director_store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            proposal = next(
                (
                    entry.record.report.material_requirements
                    for entry in reversed(director_ledger.entries)
                    if entry.record.report.material_requirements is not None
                ),
                None,
            )
            if proposal is None or proposal.proposal_id != command.target_id:
                raise ProductEntryError(
                    "Exact material requirements proposal is unavailable"
                )
            ledger = self.material_requirements.store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            updated = self.material_requirements.record(
                proposal,
                expected_revision=ledger.revision,
            )
            feedback_revision = None
            if (
                self.material_feedback is not None
                and proposal.plan.plan_kind == "supplemental_shortfall"
                and proposal.plan.shortfall_ref is not None
            ):
                feedback_ledger = self.material_feedback.store.load(
                    project_id=self.project_id
                )
                linked = self.material_feedback.link_requirements(
                    proposal.plan.shortfall_ref.report_id,
                    proposal,
                    expected_revision=feedback_ledger.revision,
                )
                feedback_revision = linked.revision
            return "reviewed", proposal.review.review_id, {
                "proposal_id": proposal.proposal_id,
                "review_id": proposal.review.review_id,
                "plan_digest": proposal.plan.digest(),
                "material_ledger_revision": updated.revision,
                "material_feedback_revision": feedback_revision,
            }
        if command.action in {"confirm_materials", "reject_materials"}:
            if self.material_requirements is None:
                raise ProductEntryError(
                    "Material requirements workflow is unavailable"
                )
            ledger = self.material_requirements.store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            confirmation, updated = self.material_requirements.decide(
                command.target_id or "",
                decision=(
                    "confirmed"
                    if command.action == "confirm_materials"
                    else "rejected"
                ),
                confirmed_by=command.actor_id,
                expected_revision=ledger.revision,
            )
            return confirmation.decision, confirmation.confirmation_id, {
                "confirmation_id": confirmation.confirmation_id,
                "decision": confirmation.decision,
                "material_ledger_revision": updated.revision,
            }
        if command.action == "withdraw_materials":
            if self.material_requirements is None:
                raise ProductEntryError(
                    "Material requirements workflow is unavailable"
                )
            ledger = self.material_requirements.store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            updated = self.material_requirements.withdraw(
                command.target_id or "",
                expected_revision=ledger.revision,
            )
            return "withdrawn", command.target_id, {
                "proposal_id": command.target_id,
                "material_ledger_revision": updated.revision,
            }
        if command.action == "plan_material_production":
            if (
                self.creation_planning_agent is None
                or self.creation_planning is None
            ):
                raise ProductEntryError(
                    "Creation planning workflow is unavailable"
                )
            request = self.creation_planning_agent.prepare_request(
                request_id=self.id_factory("creation_request"),
                material_confirmation_id=command.target_id or "",
            )
            report = self.creation_planning_agent.plan(request)
            status = {
                "proposal_ready": "production_plan_ready",
                "needs_user_input": "production_plan_needs_input",
                "unsupported": "production_plan_unsupported",
            }.get(report.status, "error")
            return status, report.report_id, {
                "report_id": report.report_id,
                "status": report.status,
                "message": report.message,
                "proposal_id": (
                    report.proposal.proposal_id
                    if report.proposal is not None
                    else None
                ),
                "review_id": (
                    report.proposal.review.review_id
                    if report.proposal is not None
                    else None
                ),
                "error_code": report.error_code,
            }
        if command.action in {
            "confirm_production_plan",
            "reject_production_plan",
        }:
            if self.creation_planning is None:
                raise ProductEntryError(
                    "Creation planning workflow is unavailable"
                )
            ledger = self.creation_planning.store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            confirmation, updated = self.creation_planning.decide(
                command.target_id or "",
                decision=(
                    "confirmed"
                    if command.action == "confirm_production_plan"
                    else "rejected"
                ),
                confirmed_by=command.actor_id,
                expected_revision=ledger.revision,
            )
            return confirmation.decision, confirmation.confirmation_id, {
                "confirmation_id": confirmation.confirmation_id,
                "decision": confirmation.decision,
                "creation_planning_revision": updated.revision,
            }
        if command.action == "withdraw_production_plan":
            if self.creation_planning is None:
                raise ProductEntryError(
                    "Creation planning workflow is unavailable"
                )
            ledger = self.creation_planning.store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            updated = self.creation_planning.withdraw(
                command.target_id or "",
                expected_revision=ledger.revision,
            )
            return "withdrawn", command.target_id, {
                "proposal_id": command.target_id,
                "creation_planning_revision": updated.revision,
            }
        if command.action == "start_material_production":
            if self.material_production_agent is None:
                raise ProductEntryError(
                    "Material production workflow is unavailable"
                )
            request = self.material_production_agent.prepare_execution(
                agent_request_id=self.id_factory("production_agent_request"),
                production_request_id=self.id_factory("production_request"),
                production_confirmation_id=command.target_id or "",
                requested_by=command.actor_id,
            )
            report = self.material_production_agent.execute(request)
            if report.disposition == "rejected":
                raise ProductEntryError(report.error.message)
            if self.material_feedback is not None:
                open_report = self.material_feedback.latest_open_report()
                if open_report is not None:
                    confirmed = self.creation_planning.confirmed(
                        command.target_id or ""
                    )
                    feedback_ledger = self.material_feedback.store.load(
                        project_id=self.project_id
                    )
                    self.material_feedback.link_production(
                        open_report.report_id,
                        requirements_confirmation_id=(
                            confirmed.confirmation.material_confirmation_ref.confirmation_id
                        ),
                        production_plan_id=confirmed.proposal.plan.production_plan_id,
                        production_plan_digest=confirmed.proposal.plan.digest(),
                        production_confirmation_id=confirmed.confirmation.confirmation_id,
                        production_run_id=report.run_id or "",
                        expected_revision=feedback_ledger.revision,
                    )
            status = self._production_status(report.status)
            return status, report.run_id, {
                "agent_report_id": report.report_id,
                "run_id": report.run_id,
                "status": report.status,
                "message": report.message,
            }
        if command.action == "poll_material_production":
            if self.material_production is None:
                raise ProductEntryError(
                    "Material production workflow is unavailable"
                )
            run = self.material_production.poll(command.target_id or "")
            status = self._production_status(run["status"])
            return status, run["run_id"], {
                "run_id": run["run_id"],
                "status": run["status"],
                "message": run["message"],
            }
        if command.action == "cancel_material_job":
            if self.material_production is None:
                raise ProductEntryError(
                    "Material production workflow is unavailable"
                )
            update = self.material_production.cancel(
                command.target_id or ""
            )
            production = self.material_production.view()
            return self._production_status(production.state), update.job_id, {
                "job_id": update.job_id,
                "status": update.status,
                "message": update.message,
                "production_state": production.state,
            }
        if command.action == "retry_material_job":
            if self.material_production is None:
                raise ProductEntryError(
                    "Material production workflow is unavailable"
                )
            update = self.material_production.retry(
                command.target_id or ""
            )
            production = self.material_production.view()
            status = self._production_status(production.state)
            return status, update.job_id, {
                "job_id": update.job_id,
                "status": update.status,
                "message": update.message,
                "production_state": production.state,
            }
        if command.action in {
            "accept_material_artifact",
            "reject_material_artifact",
        }:
            if self.material_production is None:
                raise ProductEntryError(
                    "Material production workflow is unavailable"
                )
            decision, entry = self.material_production.decide_artifact(
                command.target_id or "",
                decision=(
                    "accepted"
                    if command.action == "accept_material_artifact"
                    else "rejected"
                ),
                decided_by=command.actor_id,
                reason=(
                    "Accepted through the explicit local material review."
                    if command.action == "accept_material_artifact"
                    else "Rejected through the explicit local material review."
                ),
            )
            view = self.material_production.view()
            return self._production_status(view.state), decision.decision_id, {
                "decision_id": decision.decision_id,
                "decision": decision.decision,
                "material_id": (
                    entry.material_id if entry is not None else None
                ),
                "production_state": view.state,
            }
        if command.action == "return_to_director":
            if self.material_production is None:
                raise ProductEntryError(
                    "Material production workflow is unavailable"
                )
            view = self.material_production.view()
            target_run = next(
                (
                    run
                    for run in view.runs
                    if run["run_id"] == command.target_id
                    and run["status"] == "succeeded"
                ),
                None,
            )
            material_ids = [
                item["material_id"]
                for item in view.catalog
                if item["production_run_id"] == command.target_id
            ]
            if target_run is None or not material_ids:
                raise ProductEntryError(
                    "Exact succeeded run has no accepted catalog material"
                )
            if self.material_feedback is not None:
                open_report = self.material_feedback.latest_open_report()
                if open_report is not None:
                    feedback_ledger = self.material_feedback.store.load(
                        project_id=self.project_id
                    )
                    catalog = self.material_production.catalog.load(
                        project_id=self.project_id
                    )
                    self.material_feedback.resolve(
                        open_report.report_id,
                        catalog=catalog,
                        production_run_id=command.target_id or "",
                        expected_revision=feedback_ledger.revision,
                    )
            return "returned_to_director", command.target_id, {
                "accepted_material_ids": material_ids,
                "message": (
                    "Accepted catalog material is now observable to the "
                    "Director on the next turn."
                ),
            }
        if command.action == "persist_review":
            director_ledger = self.director_store.load(
                session_id=self.session_id,
                project_id=self.project_id,
            )
            proposal = next(
                (
                    entry.record.report.proposal
                    for entry in reversed(director_ledger.entries)
                    if entry.record.report.proposal is not None
                ),
                None,
            )
            if proposal is None or proposal.proposal_id != command.target_id:
                raise ProductEntryError("Exact Director proposal is unavailable")
            record = self.workflow.record_review(proposal.review_request)
            return "reviewed", record.review_id, {
                "review_id": record.review_id,
                "proposal_id": proposal.proposal_id,
                "diff_digest": record.diff_digest,
            }
        if command.action in {"confirm", "reject"}:
            record = self.workflow.confirm_review(
                command.target_id or "",
                confirmed_by=command.actor_id,
                decision=(
                    "confirmed" if command.action == "confirm" else "rejected"
                ),
            )
            return record.decision, record.confirmation_record_id, {
                "review_id": record.review_id,
                "confirmation_record_id": record.confirmation_record_id,
                "decision": record.decision,
            }
        if command.action == "execute":
            request = self.editing_agent.prepare_execution(
                request_id=self.id_factory("editing_request"),
                confirmation_record_id=command.target_id or "",
            )
            report = self.editing_agent.execute(request)
            return report.status, report.report_id, {
                "report_id": report.report_id,
                "request_id": report.request_id,
                "status": report.status,
                "disposition": report.disposition,
                "run_id": report.run_id,
                "execution_id": report.execution_id,
                "confirmation_record_id": report.confirmation_record_id,
                "workflow_revision_before": report.workflow_revision_before,
                "workflow_revision_after": report.workflow_revision_after,
                "steps": [
                    {
                        "sequence": step.sequence,
                        "step_id": step.step_id,
                        "tool_name": step.tool_name,
                        "request_id": step.atomic_request_id,
                        "result_id": step.atomic_result_id,
                        "status": step.status,
                    }
                    for step in report.steps
                ],
                "error": (
                    report.error.model_dump(mode="json")
                    if report.error is not None
                    else None
                ),
            }
        if command.action == "rollback_review":
            record = self.workflow.propose_rollback(command.target_id or "")
            return "reviewed", record.review_id, {
                "review_id": record.review_id,
                "proposal_id": record.proposal.proposal_id,
                "source_run_id": record.proposal.source_run_id,
            }
        if command.action in {"rollback_confirm", "rollback_reject"}:
            record = self.workflow.confirm_rollback(
                command.target_id or "",
                confirmed_by=command.actor_id,
                decision=(
                    "confirmed"
                    if command.action == "rollback_confirm"
                    else "rejected"
                ),
            )
            return record.decision, record.confirmation_id, {
                "review_id": record.review_id,
                "confirmation_id": record.confirmation_id,
                "decision": record.decision,
            }
        if command.action == "rollback_apply":
            record = self.workflow.apply_rollback(command.target_id or "")
            return record.status, record.rollback_run_id, {
                "rollback_run_id": record.rollback_run_id,
                "status": record.status,
            }
        raise ProductEntryError("Unknown product action")

    @staticmethod
    def _production_status(status: str) -> str:
        return {
            "pending": "material_production_running",
            "running": "material_production_running",
            "awaiting_review": "material_awaiting_review",
            "succeeded": "material_production_succeeded",
            "partial": "material_production_partial",
            "failed": "material_production_failed",
            "cancelled": "material_production_cancelled",
            "recovery_required": "material_production_recovery_required",
        }[status]


__all__ = [
    "ProductEntryConcurrencyError",
    "ProductEntryError",
    "ProductEntryIntegrityError",
    "ProductionEntryService",
]
