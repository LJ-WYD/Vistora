"""Original O30 effect job lifecycle, candidate, retry and cache tests."""

from __future__ import annotations

import json
import sys
from itertools import count
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from effect_jobs import (  # noqa: E402
    EffectJobConcurrencyError,
    EffectJobCost,
    EffectJobError,
    EffectJobIntegrityError,
    EffectJobLifecycleService,
    EffectJobStore,
    EffectRedoScope,
)
from effect_workflow import (  # noqa: E402
    DeterministicEffectFixtureAdapter,
    EffectAdapterRegistry,
)
from tests.test_effect_capabilities import _confirmed  # noqa: E402
from tests.test_effect_workflow import NOW  # noqa: E402


def _ids():
    values = count(1)
    return lambda prefix: f"{prefix}_{next(values):016d}"


def _system(tmp_path):
    adapters = EffectAdapterRegistry((DeterministicEffectFixtureAdapter(),))
    plan, confirmation, _, executor = _confirmed(tmp_path, adapters=adapters)
    request = executor.prepare(
        execution_request_id="effect_execution_o30",
        confirmation_id=confirmation.confirmation_id,
        requested_by="local_user",
    )
    store = EffectJobStore(tmp_path / "project.effect-jobs.json")
    service = EffectJobLifecycleService(
        store=store,
        project_id=plan.intent.project_id,
        executor=executor,
        clock=lambda: NOW,
        id_factory=_ids(),
    )
    return plan, request, service, store


def test_o30_cost_redo_and_job_schemas_are_strict_frozen_and_truthful(tmp_path):
    _, request, service, _ = _system(tmp_path)
    with pytest.raises(ValidationError, match="Known effect cost"):
        EffectJobCost(status="known")
    with pytest.raises(ValidationError, match="cannot invent"):
        EffectJobCost(status="unknown", amount=2, currency="USD")
    with pytest.raises(ValidationError, match="positive duration"):
        EffectRedoScope(start_seconds=2, end_seconds=1, instruction="repair")
    state, ledger = service.begin(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_0001",
        expected_revision=0,
    )
    assert ledger.model_validate_json(ledger.model_dump_json()) == ledger
    with pytest.raises(ValidationError):
        state.progress = 0.5
    with pytest.raises(ValidationError):
        type(state).model_validate({**state.model_dump(), "surprise": True})


def test_success_progress_cost_candidate_cache_and_safe_view(tmp_path):
    _, request, service, _ = _system(tmp_path)
    state, ledger = service.begin(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_0001",
        expected_revision=0,
    )
    state, ledger = service.progress(
        state.attempt.attempt_id,
        progress=0.5,
        stage="provider_rendering",
        cost=EffectJobCost(status="known", amount=1.25, currency="USD"),
        expected_revision=ledger.revision,
    )
    state, ledger = service.complete(
        state.attempt.attempt_id,
        service.executor.execute(request),
        expected_revision=ledger.revision,
    )
    assert state.status == "succeeded"
    assert ledger.revision == 5
    view = service.view()
    assert view.state == "awaiting_review"
    assert view.candidates[0]["candidate_version"] == 1
    assert view.candidates[0]["cost"]["status"] == "known"
    assert view.candidates[0]["cost"]["amount"] == 1.25
    assert view.candidates[0]["cost"]["currency"] == "USD"
    assert "staging_relative_path" not in view.model_dump_json()
    cached, ledger = service.begin(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_0002",
        expected_revision=ledger.revision,
    )
    assert cached.status == "cached"
    assert cached.candidate_id == state.candidate_id
    assert len(service.view().candidates) == 1
    _, ledger = service.invalidate_cache(
        service.view().cache_entries[0]["cache_key"],
        reason="Source or adapter evidence changed.",
        expected_revision=ledger.revision,
    )
    assert service.view().cache_entries[0]["status"] == "invalidated"


