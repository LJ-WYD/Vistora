"""STEP 20 subtitle contracts, tools, preview, and burn-in regression."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
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
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    DirectorOperation,
    DirectorPlan,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualSubtitleCue,
    PlanReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipConfig,
    SubtitleCue,
    SubtitleStyle,
    SubtitleTrackConfig,
    TimelineConfig,
    TrackConfig,
)
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from subtitles import (  # noqa: E402
    SubtitleCodecError,
    SubtitleEditCueInput,
    SubtitleEditEngine,
    SubtitleEditError,
    SubtitleManageTrackInput,
    SubtitleRipplePolicy,
    analyze_subtitle_layout,
    build_ass,
    burn_subtitles,
    export_subtitles,
    parse_subtitles,
)
from subtitles.transaction import SubtitleEditTransaction  # noqa: E402
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402
from timeline_preview.manual_edits import ManualEditApplicationService  # noqa: E402
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402
from timeline_edit import (  # noqa: E402
    TimelineEditEngine,
    TimelineEditError,
    TimelineEditTransaction,
    TimelineSubtitleRipplePolicy,
)


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _cue(cue_id: str, start: float, end: float, text: str) -> SubtitleCue:
    return SubtitleCue(
        cue_id=cue_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        language="en",
    )


def _timeline(*, locked: bool = False) -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video_main",
                kind="video",
                order=0,
                clips=[ClipConfig(id="clip_main", source="source.mp4", trim_out=3)],
            ),
            "audio": TrackConfig(id="audio_main", kind="audio", order=1),
        },
        subtitle_tracks={
            "captions": SubtitleTrackConfig(
                track_id="subtitle_main",
                language="en",
                order=0,
                locked=locked,
                cues=(
                    _cue("cue_first", 0.25, 1.0, "First line"),
                    _cue("cue_second", 1.25, 2.0, "Second line"),
                ),
            )
        },
    )


@contextmanager
def _server(application: PreviewApplication):
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


def _request(url: str, *, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_subtitle_models_are_frozen_strict_and_snapshot_is_detached() -> None:
    timeline = _timeline()
    style = timeline.subtitle_tracks["captions"].style
    assert style.schema_version == "1.0.0"
    assert SubtitleStyle.model_validate_json(style.model_dump_json()) == style
    with pytest.raises(ValidationError):
        style.font_size = 90
    with pytest.raises(ValidationError):
        SubtitleStyle(font_family="C:/Windows/Fonts/arial.ttf")
    with pytest.raises(ValidationError):
        SubtitleCue(cue_id="bad cue", start_seconds=0, end_seconds=1, text="x")
    with pytest.raises(ValidationError, match="overlap"):
        SubtitleTrackConfig(
            track_id="subtitle_overlap",
            cues=(_cue("cue_a", 0, 1, "A"), _cue("cue_b", 0.5, 2, "B")),
        )
    before = timeline.model_dump(mode="json")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    assert snapshot.schema_version == "11.0.0"
    assert snapshot.subtitle_track_count == 1
    assert snapshot.subtitle_cue_count == 2
    assert snapshot.subtitle_tracks[0].cues[0].text == "First line"
    assert timeline.model_dump(mode="json") == before
    with pytest.raises(ValidationError):
        snapshot.subtitle_tracks[0].language = "fr"


def test_srt_vtt_roundtrip_bom_settings_and_malformed_input() -> None:
    srt = "\ufeff1\r\n00:00:00,250 --> 00:00:01,000\r\nFirst line\r\n\r\n2\r\n00:00:01,250 --> 00:00:02,000\r\nSecond\nline\r\n"
    cues = parse_subtitles(srt, "srt", language="en")
    assert [cue.text for cue in cues] == ["First line", "Second\nline"]
    exported_srt = export_subtitles((SubtitleTrackConfig(track_id="subtitle_main", language="en", cues=cues),), "srt")
    assert parse_subtitles(exported_srt, "srt", language="en") == cues
    vtt = "WEBVTT\n\ncue_one\n00:00.250 --> 00:01.000 align:center position:50%\nHello\n"
    parsed_vtt = parse_subtitles(vtt, "vtt", language="en")
    assert parsed_vtt[0].settings == ("align:center", "position:50%")
    assert parse_subtitles(
        export_subtitles((SubtitleTrackConfig(track_id="subtitle_vtt", cues=parsed_vtt),), "vtt"),
        "vtt",
    ) == (parsed_vtt[0].model_copy(update={"language": "und"}),)
    with pytest.raises(SubtitleCodecError, match="timestamp"):
        parse_subtitles("1\nnot-a-time --> 00:00:01,000\nBad\n", "srt")
    with pytest.raises(SubtitleCodecError, match="unsupported"):
        parse_subtitles("WEBVTT\n\nSTYLE\n::cue { color: red; }\n", "vtt")


def test_subtitle_engine_precise_edits_lock_and_explicit_ripple() -> None:
    engine = SubtitleEditEngine(_timeline())
    updated, split = engine.edit_cues(SubtitleEditCueInput(
        action="split",
        track_id="subtitle_main",
        cue_id="cue_first",
        split_at_seconds=0.5,
        right_cue_id="cue_first_right",
    ))
    assert split.created_cue_ids == ("cue_first_right",)
    assert [(cue.cue_id, cue.start_seconds, cue.end_seconds) for cue in updated.subtitle_tracks["captions"].cues][:2] == [
        ("cue_first", 0.25, 0.5),
        ("cue_first_right", 0.5, 1.0),
    ]
    updated, merged = engine.edit_cues(SubtitleEditCueInput(
        action="merge",
        track_id="subtitle_main",
        merge_cue_ids=("cue_first", "cue_first_right"),
        merged_cue_id="cue_merged",
    ))
    assert merged.deleted_cue_ids == ("cue_first", "cue_first_right")
    updated, shifted = engine.edit_cues(SubtitleEditCueInput(
        action="ripple_shift",
        track_id="subtitle_main",
        anchor_seconds=1,
        delta_seconds=0.5,
    ))
    assert shifted.modified_cue_ids == ("cue_second",)
    assert updated.subtitle_tracks["captions"].cues[-1].start_seconds == 1.75
    policy_none = SubtitleRipplePolicy()
    assert SubtitleEditEngine(_timeline()).apply_ripple(anchor_seconds=1, delta_seconds=1, policy=policy_none) == ()
    policy_selected = SubtitleRipplePolicy(mode="selected_subtitle_tracks", selected_track_ids=("subtitle_main",))
    ripple_engine = SubtitleEditEngine(_timeline())
    assert ripple_engine.apply_ripple(anchor_seconds=1, delta_seconds=1, policy=policy_selected) == ("cue_second",)
    assert ripple_engine.timeline.subtitle_tracks["captions"].cues[-1].start_seconds == 2.25
    with pytest.raises(SubtitleEditError, match="locked"):
        SubtitleEditEngine(_timeline(locked=True)).edit_cues(SubtitleEditCueInput(
            action="delete", track_id="subtitle_main", cue_id="cue_first"
        ))
    with pytest.raises(SubtitleEditError, match="explicit unlock"):
        SubtitleEditEngine(_timeline(locked=True)).manage_track(SubtitleManageTrackInput(
            action="delete", track_id="subtitle_main"
        ))


def test_media_ripple_moves_only_explicit_unlocked_subtitle_tracks() -> None:
    timeline = _timeline()
    timeline.subtitle_tracks["captions"] = SubtitleTrackConfig(
        track_id="subtitle_main",
        order=0,
        cues=(_cue("cue_after_clip", 3.25, 4.0, "After"),),
    )
    unchanged, outcome = TimelineEditEngine(timeline).remove(
        "video_main",
        "clip_main",
        ripple=True,
        subtitle_ripple=TimelineSubtitleRipplePolicy(),
    )
    assert outcome.consequential_subtitle_cue_ids == ()
    assert unchanged.subtitle_tracks["captions"].cues[0].start_seconds == 3.25
    moved, outcome = TimelineEditEngine(timeline).remove(
        "video_main",
        "clip_main",
        ripple=True,
        subtitle_ripple=TimelineSubtitleRipplePolicy(
            mode="selected_subtitle_tracks",
            selected_track_ids=("subtitle_main",),
        ),
    )
    assert outcome.consequential_subtitle_cue_ids == ("cue_after_clip",)
    assert moved.subtitle_tracks["captions"].cues[0].start_seconds == 0.25
    timeline.subtitle_tracks["captions"] = timeline.subtitle_tracks["captions"].model_copy(
        update={"locked": True}
    )
    with pytest.raises(TimelineEditError, match="locked"):
        TimelineEditEngine(timeline).remove(
            "video_main",
            "clip_main",
            ripple=True,
            subtitle_ripple=TimelineSubtitleRipplePolicy(
                mode="selected_subtitle_tracks",
                selected_track_ids=("subtitle_main",),
            ),
        )


def test_registry_gateway_requires_exact_confirmation_and_is_transactional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    registry = build_production_registry()
    assert registry.reference.registry_revision == 14
    descriptor = registry.descriptor("SubtitleEditCueSkill")
    assert descriptor.transactionality == "atomic_project_state"
    assert descriptor.preview_supported is True
    request = AtomicToolRequestEnvelope(
        request_id="request_subtitle_gateway",
        execution_id="execution_subtitle_gateway",
        project_id="project_current",
        confirmation_id="confirmation_subtitle_gateway",
        plan_ref=PlanReference(plan_id="plan_subtitle", plan_version=1, plan_digest="sha256:" + "a" * 64),
        step_id="step_subtitle_gateway",
        tool_name="SubtitleEditCueSkill",
        arguments={
            "action": "update",
            "track_id": "subtitle_main",
            "cue_id": "cue_first",
            "text": "Confirmed text",
        },
        requested_at=NOW,
    )
    gateway = AtomicExecutionGateway(registry)
    before = project.read_bytes()
    rejected = gateway.execute(request, AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_current",
        confirmation_id="wrong_confirmation",
        allowed_side_effects=("files", "timeline"),
        idempotency_key="subtitle_rejected",
    ))
    assert rejected.error.code == "confirmation_binding_mismatch"
    assert project.read_bytes() == before
    context = AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_current",
        confirmation_id="confirmation_subtitle_gateway",
        allowed_side_effects=("files", "timeline"),
        idempotency_key="subtitle_apply",
    )
    applied = gateway.execute(request, context)
    assert applied.status == "success", applied.model_dump_json()
    assert applied.payload["modified_cue_ids"] == ["cue_first"]
    assert gateway.execute(request, context).replayed is True
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.subtitle_tracks["captions"].cues[0].text == "Confirmed text"
    invalid_request = request.model_copy(update={
        "request_id": "request_subtitle_invalid",
        "arguments": {"action": "trim", "track_id": "subtitle_main", "cue_id": "cue_first", "start_seconds": 2, "end_seconds": 1},
    })
    invalid = gateway.execute(invalid_request, context.model_copy(update={"idempotency_key": "subtitle_invalid"}))
    assert invalid.status == "error"
    assert project.read_bytes() != before


def test_manual_subtitle_review_writes_only_after_exact_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="proposal_subtitle_manual",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        created_at=NOW,
        edits=(ManualSubtitleCue(
            operation_id="manual_subtitle_update",
            action="update",
            track_id="subtitle_main",
            cue_id="cue_first",
            text="Manual confirmed subtitle",
        ),),
    )
    service = ManualEditApplicationService(
        TimelineSnapshotService.snapshot_current,
        build_production_registry(),
    )
    before = project.read_bytes()
    _, review = service.review(proposal.model_dump(mode="json"))
    assert review.changes[0].target_kind == "subtitle_cue"
    assert project.read_bytes() == before
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="confirmation_subtitle_manual",
        proposal=proposal,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    result = service.apply(proposal.model_dump(mode="json"), confirmation.model_dump(mode="json"))
    assert result["tool_name"] == "VideoApplyManualEditsSkill"
    saved = TimelineConfig.model_validate_json(project.read_text(encoding="utf-8"))
    assert saved.subtitle_tracks["captions"].cues[0].text == "Manual confirmed subtitle"


def test_plan_review_simulates_subtitle_changes_without_mutation() -> None:
    timeline = _timeline()
    snapshot = TimelineSnapshotService.snapshot(timeline)
    plan = DirectorPlan(
        plan_id="plan_subtitle_review",
        plan_version=1,
        objective="Add an exact reviewed subtitle.",
        operations=(DirectorOperation(
            operation_id="operation_subtitle_review",
            tool_name="SubtitleEditCueSkill",
            arguments={
                "action": "add",
                "track_id": "subtitle_main",
                "cues": [{
                    "cue_id": "cue_review",
                    "start_seconds": 2.1,
                    "end_seconds": 2.8,
                    "text": "Reviewed addition",
                    "language": "en",
                }],
            },
            rationale="Make the final statement legible.",
            expected_effect="Add one timed cue without changing media.",
        ),),
        created_at=NOW,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_subtitle_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="request_subtitle_review",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    before = timeline.model_dump_json()
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second
    assert first.review_status == "ready"
    assert any(change.category == "subtitle_cue_addition" for change in first.changes)
    assert timeline.model_dump_json() == before


def test_subtitle_transaction_restores_exact_bytes_after_persist_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / ".workspace" / "current_timeline.json"
    project.parent.mkdir()
    project.write_text(_timeline().model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project))
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(project.parent))
    before = project.read_bytes()
    replace_config = TimelineEditTransaction.replace_config

    def persist_then_fail(updated: TimelineConfig) -> None:
        replace_config(updated)
        raise OSError("simulated persistence failure")

    monkeypatch.setattr(
        TimelineEditTransaction,
        "replace_config",
        persist_then_fail,
    )
    with pytest.raises(OSError, match="simulated persistence failure"):
        SubtitleEditTransaction.apply(
            lambda engine: engine.edit_cues(
                SubtitleEditCueInput(
                    action="update",
                    track_id="subtitle_main",
                    cue_id="cue_first",
                    text="Must be rolled back",
                )
            )
        )

    assert project.read_bytes() == before
    assert not list(project.parent.glob(".*.tmp"))


def test_preview_subtitle_parse_download_and_path_redaction(tmp_path: Path) -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline())
    application = PreviewApplication(lambda: snapshot, [tmp_path])
    with _server(application) as base_url:
        status, _, body = _request(f"{base_url}/api/snapshot")
        assert status == 200
        payload = json.loads(body)
        assert payload["capabilities"]["subtitle_parse"] is True
        assert payload["snapshot"]["subtitle_tracks"][0]["cues"][0]["text"] == "First line"
        parse_status, _, parse_body = _request(
            f"{base_url}/api/subtitles/parse",
            method="POST",
            payload={
                "format": "srt",
                "language": "en",
                "content": "1\n00:00:00,000 --> 00:00:01,000\nImported\n",
            },
        )
        assert parse_status == 200
        assert json.loads(parse_body)["persisted"] is False
        query = urllib.parse.urlencode({"format": "vtt", "track_id": "subtitle_main"})
        export_status, headers, export_body = _request(f"{base_url}/api/subtitles/export?{query}")
        assert export_status == 200
        assert headers["Content-Disposition"].endswith('"vistora-subtitles.vtt"')
        assert export_body.startswith(b"WEBVTT")
        assert str(tmp_path).encode() not in body + parse_body + export_body
        invalid_status, _, invalid_body = _request(
            f"{base_url}/api/subtitles/parse",
            method="POST",
            payload={"format": "srt", "content": "C:/secret/private.srt"},
        )
        assert invalid_status == 422
        assert b"C:/secret" not in invalid_body


def test_safe_ass_and_real_burn_in_are_deterministic_and_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "base.mp4"
    burned = tmp_path / "burned.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:d=3:r=24",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True, timeout=60)
    timeline = _timeline()
    ass_first, warnings_first = build_ass(timeline, ("subtitle_main",))
    ass_second, warnings_second = build_ass(timeline, ("subtitle_main",))
    assert ass_first == ass_second
    assert warnings_first == warnings_second
    assert "Dialogue:" in ass_first and "First line" in ass_first
    result_path, warnings = burn_subtitles(str(source), str(burned), timeline, ("subtitle_main",))
    assert result_path == str(burned)
    assert isinstance(warnings, tuple)
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(burned)
    ], check=True, capture_output=True, text=True, timeout=30).stdout)
    assert any(stream["codec_type"] == "video" for stream in probe["streams"])
    assert 2.9 <= float(probe["format"]["duration"]) <= 3.1
    def frame(path: Path) -> bytes:
        return subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-ss", "0.5", "-i", str(path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ], check=True, capture_output=True, timeout=30).stdout
    base_frame, burned_frame = frame(source), frame(burned)
    assert len(base_frame) == len(burned_frame) == 320 * 180
    assert sum(abs(left - right) for left, right in zip(base_frame, burned_frame)) > 10_000
    assert not list(tmp_path.glob(".vistora-subtitles-*.ass"))
    assert not list(tmp_path.glob(".vistora-burn-*"))


def _cjk_timeline() -> TimelineConfig:
    style = SubtitleStyle(
        font_size=52,
        background_color="#000000B8",
        outline_width=3,
        safe_margin_x=0.10,
        safe_margin_y=0.145,
        bold=True,
    )
    cue = SubtitleCue(
        cue_id="cue_cjk_market_risk",
        start_seconds=0.1,
        end_seconds=1.9,
        text="标普五百和道指创下新高后高位震荡，纳指距纪录高点约百分之二。",
        language="zh-CN",
    )
    return TimelineConfig(
        width=540,
        height=960,
        fps=30,
        tracks={
            "video": TrackConfig(
                id="video_cjk",
                kind="video",
                order=0,
                clips=[ClipConfig(id="clip_cjk", source="source.mp4", trim_out=2)],
            ),
            "audio": TrackConfig(id="audio_cjk", kind="audio", order=1),
        },
        subtitle_tracks={
            "captions": SubtitleTrackConfig(
                track_id="track_cjk_captions",
                kind="subtitle",
                language="zh-CN",
                order=0,
                style=style,
                cues=(cue,),
            )
        },
    )


def test_cjk_without_spaces_is_auto_fitted_and_renderer_evidence_is_safe() -> None:
    timeline = _cjk_timeline()
    first = analyze_subtitle_layout(timeline, ("track_cjk_captions",))
    second = analyze_subtitle_layout(timeline, ("track_cjk_captions",))
    assert first == second and len(first) == 1
    evidence = first[0]
    assert evidence["safe_area_status"] == "passed"
    assert 2 <= evidence["line_count"] <= 3
    assert "\n" in evidence["rendered_text"]
    assert evidence["rendered_font_size"] < evidence["original_font_size"]
    assert evidence["maximum_line_width_px"] <= evidence["available_width_px"]
    ass, warnings = build_ass(timeline, ("track_cjk_captions",))
    assert r"\N" in ass
    assert any("auto-fitted" in warning for warning in warnings)


def test_explicit_author_line_breaks_remain_compatible_with_width_gate() -> None:
    timeline = _cjk_timeline()
    track = timeline.subtitle_tracks["captions"].model_copy(update={
        "language": "en",
        "style": SubtitleStyle(font_size=42, safe_margin_x=0.05),
        "cues": (
            SubtitleCue(
                cue_id="cue_explicit_breaks",
                start_seconds=0.1,
                end_seconds=1.9,
                text="Confirmed subtitle flow\nConfirmed subtitle flow",
                language="en",
            ),
        ),
    })
    timeline = timeline.model_copy(update={
        "width": 320,
        "height": 180,
        "subtitle_tracks": {"captions": track},
    })
    evidence = analyze_subtitle_layout(timeline, ("track_cjk_captions",))[0]
    assert evidence["safe_area_status"] == "passed"
    assert 2 <= evidence["line_count"] <= 4
    assert evidence["rendered_text"].count("\n") >= 1
    assert evidence["maximum_line_width_px"] <= evidence["available_width_px"]


def test_real_cjk_burn_stays_inside_horizontal_safe_area(tmp_path: Path) -> None:
    source = tmp_path / "cjk-base.mp4"
    burned = tmp_path / "cjk-burned.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=540x960:d=2:r=30",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True, timeout=60)
    timeline = _cjk_timeline()
    burn_subtitles(str(source), str(burned), timeline, ("track_cjk_captions",))

    def rgb_frame(path: Path) -> bytes:
        return subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-ss", "0.5", "-i", str(path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ], check=True, capture_output=True, timeout=30).stdout

    before = rgb_frame(source)
    after = rgb_frame(burned)
    changed_x = []
    for pixel in range(540 * 960):
        offset = pixel * 3
        if max(abs(after[offset + channel] - before[offset + channel]) for channel in range(3)) > 20:
            changed_x.append(pixel % 540)
    assert changed_x
    margin = round(540 * timeline.subtitle_tracks["captions"].style.safe_margin_x)
    assert min(changed_x) >= margin - 8
    assert max(changed_x) <= 539 - margin + 8
