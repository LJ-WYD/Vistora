"""Production Director Agent: dialogue, clarification, and plan proposals only."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from contracts import DirectorPlan, PlanReference
from director import (
    CreativeBriefInput,
    CreativeBriefVersion,
    DirectorAdapterError,
    DirectorAdapterTimeout,
    DirectorError,
    DirectorMaterialFact,
    CreativeBriefReference,
    DirectorProposalResult,
    DirectorReadContext,
    DirectorReasoningAdapter,
    DirectorReasoningOutput,
    DirectorReasoningRequest,
    DirectorSessionLedger,
    DirectorSessionRecord,
    DirectorStore,
    DirectorTurnReport,
    MaterialRequirementsChange,
    MaterialRequirementsPlan,
    MaterialRequirementsProposal,
    MaterialRequirementsReview,
    digest_json,
)
from plan_review import (
    PlanDiffRequest,
    PlanReviewService,
    PreviewMaterialFact,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshot, TimelineSnapshotReference


Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]
ContextProvider = Callable[[], tuple[DirectorReadContext, TimelineSnapshot]]

_WINDOWS_PATH = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s\"']+")
_POSIX_PATH = re.compile(
    r"(?<![\w:])/(?:Users|home|tmp|var|etc)/(?:[^\s\"']+)"
)
_SECRET = re.compile(
    r"(?i)(?:"
    r"sk-[a-z0-9]{20,}|"
    r"ghp_[a-z0-9]{30,}|"
    r"github_pat_[a-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+"
    r")"
)
_DISALLOWED_DIRECTOR_TOOLS = {
    "VideoApplyManualEditsSkill",
    "VideoRestoreTimelineCheckpointSkill",
}
_REQUIRED_BRIEF_FIELDS = (
    "objective",
    "audience",
    "platform",
    "target_duration_seconds",
    "style",
    "narrative",
    "pacing",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _safe_user_text(value: str) -> str:
    safe = _WINDOWS_PATH.sub("[redacted-path]", value)
    safe = _POSIX_PATH.sub("[redacted-path]", safe)
    safe = _SECRET.sub("[redacted-secret]", safe)
    return safe.strip()


def _assert_display_safe(value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if _WINDOWS_PATH.search(encoded) or _POSIX_PATH.search(encoded):
        raise ValueError("Director output contains an absolute filesystem path")
    if _SECRET.search(encoded):
        raise ValueError("Director output contains secret-like content")


class DirectorAgent:
    """General-capability, directing-specialized proposal runtime.

    This class has no confirmation, execution, rollback, timeline manager,
    renderer, skill implementation, or tool-dispatch dependency.
    """

    def __init__(
        self,
        *,
        adapter: DirectorReasoningAdapter,
        context_provider: ContextProvider,
        registry: Mapping[str, Any],
        store: DirectorStore,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _random_id,
        max_schema_attempts: int = 2,
    ) -> None:
        if max_schema_attempts < 1 or max_schema_attempts > 3:
            raise ValueError("Director schema attempts must be between 1 and 3")
        self._adapter = adapter
        self._context_provider = context_provider
        self._registry = registry
        self._store = store
        self._clock = clock
        self._id_factory = id_factory
        self._max_schema_attempts = max_schema_attempts

    def converse(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
    ) -> DirectorTurnReport:
        """Process one user turn and stop at a read-only reviewed proposal."""

        safe_message = _safe_user_text(user_message)
        if not safe_message:
            raise ValueError("Director user message cannot be empty")
        context, snapshot = self._context_provider()
        self._validate_context(context, snapshot)
        ledger = self._store.load(
            session_id=session_id,
            project_id=context.snapshot_ref.project_id,
        )
        turn_index = ledger.revision + 1
        previous_brief = (
            ledger.entries[-1].record.report.brief
            if ledger.entries
            else None
        )
        output, error = self._reason(
            session_id=session_id,
            turn_id=turn_id,
            safe_message=safe_message,
            previous_brief=previous_brief,
            context=context,
        )
        if error is not None:
            brief = previous_brief or self._brief(
                session_id=session_id,
                previous=None,
                content=CreativeBriefInput(),
                context=context,
                unsupported=False,
            )
            report = self._error_report(
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                brief=brief,
                error=error,
            )
            return self._persist(
                ledger=ledger,
                context=context,
                safe_message=safe_message,
                report=report,
            )

        assert output is not None
        try:
            _assert_display_safe(output.model_dump(mode="json"))
            if (
                output.context_snapshot_ref != context.snapshot_ref
                or output.registry_ref != context.registry_ref
            ):
                raise ValueError(
                    "Director reasoning output crosses its exact read context"
                )
            refreshed_context, refreshed_snapshot = self._context_provider()
            self._validate_context(refreshed_context, refreshed_snapshot)
            if (
                refreshed_context.digest() != context.digest()
                or TimelineSnapshotReference.from_snapshot(
                    refreshed_snapshot
                )
                != context.snapshot_ref
            ):
                stale = DirectorError(
                    code="director_context_stale",
                    message=(
                        "Timeline, media facts, provenance, or registry schemas "
                        "changed during the Director turn."
                    ),
                    retryable=True,
                    recovery_action=(
                        "Refresh read-only context and repeat the turn."
                    ),
                )
                brief = previous_brief or self._brief(
                    session_id=session_id,
                    previous=None,
                    content=CreativeBriefInput(),
                    context=context,
                    unsupported=False,
                )
                report = self._error_report(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_index,
                    context=context,
                    brief=brief,
                    error=stale,
                    status="stale_context",
                )
                return self._persist(
                    ledger=ledger,
                    context=context,
                    safe_message=safe_message,
                    report=report,
                )

            self._validate_brief_references(output.brief, context)
            brief = self._brief(
                session_id=session_id,
                previous=previous_brief,
                content=output.brief,
                context=context,
                unsupported=(
                    output.response_kind == "unsupported_next_stage"
                ),
            )
            report = self._report_from_output(
                ledger=ledger,
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                snapshot=snapshot,
                brief=brief,
                output=output,
            )
        except (ValueError, ValidationError) as exc:
            brief = previous_brief or self._brief(
                session_id=session_id,
                previous=None,
                content=CreativeBriefInput(),
                context=context,
                unsupported=False,
            )
            report = self._error_report(
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                brief=brief,
                error=DirectorError(
                    code="director_output_rejected",
                    message=str(exc),
                    recovery_action=(
                        "Clarify the request or retry with schema-valid, "
                        "context-bound output."
                    ),
                ),
            )
        return self._persist(
            ledger=ledger,
            context=context,
            safe_message=safe_message,
            report=report,
        )

    def _validate_context(
        self,
        context: DirectorReadContext,
        snapshot: TimelineSnapshot,
    ) -> None:
        if (
            TimelineSnapshotReference.from_snapshot(snapshot)
            != context.snapshot_ref
        ):
            raise ValueError("Director context crosses timeline snapshot")
        if (
            RegistrySchemaReference.from_registry(self._registry)
            != context.registry_ref
        ):
            raise ValueError("Director context crosses registry schemas")
        _assert_display_safe(context.model_dump(mode="json"))

    def _reason(
        self,
        *,
        session_id: str,
        turn_id: str,
        safe_message: str,
        previous_brief: CreativeBriefVersion | None,
        context: DirectorReadContext,
    ) -> tuple[DirectorReasoningOutput | None, DirectorError | None]:
        feedback = None
        for attempt in range(1, self._max_schema_attempts + 1):
            request = DirectorReasoningRequest(
                session_id=session_id,
                turn_id=turn_id,
                attempt=attempt,
                user_message=safe_message,
                previous_brief=previous_brief,
                context=context,
                correction_feedback=feedback,
            )
            try:
                raw = self._adapter.complete(request)
                if isinstance(raw, str):
                    raw = json.loads(raw)
                output = DirectorReasoningOutput.model_validate(raw)
                return output, None
            except DirectorAdapterTimeout as exc:
                return None, DirectorError(
                    code="director_model_timeout",
                    message=str(exc),
                    retryable=True,
                    recovery_action="Retry the Director turn.",
                )
            except DirectorAdapterError as exc:
                return None, DirectorError(
                    code="director_model_error",
                    message=str(exc),
                    retryable=True,
                    recovery_action=(
                        "Retry after checking the reasoning provider."
                    ),
                )
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                feedback = (
                    "The prior response was malformed or violated the exact "
                    f"DirectorReasoningOutput schema: {type(exc).__name__}."
                )
        return None, DirectorError(
            code="director_schema_rejected",
            message=(
                "Director reasoning output remained malformed after the "
                "bounded schema retry policy."
            ),
            recovery_action=(
                "Retry the turn or inspect the configured reasoning adapter."
            ),
        )

    @staticmethod
    def _validate_brief_references(
        content: CreativeBriefInput,
        context: DirectorReadContext,
    ) -> None:
        known_materials = {
            material.material_id for material in context.materials
        }
        known_evidence = {
            evidence.evidence_id
            for material in context.materials
            for evidence in material.evidence
        }
        unknown_materials = set(content.material_ids) - known_materials
        unknown_evidence = set(content.evidence_ids) - known_evidence
        if unknown_materials:
            raise ValueError(
                f"Brief references unobserved materials: {sorted(unknown_materials)}"
            )
        if unknown_evidence:
            raise ValueError(
                f"Brief references unobserved evidence: {sorted(unknown_evidence)}"
            )

    def _brief(
        self,
        *,
        session_id: str,
        previous: CreativeBriefVersion | None,
        content: CreativeBriefInput,
        context: DirectorReadContext,
        unsupported: bool,
    ) -> CreativeBriefVersion:
        missing = [
            field_name
            for field_name in _REQUIRED_BRIEF_FIELDS
            if getattr(content, field_name) is None
        ]
        reasons: list[str] = []
        if unsupported:
            readiness = "unsupported_next_stage"
            reasons.append(
                "The request requires no-material generation or a later "
                "creative-production stage that is not implemented."
            )
        elif missing or content.unresolved_questions:
            readiness = "needs_clarification"
            if missing:
                reasons.append(
                    "Missing creative brief fields: " + ", ".join(missing)
                )
            if content.unresolved_questions:
                reasons.append(
                    "Unresolved questions remain: "
                    + "; ".join(content.unresolved_questions)
                )
        elif not content.delivery_requirements:
            readiness = "needs_clarification"
            reasons.append("Delivery requirements are missing.")
        elif not content.acceptance_criteria:
            readiness = "needs_clarification"
            reasons.append("Acceptance criteria are missing.")
        elif not context.materials:
            readiness = "ready_for_material_requirements"
            reasons.append(
                "The creative brief is complete and no observed materials "
                "exist; a material requirements proposal may be reviewed."
            )
        elif not content.material_ids:
            readiness = "needs_clarification"
            reasons.append(
                "The brief has not selected any observed source material."
            )
        elif not content.evidence_ids:
            readiness = "needs_clarification"
            reasons.append(
                "The brief has not bound any observed source evidence."
            )
        else:
            readiness = "ready_to_plan"
            reasons.append(
                "Required creative constraints, observed materials, evidence, "
                "delivery requirements, and acceptance criteria are present."
            )
        content_digest = digest_json(content.model_dump(mode="json"))
        if previous is None:
            version = 1
        elif previous.content_digest == content_digest:
            version = previous.brief_version
        else:
            version = previous.brief_version + 1
        return CreativeBriefVersion(
            session_id=session_id,
            brief_version=version,
            content_digest=content_digest,
            content=content,
            readiness=readiness,
            readiness_reasons=tuple(reasons),
            updated_at=self._clock(),
        )

    def _report_from_output(
        self,
        *,
        ledger: DirectorSessionLedger,
        session_id: str,
        turn_id: str,
        turn_index: int,
        context: DirectorReadContext,
        snapshot: TimelineSnapshot,
        brief: CreativeBriefVersion,
        output: DirectorReasoningOutput,
    ) -> DirectorTurnReport:
        if output.response_kind == "withdraw":
            known = {
                entry.record.report.proposal.proposal_id
                for entry in ledger.entries
                if entry.record.report.proposal is not None
            }
            known.update(
                entry.record.report.material_requirements.proposal_id
                for entry in ledger.entries
                if entry.record.report.material_requirements is not None
            )
            if output.withdraw_proposal_id not in known:
                raise ValueError("Director withdrawal references unknown proposal")
            return self._report(
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                status="withdrawn",
                brief=brief,
                assistant_message=output.assistant_message,
                withdrawn_proposal_id=output.withdraw_proposal_id,
            )
        if brief.readiness == "ready_for_material_requirements":
            if output.response_kind != "propose_material_requirements":
                return self._report(
                    session_id=session_id,
                    turn_id=turn_id,
                    turn_index=turn_index,
                    context=context,
                    status="ready_for_material_requirements",
                    brief=brief,
                    assistant_message=output.assistant_message,
                    clarification_questions=output.clarification_questions,
                )
            material_requirements = self._material_requirements(
                ledger=ledger,
                context=context,
                brief=brief,
                output=output,
            )
            return self._report(
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                status="material_requirements_ready",
                brief=brief,
                assistant_message=output.assistant_message,
                material_requirements=material_requirements,
            )
        if brief.readiness != "ready_to_plan":
            return self._report(
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                status=brief.readiness,
                brief=brief,
                assistant_message=output.assistant_message,
                clarification_questions=output.clarification_questions,
            )
        if output.response_kind != "propose":
            return self._report(
                session_id=session_id,
                turn_id=turn_id,
                turn_index=turn_index,
                context=context,
                status="ready_to_plan",
                brief=brief,
                assistant_message=output.assistant_message,
                clarification_questions=output.clarification_questions,
            )
        proposal = self._proposal(
            ledger=ledger,
            context=context,
            snapshot=snapshot,
            brief=brief,
            output=output,
        )
        return self._report(
            session_id=session_id,
            turn_id=turn_id,
            turn_index=turn_index,
            context=context,
            status="proposal_ready",
            brief=brief,
            assistant_message=output.assistant_message,
            proposal=proposal,
        )

    def _proposal(
        self,
        *,
        ledger: DirectorSessionLedger,
        context: DirectorReadContext,
        snapshot: TimelineSnapshot,
        brief: CreativeBriefVersion,
        output: DirectorReasoningOutput,
    ) -> DirectorProposalResult:
        draft = output.plan_draft
        assert draft is not None
        if draft.objective != brief.content.objective:
            raise ValueError("Director plan objective drifts from creative brief")
        known_evidence = {
            evidence.evidence_id: evidence
            for material in context.materials
            for evidence in material.evidence
        }
        selected_evidence = tuple(
            known_evidence[evidence_id]
            for evidence_id in brief.content.evidence_ids
        )
        selected_ids = set(brief.content.evidence_ids)
        for operation in draft.operations:
            if operation.tool_name in _DISALLOWED_DIRECTOR_TOOLS:
                raise ValueError(
                    f"Director cannot propose workflow-only tool "
                    f"{operation.tool_name}"
                )
            skill = self._registry.get(operation.tool_name)
            if skill is None:
                raise ValueError(
                    f"Director proposed unregistered tool {operation.tool_name}"
                )
            if not set(operation.evidence_ids).issubset(selected_ids):
                raise ValueError(
                    f"Operation {operation.operation_id} references evidence "
                    "outside the current brief"
                )
            input_model = getattr(skill, "input_model", None)
            if input_model is None:
                raise ValueError(
                    f"Registered tool {operation.tool_name} has no schema"
                )
            input_model.model_validate(operation.arguments)
            _assert_display_safe(operation.arguments)
        previous_proposals = [
            entry.record.report.proposal
            for entry in ledger.entries
            if entry.record.report.proposal is not None
        ]
        plan_id = (
            previous_proposals[-1].plan.plan_id
            if previous_proposals
            else self._id_factory("director_plan")
        )
        plan_version = (
            previous_proposals[-1].plan.plan_version + 1
            if previous_proposals
            else 1
        )
        plan = DirectorPlan(
            plan_id=plan_id,
            plan_version=plan_version,
            created_at=self._clock(),
            objective=draft.objective,
            requirements=draft.requirements,
            assumptions=draft.assumptions,
            creative_direction=draft.creative_direction,
            source_evidence=selected_evidence,
            operations=draft.operations,
            outputs=draft.outputs,
            risks=draft.risks,
        )
        _assert_display_safe(plan.model_dump(mode="json"))
        proposed_execution = (
            ProposedEditingExecutionPlan.from_director_plan(
                proposal_execution_id=self._id_factory(
                    "proposed_execution"
                ),
                project_id=context.snapshot_ref.project_id,
                director_plan=plan,
            )
        )
        request = PlanDiffRequest(
            request_id=self._id_factory("plan_review_request"),
            snapshot_ref=context.snapshot_ref,
            director_plan=plan,
            proposed_execution=proposed_execution,
            registry_ref=context.registry_ref,
            material_facts=self._preview_materials(context.materials),
        )
        review = PlanReviewService.review(request, snapshot, self._registry)
        if (
            review.review_state != "current"
            or review.diff is None
            or review.diff.review_status == "blocked"
        ):
            raise ValueError(
                "Director proposal is stale, invalid, or unpreviewable: "
                f"{review.message}"
            )
        return DirectorProposalResult(
            proposal_id=self._id_factory("director_proposal"),
            plan=plan,
            plan_ref=PlanReference.from_plan(plan),
            review_request=request,
            review=review,
            created_at=self._clock(),
        )

    def _material_requirements(
        self,
        *,
        ledger: DirectorSessionLedger,
        context: DirectorReadContext,
        brief: CreativeBriefVersion,
        output: DirectorReasoningOutput,
    ) -> MaterialRequirementsProposal:
        draft = output.material_requirements_draft
        assert draft is not None
        if context.materials:
            raise ValueError(
                "Material requirements proposal requires no observed materials"
            )
        previous = [
            entry.record.report.material_requirements
            for entry in ledger.entries
            if entry.record.report.material_requirements is not None
        ]
        plan_id = (
            previous[-1].plan.plan_id
            if previous
            else self._id_factory("material_requirements_plan")
        )
        version = previous[-1].plan.plan_version + 1 if previous else 1
        no_material_fact_digest = digest_json(
            {
                "snapshot_ref": context.snapshot_ref.model_dump(mode="json"),
                "material_ids": [],
            }
        )
        plan = MaterialRequirementsPlan(
            plan_id=plan_id,
            plan_version=version,
            brief_ref=CreativeBriefReference.from_brief(brief),
            no_material_snapshot_ref=context.snapshot_ref,
            no_material_fact_digest=no_material_fact_digest,
            created_at=self._clock(),
            rationale=draft.rationale,
            items=draft.items,
            global_acceptance_criteria=draft.global_acceptance_criteria,
            assumptions=draft.assumptions,
            unresolved_constraints=draft.unresolved_constraints,
        )
        before = (
            {item.item_id: item for item in previous[-1].plan.items}
            if previous
            else {}
        )
        after = {item.item_id: item for item in plan.items}
        changes = []
        for item_id in sorted(before.keys() | after.keys()):
            old = before.get(item_id)
            new = after.get(item_id)
            if old is None:
                change_type = "added"
                summary = f"Add required {new.asset_type} material."
            elif new is None:
                change_type = "removed"
                summary = f"Remove planned {old.asset_type} material."
            elif old == new:
                continue
            else:
                change_type = "changed"
                summary = f"Revise required {new.asset_type} material."
            changes.append(
                MaterialRequirementsChange(
                    change_id=self._id_factory("material_change"),
                    change_type=change_type,
                    item_id=item_id,
                    before_digest=(
                        digest_json(old.model_dump(mode="json"))
                        if old is not None
                        else None
                    ),
                    after_digest=(
                        digest_json(new.model_dump(mode="json"))
                        if new is not None
                        else None
                    ),
                    summary=summary,
                )
            )
        if not changes:
            raise ValueError(
                "Material requirements revision contains no changes"
            )
        review_values = {
            "schema_version": "1.0.0",
            "schema_name": "vistora.material-requirements-review",
            "review_id": self._id_factory("material_review"),
            "plan_id": plan.plan_id,
            "plan_version": plan.plan_version,
            "plan_digest": plan.digest(),
            "brief_ref": plan.brief_ref,
            "snapshot_ref": plan.no_material_snapshot_ref,
            "previous_plan_digest": (
                previous[-1].plan.digest() if previous else None
            ),
            "changes": tuple(changes),
            "created_at": self._clock(),
        }
        shell = MaterialRequirementsReview.model_construct(
            **review_values,
            review_digest="sha256:" + ("0" * 64),
        )
        review = MaterialRequirementsReview(
            **review_values,
            review_digest=digest_json(
                shell.model_dump(mode="json", exclude={"review_digest"})
            ),
        )
        return MaterialRequirementsProposal(
            proposal_id=self._id_factory("material_proposal"),
            plan=plan,
            review=review,
            created_at=self._clock(),
        )

    @staticmethod
    def _preview_materials(
        materials: tuple[DirectorMaterialFact, ...],
    ) -> tuple[PreviewMaterialFact, ...]:
        facts = []
        for material in materials:
            if (
                material.observation_status != "observed"
                or material.duration_seconds is None
            ):
                continue
            if material.media_kind == "video" and (
                material.width is None or material.height is None
            ):
                continue
            facts.append(
                PreviewMaterialFact(
                    material_id=material.material_id,
                    media_kind=material.media_kind,
                    duration_seconds=material.duration_seconds,
                    width=material.width,
                    height=material.height,
                )
            )
        return tuple(facts)

    def _report(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_index: int,
        context: DirectorReadContext,
        status: str,
        brief: CreativeBriefVersion,
        assistant_message: str,
        clarification_questions: tuple[str, ...] = (),
        proposal: DirectorProposalResult | None = None,
        material_requirements: MaterialRequirementsProposal | None = None,
        withdrawn_proposal_id: str | None = None,
    ) -> DirectorTurnReport:
        return DirectorTurnReport(
            report_id=self._id_factory("director_report"),
            session_id=session_id,
            turn_id=turn_id,
            turn_index=turn_index,
            project_id=context.snapshot_ref.project_id,
            context_digest=context.digest(),
            status=status,
            brief=brief,
            assistant_message=assistant_message,
            clarification_questions=clarification_questions,
            proposal=proposal,
            material_requirements=material_requirements,
            withdrawn_proposal_id=withdrawn_proposal_id,
            finished_at=self._clock(),
        )

    def _error_report(
        self,
        *,
        session_id: str,
        turn_id: str,
        turn_index: int,
        context: DirectorReadContext,
        brief: CreativeBriefVersion,
        error: DirectorError,
        status: str = "model_error",
    ) -> DirectorTurnReport:
        return DirectorTurnReport(
            report_id=self._id_factory("director_report"),
            session_id=session_id,
            turn_id=turn_id,
            turn_index=turn_index,
            project_id=context.snapshot_ref.project_id,
            context_digest=context.digest(),
            status=status,
            brief=brief,
            assistant_message=(
                "I could not produce a safe, current Director response."
            ),
            error=error,
            finished_at=self._clock(),
        )

    def _persist(
        self,
        *,
        ledger: DirectorSessionLedger,
        context: DirectorReadContext,
        safe_message: str,
        report: DirectorTurnReport,
    ) -> DirectorTurnReport:
        record = DirectorSessionRecord(
            record_id=self._id_factory("director_record"),
            session_id=report.session_id,
            project_id=report.project_id,
            turn_id=report.turn_id,
            turn_index=report.turn_index,
            safe_user_message=safe_message,
            context_snapshot_ref=context.snapshot_ref,
            registry_ref=context.registry_ref,
            report=report,
            recorded_at=self._clock(),
        )
        _assert_display_safe(record.model_dump(mode="json"))
        self._store.append(
            record,
            entry_id=self._id_factory("director_entry"),
            expected_revision=ledger.revision,
        )
        return report


__all__ = ["DirectorAgent"]
