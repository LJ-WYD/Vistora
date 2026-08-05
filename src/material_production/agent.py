"""Constrained production Agent over exact confirmed material plans.

The Agent does not plan, infer missing tasks, resolve paths, or invoke providers
directly.  It validates one immutable run request and delegates only to the
MaterialProductionOrchestrator application boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .models import MaterialProductionRunRequest
from .service import MaterialProductionError, MaterialProductionOrchestrator
from .store import MaterialProductionStoreError


MATERIAL_PRODUCTION_AGENT_VERSION = "1.0.0"
StableId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]


class MaterialProductionAgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Literal["1.0.0"] = MATERIAL_PRODUCTION_AGENT_VERSION


class MaterialProductionAgentRequest(MaterialProductionAgentModel):
    schema_name: Literal["vistora.material-production-agent.request"] = (
        "vistora.material-production-agent.request"
    )
    agent_request_id: StableId
    run_request: MaterialProductionRunRequest
    requested_at: AwareDatetime


class MaterialProductionAgentError(MaterialProductionAgentModel):
    code: Literal[
        "confirmation_rejected",
        "adapter_registry_stale",
        "production_integrity_failed",
        "production_execution_failed",
    ]
    message: str = Field(min_length=1)
    retryable: bool = False


class MaterialProductionAgentReport(MaterialProductionAgentModel):
    schema_name: Literal["vistora.material-production-agent.report"] = (
        "vistora.material-production-agent.report"
    )
    report_id: StableId
    agent_request_id: StableId
    production_request_id: StableId
    project_id: StableId
    disposition: Literal["rejected", "executed"]
    status: Literal[
        "rejected",
        "running",
        "awaiting_review",
        "succeeded",
        "partial",
        "failed",
        "cancelled",
        "recovery_required",
    ]
    run_id: StableId | None = None
    production_plan_id: StableId
    production_plan_version: int = Field(ge=1)
    production_plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    adapter_registry_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    message: str = Field(min_length=1)
    error: MaterialProductionAgentError | None = None
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def report_is_truthful(self):
        if self.disposition == "rejected":
            if self.status != "rejected" or self.run_id is not None or self.error is None:
                raise ValueError("Rejected production report cannot claim a run")
        elif self.status == "rejected" or self.run_id is None or self.error is not None:
            raise ValueError("Executed production report requires exact run linkage")
        return self


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class MaterialProductionAgent:
    """Executes only exact confirmed production requests; it has no creativity."""

    def __init__(
        self,
        orchestrator: MaterialProductionOrchestrator,
        *,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
    ) -> None:
        self._orchestrator = orchestrator
        self._clock = clock
        self._id_factory = id_factory

    def prepare_execution(
        self,
        *,
        agent_request_id: str,
        production_request_id: str,
        production_confirmation_id: str,
        requested_by: str,
    ) -> MaterialProductionAgentRequest:
        request = self._orchestrator.prepare_request(
            request_id=production_request_id,
            production_confirmation_id=production_confirmation_id,
            requested_by=requested_by,
        )
        return MaterialProductionAgentRequest(
            agent_request_id=agent_request_id,
            run_request=request,
            requested_at=self._clock(),
        )

    def execute(
        self,
        request: MaterialProductionAgentRequest,
    ) -> MaterialProductionAgentReport:
        run_request = request.run_request
        binding = run_request.plan_confirmation_ref
        try:
            run = self._orchestrator.start(run_request)
        except (MaterialProductionError, MaterialProductionStoreError, ValueError) as exc:
            message = str(exc) or "Material production was rejected."
            lowered = message.lower()
            if "registry changed" in lowered:
                code = "adapter_registry_stale"
            elif "corrupt" in lowered or "tamper" in lowered:
                code = "production_integrity_failed"
            elif "confirm" in lowered or "plan changed" in lowered:
                code = "confirmation_rejected"
            else:
                code = "production_execution_failed"
            return MaterialProductionAgentReport(
                report_id=self._id_factory("production_agent_report"),
                agent_request_id=request.agent_request_id,
                production_request_id=run_request.request_id,
                project_id=self._orchestrator.project_id,
                disposition="rejected",
                status="rejected",
                production_plan_id=binding.production_plan_id,
                production_plan_version=binding.production_plan_version,
                production_plan_digest=binding.production_plan_digest,
                adapter_registry_digest=run_request.adapter_registry_ref.registry_digest,
                message="Material production was rejected before provider dispatch.",
                error=MaterialProductionAgentError(
                    code=code,
                    message=message,
                    retryable=code == "adapter_registry_stale",
                ),
                finished_at=self._clock(),
            )
        return MaterialProductionAgentReport(
            report_id=self._id_factory("production_agent_report"),
            agent_request_id=request.agent_request_id,
            production_request_id=run_request.request_id,
            project_id=self._orchestrator.project_id,
            disposition="executed",
            status=run["status"],
            run_id=run["run_id"],
            production_plan_id=binding.production_plan_id,
            production_plan_version=binding.production_plan_version,
            production_plan_digest=binding.production_plan_digest,
            adapter_registry_digest=run_request.adapter_registry_ref.registry_digest,
            message=run["message"],
            finished_at=self._clock(),
        )


__all__ = [
    "MATERIAL_PRODUCTION_AGENT_VERSION",
    "MaterialProductionAgent",
    "MaterialProductionAgentError",
    "MaterialProductionAgentReport",
    "MaterialProductionAgentRequest",
]
