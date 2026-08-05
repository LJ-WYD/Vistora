"""Current-workspace factory for the local production product entry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent import DirectorAgent, EditingAgent
from creation_planning import (
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
from material_feedback import MaterialFeedbackService, MaterialFeedbackStore
from material_production import (
    MaterialCatalogStore,
    MaterialProductionAgent,
    MaterialProductionOrchestrator,
    MaterialProductionStore,
    build_creation_capability_reference,
    build_material_production_registry,
)
from effect_workflow import build_effect_adapter_registry
from effect_jobs import EffectJobLifecycleService, EffectJobStore

from .service import ProductionEntryService
from .store import ProductEntryStore


DEFAULT_PRODUCT_SESSION_ID = "session_local_product"


def _material_facts(
    snapshot,
    catalog_entries=(),
) -> tuple[DirectorMaterialFact, ...]:
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
    for entry in sorted(
        catalog_entries,
        key=lambda item: item.material_id,
    ):
        evidence = SourceEvidenceReference(
            evidence_id=f"evidence_catalog_{entry.material_id[7:]}",
            material_id=entry.material_id,
            locator=WholeMaterialLocator(),
            description=(
                "Validated, explicitly accepted material catalog entry."
            ),
        )
        facts.append(
            DirectorMaterialFact(
                material_id=entry.material_id,
                media_kind=entry.media_kind,
                display_name=entry.display_name,
                source_reference=entry.source_uri,
                duration_seconds=entry.duration_seconds,
                width=entry.width,
                height=entry.height,
                has_audio=entry.has_audio,
                observation_status="observed",
                evidence=(evidence,),
            )
        )
    return tuple(
        sorted(facts, key=lambda item: item.material_id)
    )


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
    catalog_store = MaterialCatalogStore.for_project_file(
        timeline_manager.PROJECT_FILE
    )
    material_feedback = MaterialFeedbackService(
        store=MaterialFeedbackStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ),
        project_id=initial.project_id,
    )

    def context_provider():
        snapshot = TimelineSnapshotService.snapshot_current()
        catalog = catalog_store.load(project_id=initial.project_id)
        return (
            DirectorContextService.build(
                snapshot,
                registry,
                materials=_material_facts(
                    snapshot,
                    catalog.entries,
                ),
                material_shortfall=material_feedback.latest_open_report(),
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

    production_adapters = build_material_production_registry()
    effect_adapters = build_effect_adapter_registry()
    effect_job_store = EffectJobStore.for_project_file(
        timeline_manager.PROJECT_FILE
    )

    def capability_provider():
        return build_creation_capability_reference(production_adapters)

    creation_agent = CreationPlanningAgent(
        adapter=(
            creation_adapter
            or OpenAICompatibleCreationPlanningAdapter()
        ),
        service=creation_planning,
        capability_provider=capability_provider,
    )
    production = MaterialProductionOrchestrator(
        creation_planning=creation_planning,
        adapters=production_adapters,
        store=MaterialProductionStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ),
        catalog=catalog_store,
        staging_root=(
            catalog_store.path.parent / "material_staging"
        ),
        project_id=initial.project_id,
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
        material_production=production,
        material_production_agent=MaterialProductionAgent(production),
        material_feedback=material_feedback,
        effect_capability_provider=effect_adapters.public_view,
        effect_fillback_provider=lambda: {
            "schema_name": "vistora.effect-fillback-view",
            "schema_version": "1.0.0",
            "status": "available_after_human_acceptance",
            "layer_kinds": ("effect_layer", "standard_clip", "transparent_layer"),
            "message": (
                "Accepted catalog artifacts return through Director review, "
                "independent workflow confirmation, EditingAgent, and registered atomic tools."
            ),
        },
        effect_job_provider=lambda: EffectJobLifecycleService.project_view(
            effect_job_store.load(project_id=initial.project_id)
        ).model_dump(mode="json"),
        delivery_qc_provider=lambda: {
            "schema_name": "vistora.delivery-qc-product-view",
            "schema_version": "1.0.0",
            "status": "not_run",
            "checks": (
                "duration", "frame_size", "codec", "audio_tracks",
                "black_frames", "freeze_frames", "loudness", "subtitles",
                "full_decode",
            ),
            "message": (
                "Run the read-only qc command against an allowlisted finished export; "
                "no delivery has been inspected in this session."
            ),
        },
    )


__all__ = [
    "DEFAULT_PRODUCT_SESSION_ID",
    "build_current_product_entry",
]
