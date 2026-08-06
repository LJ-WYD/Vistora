"""Versioned contracts for narration-bound subtitle alignment and sync QC."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


class AlignmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Literal["1.0.0"] = "1.0.0"


class TranscriptPhrase(AlignmentModel):
    schema_name: Literal["vistora.transcript-phrase"] = "vistora.transcript-phrase"
    phrase_id: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")
    text: str = Field(min_length=1, max_length=2000)


class AlignmentWord(AlignmentModel):
    schema_name: Literal["vistora.alignment-word"] = "vistora.alignment-word"
    word_id: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")
    text: str = Field(min_length=1, max_length=256)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def forward(self):
        if self.end_seconds <= self.start_seconds + 1e-6:
            raise ValueError("Aligned word must have positive duration")
        return self


class AlignedPhrase(AlignmentModel):
    schema_name: Literal["vistora.aligned-phrase"] = "vistora.aligned-phrase"
    phrase_id: str
    text: str = Field(min_length=1, max_length=2000)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    words: tuple[AlignmentWord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact(self):
        if self.end_seconds <= self.start_seconds + 1e-6:
            raise ValueError("Aligned phrase must have positive duration")
        if self.words != tuple(sorted(self.words, key=lambda item: (item.start_seconds, item.end_seconds, item.word_id))):
            raise ValueError("Aligned words must use deterministic ordering")
        if any(word.start_seconds < self.start_seconds - 1e-6 or word.end_seconds > self.end_seconds + 1e-6 for word in self.words):
            raise ValueError("Aligned words must stay inside their phrase")
        return self


class AudioAlignTranscriptInput(AlignmentModel):
    schema_name: Literal["vistora.audio-align-transcript-input"] = "vistora.audio-align-transcript-input"
    track_id: str
    clip_id: str
    language: str = Field("zh", pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    phrases: tuple[TranscriptPhrase, ...] = Field(min_length=1, max_length=1000)
    display_lead_seconds: float = Field(0.20, ge=0, le=0.50, allow_inf_nan=False)
    minimum_confidence: float = Field(0.55, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique(self):
        ids = [item.phrase_id for item in self.phrases]
        if ids != list(dict.fromkeys(ids)):
            raise ValueError("Transcript phrase IDs must be unique and ordered")
        return self


class SubtitleAlignmentReport(AlignmentModel):
    schema_name: Literal["vistora.subtitle-alignment-report"] = "vistora.subtitle-alignment-report"
    status: Literal["success"] = "success"
    report_id: str
    provider_id: str
    provider_version: str
    track_id: str
    clip_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analyzed_clip_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    audio_duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    timeline_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    language: str
    transcript_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    display_lead_seconds: float = Field(ge=0, le=0.50, allow_inf_nan=False)
    phrases: tuple[AlignedPhrase, ...] = Field(min_length=1)
    report_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values):
        shell = cls.model_construct(**values, report_digest="sha256:" + "0" * 64)
        return cls(**values, report_digest=digest_json(shell.model_dump(mode="json", exclude={"report_digest"})))

    @model_validator(mode="after")
    def exact(self):
        phrase_ids = [item.phrase_id for item in self.phrases]
        if phrase_ids != list(dict.fromkeys(phrase_ids)):
            raise ValueError("Aligned phrase IDs must be unique and ordered")
        if self.phrases != tuple(sorted(self.phrases, key=lambda item: (item.start_seconds, item.end_seconds, item.phrase_id))):
            raise ValueError("Aligned phrases must use deterministic ordering")
        if self.phrases[-1].end_seconds > self.audio_duration_seconds + 1e-3:
            raise ValueError("Alignment exceeds the analyzed audio duration")
        payload = self.model_dump(mode="json", exclude={"report_digest"})
        if self.report_digest != digest_json(payload):
            raise ValueError("Subtitle alignment report digest mismatched")
        return self


class SubtitleBuildFromAlignmentInput(AlignmentModel):
    schema_name: Literal["vistora.subtitle-build-from-alignment-input"] = "vistora.subtitle-build-from-alignment-input"
    report: SubtitleAlignmentReport
    track_id: str
    cue_id_prefix: str = Field("aligned", min_length=3, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")
    replace_existing: Literal[True] = True
    create_track: bool = False
    language: str = Field("zh", pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


class SubtitleAlignmentBuildResult(AlignmentModel):
    schema_name: Literal["vistora.subtitle-alignment-build-result"] = "vistora.subtitle-alignment-build-result"
    status: Literal["success"] = "success"
    operation: Literal["build_from_alignment"] = "build_from_alignment"
    track_id: str
    report_id: str
    report_digest: str
    source_sha256: str
    analyzed_clip_digest: str
    created_cue_ids: tuple[str, ...]
    deleted_cue_ids: tuple[str, ...]
    before_snapshot_id: str
    after_snapshot_id: str
    project_id: str
    revision: int
    timeline_digest: str


class SubtitleSyncQCInput(AlignmentModel):
    schema_name: Literal["vistora.subtitle-sync-qc-input"] = "vistora.subtitle-sync-qc-input"
    report: SubtitleAlignmentReport
    track_id: str
    cue_id_prefix: str = Field("aligned", min_length=3, max_length=100, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$")
    maximum_timeline_error_seconds: float = Field(0.03, gt=0, le=0.25, allow_inf_nan=False)
    rendered_media_path: str | None = Field(default=None, min_length=1)
    expected_rendered_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    maximum_audio_mux_offset_seconds: float = Field(0.02, gt=0, le=0.25, allow_inf_nan=False)


class SubtitleSyncQCResult(AlignmentModel):
    schema_name: Literal["vistora.subtitle-sync-qc-result"] = "vistora.subtitle-sync-qc-result"
    status: Literal["passed", "failed"]
    sync_qc_id: str
    report_id: str
    report_digest: str
    track_id: str
    source_sha256: str
    analyzed_clip_digest: str
    timeline_status: Literal["passed", "failed"]
    maximum_timeline_error_seconds: float = Field(ge=0, allow_inf_nan=False)
    missing_cue_ids: tuple[str, ...] = ()
    extra_cue_ids: tuple[str, ...] = ()
    mismatched_cue_ids: tuple[str, ...] = ()
    rendered_content_sha256: str | None = None
    audio_mux_offset_seconds: float | None = Field(default=None, allow_inf_nan=False)
    audio_correlation: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    checks: tuple[str, ...]
    result_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @classmethod
    def create(cls, **values):
        shell = cls.model_construct(**values, result_digest="sha256:" + "0" * 64)
        return cls(**values, result_digest=digest_json(shell.model_dump(mode="json", exclude={"result_digest"})))

    @model_validator(mode="after")
    def exact(self):
        payload = self.model_dump(mode="json", exclude={"result_digest"})
        if self.result_digest != digest_json(payload):
            raise ValueError("Subtitle sync QC digest mismatched")
        return self
