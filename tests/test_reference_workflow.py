from tests.reference_workflow import (
    REFERENCE_PLAN_DIGEST,
    REFERENCE_TOOL_ORDER,
    run_reference_workflow,
)
from contracts import PlanReference


def test_reference_main_workflow_is_traceable_and_repeatable() -> None:
    first = run_reference_workflow()
    second = run_reference_workflow()

    assert first.facts == second.facts
    assert first.plan == second.plan
    assert first.pre_confirmation_diff == second.pre_confirmation_diff
    assert (
        first.pre_confirmation_diff.digest()
        == second.pre_confirmation_diff.digest()
    )
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
    assert first.pre_confirmation_diff.plan_ref == PlanReference.from_plan(
        first.plan
    )
    assert first.pre_confirmation_diff.review_status == "warning"
    assert first.pre_confirmation_diff.summary.additions == 1
    assert first.pre_confirmation_diff.summary.removals == 1
    assert "confirmation" not in (
        first.pre_confirmation_diff.model_dump_json()
    )
    assert first.execution.confirmation == first.confirmation
    assert tuple(step.tool_name for step in first.execution.steps) == (
        REFERENCE_TOOL_ORDER
    )

    plan_ref = first.confirmation.plan_ref
    assert len({request.request_id for request in first.requests}) == 3
    assert all(
        request.request_id.startswith("atomic_request_reference_")
        for request in first.requests
    )
    assert len({result.result_id for result in first.results}) == 3
    assert all(
        result.result_id.startswith("atomic_result_reference_")
        for result in first.results
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
    assert first.trace_document == second.trace_document
    assert first.workflow_ledger == second.workflow_ledger
    assert first.workflow_ledger.revision > 0
    assert first.rollback_proposal == second.rollback_proposal
    assert first.rollback_run.status == "succeeded"
    assert first.timeline_restored is True
    assert first.trace_document.revision == 4
    assert tuple(
        trace.trace_sequence
        for trace in first.trace_document.confirmed_traces
    ) == (1, 2, 3)
    add_relation = first.trace_document.confirmed_traces[1].relations[0]
    assert add_relation.origin_kind == "director_plan"
    assert add_relation.entity.entity_id == "clip_12345678"
    assert add_relation.evidence_ids == (
        "evidence_reference_source_trim",
    )
    export_relations = first.trace_document.confirmed_traces[2].relations
    generated = [
        relation
        for relation in export_relations
        if relation.entity.entity_kind == "media_output"
    ]
    assert len(generated) == 1
    assert generated[0].origin_kind == "generated_media"
    assert first.traced_clips[0]["present"] is False
    assert first.traced_clips[0]["provenance"]["mapping_status"] == "deleted"
