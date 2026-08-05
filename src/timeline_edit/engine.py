"""Pure deterministic multi-track editing over detached TimelineConfig copies."""

from __future__ import annotations

import math
import hashlib
import json
import uuid
from collections.abc import Callable, Iterable

from core.timeline import (
    AppliedAudioDucking,
    AppliedLoudnessNormalization,
    AudioEnvelopePoint,
    ClipAudioSettings,
    ClipConfig,
    FreezeFrameSettings,
    ClipColorAdjustment,
    ClipCompositeSettings,
    ClipTransform,
    ClipMask,
    MaskAutomation,
    TimelineConfig,
    TimelineTransition,
    TrackConfig,
    TrackMixSettings,
    VisualAutomation,
    VisualKeyframe,
)
from visual_automation.runtime import evaluate_curve, static_visual_value

from .models import TimelineEditOutcome, TimelineSubtitleRipplePolicy


TIME_EPSILON = 1e-6
IdFactory = Callable[[str], str]
SourceDurationResolver = Callable[[ClipConfig], float]
SourceAudioResolver = Callable[[ClipConfig], bool]


class TimelineEditError(ValueError):
    pass


def _random_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def clip_duration(clip: ClipConfig) -> float:
    if clip.freeze_frame is not None:
        return clip.freeze_frame.duration_seconds
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
        source_duration_resolver: SourceDurationResolver | None = None,
        source_audio_resolver: SourceAudioResolver | None = None,
    ) -> None:
        self.timeline = TimelineConfig.model_validate(
            timeline.model_dump(mode="python")
        )
        self.id_factory = id_factory
        self.source_duration_resolver = source_duration_resolver
        self.source_audio_resolver = source_audio_resolver
        self._sort_all()
        self.validate(self.timeline)

    @staticmethod
    def validate(timeline: TimelineConfig) -> None:
        all_ids: list[str] = []
        automation_ids: list[str] = []
        keyframe_ids: list[str] = []
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
                automation_ids.extend(
                    item.automation_id for item in clip.visual_automations
                )
                keyframe_ids.extend(
                    point.keyframe_id
                    for item in clip.visual_automations
                    for point in item.keyframes
                )
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
                if clip.freeze_frame is not None and track.kind != "video":
                    raise TimelineEditError(
                        "Freeze-frame playback is supported only on video clips"
                    )
                crop_curves = {
                    item.property_path: item
                    for item in clip.visual_automations
                    if item.enabled and item.property_path.startswith("transform.crop_")
                }
                crop_times = {
                    point.offset_seconds
                    for item in crop_curves.values()
                    for point in item.keyframes
                }
                for offset in crop_times:
                    values = {}
                    for edge in ("left", "right", "top", "bottom"):
                        path = f"transform.crop_{edge}"
                        curve = crop_curves.get(path)
                        baseline = float(getattr(clip.transform, f"crop_{edge}"))
                        values[edge] = (
                            evaluate_curve(curve, offset, baseline)
                            if curve is not None
                            else baseline
                        )
                    if values["left"] + values["right"] >= 0.99:
                        raise TimelineEditError(
                            "Animated horizontal crop must retain at least 1%"
                        )
                    if values["top"] + values["bottom"] >= 0.99:
                        raise TimelineEditError(
                            "Animated vertical crop must retain at least 1%"
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
        if len(automation_ids) != len(set(automation_ids)):
            raise TimelineEditError("Visual automation IDs must be project-unique")
        if len(keyframe_ids) != len(set(keyframe_ids)):
            raise TimelineEditError("Visual keyframe IDs must be project-unique")
        try:
            TimelineConfig.model_validate(timeline.model_dump(mode="python"))
        except ValueError as exc:
            raise TimelineEditError(
                f"Timeline transition state is invalid: {exc}"
            ) from exc

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

    def _boundary_keyframe(
        self,
        automation: VisualAutomation,
        clip: ClipConfig,
        offset: float,
        *,
        new_offset: float,
    ) -> VisualKeyframe:
        exact = next(
            (
                point
                for point in automation.keyframes
                if abs(point.offset_seconds - offset) <= TIME_EPSILON
            ),
            None,
        )
        return VisualKeyframe(
            keyframe_id=(
                exact.keyframe_id if exact is not None else self.id_factory("keyframe")
            ),
            offset_seconds=new_offset,
            value=evaluate_curve(
                automation,
                offset,
                static_visual_value(clip, automation.property_path),
            ),
            interpolation=(exact.interpolation if exact is not None else "linear"),
        )

    def _split_visual(
        self,
        clip: ClipConfig,
        split_offset: float,
        right_clip_id: str,
    ) -> tuple[tuple[VisualAutomation, ...], tuple[VisualAutomation, ...]]:
        left_curves: list[VisualAutomation] = []
        right_curves: list[VisualAutomation] = []
        for automation in clip.visual_automations:
            boundary = self._boundary_keyframe(
                automation, clip, split_offset, new_offset=split_offset
            )
            left_points = [
                point
                for point in automation.keyframes
                if point.offset_seconds < split_offset - TIME_EPSILON
            ]
            left_points.append(boundary)
            right_boundary = boundary.model_copy(
                update={
                    "keyframe_id": self.id_factory("keyframe"),
                    "offset_seconds": 0.0,
                }
            )
            right_points = [right_boundary]
            right_points.extend(
                point.model_copy(
                    update={
                        "keyframe_id": self.id_factory("keyframe"),
                        "offset_seconds": point.offset_seconds - split_offset,
                    }
                )
                for point in automation.keyframes
                if point.offset_seconds > split_offset + TIME_EPSILON
            )
            left_curves.append(
                automation.model_copy(update={"keyframes": tuple(left_points)})
            )
            right_curves.append(
                automation.model_copy(
                    update={
                        "automation_id": self.id_factory("automation"),
                        "clip_id": right_clip_id,
                        "keyframes": tuple(right_points),
                    }
                )
            )
        return tuple(left_curves), tuple(right_curves)

    def _trim_visual(
        self,
        clip: ClipConfig,
        *,
        removed_start: float,
        new_duration: float,
    ) -> tuple[VisualAutomation, ...]:
        curves: list[VisualAutomation] = []
        end_offset = removed_start + new_duration
        for automation in clip.visual_automations:
            start_boundary = self._boundary_keyframe(
                automation, clip, removed_start, new_offset=0.0
            )
            points: list[VisualKeyframe] = [start_boundary]
            points.extend(
                point.model_copy(
                    update={"offset_seconds": point.offset_seconds - removed_start}
                )
                for point in automation.keyframes
                if (
                    point.offset_seconds > removed_start + TIME_EPSILON
                    and point.offset_seconds < end_offset - TIME_EPSILON
                )
            )
            if new_duration > TIME_EPSILON:
                end_boundary = self._boundary_keyframe(
                    automation, clip, end_offset, new_offset=new_duration
                )
                if end_boundary.keyframe_id == start_boundary.keyframe_id:
                    end_boundary = end_boundary.model_copy(
                        update={"keyframe_id": self.id_factory("keyframe")}
                    )
                points.append(end_boundary)
            curves.append(automation.model_copy(update={"keyframes": tuple(points)}))
        return tuple(curves)

    def _retarget_visual(
        self,
        curves: tuple[VisualAutomation, ...],
        clip_id: str,
    ) -> tuple[VisualAutomation, ...]:
        return tuple(
            automation.model_copy(
                update={
                    "automation_id": self.id_factory("automation"),
                    "clip_id": clip_id,
                    "keyframes": tuple(
                        point.model_copy(
                            update={"keyframe_id": self.id_factory("keyframe")}
                        )
                        for point in automation.keyframes
                    ),
                }
            )
            for automation in curves
        )

    @staticmethod
    def _copy_identity(prefix: str, *parts: str) -> str:
        encoded = "\x1f".join(parts).encode("utf-8")
        return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:20]}"

    def _copy_visual_curves(
        self,
        curves: tuple[VisualAutomation, ...],
        clip_id: str,
    ) -> tuple[VisualAutomation, ...]:
        return tuple(
            automation.model_copy(
                update={
                    "automation_id": self._copy_identity(
                        "automation", automation.automation_id, clip_id
                    ),
                    "clip_id": clip_id,
                    "keyframes": tuple(
                        point.model_copy(
                            update={
                                "keyframe_id": self._copy_identity(
                                    "keyframe",
                                    automation.automation_id,
                                    point.keyframe_id,
                                    clip_id,
                                )
                            }
                        )
                        for point in automation.keyframes
                    ),
                }
            )
            for automation in curves
        )

    def _mask_boundary(
        self,
        curve: MaskAutomation,
        mask: ClipMask,
        offset: float,
        *,
        new_offset: float,
    ) -> VisualKeyframe:
        exact = next(
            (point for point in curve.keyframes if abs(point.offset_seconds - offset) <= TIME_EPSILON),
            None,
        )
        return VisualKeyframe(
            keyframe_id=exact.keyframe_id if exact else self.id_factory("maskkey"),
            offset_seconds=new_offset,
            value=evaluate_curve(curve, offset, float(getattr(mask, curve.property_path))),
            interpolation=exact.interpolation if exact else "linear",
        )

    def _split_masks(
        self, clip: ClipConfig, split_offset: float
    ) -> tuple[tuple[ClipMask, ...], tuple[ClipMask, ...]]:
        left_masks: list[ClipMask] = []
        right_masks: list[ClipMask] = []
        for mask in clip.masks:
            right_mask_id = self.id_factory("mask")
            left_curves: list[MaskAutomation] = []
            right_curves: list[MaskAutomation] = []
            for curve in mask.automations:
                boundary = self._mask_boundary(curve, mask, split_offset, new_offset=split_offset)
                left_points = [point for point in curve.keyframes if point.offset_seconds < split_offset - TIME_EPSILON]
                left_points.append(boundary)
                right_points = [boundary.model_copy(update={"keyframe_id": self.id_factory("maskkey"), "offset_seconds": 0.0})]
                right_points.extend(
                    point.model_copy(update={"keyframe_id": self.id_factory("maskkey"), "offset_seconds": point.offset_seconds - split_offset})
                    for point in curve.keyframes
                    if point.offset_seconds > split_offset + TIME_EPSILON
                )
                left_curves.append(curve.model_copy(update={"keyframes": tuple(left_points)}))
                right_curves.append(curve.model_copy(update={
                    "automation_id": self.id_factory("maskauto"),
                    "mask_id": right_mask_id,
                    "keyframes": tuple(right_points),
                }))
            left_masks.append(mask.model_copy(update={"automations": tuple(left_curves)}))
            right_masks.append(mask.model_copy(update={"mask_id": right_mask_id, "automations": tuple(right_curves)}))
        return tuple(left_masks), tuple(right_masks)

    def _trim_masks(
        self,
        clip: ClipConfig,
        *,
        removed_start: float,
        new_duration: float,
    ) -> tuple[ClipMask, ...]:
        result: list[ClipMask] = []
        end_offset = removed_start + new_duration
        for mask in clip.masks:
            curves: list[MaskAutomation] = []
            for curve in mask.automations:
                start = self._mask_boundary(curve, mask, removed_start, new_offset=0.0)
                points = [start]
                points.extend(
                    point.model_copy(update={"offset_seconds": point.offset_seconds - removed_start})
                    for point in curve.keyframes
                    if removed_start + TIME_EPSILON < point.offset_seconds < end_offset - TIME_EPSILON
                )
                end = self._mask_boundary(curve, mask, end_offset, new_offset=new_duration)
                if end.keyframe_id == start.keyframe_id:
                    end = end.model_copy(update={"keyframe_id": self.id_factory("maskkey")})
                points.append(end)
                curves.append(curve.model_copy(update={"keyframes": tuple(points)}))
            result.append(mask.model_copy(update={"automations": tuple(curves)}))
        return tuple(result)

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
        subtitle_cues: Iterable[str] = (),
        warnings: Iterable[str] = (),
        created_transitions: Iterable[str] = (),
        modified_transitions: Iterable[str] = (),
        deleted_transitions: Iterable[str] = (),
        created_automations: Iterable[str] = (),
        modified_automations: Iterable[str] = (),
        deleted_automations: Iterable[str] = (),
        created_masks: Iterable[str] = (),
        modified_masks: Iterable[str] = (),
        deleted_masks: Iterable[str] = (),
    ) -> tuple[TimelineConfig, TimelineEditOutcome]:
        self._sort_all()
        invalidated = self._remove_invalid_transitions()
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
            consequential_subtitle_cue_ids=tuple(sorted(set(subtitle_cues))),
            created_transition_ids=tuple(dict.fromkeys(created_transitions)),
            modified_transition_ids=tuple(sorted(set(modified_transitions))),
            deleted_transition_ids=tuple(
                sorted(set(deleted_transitions) | invalidated)
            ),
            created_automation_ids=tuple(dict.fromkeys(created_automations)),
            modified_automation_ids=tuple(sorted(set(modified_automations))),
            deleted_automation_ids=tuple(sorted(set(deleted_automations))),
            created_mask_ids=tuple(dict.fromkeys(created_masks)),
            modified_mask_ids=tuple(sorted(set(modified_masks))),
            deleted_mask_ids=tuple(sorted(set(deleted_masks))),
            warnings=tuple(warnings) + (
                (
                    "Structurally invalid transitions were removed and "
                    "recorded as tombstones.",
                )
                if invalidated
                else ()
            ),
        )

    def _transition_binding_valid(self, transition: TimelineTransition) -> bool:
        try:
            _, track = self._resolve_track(
                transition.track_id, allow_locked=True
            )
        except TimelineEditError:
            return False
        clips = sorted(track.clips, key=lambda item: (item.timeline_start, item.id))
        indices = {clip.id: index for index, clip in enumerate(clips)}
        left_index = indices.get(transition.from_clip_id)
        right_index = indices.get(transition.to_clip_id)
        if left_index is None or right_index != left_index + 1:
            return False
        left, right = clips[left_index], clips[right_index]
        if abs(clip_end(left) - right.timeline_start) > TIME_EPSILON:
            return False
        if transition.kind != "cut" and (
            left.freeze_frame is not None or right.freeze_frame is not None
        ):
            return False
        if transition.media_type == "video":
            return track.kind == "video"
        return track.kind == "audio" or (
            track.kind == "video" and left.keep_audio and right.keep_audio
        )

    def _remove_invalid_transitions(self) -> set[str]:
        invalid = {
            transition_id
            for transition_id, transition in self.timeline.transitions.items()
            if not self._transition_binding_valid(transition)
        }
        for transition_id, transition in self.timeline.transitions.items():
            if (
                transition.paired_transition_id in invalid
                or (
                    transition.paired_transition_id is not None
                    and transition.paired_transition_id
                    not in self.timeline.transitions
                )
            ):
                invalid.add(transition_id)
        for transition_id in invalid:
            self.timeline.transitions.pop(transition_id, None)
        return invalid

    @staticmethod
    def _handle_requirements(
        transition: TimelineTransition,
    ) -> tuple[float, float]:
        duration = transition.duration_seconds
        if transition.kind == "cut":
            return 0.0, 0.0
        if transition.alignment == "start_at_cut":
            return duration, 0.0
        if transition.alignment == "end_at_cut":
            return 0.0, duration
        return duration / 2.0, duration / 2.0

    def _validate_transition_handles(
        self,
        transition: TimelineTransition,
    ) -> None:
        if transition.kind == "cut":
            return
        if self.source_duration_resolver is None:
            raise TimelineEditError(
                "Transition handle validation requires exact media duration facts"
            )
        _, track = self._resolve_track(
            transition.track_id, allow_locked=True
        )
        clips = {clip.id: clip for clip in track.clips}
        outgoing = clips[transition.from_clip_id]
        incoming = clips[transition.to_clip_id]
        if outgoing.reverse or incoming.reverse:
            raise TimelineEditError(
                "Transitions over reversed clips are currently unsupported"
            )
        outgoing_seconds, incoming_seconds = self._handle_requirements(
            transition
        )
        outgoing_required = outgoing_seconds * outgoing.speed_factor
        incoming_required = incoming_seconds * incoming.speed_factor
        outgoing_source_duration = float(
            self.source_duration_resolver(outgoing)
        )
        incoming_source_duration = float(
            self.source_duration_resolver(incoming)
        )
        outgoing_available = max(
            0.0, outgoing_source_duration - outgoing.trim_out
        )
        incoming_available = max(0.0, incoming.trim_in)
        if outgoing_available + TIME_EPSILON < outgoing_required:
            share = outgoing_seconds / transition.duration_seconds
            maximum = outgoing_available / outgoing.speed_factor / share
            raise TimelineEditError(
                "Outgoing clip has insufficient source handle for transition; "
                f"maximum safe duration is {maximum:.6g} seconds"
            )
        if incoming_available + TIME_EPSILON < incoming_required:
            share = incoming_seconds / transition.duration_seconds
            maximum = incoming_available / incoming.speed_factor / share
            raise TimelineEditError(
                "Incoming clip has insufficient source handle for transition; "
                f"maximum safe duration is {maximum:.6g} seconds"
            )

    def _validate_transition_candidate(
        self, transition: TimelineTransition
    ) -> None:
        if transition.transition_id in self.timeline.transitions:
            raise TimelineEditError("Transition ID already exists")
        if not self._transition_binding_valid(transition):
            raise TimelineEditError(
                "Transition must bind one exact adjacent same-track cut"
            )
        _, track = self._resolve_track(transition.track_id)
        if track.kind == "video" and transition.media_type == "video":
            if track.role != "primary":
                raise TimelineEditError(
                    "First-version video transitions require a primary video track"
                )
        if transition.media_type == "audio":
            clips = {clip.id: clip for clip in track.clips}
            if track.muted or track.mix.muted or any(
                clips[clip_id].audio.muted
                for clip_id in (
                    transition.from_clip_id,
                    transition.to_clip_id,
                )
            ):
                raise TimelineEditError(
                    "Audio transitions require two active unmuted audio components"
                )
            if self.source_audio_resolver is not None and any(
                not self.source_audio_resolver(clips[clip_id])
                for clip_id in (
                    transition.from_clip_id,
                    transition.to_clip_id,
                )
            ):
                raise TimelineEditError(
                    "Audio transition requires an audio stream on both sources"
                )
        cut = (
            transition.track_id,
            transition.from_clip_id,
            transition.to_clip_id,
            transition.media_type,
        )
        for current in self.timeline.transitions.values():
            current_cut = (
                current.track_id,
                current.from_clip_id,
                current.to_clip_id,
                current.media_type,
            )
            if current_cut == cut:
                raise TimelineEditError(
                    "An exact cut already has this media transition"
                )
        self._validate_transition_handles(transition)

    def add_transition(
        self,
        transition: TimelineTransition,
        *,
        paired_transition: TimelineTransition | None = None,
    ) -> tuple[TimelineConfig, TimelineEditOutcome]:
        candidates = (transition,) + (
            (paired_transition,) if paired_transition is not None else ()
        )
        for candidate in candidates:
            self._validate_transition_candidate(candidate)
        for candidate in candidates:
            self.timeline.transitions[candidate.transition_id] = candidate
        key, track = self._resolve_track(transition.track_id, allow_locked=True)
        return self._finish(
            operation="add_transition",
            primary_key=key,
            primary_track=track,
            direct=(transition.from_clip_id, transition.to_clip_id),
            created_transitions=(item.transition_id for item in candidates),
        )

    def update_transition(
        self,
        transition: TimelineTransition,
        *,
        paired_transition: TimelineTransition | None = None,
    ) -> tuple[TimelineConfig, TimelineEditOutcome]:
        current = self.timeline.transitions.get(transition.transition_id)
        if current is None:
            raise TimelineEditError("Transition ID is unknown")
        remove_ids = {current.transition_id}
        if current.paired_transition_id is not None:
            remove_ids.add(current.paired_transition_id)
        previous = {
            identity: self.timeline.transitions.pop(identity)
            for identity in remove_ids
            if identity in self.timeline.transitions
        }
        try:
            candidates = (transition,) + (
                (paired_transition,) if paired_transition is not None else ()
            )
            for candidate in candidates:
                self._validate_transition_candidate(candidate)
            for candidate in candidates:
                self.timeline.transitions[candidate.transition_id] = candidate
        except Exception:
            self.timeline.transitions.update(previous)
            raise
        key, track = self._resolve_track(transition.track_id, allow_locked=True)
        new_ids = {candidate.transition_id for candidate in candidates}
        return self._finish(
            operation="update_transition",
            primary_key=key,
            primary_track=track,
            direct=(transition.from_clip_id, transition.to_clip_id),
            modified_transitions=tuple(sorted(new_ids & set(previous))),
            created_transitions=tuple(sorted(new_ids - set(previous))),
            deleted_transitions=tuple(sorted(set(previous) - new_ids)),
        )

    def remove_transition(
        self,
        transition_id: str,
        *,
        include_paired: bool = True,
    ) -> tuple[TimelineConfig, TimelineEditOutcome]:
        transition = self.timeline.transitions.get(transition_id)
        if transition is None:
            raise TimelineEditError("Transition ID is unknown")
        self._resolve_track(transition.track_id)
        remove_ids = {transition_id}
        if transition.paired_transition_id is not None:
            if not include_paired:
                raise TimelineEditError(
                    "Paired transition must be removed atomically"
                )
            remove_ids.add(transition.paired_transition_id)
        for identity in remove_ids:
            self.timeline.transitions.pop(identity, None)
        key, track = self._resolve_track(
            transition.track_id, allow_locked=True
        )
        return self._finish(
            operation="remove_transition",
            primary_key=key,
            primary_track=track,
            direct=(transition.from_clip_id, transition.to_clip_id),
            deleted_transitions=tuple(sorted(remove_ids)),
        )

    def copy_transition(
        self,
        source_transition_id: str,
        targets: Iterable[tuple[TimelineTransition, TimelineTransition | None]],
    ) -> tuple[TimelineConfig, TimelineEditOutcome]:
        source = self.timeline.transitions.get(source_transition_id)
        if source is None:
            raise TimelineEditError("Source transition ID is unknown")
        target_pairs = tuple(targets)
        if not target_pairs:
            raise TimelineEditError("At least one copy target is required")
        candidates = tuple(
            candidate
            for pair in target_pairs
            for candidate in pair
            if candidate is not None
        )
        for candidate in candidates:
            self._validate_transition_candidate(candidate)
        for candidate in candidates:
            self.timeline.transitions[candidate.transition_id] = candidate
        key, track = self._resolve_track(source.track_id, allow_locked=True)
        return self._finish(
            operation="copy_transition",
            primary_key=key,
            primary_track=track,
            direct=tuple(
                clip_id
                for candidate in candidates
                for clip_id in (
                    candidate.from_clip_id,
                    candidate.to_clip_id,
                )
            ),
            created_transitions=tuple(
                candidate.transition_id for candidate in candidates
            ),
        )

    def _apply_subtitle_ripple(
        self,
        *,
        anchor_seconds: float,
        delta_seconds: float,
        policy: TimelineSubtitleRipplePolicy,
    ) -> tuple[str, ...]:
        if policy.mode == "none" or abs(delta_seconds) <= TIME_EPSILON:
            return ()
        selected = set(policy.selected_track_ids)
        known = {track.track_id for track in self.timeline.subtitle_tracks.values()}
        if selected - known:
            raise TimelineEditError("Subtitle ripple references an unknown track")
        changed: list[str] = []
        next_tracks = dict(self.timeline.subtitle_tracks)
        for key, track in sorted(
            self.timeline.subtitle_tracks.items(),
            key=lambda item: (item[1].order, item[1].track_id),
        ):
            if policy.mode == "selected_subtitle_tracks" and track.track_id not in selected:
                continue
            if track.locked:
                if policy.mode == "selected_subtitle_tracks" and track.track_id in selected:
                    raise TimelineEditError(f"Subtitle ripple selected locked track {track.track_id!r}")
                continue
            cues = []
            for cue in track.cues:
                if cue.start_seconds >= anchor_seconds - TIME_EPSILON:
                    start = cue.start_seconds + delta_seconds
                    end = cue.end_seconds + delta_seconds
                    if start < -TIME_EPSILON:
                        raise TimelineEditError("Subtitle ripple would move a cue before zero")
                    cues.append(cue.model_copy(update={"start_seconds": max(0.0, start), "end_seconds": end}))
                    changed.append(cue.cue_id)
                else:
                    cues.append(cue)
            next_tracks[key] = track.model_copy(update={"cues": tuple(cues)})
        self.timeline.subtitle_tracks = next_tracks
        return tuple(sorted(set(changed)))

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
        created_automations: list[str] = []
        modified_automations: list[str] = []
        created_masks: list[str] = []
        modified_masks: list[str] = []
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
            split_offset = split_at - clip.timeline_start
            source_split = clip.trim_in + split_offset * clip.speed_factor
            original_out = clip.trim_out
            original_duration = clip_duration(clip)
            left_audio, right_audio = self._split_audio(
                clip.audio, split_offset, original_duration
            )
            left_automation, right_automation = self._split_visual(
                clip, split_offset, new_id
            )
            left_masks, right_masks = self._split_masks(clip, split_offset)
            original_freeze = clip.freeze_frame
            if original_freeze is None:
                clip.trim_out = source_split
            else:
                clip.freeze_frame = original_freeze.model_copy(
                    update={"duration_seconds": split_offset}
                )
            clip.audio = left_audio
            clip.visual_automations = left_automation
            clip.masks = left_masks
            right = clip.model_copy(deep=True)
            right.id = new_id
            if original_freeze is None:
                right.trim_in = source_split
                right.trim_out = original_out
            else:
                right.trim_in = clip.trim_in
                right.trim_out = original_out
                right.freeze_frame = original_freeze.model_copy(
                    update={
                        "duration_seconds": original_duration - split_offset
                    }
                )
            right.timeline_start = split_at
            right.audio = right_audio
            right.visual_automations = right_automation
            right.masks = right_masks
            right.link_group_id = right_group_id
            track.clips.append(right)
            for transition_id, transition in tuple(
                self.timeline.transitions.items()
            ):
                if (
                    transition.track_id == track.id
                    and transition.from_clip_id == clip.id
                ):
                    self.timeline.transitions[transition_id] = (
                        transition.model_copy(
                            update={"from_clip_id": right.id}
                        )
                    )
            created.append(new_id)
            modified.append(clip.id)
            modified_automations.extend(
                item.automation_id for item in left_automation
            )
            created_automations.extend(
                item.automation_id for item in right_automation
            )
            modified_masks.extend(item.mask_id for item in left_masks)
            created_masks.extend(item.mask_id for item in right_masks)
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
            created_automations=created_automations,
            modified_automations=modified_automations,
            created_masks=created_masks,
            modified_masks=modified_masks,
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
        subtitle_ripple: TimelineSubtitleRipplePolicy | None = None,
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        target_clip = target[2]
        if any(clip.freeze_frame is not None for _, _, clip in members):
            raise TimelineEditError(
                "Source-range trim is not defined for frozen-frame clips; "
                "set a new freeze duration instead"
            )
        subtitle_anchor = clip_end(target_clip)
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
        modified_automations: list[str] = []
        modified_masks: list[str] = []
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
            clip.visual_automations = self._trim_visual(
                clip,
                removed_start=left_delta_seconds,
                new_duration=clip_duration(clip),
            )
            clip.masks = self._trim_masks(
                clip,
                removed_start=left_delta_seconds,
                new_duration=clip_duration(clip),
            )
            modified_automations.extend(
                item.automation_id for item in clip.visual_automations
            )
            modified_masks.extend(item.mask_id for item in clip.masks)
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
        subtitle_cues = self._apply_subtitle_ripple(
            anchor_seconds=subtitle_anchor,
            delta_seconds=-(left_delta_seconds + right_delta_seconds),
            policy=subtitle_ripple or TimelineSubtitleRipplePolicy(),
        ) if ripple else ()
        return self._finish(
            operation="trim",
            primary_key=target[0],
            primary_track=target[1],
            direct=(clip_id,),
            consequential=consequential,
            modified=modified,
            subtitle_cues=subtitle_cues,
            modified_automations=modified_automations,
            modified_masks=modified_masks,
        )

    def move(
        self,
        track_reference: str,
        clip_id: str,
        timeline_start: float,
        *,
        ripple: bool,
        edit_scope: str = "current_clip",
        subtitle_ripple: TimelineSubtitleRipplePolicy | None = None,
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
        subtitle_cues: tuple[str, ...] = ()
        if ripple:
            policy = subtitle_ripple or TimelineSubtitleRipplePolicy()
            changed_subtitles = list(self._apply_subtitle_ripple(
                anchor_seconds=clip_end(target_clip),
                delta_seconds=-clip_duration(target_clip),
                policy=policy,
            ))
            changed_subtitles.extend(self._apply_subtitle_ripple(
                anchor_seconds=timeline_start,
                delta_seconds=clip_duration(target_clip),
                policy=policy,
            ))
            subtitle_cues = tuple(sorted(set(changed_subtitles)))
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
            subtitle_cues=subtitle_cues,
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
        subtitle_ripple: TimelineSubtitleRipplePolicy | None = None,
    ):
        members = self._linked_members(
            track_reference, clip_id, edit_scope
        )
        target = next(item for item in members if item[2].id == clip_id)
        affected_ids = {clip.id for _, _, clip in members}
        deleted: list[str] = []
        deleted_automations: list[str] = []
        deleted_masks: list[str] = []
        modified: list[str] = []
        consequential: list[str] = []
        subtitle_cues: tuple[str, ...] = ()
        if ripple:
            subtitle_cues = self._apply_subtitle_ripple(
                anchor_seconds=clip_end(target[2]),
                delta_seconds=-clip_duration(target[2]),
                policy=subtitle_ripple or TimelineSubtitleRipplePolicy(),
            )
        for _, track, clip in members:
            end = clip_end(clip)
            duration = clip_duration(clip)
            track.clips.remove(clip)
            deleted.append(clip.id)
            deleted_automations.extend(
                item.automation_id for item in clip.visual_automations
            )
            deleted_masks.extend(item.mask_id for item in clip.masks)
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
            subtitle_cues=subtitle_cues,
            deleted_automations=deleted_automations,
            deleted_masks=deleted_masks,
        )

    def insert_overwrite(
        self,
        track_reference: str,
        clip: ClipConfig,
        *,
        mode: str,
        edit_scope: str = "current_clip",
        subtitle_ripple: TimelineSubtitleRipplePolicy | None = None,
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
        created_automations: list[str] = []
        modified_automations: list[str] = []
        deleted_automations: list[str] = []
        if mode == "insert":
            subtitle_cues = self._apply_subtitle_ripple(
                anchor_seconds=start,
                delta_seconds=duration,
                policy=subtitle_ripple or TimelineSubtitleRipplePolicy(),
            )
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
                    split_offset = start - other.timeline_start
                    source_split = other.trim_in + split_offset * other.speed_factor
                    original_out = other.trim_out
                    original_freeze = other.freeze_frame
                    left_curves, right_curves = self._split_visual(
                        other, split_offset, "pending"
                    )
                    if original_freeze is None:
                        other.trim_out = source_split
                    else:
                        other.freeze_frame = original_freeze.model_copy(
                            update={"duration_seconds": split_offset}
                        )
                    other.visual_automations = left_curves
                    right = other.model_copy(deep=True)
                    right.id = self.id_factory("clip")
                    if original_freeze is None:
                        right.trim_in = source_split
                        right.trim_out = original_out
                    else:
                        right.trim_in = other.trim_in
                        right.trim_out = original_out
                        right.freeze_frame = original_freeze.model_copy(
                            update={
                                "duration_seconds": original_freeze.duration_seconds
                                - split_offset
                            }
                        )
                    right.timeline_start = start + duration
                    right.visual_automations = tuple(
                        item.model_copy(update={"clip_id": right.id})
                        for item in right_curves
                    )
                    replacements.append(right)
                    modified.append(other.id)
                    created.append(right.id)
                    derived_created.append(right.id)
                    consequential.extend((other.id, right.id))
                    modified_automations.extend(
                        item.automation_id for item in left_curves
                    )
                    created_automations.extend(
                        item.automation_id for item in right.visual_automations
                    )
            track.clips.extend(replacements)
        elif mode == "overwrite":
            subtitle_cues = ()
            replacements: list[ClipConfig] = []
            for other in list(track.clips):
                other_start, other_end = other.timeline_start, clip_end(other)
                if (
                    other_end <= start + TIME_EPSILON
                    or other_start >= end - TIME_EPSILON
                ):
                    continue
                track.clips.remove(other)
                original = other.model_copy(deep=True)
                left_duration = max(0.0, start - other_start)
                right_duration = max(0.0, other_end - end)
                if left_duration > TIME_EPSILON:
                    left = other.model_copy(deep=True)
                    if left.freeze_frame is None:
                        left.trim_out = (
                            left.trim_in + left_duration * left.speed_factor
                        )
                    else:
                        left.freeze_frame = left.freeze_frame.model_copy(
                            update={"duration_seconds": left_duration}
                        )
                    left.visual_automations = self._trim_visual(
                        original,
                        removed_start=0.0,
                        new_duration=left_duration,
                    )
                    replacements.append(left)
                    modified.append(left.id)
                    modified_automations.extend(
                        item.automation_id for item in left.visual_automations
                    )
                else:
                    deleted.append(other.id)
                    deleted_automations.extend(
                        item.automation_id for item in original.visual_automations
                    )
                if right_duration > TIME_EPSILON:
                    right = other.model_copy(deep=True)
                    right.id = self.id_factory("clip")
                    if right.freeze_frame is None:
                        right.trim_in = (
                            other.trim_out - right_duration * other.speed_factor
                        )
                    else:
                        right.freeze_frame = right.freeze_frame.model_copy(
                            update={"duration_seconds": right_duration}
                        )
                    right.timeline_start = end
                    right.visual_automations = self._retarget_visual(
                        self._trim_visual(
                            original,
                            removed_start=end - other_start,
                            new_duration=right_duration,
                        ),
                        right.id,
                    )
                    replacements.append(right)
                    created.append(right.id)
                    derived_created.append(right.id)
                    consequential.append(right.id)
                    created_automations.extend(
                        item.automation_id for item in right.visual_automations
                    )
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
            subtitle_cues=subtitle_cues,
            created_automations=created_automations,
            modified_automations=modified_automations,
            deleted_automations=deleted_automations,
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
        reverse: bool | None = None,
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
        if reverse is not None and any(
            clip.freeze_frame is not None for _, _, clip in members
        ):
            raise TimelineEditError(
                "Reverse playback is not defined for a frozen-frame clip"
            )
        if speed_factor is not None and any(
            clip.freeze_frame is not None for _, _, clip in members
        ):
            raise TimelineEditError(
                "Frozen-frame duration is explicit and cannot use speed_factor"
            )
        modified: list[str] = []
        consequential: list[str] = []
        modified_automations: list[str] = []
        for _, track, clip in members:
            before = clip.model_copy(deep=True)
            if speed_factor is not None:
                old_duration = clip_duration(clip)
                clip.speed_factor = speed_factor
                new_duration = clip_duration(clip)
                if clip.visual_automations:
                    ratio = new_duration / old_duration
                    clip.visual_automations = tuple(
                        automation.model_copy(
                            update={
                                "keyframes": tuple(
                                    point.model_copy(
                                        update={
                                            "offset_seconds": point.offset_seconds * ratio
                                        }
                                    )
                                    for point in automation.keyframes
                                )
                            }
                        )
                        for automation in clip.visual_automations
                    )
                    modified_automations.extend(
                        item.automation_id for item in clip.visual_automations
                    )
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
            if reverse is not None:
                clip.reverse = reverse
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
            modified_automations=modified_automations,
        )

    def set_freeze_frame(
        self,
        track_reference: str,
        clip_id: str,
        *,
        freeze_frame: FreezeFrameSettings | None,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Freeze-frame playback requires a video clip")
        if freeze_frame == clip.freeze_frame:
            raise TimelineEditError("Freeze-frame edit does not change the clip")
        if freeze_frame is not None and not (
            clip.trim_in <= freeze_frame.source_time_seconds < clip.trim_out
        ):
            raise TimelineEditError(
                "Freeze-frame source time must be inside the current source range"
            )
        clip.freeze_frame = freeze_frame
        if freeze_frame is not None:
            clip.reverse = False
            clip.keep_audio = False
        return self._finish(
            operation="set_freeze_frame",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            warnings=(
                "Freeze-frame playback is video-only and carries no embedded audio.",
            ) if freeze_frame is not None else (),
        )

    def set_clip_transform(
        self,
        track_reference: str,
        clip_id: str,
        *,
        transform: ClipTransform,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Visual transforms require a video track")
        if clip.transform == transform:
            raise TimelineEditError("Transform edit does not change the clip")
        clip.transform = transform
        return self._finish(
            operation="set_clip_transform",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
        )

    def set_clip_color(
        self,
        track_reference: str,
        clip_id: str,
        *,
        color: ClipColorAdjustment,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Color adjustment requires a video track")
        if clip.color == color:
            raise TimelineEditError("Color edit does not change the clip")
        clip.color = color
        return self._finish(
            operation="set_clip_color",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
        )

    def copy_clip_visual(
        self,
        source_track_id: str,
        source_clip_id: str,
        targets: Iterable[tuple[str, str]],
        *,
        components: str,
    ):
        source_key, source_track, source = self._clip(
            source_track_id, source_clip_id
        )
        if source_track.kind != "video":
            raise TimelineEditError("Visual copy source must be a video clip")
        resolved: list[tuple[str, TrackConfig, ClipConfig]] = []
        for track_id, clip_id in targets:
            key, track, clip = self._clip(track_id, clip_id)
            if track.kind != "video":
                raise TimelineEditError("Visual copy targets must be video clips")
            resolved.append((key, track, clip))
        prior = self.timeline.model_copy(deep=True)
        modified: list[str] = []
        try:
            for _, _, clip in resolved:
                before = clip.model_copy(deep=True)
                if components in {"transform", "both"}:
                    clip.transform = source.transform
                if components in {"color", "both"}:
                    clip.color = source.color
                if clip != before:
                    modified.append(clip.id)
            if not modified:
                raise TimelineEditError("Visual copy changes no target clip")
            primary_key, primary_track, _ = resolved[0]
            return self._finish(
                operation="copy_clip_visual",
                primary_key=primary_key,
                primary_track=primary_track,
                direct=tuple(modified),
                modified=tuple(modified),
                warnings=(
                    "Visual attributes copy only to the explicit clip IDs; linked audio is unchanged.",
                ),
            )
        except Exception:
            self.timeline = prior
            raise

    def upsert_visual_keyframe(
        self,
        track_reference: str,
        clip_id: str,
        *,
        automation_id: str,
        property_path: str,
        keyframe: VisualKeyframe,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Visual automation requires a video clip")
        if keyframe.offset_seconds > clip_duration(clip) + TIME_EPSILON:
            raise TimelineEditError("Visual keyframe exceeds clip-local duration")
        curves = list(clip.visual_automations)
        matches = [item for item in curves if item.automation_id == automation_id]
        created: tuple[str, ...] = ()
        modified: tuple[str, ...] = ()
        if matches:
            automation = matches[0]
            if automation.property_path != property_path:
                raise TimelineEditError(
                    "Automation ID cannot change its property path"
                )
            points = [
                point
                for point in automation.keyframes
                if point.keyframe_id != keyframe.keyframe_id
            ]
            duplicate_time = next(
                (
                    point
                    for point in points
                    if abs(point.offset_seconds - keyframe.offset_seconds)
                    <= TIME_EPSILON
                ),
                None,
            )
            if duplicate_time is not None:
                raise TimelineEditError(
                    "Visual keyframe time is already occupied by another ID"
                )
            points.append(keyframe)
            points.sort(key=lambda item: (item.offset_seconds, item.keyframe_id))
            replacement = automation.model_copy(update={"keyframes": tuple(points)})
            if replacement == automation:
                raise TimelineEditError("Visual keyframe edit changes nothing")
            curves[curves.index(automation)] = replacement
            modified = (automation_id,)
        else:
            if any(item.property_path == property_path for item in curves):
                raise TimelineEditError(
                    "Visual property already has a different automation ID"
                )
            if any(
                item.automation_id == automation_id
                for candidate in self.timeline.tracks.values()
                for current in candidate.clips
                for item in current.visual_automations
            ):
                raise TimelineEditError("Visual automation ID already exists")
            curves.append(
                VisualAutomation(
                    automation_id=automation_id,
                    clip_id=clip_id,
                    property_path=property_path,
                    keyframes=(keyframe,),
                )
            )
            created = (automation_id,)
        clip.visual_automations = tuple(
            sorted(curves, key=lambda item: (item.property_path, item.automation_id))
        )
        return self._finish(
            operation="upsert_visual_keyframe",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            created_automations=created,
            modified_automations=modified,
        )

    def delete_visual_keyframe(
        self,
        track_reference: str,
        clip_id: str,
        *,
        automation_id: str,
        keyframe_id: str,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Visual automation requires a video clip")
        automation = next(
            (
                item
                for item in clip.visual_automations
                if item.automation_id == automation_id
            ),
            None,
        )
        if automation is None:
            raise TimelineEditError("Visual automation ID is unknown")
        points = tuple(
            point for point in automation.keyframes if point.keyframe_id != keyframe_id
        )
        if len(points) == len(automation.keyframes):
            raise TimelineEditError("Visual keyframe ID is unknown")
        deleted: tuple[str, ...] = ()
        modified: tuple[str, ...] = ()
        if points:
            replacement = automation.model_copy(update={"keyframes": points})
            clip.visual_automations = tuple(
                replacement if item == automation else item
                for item in clip.visual_automations
            )
            modified = (automation_id,)
        else:
            clip.visual_automations = tuple(
                item for item in clip.visual_automations if item != automation
            )
            deleted = (automation_id,)
        return self._finish(
            operation="delete_visual_keyframe",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            modified_automations=modified,
            deleted_automations=deleted,
        )

    def replace_visual_automation(
        self,
        track_reference: str,
        clip_id: str,
        automation: VisualAutomation,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Visual automation requires a video clip")
        if automation.clip_id != clip_id:
            raise TimelineEditError("Automation must target the exact clip")
        if any(
            point.offset_seconds > clip_duration(clip) + TIME_EPSILON
            for point in automation.keyframes
        ):
            raise TimelineEditError("Visual curve exceeds clip-local duration")
        curves = list(clip.visual_automations)
        existing = next(
            (
                item
                for item in curves
                if item.automation_id == automation.automation_id
            ),
            None,
        )
        if existing is None:
            if any(item.property_path == automation.property_path for item in curves):
                raise TimelineEditError(
                    "Visual property already has a different automation ID"
                )
            curves.append(automation)
            created = (automation.automation_id,)
            modified: tuple[str, ...] = ()
        else:
            if existing.property_path != automation.property_path:
                raise TimelineEditError(
                    "Replacement cannot change an automation property path"
                )
            if existing == automation:
                raise TimelineEditError("Automation replacement changes nothing")
            curves[curves.index(existing)] = automation
            created = ()
            modified = (automation.automation_id,)
        clip.visual_automations = tuple(
            sorted(curves, key=lambda item: (item.property_path, item.automation_id))
        )
        return self._finish(
            operation="replace_visual_automation",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            created_automations=created,
            modified_automations=modified,
        )

    def clear_visual_automation(
        self,
        track_reference: str,
        clip_id: str,
        *,
        automation_id: str | None,
        property_path: str | None,
        clear_all: bool,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Visual automation requires a video clip")
        if clear_all:
            removed = clip.visual_automations
        else:
            removed = tuple(
                item
                for item in clip.visual_automations
                if (
                    (automation_id is not None and item.automation_id == automation_id)
                    or (property_path is not None and item.property_path == property_path)
                )
            )
        if not removed:
            raise TimelineEditError("No matching visual automation exists")
        clip.visual_automations = tuple(
            item for item in clip.visual_automations if item not in removed
        )
        return self._finish(
            operation="clear_visual_automation",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            deleted_automations=(item.automation_id for item in removed),
        )

    def copy_visual_automation(
        self,
        source_track_id: str,
        source_clip_id: str,
        targets: Iterable[tuple[str, str]],
        *,
        property_paths: tuple[str, ...],
    ):
        _, source_track, source = self._clip(source_track_id, source_clip_id)
        if source_track.kind != "video":
            raise TimelineEditError("Automation copy source must be video")
        selected = tuple(
            item
            for item in source.visual_automations
            if not property_paths or item.property_path in property_paths
        )
        if not selected:
            raise TimelineEditError("Source has no selected visual automation")
        resolved = [self._clip(track_id, clip_id) for track_id, clip_id in targets]
        prior = self.timeline.model_copy(deep=True)
        created: list[str] = []
        changed: list[str] = []
        try:
            for _, track, clip in resolved:
                if track.kind != "video":
                    raise TimelineEditError("Automation copy target must be video")
                existing_paths = {
                    item.property_path for item in clip.visual_automations
                }
                if any(item.property_path in existing_paths for item in selected):
                    raise TimelineEditError(
                        "Automation copy never overwrites an existing target curve"
                    )
                if any(
                    point.offset_seconds > clip_duration(clip) + TIME_EPSILON
                    for item in selected
                    for point in item.keyframes
                ):
                    raise TimelineEditError(
                        "Target clip is shorter than the copied automation curve"
                    )
                copied = self._copy_visual_curves(selected, clip.id)
                clip.visual_automations = tuple(
                    sorted(
                        (*clip.visual_automations, *copied),
                        key=lambda item: (item.property_path, item.automation_id),
                    )
                )
                created.extend(item.automation_id for item in copied)
                changed.append(clip.id)
            primary_key, primary_track, _ = resolved[0]
            return self._finish(
                operation="copy_visual_automation",
                primary_key=primary_key,
                primary_track=primary_track,
                direct=changed,
                modified=changed,
                created_automations=created,
                warnings=(
                    "Automation copied only to explicit video clip IDs; linked audio is unchanged.",
                ),
            )
        except Exception:
            self.timeline = prior
            raise

    def set_clip_mask(
        self,
        track_reference: str,
        clip_id: str,
        *,
        mask: ClipMask | None = None,
        mask_id: str | None = None,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Masks require a video/image clip")
        current = list(clip.masks)
        if mask is not None:
            matches = [item for item in current if item.mask_id == mask.mask_id]
            if len(matches) > 1:
                raise TimelineEditError("Mask ID is ambiguous")
            if matches and matches[0] == mask:
                raise TimelineEditError("Mask edit changes nothing")
            if matches:
                current[current.index(matches[0])] = mask
                created, modified = (), (mask.mask_id,)
            else:
                current.append(mask)
                created, modified = (mask.mask_id,), ()
            deleted = ()
        elif mask_id is not None:
            matches = [item for item in current if item.mask_id == mask_id]
            if len(matches) != 1:
                raise TimelineEditError("Mask ID must identify exactly one mask")
            current.remove(matches[0])
            created, modified, deleted = (), (), (mask_id,)
        else:
            raise TimelineEditError("Mask upsert or removal payload is required")
        clip.masks = tuple(sorted(current, key=lambda item: item.mask_id))
        return self._finish(
            operation="set_clip_mask",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            created_masks=created,
            modified_masks=modified,
            deleted_masks=deleted,
        )

    def replace_clip_masks(
        self,
        track_reference: str,
        clip_id: str,
        masks: tuple[ClipMask, ...],
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Masks require a video/image clip")
        ordered = tuple(sorted(masks, key=lambda item: item.mask_id))
        if clip.masks == ordered:
            raise TimelineEditError("Mask replacement changes nothing")
        before = {item.mask_id: item for item in clip.masks}
        after = {item.mask_id: item for item in ordered}
        clip.masks = ordered
        return self._finish(
            operation="replace_clip_masks",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            created_masks=sorted(after.keys() - before.keys()),
            deleted_masks=sorted(before.keys() - after.keys()),
            modified_masks=sorted(
                identity
                for identity in before.keys() & after.keys()
                if before[identity] != after[identity]
            ),
        )

    def copy_clip_masks(
        self,
        source_track_id: str,
        source_clip_id: str,
        targets: Iterable[tuple[str, str]],
        *,
        mask_ids: tuple[str, ...] = (),
        replace_existing: bool = False,
    ):
        source_key, source_track, source = self._clip(source_track_id, source_clip_id)
        if source_track.kind != "video":
            raise TimelineEditError("Mask copy source must be a video clip")
        selected = tuple(
            item for item in source.masks if not mask_ids or item.mask_id in set(mask_ids)
        )
        if not selected or (mask_ids and len(selected) != len(mask_ids)):
            raise TimelineEditError("Mask selectors must identify exact source masks")
        prior = self.timeline.model_copy(deep=True)
        modified: list[str] = []
        created_masks: list[str] = []
        deleted_masks: list[str] = []
        try:
            for target_track_id, target_clip_id in targets:
                _, target_track, target = self._clip(target_track_id, target_clip_id)
                if target_track.kind != "video":
                    raise TimelineEditError("Mask copy targets must be video clips")
                copied: list[ClipMask] = []
                for item in selected:
                    copied_id = self._copy_identity("mask", item.mask_id, target.id)
                    copied.append(
                        item.model_copy(
                            update={
                                "mask_id": copied_id,
                                "automations": tuple(
                                    curve.model_copy(
                                        update={
                                            "automation_id": self._copy_identity("maskauto", curve.automation_id, target.id),
                                            "mask_id": copied_id,
                                            "keyframes": tuple(
                                                point.model_copy(
                                                    update={"keyframe_id": self._copy_identity("maskkey", point.keyframe_id, target.id)}
                                                )
                                                for point in curve.keyframes
                                            ),
                                        }
                                    )
                                    for curve in item.automations
                                ),
                            }
                        )
                    )
                if replace_existing:
                    deleted_masks.extend(item.mask_id for item in target.masks)
                    target.masks = tuple(copied)
                else:
                    occupied = {item.mask_id for item in target.masks}
                    if any(item.mask_id in occupied for item in copied):
                        raise TimelineEditError("Copied mask identity already exists")
                    target.masks = tuple(sorted((*target.masks, *copied), key=lambda item: item.mask_id))
                created_masks.extend(item.mask_id for item in copied)
                modified.append(target.id)
            return self._finish(
                operation="copy_clip_masks",
                primary_key=source_key,
                primary_track=source_track,
                direct=(source_clip_id, *modified),
                modified=modified,
                created_masks=created_masks,
                deleted_masks=deleted_masks,
                warnings=("Masks copy only to explicit clip IDs; linked audio is unchanged.",),
            )
        except Exception:
            self.timeline = prior
            raise

    def set_clip_composite(
        self,
        track_reference: str,
        clip_id: str,
        composite: ClipCompositeSettings,
    ):
        key, track, clip = self._clip(track_reference, clip_id)
        if track.kind != "video":
            raise TimelineEditError("Compositing requires a video/image clip")
        if clip.composite == composite:
            raise TimelineEditError("Composite edit changes nothing")
        clip.composite = composite
        has_packaging = (
            composite.blend_mode != "normal"
            or composite.shadow_opacity > 0
            or composite.glow_strength > 0
        )
        warnings = (
            (
                "Non-normal blend, shadow, and glow require re-review if combined "
                "with a first-version transition on the same project."
            ),
        ) if has_packaging and any(item.enabled for item in self.timeline.transitions) else ()
        return self._finish(
            operation="set_clip_composite",
            primary_key=key,
            primary_track=track,
            direct=(clip_id,),
            modified=(clip_id,),
            warnings=warnings,
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
        content_role: str | None = None,
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
            ("content_role", content_role),
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

    def apply_audio_ducking(
        self,
        *,
        action: str,
        ducking_id: str,
        key_track_ids: tuple[str, ...],
        target_track_ids: tuple[str, ...],
        reduction_db: float,
        attack_seconds: float,
        release_seconds: float,
    ):
        """Bake one confirmed structural key/bed duck pass into clip envelopes."""

        target_tracks = [self._resolve_track(item) for item in target_track_ids]
        if any(track.kind != "audio" for _, track in target_tracks):
            raise TimelineEditError("Ducking targets must be exact audio tracks")
        prefix = f"duck_{ducking_id}_"
        if action == "remove":
            modified: list[str] = []
            for _, track in target_tracks:
                for clip in track.clips:
                    if clip.audio.ducking is None or clip.audio.ducking.ducking_id != ducking_id:
                        continue
                    points = tuple(
                        point for point in clip.audio.envelope
                        if not point.point_id.startswith(prefix)
                    )
                    clip.audio = clip.audio.model_copy(
                        update={"envelope": points, "ducking": None}
                    )
                    modified.append(clip.id)
            if not modified:
                raise TimelineEditError("The requested ducking pass is not applied")
            key, track = target_tracks[0]
            return self._finish(
                operation="apply_audio_ducking",
                primary_key=key,
                primary_track=track,
                direct=modified,
                modified=modified,
            )

        key_tracks = [
            self._resolve_track(item, allow_locked=True)
            for item in key_track_ids
        ]
        key_windows: list[tuple[float, float, str]] = []
        key_payload: list[dict[str, object]] = []
        for _, track in key_tracks:
            if track.kind not in {"audio", "video"}:
                raise TimelineEditError("Ducking keys must expose an audio component")
            for clip in sorted(track.clips, key=lambda item: (item.timeline_start, item.id)):
                active = track.kind == "audio" or clip.keep_audio
                if not active or track.muted or track.mix.muted or clip.audio.muted:
                    continue
                if clip.audio.content_role not in {"dialogue", "voiceover"}:
                    raise TimelineEditError(
                        "Ducking key clips must be explicitly dialogue or voiceover"
                    )
                start, end = clip.timeline_start, clip_end(clip)
                key_windows.append((start, end, clip.id))
                key_payload.append({
                    "track_id": track.id,
                    "clip_id": clip.id,
                    "start": start,
                    "end": end,
                    "role": clip.audio.content_role,
                })
        if not key_windows:
            raise TimelineEditError("Ducking keys contain no active declared speech")
        key_digest = hashlib.sha256(
            json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        ordered_windows = sorted((start, end) for start, end, _ in key_windows)
        merged: list[list[float]] = []
        bridge = attack_seconds + release_seconds
        for start, end in ordered_windows:
            if merged and start <= merged[-1][1] + bridge + TIME_EPSILON:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

        modified: list[str] = []
        counter = 0
        for _, track in target_tracks:
            for clip in sorted(track.clips, key=lambda item: (item.timeline_start, item.id)):
                if clip.audio.content_role not in {
                    "background_music", "sound_effect", "ambience"
                }:
                    raise TimelineEditError(
                        "Ducking targets must be declared music, sound effects, or ambience"
                    )
                if clip.audio.envelope and (
                    clip.audio.ducking is None
                    or clip.audio.ducking.ducking_id != ducking_id
                    or any(
                        not point.point_id.startswith(prefix)
                        for point in clip.audio.envelope
                    )
                ):
                    raise TimelineEditError(
                        "Ducking does not overwrite a manual or different envelope"
                    )
                start, end = clip.timeline_start, clip_end(clip)
                points: list[AudioEnvelopePoint] = []
                for key_start, key_end in merged:
                    active_start = max(start, key_start)
                    active_end = min(end, key_end)
                    if active_end <= active_start + TIME_EPSILON:
                        continue
                    attack_start = max(start, active_start - attack_seconds)
                    release_end = min(end, active_end + release_seconds)
                    shape = [(attack_start, 0.0), (active_start, reduction_db)]
                    if active_end > active_start + TIME_EPSILON:
                        shape.append((active_end, reduction_db))
                    if release_end > active_end + TIME_EPSILON:
                        shape.append((release_end, 0.0))
                    for absolute_time, gain in shape:
                        offset = max(0.0, absolute_time - start)
                        if points and abs(points[-1].offset_seconds - offset) <= TIME_EPSILON:
                            points[-1] = points[-1].model_copy(update={"gain_db": gain})
                            continue
                        counter += 1
                        points.append(AudioEnvelopePoint(
                            point_id=f"{prefix}{counter:04d}",
                            offset_seconds=offset,
                            gain_db=gain,
                        ))
                if not points:
                    continue
                clip.audio = clip.audio.model_copy(update={
                    "envelope": tuple(points),
                    "ducking": AppliedAudioDucking(
                        ducking_id=ducking_id,
                        key_track_ids=key_track_ids,
                        key_timeline_digest=key_digest,
                        reduction_db=reduction_db,
                        attack_seconds=attack_seconds,
                        release_seconds=release_seconds,
                    ),
                })
                modified.append(clip.id)
        if not modified:
            raise TimelineEditError("Ducking keys do not overlap any target clip")
        key, track = target_tracks[0]
        return self._finish(
            operation="apply_audio_ducking",
            primary_key=key,
            primary_track=track,
            direct=modified,
            modified=modified,
            warnings=(
                "Ducking is a confirmed structural occupancy pass, not signal detection.",
            ),
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
