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
    EditingStep,
    PlanReference,
    TimelineProjectDocument,
    ToolError,
    UserConfirmationRecord,
)
from core.timeline import TimelineConfig  # noqa: E402


def _director_plan(**changes) -> DirectorPlan:
    values = {
        "plan_id": "plan_demo",
        "plan_version": 1,
        "created_at": datetime(2026, 7, 24, tzinfo=timezone.utc),
        "objective": "Create a concise product introduction.",
        "requirements": ("Keep the source audio muted.",),
        "creative_direction": {"tone": "clear", "pace": "fast"},
        "operations": (
            DirectorOperation(
                operation_id="operation_add_intro",
                tool_name="VideoAddClipSkill",
                arguments={
                    "source_path": "source.mp4",
                    "trim_in": 0.0,
                    "trim_out": 2.0,
                    "keep_audio": False,
                },
                rationale="Open with the clearest product shot.",
                expected_effect="A two-second silent opening clip.",
            ),
        ),
        "outputs": ("output/final.mp4",),
    }
    values.update(changes)
    return DirectorPlan(**values)


def _confirmation(
    plan: DirectorPlan,
    **changes,
) -> UserConfirmationRecord:
    values = {
        "confirmation_id": "confirmation_demo",
        "plan": plan,
        "confirmed_by": "user_demo",
        "recorded_at": datetime(2026, 7, 24, 1, tzinfo=timezone.utc),
    }
    values.update(changes)
    return UserConfirmationRecord.for_plan(**values)


def _execution(
    plan: DirectorPlan,
    confirmation: UserConfirmationRecord,
) -> EditingExecutionPlan:
    return EditingExecutionPlan.from_confirmed_plan(
        execution_id="execution_demo",
        project_id="project_demo",
        director_plan=plan,
        confirmation=confirmation,
    )


def test_contract_versions_are_explicit_and_unsupported_versions_fail() -> None:
    plan = _director_plan()
    assert plan.schema_name == "vistora.director-plan"
    assert plan.schema_version == "1.0.0"
    assert plan.digest() == DirectorPlan.model_validate_json(
        plan.model_dump_json()
    ).digest()
    assert plan.digest() != _director_plan(plan_version=2).digest()

    with pytest.raises(ValidationError):
        _director_plan(schema_version="2.0.0")


@pytest.mark.parametrize(
    ("contract_type", "schema_name"),
    [
        (DirectorPlan, "vistora.director-plan"),
        (UserConfirmationRecord, "vistora.user-confirmation"),
        (EditingExecutionPlan, "vistora.editing-execution-plan"),
        (TimelineProjectDocument, "vistora.timeline-project"),
        (AtomicToolRequestEnvelope, "vistora.atomic-tool-request"),
        (AtomicToolResultEnvelope, "vistora.atomic-tool-result"),
    ],
)
def test_contract_models_export_versioned_json_schema(
    contract_type: type,
    schema_name: str,
) -> None:
    schema = contract_type.model_json_schema()
    assert schema["properties"]["schema_name"]["const"] == schema_name
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"


