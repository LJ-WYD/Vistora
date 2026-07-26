import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    DirectorOperation,
    DirectorPlan,
    EditingExecutionPlan,
    ManualClipRemove,
    ManualClipUpdate,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    MediaTimeRangeLocator,
    PlanReference,
    SourceEvidenceReference,
    UserConfirmationRecord,
)
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from timeline_preview import PreviewApplication  # noqa: E402
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.models import (  # noqa: E402
    ConfirmedAtomicTrace,
    TimelineTraceDocument,
)
from traceability.query import (  # noqa: E402
    TraceabilityQuery,
    TraceabilityQueryError,
)
from traceability.recording import (  # noqa: E402
    ConfirmedTraceRecorder,
    ManualTraceRecorder,
)
from traceability.store import TraceabilityStore  # noqa: E402


NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
SOURCE = "C:/private/media/source.mp4"
EVIDENCE_ID = "evidence_source_range"


def _timeline(
    *,
    clip: bool = False,
    trim_in: float = 0.0,
    timeline_start: float = 0.0,
) -> TimelineConfig:
    clips = (
        [
            ClipConfig(
                id="clip_trace",
                source=SOURCE,
                trim_in=trim_in,
                trim_out=2.0,
                timeline_start=timeline_start,
                keep_audio=False,
            )
        ]
        if clip
        else []
    )
    return TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(id="video", clips=clips),
            "audio": TrackConfig(id="audio"),
        },
    )


def _execution_bundle():
    evidence = SourceEvidenceReference(
        evidence_id=EVIDENCE_ID,
        material_id=(
            TimelineSnapshotService.source_id_for_configured_path(SOURCE)
        ),
        locator=MediaTimeRangeLocator(
            start_seconds=0.25,
            end_seconds=1.75,
        ),
        analysis_fact_id="analysis_fact_demo",
        analysis_fact_digest="sha256:" + ("a" * 64),
    )
    operation = DirectorOperation(
        operation_id="operation_add_trace_clip",
        tool_name="VideoAddClipSkill",
        arguments={
            "source_path": SOURCE,
            "trim_in": 0.0,
            "trim_out": 2.0,
        },
        rationale="Use the verified evidence range.",
        expected_effect="Create one traceable clip.",
        evidence_ids=(EVIDENCE_ID,),
    )
    plan = DirectorPlan(
        plan_id="plan_trace_demo",
        plan_version=1,
        created_at=NOW,
        objective="Create a traceable clip.",
        source_evidence=(evidence,),
        operations=(operation,),
    )
    confirmation = UserConfirmationRecord.for_plan(
        confirmation_id="confirmation_trace_demo",
        plan=plan,
        confirmed_by="user_demo",
        recorded_at=NOW,
    )
    execution = EditingExecutionPlan.from_confirmed_plan(
        execution_id="execution_trace_demo",
        project_id="project_trace_demo",
        director_plan=plan,
        confirmation=confirmation,
    )
    request = AtomicToolRequestEnvelope.from_execution_plan(
        request_id="request_trace_demo",
        execution_plan=execution,
        step_id=operation.operation_id,
    )
    result = AtomicToolResultEnvelope(
        result_id="result_trace_demo",
        request_id=request.request_id,
        execution_id=request.execution_id,
        step_id=request.step_id,
        tool_name=request.tool_name,
        status="success",
        payload={"clip_id": "clip_trace"},
        started_at=NOW,
        finished_at=NOW,
    )
    return plan, execution, request, result


@pytest.fixture
def isolated_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    project_file = tmp_path / "workspace" / "current_timeline.json"
    monkeypatch.setattr(
        timeline_manager,
        "WORKSPACE_DIR",
        str(project_file.parent),
    )
    monkeypatch.setattr(
        timeline_manager,
        "PROJECT_FILE",
        str(project_file),
    )
    return project_file


def _record_create():
    plan, execution, request, result = _execution_bundle()
    before = TimelineSnapshotService.snapshot(_timeline())
    after = TimelineSnapshotService.snapshot(_timeline(clip=True))
    trace = ConfirmedTraceRecorder.record(
        execution,
        request,
        result,
        before,
        after,
    )
    return plan, trace, after


