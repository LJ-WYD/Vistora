"""Original O28 high-value provider-neutral AI packaging capability tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contracts import MediaTimeRangeLocator, SourceEvidenceReference  # noqa: E402
from effect_workflow import (  # noqa: E402
    EFFECT_CAPABILITY_IDS,
    DeterministicEffectFixtureAdapter,
    EffectAdapterDescriptor,
    EffectAdapterRegistry,
    EffectAdapterResult,
    EffectArtifactCandidate,
    EffectCapabilityExecutionService,
    EffectExecutionError,
    EffectModelRequirement,
    EffectStyleReference,
    EffectTaskInput,
    ManualEffectImportAdapter,
    build_effect_adapter_registry,
    effect_capability_descriptors,
)
from tests.test_effect_workflow import NOW, _evidence, _plan, _service  # noqa: E402


def _multi_capability_plan():
    base = _plan()
    style_evidence = SourceEvidenceReference(
        evidence_id="evidence_style",
        material_id="source_1111111111111111",
        locator=MediaTimeRangeLocator(start_seconds=0, end_seconds=1),
        description="Observed color and texture reference.",
    )
    intent = base.intent.model_copy(
        update={
            "source_evidence": tuple(
                sorted((*base.intent.source_evidence, style_evidence), key=lambda item: item.evidence_id)
            )
        }
    )
    descriptors = {item.capability_id: item for item in effect_capability_descriptors()}
    tasks = []
    for capability_id in EFFECT_CAPABILITY_IDS:
        descriptor = descriptors[capability_id]
        task = base.tasks[0].model_copy(
            update={
                "task_id": f"effect_task_{capability_id}",
                "intent_id": intent.intent_id,
                "capability_id": capability_id,
                "style_references": (
                    EffectStyleReference(
                        style_reference_id="style_reference_observed",
                        evidence=style_evidence,
                        purpose="Preserve the observed look without inventing a source.",
                    ),
                ),
                "model_requirement": EffectModelRequirement(
                    capability_id=capability_id,
                    modality=descriptor.modality,
                    required_features=(f"feature_{capability_id}",),
                ),
                "output_role": descriptor.accepted_output_roles[0],
            }
        )
        tasks.append(task)
    return base.model_copy(
        update={
            "intent": intent,
            "tasks": tuple(sorted(tasks, key=lambda item: item.task_id)),
        }
    )


def _confirmed(tmp_path, *, adapters):
    plans, _, _ = _service(tmp_path)
    plan = _multi_capability_plan()
    review, ledger = plans.review(plan, expected_revision=0)
    confirmation, _ = plans.decide(
        review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=ledger.revision,
    )
    service = EffectCapabilityExecutionService(
        plans=plans,
        adapters=adapters,
        staging_root=tmp_path / "effect_staging",
    )
    return plan, confirmation, plans, service


def test_o28_registry_is_complete_deterministic_strict_and_provider_neutral():
    first = build_effect_adapter_registry()
    second = build_effect_adapter_registry()
    assert first.reference() == second.reference()
    assert tuple(item.capability_id for item in first.reference().capabilities) == EFFECT_CAPABILITY_IDS
    assert all(not item.configured for item in first.reference().adapters)
    assert all(item.execution_kind == "external_provider" for item in first.reference().adapters)
    assert all(item["status"] == "not_configured" for item in first.public_view()["capabilities"])
    assert "provider" in first.public_view()["message"].lower()
    with pytest.raises(ValidationError):
        EffectAdapterDescriptor.model_validate(
            {**first.reference().adapters[0].model_dump(), "unknown": True}
        )


def test_all_ten_high_value_capabilities_dispatch_only_from_exact_confirmation(tmp_path):
    adapters = EffectAdapterRegistry((DeterministicEffectFixtureAdapter(),))
    plan, confirmation, _, service = _confirmed(tmp_path, adapters=adapters)
    request = service.prepare(
        execution_request_id="effect_execution_all",
        confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    report = service.execute(request)
    assert report.status == "awaiting_human_review"
    assert report.timeline_mutated is False
    assert report.provider_calls_are_test_only is True
    assert {item.capability_id for item in report.tasks} == set(EFFECT_CAPABILITY_IDS)
    assert all(item.status == "ready_for_review" for item in report.tasks)
    assert all(item.fillback_status == "human_acceptance_required" for item in report.tasks)
    assert all(item.acceptance_checks for item in report.tasks)
    assert all(item.artifact.media_kind == "fixture_manifest" for item in report.tasks)
    assert len(list((tmp_path / "effect_staging" / "fixtures").glob("*.json"))) == len(plan.tasks)


def test_production_default_fails_truthfully_without_calling_a_provider(tmp_path):
    adapters = build_effect_adapter_registry()
    _, confirmation, _, service = _confirmed(tmp_path, adapters=adapters)
    request = service.prepare(
        execution_request_id="effect_execution_unconfigured",
        confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    report = service.execute(request)
    assert report.status == "blocked"
    assert report.provider_calls_are_test_only is False
    assert {item.status for item in report.tasks} == {"not_configured"}
    assert {item.error_code for item in report.tasks} == {"effect_provider_not_configured"}
    assert not (tmp_path / "effect_staging").exists()


def test_manual_import_uses_opaque_token_staging_and_never_exposes_absolute_path(tmp_path):
    source = tmp_path / "approved.png"
    source.write_bytes(b"deterministic-manual-effect")
    adapters = EffectAdapterRegistry(
        (ManualEffectImportAdapter(lambda token: source if token == "approved_token" else None),)
    )
    plan, confirmation, _, service = _confirmed(tmp_path, adapters=adapters)
    inputs = tuple(
        EffectTaskInput(task_id=task.task_id, input_token="approved_token")
        for task in plan.tasks
    )
    request = service.prepare(
        execution_request_id="effect_execution_manual",
        confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
        task_inputs=inputs,
    )
    report = service.execute(request)
    assert report.status == "awaiting_human_review"
    serialized = report.model_dump_json()
    assert str(tmp_path) not in serialized
    assert "approved.png" not in serialized
    assert all(item.artifact.staging_relative_path.startswith("manual/") for item in report.tasks)


def test_execution_rejects_registry_drift_task_omission_and_confirmation_replay(tmp_path):
    adapters = EffectAdapterRegistry((DeterministicEffectFixtureAdapter(),), revision=1)
    _, confirmation, _, service = _confirmed(tmp_path, adapters=adapters)
    request = service.prepare(
        execution_request_id="effect_execution_exact",
        confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    service.adapters = EffectAdapterRegistry((DeterministicEffectFixtureAdapter(),), revision=2)
    with pytest.raises(EffectExecutionError, match="stale or tampered"):
        service.execute(request)
    service.adapters = adapters
    with pytest.raises(EffectExecutionError, match="omits or invents"):
        service.execute(request.model_copy(update={"task_ids": request.task_ids[:-1]}))


def test_adapter_exceptions_and_mismatched_results_are_redacted(tmp_path):
    class UnsafeAdapter(DeterministicEffectFixtureAdapter):
        def submit(self, request, *, staging_root):
            raise RuntimeError(f"secret failure at {tmp_path}")

    adapters = EffectAdapterRegistry((UnsafeAdapter(),))
    _, confirmation, _, service = _confirmed(tmp_path, adapters=adapters)
    request = service.prepare(
        execution_request_id="effect_execution_unsafe",
        confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    report = service.execute(request)
    assert report.status == "failed"
    assert {item.error_code for item in report.tasks} == {"effect_adapter_failed"}
    assert str(tmp_path) not in report.model_dump_json()
    assert "secret failure" not in report.model_dump_json()


def test_artifact_paths_and_architecture_boundaries_fail_closed():
    with pytest.raises(ValidationError, match="escapes staging"):
        EffectArtifactCandidate(
            artifact_id="effect_artifact_bad",
            job_id="effect_job_bad",
            task_id="effect_task_bad",
            capability_id="object_removal",
            output_role="effect_layer",
            staging_relative_path="C:\\private\\artifact.mp4",
            content_digest="sha256:" + "1" * 64,
            media_kind="video",
        )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "effect_workflow").glob("*.py")
    )
    assert "TimelineManager" not in source
    assert "timeline_manager" not in source
    assert "AtomicExecutionGateway" not in source
    assert "from skills" not in source
