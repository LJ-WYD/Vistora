"""Original O29 accepted AI-result unified-timeline fillback tests."""

from __future__ import annotations

import hashlib
import struct
import sys
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import main as vistora_main  # noqa: E402
from agent import EditingAgent  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import TimelineConfig, TrackConfig  # noqa: E402
from director import digest_json  # noqa: E402
from effect_fillback import (  # noqa: E402
    EffectArtifactAcceptance,
    EffectFillbackCompiler,
    EffectFillbackError,
    EffectFillbackPlacement,
)
from effect_workflow import (  # noqa: E402
    EffectAcceptanceCheck,
    EffectArtifactCandidate,
    EffectExecutionBinding,
    EffectExecutionReport,
    EffectTaskExecutionReport,
)
from material_production import MaterialCatalogEntry, MaterialCatalogStore  # noqa: E402
from plan_review import PlanDiffEngine  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import (  # noqa: E402
    WorkflowApplicationError,
    WorkflowApplicationService,
    WorkflowStore,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


class Deterministic:
    def __init__(self):
        self.index = 0

    def clock(self):
        value = NOW + timedelta(seconds=self.index)
        self.index += 1
        return value

    def identifier(self, prefix):
        self.index += 1
        return f"{prefix}_{self.index:04d}"


def _write_media(path: Path, media_kind: str, *, alpha=False):
    if media_kind == "image":
        mode = "RGBA" if alpha else "RGB"
        color = (220, 40, 90, 180) if alpha else (30, 120, 220)
        Image.new(mode, (32, 24), color).save(path)
        return {"duration": None, "width": 32, "height": 24, "has_audio": False, "mime": "image/png"}
    if media_kind == "audio":
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            samples = [int(1200 * ((index % 16) / 15 - 0.5)) for index in range(16000)]
            output.writeframes(b"".join(struct.pack("<h", item) for item in samples))
        return {"duration": 1.0, "width": None, "height": None, "has_audio": True, "mime": "audio/wav"}
    raise AssertionError(media_kind)


def _setup(monkeypatch, tmp_path, *, layer_kind="transparent_layer"):
    project_file = tmp_path / ".workspace" / "current_timeline.json"
    project_file.parent.mkdir(parents=True)
    timeline = TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(id="track_video_primary", kind="video", role="primary", order=0),
            "video_effects": TrackConfig(id="track_video_effects", kind="video", role="effects", order=1),
            "audio": TrackConfig(id="track_audio_primary", kind="audio", role="effects", order=2),
        },
    )
    project_file.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project_file.parent))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    snapshot = TimelineSnapshotService.snapshot_current()

    media_kind = "audio" if layer_kind == "standard_clip" else "image"
    alpha = layer_kind == "transparent_layer"
    suffix = ".wav" if media_kind == "audio" else ".png"
    staged = tmp_path / f"accepted{suffix}"
    facts = _write_media(staged, media_kind, alpha=alpha)
    content_digest = "sha256:" + hashlib.sha256(staged.read_bytes()).hexdigest()
    task_id = f"effect_task_{layer_kind}"
    output_role = "transparent_layer" if alpha else "effect_layer"
    capability_id = "ai_sound_effect" if media_kind == "audio" else "localized_inpainting"
    artifact = EffectArtifactCandidate(
        artifact_id=f"effect_artifact_{layer_kind}",
        job_id=f"effect_job_{layer_kind}",
        task_id=task_id,
        capability_id=capability_id,
        output_role=output_role,
        staging_relative_path=f"accepted/{staged.name}",
        content_digest=content_digest,
        media_kind=media_kind,
    )
    task_report = EffectTaskExecutionReport(
        task_id=task_id,
        job_id=artifact.job_id,
        capability_id=capability_id,
        adapter_id="manual_effect_import",
        status="ready_for_review",
        artifact=artifact,
        acceptance_checks=(
            EffectAcceptanceCheck(
                dimension="technical_compliance",
                message="Explicit human review remains required.",
            ),
        ),
        fillback_status="human_acceptance_required",
        message="Validated artifact awaits a human decision.",
    )
    binding = EffectExecutionBinding(
        project_id=snapshot.project_id,
        confirmation_id="effect_confirmation_fillback",
        effect_plan_id="effect_plan_fillback",
        effect_plan_version=1,
        effect_plan_digest="sha256:" + "1" * 64,
        review_id="effect_review_fillback",
        review_digest="sha256:" + "2" * 64,
        snapshot_digest=snapshot.timeline_digest,
        snapshot_revision=snapshot.revision,
        adapter_registry_id="vistora_effect_capabilities",
        adapter_registry_revision=1,
        adapter_registry_digest="sha256:" + "3" * 64,
    )
    report = EffectExecutionReport(
        execution_request_id=f"effect_execution_{layer_kind}",
        request_digest="sha256:" + "4" * 64,
        binding=binding,
        status="awaiting_human_review",
        tasks=(task_report,),
        provider_calls_are_test_only=True,
        message="One isolated artifact awaits explicit human review.",
    )
    catalog = MaterialCatalogStore.for_project_file(project_file)
    material_id = {
        "standard_clip": "source_1111111111111111",
        "transparent_layer": "source_2222222222222222",
        "effect_layer": "source_3333333333333333",
    }[layer_kind]
    entry = MaterialCatalogEntry(
        material_id=material_id,
        display_name=f"Accepted {layer_kind}",
        media_kind=media_kind,
        managed_relative_path=f"effects/{material_id}{suffix}",
        artifact_sha256=content_digest,
        size_bytes=staged.stat().st_size,
        mime_type=facts["mime"],
        container="wav" if media_kind == "audio" else "png",
        audio_codec="pcm_s16le" if media_kind == "audio" else None,
        duration_seconds=facts["duration"],
        width=facts["width"],
        height=facts["height"],
        has_audio=facts["has_audio"],
        requirements_plan_id="material_requirements_effect",
        requirement_item_id="material_need_effect",
        production_plan_id="effect_plan_fillback",
        production_task_id=task_id,
        production_run_id="effect_execution_fillback",
        production_job_id=artifact.job_id,
        adapter_id="manual_effect_import",
        origin_kind="generated",
        license_status="unknown",
        usage_restrictions=("Verify provider rights before publishing.",),
        cost_status="unknown",
        quality_validation_id="effect_quality_fillback",
        accepted_decision_id=f"effect_acceptance_{layer_kind}",
        registered_at=NOW,
    )
    catalog.register(catalog.load(project_id=snapshot.project_id), entry=entry, staged_path=staged)
    acceptance = EffectArtifactAcceptance.create(
        acceptance_id=entry.accepted_decision_id,
        report=report,
        task_id=task_id,
        catalog_entry=entry,
        accepted_by="local_user",
        accepted_at=NOW,
        alpha_channel_verified=alpha,
    )
    track_id = "track_audio_primary" if media_kind == "audio" else "track_video_effects"
    placement = EffectFillbackPlacement(
        placement_id=f"operation_fillback_{layer_kind}",
        acceptance_id=acceptance.acceptance_id,
        layer_kind=layer_kind,
        track_id=track_id,
        clip_id=f"clip_fillback_{layer_kind}",
        timeline_start_seconds=0,
        duration_seconds=1,
        mode="insert",
    )
    compiler = EffectFillbackCompiler(catalog=catalog, registry=vistora_main.SKILLS)
    bundle = compiler.compile(
        bundle_id=f"fillback_bundle_{layer_kind}",
        plan_id=f"director_plan_fillback_{layer_kind}",
        plan_version=1,
        proposal_execution_id=f"proposal_execution_fillback_{layer_kind}",
        review_request_id=f"review_request_fillback_{layer_kind}",
        acceptance=acceptance,
        placement=placement,
        execution_report=report,
        objective=f"Return the accepted {layer_kind} to the unified timeline.",
        rationale="Use the exact accepted packaging artifact and no substitute.",
        expected_effect=f"Create one {layer_kind} entity on the exact target track.",
        created_at=NOW,
    )
    return project_file, snapshot, catalog, report, acceptance, placement, bundle


