"""Safe deterministic sidecar and ASS burn-in services."""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from pathlib import Path

from core.timeline import SubtitleStyle, SubtitleTrackConfig, TimelineConfig

from .codec import export_subtitles


class SubtitleRenderError(ValueError):
    pass


_FONT_NAMES = {
    "sans": ("Arial", "DejaVu Sans"),
    "serif": ("Times New Roman", "DejaVu Serif"),
    "monospace": ("Consolas", "DejaVu Sans Mono"),
}


def _font_exists(name: str) -> bool:
    known_windows = {
        "Arial": "arial.ttf",
        "Times New Roman": "times.ttf",
        "Consolas": "consola.ttf",
    }
    if os.name == "nt":
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        file_name = known_windows.get(name)
        return bool(file_name and (root / file_name).is_file())
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{family}", name],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return name.startswith("DejaVu")


def resolve_font(style: SubtitleStyle) -> tuple[str, bool]:
    logical = (style.font_family, *style.fallback_families, "sans")
    visited: set[str] = set()
    for family in logical:
        if family in visited:
            continue
        visited.add(family)
        for name in _FONT_NAMES[family]:
            if _font_exists(name):
                return name, family != style.font_family or name != _FONT_NAMES[style.font_family][0]
    return "Arial", True


def _ass_color(value: str) -> str:
    red = value[1:3]
    green = value[3:5]
    blue = value[5:7]
    alpha = 255 - int(value[7:9], 16)
    return f"&H{alpha:02X}{blue}{green}{red}"


def _ass_time(value: float) -> str:
    total_cs = max(0, round(value * 100))
    hours, remainder = divmod(total_cs, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _ass_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _alignment(style: SubtitleStyle) -> int:
    columns = {"left": 1, "center": 2, "right": 3}
    rows = {"bottom": 0, "middle": 3, "top": 6}
    return columns[style.alignment] + rows[style.position]


def build_ass(timeline: TimelineConfig, track_ids: tuple[str, ...] = ()) -> tuple[str, tuple[str, ...]]:
    selected = set(track_ids)
    tracks = tuple(sorted(
        (
            track
            for track in timeline.subtitle_tracks.values()
            if track.enabled and (not selected or track.track_id in selected)
        ),
        key=lambda track: (track.order, track.track_id),
    ))
    if selected - {track.track_id for track in timeline.subtitle_tracks.values()}:
        raise SubtitleRenderError("Subtitle burn references an unknown track")
    if not tracks or not any(cue.enabled for track in tracks for cue in track.cues):
        raise SubtitleRenderError("Subtitle burn requires an enabled cue")
    style_by_digest: dict[str, tuple[str, SubtitleStyle, str]] = {}
    warnings: list[str] = []
    for track in tracks:
        for cue in track.cues:
            if not cue.enabled:
                continue
            style = cue.style or track.style
            payload = style.model_dump_json()
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
            if digest not in style_by_digest:
                font, fallback = resolve_font(style)
                style_by_digest[digest] = (f"Style_{digest}", style, font)
                if fallback:
                    warnings.append(f"Logical font {style.font_family} used deterministic fallback {font}.")
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {timeline.width}\nPlayResY: {timeline.height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    style_lines: list[str] = []
    for name, style, font in sorted(style_by_digest.values(), key=lambda item: item[0]):
        margin_l = round(timeline.width * style.safe_margin_x)
        margin_v = round(timeline.height * style.safe_margin_y)
        border_style = 3 if style.background_color != "#00000000" else 1
        style_lines.append(
            "Style: " + ",".join((
                name, font, str(style.font_size), _ass_color(style.color), _ass_color(style.color),
                _ass_color(style.outline_color), _ass_color(style.background_color),
                "-1" if style.bold else "0", "-1" if style.italic else "0", "0", "0",
                "100", "100", "0", "0", str(border_style), f"{style.outline_width:.3f}", "0",
                str(_alignment(style)), str(margin_l), str(margin_l), str(margin_v), "1",
            ))
        )
    events = "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    dialogue: list[str] = []
    for track in tracks:
        for cue in track.cues:
            if not cue.enabled:
                continue
            style = cue.style or track.style
            digest = hashlib.sha256(style.model_dump_json().encode("utf-8")).hexdigest()[:12]
            style_name = style_by_digest[digest][0]
            speaker = (cue.speaker or "").replace(",", " ")
            dialogue.append(
                f"Dialogue: {track.order},{_ass_time(cue.start_seconds)},{_ass_time(cue.end_seconds)},{style_name},{speaker},0,0,0,,{_ass_text(cue.text)}"
            )
    return header + "\n".join(style_lines) + events + "\n".join(dialogue) + "\n", tuple(sorted(set(warnings)))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_sidecar(timeline: TimelineConfig, output_path: str, format: str, track_ids: tuple[str, ...]) -> dict[str, object]:
    path = Path(output_path)
    expected = ".srt" if format == "srt" else ".vtt"
    if path.suffix.lower() != expected:
        raise SubtitleRenderError(f"Subtitle sidecar must use {expected}")
    selected = set(track_ids)
    tracks = tuple(sorted(
        (track for track in timeline.subtitle_tracks.values() if not selected or track.track_id in selected),
        key=lambda track: (track.order, track.track_id),
    ))
    if selected - {track.track_id for track in timeline.subtitle_tracks.values()}:
        raise SubtitleRenderError("Subtitle export references an unknown track")
    content = export_subtitles(tracks, format)
    _atomic_write(path, content.encode("utf-8"))
    return {
        "status": "success",
        "format": format,
        "output_path": str(path),
        "track_ids": [track.track_id for track in tracks],
        "cue_count": sum(1 for track in tracks for cue in track.cues if track.enabled and cue.enabled),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def burn_subtitles(base_video: str, output_path: str, timeline: TimelineConfig, track_ids: tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    source = Path(base_video)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    ass_path = target.parent / f".vistora-subtitles-{token}.ass"
    rendered = target.parent / f".vistora-burn-{token}{target.suffix or '.mp4'}"
    ass, warnings = build_ass(timeline, track_ids)
    _atomic_write(ass_path, ass.encode("utf-8"))
    escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", str(source),
                "-vf", f"ass=filename='{escaped}'", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "copy", str(rendered),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        os.replace(rendered, target)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SubtitleRenderError("Subtitle burn-in backend failed") from exc
    finally:
        ass_path.unlink(missing_ok=True)
        rendered.unlink(missing_ok=True)
    return str(target), warnings
