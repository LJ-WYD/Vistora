import json
import sys
import ast
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import main as vistora_main  # noqa: E402
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
    RollbackRunRecord,
    WorkflowApplicationError,
    WorkflowApplicationService,
    WorkflowConcurrencyError,
    WorkflowIntegrityError,
    WorkflowLedger,
    WorkflowStore,
    WorkflowHistoryQuery,
)
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402


START = datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc)


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
                        id="clip_existing",
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


def _request(snapshot, operations=None, plan_id="plan_workflow"):
    operations = operations or (
        DirectorOperation(
            operation_id="operation_clear",
            tool_name="VideoClearTimelineSkill",
            arguments={},
            rationale="Create a deterministic rollback example.",
            expected_effect="Remove the existing timeline clip.",
        ),
    )
    plan = DirectorPlan(
        plan_id=plan_id,
        plan_version=1,
        created_at=START,
        objective="Clear the synthetic timeline through an atomic tool.",
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
def service(tmp_path, monkeypatch):
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
    app = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file),
        registry=vistora_main.SKILLS,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return app, project_file


def _review_confirm(service):
    snapshot = TimelineSnapshotService.snapshot_current()
    review = service.record_review(_request(snapshot))
    confirmation = service.confirm_review(
        review.review_id,
        confirmed_by="workflow_test_user",
        decision="confirmed",
    )
    return review, confirmation


