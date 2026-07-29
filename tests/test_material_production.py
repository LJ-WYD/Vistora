import ast
import json
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from creation_planning import (  # noqa: E402
    CapabilityRegistryReference,
    CapabilityRequirement,
    CreationPlanningAgent,
    CreationPlanningReasoningOutput,
    DeliveryFileSpecification,
    MaterialProductionPlanDraft,
    MaterialProductionTask,
    ProductionEstimate,
    ReproducibilityParameter,
)
from material_production import (  # noqa: E402
    AdapterCapability,
    AdapterJobUpdate,
    AdapterRegistry,
    ArtifactCandidate,
    DeterministicLocalVideoAdapter,
    ManualImportAdapter,
    MaterialCatalogStore,
    MaterialProductionIntegrityError,
    MaterialProductionOrchestrator,
    MaterialProductionStore,
    ProductionTaskInput,
)
from core import timeline_manager  # noqa: E402
from core.timeline import TimelineConfig, TrackConfig  # noqa: E402
from skills.video_add_clip import VideoAddClipSkill  # noqa: E402
from tests.test_creation_planning import (  # noqa: E402
    Adapter,
    planning as planning_fixture,
)


def _production_draft(*, two_tasks=False, manual=False):
    unknown = ProductionEstimate(
        status="unknown",
        rationale="The deterministic fake provider has no billable cost.",
    )

    def task(task_id, requirement_id, dependency_ids=()):
        return MaterialProductionTask(
            task_id=task_id,
            requirement_item_id=requirement_id,
            title=f"Produce deterministic fixture {task_id}",
            purpose="Satisfy the exact confirmed material requirement.",
            production_method=("import" if manual else "generate"),
            status="planned",
            capability_ids=(
                ("manual_import",) if manual else ("video_generation",)
            ),
            prompt_spec=(
                None
                if manual
                else {
                    "subject": "A deterministic reference frame.",
                    "scene": "A synthetic test canvas.",
                    "camera": "Locked frame.",
                    "action": "No motion.",
                    "lighting": "Uniform synthetic color.",
                    "style": "Deterministic regression fixture.",
                    "negative_constraints": [
                        "No nondeterministic content."
                    ],
                }
            ),
            duration_seconds=2.0,
            width=320,
            height=180,
            aspect_ratio="16:9",
            fps=24.0,
            seed=24,
            reproducibility_parameters=(
                ReproducibilityParameter(
                    name="fixture_version",
                    value="1",
                ),
            ),
            dependency_task_ids=dependency_ids,
            batch_id="production_batch_test",
            cost_estimate=unknown,
            time_estimate=unknown,
            quality_gates=("ffprobe reports 320x180 at 24 fps.",),
            retry_strategy=("Retry the deterministic adapter once.",),
            alternative_strategy="Use a validated manual import.",
            delivery=DeliveryFileSpecification(
                media_kind="video",
                container_or_extension="mp4",
                mime_type="video/mp4",
                filename_pattern=f"{task_id}_{{attempt}}.mp4",
            ),
        )

    tasks = (
        task("task_fixture_primary", "requirement_hero"),
        *(
            (task("task_fixture_secondary", "requirement_voice"),)
            if two_tasks
            else ()
        ),
    )
    return MaterialProductionPlanDraft(
        rationale="Produce deterministic local test fixtures.",
        tasks=tasks,
        delivery_summary=("Validated deterministic fixtures.",),
        global_quality_gates=(
            "Every accepted artifact maps to its confirmed requirement.",
        ),
    )


def _production_registry():
    return CapabilityRegistryReference.create(
        registry_id="production_test_capabilities",
        registry_revision=1,
        capabilities=(
            CapabilityRequirement(
                capability_id="manual_import",
                capability_kind="manual_import",
                availability="available",
            ),
            CapabilityRequirement(
                capability_id="video_generation",
                capability_kind="video_generation",
                availability="available",
            ),
        ),
    )


