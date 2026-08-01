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
    ClipSnapshot,
    MediaSourceReference,
    TimelineSnapshot,
    TimelineSnapshotReference,
    TrackSnapshot,
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
    effective_duration = declared_source_duration / speed_factor
    timeline_end = timeline_start + effective_duration
    source_digest = _sha256({"configured_path": source_value})

    return ClipSnapshot(
        clip_id=clip_id,
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
        rotate_degrees=clip.rotate,
        link_group_id=clip.link_group_id,
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
                        clips=clips,
                        clip_count=len(clips),
                        duration_seconds=max(0.0, duration),
                    )
                )

            tracks = tuple(track_snapshots)
            timeline_payload = project.timeline.model_dump(mode="json")
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
                track_count=len(tracks),
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
                    (track.duration_seconds for track in tracks),
                    default=0.0,
                ),
                empty=clip_count == 0,
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
