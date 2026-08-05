"""Confirmed atomic original O16 mask and bounded compositing mutations."""

from __future__ import annotations

from typing import Any

from core.timeline import ClipCompositeSettings
from masks import (
    CopyClipMasksInput,
    ReplaceClipMasksInput,
    SetClipCompositeInput,
    SetClipMaskInput,
)
from timeline_edit import TimelineEditTransaction

from .base import BaseSkill


class VideoSetClipMaskSkill(BaseSkill):
    name = "VideoSetClipMaskSkill"
    description = "Upsert or remove one exact validated mask on one video clip."
    input_model = SetClipMaskInput

    def run(self, params: SetClipMaskInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_mask(
                params.track_reference,
                params.clip_id,
                mask=params.mask,
                mask_id=params.mask_id,
            )
        )


class VideoReplaceClipMasksSkill(BaseSkill):
    name = "VideoReplaceClipMasksSkill"
    description = "Atomically replace the complete ordered mask set of one clip."
    input_model = ReplaceClipMasksInput

    def run(self, params: ReplaceClipMasksInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.replace_clip_masks(
                params.track_reference, params.clip_id, params.masks
            )
        )


class VideoCopyClipMasksSkill(BaseSkill):
    name = "VideoCopyClipMasksSkill"
    description = "Copy selected masks to explicit video clip IDs only."
    input_model = CopyClipMasksInput

    def run(self, params: CopyClipMasksInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.copy_clip_masks(
                params.source_track_id,
                params.source_clip_id,
                ((item.track_id, item.clip_id) for item in params.targets),
                mask_ids=params.mask_ids,
                replace_existing=params.replace_existing,
            )
        )


class VideoSetClipCompositeSkill(BaseSkill):
    name = "VideoSetClipCompositeSkill"
    description = "Set or reset one clip's bounded blend-mode declaration."
    input_model = SetClipCompositeInput

    def run(self, params: SetClipCompositeInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_composite(
                params.track_reference,
                params.clip_id,
                params.composite or ClipCompositeSettings(),
            )
        )