def _confirmed_planning(tmp_path, *, two_tasks=False, manual=False):
    deterministic, materials, material_confirmation, planning = (
        planning_fixture.__wrapped__(tmp_path)
    )

    def output(request):
        return CreationPlanningReasoningOutput(
            outcome="proposal",
            message="The deterministic production plan is ready.",
            material_confirmation_ref=request.material_confirmation_ref,
            capability_registry_ref=request.capability_registry_ref,
            plan_draft=_production_draft(
                two_tasks=two_tasks,
                manual=manual,
            ),
        ).model_dump(mode="json")

    agent = CreationPlanningAgent(
        adapter=Adapter([output]),
        service=planning,
        capability_provider=_production_registry,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    report = agent.plan(
        agent.prepare_request(
            request_id="creation_request_for_production",
            material_confirmation_id=material_confirmation.confirmation_id,
        )
    )
    assert report.status == "proposal_ready"
    confirmation, _ = planning.decide(
        report.proposal.review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=1,
    )
    return deterministic, materials, planning, confirmation


def _orchestrator(
    tmp_path,
    *,
    two_tasks=False,
    fail_task_ids=(),
    corrupt_task_ids=(),
):
    deterministic, _, planning, confirmation = _confirmed_planning(
        tmp_path,
        two_tasks=two_tasks,
    )
    adapter = DeterministicLocalVideoAdapter(
        clock=deterministic.clock,
        fail_task_ids=fail_task_ids,
        corrupt_task_ids=corrupt_task_ids,
    )
    catalog = MaterialCatalogStore(
        tmp_path / "project.material-catalog.json",
        media_root=tmp_path / "catalog_media",
    )
    service = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=AdapterRegistry((adapter,)),
        store=MaterialProductionStore(
            tmp_path / "project.production.json"
        ),
        catalog=catalog,
        staging_root=tmp_path / "staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return deterministic, service, adapter, catalog, confirmation


def test_confirmed_run_validates_then_requires_acceptance_before_catalog(tmp_path):
    _, service, adapter, catalog, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_exact",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    before_catalog = catalog.load(
        project_id="project_creation_planning"
    )
    run = service.start(request)
    assert run["status"] == "awaiting_review"
    view = service.view()
    assert len(adapter.submissions) == 1
    assert view.catalog_revision == 0
    assert view.artifacts[0]["passed"] is True
    assert before_catalog.revision == 0
    artifact_id = view.artifacts[0]["artifact_id"]
    decision, entry = service.decide_artifact(
        artifact_id,
        decision="accepted",
        decided_by="local_user",
        reason="The deterministic metadata matches the confirmed plan.",
    )
    assert decision.decision == "accepted"
    assert entry.source_uri == f"material://{entry.material_id}"
    assert service.view().state == "succeeded"
    assert service.view().catalog_revision == 1
    resolved = catalog.resolve_uri(entry.source_uri)
    assert resolved is not None and resolved.is_file()
    with pytest.raises(ValueError, match="catalog changed"):
        catalog.register(
            before_catalog,
            entry=entry,
            staged_path=resolved,
        )
    serialized_view = service.view().model_dump_json()
    assert str(tmp_path) not in serialized_view
    assert "staging_relative_path" not in serialized_view


def test_run_is_idempotent_and_stale_registry_or_unconfirmed_plan_fails(tmp_path):
    _, service, adapter, _, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_idempotent",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    first = service.start(request)
    second = service.start(request)
    assert first == second
    assert len(adapter.submissions) == 1
    drifted = request.model_copy(
        update={
            "adapter_registry_ref": request.adapter_registry_ref.model_copy(
                update={"registry_revision": 2}
            )
        }
    )
    with pytest.raises(ValueError, match="registry changed"):
        service.start(drifted)
    with pytest.raises(ValueError):
        service.prepare_request(
            request_id="production_request_unknown",
            production_confirmation_id="unknown_confirmation",
            requested_by="local_user",
        )


