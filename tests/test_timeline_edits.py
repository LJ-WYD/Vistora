"""STEP 17 core timeline edit semantics and atomic boundary coverage."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from atomic_runtime import (  # noqa: E402
    AtomicExecutionContext,
    AtomicExecutionGateway,
    build_production_registry,
)
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    DirectorOperation,
    DirectorPlan,
    MediaTimeRangeLocator,
    PlanReference,
    SourceEvidenceReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipConfig,
    FreezeFrameSettings,
    TimelineConfig,
    TimelineRenderer,
    TrackConfig,
)
from timeline_edit import (  # noqa: E402
    MoveClipInput,
    SetClipPropertiesInput,
    SplitClipInput,
    TimelineEditEngine,
    TimelineEditError,
    TimelineEditTransaction,
    TrimClipInput,
)
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from agent import EditingAgent  # noqa: E402
from traceability.query import TraceabilityQuery  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import (  # noqa: E402
    WorkflowApplicationService,
    WorkflowStore,
)


NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)
DIGEST = "sha256:" + ("a" * 64)


def _clip(
    clip_id: str,
    start: float,
    *,
    source: str = "source.mp4",
    trim_in: float = 0.0,
    trim_out: float = 4.0,
    speed: float = 1.0,
) -> ClipConfig:
    return ClipConfig(
        id=clip_id,
        source=source,
        trim_in=trim_in,
        trim_out=trim_out,
        timeline_start=start,
        speed_factor=speed,
        volume=0.6,
        keep_audio=False,
        reverse=True,
        rotate=90,
    )


def _timeline() -> TimelineConfig:
    return TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[
                    _clip("clip_a", 0.0),
                    _clip("clip_b", 4.0, source="b.mp4"),
                    _clip("clip_c", 8.0, source="c.mp4"),
                ],
            ),
            "audio": TrackConfig(
                id="audio",
                clips=[
                    _clip(
                        "audio_a",
                        0.0,
                        source="sound.wav",
                        trim_out=2.0,
                    )
                ],
            ),
        },
    )


def _by_id(timeline: TimelineConfig, track: str, clip_id: str) -> ClipConfig:
    return next(
        clip for clip in timeline.tracks[track].clips if clip.id == clip_id
    )


@pytest.fixture
def project_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".workspace" / "current_timeline.json"
    path.parent.mkdir(parents=True)
    path.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(path.parent))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(path))
    return path


def test_versioned_inputs_are_strict_and_require_exact_clip_ids() -> None:
    value = SplitClipInput(
        track_key="video",
        clip_id="clip_a",
        split_at_seconds=2.0,
    )
    assert SplitClipInput.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        SplitClipInput(
            track_key="video",
            clip_id="clip_a",
            split_at_seconds=2.0,
            target_index=0,
        )
    with pytest.raises(ValidationError):
        MoveClipInput(
            track_key="video",
            clip_id="clip_a",
            timeline_start=-1,
        )
    with pytest.raises(ValidationError):
        SetClipPropertiesInput(track_key="video", clip_id="clip_a")


def test_split_preserves_source_and_playback_properties() -> None:
    updated, outcome = TimelineEditEngine(
        _timeline(),
        id_factory=lambda prefix: f"{prefix}_right",
    ).split("video", "clip_a", 2.0)
    left = _by_id(updated, "video", "clip_a")
    right = _by_id(updated, "video", "clip_right")

    assert (left.trim_in, left.trim_out) == (0.0, 2.0)
    assert (right.trim_in, right.trim_out, right.timeline_start) == (
        2.0,
        4.0,
        2.0,
    )
    for field in (
        "source",
        "speed_factor",
        "volume",
        "keep_audio",
        "reverse",
        "rotate",
    ):
        assert getattr(right, field) == getattr(left, field)
    assert outcome.created_clip_ids == ("clip_right",)
    assert outcome.modified_clip_ids == ("clip_a",)


@pytest.mark.parametrize("point", [0.0, 0.0000001, 3.9999999, 4.0])
def test_split_rejects_boundaries_and_zero_length(point: float) -> None:
    with pytest.raises(TimelineEditError, match="inside"):
        TimelineEditEngine(_timeline()).split("video", "clip_a", point)


def test_trim_ripple_uses_speed_adjusted_duration() -> None:
    timeline = _timeline()
    timeline.tracks["video"].clips[0].speed_factor = 2.0
    timeline.tracks["video"].clips[1].timeline_start = 2.0
    timeline.tracks["video"].clips[2].timeline_start = 6.0
    updated, outcome = TimelineEditEngine(timeline).trim(
        "video",
        "clip_a",
        0.0,
        2.0,
        ripple=True,
    )
    assert _by_id(updated, "video", "clip_b").timeline_start == 1.0
    assert _by_id(updated, "video", "clip_c").timeline_start == 5.0
    assert outcome.consequential_clip_ids == ("clip_b", "clip_c")
    with pytest.raises(TimelineEditError, match="only narrow"):
        TimelineEditEngine(timeline).trim(
            "video", "clip_a", 0.0, 5.0, ripple=False
        )


def test_lift_and_ripple_delete_have_distinct_gap_semantics() -> None:
    lifted, _ = TimelineEditEngine(_timeline()).remove(
        "video", "clip_b", ripple=False
    )
    rippled, outcome = TimelineEditEngine(_timeline()).remove(
        "video", "clip_b", ripple=True
    )
    assert _by_id(lifted, "video", "clip_c").timeline_start == 8.0
    assert _by_id(rippled, "video", "clip_c").timeline_start == 4.0
    assert outcome.deleted_clip_ids == ("clip_b",)
    assert outcome.consequential_clip_ids == ("clip_c",)


def test_move_and_insert_are_deterministic_about_consequences() -> None:
    moved, outcome = TimelineEditEngine(_timeline()).move(
        "video", "clip_a", 5.0, ripple=False
    )
    assert _by_id(moved, "video", "clip_a").timeline_start == 5.0
    assert outcome.warnings

    inserted = _clip(
        "clip_insert",
        4.0,
        source="insert.mp4",
        trim_out=2.0,
    )
    first, first_outcome = TimelineEditEngine(_timeline()).insert_overwrite(
        "video", inserted, mode="insert"
    )
    second, second_outcome = TimelineEditEngine(_timeline()).insert_overwrite(
        "video", inserted, mode="insert"
    )
    assert first == second
    assert first_outcome == second_outcome
    assert _by_id(first, "video", "clip_b").timeline_start == 6.0
    assert _by_id(first, "video", "clip_c").timeline_start == 10.0


def test_overwrite_retains_both_uncovered_sides_with_unique_ids() -> None:
    timeline = TimelineConfig(
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[_clip("long_clip", 0.0, trim_out=10.0)],
            ),
            "audio": TrackConfig(id="audio"),
        }
    )
    replacement = _clip(
        "inserted",
        3.0,
        source="insert.mp4",
        trim_out=2.0,
    )
    updated, outcome = TimelineEditEngine(
        timeline,
        id_factory=lambda prefix: f"{prefix}_right",
    ).insert_overwrite("video", replacement, mode="overwrite")

    left = _by_id(updated, "video", "long_clip")
    right = _by_id(updated, "video", "clip_right")
    assert (left.trim_in, left.trim_out) == (0.0, 3.0)
    assert (right.trim_in, right.trim_out, right.timeline_start) == (
        5.0,
        10.0,
        5.0,
    )
    assert set(outcome.created_clip_ids) == {"inserted", "clip_right"}
    assert outcome.direct_clip_ids == ("inserted",)
    assert set(outcome.consequential_clip_ids) == {
        "long_clip",
        "clip_right",
    }
    assert len(
        {
            clip.id
            for track in updated.tracks.values()
            for clip in track.clips
        }
    ) == 3


def test_insert_inside_clip_preserves_and_pushes_its_right_side() -> None:
    timeline = TimelineConfig(
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[_clip("long_clip", 0.0, trim_out=8.0)],
            ),
            "audio": TrackConfig(id="audio"),
        }
    )
    inserted = _clip(
        "inserted",
        3.0,
        source="insert.mp4",
        trim_out=2.0,
    )
    updated, outcome = TimelineEditEngine(
        timeline,
        id_factory=lambda prefix: f"{prefix}_right",
    ).insert_overwrite("video", inserted, mode="insert")
    left = _by_id(updated, "video", "long_clip")
    right = _by_id(updated, "video", "clip_right")
    assert (left.trim_in, left.trim_out) == (0.0, 3.0)
    assert (right.trim_in, right.trim_out, right.timeline_start) == (
        3.0,
        8.0,
        5.0,
    )
    assert outcome.direct_clip_ids == ("inserted",)
    assert set(outcome.consequential_clip_ids) == {
        "long_clip",
        "clip_right",
    }


def test_audio_properties_are_real_and_rotation_is_rejected() -> None:
    muted, _ = TimelineEditEngine(_timeline()).set_properties(
        "audio",
        "audio_a",
        speed_factor=2.0,
        volume=None,
        keep_audio=None,
        mute=True,
        rotate=None,
    )
    audio = _by_id(muted, "audio", "audio_a")
    assert audio.speed_factor == 2.0
    assert audio.volume == 0.0
    with pytest.raises(TimelineEditError, match="video"):
        TimelineEditEngine(_timeline()).set_properties(
            "audio",
            "audio_a",
            speed_factor=None,
            volume=None,
            keep_audio=None,
            mute=None,
            rotate=90,
        )


def test_reverse_is_a_transactional_clip_property_without_proxy_media(
    project_file: Path,
) -> None:
    registry = build_production_registry()
    gateway = AtomicExecutionGateway(registry)
    request = AtomicToolRequestEnvelope(
        request_id="request_reverse",
        execution_id="execution_reverse",
        project_id="legacy_project",
        confirmation_id="confirmation_reverse",
        plan_ref=PlanReference(
            plan_id="plan_reverse",
            plan_version=1,
            plan_digest=DIGEST,
        ),
        step_id="step_reverse",
        tool_name="VideoSetClipPropertiesSkill",
        arguments={
            "track_id": "video",
            "clip_id": "clip_a",
            "reverse": False,
        },
        requested_at=NOW,
    )
    # The fixture starts reversed; disabling it proves the exact clip-ID path
    # mutates only declarative project state and never substitutes a proxy.
    before_source = _timeline().tracks["video"].clips[0].source
    result = gateway.execute(
        request,
        AtomicExecutionContext(
            caller="workflow",
            registry_ref=registry.reference,
            project_id="legacy_project",
            confirmation_id="confirmation_reverse",
            allowed_side_effects=("files", "timeline"),
            idempotency_key="reverse_once",
        ),
    )
    assert result.status == "success"
    persisted = TimelineConfig.model_validate_json(
        project_file.read_text(encoding="utf-8")
    )
    clip = _by_id(persisted, "video", "clip_a")
    assert clip.reverse is False
    assert clip.source == before_source
    assert "reverse_cache" not in clip.source


def test_freeze_frame_is_versioned_bounded_split_safe_and_clearable() -> None:
    settings = FreezeFrameSettings(
        source_time_seconds=1.25,
        duration_seconds=3.0,
    )
    updated, outcome = TimelineEditEngine(_timeline()).set_freeze_frame(
        "video", "clip_a", freeze_frame=settings
    )
    frozen = _by_id(updated, "video", "clip_a")
    assert frozen.freeze_frame == settings
    assert frozen.keep_audio is False and frozen.reverse is False
    assert outcome.operation == "set_freeze_frame"

    split, split_outcome = TimelineEditEngine(
        updated, id_factory=lambda prefix: f"{prefix}_frozen_right"
    ).split("video", "clip_a", 1.0, right_clip_id="clip_frozen_right")
    left = _by_id(split, "video", "clip_a")
    right = _by_id(split, "video", "clip_frozen_right")
    assert left.freeze_frame.duration_seconds == pytest.approx(1.0)
    assert right.freeze_frame.duration_seconds == pytest.approx(2.0)
    assert left.freeze_frame.source_time_seconds == right.freeze_frame.source_time_seconds
    assert split_outcome.created_clip_ids == ("clip_frozen_right",)

    cleared, _ = TimelineEditEngine(updated).set_freeze_frame(
        "video", "clip_a", freeze_frame=None
    )
    assert _by_id(cleared, "video", "clip_a").freeze_frame is None
    with pytest.raises(TimelineEditError, match="inside"):
        TimelineEditEngine(_timeline()).set_freeze_frame(
            "video",
            "clip_a",
            freeze_frame=FreezeFrameSettings(
                source_time_seconds=8.0,
                duration_seconds=1.0,
            ),
        )
    with pytest.raises(TimelineEditError, match="video"):
        TimelineEditEngine(_timeline()).set_freeze_frame(
            "audio",
            "audio_a",
            freeze_frame=FreezeFrameSettings(
                source_time_seconds=0.5,
                duration_seconds=1.0,
            ),
        )


def test_freeze_frame_snapshot_and_review_are_deterministic_and_read_only(
    project_file: Path,
) -> None:
    registry = build_production_registry()
    snapshot = TimelineSnapshotService.snapshot_current()
    operation = DirectorOperation(
        operation_id="operation_freeze",
        tool_name="VideoSetClipFreezeFrameSkill",
        arguments={
            "track_id": "video",
            "clip_id": "clip_a",
            "action": "set",
            "freeze_frame": {
                "source_time_seconds": 1.0,
                "duration_seconds": 2.5,
            },
        },
        rationale="Hold the reviewed source frame for emphasis.",
        expected_effect="Create a silent deterministic freeze-frame clip state.",
    )
    plan = DirectorPlan(
        plan_id="plan_freeze",
        plan_version=1,
        created_at=NOW,
        objective="Preview a bounded freeze frame.",
        operations=(operation,),
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_freeze",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    request = PlanDiffRequest(
        request_id="request_freeze",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = project_file.read_bytes()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second and first.digest() == second.digest()
    assert project_file.read_bytes() == before
    change = next(
        item for item in first.changes if item.category == "clip_freeze_frame"
    )
    assert change.after.freeze_frame_source_time_seconds == 1.0
    assert change.after.freeze_frame_duration_seconds == 2.5
    assert first.steps[0].status == "warning"


def test_reverse_and_freeze_render_real_deterministic_frames(tmp_path: Path) -> None:
    import numpy as np
    from moviepy import VideoClip, VideoFileClip

    source = tmp_path / "direction_source.mp4"
    clip = VideoClip(
        frame_function=lambda t: np.full(
            (180, 320, 3),
            (240, 20, 20) if t < 1.0 else (20, 220, 20),
            dtype=np.uint8,
        ),
        duration=2.0,
    ).with_fps(10)
    clip.write_videofile(str(source), codec="libx264", audio=False, logger=None)
    clip.close()

    reverse_output = tmp_path / "reverse.mp4"
    reverse_timeline = TimelineConfig(
        width=320,
        height=180,
        fps=10,
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[
                    ClipConfig(
                        id="clip_reverse",
                        source=str(source),
                        trim_in=0,
                        trim_out=2,
                        reverse=True,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(id="audio"),
        },
    )
    TimelineRenderer(reverse_timeline).render(str(reverse_output))

    freeze_output = tmp_path / "freeze.mp4"
    freeze_timeline = reverse_timeline.model_copy(deep=True)
    frozen = freeze_timeline.tracks["video"].clips[0]
    frozen.reverse = False
    frozen.freeze_frame = FreezeFrameSettings(
        source_time_seconds=0.25,
        duration_seconds=1.2,
    )
    TimelineRenderer(freeze_timeline).render(str(freeze_output))

    reverse_video = VideoFileClip(str(reverse_output))
    freeze_video = VideoFileClip(str(freeze_output))
    try:
        reverse_first = reverse_video.get_frame(0.1).mean(axis=(0, 1))
        reverse_last = reverse_video.get_frame(1.7).mean(axis=(0, 1))
        freeze_first = freeze_video.get_frame(0.1).mean(axis=(0, 1))
        freeze_last = freeze_video.get_frame(1.0).mean(axis=(0, 1))
        assert reverse_first[1] > reverse_first[0]
        assert reverse_last[0] > reverse_last[1]
        assert freeze_first[0] > freeze_first[1]
        assert np.max(np.abs(freeze_first - freeze_last)) < 3.0
        assert freeze_video.duration == pytest.approx(1.2, abs=0.15)
    finally:
        reverse_video.close()
        freeze_video.close()


def test_property_style_invariants_hold_for_operation_sequence() -> None:
    engine = TimelineEditEngine(
        _timeline(),
        id_factory=lambda prefix: f"{prefix}_generated",
    )
    timeline, _ = engine.split("video", "clip_a", 2.0)
    timeline, _ = TimelineEditEngine(timeline).trim(
        "video", "clip_generated", 2.5, 4.0, ripple=True
    )
    timeline, _ = TimelineEditEngine(timeline).move(
        "video", "clip_generated", 6.0, ripple=False
    )
    TimelineEditEngine.validate(timeline)
    ids = [
        clip.id for track in timeline.tracks.values() for clip in track.clips
    ]
    assert len(ids) == len(set(ids))
    for track in timeline.tracks.values():
        assert track.clips == sorted(
            track.clips, key=lambda clip: (clip.timeline_start, clip.id)
        )
        for clip in track.clips:
            assert clip.trim_out > clip.trim_in
            assert clip.timeline_start >= 0


def test_atomic_transaction_restores_exact_bytes_on_save_failure(
    project_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = project_file.read_bytes()
    original = TimelineEditTransaction._replace
    calls = {"count": 0}

    def fail_once(path: Path, content: bytes) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("simulated durable-write failure")
        original(path, content)

    monkeypatch.setattr(TimelineEditTransaction, "_replace", fail_once)
    with pytest.raises(OSError, match="durable-write"):
        TimelineEditTransaction.apply(
            lambda engine: engine.split(
                "video", "clip_a", 2.0, right_clip_id="clip_right"
            )
        )
    assert project_file.read_bytes() == before
    assert not tuple(project_file.parent.glob("*.tmp"))


def test_gateway_requires_confirmation_and_replays_exact_request(
    project_file: Path,
) -> None:
    registry = build_production_registry()
    gateway = AtomicExecutionGateway(registry)
    request = AtomicToolRequestEnvelope(
        request_id="request_split",
        execution_id="execution_split",
        project_id="legacy_project",
        confirmation_id="confirmation_split",
        plan_ref=PlanReference(
            plan_id="plan_split",
            plan_version=1,
            plan_digest=DIGEST,
        ),
        step_id="step_split",
        tool_name="VideoSplitClipSkill",
        arguments={
            "track_key": "video",
            "clip_id": "clip_a",
            "split_at_seconds": 2.0,
            "right_clip_id": "clip_right",
        },
        requested_at=NOW,
    )
    rejected = gateway.execute(
        request,
        AtomicExecutionContext(
            caller="workflow",
            registry_ref=registry.reference,
            project_id="legacy_project",
            confirmation_id="confirmation_other",
            allowed_side_effects=("files", "timeline"),
            idempotency_key="split_rejected",
        ),
    )
    before = project_file.read_bytes()
    assert rejected.error.code == "confirmation_binding_mismatch"
    assert project_file.read_bytes() == before

    context = AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="legacy_project",
        confirmation_id="confirmation_split",
        allowed_side_effects=("files", "timeline"),
        idempotency_key="split_confirmed",
    )
    result = gateway.execute(request, context)
    replay = gateway.execute(request, context)
    assert result.status == "success"
    assert replay.replayed is True
    assert replay.result_id == result.result_id
    persisted = json.loads(project_file.read_text(encoding="utf-8"))
    assert {
        clip["id"] for clip in persisted["tracks"]["video"]["clips"]
    } >= {"clip_a", "clip_right"}


def test_plan_review_simulates_new_edits_without_dispatch_or_write(
    project_file: Path,
) -> None:
    registry = build_production_registry()
    snapshot = TimelineSnapshotService.snapshot_current()
    operations = (
        DirectorOperation(
            operation_id="operation_split",
            tool_name="VideoSplitClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_a",
                "split_at_seconds": 2.0,
                "right_clip_id": "clip_a_right",
            },
            rationale="Create a precise editorial beat.",
            expected_effect="Retain both source ranges as exact clips.",
        ),
        DirectorOperation(
            operation_id="operation_trim",
            tool_name="VideoTrimClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_a_right",
                "trim_in": 2.5,
                "trim_out": 4.0,
                "ripple": True,
            },
            rationale="Tighten the second half.",
            expected_effect="Shorten and ripple the following clips.",
        ),
        DirectorOperation(
            operation_id="operation_move",
            tool_name="VideoMoveClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_a_right",
                "timeline_start": 5.0,
                "ripple": False,
            },
            rationale="Create an intentional overlap.",
            expected_effect="Move the exact clip and show a warning.",
        ),
        DirectorOperation(
            operation_id="operation_remove",
            tool_name="VideoRemoveClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_b",
                "mode": "ripple",
            },
            rationale="Remove a redundant beat.",
            expected_effect="Delete it and close the same-track gap.",
        ),
    )
    plan = DirectorPlan(
        plan_id="plan_core_edits",
        plan_version=1,
        created_at=NOW,
        objective="Preview a deterministic professional edit sequence.",
        operations=operations,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_core_edits",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    request = PlanDiffRequest(
        request_id="request_core_edits",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = project_file.read_bytes()

    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)

    assert first == second
    assert first.digest() == second.digest()
    assert project_file.read_bytes() == before
    assert {
        change.category for change in first.changes
    } >= {"clip_addition", "clip_trim", "clip_timing", "clip_removal"}
    assert any(
        change.effect_kind == "consequential"
        for change in first.changes
    )
    assert first.summary.after_clip_count == 4
    assert first.summary.after_duration_seconds >= 0
    assert all(step.status in {"previewed", "warning"} for step in first.steps)


def test_confirmed_editing_agent_sequence_records_trace_and_rolls_back(
    project_file: Path,
) -> None:
    registry = build_production_registry()
    counter = {"value": 0}

    def identifier(prefix: str) -> str:
        counter["value"] += 1
        return f"{prefix}_{counter['value']:04d}"

    workflow = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file),
        registry=registry,
        id_factory=identifier,
    )
    agent = EditingAgent(workflow, id_factory=identifier)
    snapshot = TimelineSnapshotService.snapshot_current()
    evidence = SourceEvidenceReference(
        evidence_id="evidence_clip_a",
        material_id=next(
            clip.source.source_id
            for track in snapshot.tracks
            if track.track_key == "video"
            for clip in track.clips
            if clip.clip_id == "clip_a"
        ),
        locator=MediaTimeRangeLocator(
            start_seconds=0.0,
            end_seconds=4.0,
        ),
        analysis_fact_id="fact_clip_a",
        analysis_fact_digest=DIGEST,
    )
    operations = (
        DirectorOperation(
            operation_id="operation_split",
            tool_name="VideoSplitClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_a",
                "split_at_seconds": 2.0,
                "right_clip_id": "clip_a_right",
            },
            rationale="Split on the confirmed editorial beat.",
            expected_effect="Create two source-contiguous clips.",
            evidence_ids=(evidence.evidence_id,),
        ),
        DirectorOperation(
            operation_id="operation_trim",
            tool_name="VideoTrimClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_a_right",
                "trim_in": 2.5,
                "trim_out": 4.0,
                "ripple": True,
            },
            rationale="Tighten the confirmed second beat.",
            expected_effect="Shorten it and close its source-duration gap.",
            evidence_ids=(evidence.evidence_id,),
        ),
        DirectorOperation(
            operation_id="operation_move",
            tool_name="VideoMoveClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_a_right",
                "timeline_start": 5.0,
                "ripple": False,
            },
            rationale="Place the beat at its explicit reviewed time.",
            expected_effect="Move only the exact selected clip.",
            evidence_ids=(evidence.evidence_id,),
        ),
        DirectorOperation(
            operation_id="operation_remove",
            tool_name="VideoRemoveClipSkill",
            arguments={
                "track_key": "video",
                "clip_id": "clip_b",
                "mode": "ripple",
            },
            rationale="Remove the redundant middle beat.",
            expected_effect="Delete it and close the same-track gap.",
        ),
    )
    plan = DirectorPlan(
        plan_id="plan_reference_core_edits",
        plan_version=1,
        created_at=NOW,
        objective="Execute the reviewed core-edit regression.",
        source_evidence=(evidence,),
        operations=operations,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="execution_reference_core_edits",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    request = PlanDiffRequest(
        request_id="review_reference_core_edits",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    original = project_file.read_bytes()
    review = workflow.record_review(request)
    confirmation = workflow.confirm_review(
        review.review_id,
        confirmed_by="reference_user",
        decision="confirmed",
    )
    execution_request = agent.prepare_execution(
        request_id="editing_request_core_edits",
        confirmation_record_id=confirmation.confirmation_record_id,
    )
    report = agent.execute(execution_request)

    assert report.status == "succeeded"
    assert [step.tool_name for step in report.steps] == [
        operation.tool_name for operation in operations
    ]
    document = TraceabilityStore.load(project_file)
    assert len(document.confirmed_traces) == 4
    current = TimelineSnapshotService.snapshot_current()
    provenance = TraceabilityQuery(
        document,
        current,
    ).clip_to_trace("video", "clip_a_right").provenance
    assert provenance.origin_kind == "legacy_unknown"
    assert provenance.latest_change_origin == "director_plan"
    assert provenance.plan_id == plan.plan_id
    assert provenance.evidence[0].evidence_id == evidence.evidence_id

    rollback_review = workflow.propose_rollback(report.run_id)
    rollback_confirmation = workflow.confirm_rollback(
        rollback_review.review_id,
        confirmed_by="reference_user",
        decision="confirmed",
    )
    rollback = workflow.apply_rollback(
        rollback_confirmation.confirmation_id
    )
    assert rollback.status == "succeeded"
    assert json.loads(project_file.read_bytes()) == json.loads(original)
