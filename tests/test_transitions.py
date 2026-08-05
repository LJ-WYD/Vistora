from __future__ import annotations

import json
import math
import shutil
import subprocess
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.timeline import (
    ClipConfig,
    TimelineConfig,
    TimelineRenderer,
    TimelineTransition,
    TrackConfig,
    TransitionParameters,
)
from timeline_edit import TimelineEditEngine, TimelineEditError
from timeline_query import TimelineSnapshotService
from atomic_runtime import build_production_registry
from contracts import DirectorOperation, DirectorPlan
from contracts import (
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualClipUpdate,
    ManualTransitionEdit,
)
from core import timeline_manager
from plan_review import (
    PlanDiffEngine,
    PlanDiffRequest,
    PreviewMaterialFact,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshotReference
from timeline_preview.manual_edits import ManualEditApplicationService
from traceability.store import TraceabilityStore


def _timeline(*, locked: bool = False) -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video_main": TrackConfig(
                id="track_video_main",
                kind="video",
                role="primary",
                order=0,
                locked=locked,
                clips=[
                    ClipConfig(
                        id="clip_left",
                        source="left.mp4",
                        trim_in=0.5,
                        trim_out=2.5,
                        timeline_start=0,
                    ),
                    ClipConfig(
                        id="clip_right",
                        source="right.mp4",
                        trim_in=0.5,
                        trim_out=2.5,
                        timeline_start=2,
                    ),
                    ClipConfig(
                        id="clip_third",
                        source="third.mp4",
                        trim_in=0.5,
                        trim_out=2.5,
                        timeline_start=4,
                    ),
                ],
            )
        },
    )


def _video_transition(
    identity: str = "transition_video",
    *,
    from_clip: str = "clip_left",
    to_clip: str = "clip_right",
    kind: str = "cross_dissolve",
    duration: float = 0.6,
    audio_policy: str = "none",
    pair_id: str | None = None,
) -> TimelineTransition:
    parameters = (
        TransitionParameters(direction="left")
        if kind in {"wipe", "slide"}
        else TransitionParameters(color="#000000")
        if kind == "fade_color"
        else TransitionParameters()
    )
    return TimelineTransition(
        transition_id=identity,
        track_id="track_video_main",
        from_clip_id=from_clip,
        to_clip_id=to_clip,
        kind=kind,
        duration_seconds=0 if kind == "cut" else duration,
        alignment="centered",
        parameters=parameters,
        audio_policy=audio_policy,
        paired_transition_id=pair_id,
    )


def _audio_transition(
    identity: str = "transition_audio",
    *,
    pair_id: str = "transition_video",
) -> TimelineTransition:
    return TimelineTransition(
        transition_id=identity,
        track_id="track_video_main",
        from_clip_id="clip_left",
        to_clip_id="clip_right",
        kind="audio_equal_power",
        duration_seconds=0.6,
        alignment="centered",
        paired_transition_id=pair_id,
    )


def test_transition_contract_is_strict_versioned_and_round_trips() -> None:
    transition = _video_transition()
    assert TimelineTransition.model_validate_json(
        transition.model_dump_json()
    ) == transition
    with pytest.raises(ValidationError, match="direction"):
        TimelineTransition.model_validate(
            {
                **transition.model_dump(mode="python"),
                "kind": "wipe",
            }
        )
    with pytest.raises(ValidationError, match="extra"):
        TimelineTransition.model_validate(
            {**transition.model_dump(mode="python"), "raw_filter": "evil"}
        )


def test_add_update_remove_copy_and_exact_handle_validation() -> None:
    engine = TimelineEditEngine(
        _timeline(), source_duration_resolver=lambda clip: 3.0
    )
    updated, outcome = engine.add_transition(_video_transition())
    assert outcome.created_transition_ids == ("transition_video",)
    assert updated.transitions["transition_video"].duration_seconds == 0.6

    replacement = _video_transition(kind="wipe", duration=0.4)
    updated, outcome = engine.update_transition(replacement)
    assert outcome.modified_transition_ids == ("transition_video",)
    assert updated.transitions["transition_video"].kind == "wipe"

    copied = replacement.model_copy(
        update={
            "transition_id": "transition_copy",
            "from_clip_id": "clip_right",
            "to_clip_id": "clip_third",
        }
    )
    updated, outcome = engine.copy_transition(
        "transition_video", ((copied, None),)
    )
    assert outcome.created_transition_ids == ("transition_copy",)
    assert tuple(sorted(updated.transitions)) == (
        "transition_copy",
        "transition_video",
    )
    updated, outcome = engine.remove_transition("transition_video")
    assert outcome.deleted_transition_ids == ("transition_video",)
    assert tuple(updated.transitions) == ("transition_copy",)


