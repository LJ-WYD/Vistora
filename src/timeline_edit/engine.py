"""Pure deterministic editing semantics over detached TimelineConfig copies."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable

from core.timeline import ClipConfig, TimelineConfig, TrackConfig

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
    def __init__(
        self,
        timeline: TimelineConfig,
        *,
        id_factory: IdFactory = _random_id,
    ) -> None:
        self.timeline = timeline.model_copy(deep=True)
        self.id_factory = id_factory
        for track in self.timeline.tracks.values():
            track.clips.sort(
                key=lambda item: (item.timeline_start, item.id)
            )
        self.validate(self.timeline)

    @staticmethod
    def validate(timeline: TimelineConfig) -> None:
        all_ids: list[str] = []
        for track_key, track in timeline.tracks.items():
            for clip in track.clips:
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
                    f"Track {track_key} clips are not deterministically sorted"
                )
        if len(all_ids) != len(set(all_ids)):
            raise TimelineEditError("Clip IDs must be unique across tracks")

    def _track(self, track_key: str) -> TrackConfig:
        if track_key not in {"video", "audio"}:
            raise TimelineEditError("Only video and audio tracks are supported")
        return self.timeline.tracks.setdefault(
            track_key,
            TrackConfig(id=track_key),
        )

    def _clip(self, track_key: str, clip_id: str) -> ClipConfig:
        matches = [
            clip for clip in self._track(track_key).clips
            if clip.id == clip_id
        ]
        if len(matches) != 1:
            raise TimelineEditError(
                f"clip_id {clip_id!r} must identify exactly one {track_key} clip"
            )
        return matches[0]

    def _sort(self, track_key: str) -> None:
        self._track(track_key).clips.sort(
            key=lambda item: (item.timeline_start, item.id)
        )

    def _finish(self, outcome: TimelineEditOutcome) -> tuple[
        TimelineConfig, TimelineEditOutcome
    ]:
        self._sort(outcome.track_key)
        self.validate(self.timeline)
        return self.timeline, outcome

    def split(
        self,
        track_key: str,
        clip_id: str,
        split_at: float,
        *,
        right_clip_id: str | None = None,
    ):
        clip = self._clip(track_key, clip_id)
        end = clip_end(clip)
        if (
            split_at <= clip.timeline_start + TIME_EPSILON
            or split_at >= end - TIME_EPSILON
        ):
            raise TimelineEditError("Split point must be inside the clip")
        right_id = right_clip_id or self.id_factory("clip")
        if any(
            right_id == item.id
            for track in self.timeline.tracks.values()
            for item in track.clips
        ):
            raise TimelineEditError("Split output clip ID already exists")
        source_split = clip.trim_in + (
            split_at - clip.timeline_start
        ) * clip.speed_factor
        original_out = clip.trim_out
        clip.trim_out = source_split
        right = clip.model_copy(deep=True)
        right.id = right_id
        right.trim_in = source_split
        right.trim_out = original_out
        right.timeline_start = split_at
        self._track(track_key).clips.append(right)
        return self._finish(TimelineEditOutcome(
            operation="split",
            track_key=track_key,
            direct_clip_ids=(clip_id, right_id),
            created_clip_ids=(right_id,),
            modified_clip_ids=(clip_id,),
        ))

    def trim(
        self,
        track_key: str,
        clip_id: str,
        trim_in: float,
        trim_out: float,
        *,
        ripple: bool,
    ):
        clip = self._clip(track_key, clip_id)
        if trim_out <= trim_in + TIME_EPSILON:
            raise TimelineEditError("Trim must retain positive source duration")
        if (
            trim_in < clip.trim_in - TIME_EPSILON
            or trim_out > clip.trim_out + TIME_EPSILON
        ):
            raise TimelineEditError(
                "Trim may only narrow the clip's currently validated "
                "source range"
            )
        if (
            abs(trim_in - clip.trim_in) <= TIME_EPSILON
            and abs(trim_out - clip.trim_out) <= TIME_EPSILON
        ):
            raise TimelineEditError("Trim does not change the clip range")
        old_end = clip_end(clip)
        old_duration = clip_duration(clip)
        clip.trim_in = trim_in
        clip.trim_out = trim_out
        new_duration = clip_duration(clip)
        delta = new_duration - old_duration
        consequential: list[str] = []
        if ripple and abs(delta) > TIME_EPSILON:
            for other in self._track(track_key).clips:
                if (
                    other.id != clip_id
                    and other.timeline_start >= old_end - TIME_EPSILON
                ):
                    other.timeline_start = max(
                        0.0, other.timeline_start + delta
                    )
                    consequential.append(other.id)
        return self._finish(TimelineEditOutcome(
            operation="trim",
            track_key=track_key,
            direct_clip_ids=(clip_id,),
            consequential_clip_ids=tuple(sorted(consequential)),
            modified_clip_ids=(clip_id, *sorted(consequential)),
        ))

    def move(
        self,
        track_key: str,
        clip_id: str,
        timeline_start: float,
        *,
        ripple: bool,
    ):
        clip = self._clip(track_key, clip_id)
        if timeline_start < 0:
            raise TimelineEditError("Timeline start cannot be negative")
        if abs(timeline_start - clip.timeline_start) <= TIME_EPSILON:
            raise TimelineEditError("Move does not change the clip position")
        consequential: list[str] = []
        duration = clip_duration(clip)
        old_end = clip_end(clip)
        if ripple:
            others = [
                item for item in self._track(track_key).clips
                if item.id != clip_id
            ]
            for other in others:
                if other.timeline_start >= old_end - TIME_EPSILON:
                    other.timeline_start = max(
                        0.0, other.timeline_start - duration
                    )
                    consequential.append(other.id)
            for other in others:
                if other.timeline_start >= timeline_start - TIME_EPSILON:
                    other.timeline_start += duration
                    consequential.append(other.id)
        clip.timeline_start = timeline_start
        return self._finish(TimelineEditOutcome(
            operation="move",
            track_key=track_key,
            direct_clip_ids=(clip_id,),
            consequential_clip_ids=tuple(sorted(set(consequential))),
            modified_clip_ids=(clip_id, *sorted(set(consequential))),
            warnings=(
                ("Non-ripple move may intentionally overlap another clip.",)
                if not ripple else ()
            ),
        ))

    def remove(self, track_key: str, clip_id: str, *, ripple: bool):
        clip = self._clip(track_key, clip_id)
        end = clip_end(clip)
        duration = clip_duration(clip)
        track = self._track(track_key)
        track.clips.remove(clip)
        consequential: list[str] = []
        if ripple:
            for other in track.clips:
                if other.timeline_start >= end - TIME_EPSILON:
                    other.timeline_start = max(
                        0.0, other.timeline_start - duration
                    )
                    consequential.append(other.id)
        return self._finish(TimelineEditOutcome(
            operation="remove",
            track_key=track_key,
            direct_clip_ids=(clip_id,),
            consequential_clip_ids=tuple(sorted(consequential)),
            modified_clip_ids=tuple(sorted(consequential)),
            deleted_clip_ids=(clip_id,),
        ))

    def insert_overwrite(
        self,
        track_key: str,
        clip: ClipConfig,
        *,
        mode: str,
    ):
        track = self._track(track_key)
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
                if other_end <= start + TIME_EPSILON or other_start >= end - TIME_EPSILON:
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
                if left_duration <= TIME_EPSILON and right_duration <= TIME_EPSILON:
                    deleted.append(other.id)
            track.clips.extend(replacements)
        else:
            raise TimelineEditError("Mode must be insert or overwrite")
        track.clips.append(clip)
        return self._finish(TimelineEditOutcome(
            operation=mode,
            track_key=track_key,
            direct_clip_ids=(clip.id,),
            consequential_clip_ids=tuple(sorted(set(
                consequential
                + (
                    modified
                    + deleted
                    + derived_created
                    if mode in {"insert", "overwrite"}
                    else []
                )
            ))),
            created_clip_ids=tuple(created),
            modified_clip_ids=tuple(sorted(set(modified))),
            deleted_clip_ids=tuple(sorted(set(deleted))),
        ))

    def set_properties(
        self,
        track_key: str,
        clip_id: str,
        *,
        speed_factor: float | None,
        volume: float | None,
        keep_audio: bool | None,
        mute: bool | None,
        rotate: int | None,
    ):
        clip = self._clip(track_key, clip_id)
        before = clip.model_copy(deep=True)
        if speed_factor is not None:
            clip.speed_factor = speed_factor
        if volume is not None:
            clip.volume = volume
        if keep_audio is not None:
            clip.keep_audio = keep_audio
        if mute is not None:
            if track_key == "video":
                clip.keep_audio = not mute
            else:
                clip.volume = 0.0 if mute else (
                    1.0 if clip.volume == 0 else clip.volume
                )
        if rotate is not None:
            if track_key != "video":
                raise TimelineEditError("Rotation applies only to video clips")
            clip.rotate = rotate
        if clip == before:
            raise TimelineEditError(
                "Playback property edit does not change the clip"
            )
        return self._finish(TimelineEditOutcome(
            operation="set_properties",
            track_key=track_key,
            direct_clip_ids=(clip_id,),
            modified_clip_ids=(clip_id,),
        ))
