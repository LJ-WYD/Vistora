import ast
import math
import struct
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from media_analysis import (  # noqa: E402
    MediaAnalysisRequest,
    MediaAnalysisResult,
    MediaAnalysisService,
    MediaAnalysisSettings,
)


def _request(
    *,
    media_kind: str = "video",
    clip_id: str = "clip_analysis",
    source_id: str = "source_0123456789abcdef",
    timeline_start: float = 4.0,
    timeline_end: float = 6.0,
) -> MediaAnalysisRequest:
    return MediaAnalysisRequest(
        snapshot_id="snapshot_analysis_demo",
        source_id=source_id,
        clip_id=clip_id,
        track_key=media_kind,
        media_kind=media_kind,
        source_start_seconds=1.0,
        source_end_seconds=3.0,
        timeline_start_seconds=timeline_start,
        timeline_end_seconds=timeline_end,
        settings=MediaAnalysisSettings(
            thumbnail_count=3,
            waveform_points=16,
        ),
    )


def test_analysis_contracts_are_versioned_frozen_and_round_trip() -> None:
    request = _request()

    assert request.schema_version == "1.0.0"
    assert request.digest().startswith("sha256:")
    assert MediaAnalysisRequest.model_validate_json(
        request.model_dump_json()
    ) == request

    with pytest.raises(ValidationError, match="frozen"):
        request.clip_id = "changed"
    with pytest.raises(ValidationError, match="source range"):
        MediaAnalysisRequest.model_validate(
            {
                **_request().model_dump(mode="json"),
                "source_end_seconds": 0.5,
            }
        )


def test_video_analysis_is_deterministic_cached_and_detached(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    original = b"immutable-source"
    source.write_bytes(original)
    calls: list[tuple[str, ...]] = []

    def fake_runner(command: list[str], timeout: float) -> bytes:
        calls.append(tuple(command))
        return b"\x89PNG\r\n\x1a\n" + command[command.index("-ss") + 1].encode()

    service = MediaAnalysisService(command_runner=fake_runner)
    request = _request()

    first = service.analyze(request, source, "video/mp4")
    second = service.analyze(request, source, "video/mp4")

    assert first == second
    assert MediaAnalysisResult.model_validate_json(
        first.model_dump_json()
    ) == first
    assert first.status == "ready"
    assert [frame.source_time_seconds for frame in first.thumbnails] == [
        pytest.approx(1.333333),
        pytest.approx(2.0),
        pytest.approx(2.666667),
    ]
    assert [frame.timeline_time_seconds for frame in first.thumbnails] == [
        pytest.approx(4.333333),
        pytest.approx(5.0),
        pytest.approx(5.666667),
    ]
    assert len(calls) == 3
    assert service.cache_hits == 1
    assert service.cache_misses == 1
    assert service.cache_size == 1
    assert source.read_bytes() == original
    artifact = service.get_artifact(
        first.analysis_id,
        first.thumbnails[0].artifact_id,
    )
    assert artifact is not None
    assert artifact.content_type == "image/png"
    assert service.get_artifact("../analysis", "thumbnail_bad") is None


def test_reverse_video_frames_follow_visible_timeline_direction(
    tmp_path: Path,
) -> None:
    source = tmp_path / "reverse.mp4"
    source.write_bytes(b"reverse-source")
    commands: list[list[str]] = []

    def fake_runner(command: list[str], timeout: float) -> bytes:
        commands.append(command)
        return b"\x89PNG\r\n\x1a\nframe"

    service = MediaAnalysisService(command_runner=fake_runner)
    request = MediaAnalysisRequest.model_validate(
        {
            **_request().model_dump(mode="json"),
            "reverse": True,
            "rotate_degrees": 90,
        }
    )

    result = service.analyze(request, source, "video/mp4")

    assert [
        frame.source_time_seconds for frame in result.thumbnails
    ] == sorted(
        (
            frame.source_time_seconds
            for frame in result.thumbnails
        ),
        reverse=True,
    )
    assert [
        frame.timeline_time_seconds for frame in result.thumbnails
    ] == sorted(
        frame.timeline_time_seconds for frame in result.thumbnails
    )
    assert all(
        "transpose=1" in command[command.index("-vf") + 1]
        for command in commands
    )


def test_waveform_peaks_are_deterministic_and_timeline_aligned(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"immutable-audio")
    samples = [
        math.sin(index / 8 * math.tau) * 0.75
        for index in range(160)
    ]
    raw = struct.pack(f"<{len(samples)}f", *samples)
    service = MediaAnalysisService(
        command_runner=lambda command, timeout: raw
    )
    request = _request(media_kind="audio")

    result = service.analyze(request, source, "audio/wav")

    assert result.status == "ready"
    assert len(result.waveform) == 16
    assert result.waveform[0].timeline_start_seconds == 4.0
    assert result.waveform[-1].timeline_end_seconds == 6.0
    assert [
        peak.timeline_start_seconds
        for peak in result.waveform
    ] == sorted(
        peak.timeline_start_seconds for peak in result.waveform
    )
    assert all(
        -1 <= peak.minimum <= peak.maximum <= 1
        for peak in result.waveform
    )
    assert source.read_bytes() == b"immutable-audio"


def test_bounded_cache_evicts_old_thumbnail_artifacts(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first.mp4"
    second_source = tmp_path / "second.mp4"
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second-longer")
    service = MediaAnalysisService(
        cache_capacity=1,
        command_runner=lambda command, timeout: (
            b"\x89PNG\r\n\x1a\ncached"
        ),
    )
    first = service.analyze(_request(), first_source, "video/mp4")
    first_frame = first.thumbnails[0]
    second = service.analyze(
        _request(
            clip_id="clip_second",
            source_id="source_fedcba9876543210",
        ),
        second_source,
        "video/mp4",
    )

    assert service.cache_size == 1
    assert first.analysis_id != second.analysis_id
    assert service.get_artifact(
        first.analysis_id,
        first_frame.artifact_id,
    ) is None
    assert service.get_artifact(
        second.analysis_id,
        second.thumbnails[0].artifact_id,
    ) is not None


def test_missing_unsupported_and_decode_failure_are_explicit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-media")
    service = MediaAnalysisService(
        command_runner=lambda command, timeout: b"invalid"
    )
    request = _request()

    missing = service.unavailable(request)
    mismatch = service.analyze(request, source, "audio/mpeg")
    failed = MediaAnalysisService(
        command_runner=lambda command, timeout: (_ for _ in ()).throw(
            OSError("decode failed")
        )
    ).analyze(request, source, "video/mp4")

    assert missing.status == "missing"
    assert missing.status_code == "source_unavailable"
    assert mismatch.status == "unsupported"
    assert mismatch.status_code == "media_kind_mismatch"
    assert failed.status == "error"
    assert failed.status_code == "analysis_failed"
    assert not failed.thumbnails


def test_analysis_package_has_no_timeline_or_mutation_dependencies() -> None:
    forbidden_imports = {
        "agent",
        "core",
        "skills",
        "timeline_preview",
        "utils.hardware",
        "utils.proxy",
    }
    forbidden_calls = {
        "save_current_timeline",
        "reset_timeline",
        "render",
        "write_videofile",
        "replace",
        "unlink",
    }
    violations: list[str] = []
    for path in sorted((SRC / "media_analysis").glob("*.py")):
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
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_calls
            ):
                violations.append(f"{path.name}: call {node.func.attr}")
    assert not violations, (
        "Media analysis must remain read-only and timeline-independent: "
        f"{violations}"
    )
