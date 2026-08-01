"""Deterministic STEP 18 multi-track/link execution reference."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent import EditingAgent  # noqa: E402
from atomic_runtime import build_production_registry  # noqa: E402
from contracts import (  # noqa: E402
    DirectorOperation,
    DirectorPlan,
    MediaTimeRangeLocator,
    SourceEvidenceReference,
)
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import WorkflowApplicationService, WorkflowStore  # noqa: E402


REFERENCE_TIME = datetime(2026, 7, 30, tzinfo=timezone.utc)


def _run(command: list[str]) -> None:
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _fixtures(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    main = root / "main.mp4"
    overlay = root / "overlay.mp4"
    dialogue = root / "dialogue.wav"
    music = root / "music.wav"
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x1d4ed8:s=320x180:r=24:d=4",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=4",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(main),
    ])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0xdc2626:s=160x90:r=24:d=4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(overlay),
    ])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=4",
        str(dialogue),
    ])
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=4",
        str(music),
    ])
    return {
        "main": main,
        "overlay": overlay,
        "dialogue": dialogue,
        "music": music,
    }


def _metadata(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate",
            "-show_entries", "format=duration,size",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def run_multitrack_reference_workflow() -> dict:
    test_data = ROOT / "tests" / "test_data"
    root = test_data / "multitrack_reference_generated"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    try:
        media = _fixtures(root / "media")
        workspace = root / "workspace"
        project_file = workspace / "current_timeline.json"
        output = root / "multitrack_output.mp4"
        timeline = TimelineConfig(
            width=320,
            height=180,
            fps=24,
            tracks={
                "v-main": TrackConfig(
                    id="track_video_main",
                    kind="video",
                    role="primary",
                    order=0,
                    clips=[
                        ClipConfig(
                            id="clip_video_main",
                            source=str(media["main"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0,
                            keep_audio=True,
                            link_group_id="link_scene_main",
                        )
                    ],
                ),
                "v-overlay": TrackConfig(
                    id="track_video_overlay",
                    kind="video",
                    role="overlay",
                    order=1,
                    clips=[
                        ClipConfig(
                            id="clip_video_overlay",
                            source=str(media["overlay"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0.5,
                            keep_audio=False,
                        )
                    ],
                ),
                "a-dialogue": TrackConfig(
                    id="track_audio_dialogue",
                    kind="audio",
                    role="dialogue",
                    order=2,
                    clips=[
                        ClipConfig(
                            id="clip_audio_dialogue",
                            source=str(media["dialogue"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0,
                            link_group_id="link_scene_main",
                        )
                    ],
                ),
                "a-music": TrackConfig(
                    id="track_audio_music",
                    kind="audio",
                    role="music",
                    order=3,
                    clips=[
                        ClipConfig(
                            id="clip_audio_music",
                            source=str(media["music"]),
                            trim_in=0,
                            trim_out=4,
                            timeline_start=0,
                            volume=0.15,
                        )
                    ],
                ),
            },
        )
        counter = {"value": 0}

        def identifier(prefix: str) -> str:
            counter["value"] += 1
            return f"{prefix}_{counter['value']:04d}"

        registry = build_production_registry(
            timeline_id_factory=identifier
        )
        with (
            patch.object(
                timeline_manager,
                "WORKSPACE_DIR",
                str(workspace),
            ),
            patch.object(
                timeline_manager,
                "PROJECT_FILE",
                str(project_file),
            ),
        ):
            timeline_manager.TimelineManager.save_current_timeline(timeline)
            original = json.loads(project_file.read_text(encoding="utf-8"))
            snapshot = TimelineSnapshotService.snapshot_current()
            video = next(
                clip
                for track in snapshot.tracks
                for clip in track.clips
                if clip.clip_id == "clip_video_main"
            )
            audio = next(
                clip
                for track in snapshot.tracks
                for clip in track.clips
                if clip.clip_id == "clip_audio_dialogue"
            )
            evidence = (
                SourceEvidenceReference(
                    evidence_id="evidence_video_main",
                    material_id=video.source.source_id,
                    locator=MediaTimeRangeLocator(
                        start_seconds=0,
                        end_seconds=4,
                    ),
                ),
                SourceEvidenceReference(
                    evidence_id="evidence_audio_dialogue",
                    material_id=audio.source.source_id,
                    locator=MediaTimeRangeLocator(
                        start_seconds=0,
                        end_seconds=4,
                    ),
                ),
            )
            operations = (
                DirectorOperation(
                    operation_id="operation_linked_split",
                    tool_name="VideoSplitClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_main",
                        "split_at_seconds": 1.5,
                        "right_clip_id": "clip_video_right",
                        "edit_scope": "linked_group",
                    },
                    rationale="Split the verified linked picture and dialogue.",
                    expected_effect="Create aligned linked halves.",
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                ),
                DirectorOperation(
                    operation_id="operation_linked_move",
                    tool_name="VideoMoveClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_main",
                        "timeline_start": 0.25,
                        "ripple": False,
                        "edit_scope": "linked_group",
                    },
                    rationale="Move the linked opening together.",
                    expected_effect="Move both verified linked members.",
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                ),
                DirectorOperation(
                    operation_id="operation_overlay_only",
                    tool_name="VideoMoveClipSkill",
                    arguments={
                        "track_id": "track_video_overlay",
                        "clip_id": "clip_video_overlay",
                        "timeline_start": 0.75,
                        "ripple": False,
                        "edit_scope": "current_clip",
                    },
                    rationale="Adjust only the overlay layer.",
                    expected_effect="Leave linked picture/dialogue unchanged.",
                ),
                DirectorOperation(
                    operation_id="operation_linked_ripple_remove",
                    tool_name="VideoRemoveClipSkill",
                    arguments={
                        "track_id": "track_video_main",
                        "clip_id": "clip_video_main",
                        "mode": "ripple",
                        "edit_scope": "linked_group",
                    },
                    rationale="Remove the linked opening from both tracks.",
                    expected_effect="Tombstone both members and ripple safely.",
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                ),
                DirectorOperation(
                    operation_id="operation_export_multitrack",
                    tool_name="VideoExportSkill",
                    arguments={
                        "output_path": str(output),
                        "clear_timeline_after": False,
                    },
                    rationale="Render the reviewed layers and audio mix.",
                    expected_effect="Produce one deterministic local export.",
                ),
            )
            plan = DirectorPlan(
                plan_id="plan_multitrack_reference",
                plan_version=1,
                created_at=REFERENCE_TIME,
                objective="Verify confirmed multi-track linked editing.",
                source_evidence=evidence,
                operations=operations,
            )
            proposed = ProposedEditingExecutionPlan.from_director_plan(
                proposal_execution_id="proposal_multitrack_reference",
                project_id=snapshot.project_id,
                director_plan=plan,
            )
            request = PlanDiffRequest(
                request_id="review_multitrack_reference",
                snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
                director_plan=plan,
                proposed_execution=proposed,
                registry_ref=RegistrySchemaReference.from_registry(registry),
            )
            workflow = WorkflowApplicationService(
                store=WorkflowStore.for_project_file(project_file),
                registry=registry,
                id_factory=identifier,
            )
            review = workflow.record_review(request)
            confirmation = workflow.confirm_review(
                review.review_id,
                confirmed_by="reference_user",
                decision="confirmed",
            )
            agent = EditingAgent(workflow, id_factory=identifier)
            report = agent.execute(
                agent.prepare_execution(
                    request_id="editing_multitrack_reference",
                    confirmation_record_id=(
                        confirmation.confirmation_record_id
                    ),
                )
            )
            if report.status != "succeeded":
                raise AssertionError(report.model_dump(mode="json"))
            metadata = _metadata(output)
            trace = TraceabilityStore.load(project_file)
            current = TimelineSnapshotService.snapshot_current()
            rollback_review = workflow.propose_rollback(report.run_id)
            rollback_confirmation = workflow.confirm_rollback(
                rollback_review.review_id,
                confirmed_by="reference_user",
                decision="confirmed",
            )
            rollback = workflow.apply_rollback(
                rollback_confirmation.confirmation_id
            )
            restored = json.loads(project_file.read_text(encoding="utf-8"))
            if restored != original:
                raise AssertionError("Rollback did not restore the timeline")
            return {
                "review_digest": review.diff.digest(),
                "review_change_count": len(review.diff.changes),
                "execution_status": report.status,
                "step_count": len(report.steps),
                "trace_count": len(trace.confirmed_traces),
                "current_track_count": current.track_count,
                "current_video_clip_count": current.video_clip_count,
                "current_audio_clip_count": current.audio_clip_count,
                "rollback_status": rollback.status,
                "output": metadata,
            }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    print(
        json.dumps(
            run_multitrack_reference_workflow(),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