def test_versioned_round_trip_exact_linkage_and_queries(
    isolated_store: Path,
) -> None:
    plan, trace, snapshot = _record_create()
    document = TraceabilityStore.load()
    round_trip = TimelineTraceDocument.model_validate_json(
        document.model_dump_json()
    )
    query = TraceabilityQuery(round_trip, snapshot)

    clip = query.clip_to_trace("video", "clip_trace")
    assert trace.schema_version == "1.0.0"
    assert document.schema_name == "vistora.timeline-trace-document"
    assert clip.present is True
    assert clip.provenance.mapping_status == "current"
    assert clip.provenance.origin_kind == "director_plan"
    assert clip.provenance.plan_id == plan.plan_id
    assert clip.provenance.request_id == "request_trace_demo"
    assert clip.provenance.evidence[0].material_id.startswith("source_")
    assert query.plan_to_clips(PlanReference.from_plan(plan)) == (clip,)
    assert query.evidence_to_clips(EVIDENCE_ID) == (clip,)
    assert ConfirmedAtomicTrace.model_json_schema()["properties"][
        "schema_name"
    ]["const"] == "vistora.confirmed-atomic-trace"
    assert TimelineTraceDocument.model_json_schema()["properties"][
        "schema_version"
    ]["const"] == "1.0.0"


def test_evidence_locators_and_operation_references_are_strict() -> None:
    with pytest.raises(ValidationError, match="forward"):
        MediaTimeRangeLocator(
            start_seconds=2.0,
            end_seconds=1.0,
        )
    with pytest.raises(ValidationError, match="unique"):
        DirectorOperation(
            operation_id="operation_duplicate_evidence",
            tool_name="VideoAddClipSkill",
            rationale="Test duplicate evidence.",
            expected_effect="No execution.",
            evidence_ids=(EVIDENCE_ID, EVIDENCE_ID),
        )
    with pytest.raises(ValidationError, match="unknown evidence"):
        DirectorPlan(
            plan_id="plan_unknown_evidence",
            plan_version=1,
            created_at=NOW,
            objective="Reject unknown evidence.",
            operations=(
                DirectorOperation(
                    operation_id="operation_unknown_evidence",
                    tool_name="VideoAddClipSkill",
                    rationale="Test unknown evidence.",
                    expected_effect="No execution.",
                    evidence_ids=(EVIDENCE_ID,),
                ),
            ),
        )


def test_mismatched_duplicate_and_cross_plan_traces_are_rejected(
    isolated_store: Path,
) -> None:
    _, trace, _ = _record_create()
    mismatch_cases = (
        (
            lambda value: value["request"].__setitem__(
                "execution_id",
                "execution_other",
            ),
            "crosses execution identity",
        ),
        (
            lambda value: value["request"].__setitem__(
                "confirmation_id",
                "confirmation_other",
            ),
            "crosses confirmation identity",
        ),
        (
            lambda value: value["request"]["plan_ref"].__setitem__(
                "plan_digest",
                "sha256:" + ("0" * 64),
            ),
            "crosses Director plan identity",
        ),
        (
            lambda value: value["request"].__setitem__(
                "evidence_refs",
                [],
            ),
            "evidence differs from confirmed intent",
        ),
        (
            lambda value: value["result"].__setitem__(
                "request_id",
                "request_other",
            ),
            "result crosses request linkage",
        ),
        (
            lambda value: value["relations"][0].__setitem__(
                "step_id",
                "step_other",
            ),
            "relation crosses atomic linkage",
        ),
    )
    for mutate, message in mismatch_cases:
        mismatched = json.loads(trace.model_dump_json())
        mutate(mismatched)
        with pytest.raises(ValidationError, match=message):
            ConfirmedAtomicTrace.model_validate(mismatched)

    with pytest.raises(ValidationError, match="Trace IDs"):
        TimelineTraceDocument(
            revision=3,
            confirmed_traces=(trace, trace),
        )
    with pytest.raises(ValueError, match="sequence must be 2"):
        TraceabilityStore.append_confirmed(trace)


