"""Read-only review and independent confirmation for production plans."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from material_requirements import MaterialRequirementsService

from .models import (
    ConfirmedMaterialProductionPlan,
    CreationPlanningView,
    MaterialProductionConfirmation,
    MaterialProductionProposal,
)
from .store import CreationPlanningStore


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class CreationPlanningError(ValueError):
    pass


class CreationPlanningService:
    def __init__(
        self,
        *,
        store: CreationPlanningStore,
        material_requirements: MaterialRequirementsService,
        session_id: str,
        project_id: str,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
    ) -> None:
        self.store = store
        self.material_requirements = material_requirements
        self.session_id = session_id
        self.project_id = project_id
        self.clock = clock
        self.id_factory = id_factory

    def exact_material_confirmation(self, confirmation_id: str):
        return self.material_requirements.confirmed(confirmation_id)

    def _validate_proposal(self, proposal: MaterialProductionProposal) -> None:
        confirmation_id = (
            proposal.plan.material_confirmation_ref.confirmation_id
        )
        exact = self.exact_material_confirmation(confirmation_id)
        from .models import MaterialConfirmationReference

        if (
            MaterialConfirmationReference.from_confirmed(exact)
            != proposal.plan.material_confirmation_ref
        ):
            raise CreationPlanningError(
                "Confirmed material requirements changed; re-plan"
            )

    def record(
        self,
        proposal: MaterialProductionProposal,
        *,
        expected_revision: int,
    ):
        self._validate_proposal(proposal)
        with self.store.exclusive(
            session_id=self.session_id,
            project_id=self.project_id,
            expected_revision=expected_revision,
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("creation_event"),
                event_type="proposal_recorded",
                proposal=proposal,
                recorded_at=self.clock(),
            )

    def decide(
        self,
        review_id: str,
        *,
        decision: str,
        confirmed_by: str,
        expected_revision: int,
    ):
        if decision not in {"confirmed", "rejected"}:
            raise CreationPlanningError("Invalid production-plan decision")
        with self.store.exclusive(
            session_id=self.session_id,
            project_id=self.project_id,
            expected_revision=expected_revision,
        ) as ledger:
            proposals = [
                event.proposal
                for event in ledger.events
                if event.proposal is not None
                and event.proposal.review.review_id == review_id
            ]
            if len(proposals) != 1:
                raise CreationPlanningError(
                    "Unknown material-production review"
                )
            proposal = proposals[0]
            self._validate_proposal(proposal)
            confirmation = MaterialProductionConfirmation.for_proposal(
                confirmation_id=self.id_factory("production_confirmation"),
                proposal=proposal,
                decision=decision,
                confirmed_by=confirmed_by,
                recorded_at=self.clock(),
            )
            updated = self.store.append(
                ledger,
                event_id=self.id_factory("creation_event"),
                event_type=decision,
                confirmation=confirmation,
                recorded_at=self.clock(),
            )
        return confirmation, updated

    def withdraw(self, proposal_id: str, *, expected_revision: int):
        with self.store.exclusive(
            session_id=self.session_id,
            project_id=self.project_id,
            expected_revision=expected_revision,
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("creation_event"),
                event_type="withdrawn",
                withdrawn_proposal_id=proposal_id,
                recorded_at=self.clock(),
            )

    def confirmed(self, confirmation_id: str):
        ledger = self.store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        confirmations = [
            event.confirmation
            for event in ledger.events
            if event.confirmation is not None
            and event.confirmation.confirmation_id == confirmation_id
        ]
        if len(confirmations) != 1:
            raise CreationPlanningError(
                "Unknown production-plan confirmation"
            )
        confirmation = confirmations[0]
        proposals = [
            event.proposal
            for event in ledger.events
            if event.proposal is not None
            and event.proposal.review.review_id == confirmation.review_id
        ]
        if len(proposals) != 1:
            raise CreationPlanningError(
                "Confirmed production plan is unavailable"
            )
        self._validate_proposal(proposals[0])
        return ConfirmedMaterialProductionPlan(
            ledger_revision=ledger.revision,
            proposal=proposals[0],
            confirmation=confirmation,
        )

    def view(self):
        ledger = self.store.load(
            session_id=self.session_id,
            project_id=self.project_id,
        )
        proposals = tuple(
            {
                "proposal_id": event.proposal.proposal_id,
                "production_plan_id": (
                    event.proposal.plan.production_plan_id
                ),
                "plan_version": event.proposal.plan.plan_version,
                "plan_digest": event.proposal.plan.digest(),
                "review_id": event.proposal.review.review_id,
                "review_digest": event.proposal.review.review_digest,
                "material_confirmation_id": (
                    event.proposal.plan.material_confirmation_ref.confirmation_id
                ),
                "tasks": tuple(
                    {
                        "task_id": task.task_id,
                        "requirement_item_id": task.requirement_item_id,
                        "title": task.title,
                        "method": task.production_method,
                        "status": task.status,
                        "capability_ids": task.capability_ids,
                        "quality_gates": task.quality_gates,
                        "limitation": task.limitation,
                    }
                    for task in event.proposal.plan.tasks
                ),
                "warnings": event.proposal.review.warnings,
            }
            for event in ledger.events
            if event.proposal is not None
        )
        decisions = tuple(
            {
                "confirmation_id": event.confirmation.confirmation_id,
                "review_id": event.confirmation.review_id,
                "decision": event.confirmation.decision,
                "confirmed_by": event.confirmation.confirmed_by,
            }
            for event in ledger.events
            if event.confirmation is not None
        )
        latest = ledger.events[-1].event_type if ledger.events else "empty"
        return CreationPlanningView(
            session_id=self.session_id,
            project_id=self.project_id,
            revision=ledger.revision,
            state={
                "empty": "empty",
                "proposal_recorded": "reviewable",
                "confirmed": "confirmed",
                "rejected": "rejected",
                "withdrawn": "withdrawn",
            }[latest],
            proposals=proposals,
            decisions=decisions,
        )
