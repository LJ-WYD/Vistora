"""Versioned, immutable read models for timeline media visualization."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.timeline import ClipColorAdjustment, ClipTransform


MEDIA_ANALYSIS_VERSION = "1.0.0"
AnalysisVersion = Literal["1.0.0"]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
SourceId = Annotated[str, Field(pattern=r"^source_[0-9a-f]{16}$")]
AnalysisId = Annotated[str, Field(pattern=r"^analysis_[0-9a-f]{32}$")]
ArtifactId = Annotated[str, Field(pattern=r"^thumbnail_[0-9a-f]{24}$")]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class AnalysisModel(BaseModel):
    """Strict and frozen base for detached analysis data."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: AnalysisVersion = MEDIA_ANALYSIS_VERSION


class MediaAnalysisSettings(AnalysisModel):
    """Bounded extraction settings included in deterministic cache keys."""

    thumbnail_count: int = Field(default=3, ge=1, le=8)
    thumbnail_width: int = Field(default=192, ge=64, le=512)
    waveform_points: int = Field(default=96, ge=16, le=512)
    audio_sample_rate: Literal[8000] = 8000


class MediaAnalysisRequest(AnalysisModel):
    """One snapshot-bound clip range to analyze without changing its source."""

    schema_name: Literal["vistora.media-analysis-request"] = (
        "vistora.media-analysis-request"
    )
    snapshot_id: str = Field(min_length=3, max_length=128)
    source_id: SourceId
    clip_id: str = Field(min_length=1)
    track_key: str = Field(min_length=1)
    media_kind: Literal["video", "audio"]
    source_start_seconds: FiniteFloat = Field(ge=0)
    source_end_seconds: FiniteFloat = Field(gt=0)
    timeline_start_seconds: FiniteFloat = Field(ge=0)
    timeline_end_seconds: FiniteFloat = Field(gt=0)
    reverse: bool = False
    rotate_degrees: int = 0
    preview_mode: Literal["original", "applied"] = "original"
    visual_digest: Sha256Digest | None = None
    canvas_width: int | None = Field(default=None, gt=0)
    canvas_height: int | None = Field(default=None, gt=0)
    transform: ClipTransform = Field(default_factory=ClipTransform)
    color: ClipColorAdjustment = Field(default_factory=ClipColorAdjustment)
    settings: MediaAnalysisSettings = Field(
        default_factory=MediaAnalysisSettings
    )

    @model_validator(mode="after")
    def ranges_are_forward(self) -> MediaAnalysisRequest:
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("Analysis source range must be forward")
        if self.timeline_end_seconds <= self.timeline_start_seconds:
            raise ValueError("Analysis timeline range must be forward")
        if self.preview_mode == "applied" and (
            self.media_kind != "video"
            or self.visual_digest is None
            or self.canvas_width is None
            or self.canvas_height is None
        ):
            raise ValueError(
                "Applied video preview requires visual digest and canvas"
            )
        if self.preview_mode == "original" and any(
            value is not None
            for value in (
                self.visual_digest,
                self.canvas_width,
                self.canvas_height,
            )
        ):
            raise ValueError("Original preview cannot claim applied visual data")
        return self

    def digest(self) -> str:
        encoded = _canonical_json(
            self.model_dump(mode="json")
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class VideoThumbnailFrame(AnalysisModel):
    """Opaque reference to one deterministic frame held by the cache."""

    artifact_id: ArtifactId
    source_time_seconds: FiniteFloat = Field(ge=0)
    timeline_time_seconds: FiniteFloat = Field(ge=0)
    content_type: Literal["image/png"] = "image/png"
    width: int = Field(gt=0)


class AudioWaveformPeak(AnalysisModel):
    """Normalized min/max amplitude for one aligned timeline interval."""

    index: int = Field(ge=0)
    timeline_start_seconds: FiniteFloat = Field(ge=0)
    timeline_end_seconds: FiniteFloat = Field(gt=0)
    minimum: FiniteFloat = Field(ge=-1, le=1)
    maximum: FiniteFloat = Field(ge=-1, le=1)

    @model_validator(mode="after")
    def peak_is_ordered(self) -> AudioWaveformPeak:
        if self.timeline_end_seconds <= self.timeline_start_seconds:
            raise ValueError("Waveform interval must be forward")
        if self.minimum > self.maximum:
            raise ValueError("Waveform minimum cannot exceed maximum")
        return self


class MediaAnalysisResult(AnalysisModel):
    """Deterministic detached visualization result for one clip range."""

    schema_name: Literal["vistora.media-analysis-result"] = (
        "vistora.media-analysis-result"
    )
    analysis_id: AnalysisId
    request_digest: Sha256Digest
    snapshot_id: str = Field(min_length=3, max_length=128)
    source_id: SourceId
    clip_id: str = Field(min_length=1)
    track_key: str = Field(min_length=1)
    media_kind: Literal["video", "audio"]
    status: Literal["ready", "missing", "unsupported", "error"]
    status_code: str = Field(min_length=1)
    source_start_seconds: FiniteFloat = Field(ge=0)
    source_end_seconds: FiniteFloat = Field(gt=0)
    timeline_start_seconds: FiniteFloat = Field(ge=0)
    timeline_end_seconds: FiniteFloat = Field(gt=0)
    thumbnails: tuple[VideoThumbnailFrame, ...] = ()
    waveform: tuple[AudioWaveformPeak, ...] = ()

    @model_validator(mode="after")
    def payload_matches_kind_and_status(self) -> MediaAnalysisResult:
        if self.status != "ready":
            if self.thumbnails or self.waveform:
                raise ValueError("Unavailable analysis cannot contain data")
            return self
        if self.media_kind == "video":
            if not self.thumbnails or self.waveform:
                raise ValueError(
                    "Ready video analysis requires thumbnails only"
                )
        elif not self.waveform or self.thumbnails:
            raise ValueError(
                "Ready audio analysis requires waveform peaks only"
            )
        return self


class MediaAnalysisCollection(AnalysisModel):
    """Versioned deterministic analysis batch for one timeline snapshot."""

    schema_name: Literal["vistora.media-analysis-collection"] = (
        "vistora.media-analysis-collection"
    )
    snapshot_id: str = Field(min_length=3, max_length=128)
    results: tuple[MediaAnalysisResult, ...] = ()
