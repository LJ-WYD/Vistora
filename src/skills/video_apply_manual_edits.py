"""Transactional atomic tool for a confirmed manual video-clip edit batch."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from audio_analysis import clip_audio_state_digest, source_sha256

from contracts import (
    ManualClipRemove,
    ManualClipLink,
    ManualClipSplit,
    ManualClipUpdate,
    ManualClipAudio,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualTrackManage,
    ManualTrackMix,
    ManualVolumeEnvelope,
    ManualSubtitleCue,
    ManualSubtitleTrack,
)
from core import timeline_manager
from core.timeline import TimelineConfig
from timeline_query import TimelineSnapshotService
from timeline_edit import TimelineEditEngine, TimelineEditTransaction
from traceability.recording import ManualTraceRecorder
from subtitles import SubtitleEditCueInput, SubtitleEditEngine, SubtitleManageTrackInput

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

        engine = TimelineEditEngine(current)
        for edit in proposal.edits:
            if isinstance(edit, ManualSubtitleTrack):
                subtitle_engine = SubtitleEditEngine(engine.timeline)
                updated, _ = subtitle_engine.manage_track(SubtitleManageTrackInput(
                    action=edit.action,
                    track_id=edit.track_id,
                    kind=edit.track_kind,
                    role=edit.role,
                    language=edit.language,
                    order=edit.order,
                    enabled=edit.enabled,
                    locked=edit.locked,
                    allow_overlaps=edit.allow_overlaps,
                    style=edit.style,
                ))
                engine.timeline = updated
                continue
            if isinstance(edit, ManualSubtitleCue):
                subtitle_engine = SubtitleEditEngine(engine.timeline)
                updated, _ = subtitle_engine.edit_cues(SubtitleEditCueInput(
                    **edit.model_dump(mode="python", exclude={"operation_id", "kind"})
                ))
                engine.timeline = updated
                continue
            if isinstance(edit, ManualTrackMix):
                engine.set_track_mix(
                    edit.track_id,
                    gain_db=edit.gain_db,
                    muted=edit.muted,
                    pan=edit.pan,
                )
                continue
            if isinstance(edit, ManualTrackManage):
                _, track = engine._resolve_track(
                    edit.track_id,
                    allow_locked=True,
                )
                if any(
                    value is not None
                    and value != getattr(track, field)
                    for field, value in (
                        ("role", edit.role),
                        ("enabled", edit.enabled),
                        ("muted", edit.muted),
                        ("locked", edit.locked),
                    )
                ):
                    engine.manage_track(
                        action="update",
                        track_id=edit.track_id,
                        kind=None,
                        role=edit.role,
                        order=None,
                        enabled=edit.enabled,
                        muted=edit.muted,
                        locked=edit.locked,
                    )
                if edit.order is not None and edit.order != track.order:
                    engine.manage_track(
                        action="reorder",
                        track_id=edit.track_id,
                        kind=None,
                        role=None,
                        order=edit.order,
                        enabled=None,
                        muted=None,
                        locked=None,
                    )
                continue
            if isinstance(edit, ManualClipLink):
                engine.set_clip_link(
                    action=edit.action,
                    members=(
                        (member.track_id, member.clip_id)
                        for member in edit.members
                    ),
                    link_group_id=edit.link_group_id,
                )
                continue
            track_reference = edit.track_id or edit.track_key
            if isinstance(edit, ManualClipAudio):
                if edit.normalization_evidence is not None:
                    _, target_track, target_clip = engine.clip_state(
                        track_reference, edit.clip_id
                    )
                    evidence = edit.normalization_evidence
                    if edit.gain_db != evidence.applied_gain_db:
                        raise ValueError(
                            "Loudness application must use the analyzed gain"
                        )
                    if evidence.analyzed_clip_digest != clip_audio_state_digest(
                        target_track.id, target_clip
                    ) or evidence.source_sha256 != source_sha256(
                        target_clip.source
                    ):
                        raise ValueError("Loudness evidence is stale or mismatched")
                engine.set_clip_audio(
                    track_reference,
                    edit.clip_id,
                    gain_db=edit.gain_db,
                    muted=edit.muted,
                    pan=edit.pan,
                    fade_in_seconds=edit.fade_in_seconds,
                    fade_out_seconds=edit.fade_out_seconds,
                    playback_rate=edit.playback_rate,
                    normalization=edit.normalization_evidence,
                )
            elif isinstance(edit, ManualVolumeEnvelope):
                engine.set_volume_envelope(
                    track_reference,
                    edit.clip_id,
                    action=edit.action,
                    point_id=edit.point_id,
                    offset_seconds=edit.offset_seconds,
                    gain_db=edit.gain_db,
                )
            elif isinstance(edit, ManualClipRemove):
                engine.remove(
                    track_reference,
                    edit.clip_id,
                    ripple=edit.mode == "ripple",
                    edit_scope=edit.edit_scope,
                    subtitle_ripple=edit.subtitle_ripple,
                )
            elif isinstance(edit, ManualClipSplit):
                engine.split(
                    track_reference,
                    edit.clip_id,
                    edit.split_at_seconds,
                    right_clip_id=edit.right_clip_id,
                    edit_scope=edit.edit_scope,
                )
            else:
                _, _, target = engine._clip(
                    track_reference,
                    edit.clip_id,
                )
                changed = False
                if (
                    abs(target.trim_in - edit.trim_in_seconds) > 1e-6
                    or abs(target.trim_out - edit.trim_out_seconds) > 1e-6
                ):
                    engine.trim(
                        track_reference,
                        edit.clip_id,
                        edit.trim_in_seconds,
                        edit.trim_out_seconds,
                        ripple=edit.ripple,
                        edit_scope=edit.edit_scope,
                        subtitle_ripple=edit.subtitle_ripple,
                    )
                    changed = True
                _, _, target = engine._clip(
                    track_reference,
                    edit.clip_id,
                )
                if (
                    abs(
                        target.timeline_start
                        - edit.timeline_start_seconds
                    )
                    > 1e-6
                ):
                    engine.move(
                        track_reference,
                        edit.clip_id,
                        edit.timeline_start_seconds,
                        ripple=False,
                        edit_scope=edit.edit_scope,
                    )
                    changed = True
                if not changed:
                    raise ValueError("Manual update changes no fields")
                _, track = engine._resolve_track(
                    track_reference,
                    allow_locked=True,
                )
                actual_index = next(
                    index
                    for index, clip in enumerate(track.clips)
                    if clip.id == edit.clip_id
                )
                if edit.order_index >= len(track.clips):
                    raise ValueError(
                        f"Manual clip order {edit.order_index} is outside "
                        f"0..{len(track.clips) - 1}"
                    )
                if actual_index != edit.order_index:
                    moved = track.clips.pop(actual_index)
                    track.clips.insert(edit.order_index, moved)
        updated = engine.timeline

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
