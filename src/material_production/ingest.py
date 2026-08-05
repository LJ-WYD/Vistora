"""Deterministic, local-only material ingest enrichment and derivatives."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from creation_planning import MaterialProductionTask
from director import digest_json

from .models import (
    ArtifactValidation,
    MaterialAnalysisSummary,
    MaterialDerivative,
    MaterialQualityCheck,
    MaterialQualityReport,
    MaterialTag,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _stable_id(prefix: str, value) -> str:
    return f"{prefix}_{digest_json(value)[7:23]}"


@dataclass(frozen=True)
class MaterialIngestBundle:
    derivatives: tuple[MaterialDerivative, ...]
    derivative_sources: dict[str, Path]
    analysis: MaterialAnalysisSummary
    tags: tuple[MaterialTag, ...]
    quality_report: MaterialQualityReport


class MaterialIngestError(ValueError):
    pass


class MaterialIngestPipeline:
    """Creates managed derivatives and technical facts without touching sources."""

    def __init__(
        self,
        staging_root: str | Path,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.staging_root = Path(staging_root)
        self.clock = clock

    def process(
        self,
        *,
        staged_path: Path,
        validation: ArtifactValidation,
        task: MaterialProductionTask,
        material_id: str,
    ) -> MaterialIngestBundle:
        root = self.staging_root.resolve()
        source = staged_path.resolve()
        if root not in source.parents or not source.is_file():
            raise MaterialIngestError("Material ingest source is unavailable")
        if not validation.passed or validation.sha256 != _sha256(source):
            raise MaterialIngestError("Material ingest validation binding drifted")
        probe = self._probe(source)
        analysis = self._analysis(validation, task, probe)
        quality = self._quality(validation, task, source, probe)
        if quality.overall_status == "failed":
            raise MaterialIngestError("Material quality checks failed")
        derivative_root = source.parent / "ingest_derivatives"
        derivative_root.mkdir(parents=True, exist_ok=True)
        created: list[Path] = []
        try:
            specifications = self._create_derivatives(
                source,
                derivative_root,
                task.delivery.media_kind,
            )
            derivatives = []
            sources = {}
            for role, path, mime_type in specifications:
                created.append(path)
                metadata = self._probe(path)
                relative = (
                    f"{material_id}/{material_id}.{role}{path.suffix.lower()}"
                )
                derivative = MaterialDerivative(
                    derivative_id=_stable_id(
                        "derivative", [validation.sha256, role]
                    ),
                    role=role,
                    managed_relative_path=relative,
                    sha256=_sha256(path),
                    size_bytes=path.stat().st_size,
                    mime_type=mime_type,
                    container=metadata["container"],
                    video_codec=metadata["video_codec"],
                    audio_codec=metadata["audio_codec"],
                    duration_seconds=metadata["duration_seconds"],
                    width=metadata["width"],
                    height=metadata["height"],
                    fps=metadata["fps"],
                )
                derivatives.append(derivative)
                sources[relative] = path
        except Exception as exc:
            for path in created:
                path.unlink(missing_ok=True)
            raise MaterialIngestError(
                "Material proxy/transcode generation failed"
            ) from exc
        tags = self._tags(validation, task, analysis)
        return MaterialIngestBundle(
            derivatives=tuple(sorted(derivatives, key=lambda item: item.role)),
            derivative_sources=sources,
            analysis=analysis,
            tags=tags,
            quality_report=quality,
        )

    def _create_derivatives(self, source, root, media_kind):
        if media_kind == "video":
            normalized = root / "normalized.mp4"
            proxy = root / "proxy.mp4"
            self._run([
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a?", "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-ar", "48000", "-ac", "2", str(normalized),
            ])
            self._run([
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a?", "-vf",
                "scale=w='min(640,iw)':h=-2", "-c:v", "libx264", "-crf", "28",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                "-ar", "48000", "-ac", "2", str(proxy),
            ])
            return (
                ("normalized", normalized, "video/mp4"),
                ("proxy", proxy, "video/mp4"),
            )
        if media_kind == "audio":
            normalized = root / "normalized.wav"
            proxy = root / "proxy.m4a"
            self._run([
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-map", "0:a:0", "-c:a", "pcm_s16le", "-ar", "48000",
                "-ac", "2", str(normalized),
            ])
            self._run([
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ar",
                "48000", "-ac", "2", str(proxy),
            ])
            return (
                ("normalized", normalized, "audio/wav"),
                ("proxy", proxy, "audio/mp4"),
            )
        normalized = root / "normalized.png"
        proxy = root / "proxy.jpg"
        self._run([
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-frames:v", "1", str(normalized),
        ])
        self._run([
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vf", "scale=w='min(640,iw)':h=-2", "-frames:v", "1",
            "-q:v", "3", str(proxy),
        ])
        return (
            ("normalized", normalized, "image/png"),
            ("proxy", proxy, "image/jpeg"),
        )

    @staticmethod
    def _run(command):
        subprocess.run(command, check=True, capture_output=True)

    @staticmethod
    def _probe(path: Path):
        process = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                "-show_entries", "format=format_name,duration", "-of", "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(process.stdout)
        streams = payload.get("streams", [])
        video = next((item for item in streams if item.get("codec_type") == "video"), {})
        audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
        fps = None
        rate = video.get("r_frame_rate")
        if rate:
            numerator, denominator = rate.split("/", 1)
            if float(denominator):
                fps = float(numerator) / float(denominator)
        duration = float(payload.get("format", {}).get("duration", 0) or 0) or None
        return {
            "container": payload.get("format", {}).get("format_name"),
            "duration_seconds": duration,
            "width": int(video.get("width", 0) or 0) or None,
            "height": int(video.get("height", 0) or 0) or None,
            "fps": fps,
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "audio_sample_rate": int(audio.get("sample_rate", 0) or 0) or None,
            "audio_channels": int(audio.get("channels", 0) or 0) or None,
        }

    def _analysis(self, validation, task, probe):
        orientation = "not_applicable"
        if probe["width"] is not None:
            orientation = (
                "square" if probe["width"] == probe["height"]
                else "landscape" if probe["width"] > probe["height"]
                else "portrait"
            )
        values = {
            "analysis_id": _stable_id("material_analysis", validation.sha256),
            "source_sha256": validation.sha256,
            "media_kind": task.delivery.media_kind,
            "duration_seconds": probe["duration_seconds"],
            "width": probe["width"],
            "height": probe["height"],
            "fps": probe["fps"],
            "video_codec": probe["video_codec"],
            "audio_codec": probe["audio_codec"],
            "audio_sample_rate": probe["audio_sample_rate"],
            "audio_channels": probe["audio_channels"],
            "orientation": orientation,
        }
        shell = MaterialAnalysisSummary.model_construct(
            schema_name="vistora.material-catalog.analysis",
            schema_version="1.0.0",
            technical_digest="sha256:" + "0" * 64,
            **values,
        )
        return MaterialAnalysisSummary(
            **values,
            technical_digest=digest_json(
                shell.model_dump(mode="json", exclude={"technical_digest"})
            ),
        )

    def _quality(self, validation, task, source, probe):
        checks = []
        try:
            self._run([
                "ffmpeg", "-v", "error", "-i", str(source), "-map", "0",
                "-f", "null", os.devnull,
            ])
            decode = True
        except Exception:
            decode = False
        checks.append(MaterialQualityCheck(
            check_id="check_full_decode",
            status="passed" if decode else "failed",
            message=("Full media decode succeeded." if decode else "Full media decode failed."),
        ))
        checks.append(MaterialQualityCheck(
            check_id="check_hash_binding",
            status="passed",
            message="Artifact hash matches the validated production result.",
        ))
        stream_ok = (
            (task.delivery.media_kind in {"video", "image"} and probe["video_codec"] is not None)
            or (task.delivery.media_kind == "audio" and probe["audio_codec"] is not None)
        )
        checks.append(MaterialQualityCheck(
            check_id="check_required_stream",
            status="passed" if stream_ok else "failed",
            message=("Required media stream is present." if stream_ok else "Required media stream is missing."),
        ))
        checks.append(MaterialQualityCheck(
            check_id="check_specification",
            status="passed",
            message="Duration, dimensions, frame rate, MIME and container passed the confirmed-plan validator.",
        ))
        if probe["audio_channels"] is not None:
            channel_status = "passed" if probe["audio_channels"] <= 2 else "warning"
            checks.append(MaterialQualityCheck(
                check_id="check_supported_audio_layout",
                status=channel_status,
                message=(
                    "Audio channel layout is supported by normalized derivatives."
                    if channel_status == "passed"
                    else "Multichannel source is preserved as original and normalized to stereo derivatives."
                ),
            ))
        checks = tuple(sorted(checks, key=lambda item: item.check_id))
        statuses = {item.status for item in checks}
        overall = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
        values = {
            "report_id": _stable_id("material_quality", validation.sha256),
            "source_sha256": validation.sha256,
            "overall_status": overall,
            "full_decode_passed": decode,
            "checks": checks,
            "completed_at": self.clock(),
        }
        shell = MaterialQualityReport.model_construct(
            schema_name="vistora.material-catalog.quality-report",
            schema_version="1.0.0",
            report_digest="sha256:" + "0" * 64,
            **values,
        )
        return MaterialQualityReport(
            **values,
            report_digest=digest_json(
                shell.model_dump(mode="json", exclude={"report_digest"})
            ),
        )

    @staticmethod
    def _tags(validation, task, analysis):
        values = {
            ("technical", "media_kind", analysis.media_kind, "deterministic_analysis"),
            ("technical", "orientation", analysis.orientation, "deterministic_analysis"),
            ("workflow", "production_method", task.production_method, "production_plan"),
        }
        if analysis.video_codec:
            values.add(("technical", "video_codec", analysis.video_codec, "deterministic_analysis"))
        if analysis.audio_codec:
            values.add(("technical", "audio_codec", analysis.audio_codec, "deterministic_analysis"))
        if analysis.duration_seconds:
            bucket = "short" if analysis.duration_seconds < 10 else "medium" if analysis.duration_seconds < 60 else "long"
            values.add(("technical", "duration_bucket", bucket, "deterministic_analysis"))
        return tuple(
            MaterialTag(
                tag_id=_stable_id("material_tag", [validation.sha256, namespace, name, value]),
                namespace=namespace,
                name=name,
                value=value,
                source=source,
            )
            for namespace, name, value, source in sorted(values)
        )


__all__ = ["MaterialIngestBundle", "MaterialIngestError", "MaterialIngestPipeline"]
