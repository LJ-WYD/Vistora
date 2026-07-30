"""Versioned inputs and deterministic outcomes for core timeline edits."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TrackKey = Literal["video", "audio"]
StableClipId = Annotated[
    str,
    Field(min_length=3, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]


class TimelineEditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"


class SplitClipInput(TimelineEditModel):
    track_key: TrackKey
    clip_id: StableClipId
    split_at_seconds: float = Field(gt=0, allow_inf_nan=False)
    right_clip_id: StableClipId | None = None


class TrimClipInput(TimelineEditModel):
    track_key: TrackKey
    clip_id: StableClipId
    trim_in: float = Field(ge=0, allow_inf_nan=False)
    trim_out: float = Field(gt=0, allow_inf_nan=False)
    ripple: bool = False

    @model_validator(mode="after")
    def forward_range(self) -> TrimClipInput:
        if self.trim_out <= self.trim_in:
            raise ValueError("trim_out must be greater than trim_in")
        return self


class MoveClipInput(TimelineEditModel):
    track_key: TrackKey
    clip_id: StableClipId
    timeline_start: float = Field(ge=0, allow_inf_nan=False)
    ripple: bool = False


class RemoveClipInput(TimelineEditModel):
    track_key: TrackKey
    clip_id: StableClipId
    mode: Literal["lift", "ripple"] = "lift"


class InsertOverwriteClipInput(TimelineEditModel):
    track_key: TrackKey
    source_path: str = Field(min_length=1)
    timeline_start: float = Field(ge=0, allow_inf_nan=False)
    mode: Literal["insert", "overwrite"]
    clip_id: StableClipId | None = None
    trim_in: float = Field(default=0, ge=0, allow_inf_nan=False)
    trim_out: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    speed_factor: float = Field(default=1, gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=1, ge=0, allow_inf_nan=False)
    keep_audio: bool = True
    rotate: Literal[0, 90, 180, 270] = 0


class SetClipPropertiesInput(TimelineEditModel):
    track_key: TrackKey
    clip_id: StableClipId
    speed_factor: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    keep_audio: bool | None = None
    mute: bool | None = None
    rotate: Literal[0, 90, 180, 270] | None = None

    @model_validator(mode="after")
    def has_change(self) -> SetClipPropertiesInput:
        if all(
            value is None
            for value in (
                self.speed_factor,
                self.volume,
                self.keep_audio,
                self.mute,
                self.rotate,
            )
        ):
            raise ValueError("At least one playback property is required")
        return self


class TimelineEditOutcome(TimelineEditModel):
    operation: Literal[
        "split",
        "trim",
        "move",
        "remove",
        "insert",
        "overwrite",
        "set_properties",
    ]
    track_key: TrackKey
    direct_clip_ids: tuple[str, ...]
    consequential_clip_ids: tuple[str, ...] = ()
    created_clip_ids: tuple[str, ...] = ()
    modified_clip_ids: tuple[str, ...] = ()
    deleted_clip_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
