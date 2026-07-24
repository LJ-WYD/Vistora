"""Deterministic test-only reference for Vistora's intended main workflow.

This module constructs planning data directly because production Director and
Editing Agents do not exist yet. Timeline/media mutation is still dispatched
only through the registered atomic skills.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import main as vistora_main  # noqa: E402
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    DirectorOperation,
    DirectorPlan,
    EditingExecutionPlan,
    PlanReference,
    ToolError,
    UserConfirmationRecord,
)
from core import timeline_manager  # noqa: E402
from moviepy import ColorClip  # noqa: E402


REFERENCE_TIME = datetime(2026, 7, 24, tzinfo=timezone.utc)
REFERENCE_CLIP_UUID = UUID("12345678-1234-5678-1234-567812345678")
REFERENCE_PLAN_DIGEST = (
    "sha256:43878f4d3f8738094fce210277e79763c35f6380e20d4fc31498a669330a4ddb"
)
REFERENCE_TOOL_ORDER = (
    "VideoClearTimelineSkill",
    "VideoAddClipSkill",
    "VideoExportSkill",
)


@dataclass(frozen=True)
class AnalyzedMediaFacts:
    source_path: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    has_audio: bool
    visual_summary: str


@dataclass(frozen=True)
class ReferenceWorkflowReport:
    facts: AnalyzedMediaFacts
    plan: DirectorPlan
    confirmation: UserConfirmationRecord
    execution: EditingExecutionPlan
    requests: tuple[AtomicToolRequestEnvelope, ...]
    results: tuple[AtomicToolResultEnvelope, ...]
    output_metadata: dict[str, Any]
    timeline_state_removed: bool

    def summary(self) -> dict[str, Any]:
        return {
            "facts": asdict(self.facts),
            "plan_id": self.plan.plan_id,
            "plan_version": self.plan.plan_version,
            "plan_digest": self.plan.digest(),
            "confirmation_id": self.confirmation.confirmation_id,
            "execution_id": self.execution.execution_id,
            "request_ids": [request.request_id for request in self.requests],
            "result_ids": [result.result_id for result in self.results],
            "tool_order": [request.tool_name for request in self.requests],
            "output_metadata": self.output_metadata,
            "timeline_state_removed": self.timeline_state_removed,
        }


def _probe_media(path: str) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,r_frame_rate",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        path,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(completed.stdout)
    video_streams = [
        stream
        for stream in data.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    audio_streams = [
        stream
        for stream in data.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    if len(video_streams) != 1:
        raise AssertionError(
            f"Expected one video stream in {path}, found {len(video_streams)}"
        )
    video = video_streams[0]
    return {
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": video.get("r_frame_rate"),
        "audio_stream_count": len(audio_streams),
        "duration_seconds": float(data["format"]["duration"]),
        "size_bytes": int(data["format"]["size"]),
    }


def _generate_source(path: str) -> AnalyzedMediaFacts:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    clip = ColorClip(
        size=(320, 180),
        color=(12, 34, 56),
        duration=2.0,
    ).with_fps(24)
    try:
        clip.write_videofile(
            path,
            codec="libx264",
            audio=False,
            logger=None,
        )
    finally:
        clip.close()

    metadata = _probe_media(path)
    expected = {
        "video_codec": "h264",
        "width": 320,
        "height": 180,
        "frame_rate": "24/1",
        "audio_stream_count": 0,
    }
    for field, value in expected.items():
        if metadata[field] != value:
            raise AssertionError(
                f"Unexpected synthetic source {field}: "
                f"{metadata[field]!r} != {value!r}"
            )
    if abs(metadata["duration_seconds"] - 2.0) > 0.05:
        raise AssertionError(
            "Synthetic source duration is outside the deterministic tolerance"
        )

    return AnalyzedMediaFacts(
        source_path=path,
        duration_seconds=2.0,
        width=320,
        height=180,
        fps=24,
        has_audio=False,
        visual_summary="Uniform RGB(12, 34, 56) reference frame.",
    )


def _build_plan(
    facts: AnalyzedMediaFacts,
    output_path: str,
) -> DirectorPlan:
    return DirectorPlan(
        plan_id="plan_reference_main_flow",
        plan_version=1,
        created_at=REFERENCE_TIME,
        objective="Export a deterministic trimmed reference clip.",
        requirements=(
            "Use the known analyzed source facts.",
            "Trim the source to 0.25-1.75 seconds.",
            "Keep the output silent.",
            "Clear timeline state after export.",
        ),
        assumptions=(
            "Synthetic source facts are trusted test fixture inputs.",
        ),
        creative_direction={
            "analyzed_facts": asdict(facts),
            "pacing": "single concise 1.5 second shot",
            "audio": "silent",
        },
        operations=(
            DirectorOperation(
                operation_id="operation_clear_timeline",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Begin from isolated test timeline state.",
                expected_effect="No prior clips remain.",
            ),
            DirectorOperation(
                operation_id="operation_add_reference_clip",
                tool_name="VideoAddClipSkill",
                arguments={
                    "source_path": facts.source_path,
                    "trim_in": 0.25,
                    "trim_out": 1.75,
                    "speed_factor": 1.0,
                    "reverse": False,
                    "rotate": 0,
                    "keep_audio": False,
                },
                rationale="Use the confirmed deterministic trim.",
                expected_effect="One silent 1.5 second timeline clip.",
            ),
            DirectorOperation(
                operation_id="operation_export_reference",
                tool_name="VideoExportSkill",
                arguments={
                    "output_path": output_path,
                    "clear_timeline_after": True,
                },
                rationale="Materialize and verify the confirmed output.",
                expected_effect="One exported MP4 and no residual timeline.",
            ),
        ),
        outputs=(output_path,),
        risks=("Hardware encoder availability may vary by machine.",),
    )


def _fixed_execution(
    plan: DirectorPlan,
    confirmation: UserConfirmationRecord,
) -> EditingExecutionPlan:
    execution = EditingExecutionPlan.from_confirmed_plan(
        execution_id="execution_reference_main_flow",
        project_id="project_reference_main_flow",
        director_plan=plan,
        confirmation=confirmation,
    )
    data = execution.model_dump(mode="json")
    data["created_at"] = (REFERENCE_TIME + timedelta(minutes=2)).isoformat()
    return EditingExecutionPlan.model_validate(data)


@contextmanager
def _isolated_timeline(work_dir: Path) -> Iterator[Path]:
    original_workspace = timeline_manager.WORKSPACE_DIR
    original_project_file = timeline_manager.PROJECT_FILE
    workspace = work_dir / ".workspace"
    project_file = workspace / "current_timeline.json"
    timeline_manager.WORKSPACE_DIR = str(workspace)
    timeline_manager.PROJECT_FILE = str(project_file)
    try:
        yield project_file
    finally:
        timeline_manager.WORKSPACE_DIR = original_workspace
        timeline_manager.PROJECT_FILE = original_project_file


def _dispatch_execution(
    execution: EditingExecutionPlan,
) -> tuple[
    tuple[AtomicToolRequestEnvelope, ...],
    tuple[AtomicToolResultEnvelope, ...],
]:
    requests: list[AtomicToolRequestEnvelope] = []
    results: list[AtomicToolResultEnvelope] = []

    for index, step in enumerate(execution.steps, start=1):
        started_at = REFERENCE_TIME + timedelta(minutes=3, seconds=index)
        request = AtomicToolRequestEnvelope.from_execution_plan(
            request_id=f"request_reference_{index:02d}",
            execution_plan=execution,
            step_id=step.step_id,
        )
        request_data = request.model_dump(mode="json")
        request_data["requested_at"] = started_at.isoformat()
        request = AtomicToolRequestEnvelope.model_validate(request_data)
        requests.append(request)

        validated = request.validate_against_registry(vistora_main.SKILLS)
        normalized_arguments = validated.model_dump(mode="python")
        skill = vistora_main.SKILLS[request.tool_name]
        try:
            payload = skill.execute(normalized_arguments)
        except Exception as exc:
            error_result = AtomicToolResultEnvelope(
                result_id=f"result_reference_{index:02d}",
                request_id=request.request_id,
                execution_id=request.execution_id,
                step_id=request.step_id,
                tool_name=request.tool_name,
                status="error",
                error=ToolError(
                    code="reference_dispatch_failed",
                    message=str(exc),
                ),
                started_at=started_at,
                finished_at=started_at,
            )
            results.append(error_result)
            raise AssertionError(
                f"Atomic reference dispatch failed: {error_result.model_dump()}"
            ) from exc

        results.append(
            AtomicToolResultEnvelope(
                result_id=f"result_reference_{index:02d}",
                request_id=request.request_id,
                execution_id=request.execution_id,
                step_id=request.step_id,
                tool_name=request.tool_name,
                status="success",
                payload=payload,
                started_at=started_at,
                finished_at=started_at,
            )
        )

    return tuple(requests), tuple(results)


def _verify_output(path: str) -> dict[str, Any]:
    metadata = _probe_media(path)
    expected = {
        "video_codec": "h264",
        "width": 320,
        "height": 180,
        "frame_rate": "24/1",
        "audio_stream_count": 0,
    }
    for field, value in expected.items():
        if metadata[field] != value:
            raise AssertionError(
                f"Unexpected output {field}: {metadata[field]!r} != {value!r}"
            )
    if abs(metadata["duration_seconds"] - 1.5) > 0.08:
        raise AssertionError(
            "Reference output duration is outside the deterministic tolerance"
        )
    if metadata["size_bytes"] <= 0:
        raise AssertionError("Reference output is empty")
    return metadata


def run_reference_workflow(
    work_dir: Path = Path("tests/test_data/reference_workflow"),
) -> ReferenceWorkflowReport:
    """Run the complete test-only contract-to-atomic-tool reference flow."""

    if work_dir.is_absolute():
        raise ValueError("Use a repository-relative work_dir for stable plans")

    previous_cwd = Path.cwd()
    os.chdir(ROOT)
    try:
        source_path = (work_dir / "source.mp4").as_posix()
        output_path = (work_dir / "output.mp4").as_posix()
        facts = _generate_source(source_path)
        plan = _build_plan(facts, output_path)
        if plan.digest() != REFERENCE_PLAN_DIGEST:
            raise AssertionError(
                "Reference DirectorPlan digest changed; review the fixture "
                "and update REFERENCE_PLAN_DIGEST intentionally"
            )
        confirmation = UserConfirmationRecord.for_plan(
            confirmation_id="confirmation_reference_main_flow",
            plan=plan,
            confirmed_by="user_reference",
            decision="confirmed",
            recorded_at=REFERENCE_TIME + timedelta(minutes=1),
        )
        execution = _fixed_execution(plan, confirmation)

        with _isolated_timeline(work_dir) as project_file:
            with patch(
                "skills.video_add_clip.uuid.uuid4",
                return_value=REFERENCE_CLIP_UUID,
            ):
                requests, results = _dispatch_execution(execution)
            output_metadata = _verify_output(output_path)
            timeline_state_removed = not project_file.exists()

        if not timeline_state_removed:
            raise AssertionError("Reference export did not clear timeline state")

        return ReferenceWorkflowReport(
            facts=facts,
            plan=plan,
            confirmation=confirmation,
            execution=execution,
            requests=requests,
            results=results,
            output_metadata=output_metadata,
            timeline_state_removed=timeline_state_removed,
        )
    finally:
        os.chdir(previous_cwd)


def main() -> None:
    report = run_reference_workflow()
    print(json.dumps(report.summary(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
