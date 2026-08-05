"""Strict contracts for first-class image and sticker timeline clips."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.timeline import ClipTransform


class InsertGraphicInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_name: Literal["vistora.insert-graphic-input"] = (
        "vistora.insert-graphic-input"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    track_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    track_key: str | None = Field(default=None, min_length=1, max_length=160)
    clip_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    source_path: str = Field(min_length=1, max_length=4096)
    graphic_kind: Literal["image", "sticker"]
    timeline_start: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, le=3600, allow_inf_nan=False)
    mode: Literal["insert", "overwrite"] = "insert"
    transform: ClipTransform = Field(default_factory=ClipTransform)

    @model_validator(mode="after")
    def exact_track_reference(self) -> "InsertGraphicInput":
        if (self.track_id is None) == (self.track_key is None):
            raise ValueError("Graphic insertion requires exactly one track ID or key")
        return self

    @property
    def track_reference(self) -> str:
        return self.track_id or self.track_key or ""
