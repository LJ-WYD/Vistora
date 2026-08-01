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
    ClipConfig,
    TimelineConfig,
    TimelineEditEngine,
    TimelineEditError,
    TrackConfig,
)
from timeline_query import TimelineSnapshot, TimelineSnapshotReference

from .models import (
    PlanChange,
    PlanDiffDocument,
    PlanDiffRequest,
    PlanDiffSummary,
    PlanStepPreview,
    PreviewClipState,
    PreviewMaterialFact,
    PreviewProjectSettings,
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
        rotate_degrees=clip.rotate_degrees,
        link_group_id=clip.link_group_id,
    )


def _replace_clip(
    clip: PreviewClipState,
    **changes: Any,
) -> PreviewClipState:
    values = clip.model_dump(mode="python")
    values.update(changes)
    duration = (
        values["trim_out_seconds"] - values["trim_in_seconds"]
    ) / values["speed_factor"]
    values["effective_duration_seconds"] = duration
    values["timeline_end_seconds"] = (
        values["timeline_start_seconds"] + duration
    )
    return PreviewClipState.model_validate(values)


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
                )
                for clip in track.clips
            ],
        )
    return TimelineConfig.model_validate(timeline.model_dump(mode="python"))


def _preview_state(
    clip: ClipConfig,
    track_key: str,
    track_id: str,
) -> PreviewClipState:
    duration = (clip.trim_out - clip.trim_in) / clip.speed_factor
    return PreviewClipState(
        clip_id=clip.id,
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
        rotate_degrees=clip.rotate,
        link_group_id=clip.link_group_id,
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
                "VideoRemoveClipSkill",
                "VideoSetClipPropertiesSkill",
                "TimelineManageTrackSkill",
                "TimelineSetClipLinkSkill",
            }:
                # Synchronize only the legacy primary-video view; every other
                # stable multi-track declaration remains detached and intact.
                if video_track is not None:
                    primary = core_timeline.tracks[video_track.track_key]
                    primary.clips = [
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
                            rotate=clip.rotate_degrees,
                            link_group_id=clip.link_group_id,
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
                primary_video_keys = {
                    key
                    for key, track in core_timeline.tracks.items()
                    if track.kind == "video" and track.role == "primary"
                }
                clips = [
                    state
                    for (track_key, _), state in sorted(
                        _preview_map(core_timeline).items()
                    )
                    if track_key in primary_video_keys
                ]
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
            elif step.tool_name == "VideoExportSkill":
                if not clips:
                    raise PlanDiffValidationError(
                        f"Step {step.step_id} cannot export an empty timeline"
                    )
                if not params.output_path.strip():
                    raise PlanDiffValidationError(
                        f"Step {step.step_id} has an empty output path"
                    )
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
            change.category == "clip_addition" for change in changes
        )
        removals = sum(
            change.category == "clip_removal" for change in changes
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
                "project_settings",
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
                    rotate=clip.rotate_degrees,
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
            engine = TimelineEditEngine(
                timeline,
                id_factory=preview_id,
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
                )
            elif name == "VideoMoveClipSkill":
                updated, outcome = engine.move(
                    params.track_reference,
                    params.clip_id,
                    params.timeline_start,
                    ripple=params.ripple,
                    edit_scope=params.edit_scope,
                )
            elif name == "VideoRemoveClipSkill":
                updated, outcome = engine.remove(
                    params.track_reference,
                    params.clip_id,
                    ripple=params.mode == "ripple",
                    edit_scope=params.edit_scope,
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
                    edit_scope=params.edit_scope,
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
                    fact.duration_seconds,
                    params.trim_out
                    if params.trim_out is not None
                    else fact.duration_seconds,
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
                )
        except TimelineEditError as exc:
            raise PlanDiffValidationError(str(exc)) from exc

        after = _preview_map(updated)
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