def test_linked_audio_pair_is_reciprocal_and_locked_or_short_handles_fail() -> None:
    video = _video_transition(
        audio_policy="linked_audio", pair_id="transition_audio"
    )
    audio = _audio_transition()
    engine = TimelineEditEngine(
        _timeline(), source_duration_resolver=lambda clip: 3.0
    )
    updated, outcome = engine.add_transition(
        video, paired_transition=audio
    )
    assert set(outcome.created_transition_ids) == {
        "transition_video",
        "transition_audio",
    }
    assert (
        updated.transitions["transition_audio"].paired_transition_id
        == "transition_video"
    )
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(
            _timeline(locked=True),
            source_duration_resolver=lambda clip: 3.0,
        ).add_transition(_video_transition())
    with pytest.raises(TimelineEditError, match="insufficient"):
        TimelineEditEngine(
            _timeline(), source_duration_resolver=lambda clip: 2.6
        ).add_transition(_video_transition(duration=0.6))
    with pytest.raises(TimelineEditError, match="audio stream"):
        TimelineEditEngine(
            _timeline(),
            source_duration_resolver=lambda clip: 3.0,
            source_audio_resolver=lambda clip: False,
        ).add_transition(video, paired_transition=audio)


def test_structural_edits_transfer_or_tombstone_transitions_truthfully() -> None:
    timeline = _timeline()
    timeline.transitions = {"transition_video": _video_transition()}
    timeline = TimelineConfig.model_validate(timeline.model_dump(mode="python"))
    split, split_outcome = TimelineEditEngine(
        timeline, id_factory=lambda prefix: f"{prefix}_stable"
    ).split(
        "track_video_main",
        "clip_left",
        1.0,
        right_clip_id="clip_left_right",
    )
    assert not split_outcome.deleted_transition_ids
    assert (
        split.transitions["transition_video"].from_clip_id
        == "clip_left_right"
    )
    trimmed, trim_outcome = TimelineEditEngine(split).trim(
        "track_video_main",
        "clip_left_right",
        1.5,
        2.3,
        ripple=False,
    )
    assert trim_outcome.deleted_transition_ids == ("transition_video",)
    assert not trimmed.transitions


def test_snapshot_v6_is_stable_detached_and_path_safe() -> None:
    timeline = _timeline()
    timeline.transitions = {"transition_video": _video_transition()}
    first = TimelineSnapshotService.snapshot(timeline)
    second = TimelineSnapshotService.snapshot(timeline)
    assert first == second
    assert first.schema_version == "11.0.0"
    assert first.transition_count == 1
    transition = first.transitions[0]
    assert transition.transition_id == "transition_video"
    assert "left.mp4" not in transition.model_dump_json()


