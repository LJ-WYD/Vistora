"""Deterministic read-only thumbnail and waveform extraction."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import (
    AudioWaveformPeak,
    MediaAnalysisRequest,
    MediaAnalysisResult,
    VideoThumbnailFrame,
)


CommandRunner = Callable[[list[str], float], bytes]


@dataclass(frozen=True)
class AnalysisArtifact:
    """Cached browser-safe artifact bytes without a filesystem route."""

    content: bytes
    content_type: str


@dataclass(frozen=True)
class _CacheEntry:
    result: MediaAnalysisResult
    artifacts: dict[str, AnalysisArtifact]


class MediaAnalysisError(RuntimeError):
    """Media visualization could not be derived safely."""


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_runner(command: list[str], timeout: float) -> bytes:
    completed = subprocess.run(
        command,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return completed.stdout


class MediaAnalysisService:
    """Read-only analyzer with bounded in-memory result/artifact reuse."""

    def __init__(
        self,
        *,
        cache_capacity: int = 64,
        command_runner: CommandRunner | None = None,
        command_timeout_seconds: float = 20.0,
    ) -> None:
        if cache_capacity < 1 or cache_capacity > 512:
            raise ValueError("Analysis cache capacity must be 1..512")
        if command_timeout_seconds <= 0:
            raise ValueError("Analysis timeout must be positive")
        self._capacity = cache_capacity
        self._runner = command_runner or _default_runner
        self._timeout = command_timeout_seconds
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._artifacts: dict[
            tuple[str, str],
            AnalysisArtifact,
        ] = {}
        self.cache_hits = 0
        self.cache_misses = 0

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @staticmethod
    def _analysis_identity(
        request: MediaAnalysisRequest,
        *,
        file_size: int | None,
        modified_ns: int | None,
        status_code: str,
    ) -> str:
        digest = _canonical_digest(
            {
                "request_digest": request.digest(),
                "file_size": file_size,
                "modified_ns": modified_ns,
                "status_code": status_code,
            }
        )
        return f"analysis_{digest[:32]}"

    @staticmethod
    def _result_base(
        request: MediaAnalysisRequest,
        analysis_id: str,
    ) -> dict[str, object]:
        return {
            "analysis_id": analysis_id,
            "request_digest": request.digest(),
            "snapshot_id": request.snapshot_id,
            "source_id": request.source_id,
            "clip_id": request.clip_id,
            "track_key": request.track_key,
            "media_kind": request.media_kind,
            "source_start_seconds": request.source_start_seconds,
            "source_end_seconds": request.source_end_seconds,
            "timeline_start_seconds": request.timeline_start_seconds,
            "timeline_end_seconds": request.timeline_end_seconds,
        }

    def unavailable(
        self,
        request: MediaAnalysisRequest,
        *,
        status: str = "missing",
        status_code: str = "source_unavailable",
    ) -> MediaAnalysisResult:
        if status not in {"missing", "unsupported", "error"}:
            raise ValueError("Unavailable analysis status is invalid")
        analysis_id = self._analysis_identity(
            request,
            file_size=None,
            modified_ns=None,
            status_code=status_code,
        )
        return MediaAnalysisResult(
            **self._result_base(request, analysis_id),
            status=status,
            status_code=status_code,
        )

    def analyze(
        self,
        request: MediaAnalysisRequest,
        source_path: str | Path,
        content_type: str,
    ) -> MediaAnalysisResult:
        path = Path(source_path).resolve(strict=True)
        if not path.is_file():
            return self.unavailable(request)
        if (
            request.media_kind == "video"
            and not content_type.startswith("video/")
        ):
            return self.unavailable(
                request,
                status="unsupported",
                status_code="media_kind_mismatch",
            )
        stat = path.stat()
        internal_key = _canonical_digest(
            {
                "path": str(path),
                "size": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
                "request_digest": request.digest(),
            }
        )
        cached = self._cache.get(internal_key)
        if cached is not None:
            self.cache_hits += 1
            self._cache.move_to_end(internal_key)
            return cached.result

        self.cache_misses += 1
        analysis_id = self._analysis_identity(
            request,
            file_size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            status_code="ready",
        )
        try:
            if request.media_kind == "video":
                result, artifacts = self._analyze_video(
                    request,
                    path,
                    analysis_id,
                )
            else:
                result, artifacts = self._analyze_audio(
                    request,
                    path,
                    analysis_id,
                )
        except (
            OSError,
            subprocess.SubprocessError,
            MediaAnalysisError,
            ValueError,
        ):
            result = MediaAnalysisResult(
                **self._result_base(request, analysis_id),
                status="error",
                status_code="analysis_failed",
            )
            artifacts = {}
        self._store(internal_key, _CacheEntry(result, artifacts))
        return result

    def _store(self, key: str, entry: _CacheEntry) -> None:
        self._cache[key] = entry
        for artifact_id, artifact in entry.artifacts.items():
            self._artifacts[
                (entry.result.analysis_id, artifact_id)
            ] = artifact
        while len(self._cache) > self._capacity:
            _, removed = self._cache.popitem(last=False)
            for artifact_id in removed.artifacts:
                self._artifacts.pop(
                    (removed.result.analysis_id, artifact_id),
                    None,
                )

    def get_artifact(
        self,
        analysis_id: str,
        artifact_id: str,
    ) -> AnalysisArtifact | None:
        if not (
            len(analysis_id) == 41
            and analysis_id.startswith("analysis_")
            and all(char in "0123456789abcdef" for char in analysis_id[9:])
        ):
            return None
        if not (
            len(artifact_id) == 34
            and artifact_id.startswith("thumbnail_")
            and all(char in "0123456789abcdef" for char in artifact_id[10:])
        ):
            return None
        return self._artifacts.get((analysis_id, artifact_id))

    def _analyze_video(
        self,
        request: MediaAnalysisRequest,
        path: Path,
        analysis_id: str,
    ) -> tuple[MediaAnalysisResult, dict[str, AnalysisArtifact]]:
        duration = (
            request.source_end_seconds - request.source_start_seconds
        )
        timeline_duration = (
            request.timeline_end_seconds - request.timeline_start_seconds
        )
        frames: list[VideoThumbnailFrame] = []
        artifacts: dict[str, AnalysisArtifact] = {}
        for index in range(request.settings.thumbnail_count):
            timeline_ratio = (
                (index + 0.5) / request.settings.thumbnail_count
            )
            source_ratio = (
                1 - timeline_ratio
                if request.reverse
                else timeline_ratio
            )
            source_time = (
                request.source_start_seconds + duration * source_ratio
            )
            source_time = min(
                source_time,
                max(
                    request.source_start_seconds,
                    request.source_end_seconds - 0.001,
                ),
            )
            timeline_time = (
                request.timeline_start_seconds
                + timeline_duration * timeline_ratio
            )
            artifact_digest = _canonical_digest(
                {
                    "analysis_id": analysis_id,
                    "index": index,
                    "source_time": round(source_time, 9),
                }
            )
            artifact_id = f"thumbnail_{artifact_digest[:24]}"
            filters = []
            if request.rotate_degrees == 90:
                filters.append("transpose=1")
            elif request.rotate_degrees == 180:
                filters.extend(["hflip", "vflip"])
            elif request.rotate_degrees == 270:
                filters.append("transpose=2")
            filters.append(
                f"scale={request.settings.thumbnail_width}:-2:"
                "flags=lanczos"
            )
            command = [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-ss",
                f"{source_time:.9f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                ",".join(filters),
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-threads",
                "1",
                "pipe:1",
            ]
            content = self._runner(command, self._timeout)
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise MediaAnalysisError("Thumbnail extraction was invalid")
            frames.append(
                VideoThumbnailFrame(
                    artifact_id=artifact_id,
                    source_time_seconds=round(source_time, 6),
                    timeline_time_seconds=round(timeline_time, 6),
                    width=request.settings.thumbnail_width,
                )
            )
            artifacts[artifact_id] = AnalysisArtifact(
                content=content,
                content_type="image/png",
            )
        result = MediaAnalysisResult(
            **self._result_base(request, analysis_id),
            status="ready",
            status_code="ready",
            thumbnails=tuple(frames),
        )
        return result, artifacts

    def _analyze_audio(
        self,
        request: MediaAnalysisRequest,
        path: Path,
        analysis_id: str,
    ) -> tuple[MediaAnalysisResult, dict[str, AnalysisArtifact]]:
        duration = (
            request.source_end_seconds - request.source_start_seconds
        )
        command = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{request.source_start_seconds:.9f}",
            "-t",
            f"{duration:.9f}",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(request.settings.audio_sample_rate),
            "-f",
            "f32le",
            "-threads",
            "1",
            "pipe:1",
        ]
        raw = self._runner(command, self._timeout)
        sample_count = len(raw) // 4
        if sample_count < 1:
            raise MediaAnalysisError("Waveform extraction was empty")
        samples = struct.unpack(
            f"<{sample_count}f",
            raw[: sample_count * 4],
        )
        points = request.settings.waveform_points
        timeline_duration = (
            request.timeline_end_seconds - request.timeline_start_seconds
        )
        peaks: list[AudioWaveformPeak] = []
        for index in range(points):
            start_index = math.floor(index * sample_count / points)
            end_index = math.floor((index + 1) * sample_count / points)
            segment = samples[
                start_index:max(start_index + 1, end_index)
            ]
            minimum = max(-1.0, min(1.0, min(segment)))
            maximum = max(-1.0, min(1.0, max(segment)))
            timeline_start = (
                request.timeline_start_seconds
                + timeline_duration * index / points
            )
            timeline_end = (
                request.timeline_start_seconds
                + timeline_duration * (index + 1) / points
            )
            peaks.append(
                AudioWaveformPeak(
                    index=index,
                    timeline_start_seconds=round(timeline_start, 6),
                    timeline_end_seconds=round(timeline_end, 6),
                    minimum=round(minimum, 6),
                    maximum=round(maximum, 6),
                )
            )
        result = MediaAnalysisResult(
            **self._result_base(request, analysis_id),
            status="ready",
            status_code="ready",
            waveform=tuple(peaks),
        )
        return result, {}
