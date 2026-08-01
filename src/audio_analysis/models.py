"""Frozen, browser-safe contracts for deterministic clip loudness analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from timeline_edit.models import StableClipId, StableTrackId


class LoudnessAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.loudness-analysis-request"] = (
        "vistora.loudness-analysis-request"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    track_id: StableTrackId
    clip_id: StableClipId
    target_lufs: float = Field(-16, ge=-36, le=-5, allow_inf_nan=False)
    max_true_peak_dbfs: float = Field(-1, ge=-9, le=0, allow_inf_nan=False)


class LoudnessAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.loudness-analysis-result"] = (
        "vistora.loudness-analysis-result"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["success"] = "success"
    analysis_id: str = Field(min_length=3, max_length=160)
    track_id: StableTrackId
    clip_id: StableClipId
    analyzed_clip_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    integrated_lufs: float = Field(ge=-120, le=20, allow_inf_nan=False)
    true_peak_dbfs: float = Field(ge=-120, le=20, allow_inf_nan=False)
    target_lufs: float = Field(ge=-36, le=-5, allow_inf_nan=False)
    max_true_peak_dbfs: float = Field(ge=-9, le=0, allow_inf_nan=False)
    recommended_gain_db: float = Field(ge=-60, le=24, allow_inf_nan=False)
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    cached: bool = False
