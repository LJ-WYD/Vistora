"""Strict original O16 inputs for masks and bounded clip compositing."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from core.timeline import ClipCompositeSettings, ClipMask
from timeline_edit.models import (
    ClipReference,
    StableClipId,
    TimelineEditModel,
    TrackTargetModel,
)


class SetClipMaskInput(TrackTargetModel):
    clip_id: StableClipId
    action: Literal["upsert", "remove"]
    mask: ClipMask | None = None
    mask_id: StableClipId | None = None

    @model_validator(mode="after")
    def exact_action(self) -> "SetClipMaskInput":
        if self.action == "upsert" and (self.mask is None or self.mask_id is not None):
            raise ValueError("Mask upsert requires one exact mask payload")
        if self.action == "remove" and (self.mask_id is None or self.mask is not None):
            raise ValueError("Mask removal requires one exact mask ID")
        return self


class ReplaceClipMasksInput(TrackTargetModel):
    clip_id: StableClipId
    masks: tuple[ClipMask, ...] = Field(max_length=16)


class CopyClipMasksInput(TimelineEditModel):
    source_track_id: str = Field(min_length=3, max_length=160)
    source_clip_id: StableClipId
    targets: tuple[ClipReference, ...] = Field(min_length=1, max_length=32)
    mask_ids: tuple[StableClipId, ...] = ()
    replace_existing: bool = False

    @model_validator(mode="after")
    def stable_explicit_targets(self) -> "CopyClipMasksInput":
        identities = tuple((item.track_id, item.clip_id) for item in self.targets)
        if len(identities) != len(set(identities)) or identities != tuple(sorted(identities)):
            raise ValueError("Mask copy targets must be stable and unique")
        if (self.source_track_id, self.source_clip_id) in identities:
            raise ValueError("Mask copy source cannot also be a target")
        if len(self.mask_ids) != len(set(self.mask_ids)) or self.mask_ids != tuple(sorted(self.mask_ids)):
            raise ValueError("Mask selectors must be stable and unique")
        return self


class SetClipCompositeInput(TrackTargetModel):
    clip_id: StableClipId
    action: Literal["set", "reset"] = "set"
    composite: ClipCompositeSettings | None = None

    @model_validator(mode="after")
    def exact_action(self) -> "SetClipCompositeInput":
        if self.action == "set" and self.composite is None:
            raise ValueError("Composite set requires exact settings")
        if self.action == "reset" and self.composite is not None:
            raise ValueError("Composite reset accepts no settings")
        return self
