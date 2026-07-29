import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import main as vistora_main  # noqa: E402
import workflow.service as workflow_service_module  # noqa: E402
from agent import (  # noqa: E402
    EditingAgent,
    EditingAgentExecutionReport,
    EditingAgentExecutionRequest,
)
from contracts import DirectorOperation, DirectorPlan  # noqa: E402
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffRequest,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import (  # noqa: E402
    EditingExecutionRunRecord,
    WorkflowApplicationError,
    WorkflowApplicationService,
    WorkflowStore,
)


START = datetime(2026, 7, 30, 4, 0, tzinfo=timezone.utc)


class Deterministic:
    def __init__(self):
        self.index = 0

    def clock(self):
        value = START + timedelta(seconds=self.index)
        self.index += 1
        return value

    def identifier(self, prefix):
        self.index += 1
        return f"{prefix}_{self.index:04d}"


def _timeline():
    return TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[
                    ClipConfig(
                        id="clip_agent",
                        source="synthetic/missing.mp4",
                        trim_in=0.0,
                        trim_out=2.0,
                        timeline_start=0.0,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(id="audio"),
        },
    )


def _request(snapshot, *, operations=None, plan_id="plan_editing_agent"):
    operations = operations or (
        DirectorOperation(
            operation_id="operation_agent_clear",
            tool_name="VideoClearTimelineSkill",
            arguments={},
            rationale="Clear the deterministic test timeline.",
            expected_effect="Remove its one clip.",
        ),
    )
    plan = DirectorPlan(
        plan_id=plan_id,
        plan_version=1,
        created_at=START,
        objective="Exercise the constrained Editing Agent.",
        operations=operations,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id=f"execution_{plan_id}",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    return PlanDiffRequest(
        request_id=f"request_{plan_id}",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(
            vistora_main.SKILLS
        ),
    )


@pytest.fixture
def editing(tmp_path, monkeypatch):
    project_file = tmp_path / ".workspace" / "current_timeline.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text(_timeline().model_dump_json(indent=2))
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
    TraceabilityStore.trace_path(project_file).unlink(missing_ok=True)
    deterministic = Deterministic()
    registry = dict(vistora_main.SKILLS)
    workflow = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file),
        registry=registry,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    agent = EditingAgent(
        workflow,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return agent, workflow, project_file, registry


def _confirmed(agent, workflow, *, operations=None, plan_id="plan_editing_agent"):
    snapshot = TimelineSnapshotService.snapshot_current()
    review = workflow.record_review(
        _request(snapshot, operations=operations, plan_id=plan_id)
    )
    confirmation = workflow.confirm_review(
        review.review_id,
        confirmed_by="editing_agent_test_user",
        decision="confirmed",
    )
    request = agent.prepare_execution(
        request_id=f"agent_request_{plan_id}",
        confirmation_record_id=confirmation.confirmation_record_id,
    )
    return review, confirmation, request


def test_request_and_report_are_versioned_frozen_roundtrips(editing):
    agent, workflow, _, _ = editing
    _, _, request = _confirmed(agent, workflow)
    assert EditingAgentExecutionRequest.model_validate_json(
        request.model_dump_json()
    ) == request
    unsupported = request.model_dump(mode="json")
    unsupported["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError):
        EditingAgentExecutionRequest.model_validate(unsupported)
    with pytest.raises(ValidationError):
        request.binding.workflow_revision = 99

    report = agent.execute(request)
    assert report.status == "succeeded"
    assert report.disposition == "executed"
    assert report.binding == request.binding
    assert EditingAgentExecutionReport.model_validate_json(
        report.model_dump_json()
    ) == report
    assert [step.tool_name for step in report.steps] == [
        "VideoClearTimelineSkill"
    ]
    assert report.steps[0].atomic_request_id
    assert report.steps[0].atomic_result_id


def test_rejected_confirmation_never_becomes_an_agent_request(editing):
    agent, workflow, _, _ = editing
    snapshot = TimelineSnapshotService.snapshot_current()
    review = workflow.record_review(_request(snapshot))
    rejected = workflow.confirm_review(
        review.review_id,
        confirmed_by="editing_agent_test_user",
        decision="rejected",
    )
    with pytest.raises(
        WorkflowApplicationError,
        match="exact persisted confirmation",
    ):
        agent.prepare_execution(
            request_id="agent_request_rejected",
            confirmation_record_id=rejected.confirmation_record_id,
        )


def test_mismatched_confirmation_returns_structured_rejection(editing):
    agent, workflow, _, _ = editing
    _, _, request = _confirmed(agent, workflow)
    changed = request.model_copy(
        update={
            "binding": request.binding.model_copy(
                update={"confirmation_record_id": "confirmation_missing"}
            )
        }
    )
    report = agent.execute(changed)
    assert report.status == "rejected"
    assert report.disposition == "rejected"
    assert report.run_id is None
    assert report.steps == ()
    assert report.error.code == "confirmation_gate_rejected"


def test_snapshot_registry_and_workflow_revision_drift_fail_closed(editing):
    agent, workflow, project_file, registry = editing
    _, _, stale_snapshot = _confirmed(agent, workflow)
    project_file.write_text(
        _timeline().model_copy(update={"fps": 30}).model_dump_json(indent=2)
    )
    snapshot_report = agent.execute(stale_snapshot)
    assert snapshot_report.status == "rejected"
    assert snapshot_report.error.code == "snapshot_stale"

    project_file.write_text(_timeline().model_dump_json(indent=2))
    workflow.store.path.unlink(missing_ok=True)
    _, _, stale_registry = _confirmed(
        agent,
        workflow,
        plan_id="plan_registry_drift",
    )
    registry.pop("VideoTimelapseSkill")
    registry_report = agent.execute(stale_registry)
    assert registry_report.status == "rejected"
    assert registry_report.error.code == "registry_schema_stale"


def test_ledger_tamper_is_reported_and_never_dispatched(editing):
    agent, workflow, _, _ = editing
    _, _, request = _confirmed(agent, workflow)
    payload = json.loads(workflow.store.path.read_text())
    payload["entries"][0]["record"]["plan"]["objective"] = "tampered"
    workflow.store.path.write_text(json.dumps(payload))
    report = agent.execute(request)
    assert report.status == "rejected"
    assert report.error.code == "workflow_integrity_failed"
    assert report.steps == ()


def test_partial_atomic_failure_is_truthfully_reported_and_stops(editing):
    agent, workflow, _, registry = editing
    operations = (
        DirectorOperation(
            operation_id="operation_clear_first",
            tool_name="VideoClearTimelineSkill",
            arguments={},
            rationale="Clear first.",
            expected_effect="Timeline becomes empty.",
        ),
        DirectorOperation(
            operation_id="operation_clear_second",
            tool_name="VideoClearTimelineSkill",
            arguments={},
            rationale="Exercise a bounded failure.",
            expected_effect="No further timeline change.",
        ),
    )
    _, _, request = _confirmed(
        agent,
        workflow,
        operations=operations,
        plan_id="plan_partial_agent",
    )
    original = registry["VideoClearTimelineSkill"]

    class FailSecondClear:
        name = original.name
        input_model = original.input_model

        def __init__(self):
            self.calls = 0

        def execute(self, arguments):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic second-step failure")
            return original.execute(arguments)

    registry["VideoClearTimelineSkill"] = FailSecondClear()
    report = agent.execute(request)
    assert report.status == "partial"
    assert report.disposition == "executed"
    assert [step.status for step in report.steps] == ["success", "error"]
    assert report.error.code == "atomic_dispatch_failed"
    assert report.steps[-1].error.code == "atomic_dispatch_failed"


def test_first_atomic_failure_is_reported_as_failed(editing):
    agent, workflow, _, registry = editing
    _, _, request = _confirmed(agent, workflow)
    original = registry["VideoClearTimelineSkill"]

    class FailImmediately:
        name = original.name
        input_model = original.input_model

        def execute(self, arguments):
            raise RuntimeError("synthetic first-step failure")

    registry["VideoClearTimelineSkill"] = FailImmediately()
    report = agent.execute(request)
    assert report.status == "failed"
    assert report.disposition == "executed"
    assert [step.status for step in report.steps] == ["error"]
    assert report.start_snapshot == report.latest_snapshot
    assert report.error.code == "atomic_dispatch_failed"


def test_trace_failure_without_timeline_change_requires_recovery(
    editing,
    monkeypatch,
):
    agent, workflow, project_file, _ = editing
    project_file.unlink()
    _, _, request = _confirmed(
        agent,
        workflow,
        plan_id="plan_trace_recovery",
    )

    def fail_trace(*args, **kwargs):
        raise RuntimeError("synthetic trace persistence failure")

    monkeypatch.setattr(
        workflow_service_module.ConfirmedTraceRecorder,
        "record",
        fail_trace,
    )
    report = agent.execute(request)
    assert report.status == "recovery_required"
    assert report.disposition == "executed"
    assert report.error.code == "trace_persistence_failed"


def test_concurrent_operation_returns_retryable_rejection(editing):
    agent, workflow, _, _ = editing
    _, confirmation, request = _confirmed(agent, workflow)
    with workflow.store.exclusive(project_id=confirmation.project_id):
        report = agent.execute(request)
    assert report.status == "rejected"
    assert report.error.code == "workflow_concurrency_conflict"
    assert report.error.retryable is True


def test_restart_recovery_marks_interrupted_run_without_guessing(editing):
    agent, workflow, _, _ = editing
    _, confirmation, request = _confirmed(agent, workflow)
    original_append = workflow._append
    running_writes = 0

    def interrupt_after_running(session, record):
        nonlocal running_writes
        original_append(session, record)
        if (
            isinstance(record, EditingExecutionRunRecord)
            and record.status == "running"
            and not record.steps
        ):
            running_writes += 1
            raise KeyboardInterrupt

    workflow._append = interrupt_after_running
    with pytest.raises(KeyboardInterrupt):
        agent.execute(request)
    workflow._append = original_append

    recovery = agent.recover_interrupted_runs(confirmation.project_id)
    assert recovery.status == "recovery_required"
    assert len(recovery.recovered_run_ids) == 1
    latest = [
        entry.record
        for entry in workflow.store.load().entries
        if isinstance(entry.record, EditingExecutionRunRecord)
    ][-1]
    assert latest.status == "recovery_required"
    assert latest.error.code == "interrupted_execution"


def test_confirmation_replay_returns_structured_rejection(editing):
    agent, workflow, _, _ = editing
    _, _, request = _confirmed(agent, workflow)
    assert agent.execute(request).status == "succeeded"
    replay = agent.execute(request)
    assert replay.status == "rejected"
    assert replay.error.code == "confirmation_replay_rejected"
