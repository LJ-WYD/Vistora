"""Pure deterministic multi-track editing over detached TimelineConfig copies."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Iterable

from core.timeline import (
    AppliedLoudnessNormalization,
    AudioEnvelopePoint,
    ClipAudioSettings,
    ClipConfig,
    TimelineConfig,
    TrackConfig,
    TrackMixSettings,
)

from .models import TimelineEditOutcome


TIME_EPSILON = 1e-6
IdFactory = Callable[[str], str]


class TimelineEditError(ValueError):
    pass


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def clip_duration(clip: ClipConfig) -> float:
    return (clip.trim_out - clip.trim_in) / clip.speed_factor


def clip_end(clip: ClipConfig) -> float:
    return clip.timeline_start + clip_duration(clip)


class TimelineEditEngine:
    """One source of truth for execution and detached plan simulation."""

    def __init__(
        self,
        timeline: TimelineConfig,
        *,
        id_factory: IdFactory = _random_id,
    ) -> None:
        self.timeline = TimelineConfig.model_validate(
            timeline.model_dump(mode="python")
        )
        self.id_factory = id_factory
        self._sort_all()
        self.validate(self.timeline)

    @staticmethod
    def validate(timeline: TimelineConfig) -> None:
        all_ids: list[str] = []
        track_ids: list[str] = []
        orders: list[int] = []
        for track_key, track in timeline.tracks.items():
            if not track_key.strip() or not track.id.strip():
                raise TimelineEditError("Track keys and IDs cannot be empty")
            if track.kind not in {"video", "audio"}:
                raise TimelineEditError(
                    f"Track {track.id} has an unsupported media kind"
                )
            track_ids.append(track.id)
            orders.append(track.order)
            for clip in track.clips:
                try:
                    ClipConfig.model_validate(clip.model_dump(mode="python"))
                except ValueError as exc:
                    raise TimelineEditError(
                        f"Clip {clip.id} violates its versioned model: {exc}"
                    ) from exc
                all_ids.append(clip.id)
                values = (
                    clip.trim_in,
                    clip.trim_out,
                    clip.timeline_start,
                    clip.speed_factor,
                )
                if not all(math.isfinite(value) for value in values):
                    raise TimelineEditError("Clip timing must be finite")
                if clip.trim_in < 0 or clip.trim_out <= clip.trim_in:
                    raise TimelineEditError(
                        f"Clip {clip.id} has an invalid source range"
                    )
                if clip.timeline_start < 0 or clip.speed_factor <= 0:
                    raise TimelineEditError(
                        f"Clip {clip.id} has invalid playback timing"
                    )
                if clip_duration(clip) <= TIME_EPSILON:
                    raise TimelineEditError(
                        f"Clip {clip.id} has zero effective duration"
                    )
            expected = sorted(
                track.clips,
                key=lambda item: (item.timeline_start, item.id),
            )
            if track.clips != expected:
                raise TimelineEditError(
                    f"Track {track.id} clips are not deterministically sorted"
                )
        if len(track_ids) != len(set(track_ids)):
            raise TimelineEditError("Track IDs must be unique")
        if len(orders) != len(set(orders)):
            raise TimelineEditError("Track order values must be unique")
        if len(all_ids) != len(set(all_ids)):
            raise TimelineEditError("Clip IDs must be unique across tracks")

    def _sort_all(self) -> None:
        for track in self.timeline.tracks.values():
            track.clips.sort(
                key=lambda item: (item.timeline_start, item.id)
            )

    @staticmethod
    def _gain_at(
        points: tuple[AudioEnvelopePoint, ...], offset: float
    ) -> float:
        if not points:
            return 0.0
        if offset <= points[0].offset_seconds:
            return points[0].gain_db
        for left, right in zip(points, points[1:]):
            if offset <= right.offset_seconds:
                ratio = (
                    (offset - left.offset_seconds)
                    / (right.offset_seconds - left.offset_seconds)
                )
                return left.gain_db + ratio * (right.gain_db - left.gain_db)
        return points[-1].gain_db

    def _split_audio(
        self,
        settings: ClipAudioSettings,
        split_offset: float,
        total_duration: float,
    ) -> tuple[ClipAudioSettings, ClipAudioSettings]:
        boundary_gain = self._gain_at(settings.envelope, split_offset)
        left_points = [
            point for point in settings.envelope
            if point.offset_seconds < split_offset - TIME_EPSILON
        ]
        right_points = [
            point.model_copy(
                update={"offset_seconds": point.offset_seconds - split_offset}
            )
            for point in settings.envelope
            if point.offset_seconds > split_offset + TIME_EPSILON
        ]
        if settings.envelope:
            exact = next(
                (
                    point for point in settings.envelope
                    if abs(point.offset_seconds - split_offset) <= TIME_EPSILON
                ),
                None,
            )
            left_points.append(
                (exact or AudioEnvelopePoint(
                    point_id=self.id_factory("envelope"),
                    offset_seconds=split_offset,
                    gain_db=boundary_gain,
                )).model_copy(update={"offset_seconds": split_offset})
            )
            right_points.insert(
                0,
                AudioEnvelopePoint(
                    point_id=self.id_factory("envelope"),
                    offset_seconds=0,
                    gain_db=boundary_gain,
                ),
            )
        right_duration = total_duration - split_offset
        left = settings.model_copy(
            update={
                "fade_in_seconds": min(settings.fade_in_seconds, split_offset),
                "fade_out_seconds": 0.0,
                "envelope": tuple(left_points),
            }
        )
        right = settings.model_copy(
            update={
                "fade_in_seconds": 0.0,
                "fade_out_seconds": min(settings.fade_out_seconds, right_duration),
                "envelope": tuple(right_points),
            }
        )
        return left, right

    def _trim_audio(
        self,
        settings: ClipAudioSettings,
        *,
        removed_start: float,
        new_duration: float,
        removed_end: float,
    ) -> ClipAudioSettings:
        points = [
            point.model_copy(
                update={
                    "offset_seconds": point.offset_seconds - removed_start
                }
            )
            for point in settings.envelope
            if (
                point.offset_seconds >= removed_start - TIME_EPSILON
                and point.offset_seconds
                <= removed_start + new_duration + TIME_EPSILON
            )
        ]
        points.sort(key=lambda point: (point.offset_seconds, point.point_id))
        return settings.model_copy(
            update={
                "fade_in_seconds": min(
                    new_duration,
                    max(0.0, settings.fade_in_seconds - removed_start),
                ),
                "fade_out_seconds": min(
                    new_duration,
                    max(0.0, settings.fade_out_seconds - removed_end),
                ),
                "envelope": tuple(points),
            }
        )

    def _resolve_track(
        self,
        track_reference: str,
        *,
        allow_locked: bool = False,
    ) -> tuple[str, TrackConfig]:
        exact = [
            (key, track)
            for key, track in self.timeline.tracks.items()
            if track.id == track_reference
        ]
        if len(exact) == 1:
            key, track = exact[0]
        elif not exact and track_reference in self.timeline.tracks:
            # Explicit legacy compatibility: dictionary key addressing.
            key = track_reference
            track = self.timeline.tracks[key]
        else:
            raise TimelineEditError(
                f"track_id {track_reference!r} must identify exactly one track"
            )
        if track.locked and not allow_locked:
            raise TimelineEditError(f"Track {track.id!r} is locked")
        return key, track

    def track_kind(self, track_reference: str) -> str:
        """Read-only exact track kind lookup for validated skill adapters."""

        return self._resolve_track(
            track_reference,
            allow_locked=True,
        )[1].kind

    def clip_state(
        self, track_reference: str, clip_id: str
    ) -> tuple[str, TrackConfig, ClipConfig]:
        """Read an exact detached clip for adapters without exposing mutation."""

        return self._clip(track_reference, clip_id)

    def _clip(
        self,
        track_reference: str,
        clip_id: str,
    ) -> tuple[str, TrackConfig, ClipConfig]:
        key, track = self._resolve_track(track_reference)
        matches = [clip for clip in track.clips if clip.id == clip_id]
        if len(matches) != 1:
            raise TimelineEditError(
                f"clip_id {clip_id!r} must identify exactly one clip "
                f"on track {track.id!r}"
            )
        return key, track, matches[0]

    def _linked_members(
        self,
        track_reference: str,
        clip_id: str,
        edit_scope: str,
    ) -> list[tuple[str, TrackConfig, ClipConfig]]:
        target = self._clip(track_reference, clip_id)
        if edit_scope == "current_clip":
            return [target]
        if edit_scope != "linked_group":
            raise TimelineEditError("Unknown edit scope")
        group_id = target[2].link_group_id
        if group_id is None:
            raise TimelineEditError("Target clip has no explicit link group")
        members: list[tuple[str, TrackConfig, ClipConfig]] = []
        for key, track in self.timeline.tracks.items():
            for clip in track.clips:
                if clip.link_group_id == group_id:
                    if track.locked:
                        raise TimelineEditError(
                            f"Linked track {track.id!r} is locked"
                        )
                    members.append((key, track, clip))
        if len(members) < 2:
            raise TimelineEditError(
                "Linked edit requires at least two extant group members"
            )
        return sorted(
            members,
            key=lambda item: (
                item[1].order,
                item[1].id,
                item[2].timeline_start,
                item[2].id,
            ),
        )

    def _finish(
        self,
        *,
        operation: str,
        primary_key: str,
        primary_track: TrackConfig,
        direct: Iterable[str],
        consequential: Iterable[str] = (),
        created: Iterable[str] = (),
        modified: Iterable[str] = (),
        deleted: Iterable[str] = (),
        warnings: Iterable[str] = (),
    ) -> tuple[TimelineConfig, TimelineEditOutcome]:
        self._sort_all()
        self.validate(self.timeline)
        return self.timeline, TimelineEditOutcome(
            operation=operation,
            track_id=primary_track.id,
            track_key=primary_key,
            direct_clip_ids=tuple(dict.fromkeys(direct)),
            consequential_clip_ids=tuple(sorted(set(consequential))),
            created_clip_ids=tuple(dict.fromkeys(created)),
            modified_clip_ids=tuple(sorted(set(modified))),
            deleted_clip_ids=tuple(sorted(set(deleted))),
            warnings=tuple(warnings),
        )

    def split(
        self,
        track_reference: str,
        clip_id: str,
        split_at: float,
        *,
        right_clip_id: str | None = None,
        edit_scope: str = "current_clip",
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        for _, _, clip in members:
            if (
                split_at <= clip.timeline_start + TIME_EPSILON
                or split_at >= clip_end(clip) - TIME_EPSILON
            ):
                raise TimelineEditError(
                    "Split point must be inside every affected linked clip"
                )
        right_group_id = (
            self.id_factory("link")
            if edit_scope == "linked_group"
            else target[2].link_group_id
        )
        created: list[str] = []
        modified: list[str] = []
        consequential: list[str] = []
        direct: list[str] = [clip_id]
        for key, track, clip in members:
            new_id = (
                right_clip_id
                if clip.id == clip_id and right_clip_id is not None
                else self.id_factory("clip")
            )
            if any(
                new_id == current.id
                for candidate in self.timeline.tracks.values()
                for current in candidate.clips
            ):
                raise TimelineEditError("Split output clip ID already exists")
            source_split = clip.trim_in + (
                split_at - clip.timeline_start
            ) * clip.speed_factor
            original_out = clip.trim_out
            original_duration = clip_duration(clip)
            split_offset = split_at - clip.timeline_start
            left_audio, right_audio = self._split_audio(
                clip.audio, split_offset, original_duration
            )
            clip.trim_out = source_split
            clip.audio = left_audio
            right = clip.model_copy(deep=True)
            right.id = new_id
            right.trim_in = source_split
            right.trim_out = original_out
            right.timeline_start = split_at
            right.audio = right_audio
            right.link_group_id = right_group_id
            track.clips.append(right)
            created.append(new_id)
            modified.append(clip.id)
            if clip.id == clip_id:
                direct.append(new_id)
            else:
                consequential.extend((clip.id, new_id))
        return self._finish(
            operation="split",
            primary_key=target[0],
            primary_track=target[1],
            direct=direct,
            consequential=consequential,
            created=created,
            modified=modified,
        )

    def trim(
        self,
        track_reference: str,
        clip_id: str,
        trim_in: float,
        trim_out: float,
        *,
        ripple: bool,
        edit_scope: str = "current_clip",
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        target_clip = target[2]
        if trim_out <= trim_in + TIME_EPSILON:
            raise TimelineEditError("Trim must retain positive source duration")
        if (
            trim_in < target_clip.trim_in - TIME_EPSILON
            or trim_out > target_clip.trim_out + TIME_EPSILON
        ):
            raise TimelineEditError(
                "Trim may only narrow the current source range"
            )
        if (
            abs(trim_in - target_clip.trim_in) <= TIME_EPSILON
            and abs(trim_out - target_clip.trim_out) <= TIME_EPSILON
        ):
            raise TimelineEditError("Trim does not change the clip range")
        left_delta_seconds = (
            trim_in - target_clip.trim_in
        ) / target_clip.speed_factor
        right_delta_seconds = (
            target_clip.trim_out - trim_out
        ) / target_clip.speed_factor
        affected_ids = {clip.id for _, _, clip in members}
        modified: list[str] = []
        consequential: list[str] = []
        ripple_specs: list[tuple[TrackConfig, float, float]] = []
        for _, track, clip in members:
            old_end = clip_end(clip)
            old_duration = clip_duration(clip)
            next_in = clip.trim_in + left_delta_seconds * clip.speed_factor
            next_out = clip.trim_out - right_delta_seconds * clip.speed_factor
            if next_out <= next_in + TIME_EPSILON:
                raise TimelineEditError(
                    "Linked trim would create a zero-length member"
                )
            clip.trim_in = next_in
            clip.trim_out = next_out
            clip.audio = self._trim_audio(
                clip.audio,
                removed_start=left_delta_seconds,
                new_duration=clip_duration(clip),
                removed_end=right_delta_seconds,
            )
            delta = clip_duration(clip) - old_duration
            ripple_specs.append((track, old_end, delta))
            modified.append(clip.id)
            if clip.id != clip_id:
                consequential.append(clip.id)
        if ripple:
            for track, old_end, delta in ripple_specs:
                if abs(delta) <= TIME_EPSILON:
                    continue
                for other in track.clips:
                    if (
                        other.id not in affected_ids
                        and other.timeline_start >= old_end - TIME_EPSILON
                    ):
                        other.timeline_start = max(
                            0.0, other.timeline_start + delta
                        )
                        modified.append(other.id)
                        consequential.append(other.id)
        return self._finish(
            operation="trim",
            primary_key=target[0],
            primary_track=target[1],
            direct=(clip_id,),
            consequential=consequential,
            modified=modified,
        )

    def move(
        self,
        track_reference: str,
        clip_id: str,
        timeline_start: float,
        *,
        ripple: bool,
        edit_scope: str = "current_clip",
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        target_clip = target[2]
        if timeline_start < 0:
            raise TimelineEditError("Timeline start cannot be negative")
        delta = timeline_start - target_clip.timeline_start
        if abs(delta) <= TIME_EPSILON:
            raise TimelineEditError("Move does not change clip position")
        if any(
            clip.timeline_start + delta < -TIME_EPSILON
            for _, _, clip in members
        ):
            raise TimelineEditError(
                "Linked move would place a member before zero"
            )
        affected_ids = {clip.id for _, _, clip in members}
        modified = list(affected_ids)
        consequential = [
            clip.id for _, _, clip in members if clip.id != clip_id
        ]
        if ripple:
            for _, track, clip in members:
                duration = clip_duration(clip)
                old_end = clip_end(clip)
                for other in track.clips:
                    if other.id in affected_ids:
                        continue
                    if other.timeline_start >= old_end - TIME_EPSILON:
                        other.timeline_start = max(
                            0.0, other.timeline_start - duration
                        )
                        modified.append(other.id)
                        consequential.append(other.id)
                insertion = clip.timeline_start + delta
                for other in track.clips:
                    if (
                        other.id not in affected_ids
                        and other.timeline_start >= insertion - TIME_EPSILON
                    ):
                        other.timeline_start += duration
                        modified.append(other.id)
                        consequential.append(other.id)
        for _, _, clip in members:
            clip.timeline_start += delta
        return self._finish(
            operation="move",
            primary_key=target[0],
            primary_track=target[1],
            direct=(clip_id,),
            consequential=consequential,
            modified=modified,
            warnings=(
                ("Non-ripple move may intentionally overlap clips.",)
                if not ripple else ()
            ),
        )

    def remove(
        self,
        track_reference: str,
        clip_id: str,
        *,
        ripple: bool,
        edit_scope: str = "current_clip",
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        affected_ids = {clip.id for _, _, clip in members}
        deleted: list[str] = []
        modified: list[str] = []
        consequential: list[str] = []
        for _, track, clip in members:
            end = clip_end(clip)
            duration = clip_duration(clip)
            track.clips.remove(clip)
            deleted.append(clip.id)
            if clip.id != clip_id:
                consequential.append(clip.id)
            if ripple:
                for other in track.clips:
                    if (
                        other.id not in affected_ids
                        and other.timeline_start >= end - TIME_EPSILON
                    ):
                        other.timeline_start = max(
                            0.0, other.timeline_start - duration
                        )
                        modified.append(other.id)
                        consequential.append(other.id)
        return self._finish(
            operation="remove",
            primary_key=target[0],
            primary_track=target[1],
            direct=(clip_id,),
            consequential=consequential,
            modified=modified,
            deleted=deleted,
        )

    def insert_overwrite(
        self,
        track_reference: str,
        clip: ClipConfig,
        *,
        mode: str,
        edit_scope: str = "current_clip",
    ):
        key, track = self._resolve_track(track_reference)
        if edit_scope == "linked_group" and clip.link_group_id is None:
            raise TimelineEditError(
                "Linked insertion requires an explicit link_group_id"
            )
        if any(
            clip.id == item.id
            for current in self.timeline.tracks.values()
            for item in current.clips
        ):
            raise TimelineEditError("Inserted clip ID already exists")
        start = clip.timeline_start
        end = clip_end(clip)
        duration = clip_duration(clip)
        created = [clip.id]
        derived_created: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []
        consequential: list[str] = []
        if mode == "insert":
            replacements: list[ClipConfig] = []
            for other in list(track.clips):
                if other.timeline_start >= start - TIME_EPSILON:
                    other.timeline_start += duration
                    modified.append(other.id)
                    consequential.append(other.id)
                    continue
                other_end = clip_end(other)
                if (
                    other.timeline_start + TIME_EPSILON
                    < start
                    < other_end - TIME_EPSILON
                ):
                    source_split = other.trim_in + (
                        start - other.timeline_start
                    ) * other.speed_factor
                    original_out = other.trim_out
                    other.trim_out = source_split
                    right = other.model_copy(deep=True)
                    right.id = self.id_factory("clip")
                    right.trim_in = source_split
                    right.trim_out = original_out
                    right.timeline_start = start + duration
                    replacements.append(right)
                    modified.append(other.id)
                    created.append(right.id)
                    derived_created.append(right.id)
                    consequential.extend((other.id, right.id))
            track.clips.extend(replacements)
        elif mode == "overwrite":
            replacements: list[ClipConfig] = []
            for other in list(track.clips):
                other_start, other_end = other.timeline_start, clip_end(other)
                if (
                    other_end <= start + TIME_EPSILON
                    or other_start >= end - TIME_EPSILON
                ):
                    continue
                track.clips.remove(other)
                left_duration = max(0.0, start - other_start)
                right_duration = max(0.0, other_end - end)
                if left_duration > TIME_EPSILON:
                    left = other.model_copy(deep=True)
                    left.trim_out = (
                        left.trim_in + left_duration * left.speed_factor
                    )
                    replacements.append(left)
                    modified.append(left.id)
                else:
                    deleted.append(other.id)
                if right_duration > TIME_EPSILON:
                    right = other.model_copy(deep=True)
                    right.id = self.id_factory("clip")
                    right.trim_in = (
                        other.trim_out - right_duration * other.speed_factor
                    )
                    right.timeline_start = end
                    replacements.append(right)
                    created.append(right.id)
                    derived_created.append(right.id)
                    consequential.append(right.id)
                if left_duration <= TIME_EPSILON and right_duration <= TIME_EPSILON:
                    deleted.append(other.id)
            track.clips.extend(replacements)
        else:
            raise TimelineEditError("Mode must be insert or overwrite")
        track.clips.append(clip)
        return self._finish(
            operation=mode,
            primary_key=key,
            primary_track=track,
            direct=(clip.id,),
            consequential=(
                consequential + modified + deleted + derived_created
            ),
            created=created,
            modified=modified,
            deleted=deleted,
            warnings=(
                (
                    "Linked insertion joins an explicit group; a separate "
                    "confirmed request is required for each linked source.",
                )
                if edit_scope == "linked_group"
                else ()
            ),
        )

    def set_properties(
        self,
        track_reference: str,
        clip_id: str,
        *,
        speed_factor: float | None,
        volume: float | None,
        keep_audio: bool | None,
        mute: bool | None,
        rotate: int | None,
        edit_scope: str = "current_clip",
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        if rotate is not None and any(
            track.kind != "video" for _, track, _ in members
        ):
            raise TimelineEditError(
                "Rotation is a video-only property and cannot target audio"
            )
        if keep_audio is not None and any(
            track.kind != "video" for _, track, _ in members
        ):
            raise TimelineEditError(
                "Linked keep_audio cannot target an audio track"
            )
        modified: list[str] = []
        consequential: list[str] = []
        for _, track, clip in members:
            before = clip.model_copy(deep=True)
            if speed_factor is not None:
                clip.speed_factor = speed_factor
            if volume is not None:
                clip.volume = volume
            if keep_audio is not None:
                clip.keep_audio = keep_audio
            if mute is not None:
                if track.kind == "video":
                    clip.keep_audio = not mute
                else:
                    clip.volume = 0.0 if mute else (
                        1.0 if clip.volume == 0 else clip.volume
                    )
            if rotate is not None:
                clip.rotate = rotate
            if clip != before:
                modified.append(clip.id)
                if clip.id != clip_id:
                    consequential.append(clip.id)
        if not modified:
            raise TimelineEditError(
                "Playback property edit does not change any clip"
            )
        return self._finish(
            operation="set_properties",
            primary_key=target[0],
            primary_track=target[1],
            direct=(clip_id,),
            consequential=consequential,
            modified=modified,
        )

    def set_clip_audio(
        self,
        track_reference: str,
        clip_id: str,
        *,
        gain_db: float | None,
        muted: bool | None,
        pan: float | None,
        fade_in_seconds: float | None,
        fade_out_seconds: float | None,
        playback_rate: float | None,
        normalization: AppliedLoudnessNormalization | None,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind == "video" and not clip.keep_audio:
            raise TimelineEditError("The target video clip has no active audio component")
        if playback_rate is not None and track.kind != "audio":
            raise TimelineEditError(
                "Independent audio playback rate is supported only on audio tracks; "
                "use the shared clip speed edit for embedded video audio"
            )
        updates = clip.audio.model_dump(mode="python")
        for field, value in (
            ("gain_db", gain_db),
            ("muted", muted),
            ("pan", pan),
            ("fade_in_seconds", fade_in_seconds),
            ("fade_out_seconds", fade_out_seconds),
            ("normalization", normalization),
        ):
            if value is not None:
                updates[field] = value
        before = clip.model_copy(deep=True)
        clip.audio = ClipAudioSettings.model_validate(updates)
        if playback_rate is not None:
            clip.speed_factor = playback_rate
        try:
            ClipConfig.model_validate(clip.model_dump(mode="python"))
        except ValueError as exc:
            raise TimelineEditError(str(exc)) from exc
        if clip == before:
            raise TimelineEditError("Audio property edit does not change the clip")
        return self._finish(
            operation="set_clip_audio",
            primary_key=key,
            primary_track=track,
            direct=(clip.id,),
            modified=(clip.id,),
        )

    def set_track_mix(
        self,
        track_id: str,
        *,
        gain_db: float | None,
        muted: bool | None,
        pan: float | None,
    ):
        key, track = self._resolve_track(track_id)
        if track.kind != "audio":
            raise TimelineEditError("Track mix properties require an audio track")
        updates = track.mix.model_dump(mode="python")
        if gain_db is not None:
            updates["gain_db"] = gain_db
        if muted is not None:
            updates["muted"] = muted
        if pan is not None:
            updates["pan"] = pan
        updated = TrackMixSettings.model_validate(updates)
        if updated == track.mix:
            raise TimelineEditError("Track mix edit does not change the track")
        track.mix = updated
        return self._finish(
            operation="set_track_mix",
            primary_key=key,
            primary_track=track,
            direct=(),
            consequential=tuple(clip.id for clip in track.clips),
            modified=tuple(clip.id for clip in track.clips),
        )

    def set_volume_envelope(
        self,
        track_reference: str,
        clip_id: str,
        *,
        action: str,
        point_id: str | None,
        offset_seconds: float | None,
        gain_db: float | None,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        points = list(clip.audio.envelope)
        if action == "clear":
            if not points:
                raise TimelineEditError("The volume envelope is already empty")
            points = []
        elif action == "delete":
            matches = [point for point in points if point.point_id == point_id]
            if len(matches) != 1:
                raise TimelineEditError("Envelope point ID must identify one point")
            points = [point for point in points if point.point_id != point_id]
        elif action == "upsert":
            assert point_id is not None
            assert offset_seconds is not None
            assert gain_db is not None
            replacement = AudioEnvelopePoint(
                point_id=point_id,
                offset_seconds=offset_seconds,
                gain_db=gain_db,
            )
            points = [point for point in points if point.point_id != point_id]
            if any(
                abs(point.offset_seconds - replacement.offset_seconds)
                <= TIME_EPSILON
                for point in points
            ):
                raise TimelineEditError("Envelope offsets must be unique")
            points.append(replacement)
        else:
            raise TimelineEditError("Unsupported envelope action")
        points.sort(key=lambda point: (point.offset_seconds, point.point_id))
        clip.audio = clip.audio.model_copy(update={"envelope": tuple(points)})
        try:
            ClipConfig.model_validate(clip.model_dump(mode="python"))
        except ValueError as exc:
            raise TimelineEditError(str(exc)) from exc
        return self._finish(
            operation="set_volume_envelope",
            primary_key=key,
            primary_track=track,
            direct=(clip.id,),
            modified=(clip.id,),
        )

    def manage_track(
        self,
        *,
        action: str,
        track_id: str,
        kind: str | None,
        role: str | None,
        order: int | None,
        enabled: bool | None,
        muted: bool | None,
        locked: bool | None,
    ):
        if action == "add":
            if any(track.id == track_id for track in self.timeline.tracks.values()):
                raise TimelineEditError("Track ID already exists")
            if order is None or kind is None:
                raise TimelineEditError("Track add requires kind and order")
            for track in self.timeline.tracks.values():
                if track.order >= order:
                    track.order += 1
            key = track_id
            track = TrackConfig(
                id=track_id,
                kind=kind,
                role=role or "auxiliary",
                order=order,
                enabled=True if enabled is None else enabled,
                muted=False if muted is None else muted,
                locked=False if locked is None else locked,
            )
            self.timeline.tracks[key] = track
        else:
            key, track = self._resolve_track(
                track_id,
                allow_locked=True,
            )
            if action == "remove":
                if track.clips:
                    raise TimelineEditError(
                        "A non-empty track cannot be removed"
                    )
                if track.locked:
                    raise TimelineEditError(
                        "Unlock the track before removing it"
                    )
                removed_order = track.order
                del self.timeline.tracks[key]
                for candidate in self.timeline.tracks.values():
                    if candidate.order > removed_order:
                        candidate.order -= 1
            elif action == "reorder":
                if order is None:
                    raise TimelineEditError("Track reorder requires order")
                if order >= len(self.timeline.tracks):
                    raise TimelineEditError("Track order is out of range")
                old_order = track.order
                if old_order == order:
                    raise TimelineEditError("Track order is unchanged")
                for candidate in self.timeline.tracks.values():
                    if candidate.id == track.id:
                        continue
                    if old_order < order and old_order < candidate.order <= order:
                        candidate.order -= 1
                    elif order < old_order and order <= candidate.order < old_order:
                        candidate.order += 1
                track.order = order
            elif action == "update":
                before = track.model_copy(deep=True)
                if role is not None:
                    track.role = role
                if enabled is not None:
                    track.enabled = enabled
                if muted is not None:
                    track.muted = muted
                if locked is not None:
                    track.locked = locked
                if track == before:
                    raise TimelineEditError("Track properties are unchanged")
            else:
                raise TimelineEditError("Unsupported track management action")
        self._sort_all()
        self.validate(self.timeline)
        return self.timeline, TimelineEditOutcome(
            operation="manage_track",
            track_id=track_id,
            track_key=key,
            direct_clip_ids=(),
            warnings=(),
        )

    def set_clip_link(
        self,
        *,
        action: str,
        members: Iterable[tuple[str, str]],
        link_group_id: str | None,
    ):
        resolved: list[tuple[str, TrackConfig, ClipConfig]] = [
            self._clip(track_id, clip_id) for track_id, clip_id in members
        ]
        if action == "link":
            if len(resolved) < 2 or link_group_id is None:
                raise TimelineEditError(
                    "Link requires two or more members and a group ID"
                )
            existing = [
                clip.id
                for track in self.timeline.tracks.values()
                for clip in track.clips
                if clip.link_group_id == link_group_id
                and all(clip is not item[2] for item in resolved)
            ]
            if existing:
                raise TimelineEditError(
                    "Link group ID is already used by other clips"
                )
            if any(
                clip.link_group_id not in {None, link_group_id}
                for _, _, clip in resolved
            ):
                raise TimelineEditError(
                    "Unlink existing groups before creating a new link"
                )
            for _, _, clip in resolved:
                clip.link_group_id = link_group_id
        elif action == "unlink":
            if any(clip.link_group_id is None for _, _, clip in resolved):
                raise TimelineEditError("Every selected clip must be linked")
            for _, _, clip in resolved:
                clip.link_group_id = None
        else:
            raise TimelineEditError("Unsupported link action")
        primary = resolved[0]
        return self._finish(
            operation="set_clip_link",
            primary_key=primary[0],
            primary_track=primary[1],
            direct=(clip.id for _, _, clip in resolved),
            modified=(clip.id for _, _, clip in resolved),
        )
