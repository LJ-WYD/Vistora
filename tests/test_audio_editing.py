"""STEP 19 deterministic audio contracts, edits, analysis, and rendering."""

from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import wave
from contextlib import contextmanager
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
from audio_analysis import (  # noqa: E402
    LoudnessAnalysisRequest,
    LoudnessAnalysisService,
)
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    DirectorOperation,
    DirectorPlan,
    ManualClipAudio,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualTrackMix,
    ManualVolumeEnvelope,
    PlanReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    AppliedLoudnessNormalization,
    AudioEnvelopePoint,
    ClipAudioSettings,
    ClipConfig,
    TimelineConfig,
    TimelineRenderer,
    TrackConfig,
    TrackMixSettings,
)
from timeline_edit import TimelineEditEngine, TimelineEditError  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import TimelineSnapshotReference  # noqa: E402
from timeline_preview.manual_edits import (  # noqa: E402
    ManualEditApplicationService,
    ManualEditValidationError,
)
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


@contextmanager
def _preview_server(application: PreviewApplication):
    server = create_preview_server(application, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _wave(path: Path, *, frequency: float, amplitude: float = 0.25) -> None:
    sample_rate = 48_000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate):
            value = int(
                32767 * amplitude * math.sin(2 * math.pi * frequency * index / sample_rate)
            )
            frames.extend(struct.pack("<h", value))
        output.writeframes(bytes(frames))


def _timeline(source: str = "tone.wav") -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(id="video", kind="video", order=0),
            "dialogue": TrackConfig(
                id="audio_dialogue",
                kind="audio",
                order=1,
                clips=[
                    ClipConfig(
                        id="audio_clip",
                        source=source,
                        trim_out=1,
                    )
                ],
            ),
        },
    )


def test_audio_models_are_frozen_strict_and_legacy_defaults_are_equivalent() -> None:
    point = AudioEnvelopePoint(
        point_id="point_a", offset_seconds=0.25, gain_db=-3
    )
    settings = ClipAudioSettings(envelope=(point,))
    assert point.schema_name == "vistora.audio-envelope-point"
    assert settings.schema_name == "vistora.clip-audio-settings"
    assert ClipAudioSettings.model_validate_json(settings.model_dump_json()) == settings
    with pytest.raises(ValidationError):
        settings.gain_db = 2
    with pytest.raises(ValidationError):
        ClipAudioSettings(envelope=(point, point))
    legacy = TimelineConfig.model_validate(
        {
            "tracks": {
                "audio": {
                    "id": "audio",
                    "clips": [
                        {
                            "id": "clip_legacy",
                            "source": "legacy.wav",
                            "trim_out": 1,
                            "volume": 0.5,
                        }
                    ],
                }
            }
        }
    )
    clip = legacy.tracks["audio"].clips[0]
    assert clip.volume == 0.5
    assert clip.audio == ClipAudioSettings()
    assert legacy.tracks["audio"].mix == TrackMixSettings()


def test_clip_track_and_envelope_edits_are_exact_and_locked_tracks_fail() -> None:
    engine = TimelineEditEngine(_timeline())
    updated, outcome = engine.set_clip_audio(
        "audio_dialogue",
        "audio_clip",
        gain_db=-4,
        muted=False,
        pan=0.25,
        fade_in_seconds=0.1,
        fade_out_seconds=0.2,
        playback_rate=1.25,
        normalization=None,
    )
    clip = updated.tracks["dialogue"].clips[0]
    assert outcome.operation == "set_clip_audio"
    assert (clip.audio.gain_db, clip.audio.pan, clip.speed_factor) == (-4, 0.25, 1.25)
    updated, _ = engine.set_volume_envelope(
        "audio_dialogue",
        "audio_clip",
        action="upsert",
        point_id="point_a",
        offset_seconds=0.25,
        gain_db=-6,
    )
    assert updated.tracks["dialogue"].clips[0].audio.envelope[0].point_id == "point_a"
    updated, _ = engine.set_track_mix(
        "audio_dialogue", gain_db=-2, muted=False, pan=-0.3
    )
    assert updated.tracks["dialogue"].mix.gain_db == -2
    updated.tracks["dialogue"].locked = True
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(updated).set_track_mix(
            "audio_dialogue", gain_db=0, muted=None, pan=None
        )


