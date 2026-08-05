"""Safe deterministic FFmpeg rendering for transition-bearing timelines."""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from core.timeline import ClipConfig, TimelineConfig, TimelineTransition, TrackConfig
from timeline_edit import TimelineEditEngine, TimelineEditError, clip_duration
from transitions.media import resolve_transition_source
from visuals.render import clip_visual_filter_chain


def _probe(path: str, *, audio: bool = False) -> dict[str, Any]:
    selection = "a:0" if audio else "v:0"
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", selection,
            "-show_entries", "stream=codec_type:format=duration",
            "-of", "json", path,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        raise TimelineEditError("Configured transition media cannot be probed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TimelineEditError("Configured transition media probe is malformed") from exc


def _duration(clip: ClipConfig) -> float:
    data = _probe(os.fspath(resolve_transition_source(clip.source)))
    try:
        value = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TimelineEditError("Configured transition media has no duration") from exc
    if value <= 0:
        raise TimelineEditError("Configured transition media has no positive duration")
    return value


def _has_audio(path: str) -> bool:
    return bool(_probe(path, audio=True).get("streams"))


def _atempo(speed: float) -> list[str]:
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-9:
        filters.append(f"atempo={remaining:.12g}")
    return filters


def _pan(value: float) -> str | None:
    if abs(value) <= 1e-9:
        return None
    left = math.sqrt((1.0 - value) / 2.0) * math.sqrt(2.0)
    right = math.sqrt((1.0 + value) / 2.0) * math.sqrt(2.0)
    return f"pan=stereo|c0={left:.12g}*c0|c1={right:.12g}*c1"


def _audio_properties(
    track: TrackConfig, clip: ClipConfig, duration: float
) -> list[str]:
    chain = ["aformat=channel_layouts=stereo"]
    legacy = 1.0 if clip.volume is None else clip.volume
    track_gain = track.mix.gain_db if track.kind == "audio" else 0.0
    gain = legacy * 10 ** ((clip.audio.gain_db + track_gain) / 20.0)
    if clip.audio.muted or track.muted or track.mix.muted:
        gain = 0.0
    chain.append(f"volume={gain:.12g}")
    pan = max(-1.0, min(1.0, clip.audio.pan + (track.mix.pan if track.kind == "audio" else 0.0)))
    pan_filter = _pan(pan)
    if pan_filter:
        chain.append(pan_filter)
    points = clip.audio.envelope
    if points:
        amplitudes = [10 ** (point.gain_db / 20.0) for point in points]
        expression = f"{amplitudes[-1]:.12g}"
        for index in range(len(points) - 2, -1, -1):
            left_point, right_point = points[index], points[index + 1]
            span = right_point.offset_seconds - left_point.offset_seconds
            interpolation = (
                f"{amplitudes[index]:.12g}+(t-{left_point.offset_seconds:.12g})*"
                f"{(amplitudes[index + 1] - amplitudes[index]):.12g}/{span:.12g}"
            )
            expression = f"if(lt(t,{right_point.offset_seconds:.12g}),{interpolation},{expression})"
        expression = f"if(lt(t,{points[0].offset_seconds:.12g}),{amplitudes[0]:.12g},{expression})"
        chain.append(f"volume='{expression}':eval=frame")
    if clip.audio.fade_in_seconds > 0:
        chain.append(f"afade=t=in:st=0:d={clip.audio.fade_in_seconds:.12g}")
    if clip.audio.fade_out_seconds > 0:
        start = max(0.0, duration - clip.audio.fade_out_seconds)
        chain.append(f"afade=t=out:st={start:.12g}:d={clip.audio.fade_out_seconds:.12g}")
    return chain


def _handles(transition: TimelineTransition) -> tuple[float, float]:
    if transition.kind == "cut":
        return 0.0, 0.0
    if transition.alignment == "start_at_cut":
        return transition.duration_seconds, 0.0
    if transition.alignment == "end_at_cut":
        return 0.0, transition.duration_seconds
    return transition.duration_seconds / 2.0, transition.duration_seconds / 2.0


def _video_xfade(transition: TimelineTransition) -> str:
    if transition.kind == "cross_dissolve":
        return "fade"
    if transition.kind == "fade_color":
        return "fadeblack" if transition.parameters.color == "#000000" else "fadewhite"
    if transition.kind == "wipe":
        return "wipe" + (transition.parameters.direction or "left")
    if transition.kind == "slide":
        return "slide" + (transition.parameters.direction or "left")
    raise TimelineEditError("Unsupported video transition kind")


def _groups(
    clips: list[ClipConfig], transitions: dict[tuple[str, str], TimelineTransition]
) -> list[list[ClipConfig]]:
    groups: list[list[ClipConfig]] = []
    for clip in clips:
        if not groups:
            groups.append([clip])
            continue
        previous = groups[-1][-1]
        if (previous.id, clip.id) in transitions:
            groups[-1].append(clip)
        else:
            groups.append([clip])
    return groups


def render_transition_timeline(config: TimelineConfig, output_path: str) -> str:
    """Render enabled built-in transitions without accepting raw filter text."""

    enabled = {
        identity: transition
        for identity, transition in config.transitions.items()
        if transition.enabled
    }
    if not enabled:
        raise TimelineEditError("Transition renderer requires an enabled transition")
    resolved_sources = {
        clip.id: resolve_transition_source(clip.source)
        for track in config.tracks.values()
        for clip in track.clips
    }
    validator = TimelineEditEngine(
        config,
        source_duration_resolver=_duration,
        source_audio_resolver=lambda clip: _has_audio(
            os.fspath(resolved_sources[clip.id])
        ),
    )
    for transition in enabled.values():
        track = next(
            track
            for track in config.tracks.values()
            if track.id == transition.track_id
        )
        if transition.media_type == "video" and track.role != "primary":
            raise TimelineEditError(
                "First-version renderer supports video transitions on primary tracks only"
            )
        validator._validate_transition_handles(transition)

    tracks = sorted(
        (track for track in config.tracks.values() if track.enabled),
        key=lambda item: (item.order, item.id),
    )
    video_tracks = [track for track in tracks if track.kind == "video"]
    if not any(track.clips for track in video_tracks):
        raise TimelineEditError("Transition export requires an enabled video clip")
    all_items = [
        (track, clip)
        for track in tracks
        for clip in sorted(track.clips, key=lambda item: (item.timeline_start, item.id))
    ]
    input_index = {clip.id: index for index, (_, clip) in enumerate(all_items)}
    command = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error"]
    for _, clip in all_items:
        command.extend(["-i", os.fspath(resolved_sources[clip.id])])
    duration = max(
        (clip.timeline_start + clip_duration(clip) for _, clip in all_items),
        default=0.0,
    )
    filters: list[str] = [
        f"color=c=black:s={config.width}x{config.height}:r={config.fps}:d={duration:.12g}[base]"
    ]
    video_layers: list[tuple[int, str, str]] = []
    audio_labels: list[str] = []

    for track in video_tracks:
        clips = sorted(track.clips, key=lambda item: (item.timeline_start, item.id))
        transitions = {
            (transition.from_clip_id, transition.to_clip_id): transition
            for transition in enabled.values()
            if transition.track_id == track.id and transition.media_type == "video"
        }
        for group_index, group in enumerate(_groups(clips, transitions)):
            labels: list[str] = []
            lengths: list[float] = []
            for clip_index, clip in enumerate(group):
                previous_transition = transitions.get((group[clip_index - 1].id, clip.id)) if clip_index else None
                next_transition = transitions.get((clip.id, group[clip_index + 1].id)) if clip_index + 1 < len(group) else None
                incoming = _handles(previous_transition)[1] if previous_transition else 0.0
                outgoing = _handles(next_transition)[0] if next_transition else 0.0
                segment_duration = clip_duration(clip) + incoming + outgoing
                trim_start = clip.trim_in - incoming * clip.speed_factor
                trim_end = clip.trim_out + outgoing * clip.speed_factor
                index = input_index[clip.id]
                raw = f"vt_{track.order}_{group_index}_{clip_index}"
                canvas = f"vc_{track.order}_{group_index}_{clip_index}"
                output = f"vs_{track.order}_{group_index}_{clip_index}"
                visual, overlay = clip_visual_filter_chain(
                    clip,
                    config.width,
                    config.height,
                    local_time_expression=(
                        "t" if incoming <= 1e-9 else f"(t-{incoming:.12g})"
                    ),
                )
                chain = [
                    f"[{index}:v]trim=start={trim_start:.12g}:end={trim_end:.12g}",
                    f"setpts=(PTS-STARTPTS)/{clip.speed_factor:.12g}",
                ]
                if clip.reverse:
                    chain.append("reverse")
                chain.extend((*visual, f"fps={config.fps}", "format=yuva444p", f"settb=AVTB,setpts=PTS-STARTPTS[{raw}]"))
                filters.append(",".join(chain))
                filters.append(
                    f"color=c=black:s={config.width}x{config.height}:r={config.fps}:d={segment_duration:.12g},format=yuva444p[{canvas}]"
                )
                filters.append(f"[{canvas}][{raw}]overlay={overlay}:shortest=1,format=yuv444p[{output}]")
                labels.append(f"[{output}]")
                lengths.append(segment_duration)
            current = labels[0]
            current_duration = lengths[0]
            for index in range(1, len(group)):
                transition = transitions[(group[index - 1].id, group[index].id)]
                next_label = labels[index]
                output = f"vg_{track.order}_{group_index}_{index}"
                if transition.kind == "cut":
                    filters.append(f"{current}{next_label}concat=n=2:v=1:a=0[{output}]")
                    current_duration += lengths[index]
                else:
                    offset = current_duration - transition.duration_seconds
                    filters.append(
                        f"{current}{next_label}xfade=transition={_video_xfade(transition)}:duration={transition.duration_seconds:.12g}:offset={offset:.12g}[{output}]"
                    )
                    current_duration += lengths[index] - transition.duration_seconds
                current = f"[{output}]"
            start = group[0].timeline_start
            positioned = f"vp_{track.order}_{group_index}"
            filters.append(f"{current}setpts=PTS+{start:.12g}/TB[{positioned}]")
            video_layers.append((track.order, f"[{positioned}]", "x=0:y=0"))

    audio_sources: list[tuple[TrackConfig, list[ClipConfig]]] = []
    for track in tracks:
        if track.kind == "audio" and not track.muted and not track.mix.muted:
            audio_sources.append((track, sorted(track.clips, key=lambda item: (item.timeline_start, item.id))))
        elif track.kind == "video" and not track.muted:
            active = [clip for clip in sorted(track.clips, key=lambda item: (item.timeline_start, item.id)) if clip.keep_audio and not clip.audio.muted and _has_audio(os.fspath(resolved_sources[clip.id]))]
            if active:
                audio_sources.append((track, active))
    for track, clips in audio_sources:
        transitions = {
            (transition.from_clip_id, transition.to_clip_id): transition
            for transition in enabled.values()
            if transition.track_id == track.id and transition.media_type == "audio"
        }
        for group_index, group in enumerate(_groups(clips, transitions)):
            labels: list[str] = []
            lengths: list[float] = []
            for clip_index, clip in enumerate(group):
                previous_transition = transitions.get((group[clip_index - 1].id, clip.id)) if clip_index else None
                next_transition = transitions.get((clip.id, group[clip_index + 1].id)) if clip_index + 1 < len(group) else None
                incoming = _handles(previous_transition)[1] if previous_transition else 0.0
                outgoing = _handles(next_transition)[0] if next_transition else 0.0
                segment_duration = clip_duration(clip) + incoming + outgoing
                trim_start = clip.trim_in - incoming * clip.speed_factor
                trim_end = clip.trim_out + outgoing * clip.speed_factor
                index = input_index[clip.id]
                output = f"as_{track.order}_{group_index}_{clip_index}"
                chain = [
                    f"[{index}:a]atrim=start={trim_start:.12g}:end={trim_end:.12g}",
                    "asetpts=PTS-STARTPTS",
                    *_atempo(clip.speed_factor),
                    *_audio_properties(track, clip, segment_duration),
                ]
                if clip.reverse:
                    chain.append("areverse")
                chain.append(f"aresample=48000[{output}]")
                filters.append(",".join(chain))
                labels.append(f"[{output}]")
                lengths.append(segment_duration)
            current = labels[0]
            current_duration = lengths[0]
            for index in range(1, len(group)):
                transition = transitions[(group[index - 1].id, group[index].id)]
                next_label = labels[index]
                output = f"ag_{track.order}_{group_index}_{index}"
                curve = {
                    "audio_equal_power": "qsin",
                    "audio_linear": "tri",
                    "audio_fade_out_in": "exp",
                }.get(transition.kind)
                if curve is None:
                    filters.append(f"{current}{next_label}concat=n=2:v=0:a=1[{output}]")
                    current_duration += lengths[index]
                else:
                    filters.append(
                        f"{current}{next_label}acrossfade=d={transition.duration_seconds:.12g}:c1={curve}:c2={curve}[{output}]"
                    )
                    current_duration += lengths[index] - transition.duration_seconds
                current = f"[{output}]"
            delay = max(0, round(group[0].timeline_start * 1000))
            positioned = f"ap_{track.order}_{group_index}"
            filters.append(f"{current}adelay={delay}|{delay},atrim=end={duration:.12g}[{positioned}]")
            audio_labels.append(f"[{positioned}]")

    current_video = "[base]"
    for layer_index, (_, label, overlay) in enumerate(sorted(video_layers, key=lambda item: item[0])):
        output = f"layer_transition_{layer_index}"
        filters.append(f"{current_video}{label}overlay={overlay}:eof_action=pass:shortest=0[{output}]")
        current_video = f"[{output}]"
    filters.append(f"{current_video}format=yuv420p[video_out]")
    if audio_labels:
        filters.append(
            "".join(audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=longest:normalize=0,alimiter=limit=0.95:level=false,aresample=48000,aformat=channel_layouts=stereo[audio_out]"
        )
    command.extend(["-filter_complex", ";".join(filters), "-map", "[video_out]"])
    if audio_labels:
        command.extend(["-map", "[audio_out]", "-c:a", "aac", "-ar", "48000", "-ac", "2"])
    command.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(config.fps),
        "-t", f"{duration:.12g}", output_path,
    ])
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0:
        diagnostic = " ".join((result.stderr or "").strip().splitlines()[-2:])
        raise RuntimeError("Deterministic transition export failed: " + diagnostic)
    return os.fspath(output)
