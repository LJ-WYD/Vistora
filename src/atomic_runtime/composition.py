"""Single production composition root for Vistora's atomic skills."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from audio_analysis import LoudnessAnalysisResult
from skills.audio_timeline_edits import (
    AudioAnalyzeLoudnessSkill,
    AudioSetClipPropertiesSkill,
    AudioSetTrackMixSkill,
    AudioSetVolumeEnvelopeSkill,
)

from skills.video_add_clip import VideoAddClipSkill
from skills.video_apply_manual_edits import VideoApplyManualEditsSkill
from skills.video_clear_timeline import VideoClearTimelineSkill
from skills.video_export import VideoExportSkill
from skills.video_modify_clip import VideoModifyClipSkill
from skills.video_restore_timeline_checkpoint import (
    VideoRestoreTimelineCheckpointSkill,
)
from skills.video_timelapse import VideoTimelapseSkill
from skills.video_timeline_edits import (
    TimelineManageTrackSkill,
    TimelineSetClipLinkSkill,
    VideoInsertOverwriteClipSkill,
    VideoMoveClipSkill,
    VideoRemoveClipSkill,
    VideoSetClipPropertiesSkill,
    VideoSplitClipSkill,
    VideoTrimClipSkill,
)

from .models import SkillDescriptor, digest_json
from .registry import AtomicSkillRegistry


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AddClipResult(_Result):
    status: str
    message: str
    clip_id: str
    timeline_start: float
    effective_duration: float


class ModifyClipResult(_Result):
    status: str
    message: str
    modified_clip_id: str
    updated_properties: list[str]


class ExportResult(_Result):
    status: str
    message: str
    output_path: str


class TimelapseResult(ExportResult):
    target_fps: int


class ClearTimelineResult(_Result):
    status: str
    message: str


class ManualEditResult(_Result):
    status: str
    tool_name: str
    proposal_id: str
    proposal_digest: str
    confirmation_id: str
    previous_snapshot_id: str
    snapshot_id: str
    project_id: str
    revision: int
    timeline_digest: str
    trace_id: str
    trace_sequence: int
    applied_operation_ids: list[str]


class RestoreResult(_Result):
    status: str
    restored_checkpoint_id: str
    timeline_digest: str
    external_artifacts_changed: bool


class CoreTimelineEditResult(_Result):
    status: Literal["success"]
    operation: Literal[
        "split",
        "trim",
        "move",
        "insert",
        "overwrite",
        "remove",
        "set_properties",
        "manage_track",
        "set_clip_link",
        "set_clip_audio",
        "set_track_mix",
        "set_volume_envelope",
    ]
    track_id: str
    track_key: str
    direct_clip_ids: list[str]
    consequential_clip_ids: list[str]
    created_clip_ids: list[str]
    modified_clip_ids: list[str]
    deleted_clip_ids: list[str]
    warnings: list[str]
    before_snapshot_id: str
    after_snapshot_id: str
    project_id: str
    revision: int
    timeline_digest: str


def _entry(
    skill: Any,
    output_model: type[BaseModel],
    *,
    side_effects: tuple[str, ...],
    transactionality: str,
    retry_safety: str,
    preview_supported: bool,
    rollback_support: str,
    required_capabilities: tuple[str, ...],
) -> tuple[Any, SkillDescriptor, type[BaseModel]]:
    input_schema = skill.input_model.model_json_schema()
    output_schema = output_model.model_json_schema()
    input_schema_version = (
        input_schema.get("properties", {})
        .get("schema_version", {})
        .get("default", "1.0.0")
    )
    descriptor = SkillDescriptor(
        name=skill.name,
        skill_version="1.0.0",
        description=skill.description,
        input_schema_version=input_schema_version,
        input_schema=input_schema,
        input_schema_digest=digest_json(input_schema),
        output_schema_version="1.0.0",
        output_schema=output_schema,
        output_schema_digest=digest_json(output_schema),
        side_effects=tuple(sorted(side_effects)),
        mutation=bool(side_effects),
        transactionality=transactionality,
        retry_safety=retry_safety,
        preview_supported=preview_supported,
        rollback_support=rollback_support,
        required_capabilities=tuple(sorted(required_capabilities)),
    )
    return skill, descriptor, output_model


def build_production_registry(
    *,
    timeline_id_factory: Callable[[str], str] | None = None,
) -> AtomicSkillRegistry:
    """Build a fresh immutable registry; no process-global mutable singleton."""

    legacy_modify = VideoModifyClipSkill()
    legacy_modify.description = (
        "Legacy index-addressed video property editor retained for backward "
        "compatibility; new plans should use exact clip_id tools. Enabling "
        "reverse may still generate a best-effort proxy."
    )
    return AtomicSkillRegistry(
        registry_id="registry_atomic_skills",
        registry_revision=3,
        entries=(
            _entry(
                VideoAddClipSkill(),
                AddClipResult,
                side_effects=("files", "media", "timeline"),
                transactionality="best_effort",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="checkpoint_restore",
                required_capabilities=("ffmpeg", "local_media_read"),
            ),
            _entry(
                legacy_modify,
                ModifyClipResult,
                side_effects=("files", "timeline"),
                transactionality="best_effort",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="checkpoint_restore",
                required_capabilities=("local_media_read",),
            ),
            _entry(
                VideoExportSkill(),
                ExportResult,
                side_effects=("files", "media", "timeline"),
                transactionality="best_effort",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="none",
                required_capabilities=("media_render",),
            ),
            _entry(
                VideoTimelapseSkill(),
                TimelapseResult,
                side_effects=("files", "media"),
                transactionality="best_effort",
                retry_safety="gateway_replay_only",
                preview_supported=False,
                rollback_support="none",
                required_capabilities=("ffmpeg", "local_media_read"),
            ),
            _entry(
                VideoClearTimelineSkill(),
                ClearTimelineResult,
                side_effects=("files", "timeline"),
                transactionality="best_effort",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="checkpoint_restore",
                required_capabilities=(),
            ),
            _entry(
                VideoApplyManualEditsSkill(),
                ManualEditResult,
                side_effects=("files", "timeline"),
                transactionality="atomic_project_state",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="checkpoint_restore",
                required_capabilities=(),
            ),
            _entry(
                VideoRestoreTimelineCheckpointSkill(),
                RestoreResult,
                side_effects=("files", "timeline"),
                transactionality="atomic_project_state",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="checkpoint_restore",
                required_capabilities=(),
            ),
            _entry(
                AudioAnalyzeLoudnessSkill(),
                LoudnessAnalysisResult,
                side_effects=(),
                transactionality="none",
                retry_safety="intrinsically_idempotent",
                preview_supported=True,
                rollback_support="none",
                required_capabilities=("ffmpeg", "local_media_read"),
            ),
            *tuple(
                _entry(
                    skill,
                    CoreTimelineEditResult,
                    side_effects=("files", "timeline"),
                    transactionality="atomic_project_state",
                    retry_safety="gateway_replay_only",
                    preview_supported=True,
                    rollback_support="checkpoint_restore",
                    required_capabilities=(),
                )
                for skill in (
                    AudioSetClipPropertiesSkill(),
                    AudioSetTrackMixSkill(),
                    AudioSetVolumeEnvelopeSkill(),
                )
            ),
            *tuple(
                _entry(
                    skill,
                    CoreTimelineEditResult,
                    side_effects=("files", "timeline"),
                    transactionality="atomic_project_state",
                    retry_safety="gateway_replay_only",
                    preview_supported=True,
                    rollback_support="checkpoint_restore",
                    required_capabilities=(
                        ("local_media_read",)
                        if isinstance(
                            skill,
                            VideoInsertOverwriteClipSkill,
                        )
                        else ()
                    ),
                )
                for skill in (
                    VideoSplitClipSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    VideoTrimClipSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    VideoMoveClipSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    VideoInsertOverwriteClipSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    VideoRemoveClipSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    VideoSetClipPropertiesSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    TimelineManageTrackSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                    TimelineSetClipLinkSkill(
                        **(
                            {"id_factory": timeline_id_factory}
                            if timeline_id_factory is not None
                            else {}
                        )
                    ),
                )
            ),
        ),
    )
