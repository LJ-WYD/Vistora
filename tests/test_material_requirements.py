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
from agent import DirectorAgent, EditingAgent  # noqa: E402
from creation_planning import (  # noqa: E402
    CapabilityRegistryReference,
    CapabilityRequirement,
    CreationPlanningAgent,
    CreationPlanningReasoningOutput,
    CreationPlanningService,
    CreationPlanningStore,
    DeliveryFileSpecification,
    MaterialProductionPlanDraft,
    MaterialProductionTask,
    ProductionEstimate,
)
from core import timeline_manager  # noqa: E402
from core.timeline import TimelineConfig, TrackConfig  # noqa: E402
from director import (  # noqa: E402
    CreativeBriefInput,
    DirectorContextService,
    DirectorReasoningOutput,
    DirectorStore,
    MaterialRequirementItem,
    MaterialRequirementsDraft,
    RequirementConstraint,
)
from material_requirements import (  # noqa: E402
    MaterialRequirementsConcurrencyError,
    MaterialRequirementsIntegrityError,
    MaterialRequirementsService,
    MaterialRequirementsStore,
)
from material_production import (  # noqa: E402
    AdapterRegistry,
    DeterministicLocalVideoAdapter,
    MaterialCatalogStore,
    MaterialProductionOrchestrator,
    MaterialProductionStore,
)
from product_entry import (  # noqa: E402
    ProductEntryCommand,
    ProductEntryStore,
    ProductionEntryService,
)
from timeline_query import TimelineSnapshotService  # noqa: E402
from workflow import WorkflowApplicationService, WorkflowStore  # noqa: E402


START = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)


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


def _full_brief():
    return CreativeBriefInput(
        objective="Launch a calm mobile productivity feature.",
        audience="Busy knowledge workers.",
        platform="Vertical social video.",
        target_duration_seconds=15.0,
        style="Clean, grounded, and human.",
        narrative="Problem, focused interaction, resolved outcome.",
        pacing="Measured opening with a concise payoff.",
        must_haves=("Show one authentic product interaction.",),
        must_not_haves=("Do not imply unsupported features.",),
        delivery_requirements=("1080x1920 H.264 master.",),
        assumptions=("Product UI reference will be supplied later.",),
        acceptance_criteria=(
            "The story is understandable without sound.",
            "All created material follows the vertical composition.",
        ),
    )


def _draft(*, purpose="Show the authentic interaction."):
    unknown = RequirementConstraint(status="unknown")
    return MaterialRequirementsDraft(
        rationale=(
            "No observed material exists, so the Director must specify the "
            "minimum grounded source set before production planning."
        ),
        items=(
            MaterialRequirementItem(
                item_id="material_need_hero_shot",
                asset_type="video_shot",
                purpose=purpose,
                narrative_position="Middle proof beat.",
                duration_seconds=6.0,
                aspect_ratio="9:16",
                width=1080,
                height=1920,
                fps=30.0,
                audio_requirements=("Record clean interaction sound.",),
                continuity_requirements=(
                    "Use the same device and hand across takes.",
                ),
                must_haves=("UI text must remain readable.",),
                must_not_haves=("No fabricated product state.",),
                acceptance_criteria=(
                    "The tap and resulting UI response are visible.",
                ),
                priority="required",
                alternatives=(
                    "Use a validated screen recording if filming fails.",
                ),
                budget_constraint=unknown,
                deadline_constraint=unknown,
            ),
            MaterialRequirementItem(
                item_id="material_need_narration",
                asset_type="narration",
                purpose="State the user benefit without adding claims.",
                narrative_position="Opening and final payoff.",
                duration_seconds=8.0,
                audio_requirements=("Dry mono voice recording.",),
                acceptance_criteria=(
                    "Every spoken claim appears in the approved brief.",
                ),
                priority="high",
                dependency_ids=("material_need_hero_shot",),
                budget_constraint=unknown,
                deadline_constraint=unknown,
            ),
        ),
        global_acceptance_criteria=(
            "Every accepted asset maps to one requirement item.",
        ),
        unresolved_constraints=(
            "Production budget is unknown.",
            "Delivery deadline is unknown.",
        ),
    )


