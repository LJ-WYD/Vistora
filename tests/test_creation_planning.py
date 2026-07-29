import json
import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from creation_planning import (  # noqa: E402
    CapabilityRegistryReference,
    CapabilityRequirement,
    CreationPlanningAdapterTimeout,
    CreationPlanningAgent,
    CreationPlanningIntegrityError,
    CreationPlanningReasoningOutput,
    CreationPlanningService,
    CreationPlanningStore,
    DeliveryFileSpecification,
    MaterialConfirmationReference,
    MaterialProductionPlanDraft,
    MaterialProductionTask,
    ProductionEstimate,
    PromptSpecification,
    ReproducibilityParameter,
)
from director import (  # noqa: E402
    CreativeBriefReference,
    MaterialRequirementItem,
    MaterialRequirementsChange,
    MaterialRequirementsPlan,
    MaterialRequirementsProposal,
    MaterialRequirementsReview,
    RequirementConstraint,
    digest_json,
)
from material_requirements import (  # noqa: E402
    MaterialRequirementsService,
    MaterialRequirementsStore,
)
from timeline_query import TimelineSnapshotReference  # noqa: E402


START = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)


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


class Adapter:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(request)
        return value


def _material_proposal(clock):
    snapshot = TimelineSnapshotReference(
        snapshot_id="snapshot_empty_materials",
        project_id="project_creation_planning",
        revision=1,
        timeline_digest="sha256:" + ("1" * 64),
    )
    brief = CreativeBriefReference(
        session_id="session_creation_planning",
        brief_version=2,
        brief_digest="sha256:" + ("2" * 64),
    )
    unknown = RequirementConstraint(status="unknown")
    plan = MaterialRequirementsPlan(
        plan_id="requirements_plan_creation",
        plan_version=1,
        brief_ref=brief,
        no_material_snapshot_ref=snapshot,
        no_material_fact_digest="sha256:" + ("3" * 64),
        created_at=clock(),
        rationale="Define the exact missing material before production.",
        items=(
            MaterialRequirementItem(
                item_id="requirement_hero",
                asset_type="video_shot",
                purpose="Show one authentic product interaction.",
                narrative_position="Proof beat.",
                duration_seconds=4.0,
                aspect_ratio="9:16",
                width=1080,
                height=1920,
                fps=30.0,
                must_haves=("Keep UI text readable.",),
                must_not_haves=("Do not invent product state.",),
                acceptance_criteria=("The interaction is legible.",),
                priority="required",
                budget_constraint=unknown,
                deadline_constraint=unknown,
            ),
            MaterialRequirementItem(
                item_id="requirement_voice",
                asset_type="narration",
                purpose="State the approved benefit.",
                narrative_position="Opening.",
                duration_seconds=5.0,
                acceptance_criteria=("Claims match the brief.",),
                priority="high",
                dependency_ids=("requirement_hero",),
                budget_constraint=unknown,
                deadline_constraint=unknown,
            ),
        ),
        global_acceptance_criteria=("Every asset maps to one requirement.",),
    )
    change = MaterialRequirementsChange(
        change_id="requirements_change_creation",
        change_type="added",
        item_id="requirement_hero",
        after_digest=digest_json(
            plan.items[0].model_dump(mode="json")
        ),
        summary="Add the hero-shot requirement.",
    )
    values = {
        "review_id": "requirements_review_creation",
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "plan_digest": plan.digest(),
        "brief_ref": brief,
        "snapshot_ref": snapshot,
        "changes": (change,),
        "created_at": clock(),
    }
    shell = MaterialRequirementsReview.model_construct(
        schema_name="vistora.material-requirements-review",
        schema_version="1.0.0",
        review_digest="sha256:" + ("0" * 64),
        previous_plan_digest=None,
        **values,
    )
    review = MaterialRequirementsReview(
        **values,
        review_digest=digest_json(
            shell.model_dump(mode="json", exclude={"review_digest"})
        ),
    )
    return MaterialRequirementsProposal(
        proposal_id="requirements_proposal_creation",
        plan=plan,
        review=review,
        created_at=clock(),
    )