def test_plan_review_deterministically_previews_transition_without_mutation() -> None:
    timeline = _timeline()
    snapshot = TimelineSnapshotService.snapshot(timeline)
    transition = _video_transition()
    plan = DirectorPlan(
        plan_id="plan_transition_review",
        plan_version=1,
        objective="Add a deliberate cross dissolve at the exact primary cut.",
        operations=(
            DirectorOperation(
                operation_id="operation_transition_add",
                tool_name="TimelineAddTransitionSkill",
                arguments={
                    "schema_version": "2.0.0",
                    "transition": transition.model_dump(mode="json"),
                    "paired_transition": None,
                },
                rationale="Soften the exact scene change.",
                expected_effect="Create one deterministic transition entity.",
            ),
        ),
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    execution = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_transition_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    facts = tuple(
        PreviewMaterialFact(
            material_id=TimelineSnapshotService.source_id_for_configured_path(
                name
            ),
            media_kind="video",
            duration_seconds=3,
            width=320,
            height=180,
        )
        for name in ("left.mp4", "right.mp4", "third.mp4")
    )
    request = PlanDiffRequest(
        request_id="request_transition_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=execution,
        registry_ref=RegistrySchemaReference.from_registry(registry),
        material_facts=facts,
    )
    before = timeline.model_dump_json()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second
    assert first.review_status == "ready"
    assert first.summary.before_transition_count == 0
    assert first.summary.after_transition_count == 1
    assert [change.category for change in first.changes] == [
        "transition_addition"
    ]
    assert timeline.model_dump_json() == before


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="FFmpeg is required for exact manual handle validation",
)
def test_manual_transition_draft_requires_confirmation_and_records_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = tmp_path / "left.mp4"
    right = tmp_path / "right.mp4"
    third = tmp_path / "third.mp4"
    for path, color in ((left, "red"), (right, "blue"), (third, "green")):
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
            ],
            check=True,
            timeout=30,
        )
    timeline = _timeline()
    timeline.tracks["video_main"].clips[0].source = str(left)
    timeline.tracks["video_main"].clips[1].source = str(right)
    timeline.tracks["video_main"].clips[2].source = str(third)
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="proposal_manual_transition",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        edits=(
            ManualTransitionEdit(
                operation_id="manual_transition_add",
                action="add",
                transition=_video_transition(),
            ),
            ManualTransitionEdit(
                operation_id="manual_transition_add_second",
                action="add",
                transition=_video_transition(
                    "transition_second",
                    from_clip="clip_right",
                    to_clip="clip_third",
                    kind="wipe",
                ),
            ),
        ),
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    service = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        build_production_registry(),
    )
    before = project.read_bytes()
    _, review = service.review(proposal.model_dump(mode="json"))
    assert all(change.target_kind == "transition" for change in review.changes)
    assert project.read_bytes() == before
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="confirmation_manual_transition",
        proposal=proposal,
        confirmed_by="local_user",
        recorded_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    result = service.apply(
        proposal.model_dump(mode="json"),
        confirmation.model_dump(mode="json"),
    )
    assert result["tool_name"] == "VideoApplyManualEditsSkill"
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.transitions["transition_video"].kind == "cross_dissolve"
    assert saved.transitions["transition_second"].kind == "wipe"
    trace = TraceabilityStore.load()
    relations = trace.manual_traces[-1].relations
    assert {(item.operation_id, item.entity.entity_id) for item in relations} == {
        ("manual_transition_add", "transition_video"),
        ("manual_transition_add_second", "transition_second"),
    }

    next_snapshot = TimelineSnapshotService.snapshot_current()
    trim_proposal = ManualEditProposal(
        proposal_id="proposal_manual_transition_tombstone",
        authored_by="local_user",
        base_project_id=next_snapshot.project_id,
        base_revision=next_snapshot.revision,
        base_timeline_digest=next_snapshot.timeline_digest,
        edits=(ManualClipUpdate(
            operation_id="manual_trim_transition_boundary",
            track_key="video_main",
            track_id="track_video_main",
            clip_id="clip_left",
            trim_in_seconds=0.5,
            trim_out_seconds=2.0,
            timeline_start_seconds=0,
            order_index=0,
        ),),
        created_at=datetime(2026, 8, 2, 0, 1, tzinfo=timezone.utc),
    )
    before_trim = project.read_bytes()
    _, trim_review = service.review(trim_proposal.model_dump(mode="json"))
    transition_change = next(
        change
        for change in trim_review.changes
        if change.target_kind == "transition"
    )
    assert transition_change.clip_id == "transition_video"
    assert transition_change.action == "remove"
    assert transition_change.effect_kind == "consequential"
    assert project.read_bytes() == before_trim
    trim_confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="confirmation_manual_transition_tombstone",
        proposal=trim_proposal,
        confirmed_by="local_user",
        recorded_at=datetime(2026, 8, 2, 0, 2, tzinfo=timezone.utc),
    )
    service.apply(
        trim_proposal.model_dump(mode="json"),
        trim_confirmation.model_dump(mode="json"),
    )
    tombstone_trace = TraceabilityStore.load().manual_traces[-1]
    tombstone_relation = next(
        relation
        for relation in tombstone_trace.relations
        if relation.entity.entity_kind == "transition"
    )
    assert tombstone_relation.entity.entity_id == "transition_video"
    assert tombstone_relation.relation_type == "deletes"
    assert tombstone_relation.effect_kind == "consequential"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is required for real transition validation",
)
def test_real_dissolve_and_equal_power_audio_render(tmp_path: Path) -> None:
    left = tmp_path / "left.mp4"
    right = tmp_path / "right.mp4"
    for path, color, frequency in (
        (left, "red", 440),
        (right, "blue", 880),
    ):
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d=3",
                "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000:duration=3",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(path),
            ],
            check=True,
            timeout=30,
        )
    timeline = _timeline()
    timeline.tracks["video_main"].clips = timeline.tracks["video_main"].clips[:2]
    timeline.tracks["video_main"].clips[0].source = str(left)
    timeline.tracks["video_main"].clips[1].source = str(right)
    video = _video_transition(
        audio_policy="linked_audio", pair_id="transition_audio"
    )
    audio = _audio_transition()
    timeline.transitions = {
        video.transition_id: video,
        audio.transition_id: audio,
    }
    timeline = TimelineConfig.model_validate(timeline.model_dump(mode="python"))
    output = tmp_path / "transition.mp4"
    TimelineRenderer(timeline).render(str(output))
    probe = json.loads(subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout)
    assert {stream["codec_type"] for stream in probe["streams"]} == {
        "video", "audio"
    }
    assert float(probe["format"]["duration"]) == pytest.approx(4.0, abs=0.08)

    def mean_rgb(at: float) -> tuple[float, float, float]:
        raw = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", str(at), "-i", str(output),
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        ).stdout
        pixels = len(raw) // 3
        return tuple(
            sum(raw[channel::3]) / pixels for channel in range(3)
        )

    before = mean_rgb(1.5)
    middle = mean_rgb(2.0)
    after = mean_rgb(2.5)
    assert before[0] > before[2] * 3
    assert after[2] > after[0] * 3
    assert middle[0] > 30 and middle[2] > 30

    def band_rms(at: float, frequency: int) -> float:
        raw = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", str(at), "-t", "0.18",
                "-i", str(output), "-vn", "-af",
                f"bandpass=f={frequency}:width_type=h:w=70",
                "-ac", "1", "-ar", "48000", "-f", "f32le", "-",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        ).stdout
        values = array("f")
        values.frombytes(raw)
        return math.sqrt(sum(value * value for value in values) / len(values))

    assert band_rms(1.65, 440) > band_rms(1.65, 880) * 2
    assert band_rms(2.17, 880) > band_rms(2.17, 440) * 2
    assert band_rms(1.92, 440) > 0.005
    assert band_rms(1.92, 880) > 0.005


