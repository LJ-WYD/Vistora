import ast
import json
import struct
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from contracts import (  # noqa: E402
    ManualClipUpdate,
    ManualEditConfirmationRecord,
    ManualEditProposal,
)
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from director import DirectorHistoryView  # noqa: E402
from skills.video_apply_manual_edits import (  # noqa: E402
    VideoApplyManualEditsSkill,
)
from media_analysis import MediaAnalysisService  # noqa: E402
from timeline_preview import (  # noqa: E402
    MediaResolver,
    PreviewApplication,
    create_preview_server,
)
from timeline_preview.server import PreviewConfigurationError  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402


def _timeline(source: str) -> TimelineConfig:
    return TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[
                    ClipConfig(
                        id="clip_preview",
                        source=source,
                        trim_in=0.0,
                        trim_out=2.0,
                        timeline_start=0.0,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(id="audio"),
            "captions": TrackConfig(id="captions"),
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


def _request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = dict(headers or {})
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_snapshot_endpoint_and_static_assets_are_read_only(
    tmp_path: Path,
) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"0123456789")
    snapshot = TimelineSnapshotService.snapshot(_timeline(media.name))
    application = PreviewApplication(lambda: snapshot, [tmp_path])

    with _server(application) as base_url:
        status, headers, body = _request(f"{base_url}/api/snapshot")
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        assert headers["Content-Security-Policy"]
        payload = json.loads(body)
        assert payload["api_version"] == "1.0.0"
        assert payload["read_only"] is True
        assert payload["snapshot"]["schema_name"] == (
            "vistora.timeline-snapshot"
        )
        assert payload["snapshot"]["tracks"][0]["track_key"] == "video"
        source_id = snapshot.tracks[0].clips[0].source.source_id
        browser_source = payload["snapshot"]["tracks"][0]["clips"][0][
            "source"
        ]
        assert browser_source["reference_type"] == (
            "opaque_preview_reference"
        )
        assert browser_source["value"] == f"media:{source_id}"
        assert str(tmp_path).encode() not in body
        assert payload["media"][source_id] == {
            "available": True,
            "content_type": "video/mp4",
            "reason": None,
            "size_bytes": 10,
            "url": f"/media/{source_id}",
        }
        assert payload["capabilities"]["timeline_mutation"] is False
        assert payload["capabilities"]["direct_timeline_mutation"] is False
        assert payload["capabilities"]["tool_execution"] is False
        assert payload["capabilities"]["manual_edit_apply"] is False
        assert payload["capabilities"]["confirmed_manual_dispatch"] is False
        assert payload["capabilities"]["media_analysis"] is True

        for route, content_type, marker in [
            ("/", "text/html", b"Confirm &amp; apply"),
            ("/app.css", "text/css", b".waveform"),
            ("/app.js", "text/javascript", b"/api/director"),
        ]:
            asset_status, asset_headers, asset_body = _request(
                f"{base_url}{route}"
            )
            assert asset_status == 200
            assert asset_headers["Content-Type"].startswith(content_type)
            assert marker in asset_body


def test_director_history_endpoint_is_read_only_and_path_safe(
    tmp_path: Path,
) -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline("missing.mp4"))
    history = DirectorHistoryView(
        session_id="session_preview_director",
        project_id=snapshot.project_id,
        ledger_revision=1,
        integrity_digest="sha256:" + ("1" * 64),
        latest_status="needs_clarification",
        latest_brief={
            "brief_version": 1,
            "content_digest": "sha256:" + ("2" * 64),
            "readiness": "needs_clarification",
            "readiness_reasons": ["Audience is unresolved."],
            "objective": "Prepare a grounded cut.",
            "audience": None,
            "platform": "Web",
            "target_duration_seconds": 15.0,
            "style": "Clean",
            "narrative": "Single source",
            "pacing": "Steady",
            "must_haves": [],
            "must_not_haves": [],
            "delivery_requirements": ["H.264 MP4"],
            "material_ids": [],
            "evidence_ids": [],
            "assumptions": [],
            "unresolved_questions": ["Who is the audience?"],
            "acceptance_criteria": [],
        },
        turns=(
            {
                "turn_id": "turn_preview_director",
                "turn_index": 1,
                "status": "needs_clarification",
                "assistant_message": "Who is the intended audience?",
                "clarification_questions": ["Who is the intended audience?"],
                "brief_version": 1,
                "context_digest": "sha256:" + ("3" * 64),
                "error": None,
                "withdrawn_proposal_id": None,
            },
        ),
    )
    application = PreviewApplication(
        lambda: snapshot,
        [tmp_path],
        director_history_provider=lambda: history,
    )
    with _server(application) as base_url:
        status, _, body = _request(f"{base_url}/api/director")
        assert status == 200
        payload = json.loads(body)
        assert payload["schema_name"] == "vistora.director-history"
        assert payload["latest_status"] == "needs_clarification"
        assert "arguments" not in payload
        assert str(tmp_path).encode() not in body
        write_status, headers, write_body = _request(
            f"{base_url}/api/director",
            method="POST",
            json_body={},
        )
        assert write_status == 405
        assert headers["Allow"] == "GET, HEAD"
        assert json.loads(write_body)["error"]["code"] == "read_only"


