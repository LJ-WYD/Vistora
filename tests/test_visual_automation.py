"""STEP 23 deterministic visual keyframe and animation regression."""

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
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualVisualAutomationEdit,
    PlanReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipConfig,
    TimelineConfig,
    TimelineRenderer,
    TimelineTransition,
    TrackConfig,
    TransitionParameters,
    VisualAutomation,
    VisualKeyframe,
)
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_edit import TimelineEditEngine, TimelineEditError, TimelineEditTransaction  # noqa: E402
from timeline_preview.manual_edits import ManualEditApplicationService  # noqa: E402
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from visual_automation.models import automation_digest  # noqa: E402
from visual_automation.runtime import evaluate_curve, ffmpeg_property_expressions  # noqa: E402


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _point(identity: str, time: float, value: float, interpolation: str = "linear") -> VisualKeyframe:
    return VisualKeyframe(
        keyframe_id=identity,
        offset_seconds=time,
        value=value,
        interpolation=interpolation,
    )


def _curve(
    identity: str,
    clip_id: str,
    property_path: str,
    values: tuple[tuple[str, float, float, str], ...],
) -> VisualAutomation:
    return VisualAutomation(
        automation_id=identity,
        clip_id=clip_id,
        property_path=property_path,
        keyframes=tuple(_point(*item) for item in values),
    )


def _timeline(*, locked: bool = False, source: str = "source.mp4") -> TimelineConfig:
    curve = _curve(
        "automation_position",
        "clip_main",
        "transform.position_x",
        (
            ("keyframe_position_a", 0.0, 0.2, "ease_in_out"),
            ("keyframe_position_b", 2.0, 0.8, "linear"),
        ),
    )
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
                clips=[
                    ClipConfig(
                        id="clip_main",
                        source=source,
                        trim_out=2,
                        visual_automations=(curve,),
                    ),
                    ClipConfig(
                        id="clip_target",
                        source=source,
                        trim_out=2,
                        timeline_start=2,
                    ),
                ],
            ),
            "audio": TrackConfig(id="track_audio", kind="audio", order=1),
        },
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("hold", 0.0),
        ("linear", 0.5),
        ("ease_in", 0.25),
        ("ease_out", 0.75),
        ("ease_in_out", 0.5),
    ),
)
def test_frozen_curve_schema_and_fixed_interpolation(kind: str, expected: float) -> None:
    curve = _curve(
        f"automation_{kind}",
        "clip_main",
        "transform.opacity",
        (
            (f"keyframe_{kind}_a", 0, 0, kind),
            (f"keyframe_{kind}_b", 2, 1, "linear"),
        ),
    )
    assert evaluate_curve(curve, 1, 0.4) == pytest.approx(expected)
    assert evaluate_curve(curve, -0.1, 0.4) == pytest.approx(0.4)
    assert VisualAutomation.model_validate_json(curve.model_dump_json()) == curve
    with pytest.raises(ValidationError):
        curve.enabled = False
    with pytest.raises(ValidationError):
        VisualAutomation(
            automation_id="automation_bad",
            clip_id="clip_main",
            property_path="transform.opacity",
            keyframes=(
                _point("keyframe_bad_a", 1, 0.2),
                _point("keyframe_bad_b", 1, 0.8),
            ),
        )
    with pytest.raises(ValidationError):
        _curve(
            "automation_injection",
            "clip_main",
            "transform.raw_filter",  # type: ignore[arg-type]
            (("keyframe_injection", 0, 1, "linear"),),
        )


def test_snapshot_is_detached_versioned_and_digest_bound() -> None:
    timeline = _timeline(source="source.mp4")
    first = TimelineSnapshotService.snapshot(timeline)
    second = TimelineSnapshotService.snapshot(timeline)
    clip = first.tracks[0].clips[0]
    assert first == second and first.schema_version == "8.0.0"
    assert clip.visual_automations[0].property_path == "transform.position_x"
    assert clip.automation_digest == automation_digest(
        timeline.tracks["video"].clips[0].visual_automations
    )
    timeline.tracks["video"].clips[0].visual_automations = ()
    assert clip.visual_automations