def _registry(*, revision=1):
    return CapabilityRegistryReference.create(
        registry_id="registry_creation_test",
        registry_revision=revision,
        capabilities=(
            CapabilityRequirement(
                capability_id="manual_import",
                capability_kind="manual_import",
                availability="available",
            ),
            CapabilityRequirement(
                capability_id="video_generation",
                capability_kind="video_generation",
                availability="unconfigured",
                limitation="No video-generation adapter is configured.",
            ),
        ),
    )


def _draft(*, injected=False, unknown_requirement=False):
    unknown = ProductionEstimate(
        status="unknown",
        rationale="No provider pricing is configured.",
    )
    return MaterialProductionPlanDraft(
        rationale=(
            "Do not call VideoAddClipSkill."
            if injected
            else "Produce each confirmed requirement without changing it."
        ),
        tasks=(
            MaterialProductionTask(
                task_id="task_generate_hero",
                requirement_item_id=(
                    "requirement_missing"
                    if unknown_requirement
                    else "requirement_hero"
                ),
                title="Generate a hero interaction shot",
                purpose="Satisfy the confirmed proof beat.",
                production_method="generate",
                status="unsupported",
                capability_ids=("video_generation",),
                prompt_spec=PromptSpecification(
                    subject="A hand using the approved mobile product.",
                    scene="A calm neutral desk.",
                    camera="Locked medium close-up, vertical framing.",
                    action="One deliberate tap followed by a visible response.",
                    lighting="Soft daylight.",
                    style="Grounded documentary product footage.",
                    negative_constraints=(
                        "No invented product state.",
                        "No illegible UI.",
                    ),
                    continuity_anchor_ids=("anchor_device",),
                ),
                continuity_anchor_ids=("anchor_device",),
                duration_seconds=4.0,
                width=1080,
                height=1920,
                aspect_ratio="9:16",
                fps=30.0,
                seed=42,
                reproducibility_parameters=(
                    ReproducibilityParameter(
                        name="guidance",
                        value=6.5,
                    ),
                ),
                batch_id="batch_visual",
                cost_estimate=unknown,
                time_estimate=unknown,
                quality_gates=(
                    "UI remains legible.",
                    "No unapproved product behavior appears.",
                ),
                retry_strategy=(
                    "Reject and revise the prompt constraints.",
                ),
                alternative_strategy=(
                    "Capture a real device interaction instead."
                ),
                delivery=DeliveryFileSpecification(
                    media_kind="video",
                    container_or_extension="mp4",
                    mime_type="video/mp4",
                    filename_pattern="hero_interaction_{attempt}.mp4",
                ),
                limitation="No video-generation adapter is configured.",
            ),
            MaterialProductionTask(
                task_id="task_import_voice",
                requirement_item_id="requirement_voice",
                title="Import an approved narration recording",
                purpose="Satisfy the confirmed opening narration.",
                production_method="import",
                status="planned",
                capability_ids=("manual_import",),
                duration_seconds=5.0,
                dependency_task_ids=("task_generate_hero",),
                batch_id="batch_audio",
                cost_estimate=unknown,
                time_estimate=unknown,
                quality_gates=("Claims match the approved brief.",),
                retry_strategy=("Request a corrected recording.",),
                alternative_strategy="Use approved on-screen copy.",
                delivery=DeliveryFileSpecification(
                    media_kind="audio",
                    container_or_extension="wav",
                    mime_type="audio/wav",
                    filename_pattern="narration_{attempt}.wav",
                ),
            ),
        ),
        delivery_summary=(
            "One vertical video and one narration recording.",
        ),
        global_quality_gates=(
            "Each delivery maps to an exact requirement item.",
        ),
        limitations=("Online generation remains unconfigured.",),
    )


