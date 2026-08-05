import ast
import json
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import main as vistora_main  # noqa: E402
from agent import DirectorAgent, EditingAgent  # noqa: E402
from contracts import (  # noqa: E402
    DirectorOperation,
    SourceEvidenceReference,
    WholeMaterialLocator,
)
from core import timeline_manager  # noqa: E402
from core.timeline import ClipConfig, TimelineConfig, TrackConfig  # noqa: E402
from director import (  # noqa: E402
    CreativeBriefInput,
    DirectorContextService,
    DirectorMaterialFact,
    DirectorPlanDraft,
    DirectorReasoningOutput,
    DirectorStore,
)
from product_entry import (  # noqa: E402
    ProductEntryCommand,
    ProductEntryConcurrencyError,
    ProductEntryError,
    ProductEntryStore,
    ProductionEntryService,
)
from timeline_preview import PreviewApplication, create_preview_server  # noqa: E402
from timeline_query import TimelineSnapshotService  # noqa: E402
from traceability.store import TraceabilityStore  # noqa: E402
from workflow import WorkflowApplicationService, WorkflowStore  # noqa: E402


START = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)


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


class FakeDirectorAdapter:
    def __init__(self, modes=("clarify", "propose")):
        self.modes = list(modes)

    def complete(self, request):
        mode = self.modes.pop(0)
        material = next(
            item
            for item in request.context.materials
            if item.observation_status == "observed" and item.evidence
        )
        if mode == "clarify":
            brief = CreativeBriefInput(
                objective="Create a concise existing-material cut.",
                material_ids=(material.material_id,),
                evidence_ids=(material.evidence[0].evidence_id,),
                unresolved_questions=("Who is the audience?",),
            )
            return DirectorReasoningOutput(
                response_kind="clarify",
                assistant_message="I need the intended audience.",
                context_snapshot_ref=request.context.snapshot_ref,
                registry_ref=request.context.registry_ref,
                brief=brief,
                clarification_questions=("Who is the audience?",),
            ).model_dump(mode="json")
        brief = CreativeBriefInput(
            objective="Create a concise existing-material cut.",
            audience="Existing users.",
            platform="Product landing page.",
            target_duration_seconds=2.0,
            style="Clean and restrained.",
            narrative="Conclude the existing timeline cleanly.",
            pacing="Steady.",
            must_haves=("Use observed material only.",),
            must_not_haves=("Do not invent claims.",),
            delivery_requirements=("Reviewed timeline change.",),
            material_ids=(material.material_id,),
            evidence_ids=(material.evidence[0].evidence_id,),
            acceptance_criteria=("The confirmed timeline becomes empty.",),
        )
        plan = DirectorPlanDraft(
            objective=brief.objective,
            requirements=("Clear only after explicit confirmation.",),
            creative_direction={"style": brief.style},
            operations=(
                DirectorOperation(
                    operation_id="operation_product_clear",
                    tool_name="VideoClearTimelineSkill",
                    arguments={},
                    rationale="Apply the user's requested clean conclusion.",
                    expected_effect="Clear the current timeline.",
                    evidence_ids=brief.evidence_ids,
                ),
            ),
            outputs=("A confirmed empty timeline.",),
            risks=("The current clip is removed.",),
        )
        return DirectorReasoningOutput(
            response_kind="propose",
            assistant_message="The proposal is ready for separate review.",
            context_snapshot_ref=request.context.snapshot_ref,
            registry_ref=request.context.registry_ref,
            brief=brief,
            plan_draft=plan,
        ).model_dump(mode="json")


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
                        id="clip_product",
                        source="synthetic/product.mp4",
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


