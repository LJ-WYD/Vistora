"""Transactional atomic tool for a confirmed manual video-clip edit batch."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from contracts import (
    ManualClipRemove,
    ManualClipUpdate,
    ManualEditConfirmationRecord,
    ManualEditProposal,
)
from core import timeline_manager
from core.timeline import TimelineConfig
from timeline_query import TimelineSnapshotService

from .base import BaseSkill


class VideoApplyManualEditsInput(BaseModel):
    """Exact confirmed user proposal accepted by the atomic mutation tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: ManualEditProposal
    confirmation: ManualEditConfirmationRecord


def _find_unique_clip_index(
    timeline: TimelineConfig,
    clip_id: str,
) -> int:
    video_track = timeline.tracks.get("video")
    if video_track is None:
        raise ValueError("The current timeline has no video track")
    matches = [
        index
        for index, clip in enumerate(video_track.clips)
        if clip.id == clip_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Manual edit target {clip_id!r} must identify exactly one "
            "current video clip"
        )
    return matches[0]


def _apply_edit(
    timeline: TimelineConfig,
    edit: ManualClipUpdate | ManualClipRemove,
) -> None:
    video_track = timeline.tracks.get("video")
    if video_track is None:
        raise ValueError("The current timeline has no video track")
    index = _find_unique_clip_index(timeline, edit.clip_id)
    if isinstance(edit, ManualClipRemove):
        video_track.clips.pop(index)
        return

    clip = video_track.clips[index]
    clip.trim_in = edit.trim_in_seconds
    clip.trim_out = edit.trim_out_seconds
    clip.timeline_start = edit.timeline_start_seconds
    if edit.order_index >= len(video_track.clips):
        raise ValueError(
            f"Manual clip order {edit.order_index} is outside the current "
            f"video track range 0..{len(video_track.clips) - 1}"
        )
    if edit.order_index != index:
        moved = video_track.clips.pop(index)
        video_track.clips.insert(edit.order_index, moved)


def _atomic_save(timeline: TimelineConfig) -> None:
    """Replace current timeline JSON only after a complete durable temp write."""

    project_file = Path(timeline_manager.PROJECT_FILE)
    workspace = project_file.parent
    workspace.mkdir(parents=True, exist_ok=True)
    temp_path = workspace / (
        f".{project_file.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        content = timeline.model_dump_json(indent=2)
        with temp_path.open("x", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, project_file)
    finally:
        temp_path.unlink(missing_ok=True)


class VideoApplyManualEditsSkill(BaseSkill):
    """Apply an exact confirmed manual clip proposal as one atomic write."""

    name = "VideoApplyManualEditsSkill"
    description = (
        "Apply one explicitly confirmed, snapshot-bound batch of manual "
        "video clip timing, ordering, or removal edits transactionally."
    )
    input_model = VideoApplyManualEditsInput

    def run(self, params: VideoApplyManualEditsInput) -> dict[str, Any]:
        proposal = params.proposal
        confirmation = params.confirmation
        if not confirmation.confirms(proposal):
            raise ValueError(
                "Manual edit execution requires confirmation of this exact "
                "user-authored proposal ID and digest"
            )

        current = timeline_manager.TimelineManager.get_current_timeline()
        current_snapshot = TimelineSnapshotService.snapshot(current)
        if current_snapshot.project_id != proposal.base_project_id:
            raise ValueError(
                "Manual edit proposal is stale: project identity changed"
            )
        if current_snapshot.revision != proposal.base_revision:
            raise ValueError(
                "Manual edit proposal is stale: project revision changed"
            )
        if current_snapshot.timeline_digest != proposal.base_timeline_digest:
            raise ValueError(
                "Manual edit proposal is stale: timeline content changed"
            )

        updated = current.model_copy(deep=True)
        for edit in proposal.edits:
            _apply_edit(updated, edit)

        _atomic_save(updated)
        applied_snapshot = TimelineSnapshotService.snapshot(updated)
        return {
            "status": "success",
            "tool_name": self.name,
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.digest(),
            "confirmation_id": confirmation.confirmation_id,
            "previous_snapshot_id": current_snapshot.snapshot_id,
            "snapshot_id": applied_snapshot.snapshot_id,
            "project_id": applied_snapshot.project_id,
            "revision": applied_snapshot.revision,
            "timeline_digest": applied_snapshot.timeline_digest,
            "applied_operation_ids": [
                edit.operation_id for edit in proposal.edits
            ],
        }
