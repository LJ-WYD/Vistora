"""Confirmed atomic STEP 21 visual-property mutation skills."""

from __future__ import annotations

from typing import Any

from core.timeline import ClipColorAdjustment, ClipTransform
from timeline_edit import TimelineEditTransaction
from visuals import CopyClipVisualInput, SetClipColorInput, SetClipTransformInput

from .base import BaseSkill


class VideoSetClipTransformSkill(BaseSkill):
    name = "VideoSetClipTransformSkill"
    description = (
        "Set or reset one exact video clip's bounded canvas-relative transform; "
        "linked audio and other clips are never changed implicitly."
    )
    input_model = SetClipTransformInput

    def run(self, params: SetClipTransformInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_transform(
                params.track_reference,
                params.clip_id,
                transform=params.transform or ClipTransform(),
            )
        )


class VideoSetClipColorSkill(BaseSkill):
    name = "VideoSetClipColorSkill"
    description = (
        "Set or reset one exact video clip's bounded deterministic SDR color "
        "adjustment without accepting raw filter expressions."
    )
    input_model = SetClipColorInput

    def run(self, params: SetClipColorInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_color(
                params.track_reference,
                params.clip_id,
                color=params.color or ClipColorAdjustment(),
            )
        )


class VideoCopyClipVisualSkill(BaseSkill):
    name = "VideoCopyClipVisualSkill"
    description = (
        "Copy transform, color, or both from one exact video clip to a stable "
        "explicit target list as one atomic project-state transaction."
    )
    input_model = CopyClipVisualInput

    def run(self, params: CopyClipVisualInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.copy_clip_visual(
                params.source_track_id,
                params.source_clip_id,
                (
                    (target.track_id, target.clip_id)
                    for target in params.targets
                ),
                components=params.components,
            )
        )
