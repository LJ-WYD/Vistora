"""Versioned inputs and deterministic outcomes for core timeline edits."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.timeline import AppliedLoudnessNormalization, TimelineTransition


EditScope = Literal["current_clip", "linked_group"]
StableTrackId = Annotated[
    str,
    Field(min_length=3, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
StableClipId = Annotated[
    str,
    Field(min_length=3, max_length=160, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]


class TimelineEditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0", "2.0.0"] = "2.0.0"


class TimelineSubtitleRipplePolicy(TimelineEditModel):
    schema_name: Literal["vistora.timeline-subtitle-ripple-policy"] = (
        "vistora.timeline-subtitle-ripple-policy"
    )
    mode: Literal["none", "selected_subtitle_tracks", "all_unlocked"] = "none"
    selected_track_ids: tuple[StableTrackId, ...] = ()

    @model_validator(mode="after")
    def exact_selection(self) -> "TimelineSubtitleRipplePolicy":
        if self.mode == "selected_subtitle_tracks" and not self.selected_track_ids:
            raise ValueError("Selected subtitle ripple requires track IDs")
        if self.mode != "selected_subtitle_tracks" and self.selected_track_ids:
            raise ValueError("Only selected subtitle ripple accepts track IDs")
        if len(self.selected_track_ids) != len(set(self.selected_track_ids)):
            raise ValueError("Subtitle ripple track IDs must be unique")
        if self.selected_track_ids != tuple(sorted(self.selected_track_ids)):
            raise ValueError("Subtitle ripple track IDs must use stable ordering")
        return self


class TrackTargetModel(TimelineEditModel):
    """New callers use track_id; track_key remains a legacy compatibility key."""

    track_id: StableTrackId | None = None
    track_key: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_track_reference(self) -> "TrackTargetModel":
        if self.track_id is None and self.track_key is None:
            raise ValueError("track_id is required (track_key is legacy)")
        return self

    @property
    def track_reference(self) -> str:
        return self.track_id or self.track_key or ""


class SplitClipInput(TrackTargetModel):
    clip_id: StableClipId
    split_at_seconds: float = Field(gt=0, allow_inf_nan=False)
    right_clip_id: StableClipId | None = None
    edit_scope: EditScope = "current_clip"


class TrimClipInput(TrackTargetModel):
    clip_id: StableClipId
    trim_in: float = Field(ge=0, allow_inf_nan=False)
    trim_out: float = Field(gt=0, allow_inf_nan=False)
    ripple: bool = False
    edit_scope: EditScope = "current_clip"
    subtitle_ripple: TimelineSubtitleRipplePolicy = Field(
        default_factory=TimelineSubtitleRipplePolicy
    )

    @model_validator(mode="after")
    def forward_range(self) -> TrimClipInput:
        if self.trim_out <= self.trim_in:
            raise ValueError("trim_out must be greater than trim_in")
        return self


class MoveClipInput(TrackTargetModel):
    clip_id: StableClipId
    timeline_start: float = Field(ge=0, allow_inf_nan=False)
    ripple: bool = False
    edit_scope: EditScope = "current_clip"
    subtitle_ripple: TimelineSubtitleRipplePolicy = Field(
        default_factory=TimelineSubtitleRipplePolicy
    )


class RemoveClipInput(TrackTargetModel):
    clip_id: StableClipId
    mode: Literal["lift", "ripple"] = "lift"
    edit_scope: EditScope = "current_clip"
    subtitle_ripple: TimelineSubtitleRipplePolicy = Field(
        default_factory=TimelineSubtitleRipplePolicy
    )


class InsertOverwriteClipInput(TrackTargetModel):
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
    link_group_id: StableClipId | None = None
    edit_scope: EditScope = "current_clip"
    subtitle_ripple: TimelineSubtitleRipplePolicy = Field(
        default_factory=TimelineSubtitleRipplePolicy
    )

    @model_validator(mode="after")
    def inserted_link_scope(self) -> "InsertOverwriteClipInput":
        if self.edit_scope == "linked_group" and self.link_group_id is None:
            raise ValueError(
                "linked_group insertion requires an explicit link_group_id"
            )
        return self


class SetClipPropertiesInput(TrackTargetModel):
    clip_id: StableClipId
    speed_factor: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    volume: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    keep_audio: bool | None = None
    mute: bool | None = None
    rotate: Literal[0, 90, 180, 270] | None = None
    edit_scope: EditScope = "current_clip"

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


class SetClipAudioPropertiesInput(TrackTargetModel):
    """Exact clip-local audio controls; never expands to linked members."""

    clip_id: StableClipId
    gain_db: float | None = Field(
        default=None, ge=-60, le=24, allow_inf_nan=False
    )
    muted: bool | None = None
    pan: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    fade_in_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    fade_out_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    playback_rate: float | None = Field(
        default=None, gt=0, le=16, allow_inf_nan=False
    )
    normalization_evidence: AppliedLoudnessNormalization | None = None

    @model_validator(mode="after")
    def has_audio_change(self) -> "SetClipAudioPropertiesInput":
        if all(
            value is None
            for value in (
                self.gain_db,
                self.muted,
                self.pan,
                self.fade_in_seconds,
                self.fade_out_seconds,
                self.playback_rate,
                self.normalization_evidence,
            )
        ):
            raise ValueError("At least one audio property is required")
        return self


class SetTrackMixPropertiesInput(TimelineEditModel):
    track_id: StableTrackId
    gain_db: float | None = Field(
        default=None, ge=-60, le=24, allow_inf_nan=False
    )
    muted: bool | None = None
    pan: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def has_mix_change(self) -> "SetTrackMixPropertiesInput":
        if self.gain_db is None and self.muted is None and self.pan is None:
            raise ValueError("At least one track mix property is required")
        return self


class SetVolumeEnvelopeInput(TrackTargetModel):
    clip_id: StableClipId
    action: Literal["upsert", "delete", "clear"]
    point_id: StableClipId | None = None
    offset_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    gain_db: float | None = Field(
        default=None, ge=-60, le=24, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def envelope_action_fields(self) -> "SetVolumeEnvelopeInput":
        if self.action == "upsert" and (
            self.point_id is None
            or self.offset_seconds is None
            or self.gain_db is None
        ):
            raise ValueError("upsert requires point_id, offset_seconds, and gain_db")
        if self.action == "delete" and self.point_id is None:
            raise ValueError("delete requires point_id")
        if self.action == "clear" and any(
            value is not None
            for value in (self.point_id, self.offset_seconds, self.gain_db)
        ):
            raise ValueError("clear does not accept point fields")
        return self


class ClipReference(TimelineEditModel):
    track_id: StableTrackId
    clip_id: StableClipId


class ManageTrackInput(TimelineEditModel):
    action: Literal["add", "update", "remove", "reorder"]
    track_id: StableTrackId
    kind: Literal["video", "audio"] | None = None
    role: str | None = Field(default=None, min_length=1, max_length=80)
    order: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    muted: bool | None = None
    locked: bool | None = None

    @model_validator(mode="after")
    def action_fields(self) -> "ManageTrackInput":
        if self.action == "add" and (
            self.kind is None or self.order is None
        ):
            raise ValueError("add requires kind and order")
        if self.action == "reorder" and self.order is None:
            raise ValueError("reorder requires order")
        if self.action == "update" and all(
            value is None
            for value in (
                self.role,
                self.enabled,
                self.muted,
                self.locked,
            )
        ):
            raise ValueError("update requires a track property")
        return self


class SetClipLinkInput(TimelineEditModel):
    action: Literal["link", "unlink"]
    members: tuple[ClipReference, ...] = Field(min_length=1)
    link_group_id: StableClipId | None = None

    @model_validator(mode="after")
    def link_requirements(self) -> "SetClipLinkInput":
        identities = {
            (member.track_id, member.clip_id) for member in self.members
        }
        if len(identities) != len(self.members):
            raise ValueError("linked members must be unique")
        if self.action == "link":
            if len(self.members) < 2 or self.link_group_id is None:
                raise ValueError(
                    "link requires two or more members and link_group_id"
                )
        elif self.link_group_id is not None:
            raise ValueError("unlink does not accept link_group_id")
        return self


class AddTransitionInput(TimelineEditModel):
    """Add one exact transition and, optionally, its explicit audio pair."""

    transition: TimelineTransition
    paired_transition: TimelineTransition | None = None

    @model_validator(mode="after")
    def exact_pair(self) -> "AddTransitionInput":
        expected = self.transition.paired_transition_id
        if expected is None and self.paired_transition is not None:
            raise ValueError("Unpaired transition cannot include a pair")
        if expected is not None:
            if self.paired_transition is None:
                raise ValueError("Paired transition payload is required")
            if self.paired_transition.transition_id != expected:
                raise ValueError("Paired transition ID does not match")
            if (
                self.paired_transition.paired_transition_id
                != self.transition.transition_id
            ):
                raise ValueError("Transition pairing must be reciprocal")
        return self


class UpdateTransitionInput(AddTransitionInput):
    """Replace one transition using the same stable identity."""


class RemoveTransitionInput(TimelineEditModel):
    transition_id: StableClipId
    include_paired: bool = True


class TransitionCopyTarget(TimelineEditModel):
    transition_id: StableClipId
    track_id: StableTrackId
    from_clip_id: StableClipId
    to_clip_id: StableClipId
    paired_transition_id: StableClipId | None = None
    paired_track_id: StableTrackId | None = None
    paired_from_clip_id: StableClipId | None = None
    paired_to_clip_id: StableClipId | None = None

    @model_validator(mode="after")
    def complete_pair(self) -> "TransitionCopyTarget":
        values = (
            self.paired_transition_id,
            self.paired_track_id,
            self.paired_from_clip_id,
            self.paired_to_clip_id,
        )
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("Copied audio pair references must be complete")
        return self


class CopyTransitionInput(TimelineEditModel):
    source_transition_id: StableClipId
    targets: tuple[TransitionCopyTarget, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def stable_unique_targets(self) -> "CopyTransitionInput":
        identities = tuple(target.transition_id for target in self.targets)
        if len(identities) != len(set(identities)):
            raise ValueError("Copied transition IDs must be unique")
        if identities != tuple(sorted(identities)):
            raise ValueError("Copy targets must use stable transition-ID order")
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
        "manage_track",
        "set_clip_link",
        "set_clip_audio",
        "set_track_mix",
        "set_volume_envelope",
        "set_clip_transform",
        "set_clip_color",
        "copy_clip_visual",
        "add_transition",
        "update_transition",
        "remove_transition",
        "copy_transition",
        "upsert_visual_keyframe",
        "delete_visual_keyframe",
        "replace_visual_automation",
        "clear_visual_automation",
        "copy_visual_automation",
    ]
    track_id: StableTrackId
    track_key: str
    direct_clip_ids: tuple[str, ...]
    consequential_clip_ids: tuple[str, ...] = ()
    created_clip_ids: tuple[str, ...] = ()
    modified_clip_ids: tuple[str, ...] = ()
    deleted_clip_ids: tuple[str, ...] = ()
    consequential_subtitle_cue_ids: tuple[str, ...] = ()
    created_transition_ids: tuple[str, ...] = ()
    modified_transition_ids: tuple[str, ...] = ()
    deleted_transition_ids: tuple[str, ...] = ()
    created_automation_ids: tuple[str, ...] = ()
    modified_automation_ids: tuple[str, ...] = ()
    deleted_automation_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
