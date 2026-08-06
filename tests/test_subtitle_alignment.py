"""Narration-bound subtitle alignment, mutation, preview, and QC regression."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atomic_runtime import build_production_registry  # noqa: E402
from audio_analysis import clip_audio_state_digest, source_sha256  # noqa: E402
from contracts import DirectorOperation, DirectorPlan  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, SubtitleTrackConfig, TimelineConfig, TrackConfig  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffEngine, PlanDiffRequest, ProposedEditingExecutionPlan, RegistrySchemaReference,
)
from skills.subtitle_alignment import SubtitleBuildFromAlignmentSkill  # noqa: E402
from subtitle_alignment import (  # noqa: E402
    AudioAlignTranscriptInput, SubtitleAlignmentService,
    SubtitleBuildFromAlignmentInput, SubtitleSyncQCInput,
    SubtitleSyncQCService, TranscriptPhrase, build_aligned_cues,
)
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


class FakeProvider:
    provider_id = "deterministic-test-aligner"
    provider_version = "1.0.0"

    def align(self, **_):
        return (
            {"text": "hello", "start_seconds": 0.40, "end_seconds": 0.70, "confidence": 0.99},
            {"text": "world", "start_seconds": 0.72, "end_seconds": 1.00, "confidence": 0.98},
            {"text": "market", "start_seconds": 1.30, "end_seconds": 1.60, "confidence": 0.97},
            {"text": "news", "start_seconds": 1.62, "end_seconds": 1.90, "confidence": 0.96},
        )


def _timeline(source: str, *, timeline_start=0.5):
    return TimelineConfig(
        width=320, height=180, fps=24,
        tracks={
            "video": TrackConfig(id="video_main", kind="video", order=0, clips=[
                ClipConfig(id="video_clip", source=source, trim_out=3, keep_audio=False),
            ]),
            "audio": TrackConfig(id="audio_voice", kind="audio", role="dialogue", order=1, clips=[
                ClipConfig(id="voice_clip", source=source, trim_out=3, timeline_start=timeline_start),
            ]),
        },
        subtitle_tracks={
            "captions": SubtitleTrackConfig(
                track_id="subtitle_main", role="captions", language="en", order=0,
            ),
        },
    )


def _request():
    return AudioAlignTranscriptInput(
        track_id="audio_voice", clip_id="voice_clip", language="en",
        phrases=(
            TranscriptPhrase(phrase_id="phrase_one", text="Hello world"),
            TranscriptPhrase(phrase_id="phrase_two", text="Market news"),
        ),
    )


def _report(tmp_path):
    source = tmp_path / "voice.wav"
    source.write_bytes(b"stable-final-narration")
    timeline = _timeline(str(source))
    report = SubtitleAlignmentService(FakeProvider()).analyze(timeline, _request())
    return source, timeline, report


def test_alignment_report_is_frozen_digest_bound_and_source_bound(tmp_path):
    source, timeline, report = _report(tmp_path)
    assert report.source_sha256 == source_sha256(str(source))
    clip = timeline.tracks["audio"].clips[0]
    assert report.analyzed_clip_digest == clip_audio_state_digest("audio_voice", clip)
    assert report.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        report.status = "failed"
    with pytest.raises(ValidationError, match="digest mismatched"):
        type(report).model_validate({**report.model_dump(), "provider_version": "tampered"})


def test_builder_uses_word_evidence_lead_and_non_overlapping_short_cues(tmp_path):
    _, _, report = _report(tmp_path)
    cues = build_aligned_cues(report, "narration")
    assert [cue.text for cue in cues] == ["Hello world", "Market news"]
    assert cues[0].start_seconds == pytest.approx(0.70)
    assert cues[0].end_seconds <= cues[1].start_seconds
    assert cues[1].start_seconds == pytest.approx(1.60)
    assert all(cue.words for cue in cues)
    assert cues[0].words[0].start_seconds == pytest.approx(0.90)


def test_build_skill_rejects_stale_source_and_persists_exact_cues(tmp_path, monkeypatch):
    source, timeline, report = _report(tmp_path)
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    result = SubtitleBuildFromAlignmentSkill().execute({
        "report": report.model_dump(mode="json"), "track_id": "subtitle_main",
        "cue_id_prefix": "narration", "language": "en",
    })
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert [cue.cue_id for cue in saved.subtitle_tracks["captions"].cues] == [
        "narration.cue.001", "narration.cue.002",
    ]
    source.write_bytes(b"changed-narration")
    with pytest.raises(ValueError, match="source content changed"):
        SubtitleBuildFromAlignmentSkill().execute({
            "report": report.model_dump(mode="json"), "track_id": "subtitle_main",
            "cue_id_prefix": "narration", "language": "en",
        })


def test_sync_qc_passes_exact_timeline_and_fails_shifted_cues(tmp_path):
    _, timeline, report = _report(tmp_path)
    cues = build_aligned_cues(report, "narration")
    aligned = timeline.model_copy(deep=True)
    aligned.subtitle_tracks = {"captions": aligned.subtitle_tracks["captions"].model_copy(update={"cues": cues})}
    request = SubtitleSyncQCInput(report=report, track_id="subtitle_main", cue_id_prefix="narration")
    passed = SubtitleSyncQCService().analyze(aligned, request)
    assert passed.status == "passed" and passed.maximum_timeline_error_seconds == 0
    first = cues[0].model_copy(update={
        "start_seconds": cues[0].start_seconds + 0.1,
        "words": tuple(word.model_copy(update={
            "start_seconds": word.start_seconds + 0.1,
            "end_seconds": word.end_seconds + 0.1,
        }) for word in cues[0].words),
    })
    shifted = aligned.model_copy(deep=True)
    shifted.subtitle_tracks = {"captions": aligned.subtitle_tracks["captions"].model_copy(update={"cues": (first, cues[1])})}
    failed = SubtitleSyncQCService().analyze(shifted, request)
    assert failed.status == "failed"
    assert failed.mismatched_cue_ids == ("narration.cue.001",)


def test_rendered_audio_mux_offset_is_measured_against_timeline_position(tmp_path):
    source = tmp_path / "narration.wav"
    rendered = tmp_path / "rendered.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        r"aevalsrc=if(between(t\,0.35\,0.75)\,sin(2*PI*440*t)\,if(between(t\,1.25\,1.8)\,sin(2*PI*730*t)\,0)):s=48000:d=3",
        str(source),
    ], check=True)
    timeline = _timeline(str(source), timeline_start=0.5)
    report = SubtitleAlignmentService(FakeProvider()).analyze(timeline, _request())
    cues = build_aligned_cues(report, "narration")
    timeline.subtitle_tracks = {"captions": timeline.subtitle_tracks["captions"].model_copy(update={"cues": cues})}
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-af", "adelay=500:all=1", "-t", "3.5", str(rendered),
    ], check=True)
    digest = hashlib.sha256(rendered.read_bytes()).hexdigest()
    result = SubtitleSyncQCService().analyze(timeline, SubtitleSyncQCInput(
        report=report, track_id="subtitle_main", cue_id_prefix="narration",
        rendered_media_path=str(rendered), expected_rendered_sha256=digest,
        maximum_audio_mux_offset_seconds=0.03,
    ))
    assert result.status == "passed"
    assert abs(result.audio_mux_offset_seconds or 0) <= 0.03
    assert (result.audio_correlation or 0) >= 0.9


def test_registry_and_detached_review_include_all_three_alignment_skills(tmp_path):
    _, timeline, report = _report(tmp_path)
    registry = build_production_registry(
        subtitle_alignment_service=SubtitleAlignmentService(FakeProvider())
    )
    assert registry.reference.registry_revision == 15
    assert registry.descriptor("AudioAlignTranscriptSkill").mutation is False
    assert registry.descriptor("SubtitleSyncQCSkill").mutation is False
    assert registry.descriptor("SubtitleBuildFromAlignmentSkill").mutation is True
    snapshot = TimelineSnapshotService.snapshot(timeline)
    plan = DirectorPlan(
        plan_id="plan_alignment_review", plan_version=1, created_at=NOW,
        objective="Build narration-bound captions.",
        operations=(DirectorOperation(
            operation_id="operation_alignment_build",
            tool_name="SubtitleBuildFromAlignmentSkill",
            arguments={
                "report": report.model_dump(mode="json"), "track_id": "subtitle_main",
                "cue_id_prefix": "narration", "language": "en",
            }, rationale="Use exact final narration timing.",
            expected_effect="Replace captions with word-aligned cues.",
        ),),
    )
    request = PlanDiffRequest(
        request_id="request_alignment_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=ProposedEditingExecutionPlan.from_director_plan(
            proposal_execution_id="proposal_alignment_review",
            project_id=snapshot.project_id, director_plan=plan,
        ),
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = timeline.model_dump_json()
    diff = PlanDiffEngine.generate(request, snapshot, registry)
    assert diff.review_status == "ready"
    assert sum(change.category == "subtitle_cue_addition" for change in diff.changes) == 2
    assert timeline.model_dump_json() == before


def test_alignment_provider_is_fail_closed_when_not_configured(tmp_path, monkeypatch):
    source = tmp_path / "voice.wav"
    source.write_bytes(b"voice")
    monkeypatch.delenv("VISTORA_ALIGNMENT_PYTHON", raising=False)
    monkeypatch.delenv("VISTORA_ALIGNMENT_MODEL", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        SubtitleAlignmentService().analyze(_timeline(str(source)), _request())