def test_audio_rate_does_not_implicitly_detach_embedded_video_audio() -> None:
    timeline = TimelineConfig(
        tracks={
            "video": TrackConfig(
                id="video",
                kind="video",
                clips=[ClipConfig(id="video_clip", source="v.mp4", trim_out=2)],
            )
        }
    )
    with pytest.raises(TimelineEditError, match="shared clip speed"):
        TimelineEditEngine(timeline).set_clip_audio(
            "video",
            "video_clip",
            gain_db=None,
            muted=None,
            pan=None,
            fade_in_seconds=None,
            fade_out_seconds=None,
            playback_rate=2,
            normalization=None,
        )


def test_split_and_trim_keep_envelopes_bounded_and_deterministic() -> None:
    timeline = _timeline()
    timeline.tracks["dialogue"].clips[0].audio = ClipAudioSettings(
        fade_in_seconds=0.2,
        fade_out_seconds=0.2,
        envelope=(
            AudioEnvelopePoint(point_id="point_a", offset_seconds=0, gain_db=-12),
            AudioEnvelopePoint(point_id="point_b", offset_seconds=1, gain_db=0),
        ),
    )
    ids = iter(("envelope_left", "envelope_right", "clip_right"))
    updated, _ = TimelineEditEngine(
        timeline, id_factory=lambda _prefix: next(ids)
    ).split("audio_dialogue", "audio_clip", 0.5)
    left, right = updated.tracks["dialogue"].clips
    assert left.audio.fade_out_seconds == 0
    assert right.audio.fade_in_seconds == 0
    assert all(point.offset_seconds <= 0.5 for point in left.audio.envelope)
    assert all(point.offset_seconds <= 0.5 for point in right.audio.envelope)
    TimelineEditEngine.validate(updated)


