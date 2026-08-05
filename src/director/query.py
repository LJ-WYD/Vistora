"""Browser-safe deterministic projection of Director session history."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import DirectorModel, DirectorSessionLedger


class DirectorHistoryView(DirectorModel):
    schema_name: Literal["vistora.director-history"] = (
        "vistora.director-history"
    )
    session_id: str = Field(min_length=3)
    project_id: str = Field(min_length=3)
    ledger_revision: int = Field(ge=0)
    integrity_digest: str
    latest_status: str
    latest_brief: dict[str, Any] | None = None
    turns: tuple[dict[str, Any], ...] = ()
    proposals: tuple[dict[str, Any], ...] = ()
    material_requirements: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = (
        "Director proposals are not user confirmations.",
        "Material planning and production use separate confirmed services.",
        "No online media provider is configured by default.",
        "Execution and rollback remain separate application services.",
    )


class DirectorHistoryQuery:
    """Exclude raw prompts, tool arguments, paths, and provider payloads."""

    @staticmethod
    def project(ledger: DirectorSessionLedger) -> DirectorHistoryView:
        turns = []
        proposals = []
        material_requirements = []
        latest_brief = None
        latest_status = "empty"
        for entry in ledger.entries:
            report = entry.record.report
            latest_status = report.status
            latest_brief = {
                "brief_version": report.brief.brief_version,
                "content_digest": report.brief.content_digest,
                "readiness": report.brief.readiness,
                "readiness_reasons": list(
                    report.brief.readiness_reasons
                ),
                "objective": report.brief.content.objective,
                "audience": report.brief.content.audience,
                "platform": report.brief.content.platform,
                "target_duration_seconds": (
                    report.brief.content.target_duration_seconds
                ),
                "style": report.brief.content.style,
                "narrative": report.brief.content.narrative,
                "pacing": report.brief.content.pacing,
                "must_haves": list(report.brief.content.must_haves),
                "must_not_haves": list(
                    report.brief.content.must_not_haves
                ),
                "delivery_requirements": list(
                    report.brief.content.delivery_requirements
                ),
                "material_ids": list(report.brief.content.material_ids),
                "evidence_ids": list(report.brief.content.evidence_ids),
                "assumptions": list(report.brief.content.assumptions),
                "unresolved_questions": list(
                    report.brief.content.unresolved_questions
                ),
                "acceptance_criteria": list(
                    report.brief.content.acceptance_criteria
                ),
                "material_state": (
                    report.brief.material_state.model_dump(mode="json")
                    if report.brief.material_state is not None
                    else None
                ),
            }
            turns.append(
                {
                    "turn_id": report.turn_id,
                    "turn_index": report.turn_index,
                    "status": report.status,
                    "assistant_message": report.assistant_message,
                    "clarification_questions": list(
                        report.clarification_questions
                    ),
                    "brief_version": report.brief.brief_version,
                    "context_digest": report.context_digest,
                    "error": (
                        report.error.model_dump(mode="json")
                        if report.error
                        else None
                    ),
                    "withdrawn_proposal_id": (
                        report.withdrawn_proposal_id
                    ),
                }
            )
            if report.proposal is not None:
                proposals.append(
                    {
                        "proposal_id": report.proposal.proposal_id,
                        "plan_id": report.proposal.plan.plan_id,
                        "plan_version": report.proposal.plan.plan_version,
                        "plan_digest": report.proposal.plan.digest(),
                        "review_state": report.proposal.review.review_state,
                        "review_status": (
                            report.proposal.review.diff.review_status
                            if report.proposal.review.diff
                            else None
                        ),
                        "diff_digest": (
                            report.proposal.review.diff_digest
                        ),
                    }
                )
            if report.material_requirements is not None:
                proposal = report.material_requirements
                material_requirements.append(
                    {
                        "proposal_id": proposal.proposal_id,
                        "plan_id": proposal.plan.plan_id,
                        "plan_version": proposal.plan.plan_version,
                        "plan_digest": proposal.plan.digest(),
                        "review_id": proposal.review.review_id,
                        "review_digest": proposal.review.review_digest,
                        "brief_version": (
                            proposal.plan.brief_ref.brief_version
                        ),
                        "item_count": len(proposal.plan.items),
                        "items": tuple(
                            {
                                "item_id": item.item_id,
                                "asset_type": item.asset_type,
                                "purpose": item.purpose,
                                "narrative_position": (
                                    item.narrative_position
                                ),
                                "priority": item.priority,
                                "acceptance_criteria": (
                                    item.acceptance_criteria
                                ),
                            }
                            for item in proposal.plan.items
                        ),
                    }
                )
        return DirectorHistoryView(
            session_id=ledger.session_id,
            project_id=ledger.project_id,
            ledger_revision=ledger.revision,
            integrity_digest=ledger.integrity_digest,
            latest_status=latest_status,
            latest_brief=latest_brief,
            turns=tuple(turns),
            proposals=tuple(proposals),
            material_requirements=tuple(material_requirements),
        )
