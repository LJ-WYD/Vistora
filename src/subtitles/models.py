"""Strict versioned contracts for subtitle editing and ripple policy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.timeline import SubtitleCue, SubtitleStyle


StableIdPattern = r"^[A-Za-z][A-Za-z0-9._:-]*$"


class SubtitleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Literal["1.0.0"] = "1.0.0"


class SubtitleRipplePolicy(SubtitleModel):
    schema_name: Literal["vistora.subtitle-ripple-policy"] = (
        "vistora.subtitle-ripple-policy"
    )
    mode: Literal["none", "selected_subtitle_tracks", "all_unlocked"] = "none"
    selected_track_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def exact_selection(self) -> "SubtitleRipplePolicy":
        if self.mode == "selected_subtitle_tracks" and not self.selected_track_ids:
            raise ValueError("Selected subtitle ripple requires track IDs")
        if self.mode != "selected_subtitle_tracks" and self.selected_track_ids:
            raise ValueError("Only selected subtitle ripple accepts track IDs")
        if len(self.selected_track_ids) != len(set(self.selected_track_ids)):
            raise ValueError("Subtitle ripple track IDs must be unique")
        if self.selected_track_ids != tuple(sorted(self.selected_track_ids)):
            raise ValueError("Subtitle ripple track IDs must use stable ordering")
        return self


class SubtitleManageTrackInput(SubtitleModel):
    schema_name: Literal["vistora.subtitle-manage-track-input"] = (
        "vistora.subtitle-manage-track-input"
    )
    action: Literal["create", "update", "delete"]
    track_id: str = Field(min_length=3, max_length=160, pattern=StableIdPattern)
    kind: Literal["subtitle", "text"] | None = None
    role: str | None = Field(default=None, min_length=1, max_length=80)
    language: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$",
    )
    order: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    locked: bool | None = None
    allow_overlaps: bool | None = None
    style: SubtitleStyle | None = None

    @model_validator(mode="after")
    def action_fields(self) -> "SubtitleManageTrackInput":
        supplied = (
            self.kind,
            self.role,
            self.language,
            self.order,
            self.enabled,
            self.locked,
            self.allow_overlaps,
            self.style,
        )
        if self.action == "create" and self.kind is None:
            raise ValueError("Subtitle track creation requires kind")
        if self.action == "update" and all(value is None for value in supplied):
            raise ValueError("Subtitle track update requires a property")
        if self.action == "delete" and any(value is not None for value in supplied):
            raise ValueError("Subtitle track deletion accepts only track_id")
        return self


class SubtitleEditCueInput(SubtitleModel):
    schema_name: Literal["vistora.subtitle-edit-cue-input"] = (
        "vistora.subtitle-edit-cue-input"
    )
    action: Literal[
        "add",
        "batch_add",
        "update",
        "split",
        "merge",
        "move",
        "trim",
        "ripple_shift",
        "delete",
        "set_style",
    ]
    track_id: str = Field(min_length=3, max_length=160, pattern=StableIdPattern)
    cue_id: str | None = Field(default=None, min_length=3, max_length=160, pattern=StableIdPattern)
    cues: tuple[SubtitleCue, ...] = ()
    text: str | None = Field(default=None, min_length=1, max_length=4096)
    language: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    speaker: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    split_at_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    right_cue_id: str | None = Field(default=None, min_length=3, max_length=160, pattern=StableIdPattern)
    merge_cue_ids: tuple[str, ...] = ()
    merged_cue_id: str | None = Field(default=None, min_length=3, max_length=160, pattern=StableIdPattern)
    timeline_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    anchor_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    delta_seconds: float | None = Field(default=None, allow_inf_nan=False)
    style: SubtitleStyle | None = None

    @model_validator(mode="after")
    def action_requirements(self) -> "SubtitleEditCueInput":
        if self.action == "add" and len(self.cues) != 1:
            raise ValueError("Subtitle add requires exactly one cue")
        if self.action == "batch_add" and not self.cues:
            raise ValueError("Subtitle batch_add requires cues")
        if self.action in {"update", "move", "trim", "delete", "set_style", "split"} and self.cue_id is None:
            raise ValueError(f"Subtitle {self.action} requires cue_id")
        if self.action == "split" and (self.split_at_seconds is None or self.right_cue_id is None):
            raise ValueError("Subtitle split requires split_at_seconds and right_cue_id")
        if self.action == "merge" and len(self.merge_cue_ids) < 2:
            raise ValueError("Subtitle merge requires at least two cue IDs")
        if self.action == "move" and self.timeline_start_seconds is None:
            raise ValueError("Subtitle move requires timeline_start_seconds")
        if self.action == "trim" and (self.start_seconds is None or self.end_seconds is None):
            raise ValueError("Subtitle trim requires start_seconds and end_seconds")
        if self.action == "ripple_shift" and (self.anchor_seconds is None or self.delta_seconds is None or abs(self.delta_seconds) <= 1e-9):
            raise ValueError("Subtitle ripple_shift requires anchor and non-zero delta")
        if self.action == "set_style" and self.style is None:
            raise ValueError("Subtitle set_style requires style")
        if self.action == "update" and all(
            value is None
            for value in (self.text, self.language, self.speaker, self.enabled, self.start_seconds, self.end_seconds, self.style)
        ):
            raise ValueError("Subtitle update requires a changed field")
        return self


class SubtitleImportInput(SubtitleModel):
    schema_name: Literal["vistora.subtitle-import-input"] = "vistora.subtitle-import-input"
    track_id: str = Field(min_length=3, max_length=160, pattern=StableIdPattern)
    format: Literal["auto", "srt", "vtt"] = "auto"
    input_path: str | None = Field(default=None, min_length=1, max_length=1024)
    content: str | None = Field(default=None, min_length=1, max_length=2_000_000)
    replace_existing: bool = False
    create_track: bool = False
    language: str = Field("und", pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")

    @model_validator(mode="after")
    def one_source(self) -> "SubtitleImportInput":
        if (self.input_path is None) == (self.content is None):
            raise ValueError("Subtitle import requires exactly one path or content source")
        return self


class SubtitleExportInput(SubtitleModel):
    schema_name: Literal["vistora.subtitle-export-input"] = "vistora.subtitle-export-input"
    output_path: str = Field(min_length=1, max_length=1024)
    format: Literal["srt", "vtt"]
    track_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def stable_tracks(self) -> "SubtitleExportInput":
        if len(self.track_ids) != len(set(self.track_ids)):
            raise ValueError("Subtitle export track IDs must be unique")
        if self.track_ids != tuple(sorted(self.track_ids)):
            raise ValueError("Subtitle export track IDs must use stable ordering")
        return self


class SubtitleEditOutcome(SubtitleModel):
    schema_name: Literal["vistora.subtitle-edit-outcome"] = "vistora.subtitle-edit-outcome"
    status: Literal["success"] = "success"
    operation: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    direct_cue_ids: tuple[str, ...] = ()
    consequential_cue_ids: tuple[str, ...] = ()
    created_cue_ids: tuple[str, ...] = ()
    modified_cue_ids: tuple[str, ...] = ()
    deleted_cue_ids: tuple[str, ...] = ()
    created_track_ids: tuple[str, ...] = ()
    modified_track_ids: tuple[str, ...] = ()
    deleted_track_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
