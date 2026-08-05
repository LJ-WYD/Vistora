"""Pure snapshot construction plus a read-only current-project adapter."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from contracts import TimelineProjectDocument
from core.timeline import ClipConfig, TimelineConfig
from core.timeline_manager import TimelineManager as _TimelineManager

from .models import (
    AudioDuckingSnapshot,
    ClipColorSnapshot,
    ClipSnapshot,
    VisualAutomationSnapshot,
    VisualKeyframeSnapshot,
    ClipMaskSnapshot,
    ClipCompositeSnapshot,
    MaskAutomationSnapshot,
    MaskPointSnapshot,
    ClipTransformSnapshot,
    MediaSourceReference,
    TimelineSnapshot,
    TimelineSnapshotReference,
    TrackSnapshot,
    TransitionSnapshot,
    SubtitleCueSnapshot,
    SubtitleStyleSnapshot,
    SubtitleTrackSnapshot,
    SubtitleWordSnapshot,
)

if TYPE_CHECKING:
    from traceability.models import TimelineTraceDocument


class TimelineSnapshotError(ValueError):
    """The supplied timeline cannot be represented safely as a snapshot."""


class TimelineSnapshotReferenceError(TimelineSnapshotError):
    """A requested project/revision or configured source reference is invalid."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    encoded = _canonical_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _display_name(source: str) -> str:
    normalized = source.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or source


def _track_sort_key(item: tuple[str, Any]) -> tuple[int, str, str]:
    key, track = item
    return track.order, track.id, key


