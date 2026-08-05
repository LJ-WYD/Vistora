"""Safe deterministic sidecar and ASS burn-in services."""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.timeline import SubtitleStyle, SubtitleTrackConfig, TimelineConfig

from .codec import export_subtitles


class SubtitleRenderError(ValueError):
    pass


@dataclass(frozen=True)
class SubtitleCueLayout:
    """Deterministic, path-free layout evidence for one rendered cue."""

    track_id: str
    cue_id: str
    start_seconds: float
    end_seconds: float
    source_text: str
    rendered_text: str
    original_font_size: int
    rendered_font_size: int
    line_count: int
    available_width_px: float
    maximum_line_width_px: float
    safe_area_status: str = "passed"

    def public_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "cue_id": self.cue_id,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "text": self.source_text,
            "rendered_text": self.rendered_text,
            "original_font_size": self.original_font_size,
            "rendered_font_size": self.rendered_font_size,
            "line_count": self.line_count,
            "available_width_px": round(self.available_width_px, 3),
            "maximum_line_width_px": round(self.maximum_line_width_px, 3),
            "safe_area_status": self.safe_area_status,
        }


_FONT_NAMES = {
    "sans": ("Arial", "DejaVu Sans"),
    "serif": ("Times New Roman", "DejaVu Serif"),
    "monospace": ("Consolas", "DejaVu Sans Mono"),
}

_BREAK_AFTER = frozenset(" \t，。！？；：、,.!?;:)]}）》】…—")
_OPENING_PUNCTUATION = frozenset("([{（《【“‘")
_CLOSING_PUNCTUATION = frozenset(")]}），。！？；：、》】”’…")


def _estimated_glyph_width(character: str, font_size: int) -> float:
    """Conservative deterministic width estimate used only for safe wrapping."""

    if unicodedata.combining(character):
        return 0.0
    if character == "\t":
        return font_size * 1.4
    if character.isspace():
        return font_size * 0.38
    east_asian_width = unicodedata.east_asian_width(character)
    if east_asian_width in {"W", "F", "A"}:
        return font_size * 1.04
    if character.isascii():
        if character in "MW@#%&":
            return font_size * 0.92
        if character.isupper() or character.isdigit():
            return font_size * 0.72
        if character.islower():
            return font_size * 0.62
        return font_size * 0.52
    return font_size * 0.92


def _estimated_line_width(value: str, font_size: int) -> float:
    return sum(_estimated_glyph_width(character, font_size) for character in value)


def _wrap_paragraph(value: str, font_size: int, maximum_width: float) -> tuple[str, ...]:
    remaining = value.strip()
    if not remaining:
        return ("",)
    lines: list[str] = []
    while remaining:
        consumed = 0
        width = 0.0
        last_break = 0
        for index, character in enumerate(remaining):
            next_width = width + _estimated_glyph_width(character, font_size)
            if next_width > maximum_width + 1e-6:
                break
            width = next_width
            consumed = index + 1
            if character in _BREAK_AFTER:
                last_break = consumed
        else:
            lines.append(remaining.rstrip())
            break
        if consumed == 0:
            raise SubtitleRenderError("A subtitle glyph cannot fit inside the configured safe area")
        cut = last_break if last_break and consumed - last_break <= 4 else consumed
        if cut < len(remaining) and remaining[cut] in _CLOSING_PUNCTUATION and cut > 1:
            cut -= 1
        while cut > 1 and remaining[cut - 1] in _OPENING_PUNCTUATION:
            cut -= 1
        line = remaining[:cut].rstrip()
        if not line:
            line = remaining[:consumed]
            cut = consumed
        lines.append(line)
        remaining = remaining[cut:].lstrip()
    return tuple(lines)


def _wrap_text(value: str, font_size: int, maximum_width: float) -> tuple[str, ...]:
    lines: list[str] = []
    for paragraph in value.split("\n"):
        lines.extend(_wrap_paragraph(paragraph, font_size, maximum_width))
    return tuple(lines)


