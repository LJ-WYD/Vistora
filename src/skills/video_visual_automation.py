"""Confirmed atomic STEP 23 visual keyframe mutation skills."""

from __future__ import annotations

from typing import Any

from timeline_edit import TimelineEditTransaction
from visual_automation.models import (
    ClearVisualAutomationInput,
    CopyVisualAutomationInput,
    DeleteVisualKeyframeInput,
    ReplaceVisualAutomationInput,
    UpsertVisualKeyframeInput,
)

from .base import BaseSkill


class VideoUpsertVisualKeyframeSkill(BaseSkill):
    name = "VideoUpsertVisualKeyframeSkill"
    description = "Create or update one exact seek-safe visual keyframe."
    input_model = UpsertVisualKeyframeInput

    def run(self, params: UpsertVisualKeyframeInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.upsert_visual_keyframe(
                params.track_reference,
                params.clip_id,
                automation_id=params.automation_id,
                property_path=params.property_path,
                keyframe=params.keyframe,
            )
        )


class VideoDeleteVisualKeyframeSkill(BaseSkill):
    name = "VideoDeleteVisualKeyframeSkill"
    description = "Delete one exact visual keyframe and empty curve if needed."
    input_model = DeleteVisualKeyframeInput

    def run(self, params: DeleteVisualKeyframeInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.delete_visual_keyframe(
                params.track_reference,
                params.clip_id,
                automation_id=params.automation_id,
                keyframe_id=params.keyframe_id,
            )
        )


class VideoReplaceVisualAutomationSkill(BaseSkill):
    name = "VideoReplaceVisualAutomationSkill"
    description = "Atomically replace one complete validated visual curve."
    input_model = ReplaceVisualAutomationInput

    def run(self, params: ReplaceVisualAutomationInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.replace_visual_automation(
                params.track_reference, params.clip_id, params.automation
            )
        )


class VideoClearVisualAutomationSkill(BaseSkill):
    name = "VideoClearVisualAutomationSkill"
    description = "Clear one exact curve/property or every curve on one clip."
    input_model = ClearVisualAutomationInput

    def run(self, params: ClearVisualAutomationInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.clear_visual_automation(
                params.track_reference,
                params.clip_id,
                automation_id=params.automation_id,
                property_path=params.property_path,
                clear_all=params.scope == "all",
            )
        )


class VideoCopyVisualAutomationSkill(BaseSkill):
    name = "VideoCopyVisualAutomationSkill"
    description = (
        "Copy selected visual curves to explicit video clip IDs without linked "
        "group expansion."
    )
    input_model = CopyVisualAutomationInput

    def run(self, params: CopyVisualAutomationInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.copy_visual_automation(
                params.source_track_id,
                params.source_clip_id,
                ((item.track_id, item.clip_id) for item in params.targets),
                property_paths=params.property_paths,
            )
        )
