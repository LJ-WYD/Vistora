"""Single production composition root for Vistora's atomic skills."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from audio_analysis import LoudnessAnalysisResult
from skills.audio_timeline_edits import (
    AudioApplyDuckingSkill,
    AudioAnalyzeLoudnessSkill,
    AudioSetClipPropertiesSkill,
    AudioSetTrackMixSkill,
    AudioSetVolumeEnvelopeSkill,
)
from skills.subtitle_timeline_edits import (
    SubtitleEditCueSkill,
    SubtitleExportSidecarSkill,
    SubtitleImportSkill,
    SubtitleManageTrackSkill,
)
from skills.timeline_transitions import (
    TimelineAddTransitionSkill,
    TimelineCopyTransitionSkill,
    TimelineRemoveTransitionSkill,
    TimelineUpdateTransitionSkill,
)

from skills.video_add_clip import VideoAddClipSkill
from skills.video_apply_manual_edits import VideoApplyManualEditsSkill
from skills.video_clear_timeline import VideoClearTimelineSkill
from skills.video_export import VideoExportSkill
from skills.video_export_variants import VideoExportVariantsSkill
from skills.video_graphics import VideoInsertGraphicSkill
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
    VideoSetClipFreezeFrameSkill,
    VideoSplitClipSkill,
    VideoTrimClipSkill,
)
from skills.video_visual_edits import (
    VideoCopyClipVisualSkill,
    VideoSetClipColorSkill,
    VideoSetClipTransformSkill,
)
from skills.video_visual_automation import (
    VideoClearVisualAutomationSkill,
    VideoCopyVisualAutomationSkill,
    VideoDeleteVisualKeyframeSkill,
    VideoReplaceVisualAutomationSkill,
    VideoUpsertVisualKeyframeSkill,
)
from skills.video_masks import (
    VideoCopyClipMasksSkill,
    VideoReplaceClipMasksSkill,
    VideoSetClipCompositeSkill,
    VideoSetClipMaskSkill,
)

from .models import SkillDescriptor, digest_json
from .registry import AtomicSkillRegistry


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SubtitleLayoutResult(_Result):
    track_id: str
    cue_id: str
    start_seconds: float
    end_seconds: float
    text: str
    rendered_text: str
    original_font_size: int
    rendered_font_size: int
    line_count: int
    available_width_px: float
    maximum_line_width_px: float
    safe_area_status: Literal["passed"]


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
    subtitle_mode: str = "none"
    subtitle_track_ids: list[str] = []
    font_warnings: list[str] = []
    subtitle_layout: list[SubtitleLayoutResult] = []


class ExportVariantResult(_Result):
    variant_id: str
    output_path: str
    width: int
    height: int
    fps: float
    size_bytes: int
    sha256: str
    font_warnings: list[str] = []
    subtitle_layout: list[SubtitleLayoutResult] = []


class ExportVariantsResult(_Result):
    status: Literal["success"]
    export_set_id: str
    output_policy: Literal["create_new"]
    subtitle_mode: Literal["none", "burn"]
    outputs: list[ExportVariantResult]


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
        "set_freeze_frame",
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
        "set_clip_mask",
        "replace_clip_masks",
        "copy_clip_masks",
        "set_clip_composite",
    ]
    track_id: str
    track_key: str
    direct_clip_ids: list[str]
    consequential_clip_ids: list[str]
    created_clip_ids: list[str]
    modified_clip_ids: list[str]
    deleted_clip_ids: list[str]
    consequential_subtitle_cue_ids: list[str] = []
    created_transition_ids: list[str] = []
    modified_transition_ids: list[str] = []
    deleted_transition_ids: list[str] = []
    created_automation_ids: list[str] = []
    modified_automation_ids: list[str] = []
    deleted_automation_ids: list[str] = []
    created_mask_ids: list[str] = []
    modified_mask_ids: list[str] = []
    deleted_mask_ids: list[str] = []
    warnings: list[str]
    before_snapshot_id: str
    after_snapshot_id: str
    project_id: str
    revision: int
    timeline_digest: str


class SubtitleEditResult(_Result):
    status: Literal["success"]
    operation: str
    track_id: str
    direct_cue_ids: list[str]
    consequential_cue_ids: list[str]
    created_cue_ids: list[str]
    modified_cue_ids: list[str]
    deleted_cue_ids: list[str]
    created_track_ids: list[str]
    modified_track_ids: list[str]
    deleted_track_ids: list[str]
    warnings: list[str]
    before_snapshot_id: str
    after_snapshot_id: str
    project_id: str
    revision: int
    timeline_digest: str


class SubtitleSidecarResult(_Result):
    status: Literal["success"]
    format: Literal["srt", "vtt"]
    output_path: str
    track_ids: list[str]
    cue_count: int
    sha256: str


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
        registry_revision=14,
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
                VideoExportVariantsSkill(),
                ExportVariantsResult,
                side_effects=("files", "media"),
                transactionality="best_effort",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="none",
                required_capabilities=("media_render",),
            ),
            _entry(
                VideoInsertGraphicSkill(),
                CoreTimelineEditResult,
                side_effects=("files", "timeline"),
                transactionality="atomic_project_state",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="checkpoint_restore",
                required_capabilities=("local_media_read",),
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
                    AudioApplyDuckingSkill(),
                    AudioSetClipPropertiesSkill(),
                    AudioSetTrackMixSkill(),
                    AudioSetVolumeEnvelopeSkill(),
                )
            ),
            *tuple(
                _entry(
                    skill,
                    SubtitleEditResult,
                    side_effects=("files", "timeline"),
                    transactionality="atomic_project_state",
                    retry_safety="gateway_replay_only",
                    preview_supported=True,
                    rollback_support="checkpoint_restore",
                    required_capabilities=(
                        ("local_subtitle_read",)
                        if isinstance(skill, SubtitleImportSkill)
                        else ()
                    ),
                )
                for skill in (
                    SubtitleManageTrackSkill(),
                    SubtitleEditCueSkill(),
                    SubtitleImportSkill(),
                )
            ),
            _entry(
                SubtitleExportSidecarSkill(),
                SubtitleSidecarResult,
                side_effects=("files",),
                transactionality="atomic_file",
                retry_safety="gateway_replay_only",
                preview_supported=True,
                rollback_support="none",
                required_capabilities=(),
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
                    VideoSetClipTransformSkill(),
                    VideoSetClipColorSkill(),
                    VideoCopyClipVisualSkill(),
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
                    required_capabilities=(),
                )
                for skill in (
                    VideoUpsertVisualKeyframeSkill(),
                    VideoDeleteVisualKeyframeSkill(),
                    VideoReplaceVisualAutomationSkill(),
                    VideoClearVisualAutomationSkill(),
                    VideoCopyVisualAutomationSkill(),
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
                    required_capabilities=("ffmpeg",),
                )
                for skill in (
                    VideoSetClipMaskSkill(),
                    VideoReplaceClipMasksSkill(),
                    VideoCopyClipMasksSkill(),
                    VideoSetClipCompositeSkill(),
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
                    required_capabilities=("ffmpeg", "local_media_read"),
                )
                for skill in (
                    TimelineAddTransitionSkill(),
                    TimelineUpdateTransitionSkill(),
                    TimelineRemoveTransitionSkill(),
                    TimelineCopyTransitionSkill(),
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
                    VideoSetClipFreezeFrameSkill(
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