def _finite(value: float, field: str, clip_id: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise TimelineSnapshotError(
            f"Clip {clip_id!r} has non-finite {field}: {value!r}"
        )
    return result


def _clip_snapshot(clip: ClipConfig, order_index: int) -> ClipSnapshot:
    clip_id = clip.id
    if not clip_id.strip():
        raise TimelineSnapshotReferenceError(
            "Timeline contains a clip with an empty ID"
        )

    source_value = clip.source
    if not source_value.strip():
        raise TimelineSnapshotReferenceError(
            f"Clip {clip_id!r} has an empty source reference"
        )

    trim_in = _finite(clip.trim_in, "trim_in", clip_id)
    trim_out = _finite(clip.trim_out, "trim_out", clip_id)
    timeline_start = _finite(
        clip.timeline_start,
        "timeline_start",
        clip_id,
    )
    speed_factor = _finite(clip.speed_factor, "speed_factor", clip_id)
    volume = (
        None
        if clip.volume is None
        else _finite(clip.volume, "volume", clip_id)
    )
    if trim_out < trim_in:
        raise TimelineSnapshotError(
            f"Clip {clip_id!r} has trim_out before trim_in"
        )
    if speed_factor <= 0:
        raise TimelineSnapshotError(
            f"Clip {clip_id!r} has a non-positive speed_factor"
        )

    declared_source_duration = trim_out - trim_in
    effective_duration = (
        clip.freeze_frame.duration_seconds
        if clip.freeze_frame is not None
        else declared_source_duration / speed_factor
    )
    timeline_end = timeline_start + effective_duration
    source_digest = _sha256({"configured_path": source_value})

    automation_payload = [
        item.model_dump(mode="json") for item in clip.visual_automations
    ]
    automation_digest = "sha256:" + _sha256(automation_payload)
    mask_payload = [item.model_dump(mode="json") for item in clip.masks]
    mask_digest = "sha256:" + _sha256(
        {"masks": mask_payload, "composite": clip.composite.model_dump(mode="json")}
    )
    return ClipSnapshot(
        clip_id=clip_id,
        visual_kind=clip.visual_kind,
        order_index=order_index,
        source=MediaSourceReference(
            source_id=f"source_{source_digest[:16]}",
            value=source_value,
            display_name=_display_name(source_value),
        ),
        trim_in_seconds=trim_in,
        trim_out_seconds=trim_out,
        declared_source_duration_seconds=declared_source_duration,
        speed_factor=speed_factor,
        timeline_start_seconds=timeline_start,
        timeline_end_seconds=timeline_end,
        effective_duration_seconds=effective_duration,
        volume=volume,
        keep_audio=clip.keep_audio,
        reverse=clip.reverse,
        freeze_frame_source_time_seconds=(
            clip.freeze_frame.source_time_seconds
            if clip.freeze_frame is not None
            else None
        ),
        freeze_frame_duration_seconds=(
            clip.freeze_frame.duration_seconds
            if clip.freeze_frame is not None
            else None
        ),
        rotate_degrees=clip.rotate,
        link_group_id=clip.link_group_id,
        audio_gain_db=clip.audio.gain_db,
        audio_content_role=clip.audio.content_role,
        audio_muted=clip.audio.muted,
        audio_pan=clip.audio.pan,
        audio_fade_in_seconds=clip.audio.fade_in_seconds,
        audio_fade_out_seconds=clip.audio.fade_out_seconds,
        audio_envelope=tuple(
            (point.point_id, point.offset_seconds, point.gain_db)
            for point in clip.audio.envelope
        ),
        loudness_analysis_id=(
            clip.audio.normalization.analysis_id
            if clip.audio.normalization is not None
            else None
        ),
        audio_ducking=(
            AudioDuckingSnapshot.model_validate(
                clip.audio.ducking.model_dump(
                    mode="python", exclude={"schema_name", "schema_version"}
                )
            )
            if clip.audio.ducking is not None
            else None
        ),
        transform=ClipTransformSnapshot.model_validate(
            clip.transform.model_dump(
                mode="python", exclude={"schema_name", "schema_version"}
            )
        ),
        color=ClipColorSnapshot.model_validate(
            clip.color.model_dump(
                mode="python", exclude={"schema_name", "schema_version"}
            )
        ),
        visual_automations=tuple(
            VisualAutomationSnapshot(
                automation_id=automation.automation_id,
                clip_id=automation.clip_id,
                property_path=automation.property_path,
                enabled=automation.enabled,
                keyframes=tuple(
                    VisualKeyframeSnapshot(
                        keyframe_id=point.keyframe_id,
                        offset_seconds=point.offset_seconds,
                        value=point.value,
                        interpolation=point.interpolation,
                    )
                    for point in automation.keyframes
                ),
                automation_digest="sha256:" + _sha256(
                    automation.model_dump(mode="json")
                ),
            )
            for automation in clip.visual_automations
        ),
        masks=tuple(
            ClipMaskSnapshot(
                mask_id=mask.mask_id,
                kind=mask.kind,
                operation=mask.operation,
                enabled=mask.enabled,
                invert=mask.invert,
                opacity=mask.opacity,
                feather=mask.feather,
                expand=mask.expand,
                position_x=mask.position_x,
                position_y=mask.position_y,
                scale_x=mask.scale_x,
                scale_y=mask.scale_y,
                rotation_degrees=mask.rotation_degrees,
                width=mask.width,
                height=mask.height,
                points=tuple(MaskPointSnapshot(point_id=point.point_id, x=point.x, y=point.y) for point in mask.points),
                automations=tuple(
                    MaskAutomationSnapshot(
                        automation_id=curve.automation_id,
                        mask_id=curve.mask_id,
                        property_path=curve.property_path,
                        enabled=curve.enabled,
                        keyframes=tuple(
                            VisualKeyframeSnapshot(
                                keyframe_id=point.keyframe_id,
                                offset_seconds=point.offset_seconds,
                                value=point.value,
                                interpolation=point.interpolation,
                            ) for point in curve.keyframes
                        ),
                    ) for curve in mask.automations
                ),
            ) for mask in clip.masks
        ),
        composite=ClipCompositeSnapshot(blend_mode=clip.composite.blend_mode),
        mask_digest=mask_digest,
        automation_digest=automation_digest,
        visual_digest=(
            "sha256:"
            + _sha256(
                {
                    "transform": clip.transform.model_dump(mode="json"),
                    "color": clip.color.model_dump(mode="json"),
                    "visual_automations": automation_payload,
                    "masks": mask_payload,
                    "composite": clip.composite.model_dump(mode="json"),
                }
            )
        ),
    )


class TimelineSnapshotService:
    """Build detached timeline snapshots without persistence or media writes."""

    @staticmethod
    def snapshot(
        source: TimelineConfig | TimelineProjectDocument | Mapping[str, Any],
        *,
        expected_reference: TimelineSnapshotReference | None = None,
        trace_document: TimelineTraceDocument | None = None,
    ) -> TimelineSnapshot:
        try:
            project = TimelineProjectDocument.model_validate(source)
        except (TypeError, ValueError, ValidationError) as exc:
            raise TimelineSnapshotError(
                f"Invalid timeline project input: {exc}"
            ) from exc

        if expected_reference is not None:
            if project.project_id != expected_reference.project_id:
                raise TimelineSnapshotReferenceError(
                    "Project reference mismatch: expected "
                    f"{expected_reference.project_id!r}, received "
                    f"{project.project_id!r}"
                )
            if project.revision != expected_reference.revision:
                raise TimelineSnapshotReferenceError(
                    "Project revision mismatch: expected "
                    f"{expected_reference.revision}, received "
                    f"{project.revision}"
                )

        try:
            track_snapshots: list[TrackSnapshot] = []
            for track_index, (track_key, track) in enumerate(
                sorted(project.timeline.tracks.items(), key=_track_sort_key)
            ):
                normalized_key = track_key
                if not normalized_key.strip():
                    raise TimelineSnapshotReferenceError(
                        "Timeline contains an empty track key"
                    )
                track_id = track.id
                if not track_id.strip():
                    raise TimelineSnapshotReferenceError(
                        f"Track {normalized_key!r} has an empty ID"
                    )
                clips = tuple(
                    _clip_snapshot(clip, clip_index)
                    for clip_index, clip in enumerate(track.clips)
                )
                duration = max(
                    (clip.timeline_end_seconds for clip in clips),
                    default=0.0,
                )
                track_snapshots.append(
                    TrackSnapshot(
                        track_key=normalized_key,
                        track_id=track_id,
                        kind=track.kind,
                        role=track.role,
                        order_index=track_index,
                        enabled=track.enabled,
                        muted=track.muted,
                        locked=track.locked,
                        mix_gain_db=track.mix.gain_db,
                        mix_muted=track.mix.muted,
                        mix_pan=track.mix.pan,
                        clips=clips,
                        clip_count=len(clips),
                        duration_seconds=max(0.0, duration),
                    )
                )

            tracks = tuple(track_snapshots)
            subtitle_track_snapshots = tuple(
                SubtitleTrackSnapshot(
                    track_key=track_key,
                    track_id=track.track_id,
                    kind=track.kind,
                    role=track.role,
                    language=track.language,
                    order_index=index,
                    enabled=track.enabled,
                    locked=track.locked,
                    allow_overlaps=track.allow_overlaps,
                    style=SubtitleStyleSnapshot.model_validate(
                        track.style.model_dump(
                            mode="python",
                            exclude={"schema_name", "schema_version"},
                        )
                    ),
                    cues=tuple(
                        SubtitleCueSnapshot(
                            cue_id=cue.cue_id,
                            cue_kind=cue.cue_kind,
                            order_index=cue_index,
                            start_seconds=cue.start_seconds,
                            end_seconds=cue.end_seconds,
                            duration_seconds=cue.end_seconds - cue.start_seconds,
                            text=cue.text,
                            language=cue.language,
                            speaker=cue.speaker,
                            enabled=cue.enabled,
                            settings=cue.settings,
                            style=(
                                SubtitleStyleSnapshot.model_validate(
                                    cue.style.model_dump(
                                        mode="python",
                                        exclude={"schema_name", "schema_version"},
                                    )
                                )
                                if cue.style is not None
                                else None
                            ),
                            words=tuple(
                                SubtitleWordSnapshot(
                                    word_id=word.word_id,
                                    start_seconds=word.start_seconds,
                                    end_seconds=word.end_seconds,
                                    text=word.text,
                                    confidence=word.confidence,
                                )
                                for word in cue.words
                            ),
                            word_count=len(cue.words),
                        )
                        for cue_index, cue in enumerate(track.cues)
                    ),
                    cue_count=len(track.cues),
                    duration_seconds=max(
                        (cue.end_seconds for cue in track.cues),
                        default=0.0,
                    ),
                )
                for index, (track_key, track) in enumerate(
                    sorted(
                        project.timeline.subtitle_tracks.items(),
                        key=lambda item: (item[1].order, item[1].track_id, item[0]),
                    )
                )
            )
            timeline_payload = project.timeline.model_dump(mode="json")
            transition_snapshots = tuple(
                TransitionSnapshot(
                    transition_id=transition.transition_id,
                    track_id=transition.track_id,
                    from_clip_id=transition.from_clip_id,
                    to_clip_id=transition.to_clip_id,
                    media_type=transition.media_type,
                    kind=transition.kind,
                    duration_seconds=transition.duration_seconds,
                    alignment=transition.alignment,
                    direction=transition.parameters.direction,
                    color=transition.parameters.color,
                    enabled=transition.enabled,
                    audio_policy=transition.audio_policy,
                    paired_transition_id=transition.paired_transition_id,
                )
                for transition in sorted(
                    project.timeline.transitions.values(),
                    key=lambda item: (
                        item.track_id,
                        item.from_clip_id,
                        item.to_clip_id,
                        item.media_type,
                        item.transition_id,
                    ),
                )
            )
            timeline_hash = _sha256(timeline_payload)
            snapshot_hash = _sha256(
                {
                    "project_id": project.project_id,
                    "revision": project.revision,
                    "timeline_digest": timeline_hash,
                }
            )
            clip_count = sum(track.clip_count for track in tracks)

            snapshot = TimelineSnapshot(
                snapshot_id=f"snapshot_{snapshot_hash[:16]}",
                project_id=project.project_id,
                revision=project.revision,
                migration_source=project.migration_source,
                timeline_digest=f"sha256:{timeline_hash}",
                width=project.timeline.width,
                height=project.timeline.height,
                fps=project.timeline.fps,
                tracks=tracks,
                subtitle_tracks=subtitle_track_snapshots,
                transitions=transition_snapshots,
                track_count=len(tracks),
                subtitle_track_count=len(subtitle_track_snapshots),
                subtitle_cue_count=sum(
                    track.cue_count for track in subtitle_track_snapshots
                ),
                transition_count=len(transition_snapshots),
                clip_count=clip_count,
                video_clip_count=sum(
                    track.clip_count
                    for track in tracks
                    if track.kind == "video"
                ),
                audio_clip_count=sum(
                    track.clip_count
                    for track in tracks
                    if track.kind == "audio"
                ),
                duration_seconds=max(
                    (
                        track.duration_seconds
                        for track in (*tracks, *subtitle_track_snapshots)
                    ),
                    default=0.0,
                ),
                empty=(
                    clip_count == 0
                    and not any(
                        track.cue_count for track in subtitle_track_snapshots
                    )
                ),
            )
            if expected_reference is not None:
                if (
                    expected_reference.snapshot_id is not None
                    and expected_reference.snapshot_id
                    != snapshot.snapshot_id
                ):
                    raise TimelineSnapshotReferenceError(
                        "Snapshot identity mismatch"
                    )
                if (
                    expected_reference.timeline_digest is not None
                    and expected_reference.timeline_digest
                    != snapshot.timeline_digest
                ):
                    raise TimelineSnapshotReferenceError(
                        "Timeline digest mismatch"
                    )
            if trace_document is None:
                from traceability.models import TimelineTraceDocument

                trace_document = TimelineTraceDocument()
            from traceability.query import TraceabilityQuery

            query = TraceabilityQuery(trace_document, snapshot)
            traced_tracks = tuple(
                track.model_copy(
                    update={
                        "clips": tuple(
                            clip.model_copy(
                                update={
                                    "provenance": query.clip_to_trace(
                                        track.track_key,
                                        clip.clip_id,
                                    ).provenance
                                }
                            )
                            for clip in track.clips
                        )
                    }
                )
                for track in snapshot.tracks
            )
            return snapshot.model_copy(
                update={
                    "tracks": traced_tracks,
                    "orphaned_provenance": query.orphaned_clips(),
                }
            )
        except TimelineSnapshotError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise TimelineSnapshotError(
                f"Timeline cannot be represented as a snapshot: {exc}"
            ) from exc

    @staticmethod
    def snapshot_current(
        *,
        expected_reference: TimelineSnapshotReference | None = None,
    ) -> TimelineSnapshot:
        """Read current legacy state; this never creates or saves a project."""

        from traceability.store import TraceabilityStore

        return TimelineSnapshotService.snapshot(
            _TimelineManager.get_current_timeline(),
            expected_reference=expected_reference,
            trace_document=TraceabilityStore.load(),
        )

    @staticmethod
    def source_id_for_configured_path(source: str) -> str:
        """Return the same opaque material identity used in snapshots."""

        if not source.strip():
            raise TimelineSnapshotReferenceError(
                "Configured source reference cannot be empty"
            )
        return f"source_{_sha256({'configured_path': source})[:16]}"