def test_engine_crud_copy_lock_and_animated_crop_validation() -> None:
    engine = TimelineEditEngine(_timeline())
    updated, outcome = engine.upsert_visual_keyframe(
        "track_video_main",
        "clip_main",
        automation_id="automation_position",
        property_path="transform.position_x",
        keyframe=_point("keyframe_position_mid", 1, 0.5, "ease_out"),
    )
    assert outcome.modified_automation_ids == ("automation_position",)
    updated, outcome = engine.copy_visual_automation(
        "track_video_main",
        "clip_main",
        (("track_video_main", "clip_target"),),
        property_paths=("transform.position_x",),
    )
    copied = updated.tracks["video"].clips[1].visual_automations[0]
    assert copied.clip_id == "clip_target"
    assert copied.automation_id.startswith("automation_")
    assert outcome.created_automation_ids == (copied.automation_id,)
    updated, outcome = engine.clear_visual_automation(
        "track_video_main",
        "clip_target",
        automation_id=copied.automation_id,
        property_path=None,
        clear_all=False,
    )
    assert outcome.deleted_automation_ids == (copied.automation_id,)
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(_timeline(locked=True)).upsert_visual_keyframe(
            "track_video_main", "clip_main",
            automation_id="automation_position",
            property_path="transform.position_x",
            keyframe=_point("keyframe_locked", 1, 0.4),
        )
    bad = _timeline()
    bad.tracks["video"].clips[0].visual_automations = tuple(sorted((
        _curve("automation_crop_left", "clip_main", "transform.crop_left", (("keyframe_crop_left", 1, 0.7, "linear"),)),
        _curve("automation_crop_right", "clip_main", "transform.crop_right", (("keyframe_crop_right", 1, 0.4, "linear"),)),
    ), key=lambda item: item.property_path))
    with pytest.raises(TimelineEditError, match="retain"):
        TimelineEditEngine(bad)


def test_structural_split_trim_speed_move_ripple_remove_preserves_truth() -> None:
    counter = iter(range(100))
    engine = TimelineEditEngine(
        _timeline(), id_factory=lambda prefix: f"{prefix}_{next(counter):03d}"
    )
    updated, split = engine.split(
        "track_video_main", "clip_main", 1, right_clip_id="clip_right"
    )
    left, right, target = updated.tracks["video"].clips
    assert left.visual_automations[0].keyframes[-1].offset_seconds == 1
    assert right.visual_automations[0].keyframes[0].offset_seconds == 0
    assert right.visual_automations[0].keyframes[0].value == pytest.approx(0.5)
    assert split.created_automation_ids
    moved_curve = right.visual_automations
    engine.move("track_video_main", "clip_right", 1.25, ripple=False)
    assert right.visual_automations == moved_curve
    old_end = right.visual_automations[0].keyframes[-1].offset_seconds
    engine.set_properties(
        "track_video_main", "clip_right",
        speed_factor=2, volume=None, keep_audio=None, mute=None, rotate=None,
    )
    assert right.visual_automations[0].keyframes[-1].offset_seconds == pytest.approx(old_end / 2)
    before_move = target.visual_automations
    engine.move("track_video_main", "clip_target", 3, ripple=True)
    assert target.visual_automations == before_move
    _, removed = engine.remove(
        "track_video_main", "clip_right", ripple=False
    )
    assert removed.deleted_automation_ids


def test_plan_review_is_deterministic_detached_and_registry_bound() -> None:
    timeline = _timeline(source="material://source_1111111111111111")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    operation = DirectorOperation(
        operation_id="operation_keyframe_review",
        tool_name="VideoUpsertVisualKeyframeSkill",
        arguments={
            "track_id": "track_video_main",
            "clip_id": "clip_main",
            "automation_id": "automation_position",
            "property_path": "transform.position_x",
            "keyframe": _point("keyframe_review", 1, 0.6, "ease_in").model_dump(mode="json"),
        },
        rationale="Animate a controlled reframe.",
        expected_effect="Add one seek-safe keyframe.",
    )
    plan = DirectorPlan(
        plan_id="plan_keyframe_review",
        plan_version=1,
        objective="Review a deterministic keyframe edit.",
        operations=(operation,),
        created_at=NOW,
    )
    execution = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_keyframe_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="request_keyframe_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=execution,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = timeline.model_dump_json()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second
    assert first.changes[0].category == "visual_automation"
    assert timeline.model_dump_json() == before