@pytest.mark.parametrize(
    "plan_ref",
    [
        PlanReference(
            plan_id="plan_other",
            plan_version=1,
            plan_digest="sha256:" + ("0" * 64),
        ),
        PlanReference(
            plan_id="plan_demo",
            plan_version=2,
            plan_digest="sha256:" + ("0" * 64),
        ),
        PlanReference(
            plan_id="plan_demo",
            plan_version=1,
            plan_digest="sha256:" + ("0" * 64),
        ),
    ],
)
def test_mismatched_confirmation_cannot_create_execution_plan(
    plan_ref: PlanReference,
) -> None:
    plan = _director_plan()
    confirmation = UserConfirmationRecord(
        confirmation_id="confirmation_mismatch",
        plan_ref=plan_ref,
        decision="confirmed",
        confirmed_by="user_demo",
        recorded_at=datetime(2026, 7, 24, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(ValidationError, match="exact plan ID, version, and digest"):
        EditingExecutionPlan(
            execution_id="execution_demo",
            project_id="project_demo",
            director_plan=plan,
            confirmation=confirmation,
            steps=(
                EditingStep(
                    step_id="operation_add_intro",
                    source_operation_id="operation_add_intro",
                    tool_name="VideoAddClipSkill",
                    arguments=plan.operations[0].arguments,
                ),
            ),
        )


def test_unconfirmed_or_rejected_plan_cannot_be_executed() -> None:
    plan = _director_plan()
    step = EditingStep(
        step_id="operation_add_intro",
        source_operation_id="operation_add_intro",
        tool_name="VideoAddClipSkill",
        arguments=plan.operations[0].arguments,
    )

    with pytest.raises(ValidationError, match="requires a user confirmation"):
        EditingExecutionPlan(
            execution_id="execution_demo",
            project_id="project_demo",
            director_plan=plan,
            steps=(step,),
        )

    rejected = _confirmation(plan, decision="rejected")
    with pytest.raises(ValidationError, match="exact plan ID, version, and digest"):
        EditingExecutionPlan(
            execution_id="execution_demo",
            project_id="project_demo",
            director_plan=plan,
            confirmation=rejected,
            steps=(step,),
        )


def test_confirmation_record_is_frozen() -> None:
    confirmation = _confirmation(_director_plan())

    with pytest.raises(ValidationError, match="frozen"):
        confirmation.decision = "rejected"


def test_execution_steps_cannot_drift_from_confirmed_plan() -> None:
    plan = _director_plan()
    confirmation = _confirmation(plan)

    with pytest.raises(ValidationError, match="changes confirmed arguments"):
        EditingExecutionPlan(
            execution_id="execution_demo",
            project_id="project_demo",
            director_plan=plan,
            confirmation=confirmation,
            steps=(
                EditingStep(
                    step_id="operation_add_intro",
                    source_operation_id="operation_add_intro",
                    tool_name="VideoAddClipSkill",
                    arguments={"source_path": "different.mp4"},
                ),
            ),
        )


def test_legacy_timeline_json_migrates_deterministically() -> None:
    legacy = {
        "width": 640,
        "height": 360,
        "fps": 30,
        "tracks": {
            "video": {
                "id": "video",
                "clips": [],
            }
        },
    }

    project = TimelineProjectDocument.model_validate(legacy)
    repeated = TimelineProjectDocument.model_validate(legacy)
    existing_runtime_model = TimelineConfig.model_validate(legacy)

    assert project.schema_version == "1.0.0"
    assert project.migration_source == "legacy.timeline.v0"
    assert project.project_id == repeated.project_id
    assert project.project_id.startswith("project_legacy_")
    assert project.timeline == existing_runtime_model
    assert project.revision == 1


def test_contract_serialization_round_trips() -> None:
    plan = _director_plan()
    confirmation = _confirmation(plan)
    execution = _execution(plan, confirmation)
    project = TimelineProjectDocument(
        project_id="project_demo",
        timeline=TimelineConfig(width=640, height=360, fps=30),
    )
    request = AtomicToolRequestEnvelope.from_execution_plan(
        request_id="request_demo",
        execution_plan=execution,
        step_id="operation_add_intro",
    )
    started_at = datetime(2026, 7, 24, 2, tzinfo=timezone.utc)
    result = AtomicToolResultEnvelope(
        result_id="result_demo",
        request_id=request.request_id,
        execution_id=request.execution_id,
        step_id=request.step_id,
        tool_name=request.tool_name,
        status="success",
        payload={"status": "success", "clip_id": "clip_demo"},
        started_at=started_at,
        finished_at=started_at,
    )

    for contract in (plan, confirmation, execution, project, request, result):
        restored = type(contract).model_validate_json(contract.model_dump_json())
        assert restored == contract

        unsupported = contract.model_dump(mode="json")
        unsupported["schema_version"] = "2.0.0"
        with pytest.raises(ValidationError):
            type(contract).model_validate(unsupported)


def test_atomic_request_validates_existing_registry_and_skill_schema() -> None:
    import main

    plan = _director_plan()
    confirmation = _confirmation(plan)
    execution = _execution(plan, confirmation)
    request = AtomicToolRequestEnvelope.from_execution_plan(
        request_id="request_demo",
        execution_plan=execution,
        step_id="operation_add_intro",
    )

    validated = request.validate_against_registry(main.SKILLS)
    assert request.confirmation_id == confirmation.confirmation_id
    assert validated.source_path == "source.mp4"
    assert validated.keep_audio is False

    invalid_request = request.model_copy(
        update={
            "request_id": "request_invalid",
            "arguments": {"trim_in": 0.0},
        }
    )
    with pytest.raises(ValidationError):
        invalid_request.validate_against_registry(main.SKILLS)

    unknown_request = request.model_copy(
        update={
            "request_id": "request_unknown",
            "tool_name": "UnknownAtomicTool",
        }
    )
    with pytest.raises(ValueError, match="Unknown atomic tool"):
        unknown_request.validate_against_registry(main.SKILLS)


def test_tool_result_status_and_error_are_consistent() -> None:
    started_at = datetime(2026, 7, 24, 2, tzinfo=timezone.utc)
    error = ToolError(
        code="tool_failed",
        message="The tool could not complete.",
    )

    with pytest.raises(ValidationError, match="must include an error"):
        AtomicToolResultEnvelope(
            result_id="result_error",
            request_id="request_demo",
            execution_id="execution_demo",
            step_id="operation_add_intro",
            tool_name="VideoAddClipSkill",
            status="error",
            started_at=started_at,
            finished_at=started_at,
        )

    failed = AtomicToolResultEnvelope(
        result_id="result_error",
        request_id="request_demo",
        execution_id="execution_demo",
        step_id="operation_add_intro",
        tool_name="VideoAddClipSkill",
        status="error",
        error=error,
        started_at=started_at,
        finished_at=started_at,
    )
    assert failed.error == error
