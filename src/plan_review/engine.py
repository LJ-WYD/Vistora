"""Deterministic, side-effect-free simulation of proposed atomic edit steps.

This module deliberately operates only on detached timeline snapshots.  It
validates arguments with the registered tools' Pydantic input models, but it
never calls a skill, timeline manager, renderer, proxy generator, or trace
writer.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePath
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from contracts import PlanReference
from timeline_edit import (
    AppliedAudioDucking,
    AudioEnvelopePoint,
    ClipAudioSettings,
    ClipColorAdjustment,
    ClipCompositeSettings,
    ClipConfig,
    ClipMask,
    MaskAutomation,
    MaskPoint,
    ClipTransform,
    FreezeFrameSettings,
    TimelineConfig,
    TimelineTransition,
    TransitionParameters,
    VisualAutomation,
    VisualKeyframe,
    TimelineEditEngine,
    TimelineEditError,
    TrackConfig,
    TrackMixSettings,
)
from audio_analysis import clip_audio_state_digest
from subtitles import (
    SubtitleCue,
    SubtitleCodecError,
    SubtitleEditCueInput,
    SubtitleEditEngine,
    SubtitleEditError,
    SubtitleManageTrackInput,
    SubtitleStyle,
    SubtitleTrackConfig,
    SubtitleWord,
    parse_subtitles,
)
from timeline_query import TimelineSnapshot, TimelineSnapshotReference

from .models import (
    PlanChange,
    PlanDiffDocument,
    PlanDiffRequest,
    PlanDiffSummary,
    PlanStepPreview,
    PreviewAudioDuckingState,
    PreviewClipState,
    PreviewMaterialFact,
    PreviewProjectSettings,
    PreviewSubtitleCueState,
    PreviewSubtitleTrackState,
    PreviewTransitionState,
    PreviewTrackMixState,
    ProposedEntityReference,
    ProposedExecutionReference,
    RegistrySchemaReference,
    digest_json,
    evidence_summaries,
)


class PlanDiffValidationError(ValueError):
    """A proposal cannot be reviewed safely against the supplied state."""


_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]|\\\\)[^\s,;]+"
    r"|(?<![\w:])/(?:[^/\s]+/)+[^/\s,;]+"
)


def _redact_path_text(value: str) -> str:
    return _ABSOLUTE_PATH_PATTERN.sub("[redacted-path]", value)


def _source_id(configured_path: str) -> str:
    if re.fullmatch(r"material://source_[0-9a-f]{16}", configured_path):
        return configured_path.removeprefix("material://")
    return (
        "source_"
        + digest_json({"configured_path": configured_path})[7:23]
    )


def _display_name(configured_path: str) -> str:
    if configured_path.startswith("material://"):
        return configured_path.removeprefix("material://")
    normalized = configured_path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or PurePath(configured_path).name


def _clip_state(
    clip: Any,
    track_key: str,
    track_id: str | None = None,
) -> PreviewClipState:
    return PreviewClipState(
        clip_id=clip.clip_id,
        track_key=track_key,
        track_id=track_id or track_key,
        order_index=clip.order_index,
        source_id=clip.source.source_id,
        source_name=clip.source.display_name,
        trim_in_seconds=clip.trim_in_seconds,
        trim_out_seconds=clip.trim_out_seconds,
        timeline_start_seconds=clip.timeline_start_seconds,
        timeline_end_seconds=clip.timeline_end_seconds,
        effective_duration_seconds=clip.effective_duration_seconds,
        volume=clip.volume,
        speed_factor=clip.speed_factor,
        keep_audio=clip.keep_audio,
        reverse=clip.reverse,
        freeze_frame_source_time_seconds=clip.freeze_frame_source_time_seconds,
        freeze_frame_duration_seconds=clip.freeze_frame_duration_seconds,
        rotate_degrees=clip.rotate_degrees,
        link_group_id=clip.link_group_id,
        audio_gain_db=clip.audio_gain_db,
        audio_content_role=clip.audio_content_role,
        audio_muted=clip.audio_muted,
        audio_pan=clip.audio_pan,
        audio_fade_in_seconds=clip.audio_fade_in_seconds,
        audio_fade_out_seconds=clip.audio_fade_out_seconds,
        audio_envelope=clip.audio_envelope,
        loudness_analysis_id=clip.loudness_analysis_id,
        audio_ducking=(
            PreviewAudioDuckingState.model_validate(
                clip.audio_ducking.model_dump(
                    mode="json", exclude={"schema_name", "schema_version"}
                )
            )
            if clip.audio_ducking is not None
            else None
        ),
        transform=clip.transform.model_dump(mode="python"),
        color=clip.color.model_dump(mode="python"),
        visual_automations=tuple(
            item.model_dump(mode="json") for item in clip.visual_automations
        ),
        automation_digest=clip.automation_digest,
        masks=tuple(item.model_dump(mode="json") for item in clip.masks),
        composite=clip.composite.model_dump(mode="json"),
        mask_digest=clip.mask_digest,
    )


def _replace_clip(
    clip: PreviewClipState,
    **changes: Any,
) -> PreviewClipState:
    values = clip.model_dump(mode="python")
    values.update(changes)
    duration = (
        values["freeze_frame_duration_seconds"]
        if values.get("freeze_frame_duration_seconds") is not None
        else (
            values["trim_out_seconds"] - values["trim_in_seconds"]
        ) / values["speed_factor"]
    )
    values["effective_duration_seconds"] = duration
    values["timeline_end_seconds"] = (
        values["timeline_start_seconds"] + duration
    )
    return PreviewClipState.model_validate(values)


def _core_visual_automation(value: Any) -> VisualAutomation:
    """Convert browser-safe snapshot/review data back to the core contract."""
    if isinstance(value, VisualAutomation):
        return value
    data = value.model_dump(mode="python") if isinstance(value, BaseModel) else dict(value)
    return VisualAutomation(
        automation_id=data["automation_id"],
        clip_id=data["clip_id"],
        property_path=data["property_path"],
        enabled=data.get("enabled", True),
        keyframes=tuple(
            VisualKeyframe(
                keyframe_id=point["keyframe_id"],
                offset_seconds=point["offset_seconds"],
                value=point["value"],
                interpolation=point["interpolation"],
            )
            for point in data["keyframes"]
        ),
    )


def _core_mask(value: Any) -> ClipMask:
    """Convert browser-safe mask state back to its strict core contract."""
    if isinstance(value, ClipMask):
        return value
    data = value.model_dump(mode="python") if isinstance(value, BaseModel) else dict(value)
    return ClipMask(
        mask_id=data["mask_id"],
        kind=data["kind"],
        operation=data["operation"],
        enabled=data.get("enabled", True),
        invert=data.get("invert", False),
        opacity=data.get("opacity", 1),
        feather=data.get("feather", 0),
        expand=data.get("expand", 0),
        position_x=data.get("position_x", .5),
        position_y=data.get("position_y", .5),
        scale_x=data.get("scale_x", 1),
        scale_y=data.get("scale_y", 1),
        rotation_degrees=data.get("rotation_degrees", 0),
        width=data.get("width"),
        height=data.get("height"),
        points=tuple(
            MaskPoint(point_id=point["point_id"], x=point["x"], y=point["y"])
            for point in data.get("points", ())
        ),
        automations=tuple(
            MaskAutomation(
                automation_id=curve["automation_id"],
                mask_id=curve["mask_id"],
                property_path=curve["property_path"],
                enabled=curve.get("enabled", True),
                keyframes=tuple(
                    VisualKeyframe(
                        keyframe_id=point["keyframe_id"],
                        offset_seconds=point["offset_seconds"],
                        value=point["value"],
                        interpolation=point["interpolation"],
                    )
                    for point in curve["keyframes"]
                ),
            )
            for curve in data.get("automations", ())
        ),
    )


def _core_composite(value: Any) -> ClipCompositeSettings:
    if isinstance(value, ClipCompositeSettings):
        return value
    data = value.model_dump(mode="python") if isinstance(value, BaseModel) else dict(value)
    return ClipCompositeSettings(blend_mode=data.get("blend_mode", "normal"))


def _snapshot_matches(
    expected: TimelineSnapshotReference,
    snapshot: TimelineSnapshot,
) -> bool:
    return expected == TimelineSnapshotReference.from_snapshot(snapshot)


def _timeline_duration(clips: list[PreviewClipState]) -> float:
    return max(
        (clip.timeline_end_seconds for clip in clips),
        default=0.0,
    )


def _timeline_from_snapshot(snapshot: TimelineSnapshot) -> TimelineConfig:
    timeline = TimelineConfig(
        width=snapshot.width,
        height=snapshot.height,
        fps=snapshot.fps,
    )
    for track in snapshot.tracks:
        timeline.tracks[track.track_key] = TrackConfig(
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
                    visual_kind=clip.visual_kind,
                    trim_in=clip.trim_in_seconds,
                    trim_out=clip.trim_out_seconds,
                    timeline_start=clip.timeline_start_seconds,
                    volume=clip.volume,
                    keep_audio=clip.keep_audio,
                    speed_factor=clip.speed_factor,
                    reverse=clip.reverse,
                    freeze_frame=(
                        FreezeFrameSettings(
                            source_time_seconds=clip.freeze_frame_source_time_seconds,
                            duration_seconds=clip.freeze_frame_duration_seconds,
                        )
                        if clip.freeze_frame_source_time_seconds is not None
                        and clip.freeze_frame_duration_seconds is not None
                        else None
                    ),
                    rotate=clip.rotate_degrees,
                    link_group_id=clip.link_group_id,
                    audio=ClipAudioSettings(
                        gain_db=clip.audio_gain_db,
                        content_role=clip.audio_content_role,
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
                        ducking=(
                            AppliedAudioDucking.model_validate(
                                clip.audio_ducking.model_dump(
                                    mode="python",
                                    exclude={"schema_name", "schema_version"},
                                )
                            )
                            if clip.audio_ducking is not None
                            else None
                        ),
                    ),
                    transform=ClipTransform.model_validate(
                        clip.transform.model_dump(mode="python")
                    ),
                    color=ClipColorAdjustment.model_validate(
                        clip.color.model_dump(mode="python")
                    ),
                    visual_automations=tuple(
                        VisualAutomation(
                            automation_id=item.automation_id,
                            clip_id=item.clip_id,
                            property_path=item.property_path,
                            enabled=item.enabled,
                            keyframes=tuple(
                                VisualKeyframe(
                                    keyframe_id=point.keyframe_id,
                                    offset_seconds=point.offset_seconds,
                                    value=point.value,
                                    interpolation=point.interpolation,
                                )
                                for point in item.keyframes
                            ),
                        )
                        for item in clip.visual_automations
                    ),
                    masks=tuple(_core_mask(item) for item in clip.masks),
                    composite=_core_composite(clip.composite),
                )
                for clip in track.clips
            ],
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
                    cue_kind=cue.cue_kind,
                    start_seconds=cue.start_seconds,
                    end_seconds=cue.end_seconds,
                    text=cue.text,
                    language=cue.language,
                    speaker=cue.speaker,
                    enabled=cue.enabled,
                    settings=cue.settings,
                    style=(
                        SubtitleStyle.model_validate(cue.style.model_dump(mode="python", exclude={"schema_name"}))
                        if cue.style is not None
                        else None
                    ),
                    words=tuple(
                        SubtitleWord(
                            word_id=word.word_id,
                            start_seconds=word.start_seconds,
                            end_seconds=word.end_seconds,
                            text=word.text,
                            confidence=word.confidence,
                        )
                        for word in cue.words
                    ),
                )
                for cue in track.cues
            ),
        )
        for track in snapshot.subtitle_tracks
    }
    timeline.transitions = {
        transition.transition_id: TimelineTransition(
            transition_id=transition.transition_id,
            track_id=transition.track_id,
            from_clip_id=transition.from_clip_id,
            to_clip_id=transition.to_clip_id,
            kind=transition.kind,
            duration_seconds=transition.duration_seconds,
            alignment=transition.alignment,
            parameters=TransitionParameters(
                direction=transition.direction,
                color=transition.color,
            ),
            enabled=transition.enabled,
            audio_policy=transition.audio_policy,
            paired_transition_id=transition.paired_transition_id,
        )
        for transition in snapshot.transitions
    }
    return TimelineConfig.model_validate(timeline.model_dump(mode="python"))


def _transition_map(
    timeline: TimelineConfig,
) -> dict[str, PreviewTransitionState]:
    return {
        transition.transition_id: PreviewTransitionState(
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
            timeline.transitions.values(),
            key=lambda item: item.transition_id,
        )
    }


def _subtitle_maps(timeline: TimelineConfig) -> tuple[
    dict[str, PreviewSubtitleTrackState], dict[tuple[str, str], PreviewSubtitleCueState]
]:
    tracks: dict[str, PreviewSubtitleTrackState] = {}
    cues: dict[tuple[str, str], PreviewSubtitleCueState] = {}
    for track in sorted(timeline.subtitle_tracks.values(), key=lambda item: (item.order, item.track_id)):
        tracks[track.track_id] = PreviewSubtitleTrackState(
            track_id=track.track_id,
            kind=track.kind,
            role=track.role,
            language=track.language,
            order=track.order,
            enabled=track.enabled,
            locked=track.locked,
            allow_overlaps=track.allow_overlaps,
            style=track.style.model_dump(mode="json"),
            cue_count=len(track.cues),
        )
        for cue in track.cues:
            cues[(track.track_id, cue.cue_id)] = PreviewSubtitleCueState(
                cue_id=cue.cue_id,
                track_id=track.track_id,
                cue_kind=cue.cue_kind,
                start_seconds=cue.start_seconds,
                end_seconds=cue.end_seconds,
                text=cue.text,
                language=cue.language,
                speaker=cue.speaker,
                enabled=cue.enabled,
                style=cue.style.model_dump(mode="json") if cue.style is not None else None,
                words=tuple(word.model_dump(mode="json") for word in cue.words),
            )
    return tracks, cues


def _preview_state(
    clip: ClipConfig,
    track_key: str,
    track_id: str,
) -> PreviewClipState:
    duration = (
        clip.freeze_frame.duration_seconds
        if clip.freeze_frame is not None
        else (clip.trim_out - clip.trim_in) / clip.speed_factor
    )
    return PreviewClipState(
        clip_id=clip.id,
        visual_kind=clip.visual_kind,
        track_key=track_key,
        track_id=track_id,
        order_index=0,
        source_id=_source_id(clip.source),
        source_name=_display_name(clip.source),
        trim_in_seconds=clip.trim_in,
        trim_out_seconds=clip.trim_out,
        timeline_start_seconds=clip.timeline_start,
        timeline_end_seconds=clip.timeline_start + duration,
        effective_duration_seconds=duration,
        volume=clip.volume,
        speed_factor=clip.speed_factor,
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
            PreviewAudioDuckingState.model_validate(
                clip.audio.ducking.model_dump(
                    mode="json", exclude={"schema_name", "schema_version"}
                )
            )
            if clip.audio.ducking is not None
            else None
        ),
        transform=clip.transform.model_dump(
            mode="python", exclude={"schema_name", "schema_version"}
        ),
        color=clip.color.model_dump(
            mode="python", exclude={"schema_name", "schema_version"}
        ),
        visual_automations=tuple(
            item.model_dump(mode="json") for item in clip.visual_automations
        ),
        automation_digest=digest_json(
            [item.model_dump(mode="json") for item in clip.visual_automations]
        ),
        masks=tuple(item.model_dump(mode="json") for item in clip.masks),
        composite=clip.composite.model_dump(mode="json"),
        mask_digest=digest_json({
            "masks": [item.model_dump(mode="json") for item in clip.masks],
            "composite": clip.composite.model_dump(mode="json"),
        }),
    )


def _preview_map(timeline: TimelineConfig) -> dict[
    tuple[str, str], PreviewClipState
]:
    result = {}
    for track_key, track in sorted(
        timeline.tracks.items(),
        key=lambda item: (item[1].order, item[1].id, item[0]),
    ):
        for index, clip in enumerate(
            sorted(track.clips, key=lambda item: (item.timeline_start, item.id))
        ):
            state = _preview_state(clip, track_key, track.id).model_copy(
                update={"order_index": index}
            )
            result[(track_key, clip.id)] = state
    return result


class PlanDiffEngine:
    """Simulate previewable tools against a detached timeline copy."""

    @staticmethod
    def generate(
        request: PlanDiffRequest,
        snapshot: TimelineSnapshot,
        registry: Mapping[str, Any],
    ) -> PlanDiffDocument:
        if (
            request.snapshot_ref.snapshot_id is None
            or request.snapshot_ref.timeline_digest is None
        ):
            raise PlanDiffValidationError(
                "Plan review requires an exact snapshot ID and digest"
            )
        if not _snapshot_matches(request.snapshot_ref, snapshot):
            raise PlanDiffValidationError(
                "Timeline snapshot drifted; regenerate the review"
            )

        try:
            current_registry_ref = RegistrySchemaReference.from_registry(
                registry
            )
        except (TypeError, ValueError) as exc:
            raise PlanDiffValidationError(
                f"Atomic registry cannot be reviewed: {exc}"
            ) from exc
        if request.registry_ref != current_registry_ref:
            raise PlanDiffValidationError(
                "Atomic registry or tool schema drifted; regenerate the review"
            )

        evidence_by_id = {
            evidence.evidence_id: evidence
            for evidence in request.director_plan.source_evidence
        }
        operation_by_id = {
            operation.operation_id: operation
            for operation in request.director_plan.operations
        }
        facts = {fact.material_id: fact for fact in request.material_facts}
        source_aliases: dict[str, PreviewMaterialFact] = {}
        ambiguous_source_aliases: set[str] = set()
        for track in snapshot.tracks:
            for clip in track.clips:
                fact = facts.get(clip.source.source_id)
                if fact is not None:
                    for alias in (
                        clip.source.value,
                        clip.source.display_name,
                    ):
                        if alias in ambiguous_source_aliases:
                            continue
                        current = source_aliases.get(alias)
                        if current is not None and current != fact:
                            source_aliases.pop(alias, None)
                            ambiguous_source_aliases.add(alias)
                        else:
                            source_aliases[alias] = fact
        facts.update(source_aliases)
        video_track = next(
            (
                track
                for track in snapshot.tracks
                if track.kind == "video"
                and track.enabled
                and track.role == "primary"
            ),
            None,
        )
        clips = (
            [
                _clip_state(
                    clip,
                    video_track.track_key,
                    video_track.track_id,
                )
                for clip in video_track.clips
            ]
            if video_track is not None
            else []
        )
        provenance = {
            clip.clip_id: clip.provenance
            for track in snapshot.tracks
            for clip in track.clips
        }
        core_timeline = _timeline_from_snapshot(snapshot)
        before_clip_count = snapshot.clip_count
        before_subtitle_cue_count = snapshot.subtitle_cue_count
        before_transition_count = snapshot.transition_count
        before_duration = snapshot.duration_seconds
        project_settings = PreviewProjectSettings(
            width=snapshot.width,
            height=snapshot.height,
            fps=snapshot.fps,
        )
        before_project_settings = project_settings
        changes: list[PlanChange] = []
        step_previews: list[PlanStepPreview] = []

        def append_change(
            *,
            step: Any,
            category: str,
            effect_kind: str,
            severity: str,
            entity: ProposedEntityReference,
            reason: str,
            before: PreviewClipState | None = None,
            after: PreviewClipState | None = None,
            before_project: PreviewProjectSettings | None = None,
            after_project: PreviewProjectSettings | None = None,
            before_track_mix: PreviewTrackMixState | None = None,
            after_track_mix: PreviewTrackMixState | None = None,
            before_subtitle_cue: PreviewSubtitleCueState | None = None,
            after_subtitle_cue: PreviewSubtitleCueState | None = None,
            before_subtitle_track: PreviewSubtitleTrackState | None = None,
            after_subtitle_track: PreviewSubtitleTrackState | None = None,
            before_transition: PreviewTransitionState | None = None,
            after_transition: PreviewTransitionState | None = None,
        ) -> PlanChange:
            sequence = len(changes) + 1
            identity = {
                "request": request.digest(),
                "sequence": sequence,
                "step": step.step_id,
                "category": category,
                "entity": entity.model_dump(mode="json"),
            }
            change = PlanChange(
                change_id=f"change_{digest_json(identity)[7:31]}",
                sequence=sequence,
                category=category,
                effect_kind=effect_kind,
                severity=severity,
                operation_id=step.source_operation_id,
                step_id=step.step_id,
                tool_name=step.tool_name,
                director_rationale=_redact_path_text(
                    operation_by_id[
                        step.source_operation_id
                    ].rationale
                ),
                expected_effect=_redact_path_text(
                    operation_by_id[
                        step.source_operation_id
                    ].expected_effect
                ),
                entity=entity,
                before=before,
                after=after,
                before_project=before_project,
                after_project=after_project,
                before_track_mix=before_track_mix,
                after_track_mix=after_track_mix,
                before_subtitle_cue=before_subtitle_cue,
                after_subtitle_cue=after_subtitle_cue,
                before_subtitle_track=before_subtitle_track,
                after_subtitle_track=after_subtitle_track,
                before_transition=before_transition,
                after_transition=after_transition,
                reason=reason,
                evidence=evidence_summaries(
                    tuple(
                        evidence_by_id[evidence_id]
                        for evidence_id in step.evidence_ids
                    )
                ),
                current_provenance=(
                    provenance.get(entity.entity_id)
                    if entity.entity_kind == "clip"
                    else None
                ),
            )
            changes.append(change)
            return change

        for step in request.proposed_execution.steps:
            skill = registry.get(step.tool_name)
            if skill is None:
                raise PlanDiffValidationError(
                    f"Proposed step {step.step_id} uses an unregistered tool"
                )
            input_model = getattr(skill, "input_model", None)
            if not isinstance(input_model, type) or not issubclass(
                input_model,
                BaseModel,
            ):
                raise PlanDiffValidationError(
                    f"Tool {step.tool_name} has no valid input schema"
                )
            try:
                params = input_model.model_validate(step.arguments)
            except ValidationError as exc:
                raise PlanDiffValidationError(
                    f"Step {step.step_id} has invalid arguments: {exc}"
                ) from exc

            start_index = len(changes)
            status = "previewed"
            message = "Step has a deterministic detached preview."

            if step.tool_name == "VideoAddClipSkill":
                status, message, project_settings = (
                    PlanDiffEngine._preview_add(
                        step=step,
                        params=params,
                        clips=clips,
                        facts=facts,
                        append_change=append_change,
                        request=request,
                        snapshot=snapshot,
                        project_settings=project_settings,
                    )
                )
            elif step.tool_name == "VideoModifyClipSkill":
                status, message = PlanDiffEngine._preview_modify(
                    step=step,
                    params=params,
                    clips=clips,
                    append_change=append_change,
                )
            elif step.tool_name in {
                "VideoSplitClipSkill",
                "VideoTrimClipSkill",
                "VideoMoveClipSkill",
                "VideoInsertOverwriteClipSkill",
                "VideoInsertGraphicSkill",
                "VideoRemoveClipSkill",
                "VideoSetClipPropertiesSkill",
                "VideoSetClipFreezeFrameSkill",
                "TimelineManageTrackSkill",
                "TimelineSetClipLinkSkill",
                "AudioSetClipPropertiesSkill",
                "AudioApplyDuckingSkill",
                "AudioSetTrackMixSkill",
                "AudioSetVolumeEnvelopeSkill",
                "VideoSetClipTransformSkill",
                "VideoSetClipColorSkill",
                "VideoCopyClipVisualSkill",
                "TimelineAddTransitionSkill",
                "TimelineUpdateTransitionSkill",
                "TimelineRemoveTransitionSkill",
                "TimelineCopyTransitionSkill",
                "VideoUpsertVisualKeyframeSkill",
                "VideoDeleteVisualKeyframeSkill",
                "VideoReplaceVisualAutomationSkill",
                "VideoClearVisualAutomationSkill",
                "VideoCopyVisualAutomationSkill",
                "VideoSetClipMaskSkill",
                "VideoReplaceClipMasksSkill",
                "VideoCopyClipMasksSkill",
                "VideoSetClipCompositeSkill",
            }:
                # Synchronize only the legacy primary-video view; every other
                # stable multi-track declaration remains detached and intact.
                if video_track is not None:
                    primary = core_timeline.tracks[video_track.track_key]
                    primary.clips = [
                        ClipConfig(
                            id=clip.clip_id,
                            source=clip.source_name,
                            visual_kind=clip.visual_kind,
                            trim_in=clip.trim_in_seconds,
                            trim_out=clip.trim_out_seconds,
                            timeline_start=clip.timeline_start_seconds,
                            volume=clip.volume,
                            keep_audio=clip.keep_audio,
                            speed_factor=clip.speed_factor,
                            reverse=clip.reverse,
                            freeze_frame=(
                                FreezeFrameSettings(
                                    source_time_seconds=clip.freeze_frame_source_time_seconds,
                                    duration_seconds=clip.freeze_frame_duration_seconds,
                                )
                                if clip.freeze_frame_source_time_seconds is not None
                                and clip.freeze_frame_duration_seconds is not None
                                else None
                            ),
                            rotate=clip.rotate_degrees,
                            link_group_id=clip.link_group_id,
                            audio=ClipAudioSettings(
                                gain_db=clip.audio_gain_db,
                                content_role=clip.audio_content_role,
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
                                ducking=(
                                    AppliedAudioDucking.model_validate(
                                        clip.audio_ducking.model_dump(
                                            mode="python",
                                            exclude={"schema_name", "schema_version"},
                                        )
                                    )
                                    if clip.audio_ducking is not None
                                    else None
                                ),
                            ),
                            transform=ClipTransform.model_validate(
                                clip.transform.model_dump(mode="python")
                            ),
                            color=ClipColorAdjustment.model_validate(
                                clip.color.model_dump(mode="python")
                            ),
                            visual_automations=tuple(
                                _core_visual_automation(item)
                                for item in clip.visual_automations
                            ),
                            masks=tuple(_core_mask(item) for item in clip.masks),
                            composite=_core_composite(clip.composite),
                        )
                        for clip in clips
                    ]
                status, message, core_timeline = (
                    PlanDiffEngine._preview_core_edit(
                        step=step,
                        params=params,
                        timeline=core_timeline,
                        facts=facts,
                        append_change=append_change,
                        request=request,
                    )
                )
                project_settings = PreviewProjectSettings(
                    width=core_timeline.width,
                    height=core_timeline.height,
                    fps=core_timeline.fps,
                )
                clips = [
                    state
                    for (track_key, _), state in sorted(
                        _preview_map(core_timeline).items()
                    )
                    if video_track is not None
                    and track_key == video_track.track_key
                ]
            elif step.tool_name == "AudioAnalyzeLoudnessSkill":
                target = next(
                    (
                        clip
                        for track in snapshot.tracks
                        if track.track_id == params.track_id
                        for clip in track.clips
                        if clip.clip_id == params.clip_id
                    ),
                    None,
                )
                if target is None:
                    raise PlanDiffValidationError(
                        "Loudness analysis target is absent from the snapshot"
                    )
                state = _clip_state(
                    target,
                    next(
                        track.track_key
                        for track in snapshot.tracks
                        if track.track_id == params.track_id
                    ),
                    params.track_id,
                )
                append_change(
                    step=step,
                    category="audio_analysis",
                    effect_kind="informational",
                    severity="info",
                    entity=ProposedEntityReference(
                        entity_kind="clip",
                        entity_id=params.clip_id,
                        track_id=params.track_id,
                        track_key=state.track_key,
                    ),
                    before=state,
                    after=state,
                    reason=(
                        "This read-only step measures exact clip loudness; it "
                        "does not apply gain or change project state."
                    ),
                )
                message = "Read-only loudness analysis is safely previewable."
            elif step.tool_name in {
                "SubtitleManageTrackSkill",
                "SubtitleEditCueSkill",
                "SubtitleImportSkill",
            }:
                status, message, core_timeline = PlanDiffEngine._preview_subtitle_edit(
                    step=step,
                    params=params,
                    timeline=core_timeline,
                    append_change=append_change,
                )
            elif step.tool_name == "SubtitleExportSidecarSkill":
                selected = set(params.track_ids)
                known = {track.track_id for track in core_timeline.subtitle_tracks.values()}
                if selected - known:
                    raise PlanDiffValidationError("Subtitle export references an unknown track")
                cue_count = sum(
                    1
                    for track in core_timeline.subtitle_tracks.values()
                    if not selected or track.track_id in selected
                    for cue in track.cues
                    if track.enabled and cue.enabled
                )
                append_change(
                    step=step,
                    category="subtitle_export",
                    effect_kind="informational",
                    severity="info" if cue_count else "blocker",
                    entity=ProposedEntityReference(
                        entity_kind="media_output",
                        entity_id=f"subtitle_output_{digest_json({'step': step.step_id})[7:23]}",
                    ),
                    reason=(
                        f"The confirmed step writes {cue_count} enabled cues as a deterministic {params.format.upper()} sidecar."
                        if cue_count
                        else "Subtitle sidecar export has no enabled cues."
                    ),
                )
                if not cue_count:
                    status = "unsupported"
                    message = "Sidecar export requires an enabled cue."
                else:
                    message = "Sidecar export is previewed without writing a file."
            elif step.tool_name == "VideoClearTimelineSkill":
                removed = list(clips)
                clips.clear()
                for clip in removed:
                    append_change(
                        step=step,
                        category="clip_removal",
                        effect_kind="direct",
                        severity="info",
                        entity=ProposedEntityReference(
                            entity_kind="clip",
                            entity_id=clip.clip_id,
                            track_key=clip.track_key,
                        ),
                        before=clip,
                        reason="The clear-timeline step removes this clip.",
                    )
                project_settings = PlanDiffEngine._reset_project_settings(
                    step=step,
                    project_settings=project_settings,
                    append_change=append_change,
                    effect_kind="direct",
                    severity="info",
                    reason=(
                        "Clearing the timeline resets canvas and frame rate "
                        "to TimelineManager defaults."
                    ),
                    project_id=snapshot.project_id,
                )
                core_timeline = TimelineConfig(
                    width=project_settings.width,
                    height=project_settings.height,
                    fps=project_settings.fps,
                    tracks={
                        "video": TrackConfig(id="video"),
                        "audio": TrackConfig(id="audio"),
                    },
                )
                message = (
                    f"Clears {len(removed)} detached video clip(s)."
                    if removed
                    else "The timeline is already empty."
                )
            elif step.tool_name == "VideoExportVariantsSkill":
                if not clips:
                    raise PlanDiffValidationError(
                        f"Step {step.step_id} cannot export an empty timeline"
                    )
                if params.subtitle_mode == "burn":
                    selected = set(params.subtitle_track_ids)
                    known = {track.track_id for track in core_timeline.subtitle_tracks.values()}
                    if selected - known:
                        raise PlanDiffValidationError("Subtitle burn references an unknown track")
                    enabled_cues = [
                        cue
                        for track in core_timeline.subtitle_tracks.values()
                        if track.enabled and (not selected or track.track_id in selected)
                        for cue in track.cues
                        if cue.enabled
                    ]
                    if not enabled_cues:
                        append_change(
                            step=step,
                            category="warning",
                            effect_kind="informational",
                            severity="blocker",
                            entity=ProposedEntityReference(
                                entity_kind="none",
                                entity_id=f"subtitle_burn_{step.step_id}",
                            ),
                            reason=(
                                "Subtitle burn-in requires at least one enabled cue "
                                "and a video stream."
                            ),
                        )
                        status = "unsupported"
                for variant in params.variants:
                    append_change(
                        step=step,
                        category="export_only",
                        effect_kind="informational",
                        severity="info",
                        entity=ProposedEntityReference(
                            entity_kind="media_output",
                            entity_id=f"export_variant_{variant.variant_id}",
                        ),
                        reason=(
                            f"Would render variant {variant.variant_id} at "
                            f"{variant.width}x{variant.height} and {variant.fps:g} fps; "
                            "the preview does not render or disclose filesystem paths."
                        ),
                    )
                message = (
                    f"Would export {len(params.variants)} create-new media variants "
                    "without changing the timeline."
                )
            elif step.tool_name == "VideoExportSkill":
                if not clips:
                    raise PlanDiffValidationError(
                        f"Step {step.step_id} cannot export an empty timeline"
                    )
                if not params.output_path.strip():
                    raise PlanDiffValidationError(
                        f"Step {step.step_id} has an empty output path"
                    )
                if params.subtitle_mode == "burn":
                    selected = set(params.subtitle_track_ids)
                    known = {track.track_id for track in core_timeline.subtitle_tracks.values()}
                    if selected - known:
                        raise PlanDiffValidationError("Subtitle burn references an unknown track")
                    enabled_cues = [
                        cue
                        for track in core_timeline.subtitle_tracks.values()
                        if track.enabled and (not selected or track.track_id in selected)
                        for cue in track.cues
                        if cue.enabled
                    ]
                    if not enabled_cues:
                        append_change(
                            step=step,
                            category="warning",
                            effect_kind="informational",
                            severity="blocker",
                            entity=ProposedEntityReference(entity_kind="none", entity_id=f"subtitle_burn_{step.step_id}"),
                            reason="Subtitle burn-in requires at least one enabled cue and a video stream.",
                        )
                        status = "unsupported"
                        message = "Subtitle burn-in is not currently executable."
                append_change(
                    step=step,
                    category="export_only",
                    effect_kind="informational",
                    severity="info",
                    entity=ProposedEntityReference(
                        entity_kind="media_output",
                        entity_id=(
                            "output_"
                            + digest_json(
                                {
                                    "request": request.request_id,
                                    "step": step.step_id,
                                }
                            )[7:23]
                        ),
                    ),
                    reason=(
                        "This step would export media; the preview does not "
                        "render or disclose an output filesystem path."
                    ),
                )
                if params.clear_timeline_after:
                    removed = list(clips)
                    clips.clear()
                    for clip in removed:
                        append_change(
                            step=step,
                            category="clip_removal",
                            effect_kind="consequential",
                            severity="warning",
                            entity=ProposedEntityReference(
                                entity_kind="clip",
                                entity_id=clip.clip_id,
                                track_key=clip.track_key,
                            ),
                            before=clip,
                            reason=(
                                "Export is configured to clear the timeline "
                                "after a successful render."
                            ),
                        )
                    project_settings = (
                        PlanDiffEngine._reset_project_settings(
                            step=step,
                            project_settings=project_settings,
                            append_change=append_change,
                            effect_kind="consequential",
                            severity="warning",
                            reason=(
                                "A successful export configured to clear "
                                "the timeline also restores default project "
                                "settings."
                            ),
                            project_id=snapshot.project_id,
                        )
                    )
                    core_timeline = TimelineConfig(
                        width=project_settings.width,
                        height=project_settings.height,
                        fps=project_settings.fps,
                        tracks={
                            "video": TrackConfig(id="video"),
                            "audio": TrackConfig(id="audio"),
                        },
                    )
                    status = "warning"
                    message = (
                        "Export itself is non-mutating until execution; a "
                        "successful export would then clear the timeline."
                    )
            elif step.tool_name in {
                "VideoTimelapseSkill",
                "VideoApplyManualEditsSkill",
            }:
                append_change(
                    step=step,
                    category="warning",
                    effect_kind="informational",
                    severity="blocker",
                    entity=ProposedEntityReference(
                        entity_kind="none",
                        entity_id=f"unpreviewable_{step.step_id}",
                    ),
                    reason=(
                        "This registered tool is intentionally unavailable to "
                        "Director plan preview: it writes generated media or "
                        "belongs to the separate user-authored manual-edit "
                        "boundary."
                    ),
                )
                status = "unsupported"
                message = "The step is registered but not safely previewable."
            else:
                append_change(
                    step=step,
                    category="warning",
                    effect_kind="informational",
                    severity="blocker",
                    entity=ProposedEntityReference(
                        entity_kind="none",
                        entity_id=f"unsupported_{step.step_id}",
                    ),
                    reason=(
                        "The tool schema is registered, but this plan-review "
                        "version has no detached semantic adapter for it."
                    ),
                )
                status = "unsupported"
                message = "No detached simulator exists for this tool."

            step_changes = tuple(
                change.change_id for change in changes[start_index:]
            )
            step_previews.append(
                PlanStepPreview(
                    step_id=step.step_id,
                    operation_id=step.source_operation_id,
                    tool_name=step.tool_name,
                    status=status,
                    change_ids=step_changes,
                    message=message,
                )
            )

        warnings = sum(change.severity == "warning" for change in changes)
        blockers = sum(change.severity == "blocker" for change in changes)
        additions = sum(
            change.category in {
                "clip_addition",
                "subtitle_cue_addition",
                "transition_addition",
            }
            for change in changes
        )
        removals = sum(
            change.category in {
                "clip_removal",
                "subtitle_cue_removal",
                "transition_removal",
            }
            for change in changes
        )
        consequential = sum(
            change.effect_kind == "consequential" for change in changes
        )
        modifications = sum(
            change.category
            in {
                "clip_trim",
                "clip_timing",
                "clip_reorder",
                "clip_speed",
                "clip_properties",
                "clip_freeze_frame",
                "clip_transform",
                "clip_color",
                "visual_automation",
                "clip_audio",
                "audio_envelope",
                "track_mix",
                "project_settings",
                "subtitle_track",
                "subtitle_cue_change",
                "transition_change",
            }
            for change in changes
        )
        review_status = (
            "blocked" if blockers else "warning" if warnings else "ready"
        )
        request_digest = request.digest()
        diff_identity = {
            "request_digest": request_digest,
            "snapshot": request.snapshot_ref.model_dump(mode="json"),
            "changes": [
                change.model_dump(mode="json") for change in changes
            ],
        }
        # Synchronize legacy video-only operations before aggregate totals.
        core_timeline.tracks["video"] = TrackConfig(
            id="video",
            clips=[
                ClipConfig(
                    id=clip.clip_id,
                    source=clip.source_name,
                    trim_in=clip.trim_in_seconds,
                    trim_out=clip.trim_out_seconds,
                    timeline_start=clip.timeline_start_seconds,
                    volume=clip.volume,
                    keep_audio=clip.keep_audio,
                    speed_factor=clip.speed_factor,
                    reverse=clip.reverse,
                    freeze_frame=(
                        FreezeFrameSettings(
                            source_time_seconds=clip.freeze_frame_source_time_seconds,
                            duration_seconds=clip.freeze_frame_duration_seconds,
                        )
                        if clip.freeze_frame_source_time_seconds is not None
                        and clip.freeze_frame_duration_seconds is not None
                        else None
                    ),
                    rotate=clip.rotate_degrees,
                    transform=ClipTransform.model_validate(
                        clip.transform.model_dump(mode="python")
                    ),
                    color=ClipColorAdjustment.model_validate(
                        clip.color.model_dump(mode="python")
                    ),
                    visual_automations=tuple(
                        _core_visual_automation(item)
                        for item in clip.visual_automations
                    ),
                    masks=tuple(ClipMask.model_validate(item) for item in clip.masks),
                    composite=ClipCompositeSettings.model_validate(clip.composite),
                )
                for clip in clips
            ],
        )
        after_states = _preview_map(core_timeline)
        return PlanDiffDocument(
            diff_id=f"diff_{digest_json(diff_identity)[7:31]}",
            request_digest=request_digest,
            snapshot_ref=request.snapshot_ref,
            plan_ref=PlanReference.from_plan(request.director_plan),
            execution_ref=ProposedExecutionReference.from_execution(
                request.proposed_execution
            ),
            registry_ref=request.registry_ref,
            review_status=review_status,
            steps=tuple(step_previews),
            changes=tuple(changes),
            summary=PlanDiffSummary(
                total_changes=len(changes),
                additions=additions,
                removals=removals,
                modifications=modifications,
                consequential=consequential,
                warnings=warnings,
                blockers=blockers,
                before_clip_count=before_clip_count,
                after_clip_count=len(after_states),
                before_subtitle_cue_count=before_subtitle_cue_count,
                after_subtitle_cue_count=sum(
                    len(track.cues) for track in core_timeline.subtitle_tracks.values()
                ),
                before_transition_count=before_transition_count,
                after_transition_count=len(core_timeline.transitions),
                before_duration_seconds=before_duration,
                after_duration_seconds=max(
                    (
                        state.timeline_end_seconds
                        for state in after_states.values()
                    ),
                    default=0.0,
                ),
                before_project=before_project_settings,
                after_project=project_settings,
            ),
        )

    @staticmethod
    def _preview_subtitle_edit(
        *,
        step: Any,
        params: BaseModel,
        timeline: TimelineConfig,
        append_change: Any,
    ) -> tuple[str, str, TimelineConfig]:
        before_tracks, before_cues = _subtitle_maps(timeline)
        try:
            engine = SubtitleEditEngine(timeline)
            if step.tool_name == "SubtitleManageTrackSkill":
                updated, outcome = engine.manage_track(params)
            elif step.tool_name == "SubtitleEditCueSkill":
                updated, outcome = engine.edit_cues(params)
            else:
                if params.input_path is not None:
                    append_change(
                        step=step,
                        category="warning",
                        effect_kind="informational",
                        severity="blocker",
                        entity=ProposedEntityReference(
                            entity_kind="none",
                            entity_id=f"subtitle_import_path_{step.step_id}",
                        ),
                        reason="Filesystem subtitle import is not read during detached preview; provide reviewed inline UTF-8 content.",
                    )
                    return "unsupported", "External subtitle input must be re-reviewed with bounded content.", timeline
                cues = parse_subtitles(params.content or "", params.format, language=params.language)
                if params.create_track:
                    engine.manage_track(SubtitleManageTrackInput(
                        action="create", track_id=params.track_id, kind="subtitle", language=params.language,
                    ))
                key, track = engine._find_track(params.track_id)
                if params.replace_existing:
                    engine._replace_track(key, track.model_copy(update={"cues": ()}))
                updated, outcome = engine.edit_cues(
                    SubtitleEditCueInput(
                        action="batch_add",
                        track_id=params.track_id,
                        cues=cues,
                    )
                )
        except (SubtitleEditError, SubtitleCodecError) as exc:
            raise PlanDiffValidationError(str(exc)) from exc

        after_tracks, after_cues = _subtitle_maps(updated)
        direct = set(outcome.direct_cue_ids)
        for track_id in sorted(before_tracks.keys() | after_tracks.keys()):
            old, new = before_tracks.get(track_id), after_tracks.get(track_id)
            if old == new:
                continue
            append_change(
                step=step,
                category="subtitle_track",
                effect_kind="direct",
                severity="info",
                entity=ProposedEntityReference(entity_kind="subtitle_track", entity_id=track_id, track_id=track_id),
                before_subtitle_track=old,
                after_subtitle_track=new,
                reason="The proposal changes a first-class subtitle/text track.",
            )
        for key in sorted(before_cues.keys() | after_cues.keys()):
            old, new = before_cues.get(key), after_cues.get(key)
            if old == new:
                continue
            category = "subtitle_cue_addition" if old is None else "subtitle_cue_removal" if new is None else "subtitle_cue_change"
            append_change(
                step=step,
                category=category,
                effect_kind="direct" if key[1] in direct else "consequential",
                severity="info",
                entity=ProposedEntityReference(entity_kind="subtitle_cue", entity_id=key[1], track_id=key[0]),
                before_subtitle_cue=old,
                after_subtitle_cue=new,
                reason="The proposal creates, removes, or precisely changes this subtitle cue.",
            )
        return "previewed", f"Deterministically previews subtitle operation {outcome.operation}.", updated

    @staticmethod
    def _preview_core_edit(
        *,
        step: Any,
        params: BaseModel,
        timeline: TimelineConfig,
        facts: Mapping[str, PreviewMaterialFact],
        append_change: Any,
        request: PlanDiffRequest,
    ) -> tuple[str, str, TimelineConfig]:
        before = _preview_map(timeline)
        before_track_mix = {
            track.id: PreviewTrackMixState(
                track_id=track.id,
                gain_db=track.mix.gain_db,
                muted=track.mix.muted,
                pan=track.mix.pan,
            )
            for track in timeline.tracks.values()
        }
        before_transitions = _transition_map(timeline)
        def preview_id(prefix: str) -> str:
            return (
                f"{prefix}_"
                + digest_json(
                    {
                        "request": request.request_id,
                        "step": step.step_id,
                        "count": len(before),
                    }
                )[7:23]
            )
        try:
            def duration_fact(clip: ClipConfig) -> float:
                source_id = _source_id(clip.source)
                fact = facts.get(clip.source) or facts.get(source_id)
                if fact is None:
                    raise TimelineEditError(
                        "Transition preview requires exact opaque media facts "
                        f"for {source_id}"
                    )
                if fact.duration_seconds is None:
                    raise TimelineEditError(
                        "Transition preview requires a timed media source"
                    )
                return fact.duration_seconds

            def audio_fact(clip: ClipConfig) -> bool:
                fact = facts.get(clip.source) or facts.get(
                    _source_id(clip.source)
                )
                if fact is None or fact.has_audio is None:
                    raise TimelineEditError(
                        "Audio transition preview requires exact audio-stream facts"
                    )
                return fact.has_audio

            engine = TimelineEditEngine(
                timeline,
                id_factory=preview_id,
                source_duration_resolver=duration_fact,
                source_audio_resolver=audio_fact,
            )
            name = step.tool_name
            if name == "VideoSplitClipSkill":
                updated, outcome = engine.split(
                    params.track_reference,
                    params.clip_id,
                    params.split_at_seconds,
                    right_clip_id=params.right_clip_id,
                    edit_scope=params.edit_scope,
                )
            elif name == "VideoTrimClipSkill":
                updated, outcome = engine.trim(
                    params.track_reference,
                    params.clip_id,
                    params.trim_in,
                    params.trim_out,
                    ripple=params.ripple,
                    edit_scope=params.edit_scope,
                    subtitle_ripple=params.subtitle_ripple,
                )
            elif name == "VideoMoveClipSkill":
                updated, outcome = engine.move(
                    params.track_reference,
                    params.clip_id,
                    params.timeline_start,
                    ripple=params.ripple,
                    edit_scope=params.edit_scope,
                    subtitle_ripple=params.subtitle_ripple,
                )
            elif name == "VideoRemoveClipSkill":
                updated, outcome = engine.remove(
                    params.track_reference,
                    params.clip_id,
                    ripple=params.mode == "ripple",
                    edit_scope=params.edit_scope,
                    subtitle_ripple=params.subtitle_ripple,
                )
            elif name == "VideoSetClipPropertiesSkill":
                updated, outcome = engine.set_properties(
                    params.track_reference,
                    params.clip_id,
                    speed_factor=params.speed_factor,
                    volume=params.volume,
                    keep_audio=params.keep_audio,
                    mute=params.mute,
                    rotate=params.rotate,
                    reverse=params.reverse,
                    edit_scope=params.edit_scope,
                )
            elif name == "VideoSetClipFreezeFrameSkill":
                updated, outcome = engine.set_freeze_frame(
                    params.track_reference,
                    params.clip_id,
                    freeze_frame=(
                        params.freeze_frame if params.action == "set" else None
                    ),
                )
            elif name == "AudioSetClipPropertiesSkill":
                if params.normalization_evidence is not None:
                    _, evidence_track, evidence_clip = engine.clip_state(
                        params.track_reference, params.clip_id
                    )
                    if (
                        params.gain_db
                        != params.normalization_evidence.applied_gain_db
                        or params.normalization_evidence.analyzed_clip_digest
                        != clip_audio_state_digest(
                            evidence_track.id, evidence_clip
                        )
                    ):
                        raise PlanDiffValidationError(
                            "Loudness application evidence is stale or mismatched"
                        )
                updated, outcome = engine.set_clip_audio(
                    params.track_reference,
                    params.clip_id,
                    gain_db=params.gain_db,
                    muted=params.muted,
                    pan=params.pan,
                    fade_in_seconds=params.fade_in_seconds,
                    fade_out_seconds=params.fade_out_seconds,
                    playback_rate=params.playback_rate,
                    content_role=params.content_role,
                    normalization=params.normalization_evidence,
                )
            elif name == "AudioApplyDuckingSkill":
                updated, outcome = engine.apply_audio_ducking(
                    action=params.action,
                    ducking_id=params.ducking_id,
                    key_track_ids=params.key_track_ids,
                    target_track_ids=params.target_track_ids,
                    reduction_db=params.reduction_db,
                    attack_seconds=params.attack_seconds,
                    release_seconds=params.release_seconds,
                )
            elif name == "VideoSetClipTransformSkill":
                updated, outcome = engine.set_clip_transform(
                    params.track_reference,
                    params.clip_id,
                    transform=params.transform or ClipTransform(),
                )
            elif name == "VideoSetClipColorSkill":
                updated, outcome = engine.set_clip_color(
                    params.track_reference,
                    params.clip_id,
                    color=params.color or ClipColorAdjustment(),
                )
            elif name == "VideoCopyClipVisualSkill":
                updated, outcome = engine.copy_clip_visual(
                    params.source_track_id,
                    params.source_clip_id,
                    (
                        (target.track_id, target.clip_id)
                        for target in params.targets
                    ),
                    components=params.components,
                )
            elif name == "AudioSetTrackMixSkill":
                updated, outcome = engine.set_track_mix(
                    params.track_id,
                    gain_db=params.gain_db,
                    muted=params.muted,
                    pan=params.pan,
                )
            elif name == "AudioSetVolumeEnvelopeSkill":
                updated, outcome = engine.set_volume_envelope(
                    params.track_reference,
                    params.clip_id,
                    action=params.action,
                    point_id=params.point_id,
                    offset_seconds=params.offset_seconds,
                    gain_db=params.gain_db,
                )
            elif name == "TimelineManageTrackSkill":
                updated, outcome = engine.manage_track(
                    action=params.action,
                    track_id=params.track_id,
                    kind=params.kind,
                    role=params.role,
                    order=params.order,
                    enabled=params.enabled,
                    muted=params.muted,
                    locked=params.locked,
                )
            elif name == "TimelineSetClipLinkSkill":
                updated, outcome = engine.set_clip_link(
                    action=params.action,
                    members=(
                        (member.track_id, member.clip_id)
                        for member in params.members
                    ),
                    link_group_id=params.link_group_id,
                )
            elif name == "TimelineAddTransitionSkill":
                updated, outcome = engine.add_transition(
                    params.transition,
                    paired_transition=params.paired_transition,
                )
            elif name == "TimelineUpdateTransitionSkill":
                updated, outcome = engine.update_transition(
                    params.transition,
                    paired_transition=params.paired_transition,
                )
            elif name == "TimelineRemoveTransitionSkill":
                updated, outcome = engine.remove_transition(
                    params.transition_id,
                    include_paired=params.include_paired,
                )
            elif name == "TimelineCopyTransitionSkill":
                source = engine.timeline.transitions.get(
                    params.source_transition_id
                )
                if source is None:
                    raise TimelineEditError(
                        "Source transition ID is unknown"
                    )
                source_pair = (
                    engine.timeline.transitions.get(
                        source.paired_transition_id
                    )
                    if source.paired_transition_id is not None
                    else None
                )
                copied_pairs = []
                for target in params.targets:
                    if source_pair is None and target.paired_transition_id:
                        raise TimelineEditError(
                            "Unpaired source cannot create an audio pair"
                        )
                    if source_pair is not None and not target.paired_transition_id:
                        raise TimelineEditError(
                            "Paired source requires an explicit audio cut"
                        )
                    copied = source.model_copy(update={
                        "transition_id": target.transition_id,
                        "track_id": target.track_id,
                        "from_clip_id": target.from_clip_id,
                        "to_clip_id": target.to_clip_id,
                        "paired_transition_id": target.paired_transition_id,
                    })
                    copied_pair = None
                    if source_pair is not None:
                        copied_pair = source_pair.model_copy(update={
                            "transition_id": target.paired_transition_id,
                            "track_id": target.paired_track_id,
                            "from_clip_id": target.paired_from_clip_id,
                            "to_clip_id": target.paired_to_clip_id,
                            "paired_transition_id": target.transition_id,
                        })
                    copied_pairs.append((copied, copied_pair))
                updated, outcome = engine.copy_transition(
                    params.source_transition_id,
                    tuple(copied_pairs),
                )
            elif name == "VideoUpsertVisualKeyframeSkill":
                updated, outcome = engine.upsert_visual_keyframe(
                    params.track_reference,
                    params.clip_id,
                    automation_id=params.automation_id,
                    property_path=params.property_path,
                    keyframe=params.keyframe,
                )
            elif name == "VideoDeleteVisualKeyframeSkill":
                updated, outcome = engine.delete_visual_keyframe(
                    params.track_reference,
                    params.clip_id,
                    automation_id=params.automation_id,
                    keyframe_id=params.keyframe_id,
                )
            elif name == "VideoReplaceVisualAutomationSkill":
                updated, outcome = engine.replace_visual_automation(
                    params.track_reference,
                    params.clip_id,
                    params.automation,
                )
            elif name == "VideoClearVisualAutomationSkill":
                updated, outcome = engine.clear_visual_automation(
                    params.track_reference,
                    params.clip_id,
                    automation_id=params.automation_id,
                    property_path=params.property_path,
                    clear_all=params.scope == "all",
                )
            elif name == "VideoCopyVisualAutomationSkill":
                updated, outcome = engine.copy_visual_automation(
                    params.source_track_id,
                    params.source_clip_id,
                    ((item.track_id, item.clip_id) for item in params.targets),
                    property_paths=params.property_paths,
                )
            elif name == "VideoSetClipMaskSkill":
                updated, outcome = engine.set_clip_mask(
                    params.track_reference,
                    params.clip_id,
                    mask=params.mask,
                    mask_id=params.mask_id,
                )
            elif name == "VideoReplaceClipMasksSkill":
                updated, outcome = engine.replace_clip_masks(
                    params.track_reference, params.clip_id, params.masks
                )
            elif name == "VideoCopyClipMasksSkill":
                updated, outcome = engine.copy_clip_masks(
                    params.source_track_id,
                    params.source_clip_id,
                    ((item.track_id, item.clip_id) for item in params.targets),
                    mask_ids=params.mask_ids,
                    replace_existing=params.replace_existing,
                )
            elif name == "VideoSetClipCompositeSkill":
                updated, outcome = engine.set_clip_composite(
                    params.track_reference,
                    params.clip_id,
                    params.composite or ClipCompositeSettings(),
                )
            elif name == "VideoInsertGraphicSkill":
                material_id = _source_id(params.source_path)
                fact = facts.get(material_id)
                if fact is None:
                    append_change(
                        step=step,
                        category="warning",
                        effect_kind="informational",
                        severity="blocker",
                        entity=ProposedEntityReference(
                            entity_kind="none",
                            entity_id=f"missing_graphic_fact_{step.step_id}",
                        ),
                        reason=(
                            "Graphic insertion requires exact opaque image facts "
                            "for detached simulation."
                        ),
                    )
                    return (
                        "unsupported",
                        "Required graphic preview facts are missing.",
                        timeline,
                    )
                if fact.media_kind != "image":
                    raise PlanDiffValidationError(
                        "Graphic insertion requires a validated image material"
                    )
                if engine.track_kind(params.track_reference) != "video":
                    raise PlanDiffValidationError(
                        "Graphic insertion requires a video track"
                    )
                updated, outcome = engine.insert_overwrite(
                    params.track_reference,
                    ClipConfig(
                        id=params.clip_id,
                        source=params.source_path,
                        visual_kind=params.graphic_kind,
                        trim_in=0,
                        trim_out=params.duration_seconds,
                        timeline_start=params.timeline_start,
                        keep_audio=False,
                        speed_factor=1,
                        transform=params.transform,
                    ),
                    mode=params.mode,
                    edit_scope="current_clip",
                )
            else:
                material_id = _source_id(params.source_path)
                fact = facts.get(material_id)
                if fact is None:
                    append_change(
                        step=step,
                        category="warning",
                        effect_kind="informational",
                        severity="blocker",
                        entity=ProposedEntityReference(
                            entity_kind="none",
                            entity_id=f"missing_fact_{step.step_id}",
                        ),
                        reason=(
                            "Insert/overwrite requires an exact opaque material "
                            "duration fact for detached simulation."
                        ),
                    )
                    return (
                        "unsupported",
                        "Required preview media facts are missing.",
                        timeline,
                    )
                track_kind = engine.track_kind(params.track_reference)
                if fact.media_kind != track_kind:
                    raise PlanDiffValidationError(
                        "Insert material kind differs from the selected track"
                    )
                if (
                    track_kind == "video"
                    and not any(
                        track.clips
                        for track in engine.timeline.tracks.values()
                        if track.kind == "video"
                    )
                    and fact.width is not None
                    and fact.height is not None
                ):
                    engine.timeline.width = fact.width
                    engine.timeline.height = fact.height
                trim_out = min(
                    fact.duration_seconds or 0,
                    params.trim_out
                    if params.trim_out is not None
                    else (fact.duration_seconds or 0),
                )
                if trim_out <= params.trim_in:
                    raise PlanDiffValidationError(
                        "Insert/overwrite source range is empty"
                    )
                clip_id = params.clip_id or (
                    "proposed_clip_"
                    + digest_json({
                        "request": request.request_id,
                        "step": step.step_id,
                    })[7:23]
                )
                updated, outcome = engine.insert_overwrite(
                    params.track_reference,
                    ClipConfig(
                        id=clip_id,
                        source=params.source_path,
                        trim_in=params.trim_in,
                        trim_out=trim_out,
                        timeline_start=params.timeline_start,
                        speed_factor=params.speed_factor,
                        volume=params.volume,
                        keep_audio=params.keep_audio,
                        rotate=params.rotate,
                        link_group_id=params.link_group_id,
                    ),
                    mode=params.mode,
                    edit_scope=params.edit_scope,
                    subtitle_ripple=params.subtitle_ripple,
                )
        except TimelineEditError as exc:
            raise PlanDiffValidationError(str(exc)) from exc

        after = _preview_map(updated)
        after_transitions = _transition_map(updated)
        direct = set(outcome.direct_clip_ids)
        for key in sorted(before.keys() | after.keys()):
            old, new = before.get(key), after.get(key)
            effect = "direct" if key[1] in direct else "consequential"
            if old is None:
                category = "clip_addition"
                reason = "The confirmed edit creates this clip."
            elif new is None:
                category = "clip_removal"
                reason = "The confirmed edit removes this clip."
            elif old == new:
                continue
            elif old.link_group_id != new.link_group_id:
                category = "clip_linkage"
                reason = "The edit changes explicit clip linkage."
            elif (
                old.freeze_frame_source_time_seconds
                != new.freeze_frame_source_time_seconds
                or old.freeze_frame_duration_seconds
                != new.freeze_frame_duration_seconds
            ):
                category = "clip_freeze_frame"
                reason = (
                    "The edit sets, changes, or clears deterministic "
                    "freeze-frame playback."
                )
            elif (
                old.trim_in_seconds != new.trim_in_seconds
                or old.trim_out_seconds != new.trim_out_seconds
            ):
                category = "clip_trim"
                reason = "The edit changes the clip source range."
            elif old.timeline_start_seconds != new.timeline_start_seconds:
                category = "clip_timing"
                reason = "The edit changes the timeline position."
            elif old.speed_factor != new.speed_factor:
                category = "clip_speed"
                reason = "The edit changes speed and effective duration."
            elif old.visual_automations != new.visual_automations:
                category = "visual_automation"
                reason = (
                    "The edit changes seek-safe clip-local visual keyframes."
                )
            elif old.masks != new.masks:
                category = "clip_mask"
                reason = "The edit changes validated clip masks or mask keyframes."
            elif old.composite != new.composite:
                category = "clip_composite"
                reason = "The edit changes the bounded clip compositing mode."
            elif old.transform != new.transform:
                category = "clip_transform"
                reason = (
                    "The edit changes bounded canvas-relative transform values."
                )
            elif old.color != new.color:
                category = "clip_color"
                reason = "The edit changes bounded deterministic SDR color values."
            elif old.audio_ducking != new.audio_ducking:
                category = "audio_ducking"
                reason = "The edit applies or removes a confirmed structural ducking envelope."
            elif old.audio_envelope != new.audio_envelope:
                category = "audio_envelope"
                reason = "The edit changes the linear clip gain envelope."
            elif any(
                getattr(old, field) != getattr(new, field)
                for field in (
                    "audio_gain_db",
                    "audio_content_role",
                    "audio_muted",
                    "audio_pan",
                    "audio_fade_in_seconds",
                    "audio_fade_out_seconds",
                    "loudness_analysis_id",
                )
            ):
                category = "clip_audio"
                reason = "The edit changes bounded clip audio properties."
            else:
                category = "clip_properties"
                reason = "The edit changes playback properties."
            append_change(
                step=step,
                category=category,
                effect_kind=effect,
                severity="info",
                entity=ProposedEntityReference(
                    entity_kind="clip",
                    entity_id=key[1],
                    track_key=key[0],
                    track_id=(new or old).track_id,
                ),
                before=old,
                after=new,
                reason=reason,
            )
        direct_transitions = set(outcome.created_transition_ids)
        direct_transitions.update(outcome.modified_transition_ids)
        if outcome.operation == "remove_transition":
            direct_transitions.update(outcome.deleted_transition_ids)
        for transition_id in sorted(
            before_transitions.keys() | after_transitions.keys()
        ):
            old = before_transitions.get(transition_id)
            new = after_transitions.get(transition_id)
            if old == new:
                continue
            category = (
                "transition_addition"
                if old is None
                else "transition_removal"
                if new is None
                else "transition_change"
            )
            append_change(
                step=step,
                category=category,
                effect_kind=(
                    "direct"
                    if transition_id in direct_transitions
                    else "consequential"
                ),
                severity="info",
                entity=ProposedEntityReference(
                    entity_kind="transition",
                    entity_id=transition_id,
                    track_id=(new or old).track_id,
                ),
                before_transition=old,
                after_transition=new,
                reason=(
                    "The proposal creates, changes, or removes one exact "
                    "first-class transition at an adjacent cut."
                ),
            )
        if outcome.operation == "manage_track":
            append_change(
                step=step,
                category="track_management",
                effect_kind="direct",
                severity="info",
                entity=ProposedEntityReference(
                    entity_kind="track",
                    entity_id=outcome.track_id,
                    track_key=outcome.track_key,
                    track_id=outcome.track_id,
                ),
                reason="The proposal changes a stable timeline track.",
            )
        if outcome.operation == "set_track_mix":
            changed_track = next(
                track
                for track in updated.tracks.values()
                if track.id == outcome.track_id
            )
            append_change(
                step=step,
                category="track_mix",
                effect_kind="direct",
                severity="info",
                entity=ProposedEntityReference(
                    entity_kind="track",
                    entity_id=outcome.track_id,
                    track_key=outcome.track_key,
                    track_id=outcome.track_id,
                ),
                before_track_mix=before_track_mix[outcome.track_id],
                after_track_mix=PreviewTrackMixState(
                    track_id=changed_track.id,
                    gain_db=changed_track.mix.gain_db,
                    muted=changed_track.mix.muted,
                    pan=changed_track.mix.pan,
                ),
                reason="The proposal changes deterministic audio-track mix settings.",
            )
        for warning_index, warning in enumerate(outcome.warnings, start=1):
            append_change(
                step=step,
                category="warning",
                effect_kind="informational",
                severity="warning",
                entity=ProposedEntityReference(
                    entity_kind="none",
                    entity_id=f"warning_{step.step_id}_{warning_index}",
                ),
                reason=warning,
            )
        return (
            "warning" if outcome.warnings else "previewed",
            (
                f"Deterministically previews {outcome.operation} on "
                f"{outcome.track_key}."
            ),
            updated,
        )

    @staticmethod
    def _preview_add(
        *,
        step: Any,
        params: BaseModel,
        clips: list[PreviewClipState],
        facts: Mapping[str, PreviewMaterialFact],
        append_change: Any,
        request: PlanDiffRequest,
        snapshot: TimelineSnapshot,
        project_settings: PreviewProjectSettings,
    ) -> tuple[str, str, PreviewProjectSettings]:
        if params.reverse:
            append_change(
                step=step,
                category="warning",
                effect_kind="informational",
                severity="blocker",
                entity=ProposedEntityReference(
                    entity_kind="none",
                    entity_id=f"reverse_proxy_{step.step_id}",
                ),
                reason=(
                    "Reverse add requires proxy-media generation and therefore "
                    "cannot run inside the read-only preview boundary."
                ),
            )
            return (
                "unsupported",
                "Reverse proxy generation is unpreviewable.",
                project_settings,
            )

        if not params.source_path.strip():
            raise PlanDiffValidationError(
                f"Step {step.step_id} has an empty source path"
            )
        material_id = _source_id(params.source_path)
        fact = facts.get(material_id)
        if fact is None:
            append_change(
                step=step,
                category="warning",
                effect_kind="informational",
                severity="blocker",
                entity=ProposedEntityReference(
                    entity_kind="none",
                    entity_id=f"missing_fact_{step.step_id}",
                ),
                reason=(
                    "The proposal lacks opaque, bounded media facts for this "
                    "source, so duration and trim behavior cannot be claimed."
                ),
            )
            return (
                "unsupported",
                "Required preview media facts are missing.",
                project_settings,
            )
        if fact.media_kind != "video":
            raise PlanDiffValidationError(
                f"Step {step.step_id} cannot add a non-video material"
            )

        trim_in = max(0.0, params.trim_in or 0.0)
        trim_out = min(
            fact.duration_seconds,
            (
                params.trim_out
                if params.trim_out is not None
                else fact.duration_seconds
            ),
        )
        if trim_in >= trim_out:
            raise PlanDiffValidationError(
                f"Step {step.step_id} has an invalid bounded trim range"
            )
        if params.speed_factor <= 0:
            raise PlanDiffValidationError(
                f"Step {step.step_id} has a non-positive speed factor"
            )

        was_empty = not clips
        timeline_start = (
            clips[-1].timeline_end_seconds if clips else 0.0
        )
        provisional_id = (
            "proposed_clip_"
            + digest_json(
                {
                    "request": request.request_id,
                    "step": step.step_id,
                    "snapshot": snapshot.snapshot_id,
                }
            )[7:23]
        )
        duration = (trim_out - trim_in) / params.speed_factor
        after = PreviewClipState(
            clip_id=provisional_id,
            track_key="video",
            track_id="video",
            order_index=len(clips),
            source_id=material_id,
            source_name=_display_name(params.source_path),
            trim_in_seconds=trim_in,
            trim_out_seconds=trim_out,
            timeline_start_seconds=timeline_start,
            timeline_end_seconds=timeline_start + duration,
            effective_duration_seconds=duration,
            speed_factor=params.speed_factor,
            keep_audio=params.keep_audio,
            reverse=False,
            rotate_degrees=params.rotate,
            link_group_id=None,
            provisional=True,
        )
        clips.append(after)
        append_change(
            step=step,
            category="clip_addition",
            effect_kind="direct",
            severity="info",
            entity=ProposedEntityReference(
                entity_kind="clip",
                entity_id=provisional_id,
                track_key="video",
            ),
            after=after,
            reason=(
                "The validated add operation appends a provisional clip to "
                "the detached video track. Runtime clip IDs remain tool-owned."
            ),
        )
        if was_empty:
            next_settings = PreviewProjectSettings(
                width=fact.width,
                height=fact.height,
                fps=project_settings.fps,
            )
            if next_settings != project_settings:
                append_change(
                    step=step,
                    category="project_settings",
                    effect_kind="consequential",
                    severity="info",
                    entity=ProposedEntityReference(
                        entity_kind="project",
                        entity_id=request.snapshot_ref.project_id,
                    ),
                    before_project=project_settings,
                    after_project=next_settings,
                    reason=(
                        "Adding the first clip adopts its known video "
                        "dimensions, matching the atomic tool."
                    ),
                )
                project_settings = next_settings
        return (
            "previewed",
            "Adds one provisional video clip.",
            project_settings,
        )

    @staticmethod
    def _reset_project_settings(
        *,
        step: Any,
        project_settings: PreviewProjectSettings,
        append_change: Any,
        effect_kind: str,
        severity: str,
        reason: str,
        project_id: str,
    ) -> PreviewProjectSettings:
        defaults = PreviewProjectSettings(
            width=1920,
            height=1080,
            fps=30,
        )
        if project_settings != defaults:
            append_change(
                step=step,
                category="project_settings",
                effect_kind=effect_kind,
                severity=severity,
                entity=ProposedEntityReference(
                    entity_kind="project",
                    entity_id=project_id,
                ),
                before_project=project_settings,
                after_project=defaults,
                reason=reason,
            )
        return defaults

    @staticmethod
    def _preview_modify(
        *,
        step: Any,
        params: BaseModel,
        clips: list[PreviewClipState],
        append_change: Any,
    ) -> tuple[str, str]:
        if not clips:
            raise PlanDiffValidationError(
                f"Step {step.step_id} cannot modify an empty timeline"
            )
        index = params.target_index
        if index < 0:
            index += len(clips)
        if index < 0 or index >= len(clips):
            raise PlanDiffValidationError(
                f"Step {step.step_id} targets an out-of-range clip index"
            )
        before = clips[index]
        if params.reverse is True and not before.reverse:
            append_change(
                step=step,
                category="warning",
                effect_kind="informational",
                severity="blocker",
                entity=ProposedEntityReference(
                    entity_kind="clip",
                    entity_id=before.clip_id,
                    track_key=before.track_key,
                ),
                before=before,
                reason=(
                    "Enabling reverse would generate and substitute proxy "
                    "media; the read-only simulator cannot reproduce it."
                ),
            )
            return "unsupported", "Reverse proxy generation is unpreviewable."

        after = before
        categories: list[tuple[str, str]] = []
        if params.speed_factor is not None:
            if params.speed_factor <= 0:
                raise PlanDiffValidationError(
                    f"Step {step.step_id} has a non-positive speed factor"
                )
            after = _replace_clip(after, speed_factor=params.speed_factor)
            categories.append(
                ("clip_speed", "Changes speed and effective duration.")
            )
        if params.reverse is not None:
            after = _replace_clip(after, reverse=params.reverse)
            categories.append(
                ("clip_properties", "Changes the reverse property.")
            )
        if params.rotate is not None:
            after = _replace_clip(
                after,
                rotate_degrees=params.rotate,
            )
            categories.append(
                ("clip_properties", "Changes the rotation property.")
            )
        clips[index] = after
        if not categories:
            return "previewed", "The validated operation is a no-op."
        for category, reason in categories:
            append_change(
                step=step,
                category=category,
                effect_kind="direct",
                severity="info",
                entity=ProposedEntityReference(
                    entity_kind="clip",
                    entity_id=before.clip_id,
                    track_key=before.track_key,
                ),
                before=before,
                after=after,
                reason=reason,
            )
        return "previewed", "Changes one existing video clip."
