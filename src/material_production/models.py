"""Versioned contracts for material production, validation, and cataloging."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from creation_planning import (
    ConfirmedMaterialProductionPlan,
    MaterialProductionTask,
)
from director import digest_json


MATERIAL_PRODUCTION_VERSION = "1.0.0"
Version = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GENESIS_DIGEST = "sha256:" + ("0" * 64)


class ProductionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: Version = MATERIAL_PRODUCTION_VERSION


class AdapterCapability(ProductionModel):
    schema_name: Literal["vistora.material-production.adapter-capability"] = (
        "vistora.material-production.adapter-capability"
    )
    adapter_id: StableId
    adapter_version: str = Field(min_length=1)
    capability_ids: tuple[StableId, ...] = Field(min_length=1)
    configured: bool
    execution_kind: Literal[
        "manual_import",
        "local_deterministic_test",
        "external_provider",
        "human_request",
    ]
    max_concurrency: int = Field(ge=1, le=64)
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    limitation: str | None = Field(default=None, min_length=1)
    input_schema_digest: Digest
    result_schema_digest: Digest

    @model_validator(mode="after")
    def capability_is_truthful(self) -> AdapterCapability:
        if self.configured and self.limitation is not None:
            raise ValueError("Configured adapter cannot carry a limitation")
        if not self.configured and self.limitation is None:
            raise ValueError("Unconfigured adapter requires a limitation")
        if (
            tuple(sorted(self.capability_ids)) != self.capability_ids
            or len(self.capability_ids) != len(set(self.capability_ids))
        ):
            raise ValueError("Adapter capabilities must be unique and ordered")
        return self


class AdapterRegistryReference(ProductionModel):
    schema_name: Literal["vistora.material-production.adapter-registry"] = (
        "vistora.material-production.adapter-registry"
    )
    registry_id: StableId
    registry_revision: int = Field(ge=1)
    adapters: tuple[AdapterCapability, ...] = Field(min_length=1)
    registry_digest: Digest

    @classmethod
    def create(
        cls,
        *,
        registry_id: str,
        registry_revision: int,
        adapters: tuple[AdapterCapability, ...],
    ) -> AdapterRegistryReference:
        ordered = tuple(sorted(adapters, key=lambda item: item.adapter_id))
        return cls(
            registry_id=registry_id,
            registry_revision=registry_revision,
            adapters=ordered,
            registry_digest=digest_json(
                [item.model_dump(mode="json") for item in ordered]
            ),
        )

    @model_validator(mode="after")
    def registry_is_exact(self) -> AdapterRegistryReference:
        ids = [item.adapter_id for item in self.adapters]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("Adapter IDs must be unique and ordered")
        if self.registry_digest != digest_json(
            [item.model_dump(mode="json") for item in self.adapters]
        ):
            raise ValueError("Adapter registry digest mismatched")
        return self


class ProductionPlanConfirmationReference(ProductionModel):
    schema_name: Literal[
        "vistora.material-production.plan-confirmation-reference"
    ] = "vistora.material-production.plan-confirmation-reference"
    planning_ledger_revision: int = Field(ge=1)
    production_confirmation_id: StableId
    production_plan_id: StableId
    production_plan_version: int = Field(ge=1)
    production_plan_digest: Digest
    production_review_digest: Digest
    requirements_confirmation_id: StableId
    requirements_plan_digest: Digest
    capability_registry_digest: Digest

    @classmethod
    def from_confirmed(
        cls,
        confirmed: ConfirmedMaterialProductionPlan,
    ) -> ProductionPlanConfirmationReference:
        proposal = confirmed.proposal
        material_ref = proposal.plan.material_confirmation_ref
        return cls(
            planning_ledger_revision=confirmed.ledger_revision,
            production_confirmation_id=(
                confirmed.confirmation.confirmation_id
            ),
            production_plan_id=proposal.plan.production_plan_id,
            production_plan_version=proposal.plan.plan_version,
            production_plan_digest=proposal.plan.digest(),
            production_review_digest=proposal.review.review_digest,
            requirements_confirmation_id=material_ref.confirmation_id,
            requirements_plan_digest=(
                material_ref.requirements_plan_digest
            ),
            capability_registry_digest=(
                proposal.plan.capability_registry_ref.registry_digest
            ),
        )


class ProductionTaskInput(ProductionModel):
    task_id: StableId
    input_token: StableId


class MaterialProductionRunRequest(ProductionModel):
    schema_name: Literal["vistora.material-production.run-request"] = (
        "vistora.material-production.run-request"
    )
    request_id: StableId
    plan_confirmation_ref: ProductionPlanConfirmationReference
    adapter_registry_ref: AdapterRegistryReference
    task_inputs: tuple[ProductionTaskInput, ...] = ()
    requested_by: StableId
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def inputs_are_unique(self) -> MaterialProductionRunRequest:
        task_ids = [item.task_id for item in self.task_inputs]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("Production task inputs must be unique")
        return self

    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class ProductionJobRequest(ProductionModel):
    schema_name: Literal["vistora.material-production.job-request"] = (
        "vistora.material-production.job-request"
    )
    job_id: StableId
    run_id: StableId
    task_id: StableId
    requirement_item_id: StableId
    adapter_id: StableId
    capability_id: StableId
    task_spec: MaterialProductionTask | None = None
    attempt: int = Field(ge=1, le=20)
    idempotency_key: StableId
    input_token: StableId | None = None
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def task_linkage_is_exact(self) -> ProductionJobRequest:
        if self.task_spec is None:
            return self
        if (
            self.task_spec.task_id != self.task_id
            or self.task_spec.requirement_item_id != self.requirement_item_id
            or self.capability_id not in self.task_spec.capability_ids
        ):
            raise ValueError("Production task specification crosses job linkage")
        return self


class ArtifactCandidate(ProductionModel):
    schema_name: Literal["vistora.material-production.artifact-candidate"] = (
        "vistora.material-production.artifact-candidate"
    )
    artifact_id: StableId
    job_id: StableId
    task_id: StableId
    requirement_item_id: StableId
    staging_relative_path: str = Field(min_length=1)
    claimed_mime_type: str = Field(min_length=3)

    @model_validator(mode="after")
    def relative_path_only(self) -> ArtifactCandidate:
        value = self.staging_relative_path.replace("\\", "/")
        if (
            value.startswith("/")
            or ":/" in value
            or value == ".."
            or value.startswith("../")
            or "/../" in value
        ):
            raise ValueError("Artifact candidate path escapes staging")
        return self


class AdapterJobUpdate(ProductionModel):
    schema_name: Literal["vistora.material-production.adapter-job-update"] = (
        "vistora.material-production.adapter-job-update"
    )
    job_id: StableId
    adapter_id: StableId
    provider_opaque_ref: StableId
    status: Literal[
        "submitted",
        "running",
        "needs_input",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
        "rate_limited",
        "recovery_required",
    ]
    progress: float = Field(ge=0, le=1)
    cost_status: Literal["known", "unknown"] = "unknown"
    cost_value: float | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(default=None, min_length=3)
    retry_after_seconds: float | None = Field(default=None, ge=0)
    artifacts: tuple[ArtifactCandidate, ...] = ()
    error_code: StableId | None = None
    message: str = Field(min_length=1)
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def update_is_truthful(self) -> AdapterJobUpdate:
        if self.cost_status == "known" and (
            self.cost_value is None or self.cost_currency is None
        ):
            raise ValueError("Known job cost requires value and currency")
        if self.cost_status == "unknown" and (
            self.cost_value is not None or self.cost_currency is not None
        ):
            raise ValueError("Unknown job cost cannot invent a value")
        if self.status == "succeeded" and not self.artifacts:
            raise ValueError("Succeeded job requires an artifact")
        if self.status != "succeeded" and self.artifacts:
            raise ValueError("Only succeeded jobs can return artifacts")
        error_states = {
            "failed",
            "timed_out",
            "rate_limited",
            "recovery_required",
        }
        if self.status in error_states and self.error_code is None:
            raise ValueError("Failed job state requires an error code")
        if self.status not in error_states and self.error_code is not None:
            raise ValueError("Non-failure job cannot carry an error code")
        if (
            self.status == "rate_limited"
            and self.retry_after_seconds is None
        ):
            raise ValueError("Rate-limited job requires retry timing")
        if (
            self.status != "rate_limited"
            and self.retry_after_seconds is not None
        ):
            raise ValueError("Only rate-limited jobs carry retry timing")
        if self.status == "succeeded" and self.progress != 1:
            raise ValueError("Succeeded job must report complete progress")
        return self


class ArtifactValidation(ProductionModel):
    schema_name: Literal["vistora.material-production.artifact-validation"] = (
        "vistora.material-production.artifact-validation"
    )
    validation_id: StableId
    artifact_id: StableId
    run_id: StableId
    job_id: StableId
    task_id: StableId
    requirement_item_id: StableId
    passed: bool
    sha256: Digest | None = None
    size_bytes: int | None = Field(default=None, gt=0)
    mime_type: str | None = Field(default=None, min_length=3)
    container: str | None = Field(default=None, min_length=1)
    video_codec: str | None = Field(default=None, min_length=1)
    audio_codec: str | None = Field(default=None, min_length=1)
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    issues: tuple[str, ...] = ()
    validated_at: AwareDatetime

    @model_validator(mode="after")
    def result_shape(self) -> ArtifactValidation:
        if self.passed and (
            self.sha256 is None
            or self.size_bytes is None
            or self.mime_type is None
            or self.issues
        ):
            raise ValueError("Passed artifact needs metadata and no issues")
        if not self.passed and not self.issues:
            raise ValueError("Failed artifact validation needs issues")
        if (self.width is None) != (self.height is None):
            raise ValueError("Artifact dimensions must be paired")
        return self


class ArtifactDecision(ProductionModel):
    schema_name: Literal["vistora.material-production.artifact-decision"] = (
        "vistora.material-production.artifact-decision"
    )
    decision_id: StableId
    artifact_id: StableId
    validation_id: StableId
    decision: Literal["accepted", "rejected"]
    decided_by: StableId
    reason: str = Field(min_length=1)
    decided_at: AwareDatetime


class MaterialDerivative(ProductionModel):
    schema_name: Literal["vistora.material-catalog.derivative"] = (
        "vistora.material-catalog.derivative"
    )
    derivative_id: StableId
    role: Literal["proxy", "normalized"]
    managed_relative_path: str = Field(min_length=1)
    sha256: Digest
    size_bytes: int = Field(gt=0)
    mime_type: str = Field(min_length=3)
    container: str | None = Field(default=None, min_length=1)
    video_codec: str | None = Field(default=None, min_length=1)
    audio_codec: str | None = Field(default=None, min_length=1)
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def derivative_is_safe(self):
        value = self.managed_relative_path.replace("\\", "/")
        if value.startswith("/") or ":/" in value or ".." in value.split("/"):
            raise ValueError("Derivative path must remain managed and relative")
        if (self.width is None) != (self.height is None):
            raise ValueError("Derivative dimensions must be paired")
        return self


class MaterialAnalysisSummary(ProductionModel):
    schema_name: Literal["vistora.material-catalog.analysis"] = (
        "vistora.material-catalog.analysis"
    )
    analysis_id: StableId
    source_sha256: Digest
    media_kind: Literal["video", "audio", "image"]
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    video_codec: str | None = Field(default=None, min_length=1)
    audio_codec: str | None = Field(default=None, min_length=1)
    audio_sample_rate: int | None = Field(default=None, gt=0)
    audio_channels: int | None = Field(default=None, gt=0)
    orientation: Literal["landscape", "portrait", "square", "not_applicable"]
    technical_digest: Digest

    @model_validator(mode="after")
    def analysis_shape(self):
        if (self.width is None) != (self.height is None):
            raise ValueError("Analysis dimensions must be paired")
        expected = "not_applicable"
        if self.width is not None:
            expected = (
                "square"
                if self.width == self.height
                else "landscape" if self.width > self.height else "portrait"
            )
        if self.orientation != expected:
            raise ValueError("Material orientation does not match dimensions")
        payload = self.model_dump(mode="json", exclude={"technical_digest"})
        if self.technical_digest != digest_json(payload):
            raise ValueError("Material analysis digest mismatched")
        return self


class MaterialTag(ProductionModel):
    schema_name: Literal["vistora.material-catalog.tag"] = (
        "vistora.material-catalog.tag"
    )
    tag_id: StableId
    namespace: Literal["technical", "workflow", "user"]
    name: StableId
    value: str = Field(min_length=1, max_length=256)
    source: Literal["deterministic_analysis", "production_plan", "user"]


class MaterialQualityCheck(ProductionModel):
    check_id: StableId
    status: Literal["passed", "warning", "failed"]
    message: str = Field(min_length=1)


class MaterialQualityReport(ProductionModel):
    schema_name: Literal["vistora.material-catalog.quality-report"] = (
        "vistora.material-catalog.quality-report"
    )
    report_id: StableId
    source_sha256: Digest
    overall_status: Literal["passed", "warning", "failed"]
    full_decode_passed: bool
    checks: tuple[MaterialQualityCheck, ...] = Field(min_length=1)
    report_digest: Digest
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def report_is_exact(self):
        ids = [item.check_id for item in self.checks]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("Material quality checks must be unique and ordered")
        statuses = {item.status for item in self.checks}
        expected = (
            "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
        )
        if self.overall_status != expected:
            raise ValueError("Material quality status mismatched")
        if not self.full_decode_passed and self.overall_status != "failed":
            raise ValueError("Failed full decode must fail material quality")
        payload = self.model_dump(mode="json", exclude={"report_digest"})
        if self.report_digest != digest_json(payload):
            raise ValueError("Material quality report digest mismatched")
        return self


class MaterialCatalogEntry(ProductionModel):
    schema_name: Literal["vistora.material-catalog.entry"] = (
        "vistora.material-catalog.entry"
    )
    material_id: Annotated[
        str,
        Field(pattern=r"^source_[0-9a-f]{16}$"),
    ]
    display_name: str = Field(min_length=1)
    media_kind: Literal["video", "audio", "image"]
    managed_relative_path: str = Field(min_length=1)
    artifact_sha256: Digest
    size_bytes: int = Field(gt=0)
    mime_type: str = Field(min_length=3)
    container: str | None = Field(default=None, min_length=1)
    video_codec: str | None = Field(default=None, min_length=1)
    audio_codec: str | None = Field(default=None, min_length=1)
    duration_seconds: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    has_audio: bool | None = None
    requirements_plan_id: StableId
    requirement_item_id: StableId
    production_plan_id: StableId
    production_task_id: StableId
    production_run_id: StableId
    production_job_id: StableId
    adapter_id: StableId
    origin_kind: Literal[
        "generated",
        "manual_import",
        "captured",
        "library",
    ]
    license_status: Literal[
        "user_asserted",
        "provider_terms",
        "unknown",
    ]
    usage_restrictions: tuple[str, ...] = ()
    cost_status: Literal["known", "unknown"]
    cost_value: float | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(default=None, min_length=3)
    quality_validation_id: StableId
    accepted_decision_id: StableId
    registered_at: AwareDatetime
    derivatives: tuple[MaterialDerivative, ...] = ()
    analysis: MaterialAnalysisSummary | None = None
    tags: tuple[MaterialTag, ...] = ()
    quality_report: MaterialQualityReport | None = None

    @model_validator(mode="after")
    def entry_is_safe(self) -> MaterialCatalogEntry:
        value = self.managed_relative_path.replace("\\", "/")
        if (
            value.startswith("/")
            or ":/" in value
            or ".." in value.split("/")
        ):
            raise ValueError("Catalog path must remain managed and relative")
        if self.cost_status == "known" and (
            self.cost_value is None or self.cost_currency is None
        ):
            raise ValueError("Known catalog cost requires value and currency")
        if self.cost_status == "unknown" and (
            self.cost_value is not None or self.cost_currency is not None
        ):
            raise ValueError("Unknown catalog cost cannot invent a value")
        enriched = bool(
            self.derivatives or self.analysis or self.tags or self.quality_report
        )
        if enriched and (
            not self.derivatives
            or self.analysis is None
            or not self.tags
            or self.quality_report is None
        ):
            raise ValueError("Enriched catalog entry requires complete ingest metadata")
        if enriched:
            roles = [item.role for item in self.derivatives]
            if roles != sorted(roles) or len(roles) != len(set(roles)):
                raise ValueError("Material derivatives must have unique ordered roles")
            if self.analysis.source_sha256 != self.artifact_sha256:
                raise ValueError("Material analysis crosses artifact identity")
            if self.quality_report.source_sha256 != self.artifact_sha256:
                raise ValueError("Material quality crosses artifact identity")
            if self.quality_report.overall_status == "failed":
                raise ValueError("Failed material quality cannot enter the catalog")
            tag_keys = [(item.namespace, item.name, item.value) for item in self.tags]
            if tag_keys != sorted(tag_keys) or len(tag_keys) != len(set(tag_keys)):
                raise ValueError("Material tags must be unique and ordered")
        return self

    @property
    def source_uri(self) -> str:
        return f"material://{self.material_id}"


class MaterialCatalogDocument(ProductionModel):
    schema_name: Literal["vistora.material-catalog"] = (
        "vistora.material-catalog"
    )
    project_id: StableId
    revision: int = Field(ge=0)
    entries: tuple[MaterialCatalogEntry, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, *, project_id: str) -> MaterialCatalogDocument:
        return cls(
            project_id=project_id,
            revision=0,
            entries=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def catalog_is_exact(self) -> MaterialCatalogDocument:
        if self.revision != len(self.entries):
            raise ValueError("Catalog revision is invalid")
        ids = [entry.material_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("Catalog material ID is duplicated")
        if self.integrity_digest != digest_json(
            [entry.model_dump(mode="json") for entry in self.entries]
        ):
            raise ValueError("Catalog integrity digest mismatched")
        return self


class ProductionRunState(ProductionModel):
    schema_name: Literal["vistora.material-production.run-state"] = (
        "vistora.material-production.run-state"
    )
    run_id: StableId
    request: MaterialProductionRunRequest
    status: Literal[
        "pending",
        "running",
        "awaiting_review",
        "succeeded",
        "partial",
        "failed",
        "cancelled",
        "recovery_required",
    ]
    message: str = Field(min_length=1)
    recorded_at: AwareDatetime


class ProductionJobState(ProductionModel):
    schema_name: Literal["vistora.material-production.job-state"] = (
        "vistora.material-production.job-state"
    )
    request: ProductionJobRequest
    update: AdapterJobUpdate

    @model_validator(mode="after")
    def request_result_linkage_is_exact(self) -> ProductionJobState:
        if (
            self.update.job_id != self.request.job_id
            or self.update.adapter_id != self.request.adapter_id
        ):
            raise ValueError("Production job update crosses request linkage")
        return self


class ProductionValidationState(ProductionModel):
    schema_name: Literal["vistora.material-production.validation-state"] = (
        "vistora.material-production.validation-state"
    )
    validation: ArtifactValidation


class ProductionDecisionState(ProductionModel):
    schema_name: Literal["vistora.material-production.decision-state"] = (
        "vistora.material-production.decision-state"
    )
    decision: ArtifactDecision


class ProductionCatalogState(ProductionModel):
    schema_name: Literal["vistora.material-production.catalog-state"] = (
        "vistora.material-production.catalog-state"
    )
    entry: MaterialCatalogEntry


ProductionRecord = (
    ProductionRunState
    | ProductionJobState
    | ProductionValidationState
    | ProductionDecisionState
    | ProductionCatalogState
)


class MaterialProductionEvent(ProductionModel):
    schema_name: Literal["vistora.material-production.event"] = (
        "vistora.material-production.event"
    )
    sequence: int = Field(ge=1)
    event_id: StableId
    record: ProductionRecord
    previous_event_digest: Digest
    event_digest: Digest

    @model_validator(mode="after")
    def event_digest_is_exact(self) -> MaterialProductionEvent:
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Material-production event digest mismatched")
        return self


class MaterialProductionLedger(ProductionModel):
    schema_name: Literal["vistora.material-production.ledger"] = (
        "vistora.material-production.ledger"
    )
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[MaterialProductionEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, *, project_id: str) -> MaterialProductionLedger:
        return cls(
            project_id=project_id,
            revision=0,
            events=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def ledger_is_exact(self) -> MaterialProductionLedger:
        if self.revision != len(self.events):
            raise ValueError("Material-production revision is invalid")
        previous = GENESIS_DIGEST
        request_ids: dict[str, str] = {}
        for index, event in enumerate(self.events, start=1):
            if (
                event.sequence != index
                or event.previous_event_digest != previous
            ):
                raise ValueError("Material-production ledger chain is broken")
            if isinstance(event.record, ProductionRunState):
                request = event.record.request
                known = request_ids.get(request.request_id)
                if known is None:
                    request_ids[request.request_id] = request.digest()
                elif known != request.digest():
                    raise ValueError(
                        "Production request ID was reused with new content"
                    )
            previous = event.event_digest
        if self.integrity_digest != digest_json(
            [event.event_digest for event in self.events]
        ):
            raise ValueError("Material-production integrity digest mismatched")
        return self


class MaterialProductionView(ProductionModel):
    schema_name: Literal["vistora.material-production.history"] = (
        "vistora.material-production.history"
    )
    project_id: StableId
    ledger_revision: int = Field(ge=0)
    catalog_revision: int = Field(ge=0)
    state: Literal[
        "empty",
        "running",
        "awaiting_review",
        "succeeded",
        "partial",
        "failed",
        "cancelled",
        "recovery_required",
    ]
    runs: tuple[dict[str, Any], ...] = ()
    jobs: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()
    catalog: tuple[dict[str, Any], ...] = ()
    capabilities: tuple[dict[str, Any], ...] = ()
    limitations: tuple[str, ...] = (
        "Online provider adapters are not configured.",
        "Only accepted validated artifacts become Director-observable material.",
        "Catalog acceptance never adds media to the timeline.",
    )
