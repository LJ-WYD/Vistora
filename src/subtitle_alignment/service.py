"""Narration-bound subtitle alignment, deterministic cue building, and sync QC."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from array import array
from pathlib import Path
from typing import Protocol

from audio_analysis import clip_audio_state_digest, source_sha256
from core.timeline import SubtitleCue, SubtitleWord, TimelineConfig, effective_clip_duration
from timeline_edit import TimelineEditEngine

from .models import (
    AlignedPhrase, AlignmentWord, AudioAlignTranscriptInput,
    SubtitleAlignmentReport, SubtitleSyncQCInput, SubtitleSyncQCResult,
    digest_json,
)


class SubtitleAlignmentError(ValueError):
    pass


class WordAlignmentProvider(Protocol):
    provider_id: str
    provider_version: str

    def align(self, *, source_path: str, trim_in: float, trim_out: float, speed_factor: float, language: str) -> tuple[dict, ...]: ...


class FasterWhisperSubprocessProvider:
    provider_id = "faster-whisper"
    provider_version = "1.0.0"

    def __init__(self, *, python_executable: str | None = None, model_name: str | None = None):
        self.python_executable = python_executable or os.getenv("VISTORA_ALIGNMENT_PYTHON")
        self.model_name = model_name or os.getenv("VISTORA_ALIGNMENT_MODEL")

    def align(self, *, source_path, trim_in, trim_out, speed_factor, language):
        if not self.python_executable or not self.model_name:
            raise SubtitleAlignmentError("Word alignment provider is not configured")
        script = Path(__file__).resolve().parents[2] / "scripts" / "vistora_faster_whisper_words.py"
        try:
            completed = subprocess.run(
                [self.python_executable, str(script), "--audio", source_path, "--model", self.model_name,
                 "--language", language, "--trim-in", str(trim_in), "--trim-out", str(trim_out),
                 "--speed", str(speed_factor)],
                check=True, capture_output=True, text=True, encoding="utf-8", timeout=1800,
            )
            payload = json.loads(completed.stdout)
            words = payload["words"]
            if not isinstance(words, list) or not words:
                raise ValueError
            return tuple(words)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise SubtitleAlignmentError("Word alignment provider failed without safe evidence") from exc


def _normalized(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _map_phrases(request: AudioAlignTranscriptInput, raw_words: tuple[dict, ...]) -> tuple[AlignedPhrase, ...]:
    normalized_words = []
    for index, raw in enumerate(raw_words):
        text = str(raw.get("text", "")).strip()
        token = _normalized(text)
        if not token:
            continue
        try:
            start, end = float(raw["start_seconds"]), float(raw["end_seconds"])
            confidence = float(raw.get("confidence", 1.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise SubtitleAlignmentError("Alignment provider returned malformed word evidence") from exc
        normalized_words.append((index, text, token, start, end, max(0.0, min(1.0, confidence))))
    stream = "".join(item[2] for item in normalized_words)
    offsets = []
    cursor = 0
    for item in normalized_words:
        offsets.append((cursor, cursor + len(item[2]), item))
        cursor += len(item[2])
    phrases, search_from = [], 0
    for phrase in request.phrases:
        target = _normalized(phrase.text)
        if not target:
            raise SubtitleAlignmentError("Transcript phrase has no alignable text")
        position = stream.find(target, search_from)
        if position < 0:
            raise SubtitleAlignmentError("Transcript could not be bound to the recognized narration")
        limit = position + len(target)
        selected = [item for start, end, item in offsets if end > position and start < limit]
        if not selected:
            raise SubtitleAlignmentError("Transcript phrase has no word evidence")
        confidence = sum(item[5] for item in selected) / len(selected)
        if confidence < request.minimum_confidence:
            raise SubtitleAlignmentError("Transcript alignment confidence is below the confirmed threshold")
        words = tuple(AlignmentWord(
            word_id=f"{phrase.phrase_id}.word.{word_index:03d}", text=item[1],
            start_seconds=item[3], end_seconds=item[4], confidence=item[5],
        ) for word_index, item in enumerate(selected, 1))
        phrases.append(AlignedPhrase(
            phrase_id=phrase.phrase_id, text=phrase.text,
            start_seconds=words[0].start_seconds, end_seconds=words[-1].end_seconds,
            confidence=confidence, words=words,
        ))
        search_from = limit
    return tuple(phrases)


class SubtitleAlignmentService:
    def __init__(self, provider: WordAlignmentProvider | None = None):
        self.provider = provider or FasterWhisperSubprocessProvider()

    def analyze(self, timeline: TimelineConfig, request: AudioAlignTranscriptInput) -> SubtitleAlignmentReport:
        _, track, clip = TimelineEditEngine(timeline).clip_state(request.track_id, request.clip_id)
        if track.kind not in {"audio", "video"} or (track.kind == "video" and not clip.keep_audio):
            raise SubtitleAlignmentError("Selected clip does not expose narration audio")
        if clip.reverse or clip.freeze_frame is not None:
            raise SubtitleAlignmentError("Word alignment requires forward, non-frozen narration")
        if track.muted or track.mix.muted or clip.audio.muted:
            raise SubtitleAlignmentError("Muted narration cannot produce subtitle alignment evidence")
        if not os.path.isfile(clip.source):
            raise SubtitleAlignmentError("Configured narration media is unavailable")
        duration = effective_clip_duration(clip)
        raw_words = self.provider.align(
            source_path=clip.source, trim_in=clip.trim_in, trim_out=clip.trim_out,
            speed_factor=clip.speed_factor, language=request.language,
        )
        phrases = _map_phrases(request, raw_words)
        if phrases[-1].end_seconds > duration + 1e-3:
            raise SubtitleAlignmentError("Alignment exceeds the selected narration clip")
        transcript_digest = digest_json([item.model_dump(mode="json") for item in request.phrases])
        values = dict(
            report_id=f"align_{transcript_digest[7:31]}", provider_id=self.provider.provider_id,
            provider_version=self.provider.provider_version, track_id=track.id, clip_id=clip.id,
            source_sha256=source_sha256(clip.source), analyzed_clip_digest=clip_audio_state_digest(track.id, clip),
            audio_duration_seconds=duration, timeline_start_seconds=clip.timeline_start,
            language=request.language, transcript_digest=transcript_digest,
            display_lead_seconds=request.display_lead_seconds, phrases=phrases,
        )
        return SubtitleAlignmentReport.create(**values)


def build_aligned_cues(report: SubtitleAlignmentReport, cue_id_prefix: str) -> tuple[SubtitleCue, ...]:
    starts = []
    previous_phrase_end = report.timeline_start_seconds
    for item in report.phrases:
        starts.append(max(
            report.timeline_start_seconds,
            report.timeline_start_seconds + item.start_seconds - report.display_lead_seconds,
            previous_phrase_end,
        ))
        previous_phrase_end = report.timeline_start_seconds + item.end_seconds
    cues = []
    for index, phrase in enumerate(report.phrases):
        start = starts[index]
        phrase_end = report.timeline_start_seconds + phrase.end_seconds
        end = starts[index + 1] if index + 1 < len(starts) else min(
            report.timeline_start_seconds + report.audio_duration_seconds,
            phrase_end + 0.20,
        )
        end = max(end, phrase_end)
        words = tuple(SubtitleWord(
            word_id=f"{cue_id_prefix}.word.{index + 1:03d}.{word_index:03d}",
            text=word.text,
            start_seconds=report.timeline_start_seconds + word.start_seconds,
            end_seconds=report.timeline_start_seconds + word.end_seconds,
            confidence=word.confidence,
        ) for word_index, word in enumerate(phrase.words, 1))
        cues.append(SubtitleCue(
            cue_id=f"{cue_id_prefix}.cue.{index + 1:03d}", start_seconds=start,
            end_seconds=end, text=phrase.text, language=report.language, words=words,
        ))
    return tuple(cues)


def validate_report_source(timeline: TimelineConfig, report: SubtitleAlignmentReport):
    _, track, clip = TimelineEditEngine(timeline).clip_state(report.track_id, report.clip_id)
    if clip_audio_state_digest(track.id, clip) != report.analyzed_clip_digest:
        raise SubtitleAlignmentError("Subtitle alignment is stale for the narration clip")
    if source_sha256(clip.source) != report.source_sha256:
        raise SubtitleAlignmentError("Subtitle alignment source content changed")
    if abs(clip.timeline_start - report.timeline_start_seconds) > 1e-6:
        raise SubtitleAlignmentError("Subtitle alignment timeline position changed")
    return track, clip


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _energy(path: str, *, trim_in: float | None = None, trim_out: float | None = None, speed_factor: float = 1.0) -> list[float]:
    command = ["ffmpeg", "-v", "error", "-nostdin"]
    if trim_in is not None:
        command.extend(["-ss", f"{trim_in:.12g}"])
    if trim_in is not None and trim_out is not None:
        command.extend(["-t", f"{trim_out - trim_in:.12g}"])
    command.extend(["-i", path, "-vn"])
    tempo = []
    remaining = speed_factor
    while remaining > 2:
        tempo.append("atempo=2")
        remaining /= 2
    while remaining < 0.5:
        tempo.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1) > 1e-9:
        tempo.append(f"atempo={remaining:.12g}")
    if tempo:
        command.extend(["-af", ",".join(tempo)])
    command.extend(["-ac", "1", "-ar", "8000", "-f", "f32le", "-"])
    try:
        completed = subprocess.run(
            command,
            check=True, capture_output=True, timeout=120,
        )
    except subprocess.SubprocessError as exc:
        raise SubtitleAlignmentError("Rendered audio could not be decoded for sync QC") from exc
    samples = array("f")
    samples.frombytes(completed.stdout)
    frame = 160
    return [math.sqrt(sum(value * value for value in samples[index:index + frame]) / max(1, len(samples[index:index + frame]))) for index in range(0, len(samples), frame)]


def _correlate(left: list[float], right: list[float], maximum_lag_frames=50):
    best = (0, -1.0)
    for lag in range(-maximum_lag_frames, maximum_lag_frames + 1):
        a = left[max(0, -lag):min(len(left), len(right) - lag)]
        b = right[max(0, lag):min(len(right), len(left) + lag)]
        if len(a) < 20:
            continue
        mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
        numerator = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        denominator = math.sqrt(sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b))
        score = numerator / denominator if denominator else -1.0
        if score > best[1]:
            best = (lag, score)
    return best[0] * 0.02, best[1]


class SubtitleSyncQCService:
    def analyze(self, timeline: TimelineConfig, request: SubtitleSyncQCInput) -> SubtitleSyncQCResult:
        _, clip = validate_report_source(timeline, request.report)
        expected = {cue.cue_id: cue for cue in build_aligned_cues(request.report, request.cue_id_prefix)}
        matches = [track for track in timeline.subtitle_tracks.values() if track.track_id == request.track_id]
        if len(matches) != 1:
            raise SubtitleAlignmentError("Subtitle sync QC requires one exact subtitle track")
        actual = {cue.cue_id: cue for cue in matches[0].cues if cue.enabled}
        missing = tuple(sorted(set(expected) - set(actual)))
        extra = tuple(sorted(set(actual) - set(expected)))
        mismatched, maximum_error = [], 0.0
        for cue_id in sorted(set(expected) & set(actual)):
            left, right = expected[cue_id], actual[cue_id]
            error = max(abs(left.start_seconds - right.start_seconds), abs(left.end_seconds - right.end_seconds))
            maximum_error = max(maximum_error, error)
            if error > request.maximum_timeline_error_seconds or left.text != right.text or left.words != right.words:
                mismatched.append(cue_id)
        timeline_ok = not missing and not extra and not mismatched
        rendered_digest = None
        offset = correlation = None
        checks = ["source_binding_passed", "timeline_words_passed" if timeline_ok else "timeline_words_failed"]
        rendered_ok = True
        if request.rendered_media_path is not None:
            path = os.path.realpath(request.rendered_media_path)
            if not os.path.isfile(path):
                raise SubtitleAlignmentError("Rendered media is unavailable for sync QC")
            rendered_digest = _sha256(path)
            if request.expected_rendered_sha256 and rendered_digest != request.expected_rendered_sha256:
                raise SubtitleAlignmentError("Rendered media content changed before sync QC")
            measured_lag, correlation = _correlate(
                _energy(
                    clip.source, trim_in=clip.trim_in, trim_out=clip.trim_out,
                    speed_factor=clip.speed_factor,
                ),
                _energy(path),
                maximum_lag_frames=max(
                    50,
                    math.ceil((request.report.timeline_start_seconds + 1.0) / 0.02),
                ),
            )
            offset = measured_lag - request.report.timeline_start_seconds
            rendered_ok = abs(offset) <= request.maximum_audio_mux_offset_seconds and correlation >= 0.75
            checks.append("rendered_audio_sync_passed" if rendered_ok else "rendered_audio_sync_failed")
        status = "passed" if timeline_ok and rendered_ok else "failed"
        values = dict(
            status=status, sync_qc_id=f"sync_{request.report.report_digest[7:31]}",
            report_id=request.report.report_id, report_digest=request.report.report_digest,
            track_id=request.track_id, source_sha256=request.report.source_sha256,
            analyzed_clip_digest=request.report.analyzed_clip_digest,
            timeline_status="passed" if timeline_ok else "failed",
            maximum_timeline_error_seconds=maximum_error, missing_cue_ids=missing,
            extra_cue_ids=extra, mismatched_cue_ids=tuple(mismatched),
            rendered_content_sha256=rendered_digest, audio_mux_offset_seconds=offset,
            audio_correlation=correlation, checks=tuple(checks),
        )
        return SubtitleSyncQCResult.create(**values)
