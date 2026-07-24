from tests.reference_workflow import (
    REFERENCE_PLAN_DIGEST,
    REFERENCE_TOOL_ORDER,
    run_reference_workflow,
)


def test_reference_main_workflow_is_traceable_and_repeatable() -> None:
    first = run_reference_workflow()
    second = run_reference_workflow()

    assert first.facts == second.facts
    assert first.plan == second.plan
    assert first.plan.digest() == second.plan.digest() == REFERENCE_PLAN_DIGEST
    assert first.confirmation == second.confirmation
    assert first.execution == second.execution
    assert first.requests == second.requests
    assert first.results == second.results
    for field in (
        "video_codec",
        "width",
        "height",
        "frame_rate",
        "audio_stream_count",
        "duration_seconds",
    ):
        assert first.output_metadata[field] == second.output_metadata[field]

    assert first.confirmation.confirms(first.plan)
    assert first.execution.confirmation == first.confirmation
    assert tuple(step.tool_name for step in first.execution.steps) == (
        REFERENCE_TOOL_ORDER
    )

    plan_ref = first.confirmation.plan_ref
    assert tuple(request.request_id for request in first.requests) == (
        "request_reference_01",
        "request_reference_02",
        "request_reference_03",
    )
    assert tuple(result.result_id for result in first.results) == (
        "result_reference_01",
        "result_reference_02",
        "result_reference_03",
    )
    for request, result in zip(first.requests, first.results, strict=True):
        assert request.execution_id == first.execution.execution_id
        assert request.project_id == first.execution.project_id
        assert request.confirmation_id == first.confirmation.confirmation_id
        assert request.plan_ref == plan_ref
        assert result.request_id == request.request_id
        assert result.execution_id == request.execution_id
        assert result.step_id == request.step_id
        assert result.tool_name == request.tool_name
        assert result.status == "success"
        assert result.error is None

    assert first.results[1].payload["clip_id"] == "clip_12345678"
    assert first.results[2].payload["output_path"] == (
        "tests/test_data/reference_workflow/output.mp4"
    )
    assert first.output_metadata["video_codec"] == "h264"
    assert first.output_metadata["width"] == 320
    assert first.output_metadata["height"] == 180
    assert first.output_metadata["frame_rate"] == "24/1"
    assert first.output_metadata["audio_stream_count"] == 0
    assert abs(first.output_metadata["duration_seconds"] - 1.5) <= 0.08
    assert first.timeline_state_removed is True
