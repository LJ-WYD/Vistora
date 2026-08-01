"""Serve deterministic STEP 19 audio UI states for browser verification."""

from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from atomic_runtime import build_production_registry  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import (  # noqa: E402
    AudioEnvelopePoint,
    ClipAudioSettings,
    ClipConfig,
    TimelineConfig,
    TrackConfig,
    TrackMixSettings,
)
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402


def _tone(path: Path) -> None:
    sample_rate = 48_000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate * 2):
            sample = int(
                32767
                * 0.22
                * math.sin(2 * math.pi * 330 * index / sample_rate)
            )
            frames.extend(struct.pack("<h", sample))
        output.writeframes(bytes(frames))


def _timeline(state: str, source: Path) -> TimelineConfig:
    clips = [] if state == "empty" else [
        ClipConfig(
            id="clip_audio_visual",
            source=(str(source) if state == "populated" else str(source.with_name("missing.wav"))),
            trim_out=2,
            audio=ClipAudioSettings(
                gain_db=-3,
                pan=0.2,
                fade_in_seconds=0.15,
                fade_out_seconds=0.2,
                envelope=(
                    AudioEnvelopePoint(
                        point_id="envelope_visual_start",
                        offset_seconds=0,
                        gain_db=-12,
                    ),
                    AudioEnvelopePoint(
                        point_id="envelope_visual_end",
                        offset_seconds=2,
                        gain_db=0,
                    ),
                ),
            ),
        )
    ]
    return TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(id="video", kind="video", order=0),
            "dialogue": TrackConfig(
                id="audio_dialogue",
                kind="audio",
                role="dialogue",
                order=1,
                mix=TrackMixSettings(gain_db=-2, pan=-0.1),
                clips=clips,
            ),
            "music": TrackConfig(
                id="audio_music",
                kind="audio",
                role="music",
                order=2,
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state", choices=("populated", "empty", "missing"), default="populated"
    )
    parser.add_argument("--port", type=int, default=8775)
    args = parser.parse_args()
    root = ROOT / "tests" / "test_data" / f"audio_visual_{args.state}"
    root.mkdir(parents=True, exist_ok=True)
    source = root / "tone.wav"
    _tone(source)
    workspace = root / "workspace"
    project_file = workspace / "current_timeline.json"
    project_file.parent.mkdir(parents=True, exist_ok=True)
    project_file.write_text(
        _timeline(args.state, source).model_dump_json(indent=2), encoding="utf-8"
    )
    registry = build_production_registry()
    with (
        patch.object(timeline_manager, "WORKSPACE_DIR", str(workspace)),
        patch.object(timeline_manager, "PROJECT_FILE", str(project_file)),
    ):
        application = PreviewApplication(
            TimelineSnapshotService.snapshot_current,
            [root],
            skill_registry=registry,
            manual_edits_enabled=True,
        )
        server = create_preview_server(application, port=args.port)
        print(f"Audio visual fixture: http://127.0.0.1:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
