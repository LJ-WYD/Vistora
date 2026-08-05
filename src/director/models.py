"""Versioned, immutable contracts for the production Director Agent."""

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
    field_validator,
    model_validator,
)

from contracts import (
    DirectorOperation,
    DirectorPlan,
    PlanReference,
    SourceEvidenceReference,
)
from plan_review import (
    PlanDiffRequest,
    PlanReviewEnvelope,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshotReference


DIRECTOR_VERSION = "1.0.0"
DirectorVersion = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
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


class DirectorModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: DirectorVersion = DIRECTOR_VERSION


class DirectorError(DirectorModel):
    code: StableId
    message: str = Field(min_length=1)
    retryable: bool = False
    recovery_action: str | None = Field(default=None, min_length=1)


class DirectorToolSchema(DirectorModel):
    tool_name: StableId
    input_schema: dict[str, Any]
    schema_digest: Sha256Digest

    @model_validator(mode="after")
    def digest_is_exact(self) -> DirectorToolSchema:
        if self.schema_digest != digest_json(self.input_schema):
            raise ValueError("Director tool schema digest is mismatched")
        return self


class DirectorMaterialFact(DirectorModel):
    """Browser-safe facts observed through read-only media boundaries."""

    material_id: Annotated[
        str,
        Field(pattern=r"^source_[0-9a-f]{16}$"),
    ]
    media_kind: Literal["video", "audio", "image"]
    display_name: str = Field(min_length=1)
    source_reference: str | None = Field(
        default=None,
        pattern=r"^material://source_[0-9a-f]{16}$",
    )
    duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    observation_status: Literal[
        "observed",
        "missing",
        "unsupported",
        "error",
    ] = "observed"
    evidence: tuple[SourceEvidenceReference, ...] = ()

    @model_validator(mode="after")
    def facts_are_consistent(self) -> DirectorMaterialFact:
        if (self.width is None) != (self.height is None):
            raise ValueError("Material width and height must be paired")
        if any(
            item.material_id != self.material_id for item in self.evidence
        ):
            raise ValueError("Material evidence crosses material identity")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Material evidence IDs must be unique")
        if (
            self.source_reference is not None
            and self.source_reference
            != f"material://{self.material_id}"
        ):
            raise ValueError("Material source reference crosses identity")
        return self


class DirectorReadContext(DirectorModel):
    """Exact detached facts available to one reasoning turn."""

    schema_name: Literal["vistora.director-read-context"] = (
        "vistora.director-read-context"
    )
    snapshot_ref: TimelineSnapshotReference
    registry_ref: RegistrySchemaReference
    project_summary: dict[str, Any]
    materials: tuple[DirectorMaterialFact, ...] = ()
    tool_schemas: tuple[DirectorToolSchema, ...] = ()

    @model_validator(mode="after")
    def context_is_unambiguous(self) -> DirectorReadContext:
        material_ids = [item.material_id for item in self.materials]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("Director materials must be unique")
        tool_names = [item.tool_name for item in self.tool_schemas]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("Director tool schemas must be unique")
        if tuple(tool_names) != tuple(sorted(tool_names)):
            raise ValueError("Director tool schemas require stable ordering")
        if tuple(tool_names) != self.registry_ref.tool_names:
            raise ValueError("Director tool schemas cross registry reference")
        evidence_ids = [
            evidence.evidence_id
            for material in self.materials
            for evidence in material.evidence
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Director context evidence IDs must be unique")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class CreativeBriefInput(DirectorModel):
    """Adapter-authored brief content before deterministic readiness gating."""

    objective: str | None = Field(default=None, min_length=1)
    audience: str | None = Field(default=None, min_length=1)
    platform: str | None = Field(default=None, min_length=1)
    target_duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    style: str | None = Field(default=None, min_length=1)
    narrative: str | None = Field(default=None, min_length=1)
    pacing: str | None = Field(default=None, min_length=1)
    must_haves: tuple[str, ...] = ()
    must_not_haves: tuple[str, ...] = ()
    delivery_requirements: tuple[str, ...] = ()
    material_ids: tuple[StableId, ...] = ()
    evidence_ids: tuple[StableId, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()

    @model_validator(mode="after")
    def lists_are_unique_and_noncontradictory(
        self,
    ) -> CreativeBriefInput:
        for field_name in (
            "must_haves",
            "must_not_haves",
            "delivery_requirements",
            "material_ids",
            "evidence_ids",
            "assumptions",
            "unresolved_questions",
            "acceptance_criteria",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} values must be unique")
        overlap = set(self.must_haves) & set(self.must_not_haves)
        if overlap:
            raise ValueError(
                f"Required and forbidden constraints conflict: {sorted(overlap)}"
            )
        return self


Readiness = Literal[
    "needs_clarification",
    "needs_materials",
    "materials_incomplete",
    "ready_for_material_requirements",
    "ready_to_plan",
    "unsupported_next_stage",
]


class MaterialStateAssessment(DirectorModel):
    """Exact, auditable classification of the Director's observed materials."""

    schema_name: Literal["vistora.director-material-state"] = (
        "vistora.director-material-state"
    )
    assessment_id: StableId
    snapshot_ref: TimelineSnapshotReference
    brief_content_digest: Sha256Digest
    material_facts_digest: Sha256Digest
    state: Literal[
        "materials_complete", "materials_incomplete", "no_materials"
    ]
    observed_material_ids: tuple[StableId, ...] = ()
    unavailable_material_ids: tuple[StableId, ...] = ()
    selected_material_ids: tuple[StableId, ...] = ()
    missing_evidence_material_ids: tuple[StableId, ...] = ()
    reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def classification_is_exact(self) -> "MaterialStateAssessment":
        for field_name in (
            "observed_material_ids",
            "unavailable_material_ids",
            "selected_material_ids",
            "missing_evidence_material_ids",
        ):
            values = getattr(self, field_name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field_name} must use stable unique ordering")
        if set(self.observed_material_ids) & set(self.unavailable_material_ids):
            raise ValueError("Observed and unavailable material sets must be disjoint")
        if self.state == "no_materials" and (
            self.observed_material_ids
            or self.unavailable_material_ids
            or self.selected_material_ids
        ):
            raise ValueError("No-material assessment cannot contain material IDs")
        if self.state == "materials_complete" and (
            not self.observed_material_ids
            or self.unavailable_material_ids
            or not self.selected_material_ids
            or self.missing_evidence_material_ids
            or not set(self.selected_material_ids).issubset(
                self.observed_material_ids
            )
        ):
            raise ValueError("Complete material assessment has unresolved gaps")
        if self.state == "materials_incomplete" and not (
            self.observed_material_ids
            or self.unavailable_material_ids
            or self.selected_material_ids
        ):
            raise ValueError("Incomplete material assessment needs material context")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class CreativeBriefVersion(DirectorModel):
    schema_name: Literal["vistora.director-creative-brief"] = (
        "vistora.director-creative-brief"
    )
    session_id: StableId
    brief_version: int = Field(ge=1)
    content_digest: Sha256Digest
    content: CreativeBriefInput
    readiness: Readiness
    readiness_reasons: tuple[str, ...] = Field(min_length=1)
    material_state: MaterialStateAssessment | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def digest_is_exact(self) -> CreativeBriefVersion:
        if self.content_digest != digest_json(
            self.content.model_dump(mode="json")
        ):
            raise ValueError("Creative brief digest is mismatched")
        return self


class DirectorPlanDraft(DirectorModel):
    """Structured model proposal before Agent-assigned identity/version."""

    objective: str = Field(min_length=1)
    requirements: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    creative_direction: dict[str, Any] = Field(default_factory=dict)
    operations: tuple[DirectorOperation, ...] = Field(min_length=1)
    outputs: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


class RequirementConstraint(DirectorModel):
    status: Literal["known", "unknown", "not_applicable"]
    value: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def value_matches_status(self) -> RequirementConstraint:
        if self.status == "known" and self.value is None:
            raise ValueError("Known requirement constraint needs a value")
        if self.status != "known" and self.value is not None:
            raise ValueError("Unknown/not-applicable constraint has no value")
        return self


class MaterialRequirementItem(DirectorModel):
    item_id: StableId
    asset_type: Literal[
        "video_shot",
        "audio",
        "image",
        "narration",
        "reference_asset",
    ]
    purpose: str = Field(min_length=1)
    narrative_position: str = Field(min_length=1)
    duration_seconds: FiniteFloat | None = Field(default=None, gt=0)
    aspect_ratio: str | None = Field(default=None, min_length=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: FiniteFloat | None = Field(default=None, gt=0)
    audio_requirements: tuple[str, ...] = ()
    continuity_requirements: tuple[str, ...] = ()
    must_haves: tuple[str, ...] = ()
    must_not_haves: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    priority: Literal["required", "high", "medium", "low"]
    dependency_ids: tuple[StableId, ...] = ()
    alternatives: tuple[str, ...] = ()
    budget_constraint: RequirementConstraint
    deadline_constraint: RequirementConstraint

    @model_validator(mode="after")
    def item_is_unambiguous(self) -> MaterialRequirementItem:
        if (self.width is None) != (self.height is None):
            raise ValueError("Material width and height must be paired")
        for values in (
            self.audio_requirements,
            self.continuity_requirements,
            self.must_haves,
            self.must_not_haves,
            self.acceptance_criteria,
            self.dependency_ids,
            self.alternatives,
        ):
            if len(values) != len(set(values)):
                raise ValueError("Material requirement lists must be unique")
        if set(self.must_haves) & set(self.must_not_haves):
            raise ValueError("Material requirement constraints conflict")
        if self.item_id in self.dependency_ids:
            raise ValueError("Material requirement cannot depend on itself")
        return self


class MaterialRequirementsDraft(DirectorModel):
    rationale: str = Field(min_length=1)
    items: tuple[MaterialRequirementItem, ...] = Field(min_length=1)
    global_acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = ()
    unresolved_constraints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def draft_graph_is_exact(self) -> MaterialRequirementsDraft:
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Material requirement item IDs must be unique")
        known = set(ids)
        for item in self.items:
            unknown = set(item.dependency_ids) - known
            if unknown:
                raise ValueError(
                    f"Material requirement {item.item_id} has unknown "
                    f"dependencies: {sorted(unknown)}"
                )
        return self


class CreativeBriefReference(DirectorModel):
    session_id: StableId
    brief_version: int = Field(ge=1)
    brief_digest: Sha256Digest

    @classmethod
    def from_brief(
        cls,
        brief: CreativeBriefVersion,
    ) -> CreativeBriefReference:
        return cls(
            session_id=brief.session_id,
            brief_version=brief.brief_version,
            brief_digest=brief.content_digest,
        )


class MaterialRequirementsPlan(DirectorModel):
    schema_name: Literal["vistora.material-requirements-plan"] = (
        "vistora.material-requirements-plan"
    )
    plan_id: StableId
    plan_version: int = Field(ge=1)
    brief_ref: CreativeBriefReference
    no_material_snapshot_ref: TimelineSnapshotReference
    no_material_fact_digest: Sha256Digest
    created_at: AwareDatetime
    rationale: str = Field(min_length=1)
    items: tuple[MaterialRequirementItem, ...] = Field(min_length=1)
    global_acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = ()
    unresolved_constraints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def plan_is_no_material_and_exact(self) -> MaterialRequirementsPlan:
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Material requirement item IDs must be unique")
        known = set(ids)
        for item in self.items:
            if not set(item.dependency_ids).issubset(known):
                raise ValueError("Material requirement dependency is unknown")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class MaterialRequirementsChange(DirectorModel):
    change_id: StableId
    change_type: Literal["added", "removed", "changed"]
    item_id: StableId
    before_digest: Sha256Digest | None = None
    after_digest: Sha256Digest | None = None
    summary: str = Field(min_length=1)


class MaterialRequirementsReview(DirectorModel):
    schema_name: Literal["vistora.material-requirements-review"] = (
        "vistora.material-requirements-review"
    )
    review_id: StableId
    plan_id: StableId
    plan_version: int = Field(ge=1)
    plan_digest: Sha256Digest
    brief_ref: CreativeBriefReference
    snapshot_ref: TimelineSnapshotReference
    previous_plan_digest: Sha256Digest | None = None
    changes: tuple[MaterialRequirementsChange, ...] = Field(min_length=1)
    review_digest: Sha256Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def review_digest_is_exact(self) -> MaterialRequirementsReview:
        payload = self.model_dump(mode="json", exclude={"review_digest"})
        if self.review_digest != digest_json(payload):
            raise ValueError("Material requirements review digest mismatched")
        return self


class MaterialRequirementsProposal(DirectorModel):
    schema_name: Literal["vistora.material-requirements-proposal"] = (
        "vistora.material-requirements-proposal"
    )
    proposal_id: StableId
    plan: MaterialRequirementsPlan
    review: MaterialRequirementsReview
    created_at: AwareDatetime

    @model_validator(mode="after")
    def proposal_is_exact(self) -> MaterialRequirementsProposal:
        if (
            self.review.plan_id != self.plan.plan_id
            or self.review.plan_version != self.plan.plan_version
            or self.review.plan_digest != self.plan.digest()
            or self.review.brief_ref != self.plan.brief_ref
            or self.review.snapshot_ref != self.plan.no_material_snapshot_ref
        ):
            raise ValueError("Material requirements proposal linkage drifted")
        return self


class DirectorReasoningRequest(DirectorModel):
    schema_name: Literal["vistora.director-reasoning-request"] = (
        "vistora.director-reasoning-request"
    )
    session_id: StableId
    turn_id: StableId
    attempt: int = Field(ge=1, le=3)
    user_message: str = Field(min_length=1)
    previous_brief: CreativeBriefVersion | None = None
    context: DirectorReadContext
    correction_feedback: str | None = Field(default=None, min_length=1)


class DirectorReasoningOutput(DirectorModel):
    """Only accepted model output; no tool-call field exists."""

    schema_name: Literal["vistora.director-reasoning-output"] = (
        "vistora.director-reasoning-output"
    )
    response_kind: Literal[
        "clarify",
        "propose",
        "propose_material_requirements",
        "withdraw",
        "unsupported_next_stage",
    ]
    assistant_message: str = Field(min_length=1)
    context_snapshot_ref: TimelineSnapshotReference
    registry_ref: RegistrySchemaReference
    brief: CreativeBriefInput
    clarification_questions: tuple[str, ...] = ()
    plan_draft: DirectorPlanDraft | None = None
    material_requirements_draft: MaterialRequirementsDraft | None = None
    withdraw_proposal_id: StableId | None = None

    @model_validator(mode="after")
    def response_shape_is_exact(self) -> DirectorReasoningOutput:
        if self.response_kind == "propose":
            if (
                self.plan_draft is None
                or self.material_requirements_draft is not None
                or self.withdraw_proposal_id is not None
            ):
                raise ValueError("Proposal output requires only a plan draft")
        elif self.response_kind == "propose_material_requirements":
            if (
                self.material_requirements_draft is None
                or self.plan_draft is not None
                or self.withdraw_proposal_id is not None
            ):
                raise ValueError(
                    "Material proposal requires only a requirements draft"
                )
        elif (
            self.plan_draft is not None
            or self.material_requirements_draft is not None
        ):
            raise ValueError("Non-proposal output cannot include a plan draft")
        if self.response_kind == "withdraw":
            if self.withdraw_proposal_id is None:
                raise ValueError("Withdrawal requires a proposal ID")
        elif self.withdraw_proposal_id is not None:
            raise ValueError("Only withdrawal may reference a proposal")
        if (
            self.response_kind == "clarify"
            and not self.clarification_questions
        ):
            raise ValueError("Clarification response requires questions")
        return self


class DirectorProposalResult(DirectorModel):
    schema_name: Literal["vistora.director-proposal"] = (
        "vistora.director-proposal"
    )
    proposal_id: StableId
    plan: DirectorPlan
    plan_ref: PlanReference
    review_request: PlanDiffRequest
    review: PlanReviewEnvelope
    created_at: AwareDatetime

    @model_validator(mode="after")
    def proposal_is_exact(self) -> DirectorProposalResult:
        if self.plan_ref != PlanReference.from_plan(self.plan):
            raise ValueError("Director proposal plan digest is mismatched")
        if self.review_request.director_plan != self.plan:
            raise ValueError("Director review request crosses proposal plan")
        if self.review.review_state != "current" or self.review.diff is None:
            raise ValueError("Director proposal requires a current review")
        return self


DirectorTurnStatus = Literal[
    "needs_clarification",
    "needs_materials",
    "materials_incomplete",
    "ready_for_material_requirements",
    "ready_to_plan",
    "proposal_ready",
    "material_requirements_ready",
    "withdrawn",
    "unsupported_next_stage",
    "model_error",
    "stale_context",
]


class DirectorTurnReport(DirectorModel):
    schema_name: Literal["vistora.director-turn-report"] = (
        "vistora.director-turn-report"
    )
    report_id: StableId
    session_id: StableId
    turn_id: StableId
    turn_index: int = Field(ge=1)
    project_id: StableId
    context_digest: Sha256Digest
    status: DirectorTurnStatus
    brief: CreativeBriefVersion
    assistant_message: str = Field(min_length=1)
    clarification_questions: tuple[str, ...] = ()
    proposal: DirectorProposalResult | None = None
    material_requirements: MaterialRequirementsProposal | None = None
    withdrawn_proposal_id: StableId | None = None
    error: DirectorError | None = None
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def report_state_is_truthful(self) -> DirectorTurnReport:
        if self.status == "proposal_ready":
            if (
                self.proposal is None
                or self.material_requirements is not None
                or self.error is not None
            ):
                raise ValueError("Ready proposal report is incomplete")
        elif self.status == "material_requirements_ready":
            if (
                self.material_requirements is None
                or self.proposal is not None
                or self.error is not None
            ):
                raise ValueError(
                    "Material requirements report is incomplete"
                )
        elif self.proposal is not None or self.material_requirements is not None:
            raise ValueError("Non-proposal report cannot claim a proposal")
        if self.status == "withdrawn":
            if self.withdrawn_proposal_id is None:
                raise ValueError("Withdrawal report requires proposal identity")
        elif self.withdrawn_proposal_id is not None:
            raise ValueError("Only withdrawal report may identify withdrawal")
        if self.status in {"model_error", "stale_context"}:
            if self.error is None:
                raise ValueError("Error status requires typed Director error")
        elif self.error is not None:
            raise ValueError("Non-error Director report cannot have an error")
        return self


class DirectorSessionRecord(DirectorModel):
    schema_name: Literal["vistora.director-session-record"] = (
        "vistora.director-session-record"
    )
    record_id: StableId
    session_id: StableId
    project_id: StableId
    turn_id: StableId
    turn_index: int = Field(ge=1)
    safe_user_message: str = Field(min_length=1)
    context_snapshot_ref: TimelineSnapshotReference
    registry_ref: RegistrySchemaReference
    report: DirectorTurnReport
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def record_linkage_is_exact(self) -> DirectorSessionRecord:
        if (
            self.report.session_id != self.session_id
            or self.report.turn_id != self.turn_id
            or self.report.turn_index != self.turn_index
            or self.report.project_id != self.project_id
        ):
            raise ValueError("Director session record crosses turn linkage")
        return self


class DirectorLedgerEntry(DirectorModel):
    schema_name: Literal["vistora.director-ledger-entry"] = (
        "vistora.director-ledger-entry"
    )
    sequence: int = Field(ge=1)
    entry_id: StableId
    previous_entry_digest: Sha256Digest
    record: DirectorSessionRecord
    entry_digest: Sha256Digest

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        entry_id: str,
        previous_entry_digest: str,
        record: DirectorSessionRecord,
    ) -> DirectorLedgerEntry:
        payload = {
            "sequence": sequence,
            "entry_id": entry_id,
            "previous_entry_digest": previous_entry_digest,
            "record": record.model_dump(mode="json"),
        }
        return cls(
            **payload,
            entry_digest=digest_json(payload),
        )

    @model_validator(mode="after")
    def digest_is_exact(self) -> DirectorLedgerEntry:
        payload = {
            "sequence": self.sequence,
            "entry_id": self.entry_id,
            "previous_entry_digest": self.previous_entry_digest,
            "record": self.record.model_dump(mode="json"),
        }
        if self.entry_digest != digest_json(payload):
            raise ValueError("Director ledger entry digest is mismatched")
        return self


class DirectorSessionLedger(DirectorModel):
    schema_name: Literal["vistora.director-session-ledger"] = (
        "vistora.director-session-ledger"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    entries: tuple[DirectorLedgerEntry, ...] = ()
    integrity_digest: Sha256Digest

    @classmethod
    def empty(
        cls,
        *,
        session_id: str,
        project_id: str,
    ) -> DirectorSessionLedger:
        return cls(
            session_id=session_id,
            project_id=project_id,
            revision=0,
            entries=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def chain_is_valid(self) -> DirectorSessionLedger:
        if self.revision != len(self.entries):
            raise ValueError("Director ledger revision must equal entry count")
        previous = GENESIS_DIGEST
        entry_ids: set[str] = set()
        turn_ids: set[str] = set()
        previous_brief_version = 0
        plan_versions: list[int] = []
        plan_id: str | None = None
        material_versions: list[int] = []
        material_plan_id: str | None = None
        known_proposals: set[str] = set()
        for index, entry in enumerate(self.entries, start=1):
            if entry.sequence != index:
                raise ValueError("Director ledger sequence must be contiguous")
            if entry.previous_entry_digest != previous:
                raise ValueError("Director ledger digest chain is broken")
            if entry.entry_id in entry_ids:
                raise ValueError("Director ledger entry ID is duplicated")
            if entry.record.turn_id in turn_ids:
                raise ValueError("Director turn ID is duplicated")
            if entry.record.turn_index != index:
                raise ValueError("Director turn index must be contiguous")
            if (
                entry.record.session_id != self.session_id
                or entry.record.project_id != self.project_id
            ):
                raise ValueError("Director record crosses ledger identity")
            brief_version = entry.record.report.brief.brief_version
            if brief_version < previous_brief_version:
                raise ValueError("Creative brief version cannot decrease")
            previous_brief_version = brief_version
            proposal = entry.record.report.proposal
            if proposal is not None:
                if plan_id is None:
                    plan_id = proposal.plan.plan_id
                elif proposal.plan.plan_id != plan_id:
                    raise ValueError("Director session plan ID changed")
                plan_versions.append(proposal.plan.plan_version)
                if plan_versions != sorted(set(plan_versions)):
                    raise ValueError("Director plan versions must increase")
                known_proposals.add(proposal.proposal_id)
            material = entry.record.report.material_requirements
            if material is not None:
                if material_plan_id is None:
                    material_plan_id = material.plan.plan_id
                elif material.plan.plan_id != material_plan_id:
                    raise ValueError(
                        "Material requirements session plan ID changed"
                    )
                material_versions.append(material.plan.plan_version)
                if material_versions != sorted(set(material_versions)):
                    raise ValueError(
                        "Material requirements versions must increase"
                    )
                known_proposals.add(material.proposal_id)
            withdrawn = entry.record.report.withdrawn_proposal_id
            if withdrawn is not None and withdrawn not in known_proposals:
                raise ValueError("Director withdrawal references unknown proposal")
            entry_ids.add(entry.entry_id)
            turn_ids.add(entry.record.turn_id)
            previous = entry.entry_digest
        if self.integrity_digest != digest_json(
            [entry.entry_digest for entry in self.entries]
        ):
            raise ValueError("Director ledger integrity digest is mismatched")
        return self