@pytest.mark.parametrize("layer_kind", ["standard_clip", "transparent_layer", "effect_layer"])
def test_fillback_compiles_all_three_standard_entity_kinds_without_mutation(monkeypatch, tmp_path, layer_kind):
    project_file, snapshot, _, _, _, _, bundle = _setup(monkeypatch, tmp_path, layer_kind=layer_kind)
    before = project_file.read_bytes()
    diff = PlanDiffEngine.generate(bundle.review_request, snapshot, vistora_main.SKILLS)
    assert diff.summary.additions == 1
    assert diff.review_status in {"ready", "warning"}
    assert project_file.read_bytes() == before
    assert bundle.compilation_digest == type(bundle).model_validate_json(bundle.model_dump_json()).compilation_digest
    assert "material://source_" in bundle.director_plan.model_dump_json()
    assert str(tmp_path) not in bundle.model_dump_json()


def test_fillback_requires_exact_report_catalog_alpha_and_unlocked_track(monkeypatch, tmp_path):
    _, _, catalog, report, acceptance, placement, _ = _setup(monkeypatch, tmp_path)
    compiler = EffectFillbackCompiler(catalog=catalog, registry=vistora_main.SKILLS)
    with pytest.raises(EffectFillbackError, match="stale or tampered"):
        compiler.compile(
            bundle_id="fillback_bundle_stale",
            plan_id="director_plan_stale",
            plan_version=1,
            proposal_execution_id="proposal_execution_stale",
            review_request_id="review_request_stale",
            acceptance=acceptance.model_copy(update={"execution_report_digest": "sha256:" + "9" * 64}),
            placement=placement,
            execution_report=report,
            objective="Rejected stale fillback.",
            rationale="Fail closed.",
            expected_effect="No change.",
            created_at=NOW,
        )
    with pytest.raises(ValidationError, match="digest mismatched"):
        EffectArtifactAcceptance.model_validate(
            {**acceptance.model_dump(), "alpha_channel_verified": False}
        )


