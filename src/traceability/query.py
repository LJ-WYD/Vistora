"""Deterministic revision-aware provenance queries over detached snapshots."""

from __future__ import annotations

from collections import defaultdict

from contracts import PlanReference
from timeline_query.models import (
    ClipProvenanceSummary,
    ClipTraceQueryResult,
    EvidenceSummary,
    TimelineSnapshot,
    TimelineSnapshotReference,
)

from .models import (
    ConfirmedAtomicTrace,
    ConfirmedEntityRelation,
    ManualEditTrace,
    ManualEntityRelation,
    TimelineTraceDocument,
)


class TraceabilityQueryError(ValueError):
    """Trace data is inconsistent with the requested snapshot or identity."""


TraceEvent = tuple[
    int,
    ConfirmedAtomicTrace | ManualEditTrace,
    ConfirmedEntityRelation | ManualEntityRelation,
]


def _snapshot_matches(reference, snapshot: TimelineSnapshot) -> bool:
    return (
        reference.snapshot_id == snapshot.snapshot_id
        and reference.project_id == snapshot.project_id
        and reference.revision == snapshot.revision
        and reference.timeline_digest == snapshot.timeline_digest
    )


def _evidence_summary(trace: ConfirmedAtomicTrace) -> tuple[
    EvidenceSummary, ...
]:
    summaries = []
    for evidence in trace.request.evidence_refs:
        locator = evidence.locator
        summaries.append(
            EvidenceSummary(
                evidence_id=evidence.evidence_id,
                material_id=evidence.material_id,
                locator_type=locator.locator_type,
                start_seconds=getattr(locator, "start_seconds", None),
                end_seconds=getattr(locator, "end_seconds", None),
                analysis_fact_id=evidence.analysis_fact_id,
            )
        )
    return tuple(summaries)


