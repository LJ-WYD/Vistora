"""Persistent, immutable material-requirements review and decision records."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from director import (
    MaterialRequirementsPlan,
    MaterialRequirementsProposal,
    MaterialRequirementsReview,
    digest_json,
)
from timeline_query import TimelineSnapshotReference


MATERIAL_REQUIREMENTS_VERSION = "1.0.0"
Version = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GENESIS_DIGEST = "sha256:" + ("0" * 64)


class MaterialWorkflowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Version = MATERIAL_REQUIREMENTS_VERSION


class MaterialRequirementsConfirmation(MaterialWorkflowModel):
    schema_name: Literal["vistora.material-requirements-confirmation"] = (
        "vistora.material-requirements-confirmation"
    )
    confirmation_id: StableId
    plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Digest
    review_id: StableId
    review_digest: Digest
    brief_digest: Digest
    snapshot_ref: TimelineSnapshotReference
    decision: Literal["confirmed", "rejected"]
    confirmed_by: StableId
    recorded_at: AwareDatetime

    @classmethod
    def for_proposal(
        cls,
        *,
        confirmation_id: str,
        proposal: MaterialRequirementsProposal,
        decision: Literal["confirmed", "rejected"],
        confirmed_by: str,
        recorded_at: datetime,
    ) -> MaterialRequirementsConfirmation:
        return cls(
            confirmation_id=confirmation_id,
            plan_id=proposal.plan.plan_id,
            plan_version=proposal.plan.plan_version,
            plan_digest=proposal.plan.digest(),
            review_id=proposal.review.review_id,
            review_digest=proposal.review.review_digest,
            brief_digest=proposal.plan.brief_ref.brief_digest,
            snapshot_ref=proposal.plan.no_material_snapshot_ref,
            decision=decision,
            confirmed_by=confirmed_by,
            recorded_at=recorded_at,
        )

    def validate_proposal(
        self,
        proposal: MaterialRequirementsProposal,
    ) -> None:
        if (
            self.plan_id != proposal.plan.plan_id
            or self.plan_version != proposal.plan.plan_version
            or self.plan_digest != proposal.plan.digest()
            or self.review_id != proposal.review.review_id
            or self.review_digest != proposal.review.review_digest
            or self.brief_digest != proposal.plan.brief_ref.brief_digest
            or self.snapshot_ref != proposal.plan.no_material_snapshot_ref
        ):
            raise ValueError(
                "Material requirements confirmation binding is mismatched"
            )


class MaterialRequirementsEvent(MaterialWorkflowModel):
    schema_name: Literal["vistora.material-requirements-event"] = (
        "vistora.material-requirements-event"
    )
    sequence: int = Field(ge=1)
    event_id: StableId
    event_type: Literal[
        "proposal_recorded",
        "confirmed",
        "rejected",
        "withdrawn",
    ]
    proposal: MaterialRequirementsProposal | None = None
    confirmation: MaterialRequirementsConfirmation | None = None
    withdrawn_proposal_id: StableId | None = None
    recorded_at: AwareDatetime
    previous_event_digest: Digest
    event_digest: Digest

    @model_validator(mode="after")
    def event_is_exact(self) -> MaterialRequirementsEvent:
        if self.event_type == "proposal_recorded":
            if self.proposal is None or any(
                value is not None
                for value in (
                    self.confirmation,
                    self.withdrawn_proposal_id,
                )
            ):
                raise ValueError("Proposal event shape is invalid")
        elif self.event_type in {"confirmed", "rejected"}:
            if (
                self.confirmation is None
                or self.proposal is not None
                or self.withdrawn_proposal_id is not None
                or self.confirmation.decision != self.event_type
            ):
                raise ValueError("Decision event shape is invalid")
        elif (
            self.withdrawn_proposal_id is None
            or self.proposal is not None
            or self.confirmation is not None
        ):
            raise ValueError("Withdrawal event shape is invalid")
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Material requirements event digest mismatched")
        return self


class MaterialRequirementsLedger(MaterialWorkflowModel):
    schema_name: Literal["vistora.material-requirements-ledger"] = (
        "vistora.material-requirements-ledger"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[MaterialRequirementsEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(
        cls,
        *,
        session_id: str,
        project_id: str,
    ) -> MaterialRequirementsLedger:
        return cls(
            session_id=session_id,
            project_id=project_id,
            revision=0,
            events=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def ledger_is_exact(self) -> MaterialRequirementsLedger:
        if self.revision != len(self.events):
            raise ValueError("Material ledger revision is invalid")
        previous = GENESIS_DIGEST
        proposals: dict[str, MaterialRequirementsProposal] = {}
        decided: set[str] = set()
        for index, event in enumerate(self.events, start=1):
            if event.sequence != index:
                raise ValueError("Material ledger sequence is invalid")
            if event.previous_event_digest != previous:
                raise ValueError("Material ledger chain is broken")
            if event.proposal is not None:
                proposal = event.proposal
                if proposal.proposal_id in proposals:
                    raise ValueError("Material proposal ID is duplicated")
                proposals[proposal.proposal_id] = proposal
            if event.confirmation is not None:
                confirmation = event.confirmation
                matches = [
                    proposal
                    for proposal in proposals.values()
                    if proposal.review.review_id == confirmation.review_id
                ]
                if len(matches) != 1:
                    raise ValueError("Material confirmation review is unknown")
                confirmation.validate_proposal(matches[0])
                if confirmation.review_id in decided:
                    raise ValueError("Material review was already decided")
                decided.add(confirmation.review_id)
            if (
                event.withdrawn_proposal_id is not None
                and event.withdrawn_proposal_id not in proposals
            ):
                raise ValueError("Material withdrawal proposal is unknown")
            previous = event.event_digest
        if self.integrity_digest != digest_json(
            [event.event_digest for event in self.events]
        ):
            raise ValueError("Material ledger integrity digest mismatched")
        return self


class ConfirmedMaterialRequirements(MaterialWorkflowModel):
    schema_name: Literal["vistora.confirmed-material-requirements"] = (
        "vistora.confirmed-material-requirements"
    )
    ledger_revision: int = Field(ge=1)
    proposal: MaterialRequirementsProposal
    confirmation: MaterialRequirementsConfirmation

    @model_validator(mode="after")
    def binding_is_confirmed(self) -> ConfirmedMaterialRequirements:
        self.confirmation.validate_proposal(self.proposal)
        if self.confirmation.decision != "confirmed":
            raise ValueError("Material requirements are not confirmed")
        return self


class MaterialRequirementsView(MaterialWorkflowModel):
    schema_name: Literal["vistora.material-requirements-history"] = (
        "vistora.material-requirements-history"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    state: Literal[
        "empty",
        "reviewable",
        "confirmed",
        "rejected",
        "withdrawn",
    ]
    proposals: tuple[dict, ...] = ()
    decisions: tuple[dict, ...] = ()