def test_analysis_endpoint_is_cached_safe_aligned_and_isolated(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    audio = tmp_path / "source.wav"
    video.write_bytes(b"video-source")
    audio.write_bytes(b"audio-source")
    timeline = _timeline(str(video))
    timeline.tracks["audio"].clips.append(
        ClipConfig(
            id="clip_audio",
            source=str(audio),
            trim_in=0.0,
            trim_out=2.0,
            timeline_start=1.0,
        )
    )
    snapshot = TimelineSnapshotService.snapshot(timeline)
    before_timeline = timeline.model_dump(mode="json")
    before_files = {
        path.name: path.read_bytes()
        for path in (video, audio)
    }
    calls: list[tuple[str, ...]] = []
    audio_samples = struct.pack("<32f", *([0.5, -0.5] * 16))

    def fake_runner(command: list[str], timeout: float) -> bytes:
        calls.append(tuple(command))
        if "f32le" in command:
            return audio_samples
        return b"\x89PNG\r\n\x1a\npreview"

    analysis_service = MediaAnalysisService(
        command_runner=fake_runner
    )
    application = PreviewApplication(
        lambda: snapshot,
        [tmp_path],
        analysis_service=analysis_service,
    )

    with _server(application) as base_url:
        status, _, body = _request(f"{base_url}/api/analysis")
        assert status == 200
        payload = json.loads(body)
        assert payload["schema_name"] == (
            "vistora.media-analysis-collection"
        )
        assert payload["schema_version"] == "1.0.0"
        assert payload["snapshot_id"] == snapshot.snapshot_id
        assert [result["media_kind"] for result in payload["results"]] == [
            "video",
            "audio",
        ]
        video_result, audio_result = payload["results"]
        assert video_result["status"] == "ready"
        assert len(video_result["thumbnails"]) == 3
        assert audio_result["status"] == "ready"
        assert audio_result["waveform"][0][
            "timeline_start_seconds"
        ] == 1.0
        assert audio_result["waveform"][-1][
            "timeline_end_seconds"
        ] == 3.0
        assert str(tmp_path).encode() not in body

        thumbnail = video_result["thumbnails"][0]
        artifact_url = (
            f"{base_url}/analysis/thumbnail/"
            f"{video_result['analysis_id']}/{thumbnail['artifact_id']}"
        )
        artifact_status, artifact_headers, artifact_body = _request(
            artifact_url
        )
        assert artifact_status == 200
        assert artifact_headers["Content-Type"] == "image/png"
        assert artifact_body.startswith(b"\x89PNG")
        head_status, _, head_body = _request(
            artifact_url,
            method="HEAD",
        )
        assert head_status == 200
        assert head_body == b""

        repeat_status, _, repeat_body = _request(
            f"{base_url}/api/analysis"
        )
        assert repeat_status == 200
        assert repeat_body == body
        assert analysis_service.cache_hits == 2
        assert len(calls) == 4

        invalid_status, _, invalid_body = _request(
            f"{base_url}/analysis/thumbnail/..%2F..%2Fsecret/file"
        )
        assert invalid_status == 404
        assert str(tmp_path).encode() not in invalid_body

    assert timeline.model_dump(mode="json") == before_timeline
    assert {
        path.name: path.read_bytes()
        for path in (video, audio)
    } == before_files


def test_analysis_missing_media_returns_placeholder_contract(
    tmp_path: Path,
) -> None:
    snapshot = TimelineSnapshotService.snapshot(
        _timeline("missing.mp4")
    )
    application = PreviewApplication(lambda: snapshot, [tmp_path])

    with _server(application) as base_url:
        status, _, body = _request(f"{base_url}/api/analysis")

    assert status == 200
    result = json.loads(body)["results"][0]
    assert result["status"] == "missing"
    assert result["status_code"] == "source_unavailable"
    assert result["thumbnails"] == []


def test_media_resolution_is_allowlisted_and_supports_ranges(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    media = allowed / "source.mp4"
    media.write_bytes(b"0123456789")
    outside_media = outside / "secret.mp4"
    outside_media.write_bytes(b"do-not-serve")

    snapshot = TimelineSnapshotService.snapshot(_timeline("source.mp4"))
    application = PreviewApplication(lambda: snapshot, [allowed])
    source_id = snapshot.tracks[0].clips[0].source.source_id

    with _server(application) as base_url:
        status, headers, body = _request(
            f"{base_url}/media/{source_id}",
            headers={"Range": "bytes=2-5"},
        )
        assert status == 206
        assert headers["Accept-Ranges"] == "bytes"
        assert headers["Content-Range"] == "bytes 2-5/10"
        assert headers["Content-Length"] == "4"
        assert body == b"2345"

        head_status, head_headers, head_body = _request(
            f"{base_url}/media/{source_id}",
            method="HEAD",
        )
        assert head_status == 200
        assert head_headers["Content-Length"] == "10"
        assert head_body == b""

        invalid_status, _, invalid_body = _request(
            f"{base_url}/media/{source_id}",
            headers={"Range": "bytes=99-100"},
        )
        assert invalid_status == 416
        assert invalid_body == b""

        traversal_status, _, traversal_body = _request(
            f"{base_url}/media/..%2F..%2Fsecret.mp4"
        )
        assert traversal_status == 404
        assert b"secret.mp4" not in traversal_body
        static_traversal_status, _, static_traversal_body = _request(
            f"{base_url}/..%2FREADME.md"
        )
        assert static_traversal_status == 404
        assert b"Vistora is" not in static_traversal_body

    assert MediaResolver([allowed]).resolve(str(outside_media)) is None
    assert MediaResolver([allowed]).resolve("../outside/secret.mp4") is None


def test_missing_and_unsupported_sources_are_not_exposed(
    tmp_path: Path,
) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("private", encoding="utf-8")
    missing_snapshot = TimelineSnapshotService.snapshot(
        _timeline("missing.mp4")
    )
    unsupported_snapshot = TimelineSnapshotService.snapshot(
        _timeline("notes.txt")
    )

    for snapshot in [missing_snapshot, unsupported_snapshot]:
        application = PreviewApplication(
            lambda value=snapshot: value,
            [tmp_path],
        )
        source_id = snapshot.tracks[0].clips[0].source.source_id
        payload = application.snapshot_payload()
        assert payload["media"][source_id]["available"] is False
        assert payload["media"][source_id]["url"] is None
        with _server(application) as base_url:
            status, _, body = _request(f"{base_url}/media/{source_id}")
            assert status == 404
            assert str(tmp_path).encode() not in body


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_server_has_no_write_routes(tmp_path: Path, method: str) -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline("missing.mp4"))
    application = PreviewApplication(lambda: snapshot, [tmp_path])

    with _server(application) as base_url:
        for route in ["/", "/api/snapshot", "/media/source_deadbeefdeadbeef"]:
            status, headers, body = _request(
                f"{base_url}{route}",
                method=method,
            )
            assert status == 405
            assert headers["Allow"] == "GET, HEAD"
            assert json.loads(body)["error"]["code"] == "read_only"

    with _server(application) as base_url:
        status, headers, body = _request(
            f"{base_url}/api/not-a-write-route",
            method="POST",
            json_body={},
        )
        assert status == 405
        assert headers["Allow"] == "GET, HEAD"
        assert json.loads(body)["error"]["code"] == "read_only"


def test_manual_edit_endpoints_validate_then_confirm_apply_and_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project_file = workspace / "current_timeline.json"
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    timeline_manager.TimelineManager.save_current_timeline(
        _timeline("source.mp4")
    )
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        [tmp_path],
        skill_registry={
            "VideoApplyManualEditsSkill": VideoApplyManualEditsSkill()
        },
        manual_edits_enabled=True,
    )
    snapshot = TimelineSnapshotService.snapshot_current()
    proposal = ManualEditProposal(
        proposal_id="manual_preview_proposal",
        authored_by="local_user",
        base_project_id=snapshot.project_id,
        base_revision=snapshot.revision,
        base_timeline_digest=snapshot.timeline_digest,
        edits=(
            ManualClipUpdate(
                operation_id="manual_preview_update",
                clip_id="clip_preview",
                trim_in_seconds=0.25,
                trim_out_seconds=1.75,
                timeline_start_seconds=1.0,
                order_index=0,
            ),
        ),
    )
    confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="manual_preview_confirmation",
        proposal=proposal,
        confirmed_by="local_user",
    )
    before = project_file.read_bytes()

    with _server(application) as base_url:
        snapshot_status, _, snapshot_body = _request(
            f"{base_url}/api/snapshot"
        )
        assert snapshot_status == 200
        assert json.loads(snapshot_body)["capabilities"][
            "manual_edit_apply"
        ] is True
        assert json.loads(snapshot_body)["capabilities"][
            "confirmed_manual_dispatch"
        ] is True

        validate_status, _, validate_body = _request(
            f"{base_url}/api/manual-edits/validate",
            method="POST",
            json_body={"proposal": proposal.model_dump(mode="json")},
        )
        assert validate_status == 200
        review_payload = json.loads(validate_body)
        assert review_payload["persisted"] is False
        assert review_payload["review"]["changes"][0]["before"][
            "trim_in_seconds"
        ] == 0.0
        assert review_payload["review"]["changes"][0]["after"][
            "trim_in_seconds"
        ] == 0.25
        assert project_file.read_bytes() == before

        unconfirmed_status, _, _ = _request(
            f"{base_url}/api/manual-edits/apply",
            method="POST",
            json_body={
                "proposal": proposal.model_dump(mode="json"),
                "confirmation": None,
            },
        )
        assert unconfirmed_status == 422
        assert project_file.read_bytes() == before

        apply_status, _, apply_body = _request(
            f"{base_url}/api/manual-edits/apply",
            method="POST",
            json_body={
                "proposal": proposal.model_dump(mode="json"),
                "confirmation": confirmation.model_dump(mode="json"),
            },
        )
        assert apply_status == 200
        application_payload = json.loads(apply_body)
        assert application_payload["tool_name"] == (
            "VideoApplyManualEditsSkill"
        )
        assert application_payload["confirmation_id"] == (
            confirmation.confirmation_id
        )
        assert project_file.read_bytes() != before

        reload_status, _, reload_body = _request(
            f"{base_url}/api/snapshot"
        )
        assert reload_status == 200
        reloaded = json.loads(reload_body)["snapshot"]
        clip = reloaded["tracks"][0]["clips"][0]
        assert clip["trim_in_seconds"] == 0.25
        assert clip["trim_out_seconds"] == 1.75
        assert clip["timeline_start_seconds"] == 1.0


