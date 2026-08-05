"""Frozen contracts for accepted AI artifact timeline-fillback compilation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from contracts import DirectorPlan
from director import digest_json
from effect_workflow import EffectExecutionReport
from plan_review import PlanDiffRequest

from effect_workflow.models import Digest, EffectModel, StableId


class EffectArtifactAcceptance(EffectModel):
    schema_name: Literal["vistora.effect-artifact-acceptance"] = (
        "vistora.effect-artifact-acceptance"
    )
    acceptance_id: StableId
    execution_request_id: StableId
    execution_report_digest: Digest
    task_id: StableId
    capability_id: StableId
    artifact_id: StableId
    artifact_digest: Digest
    output_role: Literal["video_clip", "transparent_layer", "effect_layer"]
    material_id: str = Field(pattern=r"^source_[0-9a-f]{16}$")
    catalog_entry_digest: Digest
    alpha_channel_verified: bool = False
    decision: Literal["accepted"] = "accepted"
    accepted_by: StableId
    accepted_at: AwareDatetime
    acceptance_digest: Digest

    @classmethod
    def create(
        cls,
        *,
        acceptance_id,
        report: EffectExecutionReport,
        task_id,
        catalog_entry,
        accepted_by,
        accepted_at,
        alpha_channel_verified=False,
    ):
        matches = [item for item in report.tasks if item.task_id == task_id]
        if len(matches) != 1 or matches[0].status != "ready_for_review":
            raise ValueError("Effect artifact is not ready for human acceptance")
        task = matches[0]
        artifact = task.artifact
        assert artifact is not None
        if (
            catalog_entry.artifact_sha256 != artifact.content_digest
            or catalog_entry.production_task_id != task.task_id
        ):
            raise ValueError("Effect artifact and catalog entry are not exact")
        values = {
            "acceptance_id": acceptance_id,
            "execution_request_id": report.execution_request_id,
            "execution_report_digest": digest_json(report.model_dump(mode="json")),
            "task_id": task.task_id,
            "capability_id": task.capability_id,
            "artifact_id": artifact.artifact_id,
            "artifact_digest": artifact.content_digest,
            "output_role": artifact.output_role,
            "material_id": catalog_entry.material_id,
            "catalog_entry_digest": digest_json(catalog_entry.model_dump(mode="json")),
            "alpha_channel_verified": alpha_channel_verified,
            "accepted_by": accepted_by,
            "accepted_at": accepted_at,
        }
        shell = cls.model_construct(
            **values,
            schema_name="vistora.effect-artifact-acceptance",
            schema_version="1.0.0",
            decision="accepted",
            acceptance_digest="sha256:" + "0" * 64,
        )
        return cls(
            **values,
            acceptance_digest=digest_json(
                shell.model_dump(mode="json", exclude={"acceptance_digest"})
            ),
        )

    @model_validator(mode="after")
    def digest_is_exact(self):
        payload = self.model_dump(mode="json", exclude={"acceptance_digest"})
        if self.acceptance_digest != digest_json(payload):
            raise ValueError("Effect artifact acceptance digest mismatched")
        return self


class EffectFillbackPlacement(EffectModel):
    schema_name: Literal["vistora.effect-fillback-placement"] = (
        "vistora.effect-fillback-placement"
    )
    placement_id: StableId
    acceptance_id: StableId
    layer_kind: Literal["standard_clip", "transparent_layer", "effect_layer"]
    track_id: StableId
    clip_id: StableId
    timeline_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, le=86400, allow_inf_nan=False)
    mode: Literal["insert", "overwrite"] = "insert"


class EffectFillbackBundle(EffectModel):
    schema_name: Literal["vistora.effect-fillback-bundle"] = (
        "vistora.effect-fillback-bundle"
    )
    bundle_id: StableId
    acceptance: EffectArtifactAcceptance
    placement: EffectFillbackPlacement
    director_plan: DirectorPlan
    review_request: PlanDiffRequest
    compilation_digest: Digest

    @model_validator(mode="after")
    def exact(self):
        if self.placement.acceptance_id != self.acceptance.acceptance_id:
            raise ValueError("Effect fillback placement crosses acceptance")
        if self.review_request.director_plan != self.director_plan:
            raise ValueError("Effect fillback review crosses Director plan")
        payload = self.model_dump(mode="json", exclude={"compilation_digest"})
        if self.compilation_digest != digest_json(payload):
            raise ValueError("Effect fillback compilation digest mismatched")
        return self
