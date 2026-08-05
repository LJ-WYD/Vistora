"""Original O32 version comparison, brand, preferences and delivery tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import EditingAgent  # noqa: E402
from atomic_runtime import build_production_registry  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from delivery_qc import DeliveryQCProfile  # noqa: E402
from delivery_workflow import (  # noqa: E402
    BrandStylePack,
    DeliveryIntegrityError,
    DeliveryPlan,
    DeliveryStore,
    DeliveryVariantSpecification,
    DeliveryWorkflowError,
    DeliveryWorkflowService,
    UserPreferenceProfile,
)
from plan_review import PlanDiffRequest, ProposedEditingExecutionPlan, RegistrySchemaReference  # noqa: E402
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import WorkflowApplicationService, WorkflowStore  # noqa: E402


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


class IDs:
    def __init__(self): self.index = 0
    def __call__(self, prefix):
        self.index += 1
        return f"{prefix}_{self.index:08d}"


def _timeline(source="material://source_delivery"):
    return TimelineConfig(
        width=160, height=90, fps=24,
        tracks={
            "video": TrackConfig(id="track_delivery_video", kind="video", order=0, clips=[
                ClipConfig(id="clip_delivery", source=source, trim_out=1, keep_audio=True)
            ]),
            "audio": TrackConfig(id="track_delivery_audio", kind="audio", order=1),
        },
    )


def _brand():
    return BrandStylePack(
        brand_pack_id="brand_vistora_launch", version=1, name="Vistora Launch",
        colors=("#6D5EF7", "#F4F7FF"), logical_fonts=("sans",),
        logo_material_ids=("source_brand_logo",),
        tone_keywords=("cinematic", "clear"), prohibited_uses=("unapproved_logo_distortion",),
    )


def _preferences():
    return UserPreferenceProfile(
        preference_id="preference_delivery_user", version=1,
        user_id="user_delivery_local", default_variant_ids=("landscape", "vertical"),
        subtitle_mode="none", target_lufs=-14, filename_prefix="vistora",
    )


def _plan(snapshot, destination_id="delivery_destination_local"):
    project = DeliveryWorkflowService.project_version(snapshot, version_id="project_version_delivery_v1")
    variants = tuple(
        DeliveryVariantSpecification(
            variant_id=variant_id, filename=filename, width=width, height=height, fps=fps,
            qc_profile=DeliveryQCProfile(
                profile_id=f"qc_profile_{variant_id}", expected_width=width,
                expected_height=height, target_lufs=-14, loudness_tolerance_lu=10,
                maximum_true_peak_dbtp=0,
            ),
        )
        for variant_id, filename, width, height, fps in (
            ("landscape", "vistora-landscape.mp4", 160, 90, 24),
            ("vertical", "vistora-vertical.mp4", 90, 160, 24),
        )
    )
    return DeliveryPlan.create(
        delivery_plan_id="delivery_plan_release_v1", version=1,
        project=project, destination_id=destination_id, brand=_brand(),
        preferences=_preferences(), variants=variants, subtitle_track_ids=(),
    )


def test_brand_preferences_and_delivery_contracts_are_strict_safe_and_bound():
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    plan = _plan(snapshot)
    assert plan.model_validate_json(plan.model_dump_json()) == plan
    assert plan.plan_digest.startswith("sha256:")
    assert "C:\\" not in plan.model_dump_json() and "/Users/" not in plan.model_dump_json()
    with pytest.raises(ValidationError):
        BrandStylePack.model_validate({**_brand().model_dump(), "colors": ["red"]})
    with pytest.raises(ValidationError, match="unique filenames"):
        DeliveryPlan.create(
            delivery_plan_id="delivery_plan_bad", version=1, project=plan.project,
            destination_id=plan.destination_id, brand=plan.brand, preferences=plan.preferences,
            variants=(plan.variants[0], plan.variants[1].model_copy(update={"filename": plan.variants[0].filename})),
        )
    with pytest.raises(ValidationError, match="digest mismatched"):
        DeliveryPlan.model_validate({**plan.model_dump(), "version": 2})


def test_project_version_comparison_is_deterministic_detached_and_path_redacted():
    before = TimelineSnapshotService.snapshot(_timeline("C:/private/source.mp4"))
    changed = _timeline("C:/private/source.mp4")
    changed.width = 320
    changed.tracks["video"].clips[0].timeline_start = 2
    changed.tracks["video"].clips.append(
        ClipConfig(id="clip_delivery_second", source="C:/private/second.mp4", trim_out=1, timeline_start=3)
    )
    after = TimelineSnapshotService.snapshot(changed)
    after = after.model_copy(update={"project_id": before.project_id})
    first = DeliveryWorkflowService.compare(before, after, comparison_id="comparison_delivery_versions", before_version_id="project_version_before", after_version_id="project_version_after")
    second = DeliveryWorkflowService.compare(before, after, comparison_id="comparison_delivery_versions", before_version_id="project_version_before", after_version_id="project_version_after")
    assert first == second
    assert first.added >= 1 and first.modified >= 2
    assert "private" not in first.model_dump_json()
    assert {item.entity_kind for item in first.changes} >= {"project_settings", "clip"}


def test_delivery_plan_compiles_only_to_existing_confirmed_export_boundary(tmp_path):
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    plan = _plan(snapshot)
    service = DeliveryWorkflowService(destinations={plan.destination_id: tmp_path}, clock=lambda: NOW)
    director = service.compile_director_plan(plan)
    assert len(director.operations) == 1
    assert director.operations[0].tool_name == "VideoExportVariantsSkill"
    assert director.operations[0].arguments["output_policy"] == "create_new"
    assert tuple(item["variant_id"] for item in director.operations[0].arguments["variants"]) == ("landscape", "vertical")
    with pytest.raises(DeliveryWorkflowError, match="not configured"):
        DeliveryWorkflowService(destinations={}).compile_director_plan(_plan(snapshot, "unknown_destination"))


def test_delivery_store_is_atomic_append_only_and_tamper_detecting(tmp_path):
    plan = _plan(TimelineSnapshotService.snapshot(_timeline()))
    store = DeliveryStore(tmp_path / "project.deliveries.json")
    ledger = store.append_plan(plan, expected_revision=0)
    assert ledger.revision == 1
    with pytest.raises(Exception):
        store.append_plan(plan, expected_revision=1)
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["plans"][0]["brand"]["name"] = "Tampered"
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeliveryIntegrityError):
        store.load(project_id=plan.project.project_id)


def test_full_delivery_uses_review_confirmation_editing_gateway_qc_and_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
    ], check=True)
    project_file = tmp_path / ".workspace" / "current_timeline.json"
    project_file.parent.mkdir()
    project_file.write_text(_timeline(str(source)).model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project_file.parent))
    TraceabilityStore.trace_path(project_file).unlink(missing_ok=True)
    snapshot = TimelineSnapshotService.snapshot_current()
    plan = _plan(snapshot)
    delivery = DeliveryWorkflowService(destinations={plan.destination_id: tmp_path}, clock=lambda: NOW)
    store = DeliveryStore.for_project_file(project_file)
    ledger = store.append_plan(plan, expected_revision=0)
    director = delivery.compile_director_plan(plan)
    registry = build_production_registry()
    review_request = delivery.review_request(
        plan, snapshot, registry, request_id="review_delivery_release_v1"
    )
    assert review_request.director_plan == director
    ids = IDs()
    workflow = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file), registry=registry,
        clock=lambda: NOW, id_factory=ids,
    )
    review = workflow.record_review(review_request)
    confirmation = workflow.confirm_review(review.review_id, confirmed_by="user_delivery_local", decision="confirmed")
    agent = EditingAgent(workflow, clock=lambda: NOW, id_factory=ids)
    request = agent.prepare_execution(
        request_id="editing_request_delivery_release_v1",
        confirmation_record_id=confirmation.confirmation_record_id,
    )
    report = agent.execute(request)
    assert report.status == "succeeded" and report.disposition == "executed"
    run = [entry.record for entry in workflow.store.load().entries if entry.record.schema_name == "vistora.workflow.execution-run"][-1]
    atomic_result = run.steps[0].result
    manifest = delivery.finalize(
        plan, confirmation_id=confirmation.user_confirmation.confirmation_id,
        execution_id=run.execution_plan.execution_id, atomic_result=atomic_result,
    )
    ledger = store.append_manifest(manifest, expected_revision=ledger.revision)
    assert ledger.revision == 2
    assert manifest.status in {"succeeded", "warning"}
    assert [item.variant_id for item in manifest.items] == ["landscape", "vertical"]
    assert all(item.qc_status in {"passed", "warning"} for item in manifest.items)
    assert all((tmp_path / item.filename).is_file() for item in manifest.items)
    assert str(tmp_path) not in manifest.model_dump_json()
    assert project_file.read_text(encoding="utf-8") == _timeline(str(source)).model_dump_json(indent=2)


def test_delivery_architecture_has_no_direct_timeline_mutation_or_skill_import():
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "delivery_workflow").glob("*.py"))
    assert "TimelineManager" not in source
    assert "TimelineRenderer" not in source
    assert "from skills" not in source
    assert "AtomicExecutionGateway" not in source
