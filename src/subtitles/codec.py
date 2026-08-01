"""Deterministic UTF-8 SRT/WebVTT import and export."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.timeline import SubtitleCue, SubtitleTrackConfig


class SubtitleCodecError(ValueError):
    pass


_SRT_TIME = re.compile(r"^(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})$")
_VTT_TIME = re.compile(r"^(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})$")
_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{2,159}$")


def _seconds(value: str, *, vtt: bool) -> float:
    match = (_VTT_TIME if vtt else _SRT_TIME).fullmatch(value.strip())
    if match is None:
        raise SubtitleCodecError("Subtitle timestamp is malformed")
    if vtt:
        hours = int(match.group(1) or 0)
        minutes, seconds, milliseconds = map(int, match.groups()[1:])
    else:
        hours, minutes, seconds, milliseconds = map(int, match.groups())
    if minutes >= 60 or seconds >= 60:
        raise SubtitleCodecError("Subtitle timestamp is outside clock bounds")
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _timestamp(value: float, *, vtt: bool) -> str:
    total_ms = max(0, round(value * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{milliseconds:03d}"


def _generated_id(index: int, start: float, end: float, text: str) -> str:
    digest = hashlib.sha256(f"{index}|{start:.3f}|{end:.3f}|{text}".encode("utf-8")).hexdigest()
    return f"cue_{digest[:24]}"


def decode_text(value: bytes) -> str:
    try:
        return value.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SubtitleCodecError("Subtitle input must be valid UTF-8") from exc


def parse_subtitles(content: str | bytes, format: str, *, language: str = "und") -> tuple[SubtitleCue, ...]:
    text = decode_text(content) if isinstance(content, bytes) else content.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if format == "auto":
        format = "vtt" if text.lstrip().startswith("WEBVTT") else "srt"
    if format not in {"srt", "vtt"}:
        raise SubtitleCodecError("Subtitle format must be srt or vtt")
    if format == "vtt":
        lines = text.split("\n")
        if not lines or lines[0].strip() != "WEBVTT":
            raise SubtitleCodecError("WebVTT input requires a WEBVTT header")
        text = "\n".join(lines[1:]).lstrip("\n")
    blocks = [block for block in re.split(r"\n{2,}", text.strip()) if block.strip()]
    cues: list[SubtitleCue] = []
    for index, block in enumerate(blocks, start=1):
        lines = block.split("\n")
        if format == "vtt" and lines[0].startswith(("NOTE", "STYLE", "REGION")):
            raise SubtitleCodecError("WebVTT NOTE/STYLE/REGION blocks are unsupported")
        cue_id: str | None = None
        timing_index = 0
        if " --> " not in lines[0]:
            candidate = lines[0].strip()
            if format == "srt" and candidate.isdigit():
                timing_index = 1
            else:
                cue_id = candidate
                timing_index = 1
        if timing_index >= len(lines) or " --> " not in lines[timing_index]:
            raise SubtitleCodecError("Subtitle cue is missing a timing line")
        timing = lines[timing_index].split(" --> ", 1)
        start_token = timing[0].strip()
        right = timing[1].strip().split()
        if not right:
            raise SubtitleCodecError("Subtitle cue is missing an end timestamp")
        end_token, raw_settings = right[0], right[1:]
        start = _seconds(start_token, vtt=format == "vtt")
        end = _seconds(end_token, vtt=format == "vtt")
        cue_text = "\n".join(lines[timing_index + 1 :]).strip()
        if not cue_text:
            raise SubtitleCodecError("Subtitle cue text cannot be empty")
        settings = tuple(sorted(raw_settings)) if format == "vtt" else ()
        if format == "srt" and raw_settings:
            raise SubtitleCodecError("SRT timing settings are unsupported")
        safe_id = cue_id if cue_id and _SAFE_ID.fullmatch(cue_id) else _generated_id(index, start, end, cue_text)
        cues.append(SubtitleCue(
            cue_id=safe_id,
            start_seconds=start,
            end_seconds=end,
            text=cue_text,
            language=language,
            settings=settings,
        ))
    if not cues:
        raise SubtitleCodecError("Subtitle input contains no cues")
    return tuple(sorted(cues, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id)))


def _selected_cues(tracks: tuple[SubtitleTrackConfig, ...]) -> tuple[SubtitleCue, ...]:
    return tuple(sorted(
        (cue for track in tracks if track.enabled for cue in track.cues if cue.enabled),
        key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id),
    ))


def export_subtitles(tracks: tuple[SubtitleTrackConfig, ...], format: str) -> str:
    cues = _selected_cues(tracks)
    if format not in {"srt", "vtt"}:
        raise SubtitleCodecError("Subtitle format must be srt or vtt")
    blocks: list[str] = []
    for index, cue in enumerate(cues, start=1):
        timing = f"{_timestamp(cue.start_seconds, vtt=format == 'vtt')} --> {_timestamp(cue.end_seconds, vtt=format == 'vtt')}"
        if format == "vtt" and cue.settings:
            timing += " " + " ".join(cue.settings)
        if format == "srt":
            blocks.append(f"{index}\n{timing}\n{cue.text}")
        else:
            blocks.append(f"{cue.cue_id}\n{timing}\n{cue.text}")
    body = "\n\n".join(blocks)
    return ("WEBVTT\n\n" + body + ("\n" if body else "")) if format == "vtt" else (body + ("\n" if body else ""))


def load_subtitles(path: str, format: str, *, language: str = "und") -> tuple[SubtitleCue, ...]:
    candidate = Path(path)
    if not candidate.is_file():
        raise SubtitleCodecError("Configured subtitle input is unavailable")
    detected = format
    if format == "auto":
        suffix = candidate.suffix.lower()
        if suffix not in {".srt", ".vtt"}:
            raise SubtitleCodecError("Subtitle file extension must be .srt or .vtt")
        detected = suffix[1:]
    return parse_subtitles(candidate.read_bytes(), detected, language=language)
