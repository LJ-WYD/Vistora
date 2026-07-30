"""Record truthful entity effects at existing atomic mutation boundaries."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    EditingExecutionPlan,
    ManualClipSplit,
    ManualEditConfirmationRecord,
    ManualEditProposal,
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
        effects: list[tuple[str, str, str]] = []
        for track_key, clip_id in sorted(before.keys() | after.keys()):
            key = (track_key, clip_id)
            if key not in before:
                effects.append(("creates", track_key, clip_id))
            elif key not in after:
                effects.append(("deletes", track_key, clip_id))
            elif before[key] != after[key]:
                effects.append(("modifies", track_key, clip_id))

        inherited: dict[tuple[str, str], str] = {}
        changed_before_ids = {
            (track_key, clip_id)
            for relation_type, track_key, clip_id in effects
            if relation_type in {"modifies", "deletes"}
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
            for relation_type, track_key, clip_id in effects:
                if relation_type != "creates":
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
                        "generates",
                        "",
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
        relations = tuple(
            ConfirmedEntityRelation(
                relation_id=_stable_id(
                    "relation",
                    {
                        "request_id": request.request_id,
                        "result_id": result.result_id,
                        "relation_type": relation_type,
                        "track_key": track_key,
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
                    "generated_media"
                    if relation_type == "generates"
                    else "director_plan"
                ),
                entity=TraceEntityReference(
                    entity_kind=(
                        "media_output"
                        if relation_type == "generates"
                        else "clip"
                    ),
                    entity_id=entity_id,
                    track_key=track_key or None,
                ),
                source_operation_id=step.source_operation_id,
                step_id=step.step_id,
                request_id=request.request_id,
                result_id=result.result_id,
                evidence_ids=evidence_ids,
                inherited_from_entity_id=inherited.get(
                    (track_key, entity_id)
                ),
                before_snapshot=before_ref,
                after_snapshot=after_ref,
            )
            for relation_index, (
                relation_type,
                track_key,
                entity_id,
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
        for edit in proposal.edits:
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
        effect_rows: list[tuple[Any, str, str, str]] = []
        video_order = [
            clip.clip_id
            for track in before_snapshot.tracks
            if track.track_key == "video"
            for clip in track.clips
        ]
        for edit in proposal.edits:
            index = video_order.index(edit.clip_id)
            if isinstance(edit, ManualClipSplit):
                effect_rows.extend(
                    (
                        (edit, "modifies", edit.clip_id, "direct"),
                        (edit, "creates", edit.right_clip_id, "direct"),
                    )
                )
                video_order.insert(index + 1, edit.right_clip_id)
                continue
            effect_rows.append(
                (
                    edit,
                    "deletes" if edit.kind == "remove" else "modifies",
                    edit.clip_id,
                    "direct",
                )
            )
            if edit.kind == "remove":
                video_order.pop(index)
                displaced = video_order[index:]
            elif edit.order_index != index:
                moved = video_order.pop(index)
                video_order.insert(edit.order_index, moved)
                lower = min(index, edit.order_index)
                upper = max(index, edit.order_index)
                displaced = [
                    clip_id
                    for clip_id in video_order[lower : upper + 1]
                    if clip_id != edit.clip_id
                ]
            else:
                displaced = []
            if getattr(edit, "ripple", False):
                displaced = [
                    clip_id
                    for clip_id in video_order
                    if clip_id != edit.clip_id
                ]
            for clip_id in displaced:
                key = ("video", clip_id)
                if (
                    key in before_clips
                    and key in after_clips
                    and before_clips[key] != after_clips[key]
                ):
                    effect_rows.append(
                        (
                            edit,
                            "modifies",
                            clip_id,
                            "consequential",
                        )
                    )

        before_ref = SnapshotTraceReference.from_snapshot(before_snapshot)
        after_ref = SnapshotTraceReference.from_snapshot(after_snapshot)
        relations = tuple(
            ManualEntityRelation(
                relation_id=_stable_id(
                    "manual_relation",
                    {
                        "proposal_id": proposal.proposal_id,
                        "operation_id": edit.operation_id,
                        "clip_id": clip_id,
                        "effect_kind": effect_kind,
                    },
                ),
                relation_sequence=relation_index,
                relation_type=relation_type,
                effect_kind=effect_kind,
                entity=TraceEntityReference(
                    entity_kind="clip",
                    entity_id=clip_id,
                    track_key=edit.track_key,
                ),
                operation_id=edit.operation_id,
                inherited_from_entity_id=(
                    edit.clip_id
                    if (
                        isinstance(edit, ManualClipSplit)
                        and relation_type == "creates"
                        and clip_id == edit.right_clip_id
                    )
                    else None
                ),
                before_snapshot=before_ref,
                after_snapshot=after_ref,
            )
            for relation_index, (
                edit,
                relation_type,
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