def test_versioned_contract_roundtrip_and_rate_limit_timeout_are_truthful(
    tmp_path,
):
    deterministic, _, planning, confirmation = _confirmed_planning(tmp_path)

    class RateLimited:
        def capability(self):
            return AdapterCapability(
                adapter_id="rate_limited_test",
                adapter_version="1.0.0",
                capability_ids=("video_generation",),
                configured=True,
                execution_kind="local_deterministic_test",
                max_concurrency=1,
                rate_limit_per_minute=1,
                input_schema_digest="sha256:" + "1" * 64,
                result_schema_digest="sha256:" + "2" * 64,
            )

        def submit(self, request, *, staging_root):
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id="rate_limited_test",
                provider_opaque_ref=f"limited_{request.job_id}",
                status="rate_limited",
                progress=0,
                retry_after_seconds=10,
                error_code="provider_rate_limited",
                message="The deterministic adapter is rate limited.",
                updated_at=deterministic.clock(),
            )

        def poll(
            self,
            request,
            *,
            provider_opaque_ref,
            staging_root,
        ):
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id="rate_limited_test",
                provider_opaque_ref=provider_opaque_ref,
                status="timed_out",
                progress=0,
                error_code="provider_timed_out",
                message="The deterministic adapter timed out.",
                updated_at=deterministic.clock(),
            )

        def cancel(self, request, *, provider_opaque_ref):
            raise AssertionError("Cancel is not used by this test")

    service = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=AdapterRegistry((RateLimited(),)),
        store=MaterialProductionStore(tmp_path / "limited.production.json"),
        catalog=MaterialCatalogStore(
            tmp_path / "limited.catalog.json",
            media_root=tmp_path / "limited_media",
        ),
        staging_root=tmp_path / "limited_staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = service.prepare_request(
        request_id="production_request_limited",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    assert request.model_validate_json(request.model_dump_json()) == request
    invalid = request.model_dump(mode="json")
    invalid["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError):
        type(request).model_validate(invalid)
    assert service.start(request)["status"] == "running"
    assert service.view().jobs[0]["status"] == "rate_limited"
    assert service.poll(service.view().runs[0]["run_id"])["status"] == "failed"
    assert service.view().jobs[0]["status"] == "timed_out"


def test_unconfigured_capability_and_concurrent_store_fail_closed(tmp_path):
    deterministic, _, planning, confirmation = _confirmed_planning(tmp_path)
    adapter = ManualImportAdapter(
        lambda _token: None,
        clock=deterministic.clock,
        configured=False,
    )
    store = MaterialProductionStore(tmp_path / "closed.production.json")
    service = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=AdapterRegistry((adapter,)),
        store=store,
        catalog=MaterialCatalogStore(
            tmp_path / "closed.catalog.json",
            media_root=tmp_path / "closed_media",
        ),
        staging_root=tmp_path / "closed_staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = service.prepare_request(
        request_id="production_request_unconfigured",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    run = service.start(request)
    assert run["status"] == "failed"
    job = service.view().jobs[0]
    assert job["error_code"] == "production_adapter_unconfigured"
    assert adapter.capability().configured is False
    with store.exclusive(
        project_id=service.project_id,
        expected_revision=service.view().ledger_revision,
    ):
        with pytest.raises(ValueError, match="in progress"):
            with store.exclusive(
                project_id=service.project_id,
                expected_revision=service.view().ledger_revision,
            ):
                pass


def test_corrupt_media_and_path_traversal_never_enter_catalog(tmp_path):
    _, service, _, catalog, confirmation = _orchestrator(
        tmp_path,
        corrupt_task_ids=("task_fixture_primary",),
    )
    request = service.prepare_request(
        request_id="production_request_corrupt",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    run = service.start(request)
    assert run["status"] == "failed"
    artifact = service.view().artifacts[0]
    assert artifact["passed"] is False
    assert any("ffprobe" in issue for issue in artifact["issues"])
    with pytest.raises(ValueError):
        service.decide_artifact(
            artifact["artifact_id"],
            decision="accepted",
            decided_by="local_user",
            reason="Attempt an invalid acceptance.",
        )
    assert catalog.load(project_id=service.project_id).revision == 0
    with pytest.raises(ValidationError):
        ArtifactCandidate(
            artifact_id="artifact_escape",
            job_id="job_escape",
            task_id="task_escape",
            requirement_item_id="requirement_escape",
            staging_relative_path="../../outside.mp4",
            claimed_mime_type="video/mp4",
        )


def test_adapter_cannot_cross_job_task_or_requirement_linkage(tmp_path):
    deterministic, _, planning, confirmation = _confirmed_planning(tmp_path)

    class CrossLinked(DeterministicLocalVideoAdapter):
        def submit(self, request, *, staging_root):
            update = super().submit(request, staging_root=staging_root)
            artifact = update.artifacts[0].model_copy(
                update={"task_id": "task_from_another_run"}
            )
            return update.model_copy(update={"artifacts": (artifact,)})

    service = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=AdapterRegistry(
            (CrossLinked(clock=deterministic.clock),)
        ),
        store=MaterialProductionStore(tmp_path / "cross.production.json"),
        catalog=MaterialCatalogStore(
            tmp_path / "cross.catalog.json",
            media_root=tmp_path / "cross_media",
        ),
        staging_root=tmp_path / "cross_staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = service.prepare_request(
        request_id="production_request_cross_link",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    assert service.start(request)["status"] == "failed"
    artifact = service.view().artifacts[0]
    assert artifact["passed"] is False
    assert artifact["issues"] == (
        "Artifact linkage does not match the submitted task.",
    )
    assert service.view().catalog_revision == 0


def test_partial_failure_retry_restart_and_rejection_are_auditable(tmp_path):
    _, service, adapter, _, confirmation = _orchestrator(
        tmp_path,
        two_tasks=True,
        fail_task_ids=("task_fixture_secondary",),
    )
    request = service.prepare_request(
        request_id="production_request_partial",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    run = service.start(request)
    assert run["status"] == "partial"
    view = service.view()
    failed = next(job for job in view.jobs if job["status"] == "failed")
    passed = next(item for item in view.artifacts if item["passed"])
    service.decide_artifact(
        passed["artifact_id"],
        decision="rejected",
        decided_by="local_user",
        reason="Exercise the explicit rejection path.",
    )
    assert service.view().catalog_revision == 0
    adapter.fail_task_ids.clear()
    retried = service.retry(failed["job_id"])
    assert retried.status == "succeeded"
    restarted = MaterialProductionOrchestrator(
        creation_planning=service.creation_planning,
        adapters=service.adapters,
        store=service.store,
        catalog=service.catalog,
        staging_root=service.staging_root,
        project_id=service.project_id,
        clock=service.clock,
        id_factory=service.id_factory,
    )
    assert restarted.view().ledger_revision == service.view().ledger_revision
    retry_artifact = next(
        item
        for item in restarted.view().artifacts
        if item["job_id"] == retried.job_id
    )
    restarted.decide_artifact(
        retry_artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="Accept the validated retry.",
    )
    assert restarted.view().catalog_revision == 1


def test_rejected_valid_artifact_can_be_retried_without_cataloging_it(
    tmp_path,
):
    _, service, _, _, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_reject_retry",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    first_artifact = service.view().artifacts[0]
    service.decide_artifact(
        first_artifact["artifact_id"],
        decision="rejected",
        decided_by="local_user",
        reason="The user rejected this otherwise valid take.",
    )
    assert service.view().state == "partial"
    assert service.view().catalog_revision == 0
    first_job = service.view().jobs[0]
    retried = service.retry(first_job["job_id"])
    assert retried.status == "succeeded"
    retry_artifact = next(
        item
        for item in service.view().artifacts
        if item["job_id"] == retried.job_id
    )
    service.decide_artifact(
        retry_artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="The replacement take passed human review.",
    )
    assert service.view().catalog_revision == 1


def test_manual_import_needs_input_cancel_and_retry_states_are_truthful(tmp_path):
    deterministic, _, planning, confirmation = _confirmed_planning(
        tmp_path,
        manual=True,
    )
    manual = ManualImportAdapter(
        lambda _token: None,
        clock=deterministic.clock,
    )
    service = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=AdapterRegistry((manual,)),
        store=MaterialProductionStore(tmp_path / "manual.production.json"),
        catalog=MaterialCatalogStore(
            tmp_path / "manual.catalog.json",
            media_root=tmp_path / "manual_media",
        ),
        staging_root=tmp_path / "manual_staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = service.prepare_request(
        request_id="production_request_manual_unconfigured",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    run = service.start(request)
    assert run["status"] == "running"
    job = service.view().jobs[0]
    assert job["status"] == "needs_input"
    cancelled = service.cancel(job["job_id"])
    assert cancelled.status == "cancelled"
    assert service.view().state == "cancelled"
    retried = service.retry(job["job_id"])
    assert retried.status == "needs_input"
    assert service.view().state == "running"
    assert service.view().catalog_revision == 0


def test_production_and_catalog_tamper_fail_closed(tmp_path):
    _, service, _, catalog, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_tamper",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    payload = json.loads(service.store.path.read_text())
    payload["events"][0]["record"]["message"] = "tampered"
    service.store.path.write_text(json.dumps(payload))
    with pytest.raises(MaterialProductionIntegrityError):
        service.store.load()

    _, service2, _, catalog2, confirmation2 = _orchestrator(
        tmp_path / "catalog_case"
    )
    request2 = service2.prepare_request(
        request_id="production_request_catalog_tamper",
        production_confirmation_id=confirmation2.confirmation_id,
        requested_by="local_user",
    )
    service2.start(request2)
    artifact = service2.view().artifacts[0]
    service2.decide_artifact(
        artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="Accept before tamper.",
    )
    data = json.loads(catalog2.path.read_text())
    data["entries"][0]["display_name"] = "tampered"
    catalog2.path.write_text(json.dumps(data))
    with pytest.raises(MaterialProductionIntegrityError):
        catalog2.load()


def test_only_accepted_catalog_uri_can_reach_timeline_through_atomic_skill(
    tmp_path,
    monkeypatch,
):
    _, service, _, catalog, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_atomic_catalog",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    artifact = service.view().artifacts[0]
    with pytest.raises(FileNotFoundError):
        VideoAddClipSkill().execute(
            {
                "source_path": "material://source_0000000000000000",
                "keep_audio": False,
            }
        )
    _, entry = service.decide_artifact(
        artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="Accept before atomic catalog resolution.",
    )
    project_file = tmp_path / "current_timeline.json"
    project_file.write_text(
        TimelineConfig(
            width=320,
            height=180,
            fps=24,
            tracks={
                "video": TrackConfig(id="video"),
                "audio": TrackConfig(id="audio"),
            },
        ).model_dump_json(),
        encoding="utf-8",
    )
    expected_catalog = project_file.with_name(
        "current_timeline.material-catalog.json"
    )
    shutil.copyfile(catalog.path, expected_catalog)
    shutil.copytree(catalog.media_root, tmp_path / "materials")
    monkeypatch.setattr(
        timeline_manager,
        "PROJECT_FILE",
        str(project_file),
    )
    result = VideoAddClipSkill().execute(
        {
            "source_path": entry.source_uri,
            "keep_audio": False,
        }
    )
    assert result["status"] == "success"
    timeline = TimelineConfig.model_validate_json(
        project_file.read_text(encoding="utf-8")
    )
    assert len(timeline.tracks["video"].clips) == 1
    assert "material://" not in timeline.tracks["video"].clips[0].source
    assert str(tmp_path / "materials") in (
        timeline.tracks["video"].clips[0].source
    )


def test_material_production_import_boundary_has_no_mutation_engines():
    forbidden_modules = {
        "core.timeline_manager",
        "core.timeline",
        "skills",
        "agent",
        "workflow",
    }
    for path in sorted((SRC / "material_production").glob("*.py")):
        imports = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not forbidden_modules.intersection(imports)