class MaterialAdapter:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def complete(self, request):
        value = self.outputs.pop(0)
        if callable(value):
            return value(request)
        return value


def _output(request, *, brief, draft=None, clarify=False):
    return DirectorReasoningOutput(
        response_kind=(
            "clarify" if clarify else "propose_material_requirements"
        ),
        assistant_message=(
            "I need the missing delivery context."
            if clarify
            else "The material requirements are ready for review."
        ),
        context_snapshot_ref=request.context.snapshot_ref,
        registry_ref=request.context.registry_ref,
        brief=brief,
        clarification_questions=(
            ("Which audience and platform should this serve?",)
            if clarify
            else ()
        ),
        material_requirements_draft=draft,
    ).model_dump(mode="json")


def _production_output(request):
    unknown = ProductionEstimate(
        status="unknown",
        rationale="No configured provider estimate is available.",
    )
    draft = MaterialProductionPlanDraft(
        rationale="Plan how to supply the exact confirmed requirements.",
        tasks=(
            MaterialProductionTask(
                task_id="production_task_manual_hero",
                requirement_item_id="material_need_hero_shot",
                title="Import an approved hero-shot recording",
                purpose="Supply the confirmed authentic interaction.",
                production_method="import",
                status="planned",
                capability_ids=("manual_import",),
                duration_seconds=6.0,
                width=1080,
                height=1920,
                aspect_ratio="9:16",
                fps=30.0,
                batch_id="production_batch_manual",
                cost_estimate=unknown,
                time_estimate=unknown,
                quality_gates=("The interaction remains legible.",),
                retry_strategy=("Request a corrected import.",),
                alternative_strategy="Capture the interaction locally.",
                delivery=DeliveryFileSpecification(
                    media_kind="video",
                    container_or_extension="mp4",
                    mime_type="video/mp4",
                    filename_pattern="hero_{attempt}.mp4",
                ),
            ),
        ),
        delivery_summary=("One approved vertical hero shot.",),
        global_quality_gates=(
            "The delivery maps to its requirement item.",
        ),
    )
    return CreationPlanningReasoningOutput(
        outcome="proposal",
        message="The production plan is ready for review.",
        material_confirmation_ref=request.material_confirmation_ref,
        capability_registry_ref=request.capability_registry_ref,
        plan_draft=draft,
    ).model_dump(mode="json")


def _production_capabilities():
    return CapabilityRegistryReference.create(
        registry_id="material_test_capabilities",
        registry_revision=1,
        capabilities=(
            CapabilityRequirement(
                capability_id="manual_import",
                capability_kind="manual_import",
                availability="available",
            ),
        ),
    )


