"""STEP 21 deterministic visual transform and color regression."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from atomic_runtime import AtomicExecutionContext, AtomicExecutionGateway, build_production_registry  # noqa: E402
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    DirectorOperation,
    DirectorPlan,
    ManualClipVisual,
    ManualCopyClipVisual,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    PlanReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipColorAdjustment,
    ClipConfig,
    ClipTransform,
    TimelineConfig,
    TimelineRenderer,
    TrackConfig,
)
from media_analysis import MediaAnalysisRequest, MediaAnalysisService  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_edit import TimelineEditEngine, TimelineEditError, TimelineEditTransaction  # noqa: E402
from timeline_edit import ClipReference  # noqa: E402
from timeline_preview.manual_edits import ManualEditApplicationService  # noqa: E402
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from visuals import CopyClipVisualInput, SetClipColorInput, SetClipTransformInput, visual_digest  # noqa: E402


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _timeline(source: str = "source.mp4", *, locked: bool = False) -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="track_video_main",
                kind="video",
                order=0,
                locked=locked,
                clips=[ClipConfig(id="clip_main", source=source, trim_out=2)],
            ),
            "overlay": TrackConfig(
                id="track_video_overlay",
                kind="video",
                order=1,
                clips=[ClipConfig(id="clip_overlay", source=source, trim_out=2)],
            ),
            "audio": TrackConfig(id="track_audio", kind="audio", order=2),
        },
    )


def _frame(path: Path, time: float = 0.5) -> bytes:
    return subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-ss", str(time),
            "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def test_visual_contracts_are_frozen_bounded_and_digest_stable() -> None:
    transform = ClipTransform(
        position_x=0.25,
        position_y=0.75,
        scale_x=1.2,
        scale_y=0.8,
        crop_left=0.1,
        fit="fill",
        flip_horizontal=True,
    )
    color = ClipColorAdjustment(
        exposure=0.5,
        contrast=0.2,
        saturation=-0.25,
        temperature=0.4,
        tint=-0.2,
        highlights=0.3,
        shadows=-0.1,
        gamma=1.1,
        sharpen=0.2,
    )
    assert visual_digest(transform, color) == visual_digest(transform, color)
    with pytest.raises(ValidationError):
        transform.opacity = 0.5
    with pytest.raises(ValidationError):
        ClipTransform(crop_left=0.6, crop_right=0.4)
    with pytest.raises(ValidationError):
        ClipTransform(position_x=float("nan"))
    with pytest.raises(ValidationError):
        ClipColorAdjustment(sharpen=0.1, blur=0.1)
    with pytest.raises(ValidationError):
        SetClipTransformInput(
            track_id="track_video_main",
            clip_id="clip_main",
            action="reset",
            transform=transform,
        )
    CopyClipVisualInput(
        source_track_id="track_video_main",
        source_clip_id="clip_main",
        targets=(ClipReference(
            track_id="track_video_overlay",
            clip_id="clip_overlay",
        ),),
    )


def test_visual_engine_exact_clip_reset_copy_and_lock_boundaries() -> None:
    transform = ClipTransform(position_x=0.2, opacity=0.6, rotation_degrees=17)
    color = ClipColorAdjustment(exposure=0.4, temperature=0.2, blur=0.4)
    engine = TimelineEditEngine(_timeline())
    updated, outcome = engine.set_clip_transform(
        "track_video_main", "clip_main", transform=transform
    )
    assert outcome.operation == "set_clip_transform"
    assert updated.tracks["video"].clips[0].transform == transform
    updated, outcome = engine.set_clip_color(
        "track_video_main", "clip_main", color=color
    )
    assert outcome.modified_clip_ids == ("clip_main",)
    updated, outcome = engine.copy_clip_visual(
        "track_video_main",
        "clip_main",
        (("track_video_overlay", "clip_overlay"),),
        components="both",
    )
    overlay = updated.tracks["overlay"].clips[0]
    assert overlay.transform == transform and overlay.color == color
    assert updated.tracks["audio"].clips == []
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(_timeline(locked=True)).set_clip_transform(
            "track_video_main", "clip_main", transform=transform
        )
    with pytest.raises(TimelineEditError, match="video"):
        TimelineEditEngine(
            TimelineConfig(tracks={
                "audio": TrackConfig(
                    id="track_audio", kind="audio", order=0,
                    clips=[ClipConfig(id="clip_audio", source="a.wav", trim_out=1)],
                )
            })
        ).set_clip_color("track_audio", "clip_audio", color=color)


def test_registry_gateway_requires_exact_confirmation_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    registry = build_production_registry()
    assert registry.reference.registry_revision == 7 and len(registry) == 35
    request = AtomicToolRequestEnvelope(
        request_id="request_visual_gateway",
        execution_id="execution_visual_gateway",
        project_id="project_current",
        confirmation_id="confirmation_visual_gateway",
        plan_ref=PlanReference(
            plan_id="plan_visual", plan_version=1,
            plan_digest="sha256:" + "b" * 64,
        ),
        step_id="step_visual_gateway",
        tool_name="VideoSetClipTransformSkill",
        arguments={
            "track_id": "track_video_main",
            "clip_id": "clip_main",
            "action": "set",
            "transform": ClipTransform(position_x=0.3).model_dump(mode="json"),
        },
        requested_at=NOW,
    )
    gateway = AtomicExecutionGateway(registry)
    before = project.read_bytes()
    rejected = gateway.execute(request, AtomicExecutionContext(
        caller="workflow", registry_ref=registry.reference,
        project_id="project_current", confirmation_id="wrong",
        allowed_side_effects=("files", "timeline"), idempotency_key="reject_visual",
    ))
    assert rejected.status == "error" and project.read_bytes() == before
    context = AtomicExecutionContext(
        caller="workflow", registry_ref=registry.reference,
        project_id="project_current", confirmation_id="confirmation_visual_gateway",
        allowed_side_effects=("files", "timeline"), idempotency_key="apply_visual",
    )
    result = gateway.execute(request, context)
    assert result.status == "success"
    assert gateway.execute(request, context).replayed is True
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.tracks["video"].clips[0].transform.position_x == 0.3


def test_plan_review_visual_diff_is_deterministic_and_detached() -> None:
    timeline = _timeline("material://source_1111111111111111")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    operations = (
        DirectorOperation(
            operation_id="operation_visual_transform",
            tool_name="VideoSetClipTransformSkill",
            arguments={
                "track_id": "track_video_main", "clip_id": "clip_main",
                "action": "set",
                "transform": ClipTransform(position_x=0.2, scale_x=0.7).model_dump(mode="json"),
            },
            rationale="Reframe the primary subject.",
            expected_effect="Move and scale the selected visual only.",
        ),
        DirectorOperation(
            operation_id="operation_visual_color",
            tool_name="VideoSetClipColorSkill",
            arguments={
                "track_id": "track_video_main", "clip_id": "clip_main",
                "action": "set",
                "color": ClipColorAdjustment(exposure=0.3, saturation=0.4).model_dump(mode="json"),
            },
            rationale="Create a brighter, richer image.",
            expected_effect="Adjust deterministic SDR color values.",
        ),
    )
    plan = DirectorPlan(
        plan_id="plan_visual_review", plan_version=1,
        objective="Review a visual treatment.", operations=operations,
        created_at=NOW,
    )
    execution = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_visual_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="request_visual_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=execution,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = timeline.model_dump_json()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second
    assert {change.category for change in first.changes} >= {
        "clip_transform", "clip_color"
    }
    assert timeline.model_dump_json() == before


def test_manual_visual_draft_requires_confirmation_and_persists_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="proposal_manual_visual",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        created_at=NOW,
        edits=(ManualClipVisual(
            operation_id="manual_visual_set",
            track_key="video",
            track_id="track_video_main",
            clip_id="clip_main",
            components="both",
            transform=ClipTransform(position_x=0.25),
            color=ClipColorAdjustment(contrast=0.25),
        ),),
    )
    service = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        build_production_registry(),
    )
    before = project.read_bytes()
    _, review = service.review(proposal.model_dump(mode="json"))
    assert review.changes[0].before["visual_digest"] != review.changes[0].after["visual_digest"]
    assert project.read_bytes() == before
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="confirmation_manual_visual",
        proposal=proposal,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    result = service.apply(
        proposal.model_dump(mode="json"),
        confirmation.model_dump(mode="json"),
    )
    assert result["tool_name"] == "VideoApplyManualEditsSkill"
    assert TraceabilityStore.trace_path(project).exists()
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.tracks["video"].clips[0].color.contrast == 0.25


def test_visual_transaction_failure_restores_exact_project_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    before = project.read_bytes()
    original = TimelineEditTransaction.replace_config

    def fail_after_write(updated: TimelineConfig) -> None:
        original(updated)
        raise OSError("simulated visual persistence failure")

    monkeypatch.setattr(TimelineEditTransaction, "replace_config", fail_after_write)
    with pytest.raises(OSError, match="visual persistence"):
        TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_color(
                "track_video_main",
                "clip_main",
                color=ClipColorAdjustment(exposure=0.5),
            )
        )
    assert project.read_bytes() == before
    assert not list(project.parent.glob(".*.tmp"))


def test_applied_thumbnail_cache_binds_visual_digest(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"visual-source")
    commands: list[list[str]] = []

    def runner(command: list[str], timeout: float) -> bytes:
        commands.append(command)
        return b"\x89PNG\r\n\x1a\nframe"

    service = MediaAnalysisService(command_runner=runner)
    transform = ClipTransform(position_x=0.25)
    color = ClipColorAdjustment(exposure=0.2)
    request = MediaAnalysisRequest(
        snapshot_id="snapshot_visual",
        source_id="source_0123456789abcdef",
        clip_id="clip_visual",
        track_key="video",
        media_kind="video",
        source_start_seconds=0,
        source_end_seconds=1,
        timeline_start_seconds=0,
        timeline_end_seconds=1,
        preview_mode="applied",
        visual_digest=visual_digest(transform, color),
        canvas_width=320,
        canvas_height=180,
        transform=transform,
        color=color,
    )
    first = service.analyze(request, source, "video/mp4")
    second = service.analyze(request, source, "video/mp4")
    assert first == second and service.cache_hits == 1
    assert "-filter_complex" in commands[0]
    drifted = request.model_copy(update={
        "transform": ClipTransform(position_x=0.75),
        "visual_digest": visual_digest(ClipTransform(position_x=0.75), color),
    })
    assert service.analyze(drifted, source, "video/mp4") != first
    assert service.cache_misses == 2


def test_real_transform_color_render_changes_pixels_and_neutral_is_equivalent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    neutral = tmp_path / "neutral.mp4"
    treated = tmp_path / "treated.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=2",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
        timeout=60,
    )
    baseline = TimelineConfig(
        width=320, height=180, fps=24,
        tracks={"video": TrackConfig(
            id="track_video", kind="video", order=0,
            clips=[ClipConfig(id="clip_video", source=str(source), trim_out=2, keep_audio=False)],
        )},
    )
    explicit_neutral = baseline.model_copy(deep=True)
    explicit_neutral.tracks["video"].clips[0].transform = ClipTransform()
    explicit_neutral.tracks["video"].clips[0].color = ClipColorAdjustment()
    TimelineRenderer(explicit_neutral).render(str(neutral))
    treatment = baseline.model_copy(deep=True)
    treatment.tracks["video"].clips[0].transform = ClipTransform(
        position_x=0.3,
        position_y=0.6,
        scale_x=0.65,
        scale_y=0.8,
        rotation_degrees=12,
        opacity=0.8,
        crop_left=0.08,
        crop_top=0.05,
        fit="contain",
        flip_horizontal=True,
    )
    treatment.tracks["video"].clips[0].color = ClipColorAdjustment(
        exposure=0.25,
        contrast=0.2,
        saturation=0.35,
        temperature=0.2,
        tint=-0.1,
        highlights=0.15,
        shadows=-0.1,
        gamma=1.1,
        sharpen=0.2,
    )
    TimelineRenderer(treatment).render(str(treated))
    source_frame = _frame(source)
    neutral_frame = _frame(neutral)
    treated_frame = _frame(treated)
    assert len(source_frame) == len(neutral_frame) == len(treated_frame)
    neutral_difference = sum(
        abs(left - right) for left, right in zip(source_frame, neutral_frame)
    ) / len(source_frame)
    treated_difference = sum(
        abs(left - right) for left, right in zip(neutral_frame, treated_frame)
    )
    assert neutral_difference < 3
    assert treated_difference > 500_000
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(treated)],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout)
    video = next(item for item in probe["streams"] if item["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (320, 180, "24/1")
    assert 1.9 <= float(probe["format"]["duration"]) <= 2.1
