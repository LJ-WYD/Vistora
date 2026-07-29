"""Read-only review and explicit decision service for material requirements."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from director import MaterialRequirementsProposal
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService

from .models import (
    ConfirmedMaterialRequirements,
    MaterialRequirementsConfirmation,
    MaterialRequirementsView,
)
from .store import MaterialRequirementsStore


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class MaterialRequirementsError(ValueError):
    pass


class MaterialRequirementsService:
    def __init__(
        self,
        *,
        store: MaterialRequirementsStore,
        session_id: str,
        project_id: str,
        snapshot_provider=TimelineSnapshotService.snapshot_current,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
    ):
        self.store = store
        self.session_id = session_id
        self.project_id = project_id
        self.snapshot_provider = snapshot_provider
        self.clock = clock
        self.id_factory = id_factory

    def _current(self, proposal):
        current = TimelineSnapshotReference.from_snapshot(
            self.snapshot_provider()
        )
        if current != proposal.plan.no_material_snapshot_ref:
            raise MaterialRequirementsError(
                "No-material snapshot changed; regenerate requirements"
            )

    def record(
        self,
        proposal: MaterialRequirementsProposal,
        *,
        expected_revision: int,
    ):
        self._current(proposal)
        with self.store.exclusive(
            session_id=self.session_id,
            project_id=self.project_id,
            expected_revision=expected_revision,
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("material_event"),
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
            raise MaterialRequirementsError("Invalid material decision")
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
                raise MaterialRequirementsError(
                    "Unknown material requirements review"
                )
            proposal = proposals[0]
            self._current(proposal)
            confirmation = MaterialRequirementsConfirmation.for_proposal(
                confirmation_id=self.id_factory("material_confirmation"),
                proposal=proposal,
                decision=decision,
                confirmed_by=confirmed_by,
                recorded_at=self.clock(),
            )
            updated = self.store.append(
                ledger,
                event_id=self.id_factory("material_event"),
                event_type=decision,
                confirmation=confirmation,
                recorded_at=self.clock(),
            )
        return confirmation, updated

    def withdraw(
        self,
        proposal_id: str,
        *,
        expected_revision: int,
    ):
        with self.store.exclusive(
            session_id=self.session_id,
            project_id=self.project_id,
            expected_revision=expected_revision,
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("material_event"),
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
            raise MaterialRequirementsError(
                "Unknown material requirements confirmation"
            )
        confirmation = confirmations[0]
        proposals = [
            event.proposal
            for event in ledger.events
            if event.proposal is not None
            and event.proposal.review.review_id == confirmation.review_id
        ]
        if len(proposals) != 1:
            raise MaterialRequirementsError(
                "Confirmed material proposal is unavailable"
            )
        self._current(proposals[0])
        return ConfirmedMaterialRequirements(
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
                "plan_id": event.proposal.plan.plan_id,
                "plan_version": event.proposal.plan.plan_version,
                "plan_digest": event.proposal.plan.digest(),
                "review_id": event.proposal.review.review_id,
                "review_digest": event.proposal.review.review_digest,
                "brief_version": event.proposal.plan.brief_ref.brief_version,
                "items": tuple(
                    {
                        "item_id": item.item_id,
                        "asset_type": item.asset_type,
                        "purpose": item.purpose,
                        "narrative_position": item.narrative_position,
                        "priority": item.priority,
                        "acceptance_criteria": item.acceptance_criteria,
                    }
                    for item in event.proposal.plan.items
                ),
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
        state = {
            "proposal_recorded": "reviewable",
            "confirmed": "confirmed",
            "rejected": "rejected",
            "withdrawn": "withdrawn",
            "empty": "empty",
        }[latest]
        return MaterialRequirementsView(
            session_id=self.session_id,
            project_id=self.project_id,
            revision=ledger.revision,
            state=state,
            proposals=proposals,
            decisions=decisions,
        )