def _layout_cue(timeline: TimelineConfig, track: SubtitleTrackConfig, cue) -> tuple[SubtitleStyle, SubtitleCueLayout]:
    base_style = cue.style or track.style
    horizontal_margin = round(timeline.width * base_style.safe_margin_x)
    outline_allowance = 2 * (math.ceil(base_style.outline_width) + 2)
    available_width = timeline.width - (2 * horizontal_margin) - outline_allowance
    if available_width <= 1:
        raise SubtitleRenderError("Subtitle safe margins leave no usable horizontal area")
    automatic_line_limit = 3 if track.kind == "subtitle" or cue.cue_kind == "subtitle" else 2
    # Explicit author line breaks are semantic and must survive legacy
    # split/merge workflows. They extend the cap without weakening the width gate.
    maximum_lines = min(6, automatic_line_limit + cue.text.count("\n"))
    minimum_font_size = max(8, math.floor(base_style.font_size * 0.60))
    best: tuple[SubtitleStyle, SubtitleCueLayout] | None = None
    for font_size in range(base_style.font_size, minimum_font_size - 1, -1):
        lines = _wrap_text(cue.text, font_size, available_width)
        maximum_line_width = max((_estimated_line_width(line, font_size) for line in lines), default=0.0)
        if len(lines) <= maximum_lines and maximum_line_width <= available_width + 1e-6:
            effective_style = (
                base_style
                if font_size == base_style.font_size
                else base_style.model_copy(update={"font_size": font_size})
            )
            candidate = effective_style, SubtitleCueLayout(
                track_id=track.track_id,
                cue_id=cue.cue_id,
                start_seconds=cue.start_seconds,
                end_seconds=cue.end_seconds,
                source_text=cue.text,
                rendered_text="\n".join(lines),
                original_font_size=base_style.font_size,
                rendered_font_size=font_size,
                line_count=len(lines),
                available_width_px=available_width,
                maximum_line_width_px=maximum_line_width,
            )
            if best is None or candidate[1].line_count < best[1].line_count:
                best = candidate
            if candidate[1].line_count == 1:
                break
    if best is not None:
        return best
    raise SubtitleRenderError(
        f"Subtitle cue {cue.cue_id} cannot fit the configured safe area in {maximum_lines} lines"
    )


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


def _selected_tracks(
    timeline: TimelineConfig,
    track_ids: tuple[str, ...],
) -> tuple[SubtitleTrackConfig, ...]:
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
    return tracks


def _prepared_events(
    timeline: TimelineConfig,
    tracks: tuple[SubtitleTrackConfig, ...],
) -> tuple[tuple[SubtitleTrackConfig, object, SubtitleStyle, SubtitleCueLayout], ...]:
    return tuple(
        (track, cue, *_layout_cue(timeline, track, cue))
        for track in tracks
        for cue in track.cues
        if cue.enabled
    )


def analyze_subtitle_layout(
    timeline: TimelineConfig,
    track_ids: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    """Return renderer-produced, path-free safe-area evidence for every cue."""

    tracks = _selected_tracks(timeline, track_ids)
    return tuple(
        layout.public_dict()
        for _, _, _, layout in _prepared_events(timeline, tracks)
    )


def build_ass(timeline: TimelineConfig, track_ids: tuple[str, ...] = ()) -> tuple[str, tuple[str, ...]]:
    tracks = _selected_tracks(timeline, track_ids)
    prepared = _prepared_events(timeline, tracks)
    style_by_digest: dict[str, tuple[str, SubtitleStyle, str]] = {}
    warnings: list[str] = []
    for _, _, style, layout in prepared:
        payload = style.model_dump_json()
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        if digest not in style_by_digest:
            font, fallback = resolve_font(style)
            style_by_digest[digest] = (f"Style_{digest}", style, font)
            if fallback:
                warnings.append(f"Logical font {style.font_family} used deterministic fallback {font}.")
        if layout.rendered_font_size != layout.original_font_size:
            warnings.append(
                f"Cue {layout.cue_id} was auto-fitted from {layout.original_font_size}px "
                f"to {layout.rendered_font_size}px for {layout.line_count} safe lines."
            )
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
    for track, cue, style, layout in prepared:
        digest = hashlib.sha256(style.model_dump_json().encode("utf-8")).hexdigest()[:12]
        style_name = style_by_digest[digest][0]
        speaker = (cue.speaker or "").replace(",", " ")
        dialogue.append(
            f"Dialogue: {track.order},{_ass_time(cue.start_seconds)},{_ass_time(cue.end_seconds)},{style_name},{speaker},0,0,0,,{_ass_text(layout.rendered_text)}"
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