def test_loudness_analysis_is_deterministic_cached_and_browser_safe(tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    _wave(source, frequency=440)
    service = LoudnessAnalysisService(max_cache_entries=2)
    request = LoudnessAnalysisRequest(
        track_id="audio_dialogue", clip_id="audio_clip"
    )
    first = service.analyze(_timeline(str(source)), request)
    second = service.analyze(_timeline(str(source)), request)
    assert first.analysis_id == second.analysis_id
    assert first.cache_key == second.cache_key
    assert second.cached is True
    payload = second.model_dump_json()
    assert str(tmp_path) not in payload
    assert -120 <= first.integrated_lufs <= 20
    assert -60 <= first.recommended_gain_db <= 24


def test_registry_gateway_requires_exact_gate_and_applies_analysis_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "tone.wav"
    _wave(source, frequency=330)
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    timeline = _timeline(str(source))
    project.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    registry = build_production_registry()
    assert registry.reference.registry_revision == 6
    assert registry.descriptor("AudioAnalyzeLoudnessSkill").mutation is False
    assert registry.descriptor("AudioSetClipPropertiesSkill").transactionality == "atomic_project_state"
    analysis = LoudnessAnalysisService().analyze(
        timeline,
        LoudnessAnalysisRequest(track_id="audio_dialogue", clip_id="audio_clip"),
    )
    evidence = AppliedLoudnessNormalization(
        analysis_id=analysis.analysis_id,
        analyzed_clip_digest=analysis.analyzed_clip_digest,
        source_sha256=analysis.source_sha256,
        integrated_lufs=analysis.integrated_lufs,
        true_peak_dbfs=analysis.true_peak_dbfs,
        target_lufs=analysis.target_lufs,
        max_true_peak_dbfs=analysis.max_true_peak_dbfs,
        applied_gain_db=analysis.recommended_gain_db,
    )
    assert evidence.schema_name == "vistora.applied-loudness-normalization"
    request = AtomicToolRequestEnvelope(
        request_id="request_audio_apply",
        execution_id="execution_audio_apply",
        project_id="project_current",
        confirmation_id="confirmation_audio",
        plan_ref=PlanReference(
            plan_id="plan_audio",
            plan_version=1,
            plan_digest="sha256:" + "a" * 64,
        ),
        step_id="step_audio_apply",
        tool_name="AudioSetClipPropertiesSkill",
        arguments={
            "track_id": "audio_dialogue",
            "clip_id": "audio_clip",
            "gain_db": analysis.recommended_gain_db,
            "normalization_evidence": evidence.model_dump(mode="json"),
        },
        requested_at=NOW,
    )
    gateway = AtomicExecutionGateway(registry)
    rejected = gateway.execute(
        request,
        AtomicExecutionContext(
            caller="workflow",
            registry_ref=registry.reference,
            project_id="project_current",
            confirmation_id="wrong_confirmation",
            allowed_side_effects=("files", "timeline"),
            idempotency_key="reject_audio",
        ),
    )
    assert rejected.status == "error"
    accepted = gateway.execute(
        request,
        AtomicExecutionContext(
            caller="workflow",
            registry_ref=registry.reference,
            project_id="project_current",
            confirmation_id="confirmation_audio",
            allowed_side_effects=("files", "timeline"),
            idempotency_key="apply_audio",
        ),
    )
    assert accepted.status == "success"
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.tracks["dialogue"].clips[0].audio.normalization.analysis_id == analysis.analysis_id
    before_stale = project.read_bytes()
    _wave(source, frequency=880)
    stale_request = request.model_copy(
        update={"request_id": "request_audio_stale", "step_id": "step_audio_stale"}
    )
    stale = gateway.execute(
        stale_request,
        AtomicExecutionContext(
            caller="workflow",
            registry_ref=registry.reference,
            project_id="project_current",
            confirmation_id="confirmation_audio",
            allowed_side_effects=("files", "timeline"),
            idempotency_key="stale_audio",
        ),
    )
    assert stale.status == "error"
    assert project.read_bytes() == before_stale


def test_advanced_multitrack_render_is_stereo_48k_and_limited(tmp_path: Path) -> None:
    video = tmp_path / "black.mp4"
    tone_a = tmp_path / "a.wav"
    tone_b = tmp_path / "b.wav"
    output = tmp_path / "mix.mp4"
    _wave(tone_a, frequency=220, amplitude=0.65)
    _wave(tone_b, frequency=440, amplitude=0.65)
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=1",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )
    timeline = TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video", kind="video", order=0,
                clips=[ClipConfig(id="video_clip", source=str(video), trim_out=1, keep_audio=False)],
            ),
            "music": TrackConfig(
                id="audio_music", kind="audio", order=1,
                mix=TrackMixSettings(gain_db=-6, pan=-0.3),
                clips=[ClipConfig(
                    id="music_clip", source=str(tone_a), trim_out=1,
                    audio=ClipAudioSettings(
                        fade_in_seconds=0.1,
                        envelope=(
                            AudioEnvelopePoint(point_id="music_a", offset_seconds=0, gain_db=-12),
                            AudioEnvelopePoint(point_id="music_b", offset_seconds=1, gain_db=0),
                        ),
                    ),
                )],
            ),
            "voice": TrackConfig(
                id="audio_voice", kind="audio", order=2,
                clips=[ClipConfig(
                    id="voice_clip", source=str(tone_b), trim_out=1,
                    audio=ClipAudioSettings(gain_db=-3, pan=0.25, fade_out_seconds=0.1),
                )],
            ),
        },
    )
    assert TimelineRenderer(timeline).render(str(output)) == str(output)
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    audio = next(stream for stream in payload["streams"] if stream["codec_type"] == "audio")
    assert audio["sample_rate"] == "48000"
    assert audio["channels"] == 2
    assert 0.9 <= float(payload["format"]["duration"]) <= 1.1
    measured = LoudnessAnalysisService().analyze(
        _timeline(str(output)),
        LoudnessAnalysisRequest(
            track_id="audio_dialogue",
            clip_id="audio_clip",
        ),
    )
    assert -70 < measured.integrated_lufs < 0
    assert measured.true_peak_dbfs <= 0.5


def test_snapshot_detaches_audio_state() -> None:
    timeline = _timeline()
    timeline.tracks["dialogue"].mix = TrackMixSettings(gain_db=-4)
    timeline.tracks["dialogue"].clips[0].audio = ClipAudioSettings(
        gain_db=-2,
        envelope=(AudioEnvelopePoint(point_id="point_a", offset_seconds=0.5, gain_db=-8),),
    )
    snapshot = TimelineSnapshotService.snapshot(timeline)
    track = next(item for item in snapshot.tracks if item.track_id == "audio_dialogue")
    assert track.mix_gain_db == -4
    assert track.clips[0].audio_envelope == (("point_a", 0.5, -8.0),)
    with pytest.raises(ValidationError):
        track.mix_gain_db = 0


