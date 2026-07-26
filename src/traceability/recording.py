"""Record truthful entity effects at existing atomic mutation boundaries."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    EditingExecutionPlan,
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