@pytest.fixture
def no_material(tmp_path, monkeypatch):
    project_file = tmp_path / ".workspace" / "current_timeline.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text(
        TimelineConfig(
            width=1080,
            height=1920,
            fps=30,
            tracks={
                "video": TrackConfig(id="video"),
                "audio": TrackConfig(id="audio"),
            },
        ).model_dump_json(indent=2)
    )
    monkeypatch.setattr(timeline_manager, "PROJECT_FILE", str(project_file))
    monkeypatch.setattr(
        timeline_manager,
        "WORKSPACE_DIR",
        str(project_file.parent),
    )
    deterministic = Deterministic()
    director_store = DirectorStore(
        project_file.with_name("requirements.director.json")
    )

    def context():
        snapshot = TimelineSnapshotService.snapshot_current()
        return (
            DirectorContextService.build(
                snapshot,
                vistora_main.SKILLS,
                materials=(),
            ),
            snapshot,
        )

    adapter = MaterialAdapter(
        [
            lambda request: _output(
                request,
                brief=CreativeBriefInput(
                    objective="Make a launch video.",
                    unresolved_questions=(
                        "Which audience and platform should this serve?",
                    ),
                ),
                clarify=True,
            ),
            lambda request: _output(
                request,
                brief=_full_brief(),
                draft=_draft(),
            ),
        ]
    )
    agent = DirectorAgent(
        adapter=adapter,
        context_provider=context,
        registry=vistora_main.SKILLS,
        store=director_store,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    service = MaterialRequirementsService(
        store=MaterialRequirementsStore(
            project_file.with_name("requirements.materials.json")
        ),
        session_id="session_materials",
        project_id=TimelineSnapshotService.snapshot_current().project_id,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return agent, director_store, service, project_file, deterministic


def test_no_material_clarification_then_reviewable_requirements(no_material):
    agent, director_store, _, project_file, _ = no_material
    before = project_file.read_bytes()
    clarify = agent.converse(
        session_id="session_materials",
        turn_id="turn_materials_01",
        user_message="Create a launch video without supplied footage.",
    )
    assert clarify.status == "needs_clarification"
    ready = agent.converse(
        session_id="session_materials",
        turn_id="turn_materials_02",
        user_message=(
            "Vertical social, knowledge workers, calm, 15 seconds, and the "
            "listed acceptance criteria."
        ),
    )
    assert ready.status == "material_requirements_ready"
    assert ready.proposal is None
    proposal = ready.material_requirements
    assert proposal.plan.brief_ref.brief_version == 2
    assert proposal.plan.items[0].asset_type == "video_shot"
    assert proposal.plan.items[0].budget_constraint.status == "unknown"
    assert proposal.review.changes[0].change_type == "added"
    assert proposal.plan.no_material_fact_digest.startswith("sha256:")
    assert not proposal.plan.model_dump().get("source_evidence")
    assert project_file.read_bytes() == before
    ledger = director_store.load()
    assert ledger.entries[-1].record.report.material_requirements == proposal


def test_material_review_requires_independent_exact_confirmation(no_material):
    agent, _, service, project_file, _ = no_material
    agent._adapter.outputs = [
        lambda request: _output(
            request,
            brief=_full_brief(),
            draft=_draft(),
        )
    ]
    report = agent.converse(
        session_id="session_materials",
        turn_id="turn_materials_ready",
        user_message="The complete no-material brief is approved for review.",
    )
    proposal = report.material_requirements
    before = project_file.read_bytes()
    recorded = service.record(proposal, expected_revision=0)
    assert recorded.revision == 1
    assert service.view().state == "reviewable"
    confirmation, ledger = service.decide(
        proposal.review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=1,
    )
    assert ledger.revision == 2
    assert service.view().state == "confirmed"
    binding = service.confirmed(confirmation.confirmation_id)
    assert binding.proposal == proposal
    assert binding.confirmation.decision == "confirmed"
    assert project_file.read_bytes() == before
    with pytest.raises(MaterialRequirementsConcurrencyError):
        service.decide(
            proposal.review.review_id,
            decision="confirmed",
            confirmed_by="local_user",
            expected_revision=1,
        )


def test_revision_diff_rejection_withdrawal_and_stale_snapshot(no_material):
    agent, _, service, project_file, _ = no_material
    agent._adapter.outputs = [
        lambda request: _output(
            request,
            brief=_full_brief(),
            draft=_draft(),
        ),
        lambda request: _output(
            request,
            brief=_full_brief().model_copy(
                update={"style": "Warm and documentary."}
            ),
            draft=_draft(purpose="Show a warmer authentic interaction."),
        ),
    ]
    first = agent.converse(
        session_id="session_materials",
        turn_id="turn_revision_01",
        user_message="Prepare material requirements.",
    ).material_requirements
    second = agent.converse(
        session_id="session_materials",
        turn_id="turn_revision_02",
        user_message="Revise the style to warm documentary.",
    ).material_requirements
    assert second.plan.plan_id == first.plan.plan_id
    assert second.plan.plan_version == 2
    assert second.review.previous_plan_digest == first.plan.digest()
    assert any(
        change.change_type == "changed"
        for change in second.review.changes
    )
    service.record(second, expected_revision=0)
    confirmation, _ = service.decide(
        second.review.review_id,
        decision="rejected",
        confirmed_by="local_user",
        expected_revision=1,
    )
    assert confirmation.decision == "rejected"
    assert service.view().state == "rejected"
    service.withdraw(second.proposal_id, expected_revision=2)
    assert service.view().state == "withdrawn"

    project_file.write_text(
        TimelineConfig(
            width=720,
            height=1280,
            fps=24,
            tracks={
                "video": TrackConfig(id="video"),
                "audio": TrackConfig(id="audio"),
            },
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="snapshot changed"):
        service.record(first, expected_revision=3)


def test_material_schema_conflicts_and_ledger_tamper(no_material):
    with pytest.raises(ValidationError):
        MaterialRequirementItem(
            item_id="material_invalid",
            asset_type="video_shot",
            purpose="Invalid.",
            narrative_position="Opening.",
            must_haves=("Same constraint.",),
            must_not_haves=("Same constraint.",),
            acceptance_criteria=("Must pass.",),
            priority="required",
            budget_constraint=RequirementConstraint(status="unknown"),
            deadline_constraint=RequirementConstraint(status="unknown"),
        )
    agent, _, service, _, _ = no_material
    agent._adapter.outputs = [
        lambda request: _output(
            request,
            brief=_full_brief(),
            draft=_draft(),
        )
    ]
    proposal = agent.converse(
        session_id="session_materials",
        turn_id="turn_tamper",
        user_message="Prepare exact requirements.",
    ).material_requirements
    service.record(proposal, expected_revision=0)
    payload = json.loads(service.store.path.read_text())
    payload["events"][0]["proposal"]["plan"]["rationale"] = "tampered"
    service.store.path.write_text(json.dumps(payload))
    with pytest.raises(MaterialRequirementsIntegrityError):
        service.store.load()


def test_product_entry_reviews_and_confirms_material_requirements(no_material):
    agent, director_store, materials, project_file, deterministic = no_material
    agent._adapter.outputs = [
        lambda request: _output(
            request,
            brief=_full_brief(),
            draft=_draft(),
        )
    ]
    workflow = WorkflowApplicationService(
        store=WorkflowStore.for_project_file(project_file),
        registry=vistora_main.SKILLS,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    creation_service = CreationPlanningService(
        store=CreationPlanningStore(
            project_file.with_name("requirements.creation-planning.json")
        ),
        material_requirements=materials,
        session_id="session_materials",
        project_id=materials.project_id,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    creation_agent = CreationPlanningAgent(
        adapter=MaterialAdapter([_production_output]),
        service=creation_service,
        capability_provider=_production_capabilities,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    material_production = MaterialProductionOrchestrator(
        creation_planning=creation_service,
        adapters=AdapterRegistry(
            (
                DeterministicLocalVideoAdapter(
                    clock=deterministic.clock,
                    capability_ids=("manual_import",),
                    width=1080,
                    height=1920,
                    fps=30,
                    duration_seconds=6,
                ),
            )
        ),
        store=MaterialProductionStore(
            project_file.with_name("requirements.production.json")
        ),
        catalog=MaterialCatalogStore(
            project_file.with_name(
                "requirements.material-catalog.json"
            ),
            media_root=project_file.parent / "materials",
        ),
        staging_root=project_file.parent / "material_staging",
        project_id=materials.project_id,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    product = ProductionEntryService(
        director=agent,
        director_store=director_store,
        workflow=workflow,
        editing_agent=EditingAgent(
            workflow,
            clock=deterministic.clock,
            id_factory=deterministic.identifier,
        ),
        store=ProductEntryStore(
            project_file.with_name("requirements.product.json")
        ),
        session_id="session_materials",
        project_id=materials.project_id,
        material_requirements=materials,
        creation_planning_agent=creation_agent,
        creation_planning=creation_service,
        material_production=material_production,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    before = project_file.read_bytes()
    ready = product.command(
        ProductEntryCommand(
            request_id="request_material_product_01",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=0,
            action="director_turn",
            actor_id="local_user",
            user_message="The no-material creative brief is complete.",
        )
    )
    assert ready.view.state == "material_requirements_ready"
    proposal = ready.view.director["material_requirements"][-1]
    reviewed = product.command(
        ProductEntryCommand(
            request_id="request_material_product_02",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=1,
            action="persist_material_review",
            actor_id="local_user",
            target_id=proposal["proposal_id"],
        )
    )
    assert reviewed.view.state == "material_reviewed"
    material_view = reviewed.view.material_requirements
    review_id = material_view["proposals"][-1]["review_id"]
    confirmed = product.command(
        ProductEntryCommand(
            request_id="request_material_product_03",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=2,
            action="confirm_materials",
            actor_id="local_user",
            target_id=review_id,
        )
    )
    assert confirmed.view.state == "materials_confirmed"
    assert confirmed.view.material_requirements["state"] == "confirmed"
    assert "plan_material_production" in confirmed.view.allowed_actions
    material_confirmation_id = confirmed.view.latest_result[
        "confirmation_id"
    ]
    planned = product.command(
        ProductEntryCommand(
            request_id="request_material_product_04",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=confirmed.view.revision,
            action="plan_material_production",
            actor_id="local_user",
            target_id=material_confirmation_id,
        )
    )
    assert planned.view.state == "production_plan_ready"
    assert planned.view.creation_planning["state"] == "reviewable"
    production_review_id = planned.view.latest_result["review_id"]
    production_confirmed = product.command(
        ProductEntryCommand(
            request_id="request_material_product_05",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=planned.view.revision,
            action="confirm_production_plan",
            actor_id="local_user",
            target_id=production_review_id,
        )
    )
    assert production_confirmed.view.state == "production_plan_confirmed"
    assert production_confirmed.view.creation_planning["state"] == "confirmed"
    started = product.command(
        ProductEntryCommand(
            request_id="request_material_product_06",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=production_confirmed.view.revision,
            action="start_material_production",
            actor_id="local_user",
            target_id=production_confirmed.view.latest_result[
                "confirmation_id"
            ],
        )
    )
    assert started.view.state == "material_awaiting_review"
    artifact_id = started.view.material_production["artifacts"][0][
        "artifact_id"
    ]
    rejected = product.command(
        ProductEntryCommand(
            request_id="request_material_product_07",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=started.view.revision,
            action="reject_material_artifact",
            actor_id="local_user",
            target_id=artifact_id,
        )
    )
    assert rejected.view.state == "material_production_partial"
    assert rejected.view.allowed_actions == ("retry_material_job",)
    job_id = rejected.view.material_production["jobs"][0]["job_id"]
    retried = product.command(
        ProductEntryCommand(
            request_id="request_material_product_08",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=rejected.view.revision,
            action="retry_material_job",
            actor_id="local_user",
            target_id=job_id,
        )
    )
    assert retried.view.state == "material_awaiting_review"
    retry_artifact = next(
        item
        for item in retried.view.material_production["artifacts"]
        if item["decision"] is None
    )
    accepted = product.command(
        ProductEntryCommand(
            request_id="request_material_product_09",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=retried.view.revision,
            action="accept_material_artifact",
            actor_id="local_user",
            target_id=retry_artifact["artifact_id"],
        )
    )
    assert accepted.view.state == "material_production_succeeded"
    assert accepted.view.material_production["catalog_revision"] == 1
    run_id = accepted.view.material_production["runs"][-1]["run_id"]
    with pytest.raises(ValueError, match="Exact succeeded run"):
        product.command(
            ProductEntryCommand(
                request_id="request_material_product_wrong_run",
                session_id=product.session_id,
                project_id=product.project_id,
                expected_revision=accepted.view.revision,
                action="return_to_director",
                actor_id="local_user",
                target_id="production_run_from_another_session",
            )
        )
    returned = product.command(
        ProductEntryCommand(
            request_id="request_material_product_10",
            session_id=product.session_id,
            project_id=product.project_id,
            expected_revision=accepted.view.revision,
            action="return_to_director",
            actor_id="local_user",
            target_id=run_id,
        )
    )
    assert returned.view.state == "returned_to_director"
    assert returned.view.latest_result["accepted_material_ids"][0].startswith(
        "source_"
    )
    assert project_file.read_bytes() == before
