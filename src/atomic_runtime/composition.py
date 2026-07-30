"""Single production composition root for Vistora's seven atomic skills."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from skills.video_add_clip import VideoAddClipSkill
from skills.video_apply_manual_edits import VideoApplyManualEditsSkill
from skills.video_clear_timeline import VideoClearTimelineSkill
from skills.video_export import VideoExportSkill
from skills.video_modify_clip import VideoModifyClipSkill
from skills.video_restore_timeline_checkpoint import (
    VideoRestoreTimelineCheckpointSkill,
)
from skills.video_timelapse import VideoTimelapseSkill

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
    descriptor = SkillDescriptor(
        name=skill.name,
        skill_version="1.0.0",
        description=skill.description,
        input_schema_version="1.0.0",
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


def build_production_registry() -> AtomicSkillRegistry:
    """Build a fresh immutable registry; no process-global mutable singleton."""

    return AtomicSkillRegistry(
        registry_id="registry_atomic_skills",
        registry_revision=1,
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
                VideoModifyClipSkill(),
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
        ),
    )
