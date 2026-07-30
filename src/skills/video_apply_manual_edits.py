"""Transactional atomic tool for a confirmed manual video-clip edit batch."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from contracts import (
    ManualClipRemove,
    ManualClipSplit,
    ManualClipUpdate,
    ManualEditConfirmationRecord,
    ManualEditProposal,
)
from core import timeline_manager
from core.timeline import TimelineConfig
from timeline_query import TimelineSnapshotService
from timeline_edit import TimelineEditTransaction
from traceability.recording import ManualTraceRecorder

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
    edit: ManualClipUpdate | ManualClipRemove | ManualClipSplit,
) -> None:
    video_track = timeline.tracks.get("video")
    if video_track is None:
        raise ValueError("The current timeline has no video track")
    index = _find_unique_clip_index(timeline, edit.clip_id)
    if isinstance(edit, ManualClipRemove):
        clip = video_track.clips.pop(index)
        if edit.mode == "ripple":
            duration = (
                clip.trim_out - clip.trim_in
            ) / clip.speed_factor
            old_end = clip.timeline_start + duration
            for other in video_track.clips:
                if other.timeline_start >= old_end - 1e-6:
                    other.timeline_start = max(
                        0.0, other.timeline_start - duration
                    )
        return

    if isinstance(edit, ManualClipSplit):
        clip = video_track.clips[index]
        duration = (clip.trim_out - clip.trim_in) / clip.speed_factor
        old_end = clip.timeline_start + duration
        if (
            edit.split_at_seconds <= clip.timeline_start + 1e-6
            or edit.split_at_seconds >= old_end - 1e-6
        ):
            raise ValueError("Split point must be inside the selected clip")
        if any(
            edit.right_clip_id == candidate.id
            for track in timeline.tracks.values()
            for candidate in track.clips
        ):
            raise ValueError("Split output clip ID already exists")
        source_split = clip.trim_in + (
            edit.split_at_seconds - clip.timeline_start
        ) * clip.speed_factor
        original_out = clip.trim_out
        clip.trim_out = source_split
        right = clip.model_copy(deep=True)
        right.id = edit.right_clip_id
        right.trim_in = source_split
        right.trim_out = original_out
        right.timeline_start = edit.split_at_seconds
        video_track.clips.insert(index + 1, right)
        return

    clip = video_track.clips[index]
    old_end = clip.timeline_start + (
        clip.trim_out - clip.trim_in
    ) / clip.speed_factor
    old_duration = (
        clip.trim_out - clip.trim_in
    ) / clip.speed_factor
    clip.trim_in = edit.trim_in_seconds
    clip.trim_out = edit.trim_out_seconds
    clip.timeline_start = edit.timeline_start_seconds
    if edit.ripple:
        new_duration = (
            clip.trim_out - clip.trim_in
        ) / clip.speed_factor
        delta = new_duration - old_duration
        for other in video_track.clips:
            if (
                other.id != clip.id
                and other.timeline_start >= old_end - 1e-6
            ):
                other.timeline_start = max(
                    0.0, other.timeline_start + delta
                )
    if edit.order_index >= len(video_track.clips):
        raise ValueError(
            f"Manual clip order {edit.order_index} is outside the current "
            f"video track range 0..{len(video_track.clips) - 1}"
        )
    if edit.order_index != index:
        moved = video_track.clips.pop(index)
        video_track.clips.insert(edit.order_index, moved)


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

        previous_content = TimelineEditTransaction.current_bytes()
        TimelineEditTransaction.replace_config(updated)
        applied_snapshot = TimelineSnapshotService.snapshot(updated)
        try:
            trace = ManualTraceRecorder.record(
                proposal,
                confirmation,
                current_snapshot,
                applied_snapshot,
            )
        except Exception:
            TimelineEditTransaction.restore_bytes(previous_content)
            raise
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
            "trace_id": trace.trace_id,
            "trace_sequence": trace.trace_sequence,
            "applied_operation_ids": [
                edit.operation_id for edit in proposal.edits
            ],
        }