class TraceabilityQuery:
    """Query immutable trace history without mutating timeline or media."""

    def __init__(
        self,
        document: TimelineTraceDocument,
        snapshot: TimelineSnapshot,
        *,
        expected_reference: TimelineSnapshotReference | None = None,
    ) -> None:
        if expected_reference is not None:
            if (
                expected_reference.project_id != snapshot.project_id
                or expected_reference.revision != snapshot.revision
            ):
                raise TraceabilityQueryError(
                    "Trace query snapshot project/revision is stale"
                )
            if (
                expected_reference.snapshot_id is not None
                and expected_reference.snapshot_id != snapshot.snapshot_id
            ):
                raise TraceabilityQueryError(
                    "Trace query snapshot identity is stale"
                )
            if (
                expected_reference.timeline_digest is not None
                and expected_reference.timeline_digest
                != snapshot.timeline_digest
            ):
                raise TraceabilityQueryError(
                    "Trace query timeline digest is stale"
                )
        self.document = document
        self.snapshot = snapshot
        self._present = {
            (track.track_key, clip.clip_id)
            for track in snapshot.tracks
            for clip in track.clips
        }
        events: list[TraceEvent] = []
        for trace in document.confirmed_traces:
            events.extend(
                (trace.trace_sequence, trace, relation)
                for relation in trace.relations
                if relation.entity.entity_kind == "clip"
            )
        for trace in document.manual_traces:
            events.extend(
                (trace.trace_sequence, trace, relation)
                for relation in trace.relations
                if relation.entity.entity_kind == "clip"
            )
        self._events = tuple(
            sorted(
                events,
                key=lambda item: (
                    item[0],
                    item[2].relation_sequence,
                ),
            )
        )
        grouped: dict[tuple[str, str], list[TraceEvent]] = defaultdict(list)
        for event in self._events:
            relation = event[2]
            grouped[
                (relation.entity.track_key or "", relation.entity.entity_id)
            ].append(event)
        self._by_clip = {
            key: tuple(value) for key, value in grouped.items()
        }

    def _summary(
        self,
        track_key: str,
        clip_id: str,
    ) -> ClipProvenanceSummary:
        events = self._by_clip.get((track_key, clip_id), ())
        if not events:
            return ClipProvenanceSummary(
                origin_kind="legacy_unknown",
                latest_change_origin="legacy_unknown",
                mapping_status="legacy_unknown",
                trace_revision=self.document.revision,
            )

        latest_trace = events[-1][1]
        latest_relation = events[-1][2]
        confirmed_events = [
            event
            for event in events
            if isinstance(event[1], ConfirmedAtomicTrace)
        ]
        creation_events = [
            event
            for event in events
            if event[2].relation_type == "creates"
        ]
        origin_event = creation_events[0] if creation_events else events[0]
        origin_is_legacy = not creation_events
        inherited_id = getattr(
            origin_event[2],
            "inherited_from_entity_id",
            None,
        )
        if inherited_id is not None:
            parent_events = self._by_clip.get(
                (track_key, inherited_id),
                (),
            )
            parent_creations = [
                event for event in parent_events
                if event[2].relation_type == "creates"
            ]
            if parent_events:
                origin_event = (
                    parent_creations[0]
                    if parent_creations
                    else parent_events[0]
                )
            origin_is_legacy = not parent_creations
        if origin_is_legacy:
            origin_kind = "legacy_unknown"
        else:
            origin_kind = (
                "director_plan"
                if isinstance(origin_event[1], ConfirmedAtomicTrace)
                else "user_manual"
            )
        latest_origin = (
            "director_plan"
            if isinstance(latest_trace, ConfirmedAtomicTrace)
            else "user_manual"
        )
        present = (track_key, clip_id) in self._present
        if latest_relation.relation_type == "deletes":
            status = "stale" if present else "deleted"
        elif not present:
            status = "orphaned"
        elif _snapshot_matches(latest_relation.after_snapshot, self.snapshot):
            status = "current"
        else:
            status = "stale"

        plan_trace = None
        if inherited_id is not None and isinstance(
            origin_event[1], ConfirmedAtomicTrace
        ):
            plan_trace = origin_event[1]
        elif confirmed_events:
            creates = [
                event
                for event in confirmed_events
                if event[2].relation_type == "creates"
            ]
            plan_trace = (creates[0] if creates else confirmed_events[-1])[1]

        values = {}
        if isinstance(plan_trace, ConfirmedAtomicTrace):
            request = plan_trace.request
            result = plan_trace.result
            values = {
                "plan_id": request.plan_ref.plan_id,
                "plan_version": request.plan_ref.plan_version,
                "plan_digest": request.plan_ref.plan_digest,
                "confirmation_id": request.confirmation_id,
                "execution_id": request.execution_id,
                "source_operation_id": next(
                    step.source_operation_id
                    for step in plan_trace.execution_plan.steps
                    if step.step_id == request.step_id
                ),
                "step_id": request.step_id,
                "request_id": request.request_id,
                "result_id": result.result_id,
                "execution_status": result.status,
                "evidence": _evidence_summary(plan_trace),
            }
        return ClipProvenanceSummary(
            origin_kind=origin_kind,
            latest_change_origin=latest_origin,
            mapping_status=status,
            trace_revision=self.document.revision,
            **values,
        )

    def clip_to_trace(
        self,
        track_key: str,
        clip_id: str,
    ) -> ClipTraceQueryResult:
        present = (track_key, clip_id) in self._present
        return ClipTraceQueryResult(
            snapshot_id=self.snapshot.snapshot_id,
            project_id=self.snapshot.project_id,
            revision=self.snapshot.revision,
            trace_revision=self.document.revision,
            track_key=track_key,
            clip_id=clip_id,
            present=present,
            provenance=self._summary(track_key, clip_id),
        )

    def plan_to_clips(
        self,
        plan_ref: PlanReference,
        *,
        include_deleted: bool = True,
    ) -> tuple[ClipTraceQueryResult, ...]:
        known = {
            trace.request.plan_ref.plan_digest
            for trace in self.document.confirmed_traces
            if (
                trace.request.plan_ref.plan_id == plan_ref.plan_id
                and trace.request.plan_ref.plan_version
                == plan_ref.plan_version
            )
        }
        if known and plan_ref.plan_digest not in known:
            raise TraceabilityQueryError(
                "Plan query digest mismatches the recorded plan version"
            )
        identities = {
            (
                relation.entity.track_key or "",
                relation.entity.entity_id,
            )
            for trace in self.document.confirmed_traces
            if trace.request.plan_ref == plan_ref
            for relation in trace.relations
            if relation.entity.entity_kind == "clip"
        }
        results = tuple(
            self.clip_to_trace(*identity)
            for identity in sorted(identities)
        )
        if include_deleted:
            return results
        return tuple(result for result in results if result.present)

    def evidence_to_clips(
        self,
        evidence_id: str,
        *,
        include_deleted: bool = True,
    ) -> tuple[ClipTraceQueryResult, ...]:
        identities = {
            (
                relation.entity.track_key or "",
                relation.entity.entity_id,
            )
            for trace in self.document.confirmed_traces
            for relation in trace.relations
            if (
                relation.entity.entity_kind == "clip"
                and evidence_id in relation.evidence_ids
            )
        }
        results = tuple(
            self.clip_to_trace(*identity)
            for identity in sorted(identities)
        )
        if include_deleted:
            return results
        return tuple(result for result in results if result.present)

    def orphaned_clips(self) -> tuple[ClipTraceQueryResult, ...]:
        """Return recorded live entities missing from the current snapshot."""

        results = tuple(
            self.clip_to_trace(*identity)
            for identity in sorted(self._by_clip)
            if identity not in self._present
        )
        return tuple(
            result
            for result in results
            if result.provenance.mapping_status == "orphaned"
        )
