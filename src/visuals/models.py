"""Strict STEP 21 visual-edit inputs and preview identity contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from core.timeline import ClipColorAdjustment, ClipTransform
from timeline_edit.models import ClipReference, StableClipId, StableTrackId, TimelineEditModel, TrackTargetModel


class SetClipTransformInput(TrackTargetModel):
    clip_id: StableClipId
    action: Literal["set", "reset"] = "set"
    transform: ClipTransform | None = None

    @model_validator(mode="after")
    def action_payload(self) -> "SetClipTransformInput":
        if self.action == "set" and self.transform is None:
            raise ValueError("Transform set requires exact transform values")
        if self.action == "reset" and self.transform is not None:
            raise ValueError("Transform reset accepts no transform values")
        return self


class SetClipColorInput(TrackTargetModel):
    clip_id: StableClipId
    action: Literal["set", "reset"] = "set"
    color: ClipColorAdjustment | None = None

    @model_validator(mode="after")
    def action_payload(self) -> "SetClipColorInput":
        if self.action == "set" and self.color is None:
            raise ValueError("Color set requires exact adjustment values")
        if self.action == "reset" and self.color is not None:
            raise ValueError("Color reset accepts no adjustment values")
        return self


class CopyClipVisualInput(TimelineEditModel):
    source_track_id: StableTrackId
    source_clip_id: StableClipId
    targets: tuple[ClipReference, ...] = Field(min_length=1, max_length=32)
    components: Literal["transform", "color", "both"] = "both"

    @model_validator(mode="after")
    def explicit_stable_targets(self) -> "CopyClipVisualInput":
        identities = tuple((item.track_id, item.clip_id) for item in self.targets)
        if len(identities) != len(set(identities)):
            raise ValueError("Visual copy target clips must be unique")
        if identities != tuple(sorted(identities)):
            raise ValueError("Visual copy targets must use stable ordering")
        if (self.source_track_id, self.source_clip_id) in identities:
            raise ValueError("Visual copy source cannot also be a target")
        return self


class VisualPreviewReference(TimelineEditModel):
    schema_name: Literal["vistora.visual-preview-reference"] = (
        "vistora.visual-preview-reference"
    )
    mode: Literal["original", "applied"] = "original"
    clip_id: StableClipId
    source_id: str = Field(min_length=3, max_length=160)
    visual_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def visual_digest(
    transform: ClipTransform,
    color: ClipColorAdjustment,
) -> str:
    payload = {
        "transform": transform.model_dump(mode="json"),
        "color": color.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