def test_gateway_confirmation_replay_and_transaction_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    registry = build_production_registry()
    request = AtomicToolRequestEnvelope(
        request_id="request_keyframe_gateway",
        execution_id="execution_keyframe_gateway",
        project_id="project_current",
        confirmation_id="confirmation_keyframe_gateway",
        plan_ref=PlanReference(
            plan_id="plan_keyframe_gateway",
            plan_version=1,
            plan_digest="sha256:" + "d" * 64,
        ),
        step_id="step_keyframe_gateway",
        tool_name="VideoUpsertVisualKeyframeSkill",
        arguments={
            "track_id": "track_video_main",
            "clip_id": "clip_main",
            "automation_id": "automation_position",
            "property_path": "transform.position_x",
            "keyframe": _point("keyframe_gateway", 1, 0.7).model_dump(mode="json"),
        },
        requested_at=NOW,
    )
    gateway = AtomicExecutionGateway(registry)
    before = project.read_bytes()
    rejected = gateway.execute(request, AtomicExecutionContext(
        caller="workflow", registry_ref=registry.reference,
        project_id="project_current", confirmation_id="wrong_confirmation",
        allowed_side_effects=("files", "timeline"), idempotency_key="reject_keyframe",
    ))
    assert rejected.status == "error" and project.read_bytes() == before
    context = AtomicExecutionContext(
        caller="workflow", registry_ref=registry.reference,
        project_id="project_current", confirmation_id="confirmation_keyframe_gateway",
        allowed_side_effects=("files", "timeline"), idempotency_key="apply_keyframe",
    )
    result = gateway.execute(request, context)
    assert result.status == "success"
    assert gateway.execute(request, context).replayed
    original = TimelineEditTransaction.replace_config

    def fail(updated: TimelineConfig) -> None:
        original(updated)
        raise OSError("simulated automation persistence failure")

    exact = project.read_bytes()
    monkeypatch.setattr(TimelineEditTransaction, "replace_config", fail)
    with pytest.raises(OSError, match="automation persistence"):
        TimelineEditTransaction.apply(
            lambda engine: engine.clear_visual_automation(
                "track_video_main", "clip_main",
                automation_id="automation_position", property_path=None,
                clear_all=False,
            )
        )
    assert project.read_bytes() == exact


def test_manual_draft_requires_confirmation_and_records_automation_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="proposal_manual_keyframe",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        created_at=NOW,
        edits=(ManualVisualAutomationEdit(
            operation_id="manual_keyframe_upsert",
            action="upsert_keyframe",
            track_key="video",
            track_id="track_video_main",
            clip_id="clip_main",
            automation_id="automation_position",
            property_path="transform.position_x",
            keyframe=_point("keyframe_manual", 1, 0.65),
        ),),
    )
    service = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        build_production_registry(),
    )
    before = project.read_bytes()
    _, review = service.review(proposal.model_dump(mode="json"))
    assert review.changes[0].target_kind == "automation"
    assert project.read_bytes() == before
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="confirmation_manual_keyframe",
        proposal=proposal,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    service.apply(
        proposal.model_dump(mode="json"), confirmation.model_dump(mode="json")
    )
    assert TraceabilityStore.trace_path(project).exists()
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert len(saved.tracks["video"].clips[0].visual_automations[0].keyframes) == 3


def test_browser_assets_expose_confirmed_keyframe_controls_and_mobile_layout() -> None:
    static = ROOT / "src" / "timeline_preview" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    styles = (static / "app.css").read_text(encoding="utf-8")
    for identity in (
        "automation-property",
        "automation-time",
        "automation-value",
        "automation-interpolation",
        "previous-keyframe",
        "next-keyframe",
        "stage-keyframe",
        "delete-keyframe",
        "clear-automation",
        "copy-automation",
    ):
        assert f'id="{identity}"' in html
    assert 'action: "upsert_keyframe"' in script
    assert 'action: "delete_keyframe"' in script
    assert 'action: "clear_curve"' in script
    assert 'action: "copy"' in script
    assert "visual-keyframe-marker" in script
    assert ".visual-keyframe-marker" in styles
    assert "@media (max-width: 420px)" in styles
    combined = html + script + styles
    assert "file://" not in combined
    assert "C:\\" not in combined


def _frame(path: Path, time: float) -> bytes:
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


