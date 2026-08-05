"""Read-only compiler from accepted effect artifacts to normal review input."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from contracts import (
    DirectorOperation,
    DirectorPlan,
    SourceEvidenceReference,
    WholeMaterialLocator,
)
from director import digest_json
from effect_workflow import EffectExecutionReport
from material_production import MaterialCatalogStore
from plan_review import (
    PlanDiffRequest,
    PreviewMaterialFact,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService

from .models import EffectArtifactAcceptance, EffectFillbackBundle, EffectFillbackPlacement


class EffectFillbackError(ValueError):
    pass


class EffectFillbackCompiler:
    """Produces a reviewable Director plan; it never confirms or dispatches it."""

    def __init__(
        self,
        *,
        catalog: MaterialCatalogStore,
        registry,
        snapshot_provider: Callable = TimelineSnapshotService.snapshot_current,
    ):
        self.catalog = catalog
        self.registry = registry
        self.snapshot_provider = snapshot_provider

    def compile(
        self,
        *,
        bundle_id: str,
        plan_id: str,
        plan_version: int,
        proposal_execution_id: str,
        review_request_id: str,
        acceptance: EffectArtifactAcceptance,
        placement: EffectFillbackPlacement,
        execution_report: EffectExecutionReport,
        objective: str,
        rationale: str,
        expected_effect: str,
        created_at: datetime,
    ) -> EffectFillbackBundle:
        snapshot = self.snapshot_provider()
        if acceptance.execution_request_id != execution_report.execution_request_id:
            raise EffectFillbackError("Effect acceptance crosses execution request")
        if acceptance.execution_report_digest != digest_json(
            execution_report.model_dump(mode="json")
        ):
            raise EffectFillbackError("Effect acceptance report is stale or tampered")
        task_reports = [
            item for item in execution_report.tasks
            if item.task_id == acceptance.task_id
        ]
        if len(task_reports) != 1 or task_reports[0].artifact is None:
            raise EffectFillbackError("Accepted effect task is unavailable")
        artifact = task_reports[0].artifact
        if (
            artifact.artifact_id != acceptance.artifact_id
            or artifact.content_digest != acceptance.artifact_digest
            or artifact.output_role != acceptance.output_role
        ):
            raise EffectFillbackError("Accepted effect artifact binding drifted")
        catalog = self.catalog.load(project_id=snapshot.project_id)
        entries = [item for item in catalog.entries if item.material_id == acceptance.material_id]
        if len(entries) != 1:
            raise EffectFillbackError("Accepted effect material is not cataloged")
        entry = entries[0]
        if (
            digest_json(entry.model_dump(mode="json")) != acceptance.catalog_entry_digest
            or entry.artifact_sha256 != acceptance.artifact_digest
            or entry.production_task_id != acceptance.task_id
        ):
            raise EffectFillbackError("Accepted effect catalog entry drifted")
        tracks = [item for item in snapshot.tracks if item.track_id == placement.track_id]
        if len(tracks) != 1:
            raise EffectFillbackError("Effect fillback target track is unavailable")
        track = tracks[0]
        if track.locked:
            raise EffectFillbackError("Effect fillback target track is locked")
        if any(
            placement.clip_id == clip.clip_id
            for candidate in snapshot.tracks for clip in candidate.clips
        ):
            raise EffectFillbackError("Effect fillback clip ID already exists")
        self._validate_placement(acceptance, placement, entry, track)
        evidence = SourceEvidenceReference(
            evidence_id=f"evidence_effect_{acceptance.acceptance_id}",
            material_id=entry.material_id,
            locator=WholeMaterialLocator(),
            analysis_fact_id=acceptance.acceptance_id,
            analysis_fact_digest=acceptance.acceptance_digest,
            description="Human-accepted AI packaging artifact in the validated material catalog.",
        )
        tool_name, arguments = self._operation(entry, placement, track)
        operation = DirectorOperation(
            operation_id=placement.placement_id,
            tool_name=tool_name,
            arguments=arguments,
            rationale=rationale,
            expected_effect=expected_effect,
            evidence_ids=(evidence.evidence_id,),
        )
        plan = DirectorPlan(
            plan_id=plan_id,
            plan_version=plan_version,
            created_at=created_at,
            objective=objective,
            requirements=(
                "Use only the exact human-accepted catalog artifact.",
                "Require independent workflow confirmation before fillback.",
            ),
            creative_direction={
                "effect_acceptance_id": acceptance.acceptance_id,
                "effect_acceptance_digest": acceptance.acceptance_digest,
                "effect_execution_request_id": acceptance.execution_request_id,
                "effect_task_id": acceptance.task_id,
                "effect_capability_id": acceptance.capability_id,
                "fillback_layer_kind": placement.layer_kind,
            },
            source_evidence=(evidence,),
            operations=(operation,),
            outputs=("One standard unified-timeline entity after confirmation.",),
            risks=("External effect artifacts are not deleted by timeline rollback.",),
        )
        proposed = ProposedEditingExecutionPlan.from_director_plan(
            proposal_execution_id=proposal_execution_id,
            project_id=snapshot.project_id,
            director_plan=plan,
        )
        request = PlanDiffRequest(
            request_id=review_request_id,
            snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
            director_plan=plan,
            proposed_execution=proposed,
            registry_ref=RegistrySchemaReference.from_registry(self.registry),
            material_facts=(self._material_fact(entry),),
        )
        values = {
            "bundle_id": bundle_id,
            "acceptance": acceptance,
            "placement": placement,
            "director_plan": plan,
            "review_request": request,
        }
        shell = EffectFillbackBundle.model_construct(
            **values,
            schema_name="vistora.effect-fillback-bundle",
            schema_version="1.0.0",
            compilation_digest="sha256:" + "0" * 64,
        )
        return EffectFillbackBundle(
            **values,
            compilation_digest=digest_json(
                shell.model_dump(mode="json", exclude={"compilation_digest"})
            ),
        )

    @staticmethod
    def _validate_placement(acceptance, placement, entry, track):
        if placement.acceptance_id != acceptance.acceptance_id:
            raise EffectFillbackError("Effect placement crosses acceptance")
        if placement.layer_kind == "standard_clip":
            if entry.media_kind not in {"video", "audio"} or track.kind != entry.media_kind:
                raise EffectFillbackError("Standard effect clip track/media kind mismatched")
        elif placement.layer_kind == "transparent_layer":
            if entry.media_kind != "image" or track.kind != "video":
                raise EffectFillbackError("Transparent effects require an image on a video track")
            if not acceptance.alpha_channel_verified:
                raise EffectFillbackError("Transparent effect alpha was not validated")
            if acceptance.output_role != "transparent_layer":
                raise EffectFillbackError("Transparent placement crosses requested output role")
        else:
            if entry.media_kind not in {"video", "image"} or track.kind != "video":
                raise EffectFillbackError("Effect layers require visual media on a video track")
            if track.role not in {"auxiliary", "effects", "graphics", "overlay"}:
                raise EffectFillbackError("Effect layers require an explicit non-primary layer track")
            if acceptance.output_role != "effect_layer":
                raise EffectFillbackError("Effect placement crosses requested output role")
        if entry.duration_seconds is not None and placement.duration_seconds > entry.duration_seconds + 1e-6:
            raise EffectFillbackError("Effect fillback duration exceeds catalog media")

    @staticmethod
    def _operation(entry, placement, track):
        source_uri = entry.source_uri
        if entry.media_kind == "image":
            return "VideoInsertGraphicSkill", {
                "track_id": track.track_id,
                "clip_id": placement.clip_id,
                "source_path": source_uri,
                "graphic_kind": "sticker" if placement.layer_kind == "transparent_layer" else "image",
                "timeline_start": placement.timeline_start_seconds,
                "duration_seconds": placement.duration_seconds,
                "mode": placement.mode,
            }
        return "VideoInsertOverwriteClipSkill", {
            "track_id": track.track_id,
            "source_path": source_uri,
            "timeline_start": placement.timeline_start_seconds,
            "mode": placement.mode,
            "clip_id": placement.clip_id,
            "trim_in": 0.0,
            "trim_out": placement.duration_seconds,
            "speed_factor": 1.0,
            "volume": 1.0,
            "keep_audio": bool(entry.has_audio) if entry.media_kind == "video" else True,
            "rotate": 0,
            "edit_scope": "current_clip",
        }

    @staticmethod
    def _material_fact(entry):
        return PreviewMaterialFact(
            material_id=entry.material_id,
            media_kind=entry.media_kind,
            duration_seconds=entry.duration_seconds,
            has_audio=entry.has_audio,
            width=entry.width,
            height=entry.height,
        )