@contextmanager
def _server(application):
    server = create_preview_server(application, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _http(url, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            **(
                {"Content-Type": "application/json"}
                if data is not None
                else {}
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_workflow_roundtrip_hash_chain_and_tamper_detection(service):
    app, _ = service
    _review_confirm(app)
    ledger = app.store.load()
    assert WorkflowLedger.model_validate_json(
        ledger.model_dump_json()
    ) == ledger
    assert ledger.revision == 3
    payload = json.loads(app.store.path.read_text())
    payload["entries"][0]["record"]["plan"]["objective"] = "tampered"
    app.store.path.write_text(json.dumps(payload))
    with pytest.raises(WorkflowIntegrityError):
        app.store.load()


def test_empty_v0_migration_and_unknown_version_fail_closed():
    migrated = WorkflowLedger.model_validate(
        {"project_id": "project_legacy", "entries": []}
    )
    assert migrated.migration_source == "legacy.workflow.v0"
    with pytest.raises(ValidationError):
        WorkflowLedger.model_validate(
            {
                **migrated.model_dump(mode="json"),
                "schema_version": "2.0.0",
            }
        )


def test_explicit_confirmation_is_exact_and_cannot_replay(service):
    app, _ = service
    review, confirmation = _review_confirm(app)
    assert confirmation.review_id == review.review_id
    assert confirmation.diff_digest == review.diff_digest
    with pytest.raises((WorkflowApplicationError, ValidationError)):
        app.confirm_review(
            review.review_id,
            confirmed_by="workflow_test_user",
            decision="confirmed",
        )


def test_rejected_review_cannot_execute(service):
    app, _ = service
    snapshot = TimelineSnapshotService.snapshot_current()
    review = app.record_review(_request(snapshot))
    rejected = app.confirm_review(
        review.review_id,
        confirmed_by="workflow_test_user",
        decision="rejected",
    )
    with pytest.raises(WorkflowApplicationError):
        app.run_confirmed_execution(rejected.confirmation_record_id)


def test_snapshot_and_registry_drift_fail_before_execution(service):
    app, project_file = service
    _, confirmation = _review_confirm(app)
    project_file.write_text(
        TimelineConfig(
            width=640,
            height=360,
            fps=24,
            tracks={
                "video": TrackConfig(id="video"),
                "audio": TrackConfig(id="audio"),
            },
        ).model_dump_json()
    )
    with pytest.raises(WorkflowApplicationError, match="drifted"):
        app.run_confirmed_execution(confirmation.confirmation_record_id)


def test_confirmed_execution_records_each_transition_and_provenance(service):
    app, project_file = service
    _, confirmation = _review_confirm(app)
    terminal = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    assert terminal.status == "succeeded"
    assert len(terminal.steps) == 1
    assert terminal.steps[0].result.status == "success"
    assert not project_file.exists()
    records = [
        entry.record
        for entry in app.store.load().entries
        if isinstance(entry.record, EditingExecutionRunRecord)
    ]
    assert [record.status for record in records] == [
        "execution_pending",
        "running",
        "running",
        "succeeded",
    ]
    trace = TraceabilityStore.load(project_file)
    assert trace.confirmed_traces[0].request.step_id == "operation_clear"
    assert trace.confirmed_traces[0].relations[0].relation_type == "deletes"


def test_legacy_content_identity_change_allows_next_exact_plan(service):
    app, _ = service
    original_snapshot_id = TimelineSnapshotService.snapshot_current().snapshot_id
    _, confirmation = _review_confirm(app)
    first = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    assert first.status == "succeeded"
    next_snapshot = TimelineSnapshotService.snapshot_current()
    assert next_snapshot.snapshot_id != original_snapshot_id
    next_request = _request(
        next_snapshot,
        (
            DirectorOperation(
                operation_id="operation_next_clear",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Review the next exact legacy snapshot.",
                expected_effect="Keep the timeline empty.",
            ),
        ),
        plan_id="plan_workflow_next",
    )
    next_review = app.record_review(next_request)
    assert next_review.project_id == confirmation.project_id
    assert (
        next_review.request.snapshot_ref.project_id
        == next_snapshot.project_id
    )


def test_rollback_requires_separate_review_confirmation_and_restores(service):
    app, project_file = service
    _, confirmation = _review_confirm(app)
    executed = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    rollback_review = app.propose_rollback(executed.run_id)
    assert rollback_review.proposal.changes[0].relation_type == "restores"
    assert any(
        "Does not delete" in item
        for item in rollback_review.proposal.limitations
    )
    rollback_confirmation = app.confirm_rollback(
        rollback_review.review_id,
        confirmed_by="workflow_test_user",
        decision="confirmed",
    )
    terminal = app.apply_rollback(
        rollback_confirmation.confirmation_id
    )
    assert terminal.status == "succeeded"
    assert project_file.exists()
    restored = timeline_manager.TimelineManager.get_current_timeline()
    assert restored.tracks["video"].clips[0].id == "clip_existing"
    rollback_records = [
        entry.record
        for entry in app.store.load().entries
        if isinstance(entry.record, RollbackRunRecord)
    ]
    assert [record.status for record in rollback_records] == [
        "rollback_pending",
        "running",
        "succeeded",
    ]


def test_rollback_failure_is_recorded_without_claiming_restore(
    service,
    monkeypatch,
):
    app, project_file = service
    _, confirmation = _review_confirm(app)
    executed = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    review = app.propose_rollback(executed.run_id)
    confirmation = app.confirm_rollback(
        review.review_id,
        confirmed_by="workflow_test_user",
        decision="confirmed",
    )
    original = vistora_main.SKILLS[
        "VideoRestoreTimelineCheckpointSkill"
    ]

    class FailedRestore:
        name = original.name
        input_model = original.input_model

        def execute(self, arguments):
            raise RuntimeError("synthetic restore failure")

    monkeypatch.setitem(
        vistora_main.SKILLS,
        "VideoRestoreTimelineCheckpointSkill",
        FailedRestore(),
    )
    terminal = app.apply_rollback(confirmation.confirmation_id)
    assert terminal.status == "failed"
    assert terminal.error.code == "rollback_failed"
    assert not project_file.exists()


def test_manual_edit_after_execution_makes_rollback_fail_closed(service):
    app, _ = service
    _, confirmation = _review_confirm(app)
    executed = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    timeline_manager.TimelineManager.save_current_timeline(
        TimelineConfig(
            tracks={
                "video": TrackConfig(
                    id="video",
                    clips=[
                        ClipConfig(
                            id="manual_clip",
                            source="manual.mp4",
                            trim_out=1.0,
                        )
                    ],
                ),
                "audio": TrackConfig(id="audio"),
            }
        )
    )
    with pytest.raises(WorkflowApplicationError, match="drifted"):
        app.propose_rollback(executed.run_id)


def test_concurrent_project_lock_serializes_operations(service):
    app, _ = service
    project_id = TimelineSnapshotService.snapshot_current().project_id
    with app.store.exclusive(project_id=project_id):
        with pytest.raises(WorkflowConcurrencyError):
            with app.store.exclusive(project_id=project_id):
                pass


def test_restart_can_reclaim_only_a_dead_well_formed_lock(service):
    app, _ = service
    project_id = TimelineSnapshotService.snapshot_current().project_id
    app.store.lock_path.write_text(
        "pid=2147483647\n"
        "token=dead-process-token\n"
    )
    with app.store.exclusive(project_id=project_id) as session:
        assert session.ledger.project_id == project_id
    app.store.lock_path.write_text("corrupt-lock")
    with pytest.raises(WorkflowConcurrencyError):
        with app.store.exclusive(project_id=project_id):
            pass
    app.store.lock_path.unlink()


def test_interrupted_run_is_recovered_as_recovery_required(service):
    app, _ = service
    _, confirmation = _review_confirm(app)
    original_append = app._append
    terminal_writes = 0

    def interrupt_after_running(session, record):
        nonlocal terminal_writes
        original_append(session, record)
        if (
            isinstance(record, EditingExecutionRunRecord)
            and record.status == "running"
        ):
            terminal_writes += 1
            if terminal_writes == 1:
                raise KeyboardInterrupt()

    app._append = interrupt_after_running
    with pytest.raises(KeyboardInterrupt):
        app.run_confirmed_execution(confirmation.confirmation_record_id)
    app._append = original_append
    recovered = app.recover_interrupted_runs(
        confirmation.project_id
    )
    latest = [
        entry.record
        for entry in recovered.entries
        if isinstance(entry.record, EditingExecutionRunRecord)
    ][-1]
    assert latest.status == "recovery_required"


def test_history_projection_redacts_paths_and_excludes_raw_arguments(service):
    app, _ = service
    _, confirmation = _review_confirm(app)
    terminal = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    payload = WorkflowHistoryQuery.project(
        app.store.load()
    ).model_dump_json()
    assert "synthetic/missing.mp4" not in payload
    assert "arguments" not in payload
    assert terminal.steps[0].request.request_id in payload


def test_browser_workflow_routes_are_explicit_and_history_is_safe(service):
    app, _ = service
    request = _request(TimelineSnapshotService.snapshot_current())
    preview = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        skill_registry=vistora_main.SKILLS,
        plan_review_request_provider=lambda: request,
        workflow_service=app,
    )
    with _server(preview) as base:
        status, history = _http(f"{base}/api/workflow")
        assert status == 200
        assert history["schema_name"] == "vistora.workflow-history"
        status, reviewed = _http(
            f"{base}/api/workflow/reviews",
            "POST",
            {},
        )
        assert status == 200
        review_id = reviewed["result"]["review_id"]
        status, confirmed = _http(
            f"{base}/api/workflow/confirmations",
            "POST",
            {
                "review_id": review_id,
                "confirmed_by": "browser_test_user",
                "decision": "confirmed",
            },
        )
        assert status == 200
        confirmation_id = confirmed["result"][
            "confirmation_record_id"
        ]
        assert Path(app.store.path).exists()
        status, executed = _http(
            f"{base}/api/workflow/executions",
            "POST",
            {"confirmation_record_id": confirmation_id},
        )
        assert status == 200
        assert executed["result"]["status"] == "succeeded"
        serialized = json.dumps(executed)
        assert "synthetic/missing.mp4" not in serialized
        status, rejected = _http(
            f"{base}/api/workflow/executions",
            "POST",
            {"confirmation_record_id": confirmation_id},
        )
        assert status in {409, 422}
        assert "error" in rejected


def test_stop_on_failure_records_partial_and_does_not_continue(
    service,
    monkeypatch,
):
    app, tmp_project = service
    snapshot = TimelineSnapshotService.snapshot_current()
    request = _request(
        snapshot,
        (
            DirectorOperation(
                operation_id="operation_clear",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Remove the clip first.",
                expected_effect="Empty timeline.",
            ),
            DirectorOperation(
                operation_id="operation_clear_again",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Exercise deterministic dispatch failure history.",
                expected_effect="Remain empty.",
            ),
        ),
    )
    review = app.record_review(request)
    confirmation = app.confirm_review(
        review.review_id,
        confirmed_by="workflow_test_user",
        decision="confirmed",
    )
    original = vistora_main.SKILLS["VideoClearTimelineSkill"]

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

    monkeypatch.setitem(
        vistora_main.SKILLS,
        "VideoClearTimelineSkill",
        FailSecondClear(),
    )
    terminal = app.run_confirmed_execution(
        confirmation.confirmation_record_id
    )
    assert terminal.status == "partial"
    assert [step.result.status for step in terminal.steps] == [
        "success",
        "error",
    ]
    assert terminal.error.code == "atomic_dispatch_failed"


def test_workflow_import_boundaries_keep_queries_and_agents_non_mutating():
    def imports(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        result = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                result.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                result.add(node.module)
        return result

    forbidden_read_imports = {
        "core.timeline_manager",
        "skills",
        "timeline_preview",
        "agent",
    }
    for name in ("models.py", "store.py", "query.py"):
        imported = imports(SRC / "workflow" / name)
        assert not imported.intersection(forbidden_read_imports)
    for path in (SRC / "agent").glob("*.py"):
        assert "workflow" not in imports(path)