def test_manual_edit_validation_errors_and_external_document_disable_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project_file = workspace / "current_timeline.json"
    monkeypatch.setattr(timeline_manager, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    timeline_manager.TimelineManager.save_current_timeline(
        _timeline("missing.mp4")
    )
    snapshot = TimelineSnapshotService.snapshot_current()
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        [tmp_path],
        skill_registry={
            "VideoApplyManualEditsSkill": VideoApplyManualEditsSkill()
        },
        manual_edits_enabled=True,
    )
    invalid = {
        "schema_name": "vistora.manual-edit-proposal",
        "schema_version": "1.0.0",
        "proposal_id": "manual_invalid",
        "authored_by": "local_user",
        "base_project_id": snapshot.project_id,
        "base_revision": snapshot.revision,
        "base_timeline_digest": snapshot.timeline_digest,
        "edits": [
            {
                "schema_version": "1.0.0",
                "operation_id": "manual_invalid_update",
                "kind": "update",
                "track_key": "video",
                "clip_id": "clip_preview",
                "trim_in_seconds": 2.0,
                "trim_out_seconds": 1.0,
                "timeline_start_seconds": 0.0,
                "order_index": 0,
            }
        ],
        "created_at": "2026-07-24T00:00:00Z",
    }
    before = project_file.read_bytes()

    with _server(application) as base_url:
        status, _, body = _request(
            f"{base_url}/api/manual-edits/validate",
            method="POST",
            json_body={"proposal": invalid},
        )
        assert status == 422
        assert json.loads(body)["error"]["code"] == "invalid_manual_edit"
        assert project_file.read_bytes() == before

    read_only_application = PreviewApplication(lambda: snapshot, [tmp_path])
    with _server(read_only_application) as base_url:
        status, _, body = _request(
            f"{base_url}/api/manual-edits/validate",
            method="POST",
            json_body={"proposal": invalid},
        )
        assert status == 409
        assert json.loads(body)["error"]["code"] == "manual_edit_disabled"


