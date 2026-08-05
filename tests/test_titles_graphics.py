"""Original O13 word timing, titles, images, and stickers regression."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from atomic_runtime import AtomicExecutionContext, AtomicExecutionGateway, build_production_registry  # noqa: E402
from contracts import AtomicToolRequestEnvelope, DirectorOperation, DirectorPlan, PlanReference  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipConfig,
    SubtitleCue,
    SubtitleTrackConfig,
    SubtitleWord,
    TimelineConfig,
    TimelineRenderer,
    TrackConfig,
)
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    PreviewMaterialFact,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from subtitles import SubtitleEditCueInput, SubtitleEditEngine, SubtitleEditError, build_ass  # noqa: E402
from timeline_preview import PreviewApplication  # noqa: E402
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402


NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _word(word_id: str, start: float, end: float, text: str) -> SubtitleWord:
    return SubtitleWord(
        word_id=word_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=0.9,
    )


def _timeline(*, source: str = "base.mp4", locked: bool = False) -> TimelineConfig:
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
                clips=[ClipConfig(id="clip_base", source=source, trim_out=2, keep_audio=False)],
            ),
            "overlay": TrackConfig(id="track_overlay", kind="video", order=1),
            "audio": TrackConfig(id="track_audio", kind="audio", order=2),
        },
        subtitle_tracks={
            "captions": SubtitleTrackConfig(
                track_id="track_captions",
                kind="subtitle",
                language="en",
                cues=(SubtitleCue(
                    cue_id="cue_words",
                    start_seconds=0.2,
                    end_seconds=1.2,
                    text="Hello world",
                    language="en",
                    words=(
                        _word("word_hello", 0.2, 0.6, "Hello"),
                        _word("word_world", 0.7, 1.2, "world"),
                    ),
                ),),
            ),
            "titles": SubtitleTrackConfig(
                track_id="track_titles",
                kind="text",
                role="titles",
                order=1,
                allow_overlaps=True,
                cues=(SubtitleCue(
                    cue_id="title_main",
                    cue_kind="title",
                    start_seconds=0.25,
                    end_seconds=1.75,
                    text="Vistora",
                ),),
            ),
        },
    )


def _configure_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timeline: TimelineConfig,
) -> Path:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(timeline.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    return project


def _graphic(path: Path, *, alpha: bool) -> None:
    mode = "RGBA" if alpha else "RGB"
    color = (255, 24, 24, 160) if alpha else (255, 24, 24)
    Image.new(mode, (96, 72), color).save(path)


def test_word_title_and_static_graphic_contracts_are_strict_and_legacy_safe() -> None:
    timeline = _timeline()
    assert TimelineConfig.model_validate_json(timeline.model_dump_json()) == timeline
    snapshot = TimelineSnapshotService.snapshot(timeline)
    assert snapshot.schema_version == "9.0.0"
    assert snapshot.subtitle_tracks[0].cues[0].word_count == 2
    assert snapshot.subtitle_tracks[1].cues[0].cue_kind == "title"
    detached_title_sidecar = PreviewApplication(lambda: snapshot).subtitle_export(
        format_name="vtt",
        track_ids=("track_titles",),
    )
    assert detached_title_sidecar.startswith("WEBVTT") and "Vistora" in detached_title_sidecar
    with pytest.raises(ValidationError, match="inside"):
        SubtitleCue(
            cue_id="cue_bad_word",
            start_seconds=1,
            end_seconds=2,
            text="bad",
            words=(_word("word_bad", 0.5, 1.5, "bad"),),
        )
    with pytest.raises(ValidationError, match="title cue"):
        SubtitleTrackConfig(
            track_id="track_text_bad",
            kind="text",
            cues=(SubtitleCue(cue_id="cue_plain", start_seconds=0, end_seconds=1, text="x"),),
        )
    legacy = TimelineConfig.model_validate({
        "width": 320,
        "height": 180,
        "fps": 24,
        "tracks": {"video": {"id": "video", "clips": [{"id": "legacy_clip", "source": "legacy.mp4", "trim_out": 1}]}},
    })
    assert legacy.tracks["video"].clips[0].visual_kind == "video"


def test_word_timing_edits_preserve_exact_time_semantics() -> None:
    engine = SubtitleEditEngine(_timeline())
    with pytest.raises(SubtitleEditError, match="timed word"):
        engine.edit_cues(SubtitleEditCueInput(
            action="split",
            track_id="track_captions",
            cue_id="cue_words",
            split_at_seconds=0.4,
            right_cue_id="cue_right",
        ))
    updated, outcome = engine.edit_cues(SubtitleEditCueInput(
        action="split",
        track_id="track_captions",
        cue_id="cue_words",
        split_at_seconds=0.65,
        right_cue_id="cue_right",
    ))
    assert outcome.created_cue_ids == ("cue_right",)
    left, right = updated.subtitle_tracks["captions"].cues
    assert [word.word_id for word in left.words] == ["word_hello"]
    assert [word.word_id for word in right.words] == ["word_world"]
    updated, _ = engine.edit_cues(SubtitleEditCueInput(
        action="move",
        track_id="track_captions",
        cue_id="cue_right",
        timeline_start_seconds=2,
    ))
    moved = updated.subtitle_tracks["captions"].cues[-1]
    assert moved.words[0].start_seconds == pytest.approx(2.05)


def test_graphic_gateway_requires_confirmation_validates_alpha_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _configure_project(tmp_path, monkeypatch, _timeline())
    image = tmp_path / "card.png"
    sticker = tmp_path / "sticker.png"
    _graphic(image, alpha=False)
    _graphic(sticker, alpha=True)
    registry = build_production_registry()
    assert registry.reference.registry_revision == 11 and len(registry) == 42
    descriptor = registry.descriptor("VideoInsertGraphicSkill")
    assert descriptor.preview_supported is True
    assert descriptor.transactionality == "atomic_project_state"
    request = AtomicToolRequestEnvelope(
        request_id="request_graphic",
        execution_id="execution_graphic",
        project_id="project_current",
        confirmation_id="confirmation_graphic",
        plan_ref=PlanReference(
            plan_id="plan_graphic",
            plan_version=1,
            plan_digest="sha256:" + "a" * 64,
        ),
        step_id="step_graphic",
        tool_name="VideoInsertGraphicSkill",
        arguments={
            "track_id": "track_overlay",
            "clip_id": "clip_sticker",
            "source_path": str(sticker),
            "graphic_kind": "sticker",
            "timeline_start": 0.25,
            "duration_seconds": 1.25,
            "mode": "insert",
        },
        requested_at=NOW,
    )
    gateway = AtomicExecutionGateway(registry)
    before = project.read_bytes()
    rejected = gateway.execute(request, AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_current",
        confirmation_id="wrong",
        allowed_side_effects=("files", "timeline"),
        idempotency_key="graphic_rejected",
    ))
    assert rejected.status == "error" and project.read_bytes() == before
    context = AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_current",
        confirmation_id="confirmation_graphic",
        allowed_side_effects=("files", "timeline"),
        idempotency_key="graphic_apply",
    )
    result = gateway.execute(request, context)
    assert result.status == "success"
    assert gateway.execute(request, context).replayed is True
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.tracks["overlay"].clips[0].visual_kind == "sticker"
    assert str(tmp_path) not in result.model_dump_json()
    invalid = request.model_copy(update={
        "request_id": "request_bad_sticker",
        "arguments": {**request.arguments, "clip_id": "clip_bad_sticker", "source_path": str(image)},
    })
    failed = gateway.execute(invalid, context.model_copy(update={"idempotency_key": "graphic_bad"}))
    assert failed.status == "error" and failed.error.code == "atomic_dispatch_failed"
    assert "card.png" not in failed.model_dump_json()


def test_graphic_plan_review_is_detached_deterministic_and_image_bound() -> None:
    timeline = _timeline(source="material://source_bbbbbbbbbbbbbbbb")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    plan = DirectorPlan(
        plan_id="plan_graphic_review",
        plan_version=1,
        objective="Add a reviewed brand sticker.",
        operations=(DirectorOperation(
            operation_id="operation_graphic_review",
            tool_name="VideoInsertGraphicSkill",
            arguments={
                "track_id": "track_overlay",
                "clip_id": "clip_review_sticker",
                "source_path": "material://source_aaaaaaaaaaaaaaaa",
                "graphic_kind": "sticker",
                "timeline_start": 0.5,
                "duration_seconds": 1,
                "mode": "insert",
            },
            rationale="Place an accepted, evidence-backed graphic.",
            expected_effect="Add one static sticker layer.",
        ),),
        created_at=NOW,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="execution_graphic_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="request_graphic_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
        material_facts=(PreviewMaterialFact(
            material_id="source_aaaaaaaaaaaaaaaa",
            media_kind="image",
            width=96,
            height=72,
        ),),
    )
    before = timeline.model_dump_json()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second and first.review_status == "ready"
    addition = next(change for change in first.changes if change.category == "clip_addition")
    assert addition.after.visual_kind == "sticker"
    assert timeline.model_dump_json() == before
    assert "C:/" not in first.model_dump_json()


def test_static_image_sticker_and_title_render_are_real(tmp_path: Path) -> None:
    base = tmp_path / "base.mp4"
    sticker = tmp_path / "sticker.png"
    output = tmp_path / "graphic.mp4"
    _graphic(sticker, alpha=True)
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2:r=24",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base),
    ], check=True, timeout=60)
    timeline = _timeline(source=str(base))
    timeline.tracks["overlay"].clips.append(ClipConfig(
        id="clip_sticker",
        source=str(sticker),
        visual_kind="sticker",
        trim_out=1.5,
        timeline_start=0.25,
        keep_audio=False,
    ))
    TimelineRenderer(timeline).render(str(output))
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output),
    ], check=True, capture_output=True, text=True, timeout=30).stdout)
    assert any(stream["codec_type"] == "video" for stream in probe["streams"])
    assert 1.9 <= float(probe["format"]["duration"]) <= 2.1

    def frame(path: Path, time: float) -> bytes:
        return subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-ss", str(time), "-i", str(path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ], check=True, capture_output=True, timeout=30).stdout

    assert frame(base, 0.75) != frame(output, 0.75)
    ass, warnings = build_ass(timeline, ("track_titles",))
    assert "Vistora" in ass and isinstance(warnings, tuple)


def test_browser_assets_expose_word_title_and_allowlisted_graphic_controls() -> None:
    html = (SRC / "timeline_preview" / "static" / "index.html").read_text(encoding="utf-8")
    script = (SRC / "timeline_preview" / "static" / "app.js").read_text(encoding="utf-8")
    css = (SRC / "timeline_preview" / "static" / "app.css").read_text(encoding="utf-8")
    for marker in (
        'id="preview-image"',
        'id="subtitle-track-kind"',
        'id="subtitle-cue-kind"',
        'id="subtitle-words"',
    ):
        assert marker in html
    assert 'classList.add("has-image")' in script
    assert "Word timings must be a JSON array" in script
    assert ".monitor.has-image" in css
    assert "C:/" not in html + script + css
