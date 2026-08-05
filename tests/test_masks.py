"""Original O16 deterministic mask and bounded compositing regression."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atomic_runtime import (  # noqa: E402
    AtomicExecutionContext,
    AtomicExecutionGateway,
    build_production_registry,
)
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    DirectorOperation,
    DirectorPlan,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualMaskEdit,
    PlanReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipConfig,
    ClipCompositeSettings,
    ClipMask,
    MaskAutomation,
    MaskPoint,
    TimelineConfig,
    TimelineRenderer,
    TrackConfig,
    VisualKeyframe,
)
from masks import mask_alpha_expression  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_edit import (  # noqa: E402
    TimelineEditEngine,
    TimelineEditError,
    TimelineEditTransaction,
)
from timeline_preview.manual_edits import ManualEditApplicationService  # noqa: E402
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.store import TraceabilityStore  # noqa: E402


NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _point(identity: str, time: float, value: float, interpolation: str = "linear") -> VisualKeyframe:
    return VisualKeyframe(
        keyframe_id=identity,
        offset_seconds=time,
        value=value,
        interpolation=interpolation,
    )


def _mask(identity: str = "mask_main", *, invert: bool = False, feather: float = 0.02) -> ClipMask:
    curve = MaskAutomation(
        automation_id=f"maskauto_{identity}",
        mask_id=identity,
        property_path="opacity",
        keyframes=(
            _point(f"maskkey_{identity}_a", 0, 1, "ease_in_out"),
            _point(f"maskkey_{identity}_b", 2, 0.65),
        ),
    )
    return ClipMask(
        mask_id=identity,
        kind="rectangle",
        width=0.55,
        height=0.55,
        feather=feather,
        invert=invert,
        automations=(curve,),
    )


def _timeline(*, locked: bool = False, source: str = "source.mp4") -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="track_video",
                kind="video",
                order=0,
                locked=locked,
                clips=[
                    ClipConfig(id="clip_main", source=source, trim_out=2, masks=(_mask(),)),
                    ClipConfig(id="clip_target", source=source, trim_out=2, timeline_start=2),
                ],
            ),
            "audio": TrackConfig(id="track_audio", kind="audio", order=1),
        },
    )


def test_mask_contracts_are_frozen_strict_and_deterministic() -> None:
    rectangle = _mask()
    ellipse = ClipMask(mask_id="mask_ellipse", kind="ellipse", width=.4, height=.7)
    polygon = ClipMask(
        mask_id="mask_polygon",
        kind="polygon",
        points=(
            MaskPoint(point_id="point_a", x=-.3, y=-.2),
            MaskPoint(point_id="point_b", x=.3, y=-.2),
            MaskPoint(point_id="point_c", x=0, y=.3),
        ),
    )
    assert ClipMask.model_validate_json(rectangle.model_dump_json()) == rectangle
    assert mask_alpha_expression((rectangle, ellipse, polygon)) == mask_alpha_expression((rectangle, ellipse, polygon))
    with pytest.raises(ValidationError):
        rectangle.opacity = .5
    with pytest.raises(ValidationError):
        ClipMask(mask_id="mask_bad", kind="rectangle", width=.5, height=.5, points=(MaskPoint(point_id="point_bad", x=0, y=0),))
    with pytest.raises(ValidationError):
        ClipMask(
            mask_id="mask_concave",
            kind="polygon",
            points=(
                MaskPoint(point_id="point_1", x=0, y=0),
                MaskPoint(point_id="point_2", x=1, y=0),
                MaskPoint(point_id="point_3", x=.2, y=.2),
                MaskPoint(point_id="point_4", x=0, y=1),
            ),
        )


def test_snapshot_v7_is_detached_and_browser_safe() -> None:
    timeline = _timeline(source="C:/private/secret/source.mp4")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    clip = snapshot.tracks[0].clips[0]
    assert snapshot.schema_version == "11.0.0"
    assert clip.masks[0].mask_id == "mask_main"
    assert clip.masks[0].automations[0].keyframes[1].value == .65
    assert clip.composite.blend_mode == "normal"
    assert clip.mask_digest.startswith("sha256:")
    timeline.tracks["video"].clips[0].masks = ()
    assert clip.masks
    browser_payload = json.dumps(clip.model_dump(mode="json", exclude={"source"}))
    assert "C:/private" not in browser_payload


def test_engine_mask_crud_copy_split_trim_and_lock() -> None:
    engine = TimelineEditEngine(_timeline())
    updated, outcome = engine.set_clip_mask(
        "track_video",
        "clip_main",
        mask=ClipMask(mask_id="mask_ellipse", kind="ellipse", width=.3, height=.4),
    )
    assert outcome.created_mask_ids == ("mask_ellipse",)
    updated, outcome = engine.copy_clip_masks(
        "track_video", "clip_main", (("track_video", "clip_target"),), mask_ids=("mask_main",)
    )
    copied = updated.tracks["video"].clips[1].masks[0]
    assert copied.mask_id != "mask_main" and copied.automations[0].mask_id == copied.mask_id
    identities = count(1)
    split_engine = TimelineEditEngine(
        _timeline(),
        id_factory=lambda prefix: f"{prefix}_deterministic_{next(identities)}",
    )
    split, split_outcome = split_engine.split("track_video", "clip_main", 1, right_clip_id="clip_right")
    left, right = split.tracks["video"].clips[:2]
    assert left.masks[0].mask_id == "mask_main"
    assert right.masks[0].mask_id.startswith("mask_deterministic_")
    assert right.masks[0].automations[0].keyframes[0].offset_seconds == 0
    assert split_outcome.created_mask_ids == (right.masks[0].mask_id,)
    trimmed, trim_outcome = TimelineEditEngine(_timeline()).trim(
        "track_video", "clip_main", .25, 1.75, ripple=False
    )
    curve = trimmed.tracks["video"].clips[0].masks[0].automations[0]
    assert curve.keyframes[0].offset_seconds == 0
    assert curve.keyframes[-1].offset_seconds == pytest.approx(1.5)
    assert trim_outcome.modified_mask_ids == ("mask_main",)
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(_timeline(locked=True)).set_clip_mask(
            "track_video", "clip_main", mask_id="mask_main"
        )


def test_registry_exposes_only_validated_mask_skills() -> None:
    registry = build_production_registry()
    assert registry.reference.registry_revision == 13
    assert len(registry) == 43
    for name in (
        "VideoSetClipMaskSkill",
        "VideoReplaceClipMasksSkill",
        "VideoCopyClipMasksSkill",
        "VideoSetClipCompositeSkill",
    ):
        descriptor = registry.descriptor(name)
        assert descriptor.preview_supported
        assert descriptor.side_effects == ("files", "timeline")
        assert descriptor.rollback_support == "checkpoint_restore"
    with pytest.raises(ValidationError):
        registry["VideoSetClipMaskSkill"].input_model.model_validate({
            "track_id": "track_video",
            "clip_id": "clip_main",
            "action": "upsert",
            "mask": {"mask_id": "mask_bad", "kind": "raw_filter"},
        })


def test_plan_review_previews_masks_deterministically_without_mutation() -> None:
    timeline = _timeline(source="material://source_1111111111111111")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    operation = DirectorOperation(
        operation_id="operation_mask_review",
        tool_name="VideoSetClipMaskSkill",
        arguments={
            "track_id": "track_video",
            "clip_id": "clip_main",
            "action": "upsert",
            "mask": ClipMask(
                mask_id="mask_review",
                kind="ellipse",
                width=.4,
                height=.6,
                feather=.03,
            ).model_dump(mode="json"),
        },
        rationale="Constrain the visible subject region.",
        expected_effect="Add one bounded, reviewable ellipse mask.",
    )
    plan = DirectorPlan(
        plan_id="plan_mask_review",
        plan_version=1,
        objective="Review a deterministic mask operation.",
        operations=(operation,),
        created_at=NOW,
    )
    execution = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_mask_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="request_mask_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=execution,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = timeline.model_dump_json()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second
    assert {change.category for change in first.changes} == {"clip_mask"}
    assert first.changes[0].effect_kind == "direct"
    assert timeline.model_dump_json() == before


def test_gateway_confirmation_replay_and_mask_transaction_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    registry = build_production_registry()
    request = AtomicToolRequestEnvelope(
        request_id="request_mask_gateway",
        execution_id="execution_mask_gateway",
        project_id="project_current",
        confirmation_id="confirmation_mask_gateway",
        plan_ref=PlanReference(
            plan_id="plan_mask_gateway",
            plan_version=1,
            plan_digest="sha256:" + "a" * 64,
        ),
        step_id="step_mask_gateway",
        tool_name="VideoSetClipMaskSkill",
        arguments={
            "track_id": "track_video",
            "clip_id": "clip_main",
            "action": "upsert",
            "mask": ClipMask(
                mask_id="mask_gateway",
                kind="rectangle",
                width=.4,
                height=.4,
            ).model_dump(mode="json"),
        },
        requested_at=NOW,
    )
    gateway = AtomicExecutionGateway(registry)
    before = project.read_bytes()
    rejected = gateway.execute(
        request,
        AtomicExecutionContext(
            caller="workflow",
            registry_ref=registry.reference,
            project_id="project_current",
            confirmation_id="wrong_confirmation",
            allowed_side_effects=("files", "timeline"),
            idempotency_key="reject_mask",
        ),
    )
    assert rejected.status == "error" and project.read_bytes() == before
    context = AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_current",
        confirmation_id="confirmation_mask_gateway",
        allowed_side_effects=("files", "timeline"),
        idempotency_key="apply_mask",
    )
    result = gateway.execute(request, context)
    assert result.status == "success"
    assert gateway.execute(request, context).replayed
    exact = project.read_bytes()
    original = TimelineEditTransaction.replace_config

    def fail(updated: TimelineConfig) -> None:
        original(updated)
        raise OSError("simulated mask persistence failure")

    monkeypatch.setattr(TimelineEditTransaction, "replace_config", fail)
    with pytest.raises(OSError, match="mask persistence"):
        TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_mask(
                "track_video", "clip_main", mask_id="mask_gateway"
            )
        )
    assert project.read_bytes() == exact


def test_manual_mask_draft_requires_confirmation_and_records_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="proposal_manual_mask",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        created_at=NOW,
        edits=(ManualMaskEdit(
            operation_id="manual_mask_upsert",
            action="upsert",
            track_key="video",
            track_id="track_video",
            clip_id="clip_main",
            mask=ClipMask(
                mask_id="mask_manual",
                kind="ellipse",
                width=.45,
                height=.45,
            ),
        ),),
    )
    service = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        build_production_registry(),
    )
    before = project.read_bytes()
    _, review = service.review(proposal.model_dump(mode="json"))
    assert review.changes[0].target_kind == "mask"
    assert project.read_bytes() == before
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="confirmation_manual_mask",
        proposal=proposal,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    service.apply(
        proposal.model_dump(mode="json"),
        confirmation.model_dump(mode="json"),
    )
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert any(
        mask.mask_id == "mask_manual"
        for mask in saved.tracks["video"].clips[0].masks
    )
    trace = TraceabilityStore.load(project)
    assert any(
        relation.entity.entity_kind == "mask"
        and relation.entity.entity_id == "mask_manual"
        for relation in trace.manual_traces[-1].relations
    )


def _frame(path: Path, time: float) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(time), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def _pixel(frame: bytes, x: int, y: int, width: int = 320) -> tuple[int, int, int]:
    offset = (y * width + x) * 3
    return tuple(frame[offset:offset + 3])  # type: ignore[return-value]


def test_real_mask_render_changes_expected_pixel_regions_and_is_seek_safe(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "masked.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:r=24:d=2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True,
        timeout=60,
    )
    timeline = TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={"video": TrackConfig(
            id="track_video_render",
            kind="video",
            order=0,
            clips=[ClipConfig(
                id="clip_render",
                source=str(source),
                trim_out=2,
                keep_audio=False,
                masks=(ClipMask(mask_id="mask_render", kind="ellipse", width=.5, height=.5, feather=.02),),
            )],
        )},
    )
    TimelineRenderer(timeline).render(str(output))
    frame = _frame(output, 1)
    center = _pixel(frame, 160, 90)
    corner = _pixel(frame, 10, 10)
    assert center[0] > 180 and center[1] < 50
    assert max(corner) < 20
    assert _frame(output, 1) == frame
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout)
    video = next(item for item in probe["streams"] if item["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (320, 180, "24/1")


def test_non_normal_blend_mode_renders_deterministically(tmp_path: Path) -> None:
    red = tmp_path / "red.mp4"
    blue = tmp_path / "blue.mp4"
    output = tmp_path / "screen.mp4"
    for path, color in ((red, "red"), (blue, "blue")):
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color={color}:s=320x180:r=24:d=1",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
            ],
            check=True,
            timeout=60,
        )
    timeline = TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "base": TrackConfig(
                id="track_base", kind="video", order=0,
                clips=[ClipConfig(id="clip_base", source=str(red), trim_out=1)],
            ),
            "top": TrackConfig(
                id="track_top", kind="video", order=1,
                clips=[ClipConfig(
                    id="clip_top", source=str(blue), trim_out=1,
                    composite=ClipCompositeSettings(blend_mode="screen"),
                )],
            ),
        },
    )
    TimelineRenderer(timeline).render(str(output))
    pixel = _pixel(_frame(output, 0.5), 160, 90)
    assert pixel[0] > 180 and pixel[2] > 180 and pixel[1] < 80
    assert _frame(output, 0.5) == _frame(output, 0.5)


def test_browser_assets_expose_review_only_mask_controls_without_paths() -> None:
    html = (ROOT / "src/timeline_preview/static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "src/timeline_preview/static/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "src/timeline_preview/static/app.css").read_text(encoding="utf-8")
    for token in ("mask-edit-panel", "stage-mask", "stage-mask-keyframe", "copy-masks", "blend-mode"):
        assert token in html
    assert 'kind: "clip_mask"' in script
    assert "Mask keyframe staged locally" in script
    assert ".mask-edit-panel" in styles
    assert "file://" not in html + script + styles
    assert "C:\\" not in html + script + styles
