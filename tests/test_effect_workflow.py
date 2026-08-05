"""Original O27 provider-neutral AI packaging task-model tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contracts import (  # noqa: E402
    MediaTimeRangeLocator,
    PlanReference,
    SourceEvidenceReference,
)
from director import digest_json  # noqa: E402
from effect_workflow import (  # noqa: E402
    EffectIntent,
    EffectMaskReference,
    EffectModelRequirement,
    EffectObjectTarget,
    EffectParameter,
    EffectPlanConcurrencyError,
    EffectPlanError,
    EffectPlanIntegrityError,
    EffectPlanService,
    EffectPlanStore,
    EffectProductionPlan,
    EffectPromptSpecification,
    EffectStyleReference,
    EffectTask,
    EffectTimeRange,
    EffectTrackingReference,
)
from timeline_query import TimelineSnapshotReference  # noqa: E402

NOW = datetime(2026, 8, 5, 11, 0, tzinfo=timezone.utc)
MASK_PAYLOAD = {"mask_id": "mask_distraction"}
MASK_DIGEST = digest_json(MASK_PAYLOAD)


class Deterministic:
    def __init__(self):
        self.index = 0

    def clock(self):
        self.index += 1
        return NOW

    def identifier(self, prefix):
        self.index += 1
        return f"{prefix}_{self.index:04d}"


def _evidence(identity="evidence_subject"):
    return SourceEvidenceReference(
        evidence_id=identity,
        material_id="source_1111111111111111",
        locator=MediaTimeRangeLocator(start_seconds=1, end_seconds=3),
        description="Observed subject in the exact source range.",
    )


def _snapshot_ref(revision=2):
    return TimelineSnapshotReference(
        project_id="project_effects",
        revision=revision,
        snapshot_id=f"snapshot_effects_{revision}",
        timeline_digest="sha256:" + ("a" * 64),
    )


def _plan(*, version=1, revision=2, task_id="effect_task_hero"):
    evidence = _evidence()
    intent = EffectIntent(
        intent_id="effect_intent_hero",
        project_id="project_effects",
        director_plan_ref=PlanReference(
            plan_id="director_plan_effects",
            plan_version=3,
            plan_digest="sha256:" + ("b" * 64),
        ),
        rationale="The confirmed Director plan asks for a grounded cleanup pass.",
        desired_outcome="Remove one distracting object without changing the subject.",
        source_evidence=(evidence,),
        created_at=NOW,
    )
    task = EffectTask(
        task_id=task_id,
        intent_id=intent.intent_id,
        capability_id="object_removal",
        shot_id="shot_hero",
        track_id="track_video_main",
        clip_id="clip_video_main",
        timeline_range=EffectTimeRange(start_seconds=1, end_seconds=3),
        object_target=EffectObjectTarget(
            object_id="object_distraction",
            description="Small distracting sign behind the subject.",
            source_evidence_ids=(evidence.evidence_id,),
        ),
        mask_ref=EffectMaskReference(
            clip_id="clip_video_main",
            mask_id="mask_distraction",
            mask_digest=MASK_DIGEST,
        ),
        tracking_ref=EffectTrackingReference(
            analysis_id="tracking_subject_01",
            source_material_id=evidence.material_id,
            source_digest="sha256:" + ("d" * 64),
            analysis_digest="sha256:" + ("e" * 64),
            status="ready",
        ),
        prompt=EffectPromptSpecification(
            subject="Preserve the observed foreground subject.",
            scene="Reconstruct only the masked background region.",
            action="Remove the named distracting sign.",
            camera="Preserve the original locked framing.",
            lighting="Match the observed scene lighting.",
            style="Photorealistic continuity with the source evidence.",
            negative_constraints=("Do not alter the subject.",),
        ),
        model_requirement=EffectModelRequirement(
            capability_id="object_removal",
            modality="video",
            required_features=("mask_conditioning", "temporal_consistency"),
            preferred_model_class="video_inpainting",
        ),
        parameters=(EffectParameter(name="seed", value="42"),),
        acceptance_criteria=(
            "The removed object is absent throughout the bounded range.",
            "The preserved subject matches the source evidence.",
        ),
        output_role="effect_layer",
        cost_limit=2.5,
        time_limit_seconds=300,
    )
    return EffectProductionPlan(
        effect_plan_id="effect_plan_hero",
        plan_version=version,
        intent=intent,
        snapshot_ref=_snapshot_ref(revision),
        tasks=(task,),
        global_acceptance_criteria=(
            "No output is accepted without human review.",
        ),
        created_at=NOW,
    )


def _service(tmp_path, revision=2):
    deterministic = Deterministic()
    snapshot = SimpleNamespace(
        project_id="project_effects",
        revision=revision,
        snapshot_id=f"snapshot_effects_{revision}",
        timeline_digest="sha256:" + ("a" * 64),
        tracks=(
            SimpleNamespace(
                track_id="track_video_main",
                clips=(
                    SimpleNamespace(
                        clip_id="clip_video_main",
                        timeline_start_seconds=0,
                        timeline_end_seconds=4,
                        source=SimpleNamespace(
                            source_id="source_1111111111111111"
                        ),
                        masks=(
                            SimpleNamespace(
                                mask_id="mask_distraction",
                                model_dump=lambda mode: MASK_PAYLOAD,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    store = EffectPlanStore(tmp_path / "effects.json")
    return EffectPlanService(
        store=store,
        project_id="project_effects",
        snapshot_provider=lambda: snapshot,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    ), store, snapshot


def test_effect_contracts_are_strict_frozen_and_round_trip():
    plan = _plan()
    assert type(plan).model_validate_json(plan.model_dump_json()) == plan
    assert plan.digest() == _plan().digest()
    assert plan.tasks[0].tracking_ref.status == "ready"
    assert plan.tasks[0].model_requirement.provider_id is None
    with pytest.raises(ValidationError):
        type(plan).model_validate({**plan.model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        plan.tasks[0].timeline_range.start_seconds = 2


def test_effect_task_rejects_ambiguous_evidence_stale_tracking_and_paths():
    plan = _plan()
    task = plan.tasks[0]
    with pytest.raises(ValidationError, match="stale/failed"):
        EffectTask.model_validate({
            **task.model_dump(mode="python"),
            "tracking_ref": task.tracking_ref.model_copy(update={"status": "stale"}),
        })
    with pytest.raises(ValidationError, match="path or secret"):
        EffectPromptSpecification(
            subject=r"Read C:\Users\private\frame.png",
            scene="scene", action="action", camera="camera",
            lighting="lighting", style="style",
        )
    duplicate_style = EffectStyleReference(
        style_reference_id="style_subject",
        evidence=_evidence(),
        purpose="Reuse source as style.",
    )
    with pytest.raises(ValidationError, match="ambiguous"):
        EffectTask.model_validate({
            **task.model_dump(mode="python"),
            "style_references": (duplicate_style,),
        })


def test_review_confirmation_are_exact_separate_and_provider_free(tmp_path):
    service, _, _ = _service(tmp_path)
    plan = _plan()
    review, ledger = service.review(plan, expected_revision=0)
    assert ledger.revision == 1
    assert review.plan_digest == plan.digest()
    assert review.warnings == (
        "No production effect provider is configured in O27.",
    )
    assert service.view().provider_status == "not_configured"
    confirmation, ledger = service.decide(
        review.review_id,
        decision="confirmed",
        confirmed_by="local_user",
        expected_revision=ledger.revision,
    )
    assert ledger.revision == 2
    assert service.confirmed(confirmation.confirmation_id) == (
        plan,
        confirmation,
    )
    assert service.view().state == "confirmed"
    assert not any(
        token in service.view().model_dump_json().lower()
        for token in ("openai", "replicate", "runway", "api_key")
    )


def test_stale_duplicate_tamper_and_revision_drift_fail_closed(tmp_path):
    service, store, snapshot = _service(tmp_path)
    plan = _plan()
    review, ledger = service.review(plan, expected_revision=0)
    with pytest.raises(EffectPlanConcurrencyError):
        service.decide(
            review.review_id,
            decision="confirmed",
            confirmed_by="local_user",
            expected_revision=0,
        )
    snapshot.revision = 3
    snapshot.snapshot_id = "snapshot_effects_3"
    with pytest.raises(EffectPlanError, match="stale"):
        service.decide(
            review.review_id,
            decision="confirmed",
            confirmed_by="local_user",
            expected_revision=ledger.revision,
        )
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["events"][0]["plan"]["tasks"][0]["prompt"]["subject"] = "tampered"
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EffectPlanIntegrityError, match="corrupt or tampered"):
        store.load(project_id="project_effects")


def test_review_rejects_missing_target_range_and_stale_mask(tmp_path):
    service, _, _ = _service(tmp_path)
    plan = _plan()
    bad_range = plan.model_copy(update={
        "tasks": (
            plan.tasks[0].model_copy(update={
                "timeline_range": EffectTimeRange(start_seconds=3, end_seconds=5)
            }),
        )
    })
    with pytest.raises(EffectPlanError, match="range exceeds"):
        service.review(bad_range, expected_revision=0)
    stale_mask = plan.model_copy(update={
        "tasks": (
            plan.tasks[0].model_copy(update={
                "mask_ref": plan.tasks[0].mask_ref.model_copy(
                    update={"mask_digest": "sha256:" + ("f" * 64)}
                )
            }),
        )
    })
    with pytest.raises(EffectPlanError, match="mask reference"):
        service.review(stale_mask, expected_revision=0)


def test_plan_revision_requires_same_director_binding_and_real_changes(tmp_path):
    service, _, _ = _service(tmp_path)
    _, ledger = service.review(_plan(), expected_revision=0)
    revised = _plan(version=2, task_id="effect_task_revised")
    _, ledger = service.review(revised, expected_revision=ledger.revision)
    assert ledger.revision == 2
    with pytest.raises(EffectPlanError, match="version or Director binding"):
        service.review(_plan(version=4), expected_revision=2)


def test_effect_planning_boundary_has_no_provider_or_mutation_imports():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "effect_workflow").glob("*.py")
    ).lower()
    for forbidden in (
        "timeline_manager",
        "timelinerenderer",
        "atomicexecutiongateway",
        "requests.",
        "openai",
        "replicate",
        "runway",
    ):
        assert forbidden not in source
