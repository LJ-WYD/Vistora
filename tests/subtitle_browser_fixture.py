"""Local deterministic STEP 20 browser-regression fixture server."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atomic_runtime import build_production_registry  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    ClipColorAdjustment,
    ClipConfig,
    ClipTransform,
    SubtitleCue,
    SubtitleTrackConfig,
    TimelineConfig,
    TimelineTransition,
    TrackConfig,
    VisualAutomation,
    VisualKeyframe,
)
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402


def _timeline(root: Path, mode: str) -> tuple[TimelineConfig, Path]:
    media = root / "media"
    media.mkdir(parents=True, exist_ok=True)
    if mode == "empty":
        return TimelineConfig(
            width=640,
            height=360,
            fps=24,
            tracks={
                "video": TrackConfig(id="video_main", kind="video", order=0),
                "audio": TrackConfig(id="audio_main", kind="audio", order=1),
            },
        ), media
    source = media / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=0x243b6b:s=640x360:d=4:r=24",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
        timeout=60,
    )
    return TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video_main",
                kind="video",
                order=0,
                clips=[
                    ClipConfig(
                        id="clip_available",
                        source=str(source),
                        trim_out=2,
                        keep_audio=False,
                        transform=ClipTransform(
                            position_x=0.42,
                            position_y=0.54,
                            scale_x=0.86,
                            scale_y=0.9,
                        ),
                        color=ClipColorAdjustment(
                            exposure=0.15,
                            contrast=0.12,
                            saturation=0.18,
                        ),
                        visual_automations=(
                            VisualAutomation(
                                automation_id="automation_fixture_position",
                                clip_id="clip_available",
                                property_path="transform.position_x",
                                keyframes=(
                                    VisualKeyframe(
                                        keyframe_id="keyframe_fixture_start",
                                        offset_seconds=0,
                                        value=0.25,
                                        interpolation="ease_in_out",
                                    ),
                                    VisualKeyframe(
                                        keyframe_id="keyframe_fixture_end",
                                        offset_seconds=1.8,
                                        value=0.75,
                                        interpolation="linear",
                                    ),
                                ),
                            ),
                        ),
                    ),
                    ClipConfig(
                        id="clip_available_second",
                        source=str(source),
                        trim_in=2,
                        trim_out=4,
                        timeline_start=2,
                        keep_audio=False,
                    ),
                ],
            ),
            "video_locked": TrackConfig(
                id="video_locked",
                kind="video",
                role="locked-reference",
                order=1,
                locked=True,
                clips=[ClipConfig(
                    id="clip_locked",
                    source=str(source),
                    trim_out=1.5,
                    timeline_start=2.2,
                    keep_audio=False,
                )],
            ),
            "video_missing": TrackConfig(
                id="video_missing",
                kind="video",
                role="missing-reference",
                order=2,
                clips=[ClipConfig(
                    id="clip_missing",
                    source=str(media / "missing.mp4"),
                    trim_out=2,
                    timeline_start=1,
                    keep_audio=False,
                )],
            ),
            "audio": TrackConfig(id="audio_main", kind="audio", order=3),
        },
        subtitle_tracks={
            "captions": SubtitleTrackConfig(
                track_id="subtitle_editable",
                language="en",
                order=0,
                cues=(
                    SubtitleCue(
                        cue_id="cue_welcome",
                        start_seconds=0.2,
                        end_seconds=1.5,
                        text="Welcome to Vistora",
                        language="en",
                    ),
                    SubtitleCue(
                        cue_id="cue_confirm",
                        start_seconds=1.7,
                        end_seconds=3.3,
                        text="Review, confirm, then apply",
                        language="en",
                    ),
                ),
            ),
            "locked": SubtitleTrackConfig(
                track_id="subtitle_locked",
                language="en",
                order=1,
                locked=True,
                cues=(SubtitleCue(
                    cue_id="cue_locked",
                    start_seconds=0.5,
                    end_seconds=1.2,
                    text="Locked reference caption",
                    language="en",
                ),),
            ),
        },
        transitions={
            "transition_fixture_cut": TimelineTransition(
                transition_id="transition_fixture_cut",
                track_id="video_main",
                from_clip_id="clip_available",
                to_clip_id="clip_available_second",
                kind="cut",
            )
        },
    ), media


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mode", choices=("normal", "empty"), default="normal")
    args = parser.parse_args()
    root = ROOT / "tests" / "test_data" / f"subtitle_browser_{args.mode}"
    shutil.rmtree(root, ignore_errors=True)
    workspace = root / ".workspace"
    workspace.mkdir(parents=True)
    timeline, media = _timeline(root, args.mode)
    timeline_manager.WORKSPACE_DIR = str(workspace)
    timeline_manager.PROJECT_FILE = str(workspace / "current_timeline.json")
    timeline_manager.TimelineManager.save_current_timeline(timeline)
    registry = build_production_registry()
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        [media],
        skill_registry=registry,
        manual_edits_enabled=True,
    )
    server = create_preview_server(
        application,
        host="127.0.0.1",
        port=args.port,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
