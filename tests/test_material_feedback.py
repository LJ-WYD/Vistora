"""Focused tests for the O26 missing-material feedback loop."""

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

from director import (  # noqa: E402
    CreativeBriefReference,
    MaterialRequirementItem,
    MaterialRequirementsChange,
    MaterialRequirementsPlan,
    MaterialRequirementsProposal,
    MaterialRequirementsReview,
    MaterialShortfallItem,
    MaterialShortfallReport,
    RequirementConstraint,
    digest_json,
)
from material_feedback import (  # noqa: E402
    MaterialFeedbackError,
    MaterialFeedbackIntegrityError,
    MaterialFeedbackService,
    MaterialFeedbackStore,
)
from material_production import (  # noqa: E402
    MaterialCatalogDocument,
    MaterialCatalogEntry,
)
from timeline_query import TimelineSnapshotReference  # noqa: E402


NOW = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)
DIGEST_A = "sha256:" + ("a" * 64)


class Deterministic:
    def __init__(self):
        self.index = 0

    def clock(self):
        self.index += 1
        return NOW

    def identifier(self, prefix):
        self.index += 1
        return f"{prefix}_{self.index:04d}"


def _snapshot_ref(revision=4):
    return TimelineSnapshotReference(
        project_id="project_feedback",
        revision=revision,
        snapshot_id=f"snapshot_{revision}",
        timeline_digest="sha256:" + ("b" * 64),
    )


def _report(*, source_kind="plan_review", revision=4):
    values = {
        "report_id": "shortfall_review_01",
        "source_kind": source_kind,
        "project_id": "project_feedback",
        "snapshot_ref": _snapshot_ref(revision),
        "source_plan_id": "director_plan_01",
        "source_plan_version": 3,
        "source_plan_digest": DIGEST_A,
        "source_review_id": (
            "plan_review_01" if source_kind == "plan_review" else None
        ),
        "source_review_digest": (
            "sha256:" + ("c" * 64)
            if source_kind == "plan_review" else None
        ),
        "source_confirmation_id": (
            "confirmation_01" if source_kind == "editing_execution" else None
        ),
        "source_execution_id": (
            "execution_01" if source_kind == "editing_execution" else None
        ),
        "items": (
            MaterialShortfallItem(
                shortfall_item_id="shortfall_item_hero",
                requirement_item_id="material_need_hero",
                asset_type="video_shot",
                reason="The reviewed ending has no grounded hero shot.",
                narrative_position="Final proof beat",
                affected_entity_ids=("operation_outro",),
                evidence_gap="No accepted source covers the required action.",
                acceptance_criteria=("Show the authentic completed action.",),
                priority="required",
            ),
        ),
        "created_at": NOW,
    }
    shell = MaterialShortfallReport.model_construct(
        **values,
        schema_name="vistora.material-shortfall-report",
        schema_version="1.0.0",
        report_digest="sha256:" + ("0" * 64),
    )
    return MaterialShortfallReport(
        **values,
        report_digest=digest_json(
            shell.model_dump(mode="json", exclude={"report_digest"})
        ),
    )


def _proposal(report):
    unknown = RequirementConstraint(status="unknown")
    item = MaterialRequirementItem(
        item_id="material_need_hero",
        asset_type="video_shot",
        purpose="Supply the missing grounded final proof beat.",
        narrative_position="Final proof beat",
        duration_seconds=2,
        acceptance_criteria=("Show the authentic completed action.",),
        priority="required",
        budget_constraint=unknown,
        deadline_constraint=unknown,
    )
    plan = MaterialRequirementsPlan(
        plan_id="requirements_supplement_01",
        plan_version=1,
        plan_kind="supplemental_shortfall",
        brief_ref=CreativeBriefReference(
            session_id="session_feedback",
            brief_version=2,
            brief_digest="sha256:" + ("d" * 64),
        ),
        no_material_snapshot_ref=report.snapshot_ref,
        no_material_fact_digest=report.report_digest,
        created_at=NOW,
        rationale="Resolve only the explicitly reported gap.",
        items=(item,),
        global_acceptance_criteria=("All gaps are mapped to accepted material.",),
        shortfall_ref=report,
    )
    change = MaterialRequirementsChange(
        change_id="material_change_hero",
        change_type="added",
        item_id=item.item_id,
        after_digest=digest_json(item.model_dump(mode="json")),
        summary="Add the missing hero shot.",
    )
    review_values = {
        "review_id": "requirements_review_01",
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "plan_digest": plan.digest(),
        "brief_ref": plan.brief_ref,
        "snapshot_ref": report.snapshot_ref,
        "changes": (change,),
        "created_at": NOW,
    }
    shell = MaterialRequirementsReview.model_construct(
        **review_values,
        schema_name="vistora.material-requirements-review",
        schema_version="1.0.0",
        review_digest="sha256:" + ("0" * 64),
    )
    review = MaterialRequirementsReview(
        **review_values,
        review_digest=digest_json(
            shell.model_dump(mode="json", exclude={"review_digest"})
        ),
    )
    return MaterialRequirementsProposal(
        proposal_id="requirements_proposal_01",
        plan=plan,
        review=review,
        created_at=NOW,
    )