def test_plan_review_simulates_audio_changes_without_mutation() -> None:
    timeline = _timeline("material://source_1111111111111111")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    operations = (
        DirectorOperation(
            operation_id="operation_audio_gain",
            tool_name="AudioSetClipPropertiesSkill",
            arguments={
                "track_id": "audio_dialogue",
                "clip_id": "audio_clip",
                "gain_db": -5,
                "pan": 0.2,
                "fade_in_seconds": 0.1,
            },
            rationale="Balance the dialogue locally.",
            expected_effect="Lower and pan only the selected audio component.",
        ),
        DirectorOperation(
            operation_id="operation_audio_envelope",
            tool_name="AudioSetVolumeEnvelopeSkill",
            arguments={
                "track_id": "audio_dialogue",
                "clip_id": "audio_clip",
                "action": "upsert",
                "point_id": "point_review",
                "offset_seconds": 0.5,
                "gain_db": -8,
            },
            rationale="Create a deterministic dialogue dip.",
            expected_effect="Add one linear gain point.",
        ),
    )
    plan = DirectorPlan(
        plan_id="plan_audio_review",
        plan_version=1,
        objective="Review a bounded audio balance.",
        operations=operations,
        created_at=NOW,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_audio_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="request_audio_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = timeline.model_dump_json()
    diff = PlanDiffEngine.generate(request, snapshot, registry)
    assert diff.review_status == "ready"
    assert {change.category for change in diff.changes} >= {
        "clip_audio",
        "audio_envelope",
    }
    assert timeline.model_dump_json() == before
    assert TimelineSnapshotService.snapshot(timeline) == snapshot


def test_manual_audio_draft_requires_exact_confirmation_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "tone.wav"
    _wave(source, frequency=550)
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline(str(source)).model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="manual_audio_proposal",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        created_at=NOW,
        edits=(
            ManualClipAudio(
                operation_id="manual_audio_clip",
                track_key="dialogue",
                track_id="audio_dialogue",
                clip_id="audio_clip",
                gain_db=-3,
                pan=0.1,
                fade_in_seconds=0.1,
            ),
            ManualTrackMix(
                operation_id="manual_audio_track",
                track_key="dialogue",
                track_id="audio_dialogue",
                gain_db=-2,
                muted=False,
            ),
            ManualVolumeEnvelope(
                operation_id="manual_audio_envelope",
                track_key="dialogue",
                track_id="audio_dialogue",
                clip_id="audio_clip",
                action="upsert",
                point_id="point_manual",
                offset_seconds=0.5,
                gain_db=-8,
            ),
        ),
    )
    application = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        build_production_registry(),
    )
    before = project.read_bytes()
    _, review = application.review(proposal.model_dump(mode="json"))
    assert project.read_bytes() == before
    rejected = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="manual_audio_rejected",
        proposal=proposal,
        confirmed_by="local_user",
        decision="rejected",
        recorded_at=NOW,
    )
    with pytest.raises(ManualEditValidationError):
        application.apply(proposal, rejected)
    assert project.read_bytes() == before
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="manual_audio_confirmed",
        proposal=proposal,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    result = application.apply(proposal, confirmation)
    assert result["confirmation_id"] == "manual_audio_confirmed"
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    clip = saved.tracks["dialogue"].clips[0]
    assert (clip.audio.gain_db, clip.audio.pan) == (-3, 0.1)
    assert clip.audio.envelope[0].point_id == "point_manual"
    assert saved.tracks["dialogue"].mix.gain_db == -2
    assert review.changes


def test_loudness_http_route_is_read_only_and_path_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "private-tone.wav"
    _wave(source, frequency=660)
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline(str(source)).model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    before = project.read_bytes()
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        [tmp_path],
        skill_registry=build_production_registry(),
        manual_edits_enabled=True,
    )
    with _preview_server(application) as base_url:
        body = json.dumps(
            {
                "track_id": "audio_dialogue",
                "clip_id": "audio_clip",
                "target_lufs": -16,
                "max_true_peak_dbfs": -1,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/audio/loudness/analyze",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
        assert payload["schema_name"] == "vistora.loudness-analysis-result"
        assert str(tmp_path) not in json.dumps(payload)
        assert project.read_bytes() == before