@pytest.mark.parametrize(
    ("kind", "direction"),
    (
        ("fade_color", "left"),
        ("wipe", "left"),
        ("wipe", "up"),
        ("slide", "right"),
        ("slide", "down"),
    ),
)
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="FFmpeg is required for built-in transition validation",
)
def test_built_in_video_transition_variants_render_deterministically(
    tmp_path: Path, kind: str, direction: str
) -> None:
    left = tmp_path / "left.mp4"
    right = tmp_path / "right.mp4"
    for path, color in ((left, "red"), (right, "blue")):
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
            ],
            check=True,
            timeout=30,
        )
    timeline = _timeline()
    timeline.width = 160
    timeline.height = 90
    timeline.tracks["video_main"].clips = timeline.tracks["video_main"].clips[:2]
    timeline.tracks["video_main"].clips[0].source = str(left)
    timeline.tracks["video_main"].clips[1].source = str(right)
    transition = _video_transition(kind=kind)
    transition = transition.model_copy(
        update={
            "parameters": (
                TransitionParameters(color="#000000")
                if kind == "fade_color"
                else TransitionParameters(direction=direction)
            )
        }
    )
    timeline.transitions = {transition.transition_id: transition}
    timeline = TimelineConfig.model_validate(timeline.model_dump(mode="python"))
    output = tmp_path / f"{kind}-{direction}.mp4"
    TimelineRenderer(timeline).render(str(output))
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-ss",
            "1.8" if kind == "fade_color" else "2.0",
            "-i", str(output),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True,
        capture_output=True,
        timeout=20,
    ).stdout
    red = sum(raw[0::3]) / (len(raw) // 3)
    blue = sum(raw[2::3]) / (len(raw) // 3)
    if kind == "fade_color":
        assert red < 35 and blue < 35
    else:
        assert red > 25 and blue > 25
