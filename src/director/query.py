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
    limitations: tuple[str, ...] = (
        "Director proposals are not user confirmations.",
        "No-material creative planning or media generation is not implemented.",
        "Execution and rollback remain separate application services.",
    )


class DirectorHistoryQuery:
    """Exclude raw prompts, tool arguments, paths, and provider payloads."""

    @staticmethod
    def project(ledger: DirectorSessionLedger) -> DirectorHistoryView:
        turns = []
        proposals = []
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
        return DirectorHistoryView(
            session_id=ledger.session_id,
            project_id=ledger.project_id,
            ledger_revision=ledger.revision,
            integrity_digest=ledger.integrity_digest,
            latest_status=latest_status,
            latest_brief=latest_brief,
            turns=tuple(turns),
            proposals=tuple(proposals),
        )
