from tests.reference_workflow import (
    REFERENCE_PLAN_DIGEST,
    REFERENCE_TOOL_ORDER,
    run_reference_workflow,
)
from tests.multitrack_reference_workflow import (
    run_multitrack_reference_workflow,
)
from contracts import PlanReference


def test_reference_main_workflow_is_traceable_and_repeatable() -> None:
    first = run_reference_workflow()
    second = run_reference_workflow()

    assert first.facts == second.facts
    assert first.director_report == second.director_report
    assert first.director_ledger == second.director_ledger
    assert first.director_report.status == "proposal_ready"
    assert first.director_report.proposal.plan == first.plan
    assert first.director_report.proposal.review_request.director_plan == (
        first.plan
    )
    assert first.plan == second.plan
    assert first.pre_confirmation_diff == second.pre_confirmation_diff
    assert (
        first.pre_confirmation_diff.digest()
        == second.pre_confirmation_diff.digest()
    )
    assert first.plan.digest() == second.plan.digest() == REFERENCE_PLAN_DIGEST
    assert first.confirmation == second.confirmation
    assert first.execution == second.execution
    assert first.editing_agent_report == second.editing_agent_report
    assert first.editing_agent_report.status == "succeeded"
    assert first.editing_agent_report.disposition == "executed"
    assert tuple(
        step.tool_name for step in first.editing_agent_report.steps
    ) == REFERENCE_TOOL_ORDER
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
    assert first.director_report.proposal.review.diff == (
        first.pre_confirmation_diff
    )
    assert first.director_ledger.revision == 1
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
    assert len({request.request_id for request in first.requests}) == 4
    assert all(
        request.request_id.startswith("atomic_request_reference_")
        for request in first.requests
    )
    assert len({result.result_id for result in first.results}) == 4
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
        assert result.registry_digest == (
            first.pre_confirmation_diff.registry_ref.registry_digest
        )

    assert first.results[1].payload["created_clip_ids"] == [
        "clip_reference_main"
    ]
    assert first.results[2].payload["modified_clip_ids"] == [
        "clip_reference_main"
    ]
    assert first.results[3].payload["output_path"] == (
        "tests/test_data/reference_workflow/output.mp4"
    )
    assert first.output_metadata["video_codec"] == "h264"
    assert first.output_metadata["width"] == 320
    assert first.output_metadata["height"] == 180
    assert first.output_metadata["frame_rate"] == "24/1"
    assert first.output_metadata["audio_stream_count"] == 0
    assert abs(first.output_metadata["duration_seconds"] - 1.25) <= 0.08
    assert first.timeline_state_removed is True
    assert first.trace_document == second.trace_document
    assert first.workflow_ledger == second.workflow_ledger
    assert first.workflow_ledger.revision > 0
    assert first.rollback_proposal == second.rollback_proposal
    assert first.rollback_run.status == "succeeded"
    assert first.timeline_restored is True
    assert first.no_material_chain == second.no_material_chain
    assert first.no_material_chain["director_status"] == (
        "material_requirements_ready"
    )
    assert first.no_material_chain["creation_planning_status"] == (
        "proposal_ready"
    )
    assert first.no_material_chain["production_method"] == "generate"
    assert first.no_material_chain["media_created"] is True
    assert first.no_material_chain["artifact_accepted"] is True
    assert first.no_material_chain["catalog_revision"] == 1
    assert first.no_material_chain["catalog_material_id"].startswith("source_")
    assert first.trace_document.revision == 5
    assert tuple(
        trace.trace_sequence
        for trace in first.trace_document.confirmed_traces
    ) == (1, 2, 3, 4)
    insert_relation = first.trace_document.confirmed_traces[1].relations[0]
    assert insert_relation.origin_kind == "director_plan"
    assert insert_relation.entity.entity_id == "clip_reference_main"
    assert insert_relation.evidence_ids == (
        "evidence_catalog_"
        + first.no_material_chain["catalog_material_id"][7:],
    )
    trim_relation = first.trace_document.confirmed_traces[2].relations[0]
    assert trim_relation.relation_type == "modifies"
    assert trim_relation.entity.entity_id == "clip_reference_main"
    assert trim_relation.evidence_ids == insert_relation.evidence_ids
    export_relations = first.trace_document.confirmed_traces[3].relations
    generated = [
        relation
        for relation in export_relations
        if relation.entity.entity_kind == "media_output"
    ]
    assert len(generated) == 1
    assert generated[0].origin_kind == "generated_media"
    assert first.traced_clips[0]["present"] is False
    assert first.traced_clips[0]["provenance"]["mapping_status"] == "deleted"


def test_multitrack_reference_is_confirmed_rendered_and_repeatable() -> None:
    first = run_multitrack_reference_workflow()
    second = run_multitrack_reference_workflow()
    assert first == second
    assert first["execution_status"] == "succeeded"
    assert first["step_count"] == 9
    assert first["trace_count"] == 9
    assert first["current_track_count"] == 4
    assert first["current_video_clip_count"] >= 2
    assert first["current_audio_clip_count"] >= 2
    assert first["rollback_status"] == "succeeded"
    assert first["loudness_analysis_id"].startswith("loud_")
    streams = first["output"]["streams"]
    assert any(stream["codec_type"] == "video" for stream in streams)
    assert any(stream["codec_type"] == "audio" for stream in streams)
    assert first["output"]["format"]["duration"]
