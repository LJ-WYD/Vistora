"""Deterministic test-only reference for Vistora's intended main workflow.

The deterministic Director adapter produces the structured proposal from
analyzed facts. A separate user confirmation still gates the constrained
Editing Agent and atomic-tool mutation boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import main as vistora_main  # noqa: E402
from agent import (  # noqa: E402
    DirectorAgent,
    EditingAgent,
    EditingAgentExecutionReport,
)
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    DirectorOperation,
    DirectorPlan,
    EditingExecutionPlan,
    MediaTimeRangeLocator,
    PlanReference,
    SourceEvidenceReference,
    UserConfirmationRecord,
    WholeMaterialLocator,
)
from core import timeline_manager  # noqa: E402
from director import (  # noqa: E402
    CreativeBriefInput,
    DirectorContextService,
    DirectorPlanDraft,
    DirectorReasoningOutput,
    DirectorSessionLedger,
    DirectorStore,
    DirectorTurnReport,
    MaterialRequirementItem,
    MaterialRequirementsDraft,
    RequirementConstraint,
)
from material_requirements import (  # noqa: E402
    MaterialRequirementsService,
    MaterialRequirementsStore,
)
from creation_planning import (  # noqa: E402
    CapabilityRegistryReference,
    CapabilityRequirement,
    CreationPlanningAgent,
    CreationPlanningReasoningOutput,
    CreationPlanningService,
    CreationPlanningStore,
    DeliveryFileSpecification,
    MaterialProductionPlanDraft,
    MaterialProductionTask,
    ProductionEstimate,
    PromptSpecification,
    ReproducibilityParameter,
)
from material_production import (  # noqa: E402
    AdapterRegistry,
    DeterministicLocalVideoAdapter,
    MaterialCatalogStore,
    MaterialProductionOrchestrator,
    MaterialProductionStore,
)
from product_entry.factory import _material_facts  # noqa: E402
from moviepy import ColorClip  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffDocument,
)
from timeline_query import TimelineSnapshotService  # noqa: E402
from traceability.models import TimelineTraceDocument  # noqa: E402
from traceability.query import TraceabilityQuery  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import (  # noqa: E402
    RollbackProposal,
    RollbackRunRecord,
    WorkflowApplicationService,
    WorkflowLedger,
    WorkflowStore,
)


REFERENCE_TIME = datetime(2026, 7, 24, tzinfo=timezone.utc)
REFERENCE_CLIP_UUID = UUID("12345678-1234-5678-1234-567812345678")
REFERENCE_PLAN_DIGEST = (
    "sha256:c8535c33ccf6539ba5604ab8ab339994580b0bd4e9c54f6b8b7a203ce59ece80"
)
REFERENCE_TOOL_ORDER = (
    "VideoClearTimelineSkill",
    "VideoAddClipSkill",
    "VideoExportSkill",
)


@dataclass(frozen=True)
class AnalyzedMediaFacts:
    source_path: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    has_audio: bool
    visual_summary: str


@dataclass(frozen=True)
class ReferenceWorkflowReport:
    facts: AnalyzedMediaFacts
    director_report: DirectorTurnReport
    director_ledger: DirectorSessionLedger
    plan: DirectorPlan
    pre_confirmation_diff: PlanDiffDocument
    confirmation: UserConfirmationRecord
    execution: EditingExecutionPlan
    editing_agent_report: EditingAgentExecutionReport
    requests: tuple[AtomicToolRequestEnvelope, ...]
    results: tuple[AtomicToolResultEnvelope, ...]
    trace_document: TimelineTraceDocument
    traced_clips: tuple[dict[str, Any], ...]
    workflow_ledger: WorkflowLedger
    rollback_proposal: RollbackProposal
    rollback_run: RollbackRunRecord
    timeline_restored: bool
    output_metadata: dict[str, Any]
    timeline_state_removed: bool
    no_material_chain: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        return {
            "facts": asdict(self.facts),
            "director_status": self.director_report.status,
            "director_brief_version": (
                self.director_report.brief.brief_version
            ),
            "plan_id": self.plan.plan_id,
            "plan_version": self.plan.plan_version,
            "plan_digest": self.plan.digest(),
            "pre_confirmation_diff_id": self.pre_confirmation_diff.diff_id,
            "pre_confirmation_diff_digest": (
                self.pre_confirmation_diff.digest()
            ),
            "pre_confirmation_review_status": (
                self.pre_confirmation_diff.review_status
            ),
            "confirmation_id": self.confirmation.confirmation_id,
            "execution_id": self.execution.execution_id,
            "editing_agent_status": self.editing_agent_report.status,
            "editing_agent_report_id": self.editing_agent_report.report_id,
            "request_ids": [request.request_id for request in self.requests],
            "result_ids": [result.result_id for result in self.results],
            "tool_order": [request.tool_name for request in self.requests],
            "trace_revision": self.trace_document.revision,
            "trace_ids": [
                trace.trace_id
                for trace in self.trace_document.confirmed_traces
            ],
            "traced_clips": list(self.traced_clips),
            "workflow_revision": self.workflow_ledger.revision,
            "workflow_integrity_digest": (
                self.workflow_ledger.integrity_digest
            ),
            "rollback_proposal_digest": self.rollback_proposal.digest(),
            "rollback_status": self.rollback_run.status,
            "timeline_restored": self.timeline_restored,
            "output_metadata": self.output_metadata,
            "timeline_state_removed": self.timeline_state_removed,
            "no_material_chain": self.no_material_chain,
        }


def _probe_media(path: str) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,r_frame_rate",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        path,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(completed.stdout)
    video_streams = [
        stream
        for stream in data.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    audio_streams = [
        stream
        for stream in data.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    if len(video_streams) != 1:
        raise AssertionError(
            f"Expected one video stream in {path}, found {len(video_streams)}"
        )
    video = video_streams[0]
    return {
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": video.get("r_frame_rate"),
        "audio_stream_count": len(audio_streams),
        "duration_seconds": float(data["format"]["duration"]),
        "size_bytes": int(data["format"]["size"]),
    }


def _generate_source(path: str) -> AnalyzedMediaFacts:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    clip = ColorClip(
        size=(320, 180),
        color=(12, 34, 56),
        duration=2.0,
    ).with_fps(24)
    try:
        clip.write_videofile(
            path,
            codec="libx264",
            audio=False,
            logger=None,
        )
    finally:
        clip.close()

    metadata = _probe_media(path)
    expected = {
        "video_codec": "h264",
        "width": 320,
        "height": 180,
        "frame_rate": "24/1",
        "audio_stream_count": 0,
    }
    for field, value in expected.items():
        if metadata[field] != value:
            raise AssertionError(
                f"Unexpected synthetic source {field}: "
                f"{metadata[field]!r} != {value!r}"
            )
    if abs(metadata["duration_seconds"] - 2.0) > 0.05:
        raise AssertionError(
            "Synthetic source duration is outside the deterministic tolerance"
        )

    return AnalyzedMediaFacts(
        source_path=path,
        duration_seconds=2.0,
        width=320,
        height=180,
        fps=24,
        has_audio=False,
        visual_summary="Uniform RGB(12, 34, 56) reference frame.",
    )


def _build_plan(
    facts: AnalyzedMediaFacts,
    output_path: str,
) -> DirectorPlan:
    fact_payload = json.dumps(
        asdict(facts),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    fact_digest = f"sha256:{hashlib.sha256(fact_payload).hexdigest()}"
    catalog_source = facts.source_path.startswith("material://")
    material_id = (
        facts.source_path.removeprefix("material://")
        if catalog_source
        else TimelineSnapshotService.source_id_for_configured_path(
            facts.source_path
        )
    )
    evidence_id = (
        f"evidence_catalog_{material_id[7:]}"
        if catalog_source
        else "evidence_reference_source_trim"
    )
    return DirectorPlan(
        plan_id="plan_reference_main_flow",
        plan_version=1,
        created_at=REFERENCE_TIME,
        objective="Export a deterministic trimmed reference clip.",
        requirements=(
            "Use the known analyzed source facts.",
            "Trim the source to 0.25-1.75 seconds.",
            "Keep the output silent.",
            "Clear timeline state after export.",
        ),
        assumptions=(
            "Synthetic source facts are trusted test fixture inputs.",
        ),
        creative_direction={
            "analyzed_facts": asdict(facts),
            "pacing": "single concise 1.5 second shot",
            "audio": "silent",
        },
        source_evidence=(
            SourceEvidenceReference(
                evidence_id=evidence_id,
                material_id=material_id,
                locator=(
                    WholeMaterialLocator()
                    if catalog_source
                    else MediaTimeRangeLocator(
                        start_seconds=0.25,
                        end_seconds=1.75,
                    )
                ),
                analysis_fact_id=(
                    None if catalog_source else "analysis_fact_reference_source"
                ),
                analysis_fact_digest=(
                    None if catalog_source else fact_digest
                ),
                description=(
                    "Validated, explicitly accepted material catalog entry."
                    if catalog_source
                    else "Known deterministic source range used by the trim."
                ),
            ),
        ),
        operations=(
            DirectorOperation(
                operation_id="operation_clear_timeline",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Begin from isolated test timeline state.",
                expected_effect="No prior clips remain.",
            ),
            DirectorOperation(
                operation_id="operation_add_reference_clip",
                tool_name="VideoAddClipSkill",
                arguments={
                    "source_path": facts.source_path,
                    "trim_in": 0.25,
                    "trim_out": 1.75,
                    "speed_factor": 1.0,
                    "reverse": False,
                    "rotate": 0,
                    "keep_audio": False,
                },
                rationale="Use the confirmed deterministic trim.",
                expected_effect="One silent 1.5 second timeline clip.",
                evidence_ids=(evidence_id,),
            ),
            DirectorOperation(
                operation_id="operation_export_reference",
                tool_name="VideoExportSkill",
                arguments={
                    "output_path": output_path,
                    "clear_timeline_after": True,
                },
                rationale="Materialize and verify the confirmed output.",
                expected_effect="One exported MP4 and no residual timeline.",
            ),
        ),
        outputs=(output_path,),
        risks=("Hardware encoder availability may vary by machine.",),
    )


class DeterministicReferenceDirectorAdapter:
    """Test-only fake reasoning adapter with deterministic directing output."""

    def __init__(
        self,
        facts: AnalyzedMediaFacts,
        output_path: str,
    ) -> None:
        self.facts = facts
        self.output_path = output_path
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        intended = _build_plan(self.facts, self.output_path)
        evidence = request.context.materials[0].evidence[0]
        brief = CreativeBriefInput(
            objective=intended.objective,
            audience="Vistora regression reviewers.",
            platform="Automated local validation.",
            target_duration_seconds=1.5,
            style="Deterministic single-shot reference.",
            narrative="Present one concise analyzed source range.",
            pacing="single concise 1.5 second shot",
            must_haves=intended.requirements,
            must_not_haves=("Do not invent unobserved source facts.",),
            delivery_requirements=("Export one H.264 MP4.",),
            material_ids=(evidence.material_id,),
            evidence_ids=(evidence.evidence_id,),
            assumptions=intended.assumptions,
            acceptance_criteria=(
                "Output is 320x180 at 24 fps.",
                "Output duration is 1.5 seconds.",
                "Timeline is clear after export.",
            ),
        )
        return DirectorReasoningOutput(
            response_kind="propose",
            assistant_message=(
                "The analyzed source and requirements are sufficient; "
                "I prepared a deterministic proposal for review."
            ),
            context_snapshot_ref=request.context.snapshot_ref,
            registry_ref=request.context.registry_ref,
            brief=brief,
            plan_draft=DirectorPlanDraft(
                objective=intended.objective,
                requirements=intended.requirements,
                assumptions=intended.assumptions,
                creative_direction=intended.creative_direction,
                operations=intended.operations,
                outputs=intended.outputs,
                risks=intended.risks,
            ),
        ).model_dump(mode="json")


class DeterministicMaterialRequirementsDirectorAdapter:
    """No-material Director branch used before any source is observed."""

    def complete(self, request):
        unknown = RequirementConstraint(status="unknown")
        return DirectorReasoningOutput(
            response_kind="propose_material_requirements",
            assistant_message=(
                "The no-material brief is complete; exact source "
                "requirements are ready for review."
            ),
            context_snapshot_ref=request.context.snapshot_ref,
            registry_ref=request.context.registry_ref,
            brief=CreativeBriefInput(
                objective="Create the deterministic reference clip.",
                audience="Vistora regression reviewers.",
                platform="Automated local validation.",
                target_duration_seconds=1.5,
                style="Deterministic single-shot reference.",
                narrative="Present one concise grounded source range.",
                pacing="One concise shot.",
                must_haves=("Use one verified source clip.",),
                must_not_haves=("Do not invent existing material.",),
                delivery_requirements=("Provide an H.264-compatible source.",),
                acceptance_criteria=(
                    "The source is 320x180 at 24 fps.",
                    "The accepted source is at least 1.5 seconds.",
                ),
            ),
            material_requirements_draft=MaterialRequirementsDraft(
                rationale=(
                    "No observed material exists, so define the exact source "
                    "required before planning production."
                ),
                items=(
                    MaterialRequirementItem(
                        item_id="reference_material_requirement",
                        asset_type="video_shot",
                        purpose="Supply the grounded reference picture.",
                        narrative_position="Only shot.",
                        duration_seconds=2.0,
                        aspect_ratio="16:9",
                        width=320,
                        height=180,
                        fps=24.0,
                        must_haves=("Use a stable uniform reference frame.",),
                        must_not_haves=("Do not claim an unobserved source.",),
                        acceptance_criteria=(
                            "The accepted clip probes as 320x180 at 24 fps.",
                        ),
                        priority="required",
                        budget_constraint=unknown,
                        deadline_constraint=unknown,
                    ),
                ),
                global_acceptance_criteria=(
                    "Accepted media maps to the exact requirement item.",
                ),
                unresolved_constraints=(
                    "Provider cost is unknown.",
                ),
            ),
        ).model_dump(mode="json")


class DeterministicCreationPlanningAdapter:
    """Plans a truthful manual/import path without producing media."""

    def complete(self, request):
        unknown = ProductionEstimate(
            status="unknown",
            rationale="No production provider is invoked in this reference.",
        )
        return CreationPlanningReasoningOutput(
            outcome="proposal",
            message="The deterministic import plan is ready for review.",
            material_confirmation_ref=request.material_confirmation_ref,
            capability_registry_ref=request.capability_registry_ref,
            plan_draft=MaterialProductionPlanDraft(
                rationale=(
                    "Use the bounded manual-import capability to supply the "
                    "confirmed source requirement."
                ),
                tasks=(
                    MaterialProductionTask(
                        task_id="reference_import_task",
                        requirement_item_id="reference_material_requirement",
                        title="Import verified synthetic reference source",
                        purpose="Supply the confirmed single-shot source.",
                        production_method="generate",
                        status="planned",
                        capability_ids=("video_generation",),
                        prompt_spec=PromptSpecification(
                            subject="A uniform deterministic reference frame.",
                            scene="A synthetic 320x180 test canvas.",
                            camera="Locked frame.",
                            action="No movement.",
                            lighting="Uniform generated color.",
                            style="Deterministic regression fixture.",
                            negative_constraints=(
                                "No nondeterministic content.",
                            ),
                        ),
                        duration_seconds=2.0,
                        width=320,
                        height=180,
                        aspect_ratio="16:9",
                        fps=24.0,
                        seed=24,
                        reproducibility_parameters=(
                            ReproducibilityParameter(
                                name="fixture_rgb",
                                value="12,34,56",
                            ),
                        ),
                        batch_id="reference_import_batch",
                        cost_estimate=unknown,
                        time_estimate=unknown,
                        quality_gates=(
                            "ffprobe reports 320x180 at 24 fps.",
                        ),
                        retry_strategy=(
                            "Reject and re-import a valid fixture.",
                        ),
                        alternative_strategy=(
                            "Capture an equivalent verified local fixture."
                        ),
                        delivery=DeliveryFileSpecification(
                            media_kind="video",
                            container_or_extension="mp4",
                            mime_type="video/mp4",
                            filename_pattern="reference_source.mp4",
                        ),
                    ),
                ),
                delivery_summary=("One verified synthetic source clip.",),
                global_quality_gates=(
                    "The delivery maps to its confirmed requirement.",
                ),
                limitations=(
                    "This step plans only; it does not create media.",
                ),
            ),
        ).model_dump(mode="json")


def _fixed_execution(
    plan: DirectorPlan,
    confirmation: UserConfirmationRecord,
) -> EditingExecutionPlan:
    execution = EditingExecutionPlan.from_confirmed_plan(
        execution_id="execution_reference_main_flow",
        project_id="project_reference_main_flow",
        director_plan=plan,
        confirmation=confirmation,
    )
    data = execution.model_dump(mode="json")
    data["created_at"] = (REFERENCE_TIME + timedelta(minutes=2)).isoformat()
    return EditingExecutionPlan.model_validate(data)


@contextmanager
def _isolated_timeline(work_dir: Path) -> Iterator[Path]:
    original_workspace = timeline_manager.WORKSPACE_DIR
    original_project_file = timeline_manager.PROJECT_FILE
    workspace = work_dir / ".workspace"
    project_file = workspace / "current_timeline.json"
    timeline_manager.WORKSPACE_DIR = str(workspace)
    timeline_manager.PROJECT_FILE = str(project_file)
    TraceabilityStore.trace_path(project_file).unlink(missing_ok=True)
    WorkflowStore.for_project_file(project_file).path.unlink(missing_ok=True)
    DirectorStore(
        project_file.with_name("reference.director.json")
    ).path.unlink(missing_ok=True)
    DirectorStore(
        project_file.with_name("reference.no-material.director.json")
    ).path.unlink(missing_ok=True)
    MaterialRequirementsStore(
        project_file.with_name("reference.materials.json")
    ).path.unlink(missing_ok=True)
    CreationPlanningStore(
        project_file.with_name("reference.creation-planning.json")
    ).path.unlink(missing_ok=True)
    MaterialProductionStore.for_project_file(
        project_file
    ).path.unlink(missing_ok=True)
    MaterialCatalogStore.for_project_file(
        project_file
    ).path.unlink(missing_ok=True)
    shutil.rmtree(workspace / "material_staging", ignore_errors=True)
    shutil.rmtree(workspace / "materials", ignore_errors=True)
    try:
        yield project_file
    finally:
        timeline_manager.WORKSPACE_DIR = original_workspace
        timeline_manager.PROJECT_FILE = original_project_file


def _verify_output(path: str) -> dict[str, Any]:
    metadata = _probe_media(path)
    expected = {
        "video_codec": "h264",
        "width": 320,
        "height": 180,
        "frame_rate": "24/1",
        "audio_stream_count": 0,
    }
    for field, value in expected.items():
        if metadata[field] != value:
            raise AssertionError(
                f"Unexpected output {field}: {metadata[field]!r} != {value!r}"
            )
    if abs(metadata["duration_seconds"] - 1.5) > 0.08:
        raise AssertionError(
            "Reference output duration is outside the deterministic tolerance"
        )
    if metadata["size_bytes"] <= 0:
        raise AssertionError("Reference output is empty")
    return metadata


def run_reference_workflow(
    work_dir: Path = Path("tests/test_data/reference_workflow"),
) -> ReferenceWorkflowReport:
    """Run the complete test-only contract-to-atomic-tool reference flow."""

    if work_dir.is_absolute():
        raise ValueError("Use a repository-relative work_dir for stable plans")

    previous_cwd = Path.cwd()
    os.chdir(ROOT)
    try:
        output_path = (work_dir / "output.mp4").as_posix()
        with _isolated_timeline(work_dir) as project_file:
            preview_snapshot = TimelineSnapshotService.snapshot_current()
            no_material_counter = 0

            def no_material_id(prefix: str) -> str:
                nonlocal no_material_counter
                no_material_counter += 1
                return f"{prefix}_no_material_{no_material_counter:03d}"

            no_material_tick = 0

            def no_material_clock() -> datetime:
                nonlocal no_material_tick
                value = REFERENCE_TIME + timedelta(
                    minutes=10,
                    seconds=no_material_tick,
                )
                no_material_tick += 1
                return value

            def no_material_context():
                current = TimelineSnapshotService.snapshot_current()
                return (
                    DirectorContextService.build(
                        current,
                        vistora_main.SKILLS,
                        materials=(),
                    ),
                    current,
                )

            no_material_director = DirectorAgent(
                adapter=DeterministicMaterialRequirementsDirectorAdapter(),
                context_provider=no_material_context,
                registry=vistora_main.SKILLS,
                store=DirectorStore(
                    project_file.with_name(
                        "reference.no-material.director.json"
                    )
                ),
                clock=no_material_clock,
                id_factory=no_material_id,
            )
            requirements_report = no_material_director.converse(
                session_id="session_reference_no_material",
                turn_id="turn_reference_no_material",
                user_message=(
                    "Create the deterministic reference, but no materials "
                    "exist yet."
                ),
            )
            if (
                requirements_report.status
                != "material_requirements_ready"
                or requirements_report.material_requirements is None
            ):
                raise AssertionError(
                    "No-material Director did not produce requirements"
                )
            material_service = MaterialRequirementsService(
                store=MaterialRequirementsStore(
                    project_file.with_name(
                        "reference.materials.json"
                    )
                ),
                session_id="session_reference_no_material",
                project_id=preview_snapshot.project_id,
                clock=no_material_clock,
                id_factory=no_material_id,
            )
            material_ledger = material_service.record(
                requirements_report.material_requirements,
                expected_revision=0,
            )
            material_confirmation, material_ledger = (
                material_service.decide(
                    requirements_report.material_requirements.review.review_id,
                    decision="confirmed",
                    confirmed_by="user_reference",
                    expected_revision=material_ledger.revision,
                )
            )
            creation_service = CreationPlanningService(
                store=CreationPlanningStore(
                    project_file.with_name(
                        "reference.creation-planning.json"
                    )
                ),
                material_requirements=material_service,
                session_id="session_reference_no_material",
                project_id=preview_snapshot.project_id,
                clock=no_material_clock,
                id_factory=no_material_id,
            )
            capability_ref = CapabilityRegistryReference.create(
                registry_id="reference_creation_capabilities",
                registry_revision=1,
                capabilities=(
                    CapabilityRequirement(
                        capability_id="video_generation",
                        capability_kind="video_generation",
                        availability="available",
                    ),
                ),
            )
            planning_agent = CreationPlanningAgent(
                adapter=DeterministicCreationPlanningAdapter(),
                service=creation_service,
                capability_provider=lambda: capability_ref,
                clock=no_material_clock,
                id_factory=no_material_id,
            )
            planning_request = planning_agent.prepare_request(
                request_id="creation_request_reference_no_material",
                material_confirmation_id=(
                    material_confirmation.confirmation_id
                ),
            )
            planning_report = planning_agent.plan(planning_request)
            if (
                planning_report.status != "proposal_ready"
                or planning_report.proposal is None
            ):
                raise AssertionError(
                    "CreationPlanningAgent did not create a reviewable plan"
                )
            production_confirmation, _ = creation_service.decide(
                planning_report.proposal.review.review_id,
                decision="confirmed",
                confirmed_by="user_reference",
                expected_revision=1,
            )
            catalog_store = MaterialCatalogStore.for_project_file(
                project_file
            )
            production_orchestrator = MaterialProductionOrchestrator(
                creation_planning=creation_service,
                adapters=AdapterRegistry(
                    (
                        DeterministicLocalVideoAdapter(
                            clock=no_material_clock,
                        ),
                    )
                ),
                store=MaterialProductionStore.for_project_file(project_file),
                catalog=catalog_store,
                staging_root=project_file.parent / "material_staging",
                project_id=preview_snapshot.project_id,
                clock=no_material_clock,
                id_factory=no_material_id,
            )
            production_request = (
                production_orchestrator.prepare_request(
                    request_id="production_request_reference_no_material",
                    production_confirmation_id=(
                        production_confirmation.confirmation_id
                    ),
                    requested_by="user_reference",
                )
            )
            production_run = production_orchestrator.start(
                production_request
            )
            if production_run["status"] != "awaiting_review":
                raise AssertionError(
                    "Fake production did not reach artifact review"
                )
            production_artifact = (
                production_orchestrator.view().artifacts[0]
            )
            _, catalog_entry = (
                production_orchestrator.decide_artifact(
                    production_artifact["artifact_id"],
                    decision="accepted",
                    decided_by="user_reference",
                    reason=(
                        "The deterministic artifact passed exact ffprobe "
                        "validation."
                    ),
                )
            )
            if catalog_entry is None:
                raise AssertionError("Accepted material was not cataloged")
            facts = AnalyzedMediaFacts(
                source_path=catalog_entry.source_uri,
                duration_seconds=(
                    catalog_entry.duration_seconds or 2.0
                ),
                width=catalog_entry.width or 320,
                height=catalog_entry.height or 180,
                fps=int(catalog_entry.fps or 24),
                has_audio=bool(catalog_entry.has_audio),
                visual_summary=(
                    "Validated deterministic catalog reference frame."
                ),
            )
            no_material_chain = {
                "director_status": requirements_report.status,
                "requirements_plan_id": (
                    requirements_report.material_requirements.plan.plan_id
                ),
                "requirements_plan_digest": (
                    requirements_report.material_requirements.plan.digest()
                ),
                "requirements_confirmation_id": (
                    material_confirmation.confirmation_id
                ),
                "creation_planning_status": planning_report.status,
                "production_plan_id": (
                    planning_report.proposal.plan.production_plan_id
                ),
                "production_plan_digest": (
                    planning_report.proposal.plan.digest()
                ),
                "production_confirmation_id": (
                    production_confirmation.confirmation_id
                ),
                "production_run_id": production_run["run_id"],
                "catalog_material_id": catalog_entry.material_id,
                "catalog_revision": (
                    production_orchestrator.view().catalog_revision
                ),
                "production_method": (
                    planning_report.proposal.plan.tasks[0].production_method
                ),
                "media_created": True,
                "artifact_accepted": True,
            }
            intended = _build_plan(facts, output_path)
            material = _material_facts(
                preview_snapshot,
                (catalog_entry,),
            )[0]

            def director_context():
                current = TimelineSnapshotService.snapshot_current()
                return (
                    DirectorContextService.build(
                        current,
                        vistora_main.SKILLS,
                        materials=(material,),
                    ),
                    current,
                )

            director_tick = -1

            def director_clock() -> datetime:
                nonlocal director_tick
                director_tick += 1
                return REFERENCE_TIME + timedelta(
                    seconds=director_tick - 1
                )

            director_counts = {}

            def director_id(prefix: str) -> str:
                exact = {
                    "director_plan": "plan_reference_main_flow",
                    "proposed_execution": (
                        "proposal_execution_reference_main_flow"
                    ),
                    "plan_review_request": "review_reference_main_flow",
                    "director_proposal": (
                        "director_proposal_reference_main_flow"
                    ),
                }
                if prefix in exact:
                    return exact[prefix]
                director_counts[prefix] = (
                    director_counts.get(prefix, 0) + 1
                )
                return (
                    f"{prefix}_reference_"
                    f"{director_counts[prefix]:03d}"
                )

            director_adapter = DeterministicReferenceDirectorAdapter(
                facts,
                output_path,
            )
            director_store = DirectorStore(
                project_file.with_name("reference.director.json")
            )
            director = DirectorAgent(
                adapter=director_adapter,
                context_provider=director_context,
                registry=vistora_main.SKILLS,
                store=director_store,
                clock=director_clock,
                id_factory=director_id,
            )
            director_report = director.converse(
                session_id="session_reference_main_flow",
                turn_id="turn_reference_main_flow_001",
                user_message=(
                    "Create the deterministic 1.5 second silent reference "
                    "cut from the observed analyzed source, export it, and "
                    "clear the timeline afterward."
                ),
            )
            if (
                director_report.status != "proposal_ready"
                or director_report.proposal is None
            ):
                raise AssertionError(
                    "Reference Director did not create a reviewable proposal"
                )
            plan = director_report.proposal.plan
            preview_request = director_report.proposal.review_request
            pre_confirmation_diff = director_report.proposal.review.diff
            director_ledger = director_store.load()
            if plan.digest() != REFERENCE_PLAN_DIGEST:
                raise AssertionError(
                    "Reference DirectorPlan digest changed; review the "
                    "deterministic adapter and update REFERENCE_PLAN_DIGEST "
                    f"intentionally: {plan.digest()}"
                )
            counter = 0

            def reference_id(prefix: str) -> str:
                nonlocal counter
                counter += 1
                return f"{prefix}_reference_{counter:03d}"

            tick = 0

            def reference_clock() -> datetime:
                nonlocal tick
                value = REFERENCE_TIME + timedelta(seconds=tick)
                tick += 1
                return value

            workflow = WorkflowApplicationService(
                store=WorkflowStore.for_project_file(project_file),
                registry=vistora_main.SKILLS,
                clock=reference_clock,
                id_factory=reference_id,
            )
            review_record = workflow.record_review(preview_request)
            confirmation_record = workflow.confirm_review(
                review_record.review_id,
                confirmed_by="user_reference",
                decision="confirmed",
            )
            editing_agent = EditingAgent(
                workflow,
                clock=reference_clock,
                id_factory=reference_id,
            )
            agent_request = editing_agent.prepare_execution(
                request_id="editing_request_reference_main_flow",
                confirmation_record_id=(
                    confirmation_record.confirmation_record_id
                ),
            )
            with patch(
                "skills.video_add_clip.uuid.uuid4",
                return_value=REFERENCE_CLIP_UUID,
            ):
                editing_agent_report = editing_agent.execute(agent_request)
            if editing_agent_report.status != "succeeded":
                raise AssertionError(
                    "Reference Editing Agent execution ended as "
                    f"{editing_agent_report.status}"
                )
            execution_runs = [
                entry.record
                for entry in workflow.store.load().entries
                if entry.record.schema_name
                == "vistora.workflow.execution-run"
            ]
            execution_run = execution_runs[-1]
            confirmation = confirmation_record.user_confirmation
            execution = execution_run.execution_plan
            requests = tuple(step.request for step in execution_run.steps)
            results = tuple(step.result for step in execution_run.steps)
            output_metadata = _verify_output(output_path)
            timeline_state_removed = not project_file.exists()
            trace_document = TraceabilityStore.load()
            final_snapshot = TimelineSnapshotService.snapshot_current()
            trace_query = TraceabilityQuery(
                trace_document,
                final_snapshot,
            )
            traced_clips = tuple(
                result.model_dump(mode="json")
                for result in trace_query.plan_to_clips(
                    PlanReference.from_plan(plan)
                )
            )
            rollback_review = workflow.propose_rollback(
                execution_run.run_id
            )
            rollback_confirmation = workflow.confirm_rollback(
                rollback_review.review_id,
                confirmed_by="user_reference",
                decision="confirmed",
            )
            rollback_run = workflow.apply_rollback(
                rollback_confirmation.confirmation_id
            )
            if rollback_run.status != "succeeded":
                raise AssertionError(
                    f"Reference rollback ended as {rollback_run.status}"
                )
            timeline_restored = project_file.exists()
            workflow_ledger = workflow.store.load()

        if not timeline_state_removed:
            raise AssertionError("Reference export did not clear timeline state")

        return ReferenceWorkflowReport(
            facts=facts,
            director_report=director_report,
            director_ledger=director_ledger,
            plan=plan,
            pre_confirmation_diff=pre_confirmation_diff,
            confirmation=confirmation,
            execution=execution,
            editing_agent_report=editing_agent_report,
            requests=requests,
            results=results,
            trace_document=trace_document,
            traced_clips=traced_clips,
            workflow_ledger=workflow_ledger,
            rollback_proposal=rollback_review.proposal,
            rollback_run=rollback_run,
            timeline_restored=timeline_restored,
            output_metadata=output_metadata,
            timeline_state_removed=timeline_state_removed,
            no_material_chain=no_material_chain,
        )
    finally:
        os.chdir(previous_cwd)


def main() -> None:
    report = run_reference_workflow()
    print(json.dumps(report.summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