def _catalog():
    entry = MaterialCatalogEntry(
        material_id="source_1234567890abcdef",
        display_name="accepted-hero.mp4",
        media_kind="video",
        managed_relative_path="source_1234567890abcdef/accepted-hero.mp4",
        artifact_sha256="sha256:" + ("e" * 64),
        size_bytes=128,
        mime_type="video/mp4",
        container="mp4",
        video_codec="h264",
        duration_seconds=2,
        width=320,
        height=180,
        fps=24,
        has_audio=False,
        requirements_plan_id="requirements_supplement_01",
        requirement_item_id="material_need_hero",
        production_plan_id="production_plan_01",
        production_task_id="production_task_hero",
        production_run_id="production_run_01",
        production_job_id="production_job_01",
        adapter_id="manual_import_adapter",
        origin_kind="manual_import",
        license_status="user_asserted",
        cost_status="unknown",
        quality_validation_id="validation_hero",
        accepted_decision_id="artifact_decision_hero",
        registered_at=NOW,
    )
    return MaterialCatalogDocument(
        project_id="project_feedback",
        revision=1,
        entries=(entry,),
        integrity_digest=digest_json([entry.model_dump(mode="json")]),
    )


def _service(tmp_path, report):
    deterministic = Deterministic()
    snapshot = SimpleNamespace(
        project_id=report.project_id,
        revision=report.snapshot_ref.revision,
        snapshot_id=report.snapshot_ref.snapshot_id,
        timeline_digest=report.snapshot_ref.timeline_digest,
    )
    store = MaterialFeedbackStore(tmp_path / "feedback.json")
    service = MaterialFeedbackService(
        store=store,
        project_id=report.project_id,
        snapshot_provider=lambda: snapshot,
        clock=deterministic.clock,
        id_factory=deterministic.identifier,
    )
    return service, store, snapshot


def test_feedback_contract_round_trip_and_source_bindings():
    review = _report()
    execution = _report(source_kind="editing_execution")
    assert type(review).model_validate_json(review.model_dump_json()) == review
    assert execution.source_execution_id == "execution_01"
    with pytest.raises(ValidationError, match="exact review binding"):
        MaterialShortfallReport.model_validate({
            **review.model_dump(mode="python"),
            "source_review_id": None,
        })
    with pytest.raises(ValidationError, match="unique and ordered"):
        MaterialShortfallReport.model_validate({
            **review.model_dump(mode="python"),
            "items": (review.items[0], review.items[0]),
        })


def test_supplemental_plan_must_exactly_cover_shortfall():
    report = _report()
    proposal = _proposal(report)
    assert proposal.plan.plan_kind == "supplemental_shortfall"
    assert proposal.plan.no_material_fact_digest == report.report_digest
    with pytest.raises(ValidationError, match="exactly cover"):
        MaterialRequirementsPlan.model_validate({
            **proposal.plan.model_dump(mode="python"),
            "items": (
                proposal.plan.items[0].model_copy(update={"item_id": "wrong_need"}),
            ),
        })


def test_feedback_loop_is_append_only_exact_and_resolvable(tmp_path):
    report = _report()
    proposal = _proposal(report)
    service, store, _ = _service(tmp_path, report)
    ledger = service.record(report, expected_revision=0)
    assert service.record(report, expected_revision=0) == ledger
    assert service.latest_open_report() == report
    ledger = service.link_requirements(
        report.report_id, proposal, expected_revision=ledger.revision
    )
    assert service.link_requirements(
        report.report_id, proposal, expected_revision=0
    ) == ledger
    ledger = service.link_production(
        report.report_id,
        requirements_confirmation_id="requirements_confirmation_01",
        production_plan_id="production_plan_01",
        production_plan_digest="sha256:" + ("f" * 64),
        production_confirmation_id="production_confirmation_01",
        production_run_id="production_run_01",
        expected_revision=ledger.revision,
    )
    assert service.link_production(
        report.report_id,
        requirements_confirmation_id="requirements_confirmation_01",
        production_plan_id="production_plan_01",
        production_plan_digest="sha256:" + ("f" * 64),
        production_confirmation_id="production_confirmation_01",
        production_run_id="production_run_01",
        expected_revision=0,
    ) == ledger
    ledger = service.resolve(
        report.report_id,
        catalog=_catalog(),
        production_run_id="production_run_01",
        expected_revision=ledger.revision,
    )
    assert service.resolve(
        report.report_id,
        catalog=_catalog(),
        production_run_id="production_run_01",
        expected_revision=0,
    ) == ledger
    assert ledger.revision == 4
    assert service.latest_open_report() is None
    assert service.view().state == "resolved"
    assert type(ledger).model_validate_json(ledger.model_dump_json()) == ledger
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["events"][0]["report"]["items"][0]["reason"] = "tampered"
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MaterialFeedbackIntegrityError, match="corrupt or tampered"):
        store.load(project_id=report.project_id)


def test_feedback_rejects_stale_cross_plan_and_incomplete_resolution(tmp_path):
    report = _report()
    service, _, snapshot = _service(tmp_path, report)
    snapshot.revision += 1
    with pytest.raises(MaterialFeedbackError, match="stale"):
        service.record(report, expected_revision=0)
    current = _report(revision=snapshot.revision)
    snapshot.snapshot_id = current.snapshot_ref.snapshot_id
    service.record(current, expected_revision=0)
    wrong = _proposal(current)
    wrong = wrong.model_copy(
        update={
            "plan": wrong.plan.model_copy(
                update={"shortfall_ref": _report(source_kind="editing_execution")}
            )
        }
    )
    with pytest.raises(MaterialFeedbackError, match="binding drifted"):
        service.link_requirements(current.report_id, wrong, expected_revision=1)


def test_feedback_payloads_never_expose_filesystem_paths(tmp_path):
    report = _report()
    service, _, _ = _service(tmp_path, report)
    service.record(report, expected_revision=0)
    encoded = service.view().model_dump_json()
    assert "C:\\" not in encoded
    assert "file://" not in encoded
    assert str(tmp_path).replace("\\", "/") not in encoded.replace("\\", "/")
