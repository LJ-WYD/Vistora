"""Strict STEP 23 visual-automation inputs and deterministic identities."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from core.timeline import VisualAutomation, VisualKeyframe, VisualPropertyPath
from timeline_edit.models import (
    ClipReference,
    StableClipId,
    StableTrackId,
    TimelineEditModel,
    TrackTargetModel,
)


class UpsertVisualKeyframeInput(TrackTargetModel):
    clip_id: StableClipId
    automation_id: StableClipId
    property_path: VisualPropertyPath
    keyframe: VisualKeyframe


class DeleteVisualKeyframeInput(TrackTargetModel):
    clip_id: StableClipId
    automation_id: StableClipId
    keyframe_id: StableClipId


class ReplaceVisualAutomationInput(TrackTargetModel):
    clip_id: StableClipId
    automation: VisualAutomation

    @model_validator(mode="after")
    def exact_target(self) -> "ReplaceVisualAutomationInput":
        if self.automation.clip_id != self.clip_id:
            raise ValueError("Replacement automation must target clip_id")
        return self


class ClearVisualAutomationInput(TrackTargetModel):
    clip_id: StableClipId
    automation_id: StableClipId | None = None
    property_path: VisualPropertyPath | None = None
    scope: Literal["curve", "all"] = "curve"

    @model_validator(mode="after")
    def exact_scope(self) -> "ClearVisualAutomationInput":
        if self.scope == "all":
            if self.automation_id is not None or self.property_path is not None:
                raise ValueError("Clear-all accepts no curve selector")
        elif (self.automation_id is None) == (self.property_path is None):
            raise ValueError(
                "Curve clear requires exactly one automation_id or property_path"
            )
        return self


class CopyVisualAutomationInput(TimelineEditModel):
    source_track_id: StableTrackId
    source_clip_id: StableClipId
    targets: tuple[ClipReference, ...] = Field(min_length=1, max_length=32)
    property_paths: tuple[VisualPropertyPath, ...] = ()

    @model_validator(mode="after")
    def stable_explicit_targets(self) -> "CopyVisualAutomationInput":
        identities = tuple((item.track_id, item.clip_id) for item in self.targets)
        if len(identities) != len(set(identities)):
            raise ValueError("Automation copy targets must be unique")
        if identities != tuple(sorted(identities)):
            raise ValueError("Automation copy targets must use stable ordering")
        if (self.source_track_id, self.source_clip_id) in identities:
            raise ValueError("Automation copy source cannot be a target")
        if len(self.property_paths) != len(set(self.property_paths)):
            raise ValueError("Automation property selectors must be unique")
        if self.property_paths != tuple(sorted(self.property_paths)):
            raise ValueError("Automation property selectors must be sorted")
        return self


def automation_digest(automations: tuple[VisualAutomation, ...]) -> str:
    payload = [item.model_dump(mode="json") for item in automations]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
