import ast
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
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
    ArtifactValidation,
    DeterministicLocalMediaAdapter,
    DeterministicLocalVideoAdapter,
    ManualImportAdapter,
    MaterialProductionAgent,
    MaterialIngestError,
    MaterialIngestPipeline,
    MaterialDerivative,
    MaterialCatalogStore,
    MaterialProductionIntegrityError,
    MaterialProductionOrchestrator,
    MaterialProductionStore,
    ProductionTaskInput,
    PRODUCTION_CAPABILITY_KINDS,
    UserMaterialRequestAdapter,
    build_creation_capability_reference,
    build_material_production_registry,
)
import material_production.store as production_store_module  # noqa: E402
from core import timeline_manager  # noqa: E402
from director import digest_json  # noqa: E402
from core.timeline import TimelineConfig, TrackConfig  # noqa: E402
from skills.video_add_clip import VideoAddClipSkill  # noqa: E402
from tests.test_creation_planning import (  # noqa: E402
    Adapter,
    planning as planning_fixture,
)


def _production_draft(*, two_tasks=False, manual=False, dependent=False):
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
            (
                task(
                    "task_fixture_secondary",
                    "requirement_voice",
                    ("task_fixture_primary",) if dependent else (),
                ),
            )
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


def _confirmed_planning(
    tmp_path,
    *,
    two_tasks=False,
    manual=False,
    dependent=False,
):
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
                dependent=dependent,
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
    dependent=False,
):
    deterministic, _, planning, confirmation = _confirmed_planning(
        tmp_path,
        two_tasks=two_tasks,
        dependent=dependent,
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


def test_catalog_acceptance_builds_proxy_transcode_analysis_tags_and_quality(tmp_path):
    _, service, _, catalog, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_o24_ingest",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    artifact = service.view().artifacts[0]
    _, entry = service.decide_artifact(
        artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="Accept after complete local ingest checks.",
    )
    assert [item.role for item in entry.derivatives] == ["normalized", "proxy"]
    assert entry.analysis.media_kind == "video"
    assert entry.analysis.orientation == "landscape"
    assert entry.analysis.width == 320
    assert entry.analysis.height == 180
    assert entry.quality_report.overall_status == "passed"
    assert entry.quality_report.full_decode_passed is True
    assert {item.check_id for item in entry.quality_report.checks} >= {
        "check_full_decode",
        "check_hash_binding",
        "check_required_stream",
        "check_specification",
    }
    assert {(item.namespace, item.name, item.value) for item in entry.tags} >= {
        ("technical", "media_kind", "video"),
        ("technical", "orientation", "landscape"),
        ("workflow", "production_method", "generate"),
    }
    for role in ("normalized", "proxy"):
        derivative = catalog.resolve_derivative(entry.material_id, role)
        assert derivative is not None and derivative.is_file()
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,width,height", "-of", "json",
                str(derivative),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert any(
            item["codec_type"] == "video"
            for item in json.loads(probe.stdout)["streams"]
        )
    view = service.view().model_dump_json()
    assert "material_analysis_" in view
    assert '"overall_status":"passed"' in view
    assert "managed_relative_path" not in view
    assert str(tmp_path) not in view
    assert type(entry).model_validate_json(entry.model_dump_json()) == entry


def test_o24_derivative_failure_does_not_accept_or_catalog(tmp_path, monkeypatch):
    _, service, _, catalog, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_o24_failure",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    artifact = service.view().artifacts[0]

    def fail_derivatives(*_args, **_kwargs):
        raise RuntimeError("synthetic derivative failure")

    monkeypatch.setattr(service.ingest, "_create_derivatives", fail_derivatives)
    with pytest.raises(MaterialIngestError, match="proxy/transcode"):
        service.decide_artifact(
            artifact["artifact_id"],
            decision="accepted",
            decided_by="local_user",
            reason="This must fail before acceptance.",
        )
    assert catalog.load(project_id=service.project_id).revision == 0
    assert service.view().artifacts[0]["decision"] is None
    assert not catalog.media_root.exists()


def test_o24_catalog_manifest_failure_removes_original_and_derivatives(
    tmp_path,
    monkeypatch,
):
    _, service, _, catalog, confirmation = _orchestrator(tmp_path / "source")
    request = service.prepare_request(
        request_id="production_request_o24_atomic",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    artifact = service.view().artifacts[0]
    _, entry = service.decide_artifact(
        artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="Prepare verified files for the atomic publication test.",
    )
    source = catalog.resolve_uri(entry.source_uri)
    derivatives = {
        item.role: catalog.resolve_derivative(entry.material_id, item.role)
        for item in entry.derivatives
    }
    replacement_id = "source_fedcba9876543210"
    replacement_derivatives = tuple(
        item.model_copy(
            update={
                "managed_relative_path": (
                    f"{replacement_id}/{replacement_id}.{item.role}"
                    f"{Path(item.managed_relative_path).suffix}"
                )
            }
        )
        for item in entry.derivatives
    )
    replacement = entry.model_copy(
        update={
            "material_id": replacement_id,
            "managed_relative_path": (
                f"{replacement_id}/{replacement_id}{source.suffix}"
            ),
            "derivatives": replacement_derivatives,
        }
    )
    target = MaterialCatalogStore(
        tmp_path / "failed.catalog.json",
        media_root=tmp_path / "failed_media",
    )

    def fail_manifest(*_args, **_kwargs):
        raise OSError("synthetic manifest failure")

    monkeypatch.setattr(production_store_module, "_atomic_json", fail_manifest)
    with pytest.raises(OSError, match="manifest failure"):
        target.register(
            target.load(project_id=service.project_id),
            entry=replacement,
            staged_path=source,
            derivative_sources={
                item.managed_relative_path: derivatives[item.role]
                for item in replacement_derivatives
            },
        )
    assert not target.path.exists()
    assert not any(item.is_file() for item in target.media_root.rglob("*"))


def test_legacy_catalog_migrates_in_memory_without_fabricated_ingest_metadata(tmp_path):
    _, service, _, catalog, confirmation = _orchestrator(tmp_path)
    request = service.prepare_request(
        request_id="production_request_o24_legacy",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.start(request)
    artifact = service.view().artifacts[0]
    _, entry = service.decide_artifact(
        artifact["artifact_id"],
        decision="accepted",
        decided_by="local_user",
        reason="Create a catalog entry before legacy projection.",
    )
    payload = json.loads(catalog.path.read_text(encoding="utf-8"))
    for item in payload["entries"]:
        item.pop("derivatives")
        item.pop("analysis")
        item.pop("tags")
        item.pop("quality_report")
    payload["integrity_digest"] = digest_json(payload["entries"])
    catalog.path.write_text(json.dumps(payload), encoding="utf-8")
    migrated = catalog.load(project_id=service.project_id)
    assert migrated.entries[0].material_id == entry.material_id
    assert migrated.entries[0].derivatives == ()
    assert migrated.entries[0].analysis is None
    assert migrated.entries[0].tags == ()
    assert migrated.entries[0].quality_report is None
    assert catalog.resolve_uri(entry.source_uri).is_file()


def test_o24_derivative_contract_rejects_managed_path_escape():
    with pytest.raises(ValidationError, match="managed and relative"):
        MaterialDerivative(
            derivative_id="derivative_escape",
            role="proxy",
            managed_relative_path="../outside.mp4",
            sha256="sha256:" + "1" * 64,
            size_bytes=1,
            mime_type="video/mp4",
        )


def test_o24_unified_ingest_handles_image_and_audio_without_modifying_sources(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    image = staging / "source.png"
    audio = staging / "source.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x305070:s=320x180:r=1", "-frames:v", "1", str(image),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=2", "-c:a",
            "pcm_s16le", str(audio),
        ],
        check=True,
    )
    unknown = ProductionEstimate(
        status="unknown",
        rationale="No provider cost is associated with this fixture.",
    )
    prompt = {
        "subject": "Synthetic fixture.",
        "scene": "Local test.",
        "camera": "Static.",
        "action": "None.",
        "lighting": "Uniform.",
        "style": "Deterministic.",
    }

    def bundle(path, media_kind):
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        is_image = media_kind == "image"
        task = MaterialProductionTask(
            task_id=f"task_{media_kind}_ingest",
            requirement_item_id="requirement_hero",
            title=f"Ingest {media_kind}",
            purpose="Validate unified ingest behavior.",
            production_method="generate",
            status="planned",
            capability_ids=(f"{media_kind}_generation",),
            prompt_spec=prompt,
            duration_seconds=None if is_image else 2.0,
            width=320 if is_image else None,
            height=180 if is_image else None,
            aspect_ratio="16:9" if is_image else None,
            batch_id="batch_o24_ingest",
            cost_estimate=unknown,
            time_estimate=unknown,
            quality_gates=("Full decode succeeds.",),
            retry_strategy=("Retry after review.",),
            alternative_strategy="Use manual import.",
            delivery=DeliveryFileSpecification(
                media_kind=media_kind,
                container_or_extension=path.suffix[1:],
                mime_type="image/png" if is_image else "audio/wav",
                filename_pattern=f"{media_kind}.{{attempt}}{path.suffix}",
            ),
        )
        validation = ArtifactValidation(
            validation_id=f"validation_{media_kind}",
            artifact_id=f"artifact_{media_kind}",
            run_id="run_o24_ingest",
            job_id=f"job_{media_kind}",
            task_id=task.task_id,
            requirement_item_id=task.requirement_item_id,
            passed=True,
            sha256=digest,
            size_bytes=path.stat().st_size,
            mime_type=task.delivery.mime_type,
            width=320 if is_image else None,
            height=180 if is_image else None,
            duration_seconds=None if is_image else 2.0,
            has_audio=not is_image,
            validated_at=datetime.now(timezone.utc),
        )
        return MaterialIngestPipeline(staging).process(
            staged_path=path,
            validation=validation,
            task=task,
            material_id=f"source_{media_kind}0000000000"[:23],
        )

    original_image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    original_audio_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
    image_bundle = bundle(image, "image")
    audio_bundle = bundle(audio, "audio")
    assert [item.role for item in image_bundle.derivatives] == ["normalized", "proxy"]
    assert image_bundle.analysis.orientation == "landscape"
    assert image_bundle.analysis.duration_seconds is None
    assert [item.role for item in audio_bundle.derivatives] == ["normalized", "proxy"]
    assert audio_bundle.analysis.audio_sample_rate == 48000
    assert audio_bundle.analysis.audio_channels == 1
    assert audio_bundle.analysis.orientation == "not_applicable"
    assert hashlib.sha256(image.read_bytes()).hexdigest() == original_image_hash
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == original_audio_hash


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


def test_async_dependency_is_deferred_then_submitted_after_predecessor_succeeds(
    tmp_path,
):
    deterministic, _, planning, confirmation = _confirmed_planning(
        tmp_path,
        two_tasks=True,
        dependent=True,
    )

    class AsyncAdapter(DeterministicLocalVideoAdapter):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.pending = set()

        def submit(self, request, *, staging_root):
            if request.job_id not in self.pending:
                self.pending.add(request.job_id)
                return AdapterJobUpdate(
                    job_id=request.job_id,
                    adapter_id=self.capability().adapter_id,
                    provider_opaque_ref=f"async_{request.job_id}",
                    status="submitted",
                    progress=0.1,
                    message="The synthetic asynchronous job was submitted.",
                    updated_at=self.clock(),
                )
            return super().submit(request, staging_root=staging_root)

        def poll(self, request, *, provider_opaque_ref, staging_root):
            return super().submit(request, staging_root=staging_root)

    adapter = AsyncAdapter(clock=deterministic.clock)
    service = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=AdapterRegistry((adapter,)),
        store=MaterialProductionStore(tmp_path / "async.production.json"),
        catalog=MaterialCatalogStore(
            tmp_path / "async.catalog.json",
            media_root=tmp_path / "async_media",
        ),
        staging_root=tmp_path / "async_staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = service.prepare_request(
        request_id="production_request_async_dependency",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    assert service.start(request)["status"] == "running"
    by_task = {item["task_id"]: item for item in service.view().jobs}
    assert by_task["task_fixture_primary"]["status"] == "submitted"
    assert by_task["task_fixture_secondary"]["status"] == "rate_limited"
    assert by_task["task_fixture_secondary"]["error_code"] == (
        "production_dependency_pending"
    )

    assert service.poll(by_task["task_fixture_primary"]["run_id"])["status"] == (
        "running"
    )
    by_task = {item["task_id"]: item for item in service.view().jobs}
    assert by_task["task_fixture_primary"]["status"] == "succeeded"
    assert by_task["task_fixture_secondary"]["status"] == "submitted"
    assert service.poll(by_task["task_fixture_primary"]["run_id"])["status"] == (
        "awaiting_review"
    )


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


def test_default_production_capabilities_are_complete_and_truthful():
    first = build_material_production_registry()
    second = build_material_production_registry()
    assert first.reference() == second.reference()
    projected = build_creation_capability_reference(first)
    expected = set(PRODUCTION_CAPABILITY_KINDS)
    assert {item.capability_id for item in projected.capabilities} == expected
    by_id = {item.capability_id: item for item in projected.capabilities}
    assert by_id["user_material_request"].availability == "available"
    assert by_id["manual_import"].availability == "unconfigured"
    for capability_id in {
        "image_generation",
        "video_generation",
        "voice_synthesis",
        "music_generation",
        "asset_search",
        "local_capture",
    }:
        assert by_id[capability_id].availability == "unconfigured"
        assert "No " in by_id[capability_id].limitation
    serialized = first.reference().model_dump_json()
    assert "api_key" not in serialized.lower()
    assert ":\\" not in serialized


def _confirmed_o23_plan(tmp_path):
    deterministic, _, material_confirmation, planning = (
        planning_fixture.__wrapped__(tmp_path)
    )
    unknown = ProductionEstimate(
        status="unknown",
        rationale="No external provider or billable estimate is configured.",
    )
    prompt = {
        "subject": "A deterministic synthetic requirement fixture.",
        "scene": "A local test-only scene.",
        "camera": "Locked frame or neutral audio perspective.",
        "action": "Produce only the declared fixture.",
        "lighting": "Uniform synthetic lighting.",
        "style": "Deterministic regression fixture.",
        "negative_constraints": ["No external provider call."],
    }

    def task(
        task_id,
        capability_id,
        method,
        media_kind,
        extension,
        mime_type,
        *,
        requirement_id="requirement_hero",
    ):
        generated = method == "generate"
        visual = media_kind in {"video", "image"}
        timed = media_kind in {"video", "audio"}
        return MaterialProductionTask(
            task_id=task_id,
            requirement_item_id=requirement_id,
            title=f"Execute {capability_id}",
            purpose="Exercise the exact confirmed provider-neutral capability.",
            production_method=method,
            status="planned",
            capability_ids=(capability_id,),
            prompt_spec=prompt if generated else None,
            duration_seconds=2.0 if timed else None,
            width=320 if visual else None,
            height=180 if visual else None,
            aspect_ratio="16:9" if visual else None,
            fps=24.0 if media_kind == "video" else None,
            seed=23 if generated else None,
            batch_id="production_batch_o23",
            cost_estimate=unknown,
            time_estimate=unknown,
            quality_gates=("Artifact remains locally reproducible.",),
            retry_strategy=("Retry only after explicit review.",),
            alternative_strategy="Request a validated user import.",
            delivery=DeliveryFileSpecification(
                media_kind=media_kind,
                container_or_extension=extension,
                mime_type=mime_type,
                filename_pattern=f"{task_id}_{{attempt}}.{extension}",
            ),
        )

    tasks = (
        task("task_ai_image", "image_generation", "generate", "image", "png", "image/png"),
        task("task_ai_video", "video_generation", "generate", "video", "mp4", "video/mp4"),
        task("task_ai_voice", "voice_synthesis", "generate", "audio", "wav", "audio/wav", requirement_id="requirement_voice"),
        task("task_ai_music", "music_generation", "generate", "audio", "wav", "audio/wav", requirement_id="requirement_voice"),
        task("task_asset_search", "asset_search", "library_search", "image", "png", "image/png"),
        task("task_local_capture", "local_capture", "capture", "video", "mp4", "video/mp4"),
        task("task_user_request", "user_material_request", "manual", "video", "mp4", "video/mp4"),
    )
    capabilities = tuple(
        CapabilityRequirement(
            capability_id=capability_id,
            capability_kind=PRODUCTION_CAPABILITY_KINDS[capability_id],
            availability="available",
        )
        for capability_id in sorted(
            {item.capability_ids[0] for item in tasks}
        )
    )
    planning_registry = CapabilityRegistryReference.create(
        registry_id="o23_test_capabilities",
        registry_revision=1,
        capabilities=capabilities,
    )

    def output(request):
        return CreationPlanningReasoningOutput(
            outcome="proposal",
            message="The bounded O23 production plan is ready.",
            material_confirmation_ref=request.material_confirmation_ref,
            capability_registry_ref=request.capability_registry_ref,
            plan_draft=MaterialProductionPlanDraft(
                rationale="Exercise every original O23 production task kind.",
                tasks=tasks,
                delivery_summary=("Synthetic fixtures require human acceptance.",),
                global_quality_gates=("No task invokes an online provider.",),
                limitations=("All configured adapters are deterministic test doubles.",),
            ),
        ).model_dump(mode="json")

    agent = CreationPlanningAgent(
        adapter=Adapter([output]),
        service=planning,
        capability_provider=lambda: planning_registry,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    proposal = agent.plan(
        agent.prepare_request(
            request_id="creation_request_o23",
            material_confirmation_id=material_confirmation.confirmation_id,
        )
    ).proposal
    confirmation, _ = planning.decide(
        proposal.review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=1,
    )
    return deterministic, planning, confirmation


def test_material_production_agent_executes_all_o23_task_kinds_without_online_provider(
    tmp_path,
):
    deterministic, planning, confirmation = _confirmed_o23_plan(tmp_path)
    adapter_specs = (
        ("fake_image", "image_generation", "image"),
        ("fake_video", "video_generation", "video"),
        ("fake_voice", "voice_synthesis", "audio"),
        ("fake_music", "music_generation", "audio"),
        ("fake_search", "asset_search", "image"),
        ("fake_capture", "local_capture", "video"),
    )
    adapters = AdapterRegistry(
        (
            *tuple(
                DeterministicLocalMediaAdapter(
                    adapter_id=adapter_id,
                    capability_id=capability_id,
                    media_kind=media_kind,
                    clock=deterministic.clock,
                )
                for adapter_id, capability_id, media_kind in adapter_specs
            ),
            UserMaterialRequestAdapter(clock=deterministic.clock),
        ),
        registry_id="o23_test_adapters",
        registry_revision=1,
    )
    orchestrator = MaterialProductionOrchestrator(
        creation_planning=planning,
        adapters=adapters,
        store=MaterialProductionStore(tmp_path / "o23.production.json"),
        catalog=MaterialCatalogStore(
            tmp_path / "o23.catalog.json",
            media_root=tmp_path / "o23_catalog_media",
        ),
        staging_root=tmp_path / "o23_staging",
        project_id="project_creation_planning",
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    production_agent = MaterialProductionAgent(
        orchestrator,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    request = production_agent.prepare_execution(
        agent_request_id="production_agent_request_o23",
        production_request_id="production_request_o23",
        production_confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    assert request.model_validate_json(request.model_dump_json()) == request
    report = production_agent.execute(request)
    assert report.disposition == "executed"
    assert report.status == "running"
    assert report.model_validate_json(report.model_dump_json()) == report
    view = orchestrator.view()
    assert len(view.jobs) == 7
    assert len(view.artifacts) == 6
    assert all(item["passed"] for item in view.artifacts)
    assert view.catalog_revision == 0
    user_job = next(
        item for item in view.jobs if item["task_id"] == "task_user_request"
    )
    assert user_job["status"] == "needs_input"
    assert "No media was created" in user_job["message"]
    serialized = view.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "provider_opaque_ref" not in serialized

    drifted = request.model_copy(
        update={
            "run_request": request.run_request.model_copy(
                update={
                    "adapter_registry_ref": request.run_request.adapter_registry_ref.model_copy(
                        update={"registry_revision": 2}
                    )
                }
            )
        }
    )
    rejected = production_agent.execute(drifted)
    assert rejected.disposition == "rejected"
    assert rejected.error.code == "adapter_registry_stale"
    assert len(orchestrator.view().jobs) == 7


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
                imports.append(("." * node.level) + (node.module or ""))
        assert not forbidden_modules.intersection(imports)