def test_snapshot_reads_do_not_change_source_or_disk(tmp_path: Path) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"media")
    timeline = _timeline(media.name)
    before = timeline.model_dump(mode="json")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    application = PreviewApplication(lambda: snapshot, [tmp_path])
    before_files = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    first = application.snapshot_payload()
    second = application.snapshot_payload()

    assert first == second
    assert timeline.model_dump(mode="json") == before
    assert {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before_files


def test_server_rejects_non_loopback_bind_and_invalid_media_root(
    tmp_path: Path,
) -> None:
    snapshot = TimelineSnapshotService.snapshot(_timeline("missing.mp4"))
    application = PreviewApplication(lambda: snapshot)
    with pytest.raises(PreviewConfigurationError, match="loopback"):
        create_preview_server(application, host="0.0.0.0", port=0)
    with pytest.raises(FileNotFoundError):
        PreviewApplication(lambda: snapshot, [tmp_path / "missing"])


def test_preview_package_has_no_mutation_or_agent_execution_calls() -> None:
    forbidden_imports = {
        "agent",
        "skills",
        "subprocess",
        "utils.hardware",
        "utils.proxy",
    }
    forbidden_calls = {
        "save_current_timeline",
        "reset_timeline",
        "render",
        "write_videofile",
    }
    violations: list[str] = []
    registry_dispatches: list[str] = []
    for path in sorted((SRC / "timeline_preview").glob("*.py")):
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
                if node.func.attr == "execute":
                    if (
                        path.name == "manual_edits.py"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "skill"
                    ):
                        registry_dispatches.append(
                            f"{path.name}: skill.execute"
                        )
                    else:
                        violations.append(
                            f"{path.name}: unapproved execute dispatch"
                        )
    assert not violations, (
        "Timeline preview must keep mutation behind its application service: "
        f"{violations}"
    )
    assert registry_dispatches == ["manual_edits.py: skill.execute"]
