"""Read-only deterministic FFmpeg loudness analysis with bounded reuse."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import OrderedDict
from pathlib import Path

from core.timeline import ClipConfig, TimelineConfig
from timeline_edit import TimelineEditEngine

from .models import LoudnessAnalysisRequest, LoudnessAnalysisResult


class LoudnessAnalysisError(ValueError):
    pass


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def source_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clip_audio_state_digest(track_id: str, clip: ClipConfig) -> str:
    """Digest only state that changes the analyzed decoded audio range."""

    return _digest_json(
        {
            "track_id": track_id,
            "clip_id": clip.id,
            "source_ref": clip.source,
            "trim_in": clip.trim_in,
            "trim_out": clip.trim_out,
            "speed_factor": clip.speed_factor,
            "reverse": clip.reverse,
        }
    )


class LoudnessAnalysisService:
    """Analyze exact current clips without mutating project or media state."""

    def __init__(self, *, max_cache_entries: int = 64) -> None:
        self.max_cache_entries = max_cache_entries
        self._cache: OrderedDict[str, LoudnessAnalysisResult] = OrderedDict()

    def analyze(
        self,
        timeline: TimelineConfig,
        request: LoudnessAnalysisRequest,
    ) -> LoudnessAnalysisResult:
        detached = TimelineEditEngine(timeline)
        _, track, clip = detached.clip_state(request.track_id, request.clip_id)
        if track.kind not in {"audio", "video"}:
            raise LoudnessAnalysisError("The target does not expose audio")
        if track.kind == "video" and not clip.keep_audio:
            raise LoudnessAnalysisError("Embedded clip audio is disabled")
        if track.muted or track.mix.muted or clip.audio.muted:
            raise LoudnessAnalysisError("Muted audio cannot be normalized")
        if not os.path.isfile(clip.source):
            raise LoudnessAnalysisError("The configured media is unavailable")
        source_digest = source_sha256(clip.source)
        state_digest = clip_audio_state_digest(track.id, clip)
        cache_key = _digest_json(
            {
                "source_sha256": source_digest,
                "clip_digest": state_digest,
                "target_lufs": request.target_lufs,
                "max_true_peak_dbfs": request.max_true_peak_dbfs,
                "analyzer": "ffmpeg-loudnorm-v1",
            }
        )
        if cache_key in self._cache:
            prior = self._cache.pop(cache_key)
            reused = prior.model_copy(update={"cached": True})
            self._cache[cache_key] = prior
            return reused
        tempo_filters: list[str] = []
        remaining = clip.speed_factor
        while remaining > 2:
            tempo_filters.append("atempo=2")
            remaining /= 2
        while remaining < 0.5:
            tempo_filters.append("atempo=0.5")
            remaining /= 0.5
        if abs(remaining - 1) > 1e-9:
            tempo_filters.append(f"atempo={remaining:.12g}")
        loudnorm_filter = (
            f"loudnorm=I={request.target_lufs:.12g}:"
            f"TP={request.max_true_peak_dbfs:.12g}:LRA=11:"
            "print_format=json"
        )
        command = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{clip.trim_in:.12g}",
            "-t",
            f"{clip.trim_out - clip.trim_in:.12g}",
            "-i",
            clip.source,
            "-vn",
            "-af",
            ",".join((*tempo_filters, loudnorm_filter)),
            "-f",
            "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise LoudnessAnalysisError(
                "Loudness analysis could not decode the selected audio"
            ) from exc
        blocks = re.findall(r"\{[\s\S]*?\}", completed.stderr)
        if not blocks:
            raise LoudnessAnalysisError("FFmpeg returned no loudness evidence")
        try:
            measured = json.loads(blocks[-1])
            integrated = float(measured["input_i"])
            true_peak = float(measured["input_tp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LoudnessAnalysisError("FFmpeg loudness evidence was malformed") from exc
        recommended = min(
            request.target_lufs - integrated,
            request.max_true_peak_dbfs - true_peak,
        )
        recommended = max(-60.0, min(24.0, recommended))
        result = LoudnessAnalysisResult(
            analysis_id=f"loud_{cache_key[:24]}",
            track_id=track.id,
            clip_id=clip.id,
            analyzed_clip_digest=state_digest,
            source_sha256=source_digest,
            integrated_lufs=integrated,
            true_peak_dbfs=true_peak,
            target_lufs=request.target_lufs,
            max_true_peak_dbfs=request.max_true_peak_dbfs,
            recommended_gain_db=recommended,
            cache_key=cache_key,
        )
        self._cache[cache_key] = result
        while len(self._cache) > self.max_cache_entries:
            self._cache.popitem(last=False)
        return result