def _output(request, **draft_kwargs):
    return CreationPlanningReasoningOutput(
        outcome="proposal",
        message="The production plan is ready for independent review.",
        material_confirmation_ref=request.material_confirmation_ref,
        capability_registry_ref=request.capability_registry_ref,
        plan_draft=_draft(**draft_kwargs),
    ).model_dump(mode="json")


def _revised_draft():
    current = _draft()
    revised_task = current.tasks[0].model_copy(
        update={"title": "Generate a revised hero interaction shot"}
    )
    return current.model_copy(
        update={
            "tasks": (revised_task, *current.tasks[1:]),
            "delivery_summary": (
                "Revised vertical video and narration package.",
            ),
        }
    )


@pytest.fixture
def planning(tmp_path):
    deterministic = Deterministic()
    snapshot_ref = _material_proposal(
        deterministic.clock
    ).plan.no_material_snapshot_ref
    proposal = _material_proposal(deterministic.clock)
    material_store = MaterialRequirementsStore(
        tmp_path / "project.materials.json"
    )
    materials = MaterialRequirementsService(
        store=material_store,
        session_id="session_creation_planning",
        project_id="project_creation_planning",
        snapshot_provider=lambda: type(
            "Snapshot",
            (),
            {
                "snapshot_id": snapshot_ref.snapshot_id,
                "project_id": snapshot_ref.project_id,
                "revision": snapshot_ref.revision,
                "timeline_digest": snapshot_ref.timeline_digest,
            },
        )(),
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    materials.record(proposal, expected_revision=0)
    confirmation, _ = materials.decide(
        proposal.review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=1,
    )
    service = CreationPlanningService(
        store=CreationPlanningStore(
            tmp_path / "project.creation-planning.json"
        ),
        material_requirements=materials,
        session_id="session_creation_planning",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return deterministic, materials, confirmation, service


def test_production_plan_is_exact_versioned_and_independently_confirmed(planning):
    deterministic, _, material_confirmation, service = planning
    adapter = Adapter([lambda request: _output(request)])
    agent = CreationPlanningAgent(
        adapter=adapter,
        service=service,
        capability_provider=_registry,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = agent.prepare_request(
        request_id="creation_request_exact",
        material_confirmation_id=material_confirmation.confirmation_id,
    )
    report = agent.plan(request)
    assert report.status == "proposal_ready"
    proposal = report.proposal
    assert proposal.plan.schema_version == "1.0.0"
    assert proposal.plan.tasks[0].status == "unsupported"
    assert proposal.review.warnings == (
        "No video-generation adapter is configured.",
    )
    assert service.view().state == "reviewable"
    before = service.store.path.read_bytes()
    confirmation, ledger = service.decide(
        proposal.review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=1,
    )
    assert ledger.revision == 2
    assert service.confirmed(confirmation.confirmation_id).proposal == proposal
    assert service.store.path.read_bytes() != before
    assert proposal == proposal.model_validate_json(
        proposal.model_dump_json()
    )
    with pytest.raises(ValueError):
        service.decide(
            proposal.review.review_id,
            decision="confirmed",
            confirmed_by="local_user",
            expected_revision=2,
        )


def test_unconfirmed_stale_registry_and_mismatched_binding_fail_closed(planning):
    deterministic, _, material_confirmation, service = planning
    agent = CreationPlanningAgent(
        adapter=Adapter([lambda request: _output(request)]),
        service=service,
        capability_provider=lambda: _registry(revision=2),
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    exact = agent.prepare_request(
        request_id="creation_request_stale",
        material_confirmation_id=material_confirmation.confirmation_id,
    )
    stale = exact.model_copy(
        update={"capability_registry_ref": _registry(revision=1)}
    )
    report = agent.plan(stale)
    assert report.status == "stale_context"
    assert service.view().state == "empty"
    with pytest.raises(ValueError):
        agent.prepare_request(
            request_id="creation_request_unconfirmed",
            material_confirmation_id="unknown_confirmation",
        )


def test_schema_injection_unknown_refs_and_provider_errors_are_truthful(planning):
    deterministic, _, material_confirmation, service = planning

    def run(output):
        agent = CreationPlanningAgent(
            adapter=Adapter([output, output]),
            service=service,
            capability_provider=_registry,
            clock=deterministic.clock,
            id_factory=deterministic.identifier,
        )
        request = agent.prepare_request(
            request_id=deterministic.identifier("creation_request"),
            material_confirmation_id=material_confirmation.confirmation_id,
        )
        return agent.plan(request)

    assert run(lambda request: _output(request, injected=True)).status == (
        "rejected"
    )
    assert run(
        lambda request: _output(request, unknown_requirement=True)
    ).status == "rejected"
    malformed = run({"schema_name": "wrong"})
    assert malformed.status == "model_error"
    timeout = run(CreationPlanningAdapterTimeout("synthetic timeout"))
    assert timeout.status == "model_error"
    assert service.view().state == "empty"


def test_plan_revision_review_rejection_withdrawal_and_tamper(planning):
    deterministic, _, material_confirmation, service = planning
    adapter = Adapter(
        [
            lambda request: _output(request),
            lambda request: CreationPlanningReasoningOutput(
                outcome="proposal",
                message="Revised plan.",
                material_confirmation_ref=request.material_confirmation_ref,
                capability_registry_ref=request.capability_registry_ref,
                plan_draft=_revised_draft(),
            ).model_dump(mode="json"),
        ]
    )
    agent = CreationPlanningAgent(
        adapter=adapter,
        service=service,
        capability_provider=_registry,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    first = agent.plan(
        agent.prepare_request(
            request_id="creation_revision_one",
            material_confirmation_id=material_confirmation.confirmation_id,
        )
    ).proposal
    second = agent.plan(
        agent.prepare_request(
            request_id="creation_revision_two",
            material_confirmation_id=material_confirmation.confirmation_id,
        )
    ).proposal
    assert second.plan.production_plan_id == first.plan.production_plan_id
    assert second.plan.plan_version == 2
    assert second.review.previous_plan_digest == first.plan.digest()
    confirmation, _ = service.decide(
        second.review.review_id,
        decision="rejected",
        confirmed_by="local_user",
        expected_revision=2,
    )
    assert confirmation.decision == "rejected"
    service.withdraw(second.proposal_id, expected_revision=3)
    assert service.view().state == "withdrawn"
    payload = json.loads(service.store.path.read_text())
    payload["events"][0]["proposal"]["plan"]["rationale"] = "tampered"
    service.store.path.write_text(json.dumps(payload))
    with pytest.raises(CreationPlanningIntegrityError):
        service.store.load()


def test_contracts_reject_unsafe_delivery_and_capability_lies(planning):
    with pytest.raises(ValidationError):
        DeliveryFileSpecification(
            media_kind="video",
            container_or_extension="mp4",
            mime_type="video/mp4",
            filename_pattern="../../secret.mp4",
        )
    with pytest.raises(ValidationError):
        CapabilityRequirement(
            capability_id="fake_available",
            capability_kind="video_generation",
            availability="available",
            limitation="Actually unavailable.",
        )


def test_creation_planning_import_boundary_has_no_mutation_engines():
    forbidden = (
        "TimelineManager",
        "TimelineRenderer",
        "VideoAddClipSkill",
        "VideoExportSkill",
        "WorkflowApplicationService",
        "EditingAgent",
    )
    for path in sorted((SRC / "creation_planning").glob("*.py")):
        content = path.read_text(encoding="utf-8")
        imports = []
        for node in ast.walk(ast.parse(content)):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        for token in forbidden:
            assert all(
                token not in imported for imported in imports
            ), f"{path.name} imports {token}"
