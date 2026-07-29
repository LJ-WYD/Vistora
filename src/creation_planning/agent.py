"""Production constrained CreationPlanningAgent."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from director import digest_json

from .adapters import (
    CreationPlanningAdapter,
    CreationPlanningAdapterError,
    CreationPlanningAdapterTimeout,
)
from .models import (
    CapabilityRegistryReference,
    CreationPlanningReasoningOutput,
    CreationPlanningReport,
    CreationPlanningRequest,
    MaterialConfirmationReference,
    MaterialProductionChange,
    MaterialProductionPlan,
    MaterialProductionProposal,
    MaterialProductionReview,
)
from .service import CreationPlanningError, CreationPlanningService


_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:\\|file://|/(?:Users|home)/)")
_FORBIDDEN_AUTHORITY = re.compile(
    r"(?:tool[_ -]?call|Video[A-Za-z]+Skill|TimelineManager|"
    r"EditingAgent|DirectorAgent|execute\s*\()",
    re.IGNORECASE,
)
_SECRET = re.compile(
    r"(?:api[_-]?key|access[_-]?token|authorization:\s*bearer|"
    r"password\s*[:=])",
    re.IGNORECASE,
)


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class CreationPlanningAgent:
    """Plans how to produce confirmed requirements; never produces anything."""

    def __init__(
        self,
        *,
        adapter: CreationPlanningAdapter,
        service: CreationPlanningService,
        capability_provider: Callable[[], CapabilityRegistryReference],
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
        max_schema_attempts: int = 2,
    ) -> None:
        self.adapter = adapter
        self.service = service
        self.capability_provider = capability_provider
        self.clock = clock
        self.id_factory = id_factory
        self.max_schema_attempts = max_schema_attempts

    def prepare_request(
        self,
        *,
        request_id: str,
        material_confirmation_id: str,
    ) -> CreationPlanningRequest:
        confirmed = self.service.exact_material_confirmation(
            material_confirmation_id
        )
        return CreationPlanningRequest(
            request_id=request_id,
            material_confirmation_ref=(
                MaterialConfirmationReference.from_confirmed(confirmed)
            ),
            capability_registry_ref=self.capability_provider(),
        )

    def plan(self, request: CreationPlanningRequest) -> CreationPlanningReport:
        try:
            exact = self.service.exact_material_confirmation(
                request.material_confirmation_ref.confirmation_id
            )
            material_ref = MaterialConfirmationReference.from_confirmed(exact)
            capabilities = self.capability_provider()
            if material_ref != request.material_confirmation_ref:
                raise CreationPlanningError(
                    "Material confirmation binding is stale or mismatched"
                )
            if capabilities != request.capability_registry_ref:
                raise CreationPlanningError(
                    "Capability registry changed; regenerate the request"
                )
        except Exception as exc:
            return self._report(
                request,
                status="stale_context",
                message=str(exc),
                error_code="creation_context_stale",
            )

        output = None
        last_error = None
        for _ in range(self.max_schema_attempts):
            try:
                raw = self.adapter.complete(request)
                output = CreationPlanningReasoningOutput.model_validate(raw)
                break
            except CreationPlanningAdapterTimeout as exc:
                return self._report(
                    request,
                    status="model_error",
                    message=str(exc),
                    error_code="creation_provider_timeout",
                )
            except CreationPlanningAdapterError as exc:
                return self._report(
                    request,
                    status="model_error",
                    message=str(exc),
                    error_code="creation_provider_error",
                )
            except (ValidationError, ValueError, TypeError) as exc:
                last_error = exc
        if output is None:
            return self._report(
                request,
                status="model_error",
                message="Creation planning output failed strict validation.",
                error_code="creation_schema_rejected",
            )
        if (
            output.material_confirmation_ref
            != request.material_confirmation_ref
            or output.capability_registry_ref
            != request.capability_registry_ref
        ):
            return self._report(
                request,
                status="rejected",
                message="Creation planning output drifted from its exact input.",
                error_code="creation_binding_mismatch",
            )
        output_text = output.model_dump_json()
        if (
            _ABSOLUTE_PATH.search(output_text)
            or _FORBIDDEN_AUTHORITY.search(output_text)
            or _SECRET.search(output_text)
        ):
            return self._report(
                request,
                status="rejected",
                message=(
                    "Creation planning output requested forbidden authority "
                    "or contained unsafe display data."
                ),
                error_code="creation_output_unsafe",
            )
        if output.outcome != "proposal":
            return self._report(
                request,
                status=output.outcome,
                message=output.message,
            )
        try:
            proposal = self._proposal(request, exact, output)
            ledger = self.service.store.load(
                session_id=self.service.session_id,
                project_id=self.service.project_id,
            )
            self.service.record(
                proposal,
                expected_revision=ledger.revision,
            )
        except (ValidationError, ValueError, CreationPlanningError) as exc:
            return self._report(
                request,
                status="rejected",
                message=str(exc),
                error_code="creation_plan_rejected",
            )
        return self._report(
            request,
            status="proposal_ready",
            message=output.message,
            proposal=proposal,
        )

    def _proposal(self, request, confirmed, output):
        draft = output.plan_draft
        assert draft is not None
        serialized = json.dumps(
            draft.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        if _ABSOLUTE_PATH.search(serialized):
            raise CreationPlanningError(
                "Production plan contains an absolute path"
            )
        if _FORBIDDEN_AUTHORITY.search(serialized):
            raise CreationPlanningError(
                "Production plan requests forbidden execution authority"
            )
        requirement_ids = {
            item.item_id for item in confirmed.proposal.plan.items
        }
        registry = {
            item.capability_id: item
            for item in request.capability_registry_ref.capabilities
        }
        for task in draft.tasks:
            if task.requirement_item_id not in requirement_ids:
                raise CreationPlanningError(
                    "Production task references an unknown requirement"
                )
            unknown = set(task.capability_ids) - set(registry)
            if unknown:
                raise CreationPlanningError(
                    "Production task references an unknown capability"
                )
            unavailable = [
                registry[item]
                for item in task.capability_ids
                if registry[item].availability != "available"
            ]
            if unavailable and task.status == "planned":
                raise CreationPlanningError(
                    "Unavailable capability cannot be presented as planned"
                )
        ledger = self.service.store.load(
            session_id=self.service.session_id,
            project_id=self.service.project_id,
        )
        previous = [
            event.proposal
            for event in ledger.events
            if event.proposal is not None
            and event.proposal.plan.material_confirmation_ref.confirmation_id
            == request.material_confirmation_ref.confirmation_id
        ]
        plan_id = (
            previous[-1].plan.production_plan_id
            if previous
            else self.id_factory("material_production_plan")
        )
        plan = MaterialProductionPlan(
            production_plan_id=plan_id,
            plan_version=(
                previous[-1].plan.plan_version + 1 if previous else 1
            ),
            material_confirmation_ref=request.material_confirmation_ref,
            capability_registry_ref=request.capability_registry_ref,
            created_at=self.clock(),
            **draft.model_dump(),
        )
        before = (
            {task.task_id: task for task in previous[-1].plan.tasks}
            if previous
            else {}
        )
        after = {task.task_id: task for task in plan.tasks}
        changes = []
        for task_id in sorted(before.keys() | after.keys()):
            old = before.get(task_id)
            new = after.get(task_id)
            if old is None:
                kind, summary, requirement = (
                    "added",
                    f"Add {new.production_method} task.",
                    new.requirement_item_id,
                )
            elif new is None:
                kind, summary, requirement = (
                    "removed",
                    f"Remove {old.production_method} task.",
                    old.requirement_item_id,
                )
            elif old == new:
                continue
            else:
                kind, summary, requirement = (
                    "changed",
                    f"Revise {new.production_method} task.",
                    new.requirement_item_id,
                )
            changes.append(
                MaterialProductionChange(
                    change_id=self.id_factory("production_change"),
                    change_type=kind,
                    task_id=task_id,
                    requirement_item_id=requirement,
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
            raise CreationPlanningError(
                "Production-plan revision contains no changes"
            )
        warnings = tuple(
            task.limitation
            for task in plan.tasks
            if task.limitation is not None
        )
        values = {
            "review_id": self.id_factory("production_review"),
            "production_plan_id": plan.production_plan_id,
            "plan_version": plan.plan_version,
            "plan_digest": plan.digest(),
            "material_confirmation_ref": plan.material_confirmation_ref,
            "capability_registry_ref": plan.capability_registry_ref,
            "previous_plan_digest": (
                previous[-1].plan.digest() if previous else None
            ),
            "changes": tuple(changes),
            "warnings": warnings,
            "created_at": self.clock(),
        }
        shell = MaterialProductionReview.model_construct(
            schema_name="vistora.material-production-review",
            schema_version="1.0.0",
            review_digest="sha256:" + ("0" * 64),
            **values,
        )
        review = MaterialProductionReview(
            **values,
            review_digest=digest_json(
                shell.model_dump(mode="json", exclude={"review_digest"})
            ),
        )
        return MaterialProductionProposal(
            proposal_id=self.id_factory("production_proposal"),
            plan=plan,
            review=review,
            created_at=self.clock(),
        )

    def _report(
        self,
        request,
        *,
        status,
        message,
        proposal=None,
        error_code=None,
    ):
        return CreationPlanningReport(
            report_id=self.id_factory("creation_report"),
            request_id=request.request_id,
            status=status,
            message=message,
            proposal=proposal,
            error_code=error_code,
            recorded_at=self.clock(),
        )
