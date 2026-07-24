import ast
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from contracts import TimelineProjectDocument  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from timeline_query import (  # noqa: E402
    TimelineSnapshot,
    TimelineSnapshotError,
    TimelineSnapshotReference,
    TimelineSnapshotReferenceError,
    TimelineSnapshotService,
)


def _timeline() -> TimelineConfig:
    return TimelineConfig(
        width=1280,
        height=720,
        fps=25,
        tracks={
            "overlay": TrackConfig(
                id="overlay_track",
                clips=[
                    ClipConfig(
                        id="overlay_clip",
                        source="assets/overlay.png",
                        trim_in=0.0,
                        trim_out=4.0,
                        timeline_start=0.5,
                        speed_factor=2.0,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(
                id="audio_track",
                clips=[
                    ClipConfig(
                        id="music_clip",
                        source=r"media\music.wav",
                        trim_in=1.0,
                        trim_out=7.0,
                        timeline_start=0.0,
                        volume=0.5,
                    )
                ],
            ),
            "video": TrackConfig(
                id="video_track",
                clips=[
                    ClipConfig(
                        id="second_clip",
                        source="media/second.mp4",
                        trim_in=1.0,
                        trim_out=3.0,
                        timeline_start=3.0,
                        keep_audio=False,
                    ),
                    ClipConfig(
                        id="first_clip",
                        source="media/first.mp4",
                        trim_in=0.0,
                        trim_out=3.0,
                        timeline_start=0.0,
                    ),
                ],
            ),
        },
    )


def test_snapshot_is_deterministic_ordered_and_has_derived_summary() -> None:
    source = _timeline()

    first = TimelineSnapshotService.snapshot(source)
    second = TimelineSnapshotService.snapshot(source.model_dump(mode="json"))

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert [track.track_key for track in first.tracks] == [
        "video",
        "audio",
        "overlay",
    ]
    assert [clip.clip_id for clip in first.tracks[0].clips] == [
        "second_clip",
        "first_clip",
    ]
    assert first.track_count == 3
    assert first.clip_count == 4
    assert first.video_clip_count == 2
    assert first.audio_clip_count == 1
    assert first.duration_seconds == 6.0
    assert first.tracks[2].kind == "other"
    assert first.tracks[2].clips[0].effective_duration_seconds == 2.0
    assert first.tracks[2].clips[0].timeline_end_seconds == 2.5
    assert first.tracks[1].clips[0].source.display_name == "music.wav"
    assert not hasattr(first.tracks[0].clips[0].source, "exists")


def test_snapshot_is_detached_immutable_and_does_not_change_source() -> None:
    source = _timeline()
    before = source.model_dump(mode="json")

    snapshot = TimelineSnapshotService.snapshot(source)

    assert source.model_dump(mode="json") == before
    with pytest.raises(ValidationError):
        snapshot.width = 1
    with pytest.raises(ValidationError):
        snapshot.tracks[0].clips[0].source.value = "changed.mp4"

    detached = snapshot.model_dump(mode="json")
    detached["tracks"][0]["clips"][0]["source"]["value"] = "changed.mp4"
    assert source.tracks["video"].clips[0].source == "media/second.mp4"
    assert snapshot.tracks[0].clips[0].source.value == "media/second.mp4"


def test_snapshot_round_trip_enforces_schema_version() -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    restored = TimelineSnapshot.model_validate_json(snapshot.model_dump_json())
    assert restored == snapshot

    invalid = snapshot.model_dump(mode="json")
    invalid["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError, match="1.0.0"):
        TimelineSnapshot.model_validate(invalid)


def test_legacy_and_versioned_inputs_are_compatible() -> None:
    timeline = _timeline()
    legacy = timeline.model_dump(mode="json")
    migrated = TimelineProjectDocument.model_validate(legacy)
    native = TimelineProjectDocument(
        project_id="project_native",
        revision=7,
        timeline=timeline,
    )

    from_model = TimelineSnapshotService.snapshot(timeline)
    from_legacy = TimelineSnapshotService.snapshot(legacy)
    from_migrated = TimelineSnapshotService.snapshot(migrated)
    from_native = TimelineSnapshotService.snapshot(native)

    assert from_model == from_legacy == from_migrated
    assert from_model.migration_source == "legacy.timeline.v0"
    assert from_native.project_id == "project_native"
    assert from_native.revision == 7
    assert from_native.migration_source == "native"
    assert from_native.timeline_digest == from_model.timeline_digest


def test_expected_project_reference_rejects_stale_or_wrong_reads() -> None:
    project = TimelineProjectDocument(
        project_id="project_demo",
        revision=3,
        timeline=_timeline(),
    )

    accepted = TimelineSnapshotService.snapshot(
        project,
        expected_reference=TimelineSnapshotReference(
            project_id="project_demo",
            revision=3,
        ),
    )
    assert accepted.revision == 3

    with pytest.raises(
        TimelineSnapshotReferenceError,
        match="Project reference mismatch",
    ):
        TimelineSnapshotService.snapshot(
            project,
            expected_reference=TimelineSnapshotReference(
                project_id="project_other",
                revision=3,
            ),
        )
    with pytest.raises(
        TimelineSnapshotReferenceError,
        match="Project revision mismatch",
    ):
        TimelineSnapshotService.snapshot(
            project,
            expected_reference=TimelineSnapshotReference(
                project_id="project_demo",
                revision=2,
            ),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source": "   "}, "empty source reference"),
        ({"trim_in": 2.0, "trim_out": 1.0}, "trim_out before trim_in"),
        ({"speed_factor": 0.0}, "non-positive speed_factor"),
    ],
)
def test_invalid_clip_references_and_timing_fail_clearly(
    changes: dict,
    message: str,
) -> None:
    values = {
        "id": "clip_invalid",
        "source": "media/source.mp4",
        "trim_in": 0.0,
        "trim_out": 1.0,
        "speed_factor": 1.0,
    }
    values.update(changes)
    timeline = TimelineConfig(
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[ClipConfig(**values)],
            )
        }
    )

    with pytest.raises(TimelineSnapshotError, match=message):
        TimelineSnapshotService.snapshot(timeline)


def test_current_snapshot_never_changes_or_creates_persisted_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project_file = workspace / "current_timeline.json"
    workspace.mkdir()
    serialized = json.dumps(
        _timeline().model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    )
    project_file.write_text(serialized, encoding="utf-8")
    before_bytes = project_file.read_bytes()
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))

    first = TimelineSnapshotService.snapshot_current()
    second = TimelineSnapshotService.snapshot_current()

    assert first == second
    assert project_file.read_bytes() == before_bytes

    project_file.unlink()
    empty = TimelineSnapshotService.snapshot_current()
    assert empty.empty is True
    assert [track.track_key for track in empty.tracks] == ["video", "audio"]
    assert not project_file.exists()


def test_query_package_has_no_mutation_or_media_engine_calls() -> None:
    forbidden_imports = {"moviepy", "subprocess", "utils.hardware", "utils.proxy"}
    forbidden_calls = {
        "save_current_timeline",
        "reset_timeline",
        "render",
        "execute",
        "write_videofile",
    }
    violations: list[str] = []

    for path in sorted((SRC / "timeline_query").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_imports:
                        violations.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in forbidden_imports:
                    violations.append(
                        f"{path.name}: import from {node.module}"
                    )
            elif isinstance(node, ast.Call) and isinstance(
                node.func,
                ast.Attribute,
            ):
                if node.func.attr in forbidden_calls:
                    violations.append(
                        f"{path.name}: call {node.func.attr}"
                    )

    assert not violations, (
        "Timeline query code must remain read-only and media-engine-free: "
        f"{violations}"
    )
