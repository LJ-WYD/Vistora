"""Strict versioned provenance contracts for plans, evidence, and entities."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    EditingExecutionPlan,
    ManualClipRemove,
    ManualClipLink,
    ManualClipSplit,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualTrackManage,
    ManualTrackMix,
    ManualSubtitleCue,
    ManualSubtitleTrack,
    ManualTransitionEdit,
    ManualVisualAutomationEdit,
    ManualMaskEdit,
    PlanReference,
)


TRACEABILITY_VERSION = "1.0.0"
TraceVersion = Literal["1.0.0"]
TraceId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class TraceModel(BaseModel):
    """Frozen strict base for persisted provenance data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: TraceVersion = TRACEABILITY_VERSION


class SnapshotTraceReference(TraceModel):
    """Exact timeline snapshot state before or after one atomic result."""

    snapshot_id: TraceId
    project_id: TraceId
    revision: int = Field(ge=1)
    timeline_digest: Sha256Digest

    @classmethod
    def from_snapshot(cls, snapshot) -> SnapshotTraceReference:
        return cls(
            snapshot_id=snapshot.snapshot_id,
            project_id=snapshot.project_id,
            revision=snapshot.revision,
            timeline_digest=snapshot.timeline_digest,
        )


class TraceEntityReference(TraceModel):
    """Opaque timeline or generated-media entity identity."""

    entity_kind: Literal[
        "clip", "track", "subtitle_track", "subtitle_cue", "transition", "automation", "mask", "composite", "media_output"
    ]
    entity_id: str = Field(min_length=1, max_length=160)
    track_key: str | None = Field(default=None, min_length=1)
    track_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def track_matches_entity_kind(self) -> TraceEntityReference:
        if self.entity_kind != "media_output" and self.track_key is None:
            raise ValueError("Timeline trace entities require a track key")
        if self.entity_kind == "media_output" and self.track_key is not None:
            raise ValueError("Generated media trace entities have no track")
        return self


class ConfirmedEntityRelation(TraceModel):
    """One entity effect caused by one exact confirmed atomic result."""

    relation_id: TraceId
    relation_sequence: int = Field(ge=1)
    relation_type: Literal["creates", "modifies", "deletes", "generates"]
    effect_kind: Literal["direct", "consequential"] = "direct"
    origin_kind: Literal["director_plan", "generated_media"]
    entity: TraceEntityReference
    source_operation_id: TraceId
    step_id: TraceId
    request_id: TraceId
    result_id: TraceId
    evidence_ids: tuple[TraceId, ...] = ()
    inherited_from_entity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    before_snapshot: SnapshotTraceReference
    after_snapshot: SnapshotTraceReference

    @model_validator(mode="after")
    def relation_matches_entity(self) -> ConfirmedEntityRelation:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Confirmed relation evidence IDs must be unique")
        if self.entity.entity_kind != "media_output":
            if self.relation_type == "generates":
                raise ValueError("Timeline entity relations cannot use generates")
            if self.origin_kind != "director_plan":
                raise ValueError(
                    "Confirmed timeline effects originate from Director intent"
                )
            if (
                self.inherited_from_entity_id is not None
                and (
                    self.entity.entity_kind != "clip"
                    or self.relation_type != "creates"
                )
            ):
                raise ValueError(
                    "Only a created clip can inherit another clip's origin"
                )
        elif (
            self.relation_type != "generates"
            or self.origin_kind != "generated_media"
        ):
            raise ValueError(
                "Generated media outputs require generated-media provenance"
            )
        elif self.inherited_from_entity_id is not None:
            raise ValueError("Generated media cannot inherit clip provenance")
        return self


