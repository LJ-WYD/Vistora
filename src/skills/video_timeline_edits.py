"""Professional core timeline edits backed by one shared atomic transaction."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

from moviepy import AudioFileClip, VideoFileClip

from core import timeline_manager
from core.timeline import ClipConfig
from material_production import MaterialCatalogStore
from timeline_edit import (
    InsertOverwriteClipInput,
    ManageTrackInput,
    MoveClipInput,
    RemoveClipInput,
    SetClipPropertiesInput,
    SetClipLinkInput,
    SplitClipInput,
    TimelineEditEngine,
    TimelineEditTransaction,
    TrimClipInput,
)

from .base import BaseSkill


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _resolve_source(source_path: str) -> str:
    if source_path.startswith("material://"):
        resolved = MaterialCatalogStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ).resolve_uri(source_path)
        if resolved is None:
            raise FileNotFoundError(
                "Catalog material is missing, unaccepted, or tampered"
            )
        return str(resolved)
    if not os.path.isfile(source_path):
        raise FileNotFoundError("The configured source file is unavailable")
    return source_path


def _media_facts(
    source_path: str,
    track_key: str,
) -> tuple[float, int | None, int | None]:
    clip = (
        VideoFileClip(source_path)
        if track_key == "video"
        else AudioFileClip(source_path)
    )
    try:
        if clip.duration is None or clip.duration <= 0:
            raise ValueError("Source media has no positive duration")
        return (
            float(clip.duration),
            int(clip.w) if track_key == "video" else None,
            int(clip.h) if track_key == "video" else None,
        )
    finally:
        clip.close()


class _TransactionalEditSkill(BaseSkill):
    def __init__(
        self,
        *,
        id_factory: Callable[[str], str] = _random_id,
    ) -> None:
        self.id_factory = id_factory


class VideoSplitClipSkill(_TransactionalEditSkill):
    name = "VideoSplitClipSkill"
    description = (
        "Split one exact video or audio clip at an interior timeline time, "
        "preserving source and playback properties."
    )
    input_model = SplitClipInput

    def run(self, params: SplitClipInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.split(
                params.track_reference,
                params.clip_id,
                params.split_at_seconds,
                right_clip_id=params.right_clip_id,
                edit_scope=params.edit_scope,
            ),
            id_factory=self.id_factory,
        )


class VideoTrimClipSkill(_TransactionalEditSkill):
    name = "VideoTrimClipSkill"
    description = (
        "Trim one exact clip by source in/out with optional same-track "
        "ripple movement of clips that follow its prior end."
    )
    input_model = TrimClipInput

    def run(self, params: TrimClipInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.trim(
                params.track_reference,
                params.clip_id,
                params.trim_in,
                params.trim_out,
                ripple=params.ripple,
                edit_scope=params.edit_scope,
            ),
            id_factory=self.id_factory,
        )


class VideoMoveClipSkill(_TransactionalEditSkill):
    name = "VideoMoveClipSkill"
    description = (
        "Move one exact clip to an explicit timeline start using non-ripple "
        "overlap or deterministic same-track ripple semantics."
    )
    input_model = MoveClipInput

    def run(self, params: MoveClipInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.move(
                params.track_reference,
                params.clip_id,
                params.timeline_start,
                ripple=params.ripple,
                edit_scope=params.edit_scope,
            ),
            id_factory=self.id_factory,
        )


class VideoRemoveClipSkill(_TransactionalEditSkill):
    name = "VideoRemoveClipSkill"
    description = (
        "Remove one exact clip as a gap-preserving lift or same-track "
        "ripple delete."
    )
    input_model = RemoveClipInput

    def run(self, params: RemoveClipInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.remove(
                params.track_reference,
                params.clip_id,
                ripple=params.mode == "ripple",
                edit_scope=params.edit_scope,
            ),
            id_factory=self.id_factory,
        )


class VideoInsertOverwriteClipSkill(_TransactionalEditSkill):
    name = "VideoInsertOverwriteClipSkill"
    description = (
        "Insert or overwrite one accepted catalog/local source at an exact "
        "time, retaining every uncovered side of overlapped clips."
    )
    input_model = InsertOverwriteClipInput

    def run(self, params: InsertOverwriteClipInput) -> dict[str, Any]:
        resolved = _resolve_source(params.source_path)
        current = timeline_manager.TimelineManager.get_current_timeline()
        track_kind = TimelineEditEngine(current).track_kind(
            params.track_reference
        )
        source_duration, width, height = _media_facts(
            resolved,
            track_kind,
        )
        trim_out = min(
            source_duration,
            params.trim_out
            if params.trim_out is not None
            else source_duration,
        )
        if trim_out <= params.trim_in:
            raise ValueError("Insert source range is empty or out of bounds")
        clip = ClipConfig(
            id=params.clip_id or self.id_factory("clip"),
            source=resolved,
            trim_in=params.trim_in,
            trim_out=trim_out,
            timeline_start=params.timeline_start,
            speed_factor=params.speed_factor,
            volume=params.volume,
            keep_audio=params.keep_audio,
            rotate=params.rotate,
            reverse=False,
            link_group_id=params.link_group_id,
        )
        def apply(engine):
            if (
                track_kind == "video"
                and not any(
                    track.clips
                    for track in engine.timeline.tracks.values()
                    if track.kind == "video"
                )
                and width is not None
                and height is not None
            ):
                engine.timeline.width = width
                engine.timeline.height = height
            return engine.insert_overwrite(
                params.track_reference,
                clip,
                mode=params.mode,
                edit_scope=params.edit_scope,
            )

        return TimelineEditTransaction.apply(
            apply,
            id_factory=self.id_factory,
        )


class VideoSetClipPropertiesSkill(_TransactionalEditSkill):
    name = "VideoSetClipPropertiesSkill"
    description = (
        "Update speed, volume/mute, embedded-audio retention, or rotation for "
        "one exact clip_id without generating reverse proxy media."
    )
    input_model = SetClipPropertiesInput

    def run(self, params: SetClipPropertiesInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_properties(
                params.track_reference,
                params.clip_id,
                speed_factor=params.speed_factor,
                volume=params.volume,
                keep_audio=params.keep_audio,
                mute=params.mute,
                rotate=params.rotate,
                edit_scope=params.edit_scope,
            ),
            id_factory=self.id_factory,
        )


class TimelineManageTrackSkill(_TransactionalEditSkill):
    name = "TimelineManageTrackSkill"
    description = (
        "Add, update, reorder, or safely remove an empty stable-ID video or "
        "audio track. Locked tracks must be explicitly unlocked before removal."
    )
    input_model = ManageTrackInput

    def run(self, params: ManageTrackInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.manage_track(
                action=params.action,
                track_id=params.track_id,
                kind=params.kind,
                role=params.role,
                order=params.order,
                enabled=params.enabled,
                muted=params.muted,
                locked=params.locked,
            ),
            id_factory=self.id_factory,
        )


class TimelineSetClipLinkSkill(_TransactionalEditSkill):
    name = "TimelineSetClipLinkSkill"
    description = (
        "Explicitly link or unlink exact clip IDs across stable tracks; "
        "filesystem paths and timing proximity are never used for inference."
    )
    input_model = SetClipLinkInput

    def run(self, params: SetClipLinkInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_link(
                action=params.action,
                members=(
                    (member.track_id, member.clip_id)
                    for member in params.members
                ),
                link_group_id=params.link_group_id,
            ),
            id_factory=self.id_factory,
        )
