"""Original O31 finished-media automatic QC tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delivery_qc import (  # noqa: E402
    DeliveryQCError,
    DeliveryQCProfile,
    DeliveryQCRequest,
    DeliveryQCService,
    QCSubtitleCueEvidence,
)
from subtitle_alignment import SubtitleSyncQCResult  # noqa: E402


def _digest(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _request(path, *, profile=None, cues=()):
    return DeliveryQCRequest(
        request_id="qc_request_00000001",
        project_id="project_qc_00000001",
        project_revision=12,
        asset_id="delivery_asset_00000001",
        expected_content_digest=_digest(path),
        profile=profile or DeliveryQCProfile(
            profile_id="qc_profile_00000001",
            expected_width=1920,
            expected_height=1080,
        ),
        subtitle_cues=cues,
    )


class FakeRunner:
    def __init__(self, *, black=False, freeze=False, decode_ok=True, probe_ok=True):
        self.black = black
        self.freeze = freeze
        self.decode_ok = decode_ok
        self.probe_ok = probe_ok
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(tuple(args))
        if args[0] == "ffprobe":
            if not self.probe_ok:
                return subprocess.CompletedProcess(args, 1, "", "unsafe C:\\private\\media.mp4")
            payload = {
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"},
                    {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
                ],
                "format": {"duration": "10.0"},
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        joined = " ".join(args)
        if "blackdetect=" in joined:
            stderr = "[blackdetect] black_start:1 black_end:2 black_duration:1" if self.black else ""
            return subprocess.CompletedProcess(args, 0, "", stderr)
        if "freezedetect=" in joined:
            stderr = "[freezedetect] freeze_start:4\nfreeze_end:7" if self.freeze else ""
            return subprocess.CompletedProcess(args, 0, "", stderr)
        if "loudnorm=" in joined:
            return subprocess.CompletedProcess(args, 0, "", '{"input_i":"-14.0","input_tp":"-1.5"}')
        return subprocess.CompletedProcess(args, 0 if self.decode_ok else 1, "", "decoder failed")


def test_qc_contracts_are_versioned_frozen_strict_and_digest_bound(tmp_path):
    media = tmp_path / "delivery.mp4"
    media.write_bytes(b"finished-media")
    request = _request(media)
    service = DeliveryQCService(allowlisted_roots=(tmp_path,), runner=FakeRunner())
    report = service.analyze(request, source_path=media)
    assert report.schema_version == "1.0.0"
    assert report.status == "passed"
    assert report.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        report.status = "failed"
    with pytest.raises(ValidationError):
        DeliveryQCProfile.model_validate({**request.profile.model_dump(), "unknown": True})
    with pytest.raises(ValidationError, match="digest mismatched"):
        type(report).model_validate({**report.model_dump(), "report_id": "qc_report_tampered"})


def test_all_ten_checks_are_deterministic_cached_and_browser_safe(tmp_path):
    media = tmp_path / "delivery.mp4"
    media.write_bytes(b"finished-media")
    runner = FakeRunner()
    service = DeliveryQCService(allowlisted_roots=(tmp_path,), runner=runner)
    request = _request(media, cues=(
        QCSubtitleCueEvidence(
            cue_id="cue_delivery_0001", start_seconds=1, end_seconds=2,
            text="Safe caption", safe_area_status="passed",
        ),
    ))
    first = service.analyze(request, source_path=media)
    calls = len(runner.calls)
    second = service.analyze(request, source_path=media)
    assert first == second and len(runner.calls) == calls
    assert [item.check_id for item in first.checks] == [
        "audio_tracks", "black_frames", "codec", "duration", "frame_size",
        "freeze_frames", "full_decode", "loudness", "subtitle_sync",
        "subtitles",
    ]
    payload = first.model_dump_json()
    assert str(tmp_path) not in payload
    assert "delivery.mp4" not in payload
    assert first.browser_safe is True


def test_black_freeze_loudness_subtitle_and_decode_failures_are_truthful(tmp_path):
    media = tmp_path / "delivery.mp4"
    media.write_bytes(b"finished-media")
    cues = (
        QCSubtitleCueEvidence(cue_id="cue_000000000001", start_seconds=0, end_seconds=2, text="First", safe_area_status="failed"),
        QCSubtitleCueEvidence(cue_id="cue_000000000002", start_seconds=1, end_seconds=3, text="Overlap"),
    )
    runner = FakeRunner(black=True, freeze=True, decode_ok=False)
    report = DeliveryQCService(allowlisted_roots=(tmp_path,), runner=runner).analyze(
        _request(media, cues=cues), source_path=media
    )
    checks = {item.check_id: item for item in report.checks}
    assert report.status == "failed"
    assert checks["black_frames"].status == "warning"
    assert checks["freeze_frames"].status == "warning"
    assert checks["subtitles"].status == "failed"
    assert checks["full_decode"].status == "failed"


def test_required_subtitle_sync_is_exact_finished_asset_bound(tmp_path):
    media = tmp_path / "delivery.mp4"
    media.write_bytes(b"finished-media")
    bare_digest = hashlib.sha256(media.read_bytes()).hexdigest()
    sync = SubtitleSyncQCResult.create(
        status="passed", sync_qc_id="sync_delivery_0001",
        report_id="alignment_delivery_0001", report_digest="sha256:" + "1" * 64,
        track_id="subtitle_delivery", source_sha256="2" * 64,
        analyzed_clip_digest="3" * 64, timeline_status="passed",
        maximum_timeline_error_seconds=0, rendered_content_sha256=bare_digest,
        audio_mux_offset_seconds=0.005, audio_correlation=0.99,
        checks=("source_binding_passed", "timeline_words_passed", "rendered_audio_sync_passed"),
    )
    profile = DeliveryQCProfile(
        profile_id="qc_profile_sync_0001", expected_width=1920, expected_height=1080,
        require_subtitle_sync=True,
    )
    request = DeliveryQCRequest(
        request_id="qc_request_sync_0001", project_id="project_qc_sync_0001",
        project_revision=12, asset_id="delivery_asset_sync_0001",
        expected_content_digest=_digest(media), profile=profile,
        subtitle_sync_evidence=sync,
    )
    report = DeliveryQCService(allowlisted_roots=(tmp_path,), runner=FakeRunner()).analyze(request, source_path=media)
    assert {item.check_id: item.status for item in report.checks}["subtitle_sync"] == "passed"
    with pytest.raises(ValidationError, match="finished asset"):
        DeliveryQCRequest.model_validate({
            **request.model_dump(mode="python"),
            "expected_content_digest": "sha256:" + "f" * 64,
        })


def test_probe_failure_digest_drift_and_path_escape_fail_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    media = root / "delivery.mp4"
    media.write_bytes(b"finished-media")
    service = DeliveryQCService(allowlisted_roots=(root,), runner=FakeRunner(probe_ok=False))
    report = service.analyze(_request(media), source_path=media)
    assert report.status == "failed"
    assert {item.status for item in report.checks} == {"failed", "not_applicable"}
    request = _request(media)
    media.write_bytes(b"changed")
    with pytest.raises(DeliveryQCError, match="content changed"):
        service.analyze(request, source_path=media)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    with pytest.raises(DeliveryQCError, match="outside"):
        service.analyze(_request(outside), source_path=outside)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_real_ffmpeg_qc_probes_decodes_and_analyzes_synthetic_delivery(tmp_path):
    media = tmp_path / "synthetic-delivery.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(media),
    ], check=True)
    profile = DeliveryQCProfile(
        profile_id="qc_profile_real_0001",
        expected_width=160,
        expected_height=90,
        freeze_duration_threshold_seconds=2,
        black_duration_threshold_seconds=0.5,
        loudness_tolerance_lu=10,
        maximum_true_peak_dbtp=0,
    )
    report = DeliveryQCService(allowlisted_roots=(tmp_path,)).analyze(
        _request(media, profile=profile), source_path=media
    )
    assert report.probe.width == 160 and report.probe.height == 90
    assert report.probe.video_codec == "h264"
    assert report.probe.audio_streams == 1
    assert {item.check_id: item.status for item in report.checks}["full_decode"] == "passed"
    assert report.status in {"passed", "warning"}
    cli = subprocess.run([
        sys.executable, str(ROOT / "src" / "main.py"), "qc",
        "--input", str(media), "--media-root", str(tmp_path),
        "--asset-id", "delivery_asset_cli_test",
        "--expected-width", "160", "--expected-height", "90",
    ], capture_output=True, text=True, check=True)
    cli_report = json.loads(cli.stdout)
    assert cli_report["schema_name"] == "vistora.delivery-qc-report"
    assert str(tmp_path) not in cli.stdout


def test_qc_architecture_is_read_only_and_has_no_mutation_imports():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "delivery_qc").glob("*.py")
    )
    assert "TimelineManager" not in source
    assert "AtomicExecutionGateway" not in source
    assert "from skills" not in source
    assert "timeline_manager" not in source