def test_legacy_absence_stale_revision_and_orphan_are_explicit(
    isolated_store: Path,
) -> None:
    legacy = TimelineSnapshotService.snapshot(_timeline(clip=True))
    legacy_query = TraceabilityQuery(TimelineTraceDocument(), legacy)
    assert (
        legacy_query.clip_to_trace("video", "clip_trace")
        .provenance.mapping_status
        == "legacy_unknown"
    )
    assert not TraceabilityStore.trace_path().exists()

    plan, _, recorded = _record_create()
    changed = TimelineSnapshotService.snapshot(
        _timeline(clip=True, trim_in=0.25)
    )
    query = TraceabilityQuery(TraceabilityStore.load(), changed)
    assert (
        query.clip_to_trace("video", "clip_trace")
        .provenance.mapping_status
        == "stale"
    )
    with pytest.raises(TraceabilityQueryError, match="stale"):
        TraceabilityQuery(
            TraceabilityStore.load(),
            changed,
            expected_reference=TimelineSnapshotReference.from_snapshot(
                recorded
            ),
        )

    empty = TimelineSnapshotService.snapshot(_timeline())
    orphan = TraceabilityQuery(
        TraceabilityStore.load(),
        empty,
    ).plan_to_clips(PlanReference.from_plan(plan))[0]
    assert orphan.present is False
    assert orphan.provenance.mapping_status == "orphaned"
    orphan_snapshot = TimelineSnapshotService.snapshot(
        _timeline(),
        trace_document=TraceabilityStore.load(),
    )
    assert orphan_snapshot.orphaned_provenance == (orphan,)
    assert (
        TimelineSnapshotService.snapshot(
            _timeline(),
            trace_document=TraceabilityStore.load(),
        ).model_dump_json()
        == orphan_snapshot.model_dump_json()
    )


def test_manual_update_preserves_origin_and_delete_keeps_tombstone(
    isolated_store: Path,
) -> None:
    plan, _, before = _record_create()
    update = ManualEditProposal(
        proposal_id="manual_trace_update",
        authored_by="local_user",
        base_project_id=before.project_id,
        base_revision=before.revision,
        base_timeline_digest=before.timeline_digest,
        edits=(
            ManualClipUpdate(
                operation_id="manual_update_trace",
                clip_id="clip_trace",
                trim_in_seconds=0.25,
                trim_out_seconds=2.0,
                timeline_start_seconds=1.0,
                order_index=0,
            ),
        ),
        created_at=NOW,
    )
    update_confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="manual_confirmation_update",
        proposal=update,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    updated = TimelineSnapshotService.snapshot(
        _timeline(clip=True, trim_in=0.25, timeline_start=1.0)
    )
    ManualTraceRecorder.record(
        update,
        update_confirmation,
        before,
        updated,
    )
    changed = TraceabilityQuery(
        TraceabilityStore.load(),
        updated,
    ).clip_to_trace("video", "clip_trace")
    assert changed.provenance.origin_kind == "director_plan"
    assert changed.provenance.latest_change_origin == "user_manual"
    assert changed.provenance.plan_id == plan.plan_id

    remove = ManualEditProposal(
        proposal_id="manual_trace_remove",
        authored_by="local_user",
        base_project_id=updated.project_id,
        base_revision=updated.revision,
        base_timeline_digest=updated.timeline_digest,
        edits=(
            ManualClipRemove(
                operation_id="manual_remove_trace",
                clip_id="clip_trace",
            ),
        ),
        created_at=NOW,
    )
    remove_confirmation = ManualEditConfirmationRecord.for_proposal(
        confirmation_id="manual_confirmation_remove",
        proposal=remove,
        confirmed_by="local_user",
        recorded_at=NOW,
    )
    empty = TimelineSnapshotService.snapshot(_timeline())
    ManualTraceRecorder.record(
        remove,
        remove_confirmation,
        updated,
        empty,
    )
    tombstone = TraceabilityQuery(
        TraceabilityStore.load(),
        empty,
    ).plan_to_clips(PlanReference.from_plan(plan))[0]
    assert tombstone.present is False
    assert tombstone.provenance.mapping_status == "deleted"
    assert tombstone.provenance.latest_change_origin == "user_manual"


def test_snapshot_provenance_is_detached_and_browser_paths_are_redacted(
    isolated_store: Path,
) -> None:
    _, _, snapshot = _record_create()
    traced = TimelineSnapshotService.snapshot(
        _timeline(clip=True),
        trace_document=TraceabilityStore.load(),
    )
    source = _timeline(clip=True)
    payload = PreviewApplication(lambda: traced).snapshot_payload()
    serialized = json.dumps(payload)

    assert SOURCE not in serialized
    assert payload["snapshot"]["tracks"][0]["clips"][0][
        "provenance"
    ]["mapping_status"] == "current"
    traced.tracks[0].clips[0].model_copy(
        update={"trim_in_seconds": 999.0}
    )
    assert source.tracks["video"].clips[0].trim_in == 0.0