@pytest.fixture
def product(tmp_path, monkeypatch):
    project_file = tmp_path / ".workspace" / "current_timeline.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text(_timeline().model_dump_json(indent=2))
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    monkeypatch.setattr(
        timeline_manager,
        "WORKSPACE_DIR",
        str(project_file.parent),
    )
    TraceabilityStore.trace_path(project_file).unlink(missing_ok=True)
    deterministic = Deterministic()
    director_store = DirectorStore(
        project_file.with_name("product.director.json")
    )

    def context():
        snapshot = TimelineSnapshotService.snapshot_current()
        clip = snapshot.tracks[0].clips[0]
        evidence = SourceEvidenceReference(
            evidence_id="evidence_product",
            material_id=clip.source.source_id,
            locator=WholeMaterialLocator(),
            description="Observed in the current timeline snapshot.",
        )
        materials = (
            DirectorMaterialFact(
                material_id=clip.source.source_id,
                media_kind="video",
                display_name="product.mp4",
                duration_seconds=2.0,
                width=320,
                height=180,
                has_audio=False,
                evidence=(evidence,),
            ),
        )
        return (
            DirectorContextService.build(
                snapshot,
                vistora_main.SKILLS,
                materials=materials,
            ),
            snapshot,
        )

    director = DirectorAgent(
        adapter=FakeDirectorAdapter(),
        context_provider=context,
        registry=vistora_main.SKILLS,
        store=director_store,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    workflow = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file),
        registry=vistora_main.SKILLS,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    service = ProductionEntryService(
        director=director,
        director_store=director_store,
        workflow=workflow,
        editing_agent=EditingAgent(
            workflow,
            clock=deterministic.clock,
            id_factory=deterministic.identifier,
        ),
        store=ProductEntryStore(
            project_file.with_name("product.product.json")
        ),
        session_id="session_product",
        project_id=TimelineSnapshotService.snapshot_current().project_id,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return service, project_file


def _command(service, revision, action, request_id, target=None, message=None):
    return ProductEntryCommand(
        request_id=request_id,
        session_id=service.session_id,
        project_id=service.project_id,
        expected_revision=revision,
        action=action,
        actor_id="local_user",
        target_id=target,
        user_message=message,
    )


def test_full_product_flow_requires_separate_confirmation_and_editing(product):
    service, project_file = product
    first = service.command(
        _command(
            service,
            0,
            "director_turn",
            "request_product_01",
            message="Make a concise cut.",
        )
    )
    assert first.view.state == "needs_clarification"
    second = service.command(
        _command(
            service,
            1,
            "director_turn",
            "request_product_02",
            message="Existing users, clean and steady, two seconds.",
        )
    )
    assert second.view.state == "proposal_ready"
    assert TimelineConfig.model_validate_json(
        project_file.read_text()
    ).tracks["video"].clips

    proposal = second.view.director["proposals"][-1]
    reviewed = service.command(
        _command(
            service,
            2,
            "persist_review",
            "request_product_03",
            target=proposal["proposal_id"],
        )
    )
    assert reviewed.view.state == "reviewed"
    assert TimelineConfig.model_validate_json(
        project_file.read_text()
    ).tracks["video"].clips
    review_id = reviewed.view.workflow["reviews"][-1]["review_id"]
    confirmed = service.command(
        _command(
            service,
            3,
            "confirm",
            "request_product_04",
            target=review_id,
        )
    )
    assert confirmed.view.state == "confirmed"
    assert TimelineConfig.model_validate_json(
        project_file.read_text()
    ).tracks["video"].clips
    confirmation_id = confirmed.view.workflow["confirmations"][-1][
        "confirmation_record_id"
    ]
    executed = service.command(
        _command(
            service,
            4,
            "execute",
            "request_product_05",
            target=confirmation_id,
        )
    )
    assert executed.view.state == "succeeded"
    assert not project_file.exists()
    assert not timeline_manager.TimelineManager.get_current_timeline().tracks[
        "video"
    ].clips
    assert executed.view.workflow["executions"][-1]["status"] == "succeeded"
    run_id = executed.view.workflow["executions"][-1]["run_id"]
    rollback_reviewed = service.command(
        _command(
            service,
            5,
            "rollback_review",
            "request_product_06",
            target=run_id,
        )
    )
    rollback_review_id = rollback_reviewed.view.workflow[
        "rollback_reviews"
    ][-1]["review_id"]
    rollback_confirmed = service.command(
        _command(
            service,
            6,
            "rollback_confirm",
            "request_product_07",
            target=rollback_review_id,
        )
    )
    rollback_confirmation_id = rollback_confirmed.view.workflow[
        "rollback_confirmations"
    ][-1]["confirmation_id"]
    rolled_back = service.command(
        _command(
            service,
            7,
            "rollback_apply",
            "request_product_08",
            target=rollback_confirmation_id,
        )
    )
    assert rolled_back.view.state == "rolled_back"
    assert timeline_manager.TimelineManager.get_current_timeline().tracks[
        "video"
    ].clips


def test_product_entry_exposes_audited_incomplete_material_state(product):
    service, project_file = product
    original_provider = service.director._context_provider

    def mixed_context():
        context, snapshot = original_provider()
        missing = DirectorMaterialFact(
            material_id="source_2222222222222222",
            media_kind="audio",
            display_name="missing-dialogue.wav",
            observation_status="missing",
        )
        return (
            DirectorContextService.build(
                snapshot,
                vistora_main.SKILLS,
                materials=(*context.materials, missing),
            ),
            snapshot,
        )

    service.director._context_provider = mixed_context
    service.director._adapter = FakeDirectorAdapter(("propose",))
    response = service.command(_command(
        service,
        0,
        "director_turn",
        "request_product_incomplete_materials",
        message="Use the picture and the missing dialogue source.",
    ))
    assert response.view.state == "materials_incomplete"
    assert response.view.allowed_actions == ("director_turn",)
    assessment = response.view.director["latest_brief"]["material_state"]
    assert assessment["state"] == "materials_incomplete"
    assert assessment["unavailable_material_ids"] == [
        "source_2222222222222222"
    ]
    assert project_file.exists()


def test_idempotency_stale_guard_and_restart_view(product):
    service, _ = product
    command = _command(
        service,
        0,
        "director_turn",
        "request_replay",
        message="Start a grounded edit.",
    )
    first = service.command(command)
    replay = service.command(command)
    assert replay.replayed is True
    assert replay.view.revision == first.view.revision == 1
    with pytest.raises(ProductEntryError):
        service.command(command.model_copy(update={"user_message": "Changed"}))
    with pytest.raises(ProductEntryConcurrencyError):
        service.command(
            _command(
                service,
                0,
                "director_turn",
                "request_stale",
                message="This revision is stale.",
            )
        )
    restarted = ProductionEntryService(
        director=service.director,
        director_store=service.director_store,
        workflow=service.workflow,
        editing_agent=service.editing_agent,
        store=service.store,
        session_id=service.session_id,
        project_id=service.project_id,
    )
    assert restarted.view().revision == 1
    assert restarted.view().state == "needs_clarification"


def test_rejection_never_executes(product):
    service, project_file = product
    service.director._adapter.modes = ["propose"]
    proposed = service.command(
        _command(
            service,
            0,
            "director_turn",
            "request_reject_01",
            message="All requirements are clear.",
        )
    )
    proposal_id = proposed.view.director["proposals"][-1]["proposal_id"]
    reviewed = service.command(
        _command(
            service,
            1,
            "persist_review",
            "request_reject_02",
            target=proposal_id,
        )
    )
    review_id = reviewed.view.workflow["reviews"][-1]["review_id"]
    rejected = service.command(
        _command(
            service,
            2,
            "reject",
            "request_reject_03",
            target=review_id,
        )
    )
    assert rejected.view.state == "rejected"
    assert "execute" not in rejected.view.allowed_actions
    assert TimelineConfig.model_validate_json(
        project_file.read_text()
    ).tracks["video"].clips


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


def _http(url, method="GET", payload=None, token=None, origin=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Vistora-CSRF"] = token
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_product_http_csrf_origin_and_no_write_before_director(product):
    service, project_file = product
    application = PreviewApplication(
        TimelineSnapshotService.snapshot_current,
        skill_registry=vistora_main.SKILLS,
        product_entry_service=service,
        product_csrf_token="csrf_product_test_token",
    )
    with _server(application) as base:
        status, payload = _http(f"{base}/api/product")
        assert status == 200
        assert payload["view"]["state"] == "dialogue"
        command = _command(
            service,
            0,
            "director_turn",
            "request_http",
            message="Start a grounded edit.",
        ).model_dump(mode="json")
        assert _http(
            f"{base}/api/product/actions",
            "POST",
            command,
        )[0] == 403
        assert _http(
            f"{base}/api/product/actions",
            "POST",
            command,
            token="csrf_product_test_token",
            origin="https://evil.example",
        )[0] == 403
        ok, result = _http(
            f"{base}/api/product/actions",
            "POST",
            command,
            token="csrf_product_test_token",
            origin=base,
        )
        assert ok == 200
        assert result["view"]["state"] == "needs_clarification"
    assert TimelineConfig.model_validate_json(
        project_file.read_text()
    ).tracks["video"].clips


def _imports(path):
    tree = ast.parse(path.read_text())
    return {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_product_service_has_no_timeline_renderer_or_skill_imports():
    imports = _imports(SRC / "product_entry" / "service.py")
    forbidden = {
        "core",
        "core.timeline",
        "core.timeline_manager",
        "skills",
        "timeline_manager",
    }
    assert not any(
        name in forbidden or name.startswith("skills.")
        for name in imports
    )
