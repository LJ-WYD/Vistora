"""Current-workspace factory for the local production product entry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent import DirectorAgent, EditingAgent
from creation_planning import (
    CapabilityRegistryReference,
    CapabilityRequirement,
    CreationPlanningAgent,
    CreationPlanningAdapter,
    CreationPlanningService,
    CreationPlanningStore,
    OpenAICompatibleCreationPlanningAdapter,
)
from contracts import SourceEvidenceReference, WholeMaterialLocator
from core import timeline_manager
from director import (
    DirectorContextService,
    DirectorMaterialFact,
    DirectorReasoningAdapter,
    DirectorStore,
    OpenAICompatibleDirectorAdapter,
)
from timeline_query import TimelineSnapshotService
from workflow import WorkflowApplicationService
from material_requirements import (
    MaterialRequirementsService,
    MaterialRequirementsStore,
)

from .service import ProductionEntryService
from .store import ProductEntryStore


DEFAULT_PRODUCT_SESSION_ID = "session_local_product"


def _material_facts(snapshot) -> tuple[DirectorMaterialFact, ...]:
    by_source: dict[str, dict[str, Any]] = {}
    for track in snapshot.tracks:
        for clip in track.clips:
            current = by_source.setdefault(
                clip.source.source_id,
                {
                    "display_name": clip.source.display_name,
                    "kind": "audio" if track.kind == "audio" else "video",
                    "duration": 0.0,
                    "has_audio": False,
                },
            )
            if track.kind == "video":
                current["kind"] = "video"
            current["duration"] = max(
                current["duration"],
                clip.trim_out_seconds,
            )
            current["has_audio"] = (
                current["has_audio"] or clip.keep_audio
            )
    facts = []
    for source_id, item in sorted(by_source.items()):
        suffix = source_id.removeprefix("source_")
        evidence = SourceEvidenceReference(
            evidence_id=f"evidence_observed_{suffix}",
            material_id=source_id,
            locator=WholeMaterialLocator(),
            description="Observed in the current detached timeline snapshot.",
        )
        video = item["kind"] == "video"
        facts.append(
            DirectorMaterialFact(
                material_id=source_id,
                media_kind=item["kind"],
                display_name=item["display_name"],
                duration_seconds=max(float(item["duration"]), 0.001),
                width=snapshot.width if video else None,
                height=snapshot.height if video else None,
                has_audio=item["has_audio"],
                observation_status="observed",
                evidence=(evidence,),
            )
        )
    return tuple(facts)


def build_current_product_entry(
    registry: Mapping[str, Any],
    *,
    adapter: DirectorReasoningAdapter | None = None,
    creation_adapter: CreationPlanningAdapter | None = None,
    session_id: str = DEFAULT_PRODUCT_SESSION_ID,
) -> ProductionEntryService:
    """Compose existing production boundaries without merging responsibilities."""

    initial = TimelineSnapshotService.snapshot_current()
    director_store = DirectorStore.for_project_file(
        timeline_manager.PROJECT_FILE,
        session_id=session_id,
    )

    def context_provider():
        snapshot = TimelineSnapshotService.snapshot_current()
        return (
            DirectorContextService.build(
                snapshot,
                registry,
                materials=_material_facts(snapshot),
            ),
            snapshot,
        )

    director = DirectorAgent(
        adapter=adapter or OpenAICompatibleDirectorAdapter(),
        context_provider=context_provider,
        registry=registry,
        store=director_store,
    )
    workflow = WorkflowApplicationService.for_current_project(registry)
    material_requirements = MaterialRequirementsService(
        store=MaterialRequirementsStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ),
        session_id=session_id,
        project_id=initial.project_id,
    )
    creation_planning = CreationPlanningService(
        store=CreationPlanningStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ),
        material_requirements=material_requirements,
        session_id=session_id,
        project_id=initial.project_id,
    )

    def capability_provider():
        return CapabilityRegistryReference.create(
            registry_id="creation_capabilities_local",
            registry_revision=1,
            capabilities=(
                CapabilityRequirement(
                    capability_id="manual_import",
                    capability_kind="manual_import",
                    availability="available",
                ),
                CapabilityRequirement(
                    capability_id="local_capture",
                    capability_kind="capture",
                    availability="unconfigured",
                    limitation="No capture adapter is configured.",
                ),
                CapabilityRequirement(
                    capability_id="video_generation",
                    capability_kind="video_generation",
                    availability="unconfigured",
                    limitation="No video-generation adapter is configured.",
                ),
                CapabilityRequirement(
                    capability_id="image_generation",
                    capability_kind="image_generation",
                    availability="unconfigured",
                    limitation="No image-generation adapter is configured.",
                ),
                CapabilityRequirement(
                    capability_id="audio_generation",
                    capability_kind="audio_generation",
                    availability="unconfigured",
                    limitation="No audio-generation adapter is configured.",
                ),
                CapabilityRequirement(
                    capability_id="voice_synthesis",
                    capability_kind="voice_synthesis",
                    availability="unconfigured",
                    limitation="No voice-synthesis adapter is configured.",
                ),
                CapabilityRequirement(
                    capability_id="asset_search",
                    capability_kind="asset_search",
                    availability="unconfigured",
                    limitation="No asset-library adapter is configured.",
                ),
            ),
        )

    creation_agent = CreationPlanningAgent(
        adapter=(
            creation_adapter
            or OpenAICompatibleCreationPlanningAdapter()
        ),
        service=creation_planning,
        capability_provider=capability_provider,
    )
    return ProductionEntryService(
        director=director,
        director_store=director_store,
        workflow=workflow,
        editing_agent=EditingAgent(workflow),
        store=ProductEntryStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ),
        session_id=session_id,
        project_id=initial.project_id,
        material_requirements=material_requirements,
        creation_planning_agent=creation_agent,
        creation_planning=creation_planning,
    )


__all__ = [
    "DEFAULT_PRODUCT_SESSION_ID",
    "build_current_product_entry",
]
