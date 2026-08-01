"""Confirmed manual-edit application service for the local preview."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from atomic_runtime import (
    AtomicExecutionContext,
    AtomicExecutionGateway,
    AtomicSkillRegistry,
)
from contracts import (
    AtomicToolRequestEnvelope,
    ManualClipRemove,
    ManualClipLink,
    ManualClipSplit,
    ManualClipUpdate,
    ManualClipAudio,
    ManualEditChange,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualEditProposalReference,
    ManualEditReview,
    ManualTrackManage,
    ManualTrackMix,
    ManualVolumeEnvelope,
    ManualSubtitleCue,
    ManualSubtitleTrack,
    PlanReference,
)
from core.timeline import (
    AudioEnvelopePoint,
    ClipAudioSettings,
    ClipConfig,
    TimelineConfig,
    TrackConfig,
    TrackMixSettings,
    SubtitleCue,
    SubtitleStyle,
    SubtitleTrackConfig,
)
from subtitles import SubtitleEditCueInput, SubtitleEditEngine, SubtitleEditError, SubtitleManageTrackInput
from timeline_edit import TimelineEditEngine, TimelineEditError
from timeline_query import TimelineSnapshot, TimelineSnapshotService


MANUAL_EDIT_TOOL_NAME = "VideoApplyManualEditsSkill"
LOUDNESS_ANALYSIS_TOOL_NAME = "AudioAnalyzeLoudnessSkill"


class ManualEditValidationError(ValueError):
    """A user-authored proposal cannot be reviewed or applied safely."""


def _validation_message(exc: ValidationError, subject: str) -> str:
    error = exc.errors(include_url=False, include_context=False)[0]
    location = ".".join(str(item) for item in error.get("loc", ()))
    detail = str(error.get("msg", "does not match the versioned schema"))
    return f"Invalid {subject} field {location}: {detail}."


def _clip_state(clip: Any, order_index: int) -> dict[str, Any]:
    return {
        "clip_id": clip.clip_id,
        "order_index": order_index,
        "trim_in_seconds": clip.trim_in_seconds,
        "trim_out_seconds": clip.trim_out_seconds,
        "timeline_start_seconds": clip.timeline_start_seconds,
        "timeline_end_seconds": clip.timeline_end_seconds,
        "effective_duration_seconds": clip.effective_duration_seconds,
        "speed_factor": clip.speed_factor,
        "volume": clip.volume,
        "keep_audio": clip.keep_audio,
        "reverse": clip.reverse,
        "rotate_degrees": clip.rotate_degrees,
        "link_group_id": clip.link_group_id,
        "source_id": clip.source.source_id,
        "source_name": clip.source.display_name,
        "audio_gain_db": clip.audio_gain_db,
        "audio_muted": clip.audio_muted,
        "audio_pan": clip.audio_pan,
        "audio_fade_in_seconds": clip.audio_fade_in_seconds,
        "audio_fade_out_seconds": clip.audio_fade_out_seconds,
        "audio_envelope": clip.audio_envelope,
        "loudness_analysis_id": clip.loudness_analysis_id,
    }


def _find_unique_state_index(
    states: list[dict[str, Any]],
    clip_id: str,
) -> int:
    matches = [
        index
        for index, state in enumerate(states)
        if state["clip_id"] == clip_id
    ]
    if len(matches) != 1:
        raise ManualEditValidationError(
            f"Clip {clip_id!r} must identify exactly one current video clip"
        )
    return matches[0]


def _review_manual_edit_proposal_legacy(
    snapshot: TimelineSnapshot,
    proposal: ManualEditProposal,
) -> ManualEditReview:
    """Validate and diff a proposal without mutating source or persistence."""

    if snapshot.project_id != proposal.base_project_id:
        raise ManualEditValidationError(
            "Proposal project does not match the current snapshot"
        )
    if snapshot.revision != proposal.base_revision:
        raise ManualEditValidationError(
            "Proposal revision does not match the current snapshot"
        )
    if snapshot.timeline_digest != proposal.base_timeline_digest:
        raise ManualEditValidationError(
            "Proposal timeline digest does not match the current snapshot"
        )

    video_tracks = [
        track for track in snapshot.tracks if track.track_key == "video"
    ]
    if len(video_tracks) != 1:
        raise ManualEditValidationError(
            "Manual editing requires exactly one current video track"
        )
    states = [
        _clip_state(clip, index)
        for index, clip in enumerate(video_tracks[0].clips)
    ]
    changes: list[ManualEditChange] = []

    for edit in proposal.edits:
        index = _find_unique_state_index(states, edit.clip_id)
        before = {**states[index], "order_index": index}
        if isinstance(edit, ManualClipRemove):
            states.pop(index)
            changes.append(
                ManualEditChange(
                    operation_id=edit.operation_id,
                    track_key=edit.track_key,
                    clip_id=edit.clip_id,
                    action="remove",
                    before=before,
                    after=None,
                )
            )
            if edit.mode == "ripple":
                duration = before["effective_duration_seconds"]
                old_end = before["timeline_end_seconds"]
                for state in states:
                    if state["timeline_start_seconds"] >= old_end - 1e-6:
                        previous = dict(state)
                        state["timeline_start_seconds"] -= duration
                        state["timeline_end_seconds"] -= duration
                        changes.append(
                            ManualEditChange(
                                operation_id=edit.operation_id,
                                track_key=edit.track_key,
                                clip_id=state["clip_id"],
                                action="update",
                                effect_kind="consequential",
                                before=previous,
                                after=dict(state),
                            )
                        )
            continue

        if isinstance(edit, ManualClipSplit):
            if any(
                state["clip_id"] == edit.right_clip_id
                for state in states
            ):
                raise ManualEditValidationError(
                    "Split output clip ID already exists"
                )
            if (
                edit.split_at_seconds
                <= before["timeline_start_seconds"] + 1e-6
                or edit.split_at_seconds
                >= before["timeline_end_seconds"] - 1e-6
            ):
                raise ManualEditValidationError(
                    "Split point must be inside the selected clip"
                )
            source_split = before["trim_in_seconds"] + (
                edit.split_at_seconds
                - before["timeline_start_seconds"]
            ) * before["speed_factor"]
            left = {
                **before,
                "trim_out_seconds": source_split,
                "timeline_end_seconds": edit.split_at_seconds,
                "effective_duration_seconds": (
                    edit.split_at_seconds
                    - before["timeline_start_seconds"]
                ),
            }
            right = {
                **before,
                "clip_id": edit.right_clip_id,
                "order_index": index + 1,
                "trim_in_seconds": source_split,
                "timeline_start_seconds": edit.split_at_seconds,
                "effective_duration_seconds": (
                    before["timeline_end_seconds"] - edit.split_at_seconds
                ),
            }
            states[index] = left
            states.insert(index + 1, right)
            changes.extend(
                (
                    ManualEditChange(
                        operation_id=edit.operation_id,
                        track_key=edit.track_key,
                        clip_id=edit.clip_id,
                        action="update",
                        before=before,
                        after=left,
                    ),
                    ManualEditChange(
                        operation_id=edit.operation_id,
                        track_key=edit.track_key,
                        clip_id=edit.right_clip_id,
                        action="create",
                        before=None,
                        after=right,
                    ),
                )
            )
            continue

        clip = video_tracks[0].clips[
            next(
                clip_index
                for clip_index, candidate in enumerate(video_tracks[0].clips)
                if candidate.clip_id == edit.clip_id
            )
        ]
        if edit.order_index >= len(states):
            raise ManualEditValidationError(
                f"Clip order {edit.order_index} is outside the current "
                f"video track range 0..{len(states) - 1}"
            )
        duration = (
            edit.trim_out_seconds - edit.trim_in_seconds
        ) / clip.speed_factor
        after = {
            **before,
            "order_index": edit.order_index,
            "trim_in_seconds": edit.trim_in_seconds,
            "trim_out_seconds": edit.trim_out_seconds,
            "timeline_start_seconds": edit.timeline_start_seconds,
            "timeline_end_seconds": (
                edit.timeline_start_seconds + duration
            ),
            "effective_duration_seconds": duration,
        }
        if after == before:
            raise ManualEditValidationError(
                f"Update for clip {edit.clip_id!r} does not change any field"
            )
        ripple_changes: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if edit.ripple:
            old_end = before["timeline_end_seconds"]
            delta = duration - before["effective_duration_seconds"]
            for state in states:
                if (
                    state["clip_id"] != edit.clip_id
                    and state["timeline_start_seconds"] >= old_end - 1e-6
                ):
                    previous = dict(state)
                    state["timeline_start_seconds"] += delta
                    state["timeline_end_seconds"] += delta
                    ripple_changes.append((previous, dict(state)))
        states[index] = after
        if edit.order_index != index:
            moved = states.pop(index)
            states.insert(edit.order_index, moved)
        changes.append(
            ManualEditChange(
                operation_id=edit.operation_id,
                track_key=edit.track_key,
                clip_id=edit.clip_id,
                action="update",
                before=before,
                after=after,
            )
        )
        changes.extend(
            ManualEditChange(
                operation_id=edit.operation_id,
                track_key=edit.track_key,
                clip_id=current["clip_id"],
                action="update",
                effect_kind="consequential",
                before=previous,
                after=current,
            )
            for previous, current in ripple_changes
        )

    return ManualEditReview(
        proposal_ref=ManualEditProposalReference.from_proposal(proposal),
        snapshot_id=snapshot.snapshot_id,
        changes=tuple(changes),
    )


def _timeline_from_snapshot(snapshot: TimelineSnapshot) -> TimelineConfig:
    timeline = TimelineConfig(
        width=snapshot.width,
        height=snapshot.height,
        fps=snapshot.fps,
        tracks={
            track.track_key: TrackConfig(
                id=track.track_id,
                kind=track.kind,
                role=track.role,
                order=track.order_index,
                enabled=track.enabled,
                muted=track.muted,
                locked=track.locked,
                mix=TrackMixSettings(
                    gain_db=track.mix_gain_db,
                    muted=track.mix_muted,
                    pan=track.mix_pan,
                ),
                clips=[
                    ClipConfig(
                        id=clip.clip_id,
                        source=clip.source.value,
                        trim_in=clip.trim_in_seconds,
                        trim_out=clip.trim_out_seconds,
                        timeline_start=clip.timeline_start_seconds,
                        volume=clip.volume,
                        keep_audio=clip.keep_audio,
                        speed_factor=clip.speed_factor,
                        reverse=clip.reverse,
                        rotate=clip.rotate_degrees,
                        link_group_id=clip.link_group_id,
                        audio=ClipAudioSettings(
                            gain_db=clip.audio_gain_db,
                            muted=clip.audio_muted,
                            pan=clip.audio_pan,
                            fade_in_seconds=clip.audio_fade_in_seconds,
                            fade_out_seconds=clip.audio_fade_out_seconds,
                            envelope=tuple(
                                AudioEnvelopePoint(
                                    point_id=point[0],
                                    offset_seconds=point[1],
                                    gain_db=point[2],
                                )
                                for point in clip.audio_envelope
                            ),
                        ),
                    )
                    for clip in track.clips
                ],
            )
            for track in snapshot.tracks
        },
    )
    timeline.subtitle_tracks = {
        track.track_key: SubtitleTrackConfig(
            track_id=track.track_id,
            kind=track.kind,
            role=track.role,
            language=track.language,
            order=track.order_index,
            enabled=track.enabled,
            locked=track.locked,
            allow_overlaps=track.allow_overlaps,
            style=SubtitleStyle.model_validate(track.style.model_dump(mode="python", exclude={"schema_name"})),
            cues=tuple(
                SubtitleCue(
                    cue_id=cue.cue_id,
                    start_seconds=cue.start_seconds,
                    end_seconds=cue.end_seconds,
                    text=cue.text,
                    language=cue.language,
                    speaker=cue.speaker,
                    enabled=cue.enabled,
                    settings=cue.settings,
                    style=(SubtitleStyle.model_validate(cue.style.model_dump(mode="python", exclude={"schema_name"})) if cue.style is not None else None),
                )
                for cue in track.cues
            ),
        )
        for track in snapshot.subtitle_tracks
    }
    return TimelineConfig.model_validate(timeline.model_dump(mode="python"))


def _subtitle_states(timeline: TimelineConfig) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    tracks = {
        track.track_id: track.model_dump(mode="json", exclude={"cues"})
        for track in timeline.subtitle_tracks.values()
    }
    cues = {
        (track.track_id, cue.cue_id): cue.model_dump(mode="json")
        for track in timeline.subtitle_tracks.values()
        for cue in track.cues
    }
    return tracks, cues


def _state_map(
    timeline: TimelineConfig,
) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    snapshot = TimelineSnapshotService.snapshot(timeline)
    return {
        (track.track_key, clip.clip_id): (
            track.track_id,
            _clip_state(clip, clip.order_index),
        )
        for track in snapshot.tracks
        for clip in track.clips
    }


def review_manual_edit_proposal(
    snapshot: TimelineSnapshot,
    proposal: ManualEditProposal,
) -> ManualEditReview:
    """Review a detached multi-track proposal through production semantics."""

    if (
        snapshot.project_id != proposal.base_project_id
        or snapshot.revision != proposal.base_revision
        or snapshot.timeline_digest != proposal.base_timeline_digest
    ):
        raise ManualEditValidationError(
            "Manual proposal is stale or crosses project identity"
        )
    engine = TimelineEditEngine(_timeline_from_snapshot(snapshot))
    changes: list[ManualEditChange] = []
    for edit in proposal.edits:
        before = _state_map(engine.timeline)
        try:
            outcomes = []
            if isinstance(edit, ManualSubtitleTrack):
                before_tracks, _ = _subtitle_states(engine.timeline)
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
                after_tracks, _ = _subtitle_states(updated)
                old, new = before_tracks.get(edit.track_id), after_tracks.get(edit.track_id)
                changes.append(ManualEditChange(
                    operation_id=edit.operation_id,
                    target_kind="subtitle_track",
                    track_key=edit.track_id,
                    track_id=edit.track_id,
                    clip_id=edit.track_id,
                    action="create" if old is None else "remove" if new is None else "update",
                    before=old,
                    after=new,
                ))
                continue
            if isinstance(edit, ManualSubtitleCue):
                _, before_cues = _subtitle_states(engine.timeline)
                subtitle_engine = SubtitleEditEngine(engine.timeline)
                updated, outcome = subtitle_engine.edit_cues(SubtitleEditCueInput(
                    **edit.model_dump(mode="python", exclude={"operation_id", "kind"})
                ))
                engine.timeline = updated
                _, after_cues = _subtitle_states(updated)
                direct = set(outcome.direct_cue_ids)
                for key in sorted(before_cues.keys() | after_cues.keys()):
                    old, new = before_cues.get(key), after_cues.get(key)
                    if old == new:
                        continue
                    changes.append(ManualEditChange(
                        operation_id=edit.operation_id,
                        target_kind="subtitle_cue",
                        track_key=key[0],
                        track_id=key[0],
                        clip_id=key[1],
                        action="create" if old is None else "remove" if new is None else "update",
                        effect_kind="direct" if key[1] in direct else "consequential",
                        before=old,
                        after=new,
                    ))
                continue
            if isinstance(edit, ManualTrackMix):
                key, track = engine._resolve_track(edit.track_id)
                track_before = track.model_dump(mode="json", exclude={"clips"})
                updated, outcome = engine.set_track_mix(
                    edit.track_id,
                    gain_db=edit.gain_db,
                    muted=edit.muted,
                    pan=edit.pan,
                )
                _, changed_track = engine._resolve_track(edit.track_id)
                changes.append(
                    ManualEditChange(
                        operation_id=edit.operation_id,
                        target_kind="track",
                        track_key=key,
                        track_id=edit.track_id,
                        clip_id=edit.track_id,
                        action="update",
                        before=track_before,
                        after=changed_track.model_dump(mode="json", exclude={"clips"}),
                    )
                )
                continue
            if isinstance(edit, ManualTrackManage):
                key, track = engine._resolve_track(
                    edit.track_id,
                    allow_locked=True,
                )
                track_before = track.model_dump(
                    mode="json",
                    exclude={"clips"},
                )
                changed_properties = any(
                    value is not None
                    and value != getattr(track, field)
                    for field, value in (
                        ("role", edit.role),
                        ("enabled", edit.enabled),
                        ("muted", edit.muted),
                        ("locked", edit.locked),
                    )
                )
                updated = engine.timeline
                if changed_properties:
                    updated, outcome = engine.manage_track(
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
                    updated, outcome = engine.manage_track(
                        action="reorder",
                        track_id=edit.track_id,
                        kind=None,
                        role=None,
                        order=edit.order,
                        enabled=None,
                        muted=None,
                        locked=None,
                    )
                if not changed_properties and (
                    edit.order is None or edit.order == track.order
                ):
                    raise ManualEditValidationError(
                        "Track settings proposal changes nothing"
                    )
                _, changed_track = engine._resolve_track(
                    edit.track_id,
                    allow_locked=True,
                )
                changes.append(
                    ManualEditChange(
                        operation_id=edit.operation_id,
                        target_kind="track",
                        track_key=key,
                        track_id=edit.track_id,
                        clip_id=edit.track_id,
                        action="update",
                        before=track_before,
                        after=changed_track.model_dump(
                            mode="json",
                            exclude={"clips"},
                        ),
                    )
                )
                continue
            if isinstance(edit, ManualClipLink):
                updated, outcome = engine.set_clip_link(
                    action=edit.action,
                    members=(
                        (member.track_id, member.clip_id)
                        for member in edit.members
                    ),
                    link_group_id=edit.link_group_id,
                )
                outcomes.append(outcome)
            else:
                track_reference = edit.track_id or edit.track_key
            if isinstance(edit, ManualClipAudio):
                updated, outcome = engine.set_clip_audio(
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
                outcomes.append(outcome)
            elif isinstance(edit, ManualVolumeEnvelope):
                updated, outcome = engine.set_volume_envelope(
                    track_reference,
                    edit.clip_id,
                    action=edit.action,
                    point_id=edit.point_id,
                    offset_seconds=edit.offset_seconds,
                    gain_db=edit.gain_db,
                )
                outcomes.append(outcome)
            elif isinstance(edit, ManualClipRemove):
                updated, outcome = engine.remove(
                    track_reference,
                    edit.clip_id,
                    ripple=edit.mode == "ripple",
                    edit_scope=edit.edit_scope,
                    subtitle_ripple=edit.subtitle_ripple,
                )
                outcomes.append(outcome)
            elif isinstance(edit, ManualClipSplit):
                updated, outcome = engine.split(
                    track_reference,
                    edit.clip_id,
                    edit.split_at_seconds,
                    right_clip_id=edit.right_clip_id,
                    edit_scope=edit.edit_scope,
                )
                outcomes.append(outcome)
            elif isinstance(edit, ManualClipUpdate):
                _, _, target = engine._clip(
                    track_reference,
                    edit.clip_id,
                )
                updated = engine.timeline
                if (
                    abs(target.trim_in - edit.trim_in_seconds) > 1e-6
                    or abs(target.trim_out - edit.trim_out_seconds) > 1e-6
                ):
                    updated, outcome = engine.trim(
                        track_reference,
                        edit.clip_id,
                        edit.trim_in_seconds,
                        edit.trim_out_seconds,
                        ripple=edit.ripple,
                        edit_scope=edit.edit_scope,
                        subtitle_ripple=edit.subtitle_ripple,
                    )
                    outcomes.append(outcome)
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
                    updated, outcome = engine.move(
                        track_reference,
                        edit.clip_id,
                        edit.timeline_start_seconds,
                        ripple=False,
                        edit_scope=edit.edit_scope,
                    )
                    outcomes.append(outcome)
                if not outcomes:
                    raise ManualEditValidationError(
                        f"Update for clip {edit.clip_id!r} changes nothing"
                    )
                _, target_track = engine._resolve_track(
                    track_reference,
                    allow_locked=True,
                )
                actual_index = next(
                    index
                    for index, clip in enumerate(target_track.clips)
                    if clip.id == edit.clip_id
                )
                if edit.order_index >= len(target_track.clips):
                    raise ManualEditValidationError(
                        f"Clip order {edit.order_index} is outside the "
                        f"current track range 0..{len(target_track.clips) - 1}"
                    )
                if edit.order_index != actual_index:
                    moved = target_track.clips.pop(actual_index)
                    target_track.clips.insert(edit.order_index, moved)
        except (TimelineEditError, SubtitleEditError) as exc:
            raise ManualEditValidationError(str(exc)) from exc
        after = _state_map(updated)
        direct = {
            clip_id
            for outcome in outcomes
            for clip_id in outcome.direct_clip_ids
        }
        changed = sorted(
            before.keys() | after.keys(),
            key=lambda key: (key[1] not in direct, key),
        )
        for key in changed:
            old = before.get(key)
            new = after.get(key)
            if old == new:
                continue
            if (
                isinstance(edit, ManualClipSplit)
                and key[1] not in direct
                and old is not None
                and new is not None
                and {
                    field: value
                    for field, value in old[1].items()
                    if field != "order_index"
                }
                == {
                    field: value
                    for field, value in new[1].items()
                    if field != "order_index"
                }
            ):
                continue
            state = new or old
            assert state is not None
            changes.append(
                ManualEditChange(
                    operation_id=edit.operation_id,
                    track_key=key[0],
                    track_id=state[0],
                    clip_id=key[1],
                    action=(
                        "create"
                        if old is None
                        else "remove"
                        if new is None
                        else "update"
                    ),
                    effect_kind=(
                        "direct" if key[1] in direct else "consequential"
                    ),
                    before=None if old is None else old[1],
                    after=None if new is None else new[1],
                )
            )
    if not changes:
        raise ManualEditValidationError("Manual proposal has no effect")
    return ManualEditReview(
        proposal_ref=ManualEditProposalReference.from_proposal(proposal),
        snapshot_id=snapshot.snapshot_id,
        changes=tuple(changes),
    )


class ManualEditApplicationService:
    """Review then registry-dispatch exact confirmed user-authored proposals."""

    def __init__(
        self,
        snapshot_provider: Callable[[], TimelineSnapshot],
        registry: Mapping[str, Any],
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._registry = registry
        self._gateway = (
            AtomicExecutionGateway(registry)
            if isinstance(registry, AtomicSkillRegistry)
            else None
        )

    def _dispatch_gateway(
        self,
        request: AtomicToolRequestEnvelope,
        context: AtomicExecutionContext,
    ):
        if self._gateway is None:
            raise ManualEditValidationError(
                "The production atomic gateway is unavailable"
            )
        return self._gateway.execute(request, context)

    def review(self, proposal_value: Any) -> tuple[
        ManualEditProposal,
        ManualEditReview,
    ]:
        try:
            proposal = ManualEditProposal.model_validate(proposal_value)
        except ValidationError as exc:
            raise ManualEditValidationError(
                _validation_message(exc, "manual proposal")
            ) from exc
        review = review_manual_edit_proposal(
            self._snapshot_provider(),
            proposal,
        )
        return proposal, review

    def analyze_loudness(self, request_value: Any) -> dict[str, Any]:
        """Dispatch one read-only analysis through the production gateway."""

        if self._gateway is None:
            raise ManualEditValidationError(
                "Loudness analysis requires the production atomic registry"
            )
        snapshot = self._snapshot_provider()
        token = uuid.uuid4().hex
        request = AtomicToolRequestEnvelope(
            request_id=f"request_loudness_{token}",
            execution_id=f"execution_loudness_{token}",
            project_id=snapshot.project_id,
            confirmation_id="confirmation_read_only_analysis",
            plan_ref=PlanReference(
                plan_id="plan_read_only_analysis",
                plan_version=1,
                plan_digest=snapshot.timeline_digest,
            ),
            step_id=f"step_loudness_{token}",
            tool_name=LOUDNESS_ANALYSIS_TOOL_NAME,
            arguments=request_value,
            requested_at=datetime.now(timezone.utc),
        )
        result = self._dispatch_gateway(
            request,
            AtomicExecutionContext(
                caller="manual_edit",
                registry_ref=self._registry.reference,
                project_id=snapshot.project_id,
                confirmation_id="confirmation_read_only_analysis",
                allowed_side_effects=(),
                idempotency_key=request.request_id,
            ),
        )
        if result.status != "success" or result.payload is None:
            raise ManualEditValidationError(
                result.error.message
                if result.error is not None
                else "Loudness analysis failed"
            )
        return result.payload

    def apply(
        self,
        proposal_value: Any,
        confirmation_value: Any,
    ) -> dict[str, Any]:
        proposal, review = self.review(proposal_value)
        try:
            confirmation = ManualEditConfirmationRecord.model_validate(
                confirmation_value
            )
        except ValidationError as exc:
            raise ManualEditValidationError(
                _validation_message(exc, "manual confirmation")
            ) from exc
        if not confirmation.confirms(proposal):
            raise ManualEditValidationError(
                "Apply requires confirmation of this exact manual proposal"
            )

        skill = self._registry.get(MANUAL_EDIT_TOOL_NAME)
        if skill is None:
            raise ManualEditValidationError(
                "The manual edit atomic tool is not registered"
            )
        if getattr(skill, "name", None) != MANUAL_EDIT_TOOL_NAME:
            raise ManualEditValidationError(
                "The registered manual edit tool identity is invalid"
            )
        arguments = {
            "proposal": proposal.model_dump(mode="json"),
            "confirmation": confirmation.model_dump(mode="json"),
        }
        if self._gateway is not None:
            token = uuid.uuid4().hex
            request = AtomicToolRequestEnvelope(
                request_id=f"request_manual_{token}",
                execution_id=f"execution_manual_{token}",
                project_id=proposal.base_project_id,
                confirmation_id=confirmation.confirmation_id,
                plan_ref=PlanReference(
                    plan_id=proposal.proposal_id,
                    plan_version=1,
                    plan_digest=proposal.digest(),
                ),
                step_id=f"step_manual_{token}",
                tool_name=MANUAL_EDIT_TOOL_NAME,
                arguments=arguments,
                requested_at=datetime.now(timezone.utc),
            )
            gateway_result = self._dispatch_gateway(
                request,
                AtomicExecutionContext(
                    caller="manual_edit",
                    registry_ref=self._registry.reference,
                    project_id=proposal.base_project_id,
                    confirmation_id=confirmation.confirmation_id,
                    allowed_side_effects=("files", "timeline"),
                    idempotency_key=request.request_id,
                ),
            )
            if gateway_result.status != "success":
                raise ManualEditValidationError(
                    gateway_result.error.message
                    if gateway_result.error is not None
                    else "Manual edit atomic dispatch failed"
                )
            result = gateway_result.payload
        else:
            result = skill.execute(arguments)
        applied_snapshot = self._snapshot_provider()
        return {
            "schema_name": "vistora.manual-edit-application",
            "schema_version": "1.0.0",
            "application_id": f"application_{uuid.uuid4().hex}",
            "proposal_ref": review.proposal_ref.model_dump(mode="json"),
            "confirmation_id": confirmation.confirmation_id,
            "tool_name": MANUAL_EDIT_TOOL_NAME,
            "tool_result": result,
            "snapshot": applied_snapshot.model_dump(mode="json"),
        }
