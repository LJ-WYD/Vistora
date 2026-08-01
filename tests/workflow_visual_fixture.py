"""Local-only browser fixture for the complete step-9 workflow history UI."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


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
from timeline_preview import (  # noqa: E402
    PreviewApplication,
    create_preview_server,
)
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import (  # noqa: E402
    EditingExecutionRunRecord,
    WorkflowApplicationService,
    WorkflowStore,
)


FIXTURE_TIME = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)


class DeterministicFixture:
    def __init__(self) -> None:
        self.counter = 0

    def clock(self) -> datetime:
        value = FIXTURE_TIME + timedelta(seconds=self.counter)
        self.counter += 1
        return value

    def identifier(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_visual_{self.counter:04d}"


def request_for(
    plan_id: str,
    objective: str,
    operations: tuple[DirectorOperation, ...],
) -> PlanDiffRequest:
    snapshot = TimelineSnapshotService.snapshot_current()
    plan = DirectorPlan(
        plan_id=plan_id,
        plan_version=1,
        created_at=FIXTURE_TIME,
        objective=objective,
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


def seed_fixture(workspace: Path) -> tuple[
    WorkflowApplicationService,
    PlanDiffRequest,
]:
    project_file = workspace / "current_timeline.json"
    workspace.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tests/test_data/reference_workflow/source.mp4"
    timeline = TimelineConfig(
        width=320,
        height=180,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video",
                kind="video",
                role="primary",
                order=0,
                clips=[
                    ClipConfig(
                        id="clip_workflow_visual",
                        source=str(source),
                        trim_in=0.0,
                        trim_out=1.5,
                        timeline_start=0.0,
                        keep_audio=False,
                        link_group_id="link_visual_primary",
                    )
                ],
            ),
            "overlay": TrackConfig(
                id="track_overlay_visual",
                kind="video",
                role="overlay",
                order=1,
                clips=[
                    ClipConfig(
                        id="clip_overlay_visual",
                        source=str(source),
                        trim_in=0.0,
                        trim_out=1.0,
                        timeline_start=0.25,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(
                id="audio",
                kind="audio",
                role="dialogue",
                order=2,
                clips=[
                    ClipConfig(
                        id="clip_dialogue_visual",
                        source=str(source),
                        trim_in=0.0,
                        trim_out=1.5,
                        timeline_start=0.0,
                        link_group_id="link_visual_primary",
                    )
                ],
            ),
            "music": TrackConfig(
                id="track_music_visual",
                kind="audio",
                role="music",
                order=3,
                muted=True,
            ),
        },
    )
    project_file.write_text(timeline.model_dump_json(indent=2))
    timeline_manager.WORKSPACE_DIR = str(workspace)
    timeline_manager.PROJECT_FILE = str(project_file)
    TraceabilityStore.trace_path(project_file).unlink(missing_ok=True)
    workflow_store = WorkflowStore.for_project_file(project_file)
    workflow_store.path.unlink(missing_ok=True)
    workflow_store.lock_path.unlink(missing_ok=True)

    deterministic = DeterministicFixture()
    service = WorkflowApplicationService(
        store=workflow_store,
        registry=vistora_main.SKILLS,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )

    success_request = request_for(
        "plan_visual_success",
        "Demonstrate a successful recorded clip-speed change.",
        (
            DirectorOperation(
                operation_id="operation_visual_speed",
                tool_name="VideoModifyClipSkill",
                arguments={"target_index": 0, "speed_factor": 1.25},
                rationale="Tighten the synthetic clip.",
                expected_effect="Shorten its effective timeline duration.",
            ),
        ),
    )
    success_review = service.record_review(success_request)
    success_confirmation = service.confirm_review(
        success_review.review_id,
        confirmed_by="visual_fixture_user",
        decision="confirmed",
    )
    succeeded = service.run_confirmed_execution(
        success_confirmation.confirmation_record_id
    )
    rollback_review = service.propose_rollback(succeeded.run_id)
    rollback_confirmation = service.confirm_rollback(
        rollback_review.review_id,
        confirmed_by="visual_fixture_user",
        decision="confirmed",
    )
    service.apply_rollback(rollback_confirmation.confirmation_id)

    failure_request = request_for(
        "plan_visual_partial",
        "Demonstrate stopped partial execution.",
        (
            DirectorOperation(
                operation_id="operation_visual_clear",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Clear the synthetic timeline.",
                expected_effect="Remove the clip.",
            ),
            DirectorOperation(
                operation_id="operation_visual_fail",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Exercise a synthetic dispatch failure.",
                expected_effect="Remain empty.",
            ),
        ),
    )
    failure_review = service.record_review(failure_request)
    failure_confirmation = service.confirm_review(
        failure_review.review_id,
        confirmed_by="visual_fixture_user",
        decision="confirmed",
    )
    original_clear = vistora_main.SKILLS["VideoClearTimelineSkill"]

    class FailSecond:
        name = original_clear.name
        input_model = original_clear.input_model

        def __init__(self) -> None:
            self.calls = 0

        def execute(self, arguments):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("Synthetic visual fixture failure")
            return original_clear.execute(arguments)

    vistora_main.SKILLS["VideoClearTimelineSkill"] = FailSecond()
    failed = service.run_confirmed_execution(
        failure_confirmation.confirmation_record_id
    )
    vistora_main.SKILLS["VideoClearTimelineSkill"] = original_clear
    failed_rollback = service.propose_rollback(failed.run_id)
    failed_rollback_confirmation = service.confirm_rollback(
        failed_rollback.review_id,
        confirmed_by="visual_fixture_user",
        decision="confirmed",
    )
    service.apply_rollback(failed_rollback_confirmation.confirmation_id)

    interrupted_request = request_for(
        "plan_visual_interrupted",
        "Demonstrate restart recovery without guessing success.",
        (
            DirectorOperation(
                operation_id="operation_visual_interrupted",
                tool_name="VideoClearTimelineSkill",
                arguments={},
                rationale="Create an interrupted pending run.",
                expected_effect="Would clear only after dispatch.",
            ),
        ),
    )
    interrupted_review = service.record_review(interrupted_request)
    interrupted_confirmation = service.confirm_review(
        interrupted_review.review_id,
        confirmed_by="visual_fixture_user",
        decision="confirmed",
    )
    original_append = service._append
    interrupted = False

    def interrupt(session, record):
        nonlocal interrupted
        original_append(session, record)
        if (
            isinstance(record, EditingExecutionRunRecord)
            and record.status == "running"
            and not interrupted
        ):
            interrupted = True
            raise KeyboardInterrupt()

    service._append = interrupt
    try:
        service.run_confirmed_execution(
            interrupted_confirmation.confirmation_record_id
        )
    except KeyboardInterrupt:
        pass
    finally:
        service._append = original_append
    service.recover_interrupted_runs(
        interrupted_confirmation.project_id
    )

    confirmed_request = request_for(
        "plan_visual_confirmed",
        "Demonstrate a confirmed plan awaiting execution.",
        (
            DirectorOperation(
                operation_id="operation_visual_rotate",
                tool_name="VideoModifyClipSkill",
                arguments={"target_index": 0, "rotate": 180},
                rationale="Prepare a visibly confirmed pending change.",
                expected_effect="Rotate the clip after execution.",
            ),
        ),
    )
    confirmed_review = service.record_review(confirmed_request)
    service.confirm_review(
        confirmed_review.review_id,
        confirmed_by="visual_fixture_user",
        decision="confirmed",
    )
    return service, confirmed_request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8879)
    args = parser.parse_args()
    workspace = ROOT / "tests/test_data/workflow_visual/.workspace"
    service, request = seed_fixture(workspace)
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        [ROOT],
        skill_registry=vistora_main.SKILLS,
        manual_edits_enabled=True,
        plan_review_request_provider=lambda: request,
        workflow_service=service,
    )
    server = create_preview_server(application, port=args.port)
    print(f"Workflow visual fixture: http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
