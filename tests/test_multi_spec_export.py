"""Original O12 deterministic multi-specification export regression."""

from __future__ import annotations

import json
import subprocess
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
    PlanReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TimelineRenderer, TrackConfig  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from skills.video_export_variants import (  # noqa: E402
    VideoExportVariant,
    VideoExportVariantsInput,
    VideoExportVariantsSkill,
)
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService  # noqa: E402


NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def _timeline(source: str = "source.mp4") -> TimelineConfig:
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="track_video",
                kind="video",
                role="primary",
                order=0,
                clips=[
                    ClipConfig(
                        id="clip_export",
                        source=source,
                        trim_out=1.0,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(id="track_audio", kind="audio", order=1),
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


def _arguments(tmp_path: Path) -> dict:
    return {
        "export_set_id": "exports_social_v1",
        "variants": [
            {
                "variant_id": "landscape",
                "output_path": str((tmp_path / "landscape.mp4").resolve()),
                "width": 320,
                "height": 180,
                "fps": 24,
            },
            {
                "variant_id": "square",
                "output_path": str((tmp_path / "square.mp4").resolve()),
                "width": 180,
                "height": 180,
                "fps": 30,
            },
        ],
    }


def test_export_variant_contracts_are_frozen_bounded_and_stable(tmp_path: Path) -> None:
    parsed = VideoExportVariantsInput.model_validate(_arguments(tmp_path))
    assert parsed.schema_name == "vistora.video-export-variants-input"
    assert tuple(item.variant_id for item in parsed.variants) == (
        "landscape",
        "square",
    )
    with pytest.raises(ValidationError):
        parsed.export_set_id = "changed"
    invalid = _arguments(tmp_path)
    invalid["variants"] = list(reversed(invalid["variants"]))
    with pytest.raises(ValidationError, match="stably sorted"):
        VideoExportVariantsInput.model_validate(invalid)
    invalid = _arguments(tmp_path)
    invalid["variants"][1]["output_path"] = invalid["variants"][0]["output_path"]
    with pytest.raises(ValidationError, match="paths must be unique"):
        VideoExportVariantsInput.model_validate(invalid)
    with pytest.raises(ValidationError):
        VideoExportVariant(
            variant_id="odd",
            output_path=str((tmp_path / "odd.mp4").resolve()),
            width=319,
            height=180,
            fps=24,
        )
    with pytest.raises(ValidationError, match="absolute"):
        VideoExportVariant(
            variant_id="relative",
            output_path="relative.mp4",
            width=320,
            height=180,
            fps=24,
        )


def test_gateway_exports_atomically_replays_and_redacts_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _configure_project(tmp_path, monkeypatch, _timeline())
    rendered: list[tuple[int, int, float]] = []

    def fake_render(self, output_path: str, *, enforce_canvas: bool = False) -> str:
        assert enforce_canvas is True
        rendered.append((self.config.width, self.config.height, self.config.fps))
        Path(output_path).write_bytes(
            f"{self.config.width}x{self.config.height}@{self.config.fps}".encode()
        )
        return output_path

    monkeypatch.setattr(TimelineRenderer, "render", fake_render)
    registry = build_production_registry()
    assert registry.reference.registry_revision == 12 and len(registry) == 43
    request = AtomicToolRequestEnvelope(
        request_id="request_multi_spec_export",
        execution_id="execution_multi_spec_export",
        project_id="project_export",
        confirmation_id="confirmation_export",
        plan_ref=PlanReference(
            plan_id="plan_export",
            plan_version=1,
            plan_digest="sha256:" + "a" * 64,
        ),
        step_id="step_multi_spec_export",
        tool_name="VideoExportVariantsSkill",
        arguments=_arguments(tmp_path),
        requested_at=NOW,
    )
    context = AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_export",
        confirmation_id="confirmation_export",
        allowed_side_effects=("files", "media"),
        idempotency_key="multi_spec_export_once",
    )
    gateway = AtomicExecutionGateway(registry)
    result = gateway.execute(request, context)
    assert result.status == "success"
    assert result.payload["export_set_id"] == "exports_social_v1"
    assert [item["variant_id"] for item in result.payload["outputs"]] == [
        "landscape",
        "square",
    ]
    assert str(tmp_path) not in json.dumps(result.payload)
    assert rendered == [(320, 180, 24.0), (180, 180, 30.0)]
    assert (tmp_path / "landscape.mp4").is_file()
    assert (tmp_path / "square.mp4").is_file()
    assert project.read_text(encoding="utf-8") == _timeline().model_dump_json(indent=2)
    replay = gateway.execute(request, context)
    assert replay.replayed is True and len(rendered) == 2


def test_failed_variant_removes_staging_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_project(tmp_path, monkeypatch, _timeline())
    calls = 0

    def failing_render(self, output_path: str, *, enforce_canvas: bool = False) -> str:
        nonlocal calls
        calls += 1
        Path(output_path).write_bytes(b"staged")
        if calls == 2:
            raise RuntimeError("synthetic second render failure")
        return output_path

    monkeypatch.setattr(TimelineRenderer, "render", failing_render)
    with pytest.raises(RuntimeError, match="second render failure"):
        VideoExportVariantsSkill().run(
            VideoExportVariantsInput.model_validate(_arguments(tmp_path))
        )
    assert not (tmp_path / "landscape.mp4").exists()
    assert not (tmp_path / "square.mp4").exists()
    assert not list(tmp_path.glob(".vistora-export-*.mp4"))


def test_plan_review_lists_each_variant_without_paths_or_mutation(tmp_path: Path) -> None:
    timeline = _timeline("material://source_1111111111111111")
    snapshot = TimelineSnapshotService.snapshot(timeline)
    operation = DirectorOperation(
        operation_id="operation_multi_spec_export",
        tool_name="VideoExportVariantsSkill",
        arguments=_arguments(tmp_path),
        rationale="Deliver explicit landscape and square canvases.",
        expected_effect="Render two reviewed outputs without changing the timeline.",
    )
    plan = DirectorPlan(
        plan_id="plan_multi_spec_export",
        plan_version=1,
        created_at=NOW,
        objective="Prepare two canvas variants.",
        operations=(operation,),
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_multi_spec_export",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = build_production_registry()
    request = PlanDiffRequest(
        request_id="review_multi_spec_export",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
    )
    first = PlanDiffEngine.generate(request, snapshot, registry)
    second = PlanDiffEngine.generate(request, snapshot, registry)
    assert first == second
    exports = [change for change in first.changes if change.category == "export_only"]
    assert [change.entity.entity_id for change in exports] == [
        "export_variant_landscape",
        "export_variant_square",
    ]
    assert first.summary.before_project == first.summary.after_project
    serialized = first.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "landscape.mp4" not in serialized and "square.mp4" not in serialized
    assert timeline == _timeline("material://source_1111111111111111")


def test_real_multi_spec_export_has_exact_canvas_and_frame_rate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x315c8a:s=160x90:r=24:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    _configure_project(tmp_path, monkeypatch, _timeline(str(source)))
    arguments = _arguments(tmp_path)
    arguments["variants"][0].update(width=160, height=90, fps=24)
    arguments["variants"][1].update(width=120, height=120, fps=30)
    result = VideoExportVariantsSkill().run(
        VideoExportVariantsInput.model_validate(arguments)
    )
    assert result["status"] == "success"
    for expected, output in [
        ((160, 90, "24/1"), tmp_path / "landscape.mp4"),
        ((120, 120, "30/1"), tmp_path / "square.mp4"),
    ]:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate",
                "-of",
                "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        assert (stream["width"], stream["height"], stream["r_frame_rate"]) == expected
