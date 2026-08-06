"""Frozen, versioned contracts for original O31 finished-media QC."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from director import digest_json
from subtitle_alignment import SubtitleSyncQCResult


Digest = str
StableId = str


class QCModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"


class DeliveryQCProfile(QCModel):
    schema_name: Literal["vistora.delivery-qc-profile"] = "vistora.delivery-qc-profile"
    profile_id: StableId
    minimum_duration_seconds: float = Field(default=0.05, ge=0, allow_inf_nan=False)
    maximum_duration_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    expected_width: int | None = Field(default=None, ge=16, le=16384)
    expected_height: int | None = Field(default=None, ge=16, le=16384)
    allowed_video_codecs: tuple[StableId, ...] = ("av1", "h264", "hevc", "vp9")
    allowed_audio_codecs: tuple[StableId, ...] = ("aac", "flac", "opus", "pcm_s16le")
    require_audio: bool = True
    minimum_audio_streams: int = Field(default=1, ge=0, le=32)
    maximum_audio_streams: int = Field(default=8, ge=0, le=32)
    require_subtitles: bool = False
    require_subtitle_sync: bool = False
    black_duration_threshold_seconds: float = Field(default=0.5, gt=0, le=30, allow_inf_nan=False)
    freeze_duration_threshold_seconds: float = Field(default=2.0, gt=0, le=120, allow_inf_nan=False)
    target_lufs: float = Field(default=-14, ge=-36, le=-5, allow_inf_nan=False)
    loudness_tolerance_lu: float = Field(default=2, gt=0, le=10, allow_inf_nan=False)
    maximum_true_peak_dbtp: float = Field(default=-1, ge=-12, le=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def exact(self):
        if self.maximum_duration_seconds is not None and self.maximum_duration_seconds < self.minimum_duration_seconds:
            raise ValueError("QC duration range is inverted")
        if self.minimum_audio_streams > self.maximum_audio_streams:
            raise ValueError("QC audio stream range is inverted")
        if self.allowed_video_codecs != tuple(sorted(set(self.allowed_video_codecs))):
            raise ValueError("QC video codecs must be unique and ordered")
        if self.allowed_audio_codecs != tuple(sorted(set(self.allowed_audio_codecs))):
            raise ValueError("QC audio codecs must be unique and ordered")
        return self

class QCSubtitleCueEvidence(QCModel):
    schema_name: Literal["vistora.qc-subtitle-cue-evidence"] = "vistora.qc-subtitle-cue-evidence"
    cue_id: StableId
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=4000)
    safe_area_status: Literal["passed", "failed", "unknown"] = "unknown"

    @model_validator(mode="after")
    def forward(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("QC subtitle cue must have positive duration")
        return self


class DeliveryQCRequest(QCModel):
    schema_name: Literal["vistora.delivery-qc-request"] = "vistora.delivery-qc-request"
    request_id: StableId
    project_id: StableId
    project_revision: int = Field(ge=0)
    asset_id: StableId
    expected_content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    profile: DeliveryQCProfile
    subtitle_cues: tuple[QCSubtitleCueEvidence, ...] = ()
    subtitle_sync_evidence: SubtitleSyncQCResult | None = None

    @model_validator(mode="after")
    def exact_subtitles(self):
        ids = [item.cue_id for item in self.subtitle_cues]
        if ids != sorted(set(ids)):
            raise ValueError("QC subtitle evidence must have unique ordered IDs")
        if self.profile.require_subtitle_sync:
            evidence = self.subtitle_sync_evidence
            if evidence is None or evidence.status != "passed":
                raise ValueError("QC requires passed subtitle synchronization evidence")
            if evidence.rendered_content_sha256 is None or (
                "sha256:" + evidence.rendered_content_sha256
                != self.expected_content_digest
            ):
                raise ValueError("Subtitle sync evidence is not bound to this finished asset")
        return self

    def digest(self):
        return digest_json(self.model_dump(mode="json"))


class DeliveryQCCheck(QCModel):
    schema_name: Literal["vistora.delivery-qc-check"] = "vistora.delivery-qc-check"
    check_id: Literal[
        "audio_tracks", "black_frames", "codec", "duration", "frame_size",
        "freeze_frames", "full_decode", "loudness", "subtitles",
        "subtitle_sync",
    ]
    status: Literal["passed", "warning", "failed", "not_applicable"]
    message: str = Field(min_length=1, max_length=500)
    observed: dict[str, object] = Field(default_factory=dict)


class DeliveryMediaProbe(QCModel):
    schema_name: Literal["vistora.delivery-media-probe"] = "vistora.delivery-media-probe"
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    frame_rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    video_codec: StableId | None = None
    audio_codecs: tuple[StableId, ...] = ()
    audio_streams: int = Field(ge=0)
    subtitle_streams: int = Field(ge=0)
    sample_rates: tuple[int, ...] = ()
    channel_counts: tuple[int, ...] = ()


class DeliveryQCReport(QCModel):
    schema_name: Literal["vistora.delivery-qc-report"] = "vistora.delivery-qc-report"
    report_id: StableId
    request_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    project_id: StableId
    project_revision: int = Field(ge=0)
    asset_id: StableId
    source_content_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    profile_id: StableId
    status: Literal["passed", "warning", "failed"]
    probe: DeliveryMediaProbe | None = None
    checks: tuple[DeliveryQCCheck, ...]
    report_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    browser_safe: Literal[True] = True

    @classmethod
    def create(cls, **values):
        shell = cls.model_construct(**values, report_digest="sha256:" + "0" * 64)
        return cls(**values, report_digest=digest_json(shell.model_dump(mode="json", exclude={"report_digest"})))

    @model_validator(mode="after")
    def exact(self):
        ids = [item.check_id for item in self.checks]
        if ids != sorted(set(ids)):
            raise ValueError("QC checks must be unique and ordered")
        statuses = {item.status for item in self.checks}
        expected = "failed" if "failed" in statuses else "warning" if "warning" in statuses else "passed"
        if self.status != expected:
            raise ValueError("QC aggregate status mismatched")
        payload = self.model_dump(mode="json", exclude={"report_digest"})
        if self.report_digest != digest_json(payload):
            raise ValueError("QC report digest mismatched")
        return self