class ConfirmedAtomicTrace(TraceModel):
    """Self-validating confirmed plan/execution/request/result trace."""

    schema_name: Literal["vistora.confirmed-atomic-trace"] = (
        "vistora.confirmed-atomic-trace"
    )
    trace_id: TraceId
    trace_sequence: int = Field(ge=1)
    execution_plan: EditingExecutionPlan
    request: AtomicToolRequestEnvelope
    result: AtomicToolResultEnvelope
    relations: tuple[ConfirmedEntityRelation, ...] = ()

    @model_validator(mode="after")
    def linkage_is_exact(self) -> ConfirmedAtomicTrace:
        execution = self.execution_plan
        confirmation = execution.confirmation
        if confirmation is None:
            raise ValueError("Confirmed trace requires a confirmation")
        plan_ref = PlanReference.from_plan(execution.director_plan)
        request = self.request
        if request.execution_id != execution.execution_id:
            raise ValueError("Atomic request crosses execution identity")
        if request.project_id != execution.project_id:
            raise ValueError("Atomic request crosses execution project")
        if request.confirmation_id != confirmation.confirmation_id:
            raise ValueError("Atomic request crosses confirmation identity")
        if request.plan_ref != plan_ref:
            raise ValueError("Atomic request crosses Director plan identity")

        steps = [
            step
            for step in execution.steps
            if step.step_id == request.step_id
        ]
        if len(steps) != 1:
            raise ValueError("Atomic request references an unknown step")
        step = steps[0]
        if (
            request.tool_name != step.tool_name
            or request.arguments != step.arguments
        ):
            raise ValueError("Atomic request drifts from its execution step")
        operations = {
            operation.operation_id: operation
            for operation in execution.director_plan.operations
        }
        operation = operations[step.source_operation_id]
        evidence_by_id = {
            evidence.evidence_id: evidence
            for evidence in execution.director_plan.source_evidence
        }
        expected_evidence = tuple(
            evidence_by_id[evidence_id]
            for evidence_id in operation.evidence_ids
        )
        if request.evidence_refs != expected_evidence:
            raise ValueError(
                "Atomic request evidence differs from confirmed intent"
            )

        result = self.result
        if (
            result.request_id != request.request_id
            or result.execution_id != request.execution_id
            or result.step_id != request.step_id
            or result.tool_name != request.tool_name
        ):
            raise ValueError("Atomic result crosses request linkage")
        if result.status != "success" and self.relations:
            raise ValueError("Non-success atomic results cannot affect entities")

        relation_ids = [relation.relation_id for relation in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("Confirmed relation IDs must be unique")
        relation_sequences = [
            relation.relation_sequence for relation in self.relations
        ]
        if sorted(relation_sequences) != list(
            range(1, len(relation_sequences) + 1)
        ):
            raise ValueError(
                "Confirmed relation sequences must be contiguous from one"
            )
        expected_evidence_ids = operation.evidence_ids
        for relation in self.relations:
            if (
                relation.source_operation_id != operation.operation_id
                or relation.step_id != step.step_id
                or relation.request_id != request.request_id
                or relation.result_id != result.result_id
            ):
                raise ValueError(
                    "Confirmed entity relation crosses atomic linkage"
                )
            if relation.evidence_ids != expected_evidence_ids:
                raise ValueError(
                    "Confirmed entity relation evidence is ambiguous"
                )
        return self


class ManualEntityRelation(TraceModel):
    """Truthful user-authored modification or deletion of one clip."""

    relation_id: TraceId
    relation_sequence: int = Field(ge=1)
    relation_type: Literal["creates", "modifies", "deletes"]
    origin_kind: Literal["user_manual"] = "user_manual"
    effect_kind: Literal["direct", "consequential"] = "direct"
    entity: TraceEntityReference
    operation_id: TraceId
    inherited_from_entity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    before_snapshot: SnapshotTraceReference
    after_snapshot: SnapshotTraceReference

    @model_validator(mode="after")
    def entity_is_a_clip(self) -> ManualEntityRelation:
        if self.entity.entity_kind not in {
            "clip",
            "track",
            "subtitle_track",
            "subtitle_cue",
            "transition",
            "automation",
            "mask",
            "composite",
        }:
            raise ValueError(
                "Manual edit traces may reference timeline entities only"
            )
        if (
            self.inherited_from_entity_id is not None
            and self.relation_type != "creates"
        ):
            raise ValueError(
                "Only a manually created clip can inherit clip provenance"
            )
        return self


class ManualEditTrace(TraceModel):
    """Exact user-authored proposal/confirmation/entity effect trace."""

    schema_name: Literal["vistora.manual-edit-trace"] = (
        "vistora.manual-edit-trace"
    )
    trace_id: TraceId
    trace_sequence: int = Field(ge=1)
    proposal: ManualEditProposal
    confirmation: ManualEditConfirmationRecord
    relations: tuple[ManualEntityRelation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def linkage_is_exact(self) -> ManualEditTrace:
        if not self.confirmation.confirms(self.proposal):
            raise ValueError(
                "Manual trace requires exact confirmed user proposal"
            )
        relation_ids = [relation.relation_id for relation in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("Manual relation IDs must be unique")
        relation_sequences = [
            relation.relation_sequence for relation in self.relations
        ]
        if sorted(relation_sequences) != list(
            range(1, len(relation_sequences) + 1)
        ):
            raise ValueError(
                "Manual relation sequences must be contiguous from one"
            )
        by_operation = {
            operation_id: tuple(
                relation
                for relation in self.relations
                if relation.operation_id == operation_id
            )
            for operation_id in {
                relation.operation_id for relation in self.relations
            }
        }
        if set(by_operation) != {
            edit.operation_id for edit in self.proposal.edits
        }:
            raise ValueError(
                "Manual trace must cover every proposal operation exactly"
            )
        for edit in self.proposal.edits:
            operation_relations = by_operation[edit.operation_id]
            direct = tuple(
                relation
                for relation in operation_relations
                if relation.effect_kind == "direct"
            )
            if isinstance(edit, (ManualTrackManage, ManualTrackMix)):
                if (
                    len(direct) != 1
                    or direct[0].entity.entity_kind != "track"
                    or direct[0].entity.entity_id != edit.track_id
                    or direct[0].relation_type != "modifies"
                ):
                    raise ValueError(
                        "Manual track trace differs from its proposal"
                    )
                continue
            if isinstance(edit, ManualSubtitleTrack):
                if (
                    len(direct) != 1
                    or direct[0].entity.entity_kind != "subtitle_track"
                    or direct[0].entity.entity_id != edit.track_id
                ):
                    raise ValueError("Manual subtitle track trace differs from proposal")
                continue
            if isinstance(edit, ManualSubtitleCue):
                if not direct or any(
                    relation.entity.entity_kind != "subtitle_cue"
                    or relation.entity.track_id != edit.track_id
                    for relation in direct
                ):
                    raise ValueError("Manual subtitle cue trace differs from proposal")
                continue
            if isinstance(edit, ManualTransitionEdit):
                if not direct or any(
                    relation.entity.entity_kind != "transition"
                    for relation in direct
                ):
                    raise ValueError(
                        "Manual transition trace differs from proposal"
                    )
                continue
            if isinstance(edit, ManualVisualAutomationEdit):
                if not direct or any(
                    relation.entity.entity_kind != "automation"
                    for relation in direct
                ):
                    raise ValueError(
                        "Manual visual automation trace differs from proposal"
                    )
                continue
            if isinstance(edit, ManualMaskEdit):
                expected_kind = "composite" if "composite" in edit.action else "mask"
                if not direct or any(
                    relation.entity.entity_kind != expected_kind
                    for relation in direct
                ):
                    raise ValueError("Manual mask/composite trace differs from proposal")
                continue
            if isinstance(edit, ManualClipLink):
                expected = {
                    (member.track_key, member.clip_id)
                    for member in edit.members
                }
                actual = {
                    (
                        relation.entity.track_key,
                        relation.entity.entity_id,
                    )
                    for relation in direct
                }
                if (
                    actual != expected
                    or any(
                        relation.relation_type != "modifies"
                        for relation in direct
                    )
                ):
                    raise ValueError(
                        "Manual link trace differs from its members"
                    )
                continue
            expected_direct_count = (
                2 if isinstance(edit, ManualClipSplit) else 1
            )
            if len(direct) != expected_direct_count:
                raise ValueError(
                    "Manual operation direct relation count is invalid"
                )
            relation = next(
                (
                    item
                    for item in direct
                    if item.entity.entity_id == edit.clip_id
                ),
                None,
            )
            if relation is None:
                raise ValueError(
                    "Manual trace is missing its exact target relation"
                )
            expected_type = (
                "deletes"
                if isinstance(edit, ManualClipRemove)
                else "modifies"
            )
            if (
                relation.relation_type != expected_type
                or relation.entity.entity_id != edit.clip_id
                or relation.entity.track_key != edit.track_key
            ):
                raise ValueError(
                    "Manual trace entity effect differs from proposal"
                )
            if isinstance(edit, ManualClipSplit):
                created = tuple(
                    item
                    for item in direct
                    if item.relation_type == "creates"
                )
                if (
                    len(created) != 1
                    or created[0].entity.entity_id != edit.right_clip_id
                    or created[0].entity.track_key != edit.track_key
                    or created[0].inherited_from_entity_id != edit.clip_id
                ):
                    raise ValueError(
                        "Manual split trace must create its exact right clip"
                    )
            for effect in operation_relations:
                before = effect.before_snapshot
                if (
                    before.project_id != self.proposal.base_project_id
                    or before.revision != self.proposal.base_revision
                    or before.timeline_digest
                    != self.proposal.base_timeline_digest
                ):
                    raise ValueError(
                        "Manual trace starts from a stale proposal snapshot"
                    )
                if effect.effect_kind == "consequential":
                    transition_consequence = (
                        effect.entity.entity_kind == "transition"
                        and effect.relation_type in {"modifies", "deletes"}
                    )
                    if not transition_consequence and (
                        effect.relation_type != "modifies"
                        or effect.entity == relation.entity
                    ):
                        raise ValueError(
                            "Consequential manual effects must modify a "
                            "different displaced clip or truthfully update/"
                            "tombstone a bound transition"
                        )
        return self


class TimelineTraceDocument(TraceModel):
    """Append-only trace sidecar; legacy timelines may omit it entirely."""

    schema_name: Literal["vistora.timeline-trace-document"] = (
        "vistora.timeline-trace-document"
    )
    document_id: TraceId = "trace_document_current"
    revision: int = Field(default=1, ge=1)
    confirmed_traces: tuple[ConfirmedAtomicTrace, ...] = ()
    manual_traces: tuple[ManualEditTrace, ...] = ()

    @model_validator(mode="after")
    def identities_are_globally_consistent(
        self,
    ) -> TimelineTraceDocument:
        trace_ids = [
            trace.trace_id
            for trace in (*self.confirmed_traces, *self.manual_traces)
        ]
        if len(trace_ids) != len(set(trace_ids)):
            raise ValueError("Trace IDs must be globally unique")
        sequences = [
            trace.trace_sequence
            for trace in (*self.confirmed_traces, *self.manual_traces)
        ]
        if sorted(sequences) != list(range(1, len(sequences) + 1)):
            raise ValueError(
                "Trace sequences must be unique and contiguous from one"
            )
        if self.revision != len(sequences) + 1:
            raise ValueError(
                "Trace document revision must equal event count plus one"
            )

        request_ids: set[str] = set()
        result_ids: set[str] = set()
        relation_ids: set[str] = set()
        plan_versions: dict[tuple[str, int], str] = {}
        confirmations: dict[str, PlanReference] = {}
        executions: dict[str, PlanReference] = {}
        for trace in self.confirmed_traces:
            request = trace.request
            result = trace.result
            if request.request_id in request_ids:
                raise ValueError("Atomic request IDs must be globally unique")
            if result.result_id in result_ids:
                raise ValueError("Atomic result IDs must be globally unique")
            request_ids.add(request.request_id)
            result_ids.add(result.result_id)
            plan_ref = request.plan_ref
            version_key = (plan_ref.plan_id, plan_ref.plan_version)
            existing_digest = plan_versions.setdefault(
                version_key,
                plan_ref.plan_digest,
            )
            if existing_digest != plan_ref.plan_digest:
                raise ValueError(
                    "One plan ID/version cannot have multiple digests"
                )
            existing_plan = confirmations.setdefault(
                request.confirmation_id,
                plan_ref,
            )
            if existing_plan != plan_ref:
                raise ValueError(
                    "One confirmation ID cannot cross Director plans"
                )
            existing_execution = executions.setdefault(
                request.execution_id,
                plan_ref,
            )
            if existing_execution != plan_ref:
                raise ValueError(
                    "One execution ID cannot cross Director plans"
                )
            for relation in trace.relations:
                if relation.relation_id in relation_ids:
                    raise ValueError(
                        "Entity relation IDs must be globally unique"
                    )
                relation_ids.add(relation.relation_id)

        proposal_refs: dict[str, Sha256Digest] = {}
        for trace in self.manual_traces:
            proposal_ref = trace.confirmation.proposal_ref
            existing_digest = proposal_refs.setdefault(
                proposal_ref.proposal_id,
                proposal_ref.proposal_digest,
            )
            if existing_digest != proposal_ref.proposal_digest:
                raise ValueError(
                    "One manual proposal ID cannot have multiple digests"
                )
            for relation in trace.relations:
                if relation.relation_id in relation_ids:
                    raise ValueError(
                        "Entity relation IDs must be globally unique"
                    )
                relation_ids.add(relation.relation_id)
        return self
