import ast
import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import main as vistora_main  # noqa: E402
from contracts import (  # noqa: E402
    DirectorOperation,
    DirectorPlan,
    EditingStep,
    MediaTimeRangeLocator,
    PlanReference,
    SourceEvidenceReference,
    TimelineProjectDocument,
)
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from plan_review import (  # noqa: E402
    PlanDiffEngine,
    PlanDiffQuery,
    PlanDiffQueryError,
    PlanDiffRequest,
    PlanDiffValidationError,
    PlanReviewService,
    PreviewMaterialFact,
    ProposedEditingExecutionPlan,
    RegistrySchemaReference,
)
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402
from timeline_query import (  # noqa: E402
    TimelineSnapshotReference,
    TimelineSnapshotService,
)


CREATED_AT = datetime(2026, 7, 26, tzinfo=timezone.utc)
NEW_SOURCE = r"C:\private\media\new-source.mp4"


def _snapshot(*, revision: int = 4):
    timeline = TimelineConfig(
        width=640,
        height=360,
        fps=24,
        tracks={
            "video": TrackConfig(
                id="video",
                clips=[
                    ClipConfig(
                        id="clip_existing",
                        source=r"C:\private\media\existing.mp4",
                        trim_in=1.0,
                        trim_out=5.0,
                        timeline_start=0.0,
                        speed_factor=1.0,
                        keep_audio=False,
                    )
                ],
            ),
            "audio": TrackConfig(id="audio"),
        },
    )
    return TimelineSnapshotService.snapshot(
        TimelineProjectDocument(
            project_id="project_review",
            revision=revision,
            timeline=timeline,
        )
    )


def _evidence() -> SourceEvidenceReference:
    return SourceEvidenceReference(
        evidence_id="evidence_new_source",
        material_id=TimelineSnapshotService.source_id_for_configured_path(
            NEW_SOURCE
        ),
        locator=MediaTimeRangeLocator(
            start_seconds=0.5,
            end_seconds=3.5,
        ),
        analysis_fact_id="fact_new_source",
        analysis_fact_digest="sha256:" + ("a" * 64),
    )