def test_fillback_runs_only_after_workflow_confirmation_and_rolls_back(monkeypatch, tmp_path):
    project_file, initial, _, _, acceptance, _, bundle = _setup(monkeypatch, tmp_path)
    before = project_file.read_bytes()
    deterministic = Deterministic()
    workflow = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file),
        registry=vistora_main.SKILLS,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    review = workflow.record_review(bundle.review_request)
    assert project_file.read_bytes() == before
    with pytest.raises(WorkflowApplicationError):
        workflow.run_confirmed_execution(acceptance.acceptance_id)
    confirmation = workflow.confirm_review(
        review.review_id,
        confirmed_by="local_user",
        decision="confirmed",
    )
    assert project_file.read_bytes() == before
    editing = EditingAgent(
        workflow,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = editing.prepare_execution(
        request_id="editing_request_effect_fillback",
        confirmation_record_id=confirmation.confirmation_record_id,
    )
    report = editing.execute(request)
    assert report.status == "succeeded"
    snapshot = TimelineSnapshotService.snapshot_current()
    effects = next(track for track in snapshot.tracks if track.track_id == "track_video_effects")
    assert [clip.clip_id for clip in effects.clips] == ["clip_fillback_transparent_layer"]
    assert effects.clips[0].visual_kind == "sticker"
    trace = TraceabilityStore.load(project_file)
    relations = trace.confirmed_traces[-1].relations
    assert any(
        relation.relation_type == "creates"
        and relation.entity.entity_id == "clip_fillback_transparent_layer"
        and relation.evidence_ids == (f"evidence_effect_{acceptance.acceptance_id}",)
        for relation in relations
    )
    rollback_review = workflow.propose_rollback(report.run_id)
    rollback_confirmation = workflow.confirm_rollback(
        rollback_review.review_id,
        confirmed_by="local_user",
        decision="confirmed",
    )
    rollback = workflow.apply_rollback(rollback_confirmation.confirmation_id)
    assert rollback.status == "succeeded"
    restored = TimelineSnapshotService.snapshot_current()
    assert restored.timeline_digest == initial.timeline_digest