def test_retry_partial_redo_candidate_versions_replace_and_rollback(tmp_path):
    _, request, service, _ = _system(tmp_path)
    first, ledger = service.submit(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_0001",
        expected_revision=0,
    )
    accepted, ledger = service.select(
        first.candidate_id,
        action="accept",
        actor_id="local_user",
        reason="Preferred initial candidate.",
        expected_revision=ledger.revision,
    )
    scope = EffectRedoScope(
        start_seconds=0.2,
        end_seconds=0.8,
        object_id="object_subject",
        instruction="Repair only the bounded subject edge.",
    )
    second, ledger = service.submit(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_redo",
        expected_revision=ledger.revision,
        reason="partial_redo",
        base_candidate_id=first.candidate_id,
        redo_scope=scope,
    )
    assert second.candidate_id != first.candidate_id
    assert [item["candidate_version"] for item in service.view().candidates] == [1, 2]
    _, ledger = service.select(
        second.candidate_id,
        action="replace",
        actor_id="local_user",
        reason="Bounded repair is better.",
        expected_revision=ledger.revision,
    )
    rollback, ledger = service.select(
        first.candidate_id,
        action="rollback",
        actor_id="local_user",
        reason="Restore the prior accepted candidate.",
        expected_revision=ledger.revision,
    )
    assert rollback.previous_candidate_id == second.candidate_id
    assert rollback.selected_candidate_id == first.candidate_id
    assert service.view().state == "selected"
    assert [item["review_status"] for item in service.view().candidates] == [
        "accepted", "superseded"
    ]


def test_failed_retry_cancel_restart_recovery_and_idempotency_drift(tmp_path):
    _, request, service, _ = _system(tmp_path)
    state, ledger = service.begin(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_failed",
        expected_revision=0,
    )
    blocked = service.executor.execute(request).model_copy(
        update={
            "status": "failed",
            "tasks": tuple(
                item.model_copy(update={
                    "status": "failed", "artifact": None,
                    "acceptance_checks": (), "fillback_status": "blocked",
                    "error_code": "effect_fixture_failure",
                    "message": "Fixture failure.",
                })
                for item in service.executor.execute(request).tasks
            ),
            "message": "Fixture failed.",
        }
    )
    failed, ledger = service.complete(
        state.attempt.attempt_id, blocked, expected_revision=ledger.revision
    )
    assert failed.status == "failed"
    retry, ledger = service.begin(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_retry",
        expected_revision=ledger.revision,
        reason="retry",
    )
    assert retry.attempt.attempt_number == 2
    cancelled, ledger = service.cancel(
        retry.attempt.attempt_id, expected_revision=ledger.revision
    )
    assert cancelled.status == "cancelled"
    running, ledger = service.begin(
        request,
        task_id=request.task_ids[1],
        idempotency_key="effect_idempotency_restart",
        expected_revision=ledger.revision,
    )
    ledger = service.recover_interrupted(expected_revision=ledger.revision)
    assert service.view().state == "recovery_required"
    with pytest.raises(EffectJobError, match="replayed with drift"):
        service.begin(
            request,
            task_id=request.task_ids[2],
            idempotency_key="effect_idempotency_restart",
            expected_revision=ledger.revision,
        )


def test_store_detects_concurrency_tamper_and_architecture_boundary(tmp_path):
    _, request, service, store = _system(tmp_path)
    _, ledger = service.begin(
        request,
        task_id=request.task_ids[0],
        idempotency_key="effect_idempotency_0001",
        expected_revision=0,
    )
    with pytest.raises(EffectJobConcurrencyError):
        with store.exclusive(project_id=service.project_id, expected_revision=0):
            pass
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["events"][0]["record"]["message"] = "tampered"
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectJobIntegrityError):
        store.load(project_id=service.project_id)
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "effect_jobs").glob("*.py")
    )
    assert "TimelineManager" not in source
    assert "AtomicExecutionGateway" not in source
    assert "from skills" not in source