def _request(
    snapshot=None,
    *,
    operations: tuple[DirectorOperation, ...] | None = None,
    registry=None,
) -> PlanDiffRequest:
    snapshot = snapshot or _snapshot()
    evidence = _evidence()
    operations = operations or (
        DirectorOperation(
            operation_id="operation_speed",
            tool_name="VideoModifyClipSkill",
            arguments={"target_index": 0, "speed_factor": 2.0},
            rationale="Tighten the opening.",
            expected_effect="Halve its effective duration.",
        ),
        DirectorOperation(
            operation_id="operation_add",
            tool_name="VideoAddClipSkill",
            arguments={
                "source_path": NEW_SOURCE,
                "trim_in": 0.5,
                "trim_out": 3.5,
                "speed_factor": 1.0,
                "keep_audio": True,
            },
            rationale="Continue with verified product footage.",
            expected_effect="Append a three-second clip.",
            evidence_ids=(evidence.evidence_id,),
        ),
        DirectorOperation(
            operation_id="operation_export",
            tool_name="VideoExportSkill",
            arguments={
                "output_path": r"C:\private\exports\final.mp4",
                "clear_timeline_after": True,
            },
            rationale=(
                r"Deliver the reviewed sequence to "
                r"C:\private\exports\final.mp4."
            ),
            expected_effect=(
                r"Export /private/exports/final.mp4 and clear after success."
            ),
        ),
    )
    plan = DirectorPlan(
        plan_id="plan_review",
        plan_version=2,
        created_at=CREATED_AT,
        objective="Review a concise cut before confirmation.",
        source_evidence=(evidence,),
        operations=operations,
    )
    proposed = ProposedEditingExecutionPlan.from_director_plan(
        proposal_execution_id="proposal_execution_review",
        project_id=snapshot.project_id,
        director_plan=plan,
    )
    registry = registry or vistora_main.SKILLS
    return PlanDiffRequest(
        request_id="review_request",
        snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
        director_plan=plan,
        proposed_execution=proposed,
        registry_ref=RegistrySchemaReference.from_registry(registry),
        material_facts=(
            PreviewMaterialFact(
                material_id=evidence.material_id,
                media_kind="video",
                duration_seconds=6.0,
                width=1280,
                height=720,
            ),
        ),
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@contextmanager
def _server(application: PreviewApplication):
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


def _multitrack_snapshot(*, locked_audio: bool = False):
    return TimelineSnapshotService.snapshot(
        TimelineProjectDocument(
            project_id="project_multitrack_review",
            revision=7,
            timeline=TimelineConfig(
                width=320,
                height=180,
                fps=24,
                tracks={
                    "v-main": TrackConfig(
                        id="track_video_main",
                        kind="video",
                        role="primary",
                        order=0,
                        clips=[
                            ClipConfig(
                                id="clip_video_linked",
                                source="material://source_1111111111111111",
                                trim_in=0,
                                trim_out=4,
                                timeline_start=0,
                                link_group_id="link_scene_one",
                            )
                        ],
                    ),
                    "v-overlay": TrackConfig(
                        id="track_video_overlay",
                        kind="video",
                        role="overlay",
                        order=1,
                    ),
                    "a-dialogue": TrackConfig(
                        id="track_audio_dialogue",
                        kind="audio",
                        role="dialogue",
                        order=2,
                        locked=locked_audio,
                        clips=[
                            ClipConfig(
                                id="clip_audio_linked",
                                source="material://source_2222222222222222",
                                trim_in=0,
                                trim_out=4,
                                timeline_start=0,
                                link_group_id="link_scene_one",
                            )
                        ],
                    ),
                },
            ),
        )
    )


def test_plan_review_contracts_round_trip_and_digests_are_stable() -> None:
    snapshot = _snapshot()
    request = _request(snapshot)
    round_tripped = PlanDiffRequest.model_validate_json(
        request.model_dump_json()
    )

    assert round_tripped == request
    assert round_tripped.digest() == request.digest()


def test_multitrack_linked_split_preview_is_detached_and_consequential() -> None:
    snapshot = _multitrack_snapshot()
    before = snapshot.model_dump_json()
    request = _request(
        snapshot,
        operations=(
            DirectorOperation(
                operation_id="operation_linked_split",
                tool_name="VideoSplitClipSkill",
                arguments={
                    "track_id": "track_video_main",
                    "clip_id": "clip_video_linked",
                    "split_at_seconds": 2,
                    "right_clip_id": "clip_video_right",
                    "edit_scope": "linked_group",
                },
                rationale="Split the explicitly linked scene together.",
                expected_effect="Create aligned linked video/audio halves.",
            ),
        ),
    )
    document = PlanDiffEngine.generate(
        request,
        snapshot,
        vistora_main.SKILLS,
    )
    assert snapshot.model_dump_json() == before
    changed = {
        (change.entity.entity_id, change.effect_kind)
        for change in document.changes
        if change.entity.entity_kind == "clip"
    }
    assert ("clip_video_linked", "direct") in changed
    assert ("clip_video_right", "direct") in changed
    assert ("clip_audio_linked", "consequential") in changed
    assert any(
        change.after
        and change.after.link_group_id
        and change.after.link_group_id != "link_scene_one"
        for change in document.changes
        if change.category == "clip_addition"
    )


def test_multitrack_preview_rejects_locked_link_member() -> None:
    snapshot = _multitrack_snapshot(locked_audio=True)
    request = _request(
        snapshot,
        operations=(
            DirectorOperation(
                operation_id="operation_locked_split",
                tool_name="VideoSplitClipSkill",
                arguments={
                    "track_id": "track_video_main",
                    "clip_id": "clip_video_linked",
                    "split_at_seconds": 2,
                    "edit_scope": "linked_group",
                },
                rationale="Attempt a linked split.",
                expected_effect="Must fail because one member is locked.",
            ),
        ),
    )
    with pytest.raises(PlanDiffValidationError, match="locked"):
        PlanDiffEngine.generate(request, snapshot, vistora_main.SKILLS)
    assert request.proposed_execution.director_plan == request.director_plan
    assert request.registry_ref.schema_version == "1.0.0"
    assert request.snapshot_ref.snapshot_id == snapshot.snapshot_id

    with pytest.raises(ValidationError):
        PlanDiffRequest.model_validate(
            {**request.model_dump(mode="json"), "schema_version": "2.0.0"}
        )


def test_diff_is_deterministic_path_redacted_and_never_mutates_snapshot() -> None:
    snapshot = _snapshot()
    before = snapshot.model_dump_json()
    request = _request(snapshot)

    first = PlanDiffEngine.generate(request, snapshot, vistora_main.SKILLS)
    second = PlanDiffEngine.generate(request, snapshot, vistora_main.SKILLS)

    assert first == second
    assert first.digest() == second.digest()
    assert snapshot.model_dump_json() == before
    serialized = first.model_dump_json()
    assert r"C:\private" not in serialized
    assert "final.mp4" not in serialized
    assert first.review_status == "warning"
    assert first.summary.before_clip_count == 1
    assert first.summary.after_clip_count == 0
    assert first.summary.additions == 1
    assert first.summary.removals == 2
    assert first.summary.modifications == 2
    assert first.summary.consequential == 3
    assert first.summary.warnings == 3

    categories = [change.category for change in first.changes]
    assert categories == [
        "clip_speed",
        "clip_addition",
        "export_only",
        "clip_removal",
        "clip_removal",
        "project_settings",
    ]
    assert first.summary.before_project.width == 640
    assert first.summary.after_project.width == 1920
    assert first.changes[-1].before_project.width == 640
    assert first.changes[-1].after_project.fps == 30
    addition = first.changes[1]
    assert addition.after.provisional is True
    assert addition.evidence[0].evidence_id == "evidence_new_source"
    assert addition.evidence[0].start_seconds == 0.5
    speed = first.changes[0]
    assert speed.current_provenance.origin_kind == "legacy_unknown"
    assert speed.current_provenance.mapping_status == "legacy_unknown"


def test_stale_snapshot_and_registry_schema_drift_require_regeneration() -> None:
    snapshot = _snapshot()
    request = _request(snapshot)
    stale_snapshot = _snapshot(revision=5)
    stale = PlanReviewService.review(
        request,
        stale_snapshot,
        vistora_main.SKILLS,
    )
    assert stale.review_state == "stale"
    assert stale.diff is None

    class DriftedInput(BaseModel):
        value: int

    class DriftedSkill:
        name = "VideoModifyClipSkill"
        input_model = DriftedInput

    drifted_registry = dict(vistora_main.SKILLS)
    drifted_registry["VideoModifyClipSkill"] = DriftedSkill()
    invalid = PlanReviewService.review(
        request,
        snapshot,
        drifted_registry,
    )
    assert invalid.review_state == "invalid"
    assert "schema drifted" in invalid.message


def test_invalid_arguments_and_unregistered_tools_are_rejected() -> None:
    snapshot = _snapshot()
    invalid_operation = DirectorOperation(
        operation_id="operation_bad",
        tool_name="VideoModifyClipSkill",
        arguments={"target_index": "not-an-index"},
        rationale="Invalid fixture.",
        expected_effect="Must be rejected.",
    )
    request = _request(snapshot, operations=(invalid_operation,))
    with pytest.raises(
        PlanDiffValidationError,
        match="invalid arguments",
    ):
        PlanDiffEngine.generate(request, snapshot, vistora_main.SKILLS)

    unknown_operation = DirectorOperation(
        operation_id="operation_unknown",
        tool_name="UnregisteredTimelineTool",
        arguments={},
        rationale="Unknown fixture.",
        expected_effect="Must be rejected.",
    )
    unknown_request = _request(snapshot, operations=(unknown_operation,))
    with pytest.raises(
        PlanDiffValidationError,
        match="unregistered tool",
    ):
        PlanDiffEngine.generate(
            unknown_request,
            snapshot,
            vistora_main.SKILLS,
        )


def test_registered_reorder_without_semantic_adapter_is_blocked_not_faked() -> None:
    class ReorderInput(BaseModel):
        clip_id: str
        order_index: int

    class ReorderSkill:
        name = "FutureReorderSkill"
        input_model = ReorderInput

    registry = {**vistora_main.SKILLS, "FutureReorderSkill": ReorderSkill()}
    operation = DirectorOperation(
        operation_id="operation_reorder",
        tool_name="FutureReorderSkill",
        arguments={"clip_id": "clip_existing", "order_index": 0},
        rationale="Exercise an unavailable semantic adapter.",
        expected_effect="No reorder may be fabricated.",
    )
    request = _request(operations=(operation,), registry=registry)
    diff = PlanDiffEngine.generate(request, _snapshot(), registry)

    assert diff.review_status == "blocked"
    assert diff.summary.before_clip_count == diff.summary.after_clip_count == 1
    assert diff.changes[0].category == "warning"
    assert diff.changes[0].severity == "blocker"
    assert all(change.category != "clip_reorder" for change in diff.changes)


def test_duplicate_or_drifted_proposed_steps_are_rejected() -> None:
    request = _request()
    original = request.proposed_execution.steps[0]
    with pytest.raises(ValidationError, match="step IDs must be unique"):
        ProposedEditingExecutionPlan(
            proposal_execution_id="proposal_duplicate",
            project_id=request.snapshot_ref.project_id,
            director_plan=request.director_plan,
            steps=(
                original,
                original,
                *request.proposed_execution.steps[2:],
            ),
        )

    drifted = EditingStep(
        **{
            **original.model_dump(mode="python"),
            "arguments": {"target_index": 0, "speed_factor": 3.0},
        }
    )
    with pytest.raises(ValidationError, match="drifts from Director intent"):
        ProposedEditingExecutionPlan(
            proposal_execution_id="proposal_drifted",
            project_id=request.snapshot_ref.project_id,
            director_plan=request.director_plan,
            steps=(drifted, *request.proposed_execution.steps[1:]),
        )


def test_revision_aware_queries_are_stable_for_plan_clip_and_evidence() -> None:
    snapshot = _snapshot()
    request = _request(snapshot)
    diff = PlanDiffEngine.generate(request, snapshot, vistora_main.SKILLS)
    query = PlanDiffQuery(
        diff,
        current_snapshot_ref=request.snapshot_ref,
    )

    assert query.for_plan(PlanReference.from_plan(request.director_plan)) == (
        diff.changes
    )
    assert query.for_clip(
        track_key="video",
        clip_id="clip_existing",
    ) == (diff.changes[0], diff.changes[3])
    assert query.for_evidence("evidence_new_source") == (diff.changes[1],)
    assert query.warning_summary() == query.warning_summary()

    with pytest.raises(PlanDiffQueryError, match="stale"):
        PlanDiffQuery(
            diff,
            current_snapshot_ref=TimelineSnapshotReference.from_snapshot(
                _snapshot(revision=5)
            ),
        )


def test_plan_review_endpoint_is_read_only_and_redacts_fixture_paths() -> None:
    snapshot = _snapshot()
    request = _request(snapshot)
    application = PreviewApplication(
        lambda: snapshot,
        skill_registry=vistora_main.SKILLS,
        plan_review_request_provider=lambda: request,
    )
    with _server(application) as base_url:
        with urllib.request.urlopen(
            f"{base_url}/api/plan-review",
            timeout=3,
        ) as response:
            body = response.read()
            payload = json.loads(body)
        request_object = urllib.request.Request(
            f"{base_url}/api/plan-review",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request_object, timeout=3)

    assert payload["review_state"] == "current"
    assert payload["diff"]["review_status"] == "warning"
    assert b"C:\\\\private" not in body
    assert b"output_path" not in body
    assert b"source_path" not in body
    assert payload["diff"]["changes"][1]["after"]["source_name"] == (
        "new-source.mp4"
    )
    assert error.value.code == 405


def test_plan_review_engine_has_no_mutation_or_media_execution_imports() -> None:
    forbidden_imports = {
        "core.timeline",
        "core.timeline_manager",
        "skills",
        "moviepy",
        "subprocess",
        "traceability.recording",
        "traceability.store",
        "utils.proxy",
    }
    violations = {}
    for path in sorted((SRC / "plan_review").glob("*.py")):
        forbidden = sorted(_imports(path) & forbidden_imports)
        if forbidden:
            violations[path.name] = forbidden
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert not (
            called
            & {
                "execute",
                "run",
                "render",
                "save_current_timeline",
                "reset_timeline",
                "record",
            }
        ), path.name
    assert not violations
