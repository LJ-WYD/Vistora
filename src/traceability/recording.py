"""Record truthful entity effects at existing atomic mutation boundaries."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    EditingExecutionPlan,
    ManualClipLink,
    ManualClipSplit,
    ManualClipAudio,
    ManualClipVisual,
    ManualCopyClipVisual,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualTrackManage,
    ManualTrackMix,
    ManualVolumeEnvelope,
    ManualSubtitleCue,
    ManualSubtitleTrack,
    ManualTransitionEdit,
    ManualVisualAutomationEdit,
)
from timeline_query import TimelineSnapshot

from .models import (
    ConfirmedAtomicTrace,
    ConfirmedEntityRelation,
    ManualEditTrace,
    ManualEntityRelation,
    SnapshotTraceReference,
    TraceEntityReference,
)
from .store import TraceabilityStore


def _canonical_hash(value: Any) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_canonical_hash(value)[:24]}"


def _clips(snapshot: TimelineSnapshot) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (track.track_key, clip.clip_id): clip.model_dump(
            mode="json",
            exclude={"provenance"},
        )
        for track in snapshot.tracks
        for clip in track.clips
    }


def _subtitle_tracks(snapshot: TimelineSnapshot) -> dict[str, dict[str, Any]]:
    return {
        track.track_id: track.model_dump(mode="json", exclude={"cues"})
        for track in snapshot.subtitle_tracks
    }


def _subtitle_cues(snapshot: TimelineSnapshot) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (track.track_id, cue.cue_id): cue.model_dump(mode="json")
        for track in snapshot.subtitle_tracks
        for cue in track.cues
    }


def _transitions(snapshot: TimelineSnapshot) -> dict[str, dict[str, Any]]:
    return {
        transition.transition_id: transition.model_dump(mode="json")
        for transition in snapshot.transitions
    }


def _automations(
    snapshot: TimelineSnapshot,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (track.track_key, clip.clip_id, automation.automation_id):
        automation.model_dump(mode="json")
        for track in snapshot.tracks
        for clip in track.clips
        for automation in clip.visual_automations
    }


def _manual_transition_ids(
    edit: ManualTransitionEdit,
    before: dict[str, dict[str, Any]],
) -> set[str]:
    """Resolve only the exact transition identities owned by one operation."""

    if edit.action in {"add", "update"}:
        identities = {edit.transition.transition_id}
        if edit.paired_transition is not None:
            identities.add(edit.paired_transition.transition_id)
        previous = before.get(edit.transition.transition_id)
        if previous is not None and previous.get("paired_transition_id"):
            identities.add(previous["paired_transition_id"])
        return identities
    if edit.action == "remove":
        identities = {edit.transition_id}
        previous = before.get(edit.transition_id)
        if previous is not None and previous.get("paired_transition_id"):
            identities.add(previous["paired_transition_id"])
        return identities
    identities = {target.transition_id for target in edit.targets}
    identities.update(
        target.paired_transition_id
        for target in edit.targets
        if target.paired_transition_id is not None
    )
    return identities


class ConfirmedTraceRecorder:
    """Correlate one confirmed atomic result with observed state effects."""

    @classmethod
    def record(
        cls,
        execution_plan: EditingExecutionPlan,
        request: AtomicToolRequestEnvelope,
        result: AtomicToolResultEnvelope,
        before_snapshot: TimelineSnapshot,
        after_snapshot: TimelineSnapshot,
    ) -> ConfirmedAtomicTrace:
        before = _clips(before_snapshot)
        after = _clips(after_snapshot)
        track_ids = {
            track.track_key: track.track_id
            for track in (*before_snapshot.tracks, *after_snapshot.tracks)
        }
        track_ids.update(
            {
                track.track_id: track.track_id
                for track in (
                    *before_snapshot.subtitle_tracks,
                    *after_snapshot.subtitle_tracks,
                )
            }
        )
        effects: list[tuple[str, str, str, str]] = []
        for track_key, clip_id in sorted(before.keys() | after.keys()):
            key = (track_key, clip_id)
            if key not in before:
                effects.append(("creates", "clip", track_key, clip_id))
            elif key not in after:
                effects.append(("deletes", "clip", track_key, clip_id))
            elif before[key] != after[key]:
                effects.append(("modifies", "clip", track_key, clip_id))

        before_subtitle_tracks = _subtitle_tracks(before_snapshot)
        after_subtitle_tracks = _subtitle_tracks(after_snapshot)
        for track_id in sorted(before_subtitle_tracks.keys() | after_subtitle_tracks.keys()):
            if track_id not in before_subtitle_tracks:
                effects.append(("creates", "subtitle_track", track_id, track_id))
            elif track_id not in after_subtitle_tracks:
                effects.append(("deletes", "subtitle_track", track_id, track_id))
            elif before_subtitle_tracks[track_id] != after_subtitle_tracks[track_id]:
                effects.append(("modifies", "subtitle_track", track_id, track_id))
        before_subtitle_cues = _subtitle_cues(before_snapshot)
        after_subtitle_cues = _subtitle_cues(after_snapshot)
        for track_id, cue_id in sorted(before_subtitle_cues.keys() | after_subtitle_cues.keys()):
            key = (track_id, cue_id)
            if key not in before_subtitle_cues:
                effects.append(("creates", "subtitle_cue", track_id, cue_id))
            elif key not in after_subtitle_cues:
                effects.append(("deletes", "subtitle_cue", track_id, cue_id))
            elif before_subtitle_cues[key] != after_subtitle_cues[key]:
                effects.append(("modifies", "subtitle_cue", track_id, cue_id))
        before_transitions = _transitions(before_snapshot)
        after_transitions = _transitions(after_snapshot)
        track_key_by_id = {
            track.track_id: track.track_key
            for track in (*before_snapshot.tracks, *after_snapshot.tracks)
        }
        for transition_id in sorted(
            before_transitions.keys() | after_transitions.keys()
        ):
            old = before_transitions.get(transition_id)
            new = after_transitions.get(transition_id)
            state = new or old
            track_key = track_key_by_id.get(state["track_id"], state["track_id"])
            if old is None:
                effects.append(("creates", "transition", track_key, transition_id))
            elif new is None:
                effects.append(("deletes", "transition", track_key, transition_id))
            elif old != new:
                effects.append(("modifies", "transition", track_key, transition_id))
        before_automations = _automations(before_snapshot)
        after_automations = _automations(after_snapshot)
        for track_key, _clip_id, automation_id in sorted(
            before_automations.keys() | after_automations.keys()
        ):
            key = (track_key, _clip_id, automation_id)
            old = before_automations.get(key)
            new = after_automations.get(key)
            if old is None:
                effects.append(("creates", "automation", track_key, automation_id))
            elif new is None:
                effects.append(("deletes", "automation", track_key, automation_id))
            elif old != new:
                effects.append(("modifies", "automation", track_key, automation_id))

        inherited: dict[tuple[str, str], str] = {}
        changed_before_ids = {
            (track_key, clip_id)
            for relation_type, entity_kind, track_key, clip_id in effects
            if entity_kind == "clip" and relation_type in {"modifies", "deletes"}
        }
        if request.tool_name in {
            "VideoSplitClipSkill",
            "VideoInsertOverwriteClipSkill",
        }:
            inserted_id = None
            if (
                request.tool_name == "VideoInsertOverwriteClipSkill"
                and isinstance(result.payload, dict)
            ):
                created_ids = result.payload.get("created_clip_ids")
                if isinstance(created_ids, list) and created_ids:
                    inserted_id = created_ids[0]
            for relation_type, entity_kind, track_key, clip_id in effects:
                if entity_kind != "clip" or relation_type != "creates":
                    continue
                if clip_id == inserted_id:
                    continue
                created = after[(track_key, clip_id)]
                source = created["source"]["source_id"]
                candidates = []
                for candidate_key in sorted(changed_before_ids):
                    if candidate_key[0] != track_key:
                        continue
                    candidate = before[candidate_key]
                    if (
                        candidate["source"]["source_id"] == source
                        and created["trim_in_seconds"]
                        >= candidate["trim_in_seconds"] - 1e-6
                        and created["trim_out_seconds"]
                        <= candidate["trim_out_seconds"] + 1e-6
                    ):
                        candidates.append(candidate_key[1])
                if candidates:
                    inherited[(track_key, clip_id)] = candidates[0]

        if result.status == "success" and isinstance(result.payload, dict):
            output_path = result.payload.get("output_path")
            if isinstance(output_path, str) and output_path:
                effects.append(
                    (
                        "generates", "media_output", "",
                        _stable_id(
                            "media_output",
                            {
                                "request_id": request.request_id,
                                "output_path": output_path,
                            },
                        ),
                    )
                )

        step = next(
            step
            for step in execution_plan.steps
            if step.step_id == request.step_id
        )
        evidence_ids = tuple(
            evidence.evidence_id for evidence in request.evidence_refs
        )
        before_ref = SnapshotTraceReference.from_snapshot(before_snapshot)
        after_ref = SnapshotTraceReference.from_snapshot(after_snapshot)
        consequential_ids = set()
        if result.status == "success" and isinstance(result.payload, dict):
            raw_consequential = result.payload.get(
                "consequential_clip_ids",
                (),
            )
            if isinstance(raw_consequential, (list, tuple)):
                consequential_ids = {
                    item
                    for item in raw_consequential
                    if isinstance(item, str)
                }
            raw_subtitle = result.payload.get(
                "consequential_subtitle_cue_ids",
                (),
            )
            if isinstance(raw_subtitle, (list, tuple)):
                consequential_ids.update(
                    item for item in raw_subtitle if isinstance(item, str)
                )
            if not request.tool_name.startswith("Timeline") or not request.tool_name.endswith("TransitionSkill"):
                raw_transitions = result.payload.get(
                    "deleted_transition_ids", ()
                )
                if isinstance(raw_transitions, (list, tuple)):
                    consequential_ids.update(
                        item for item in raw_transitions
                        if isinstance(item, str)
                    )
            if "Visual" not in request.tool_name:
                for field in (
                    "created_automation_ids",
                    "modified_automation_ids",
                    "deleted_automation_ids",
                ):
                    raw_automations = result.payload.get(field, ())
                    if isinstance(raw_automations, (list, tuple)):
                        consequential_ids.update(
                            item
                            for item in raw_automations
                            if isinstance(item, str)
                        )
        relations = tuple(
            ConfirmedEntityRelation(
                relation_id=_stable_id(
                    "relation",
                    {
                        "request_id": request.request_id,
                        "result_id": result.result_id,
                        "relation_type": relation_type,
                        "entity_kind": entity_kind,
                        "track_key": track_key,
                        "track_id": track_ids.get(track_key),
                        "entity_id": entity_id,
                    },
                ),
                relation_sequence=relation_index,
                relation_type=relation_type,
                effect_kind=(
                    "consequential"
                    if entity_id in consequential_ids
                    else "direct"
                ),
                origin_kind=(
                    "generated_media" if entity_kind == "media_output"
                    else "director_plan"
                ),
                entity=TraceEntityReference(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    track_key=track_key or None,
                    track_id=track_ids.get(track_key),
                ),
                source_operation_id=step.source_operation_id,
                step_id=step.step_id,
                request_id=request.request_id,
                result_id=result.result_id,
                evidence_ids=evidence_ids,
                inherited_from_entity_id=inherited.get(
                    (track_key, entity_id) if entity_kind == "clip" else ("", "")
                ),
                before_snapshot=before_ref,
                after_snapshot=after_ref,
            )
            for relation_index, (
                relation_type, entity_kind, track_key, entity_id,
            ) in enumerate(effects, start=1)
        )
        trace = ConfirmedAtomicTrace(
            trace_id=_stable_id(
                "confirmed_trace",
                {
                    "request_id": request.request_id,
                    "result_id": result.result_id,
                },
            ),
            trace_sequence=TraceabilityStore.next_sequence(),
            execution_plan=execution_plan,
            request=request,
            result=result,
            relations=relations,
        )
        TraceabilityStore.append_confirmed(trace)
        return trace


class ManualTraceRecorder:
    """Record a confirmed user edit without calling it Director intent."""

    @classmethod
    def record(
        cls,
        proposal: ManualEditProposal,
        confirmation: ManualEditConfirmationRecord,
        before_snapshot: TimelineSnapshot,
        after_snapshot: TimelineSnapshot,
    ) -> ManualEditTrace:
        before_clips = _clips(before_snapshot)
        after_clips = _clips(after_snapshot)
        before_tracks = {
            track.track_key: track.model_dump(
                mode="json",
                exclude={"clips"},
            )
            for track in before_snapshot.tracks
        }
        after_tracks = {
            track.track_key: track.model_dump(
                mode="json",
                exclude={"clips"},
            )
            for track in after_snapshot.tracks
        }
        before_subtitle_tracks = _subtitle_tracks(before_snapshot)
        after_subtitle_tracks = _subtitle_tracks(after_snapshot)
        before_subtitle_cues = _subtitle_cues(before_snapshot)
        after_subtitle_cues = _subtitle_cues(after_snapshot)
        before_transitions = _transitions(before_snapshot)
        after_transitions = _transitions(after_snapshot)
        before_automations = _automations(before_snapshot)
        after_automations = _automations(after_snapshot)
        for edit in proposal.edits:
            if isinstance(edit, ManualVisualAutomationEdit):
                target_ids = {edit.clip_id}
                target_ids.update(item.clip_id for item in edit.targets)
                if not any(
                    clip_id in target_ids
                    and before_automations.get((track_key, clip_id, automation_id))
                    != after_automations.get((track_key, clip_id, automation_id))
                    for track_key, clip_id, automation_id in (
                        before_automations.keys() | after_automations.keys()
                    )
                ):
                    raise ValueError(
                        "Manual visual automation trace has no exact state change"
                    )
                continue
            if isinstance(edit, ManualTransitionEdit):
                expected_ids = _manual_transition_ids(
                    edit, before_transitions
                )
                if not any(
                    before_transitions.get(identity)
                    != after_transitions.get(identity)
                    for identity in expected_ids
                ):
                    raise ValueError(
                        "Manual transition trace has no exact state change"
                    )
                continue
            if isinstance(edit, ManualSubtitleTrack):
                old = before_subtitle_tracks.get(edit.track_id)
                new = after_subtitle_tracks.get(edit.track_id)
                if old == new:
                    raise ValueError("Manual subtitle track trace has no exact state change")
                continue
            if isinstance(edit, ManualSubtitleCue):
                if not any(
                    track_id == edit.track_id
                    and before_subtitle_cues.get((track_id, cue_id))
                    != after_subtitle_cues.get((track_id, cue_id))
                    for track_id, cue_id in (
                        before_subtitle_cues.keys() | after_subtitle_cues.keys()
                    )
                ):
                    raise ValueError("Manual subtitle cue trace has no exact state change")
                continue
            if isinstance(edit, (ManualTrackManage, ManualTrackMix)):
                if (
                    edit.track_key not in before_tracks
                    or edit.track_key not in after_tracks
                    or before_tracks[edit.track_key]
                    == after_tracks[edit.track_key]
                ):
                    raise ValueError(
                        "Manual track trace has no exact state change"
                    )
                continue
            if isinstance(edit, ManualClipLink):
                for member in edit.members:
                    key = (member.track_key, member.clip_id)
                    if (
                        key not in before_clips
                        or key not in after_clips
                        or before_clips[key] == after_clips[key]
                    ):
                        raise ValueError(
                            "Manual link member was not modified"
                        )
                continue
            if isinstance(edit, ManualCopyClipVisual):
                for member in edit.targets:
                    key = (member.track_key, member.clip_id)
                    if (
                        key not in before_clips
                        or key not in after_clips
                        or before_clips[key] == after_clips[key]
                    ):
                        raise ValueError(
                            "Manual visual copy target was not modified"
                        )
                continue
            key = (edit.track_key, edit.clip_id)
            if key not in before_clips:
                raise ValueError(
                    "Manual trace target is absent from the before snapshot"
                )
            if edit.kind == "remove":
                if key in after_clips:
                    raise ValueError(
                        "Manual removal trace target remains after application"
                    )
                continue
            if isinstance(edit, ManualClipSplit):
                right_key = (edit.track_key, edit.right_clip_id)
                if key not in after_clips or right_key not in after_clips:
                    raise ValueError(
                        "Manual split trace outputs are absent after application"
                    )
                left = after_clips[key]
                right = after_clips[right_key]
                if (
                    left["trim_out_seconds"]
                    != right["trim_in_seconds"]
                    or right["timeline_start_seconds"]
                    != edit.split_at_seconds
                ):
                    raise ValueError(
                        "Manual split trace differs from confirmed split"
                    )
                continue
            if key not in after_clips:
                raise ValueError(
                    "Manual update trace target is absent after application"
                )
            if isinstance(
                edit,
                (ManualClipAudio, ManualVolumeEnvelope, ManualClipVisual),
            ):
                if before_clips[key] == after_clips[key]:
                    raise ValueError(
                        "Manual audio trace has no exact state change"
                    )
                continue
            actual = after_clips[key]
            expected = {
                "trim_in_seconds": edit.trim_in_seconds,
                "trim_out_seconds": edit.trim_out_seconds,
                "timeline_start_seconds": edit.timeline_start_seconds,
                "order_index": edit.order_index,
            }
            if any(actual[field] != value for field, value in expected.items()):
                raise ValueError(
                    "Manual trace after snapshot differs from confirmed edit"
                )
        effect_rows: list[tuple[Any, str, str, str, str]] = []
        seen_effects: set[tuple[str, str, str]] = set()
        for edit in proposal.edits:
            if isinstance(edit, ManualVisualAutomationEdit):
                target_ids = {edit.clip_id}
                target_ids.update(item.clip_id for item in edit.targets)
                for track_key, clip_id, automation_id in sorted(
                    before_automations.keys() | after_automations.keys()
                ):
                    if clip_id not in target_ids:
                        continue
                    old = before_automations.get(
                        (track_key, clip_id, automation_id)
                    )
                    new = after_automations.get(
                        (track_key, clip_id, automation_id)
                    )
                    if old == new:
                        continue
                    effect_rows.append((
                        edit,
                        "creates" if old is None else "deletes" if new is None else "modifies",
                        track_key,
                        automation_id,
                        "direct",
                    ))
                continue
            if isinstance(edit, ManualTransitionEdit):
                for transition_id in sorted(
                    _manual_transition_ids(edit, before_transitions)
                ):
                    old = before_transitions.get(transition_id)
                    new = after_transitions.get(transition_id)
                    if old == new:
                        continue
                    state = new or old
                    track_id = state["track_id"]
                    track_key = next(
                        (
                            track.track_key
                            for track in (*after_snapshot.tracks, *before_snapshot.tracks)
                            if track.track_id == track_id
                        ),
                        track_id,
                    )
                    effect_rows.append((
                        edit,
                        "creates" if old is None else "deletes" if new is None else "modifies",
                        track_key,
                        transition_id,
                        "direct",
                    ))
                continue
            if isinstance(edit, ManualSubtitleTrack):
                old = before_subtitle_tracks.get(edit.track_id)
                new = after_subtitle_tracks.get(edit.track_id)
                effect_rows.append((
                    edit,
                    "creates" if old is None else "deletes" if new is None else "modifies",
                    edit.track_id,
                    edit.track_id,
                    "direct",
                ))
                continue
            if isinstance(edit, ManualSubtitleCue):
                for track_id, cue_id in sorted(
                    before_subtitle_cues.keys() | after_subtitle_cues.keys()
                ):
                    if track_id != edit.track_id:
                        continue
                    old = before_subtitle_cues.get((track_id, cue_id))
                    new = after_subtitle_cues.get((track_id, cue_id))
                    if old == new:
                        continue
                    effect_rows.append((
                        edit,
                        "creates" if old is None else "deletes" if new is None else "modifies",
                        track_id,
                        cue_id,
                        "direct",
                    ))
                continue
            if isinstance(edit, (ManualTrackManage, ManualTrackMix)):
                effect_rows.append(
                    (
                        edit,
                        "modifies",
                        edit.track_key,
                        edit.track_id,
                        "direct",
                    )
                )
                continue
            if isinstance(edit, ManualClipLink):
                for member in edit.members:
                    effect_rows.append(
                        (
                            edit,
                            "modifies",
                            member.track_key,
                            member.clip_id,
                            "direct",
                        )
                    )
                continue
            if isinstance(edit, ManualCopyClipVisual):
                for member in edit.targets:
                    effect_rows.append(
                        (
                            edit,
                            "modifies",
                            member.track_key,
                            member.clip_id,
                            "direct",
                        )
                    )
                continue
            target_key = (edit.track_key, edit.clip_id)
            if target_key not in before_clips:
                raise ValueError(
                    "Manual trace target is absent from its exact track"
                )
            direct_rows: list[tuple[str, str, str]] = []
            if isinstance(edit, ManualClipSplit):
                direct_rows.extend((
                    ("modifies", edit.track_key, edit.clip_id),
                    ("creates", edit.track_key, edit.right_clip_id),
                ))
            else:
                direct_rows.append((
                    "deletes" if edit.kind == "remove" else "modifies",
                    edit.track_key,
                    edit.clip_id,
                ))
            for relation_type, track_key, clip_id in direct_rows:
                effect_rows.append(
                    (edit, relation_type, track_key, clip_id, "direct")
                )
                seen_effects.add(
                    (edit.operation_id, track_key, clip_id)
                )

            target_before = before_clips[target_key]
            original_group = target_before.get("link_group_id")
            direct_right_group = (
                after_clips.get(
                    (edit.track_key, edit.right_clip_id),
                    {},
                ).get("link_group_id")
                if isinstance(edit, ManualClipSplit)
                else None
            )
            linked_scope = getattr(edit, "edit_scope", "") == "linked_group"
            ripple = (
                getattr(edit, "ripple", False)
                or getattr(edit, "mode", "") == "ripple"
            )
            reorder = (
                hasattr(edit, "order_index")
                and before_clips[target_key].get("order_index")
                != getattr(edit, "order_index", None)
            )
            for key in sorted(before_clips.keys() | after_clips.keys()):
                if key == target_key:
                    continue
                old, new = before_clips.get(key), after_clips.get(key)
                if old == new:
                    continue
                state = new or old or {}
                linked_effect = linked_scope and (
                    state.get("link_group_id") == original_group
                    or (
                        direct_right_group is not None
                        and state.get("link_group_id") == direct_right_group
                    )
                )
                ripple_effect = ripple and key[0] == edit.track_key
                reorder_effect = reorder and key[0] == edit.track_key
                if (
                    not linked_effect
                    and not ripple_effect
                    and not reorder_effect
                ):
                    continue
                identity = (edit.operation_id, key[0], key[1])
                if identity in seen_effects:
                    continue
                relation_type = (
                    "creates"
                    if old is None
                    else "deletes"
                    if new is None
                    else "modifies"
                )
                if (
                    relation_type != "modifies"
                    and not linked_effect
                ):
                    continue
                effect_rows.append(
                    (
                        edit,
                        relation_type,
                        key[0],
                        key[1],
                        "consequential",
                    )
                )
                seen_effects.add(identity)

        transition_relation_ids = {
            clip_id
            for edit, _, _, clip_id, _ in effect_rows
            if isinstance(edit, ManualTransitionEdit)
        }
        for transition_id in sorted(
            before_transitions.keys() | after_transitions.keys()
        ):
            old_transition = before_transitions.get(transition_id)
            new_transition = after_transitions.get(transition_id)
            if (
                old_transition == new_transition
                or transition_id in transition_relation_ids
            ):
                continue
            transition_state = new_transition or old_transition
            bound_clip_ids = {
                transition_state["from_clip_id"],
                transition_state["to_clip_id"],
            }
            candidates = []
            for edit in proposal.edits:
                if isinstance(edit, ManualTransitionEdit):
                    continue
                target_ids = set()
                if hasattr(edit, "clip_id"):
                    target_ids.add(edit.clip_id)
                if isinstance(edit, ManualClipSplit):
                    target_ids.add(edit.right_clip_id)
                if isinstance(edit, ManualClipLink):
                    target_ids.update(
                        member.clip_id for member in edit.members
                    )
                elif isinstance(edit, ManualCopyClipVisual):
                    target_ids.update(
                        member.clip_id for member in edit.targets
                    )
                if target_ids & bound_clip_ids:
                    candidates.append(edit)
            if len(candidates) != 1:
                raise ValueError(
                    "Manual transition consequence cannot be mapped to one exact operation"
                )
            edit = candidates[0]
            track_id = transition_state["track_id"]
            track_key = next(
                (
                    track.track_key
                    for track in (*after_snapshot.tracks, *before_snapshot.tracks)
                    if track.track_id == track_id
                ),
                track_id,
            )
            effect_rows.append((
                edit,
                "creates" if old_transition is None else "deletes" if new_transition is None else "modifies",
                track_key,
                transition_id,
                "consequential",
            ))
            transition_relation_ids.add(transition_id)

        before_ref = SnapshotTraceReference.from_snapshot(before_snapshot)
        after_ref = SnapshotTraceReference.from_snapshot(after_snapshot)
        relations = tuple(
            ManualEntityRelation(
                relation_id=_stable_id(
                    "manual_relation",
                    {
                        "proposal_id": proposal.proposal_id,
                        "operation_id": edit.operation_id,
                        "track_key": track_key,
                        "clip_id": clip_id,
                        "effect_kind": effect_kind,
                    },
                ),
                relation_sequence=relation_index,
                relation_type=relation_type,
                effect_kind=effect_kind,
                entity=TraceEntityReference(
                    entity_kind=(
                        "subtitle_track"
                        if isinstance(edit, ManualSubtitleTrack)
                        else "subtitle_cue"
                        if isinstance(edit, ManualSubtitleCue)
                        else "track"
                        if isinstance(edit, (ManualTrackManage, ManualTrackMix))
                        else "transition"
                        if (
                            isinstance(edit, ManualTransitionEdit)
                            or clip_id in transition_relation_ids
                        )
                        else "automation"
                        if isinstance(edit, ManualVisualAutomationEdit)
                        else "clip"
                    ),
                    entity_id=clip_id,
                    track_key=track_key,
                    track_id=next(
                        (
                            track.track_id
                            for track in after_snapshot.tracks
                            if track.track_key == track_key
                        ),
                        track_key,
                    ),
                ),
                operation_id=edit.operation_id,
                inherited_from_entity_id=(
                    edit.clip_id
                    if (
                        isinstance(edit, ManualClipSplit)
                        and relation_type == "creates"
                        and clip_id == edit.right_clip_id
                    )
                    else next(
                        (
                            candidate_id
                            for (candidate_track, candidate_id), candidate
                            in before_clips.items()
                            if relation_type == "creates"
                            and candidate_track == track_key
                            and (after_clips.get((track_key, clip_id)) or {})
                            .get("source", {})
                            .get("source_id")
                            == candidate.get("source", {}).get("source_id")
                        ),
                        None,
                    )
                    if not isinstance(
                        edit,
                        (
                            ManualSubtitleTrack,
                            ManualSubtitleCue,
                            ManualCopyClipVisual,
                            ManualTransitionEdit,
                            ManualVisualAutomationEdit,
                        ),
                    ) and clip_id not in transition_relation_ids
                    else None
                ),
                before_snapshot=before_ref,
                after_snapshot=after_ref,
            )
            for relation_index, (
                edit,
                relation_type,
                track_key,
                clip_id,
                effect_kind,
            ) in enumerate(effect_rows, start=1)
        )
        trace = ManualEditTrace(
            trace_id=_stable_id(
                "manual_trace",
                {
                    "proposal_id": proposal.proposal_id,
                    "proposal_digest": proposal.digest(),
                    "confirmation_id": confirmation.confirmation_id,
                },
            ),
            trace_sequence=TraceabilityStore.next_sequence(),
            proposal=proposal,
            confirmation=confirmation,
            relations=relations,
        )
        TraceabilityStore.append_manual(trace)
        return trace