def test_real_keyframe_render_changes_fixed_frames_and_is_seek_safe(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "animated.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=160x120:r=24:d=2",
            "-vf", "drawbox=x=10:y=30:w=35:h=35:color=white:t=fill",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
        timeout=60,
    )
    curves = tuple(sorted((
        _curve("automation_position_render", "clip_render", "transform.position_x", (("keyframe_position_render_a", 0, 0.2, "ease_in_out"), ("keyframe_position_render_b", 2, 0.8, "linear"))),
        _curve("automation_rotation_render", "clip_render", "transform.rotation_degrees", (("keyframe_rotation_render_a", 0, 0, "linear"), ("keyframe_rotation_render_b", 2, 35, "linear"))),
        _curve("automation_opacity_render", "clip_render", "transform.opacity", (("keyframe_opacity_render_a", 0, 1, "linear"), ("keyframe_opacity_render_b", 2, 0.45, "linear"))),
        _curve("automation_crop_render", "clip_render", "transform.crop_left", (("keyframe_crop_render_a", 0, 0, "linear"), ("keyframe_crop_render_b", 2, 0.25, "linear"))),
        _curve("automation_exposure_render", "clip_render", "color.exposure", (("keyframe_exposure_render_a", 0, -0.5, "ease_out"), ("keyframe_exposure_render_b", 2, 0.8, "linear"))),
        _curve("automation_saturation_render", "clip_render", "color.saturation", (("keyframe_saturation_render_a", 0, -0.5, "linear"), ("keyframe_saturation_render_b", 2, 1.0, "linear"))),
        _curve("automation_temperature_render", "clip_render", "color.temperature", (("keyframe_temperature_render_a", 0, -0.5, "linear"), ("keyframe_temperature_render_b", 2, 0.5, "linear"))),
        _curve("automation_tint_render", "clip_render", "color.tint", (("keyframe_tint_render_a", 0, -0.3, "linear"), ("keyframe_tint_render_b", 2, 0.3, "linear"))),
        _curve("automation_gamma_render", "clip_render", "color.gamma", (("keyframe_gamma_render_a", 0, 0.8, "linear"), ("keyframe_gamma_render_b", 2, 1.4, "linear"))),
    ), key=lambda item: item.property_path))
    timeline = TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={"video": TrackConfig(
            id="track_video_render", kind="video", order=0,
            clips=[ClipConfig(
                id="clip_render", source=str(source), trim_out=2,
                keep_audio=False, visual_automations=curves,
            )],
        )},
    )
    expressions = ffmpeg_property_expressions(timeline.tracks["video"].clips[0])
    assert "between" in expressions["transform.position_x"]
    TimelineRenderer(timeline).render(str(output))
    early, middle, late = (_frame(output, time) for time in (0.1, 1.0, 1.85))
    assert len(early) == len(middle) == len(late) == 320 * 180 * 3
    assert sum(abs(a - b) for a, b in zip(early, middle)) > 100_000
    assert sum(abs(a - b) for a, b in zip(middle, late)) > 100_000
    assert _frame(output, 1.0) == middle
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout)
    video = next(item for item in probe["streams"] if item["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (320, 180, "24/1")
    assert 1.9 <= float(probe["format"]["duration"]) <= 2.1


def test_transition_interval_uses_clip_local_automation_time(tmp_path: Path) -> None:
    source_a = tmp_path / "a.mp4"
    source_b = tmp_path / "b.mp4"
    output = tmp_path / "transition-animation.mp4"
    for path, color in ((source_a, "red"), (source_b, "blue")):
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=160x120:r=24:d=3", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
            check=True, timeout=60,
        )
    curve = _curve(
        "automation_transition_position", "clip_transition_a",
        "transform.position_x",
        (("keyframe_transition_a", 0, 0.25, "linear"), ("keyframe_transition_b", 1, 0.75, "linear")),
    )
    timeline = TimelineConfig(
        width=320, height=180, fps=24,
        tracks={"video": TrackConfig(
            id="track_video_transition", kind="video", role="primary", order=0,
            clips=[
                ClipConfig(id="clip_transition_a", source=str(source_a), trim_in=0.5, trim_out=1.5, visual_automations=(curve,)),
                ClipConfig(id="clip_transition_b", source=str(source_b), trim_in=0.5, trim_out=1.5, timeline_start=1),
            ],
        )},
        transitions={"transition_animation": TimelineTransition(
            transition_id="transition_animation", track_id="track_video_transition",
            from_clip_id="clip_transition_a", to_clip_id="clip_transition_b",
            kind="cross_dissolve", duration_seconds=0.4,
            parameters=TransitionParameters(),
        )},
    )
    TimelineRenderer(timeline).render(str(output))
    assert _frame(output, 0.75) != _frame(output, 1.05)
