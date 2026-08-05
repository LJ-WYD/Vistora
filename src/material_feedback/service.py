"""Constrained application service for the missing-material feedback loop."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from director import MaterialRequirementsProposal, MaterialShortfallReport, digest_json
from material_production import MaterialCatalogDocument
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService

from .models import (
    FeedbackProductionLink,
    FeedbackResolution,
    MaterialFeedbackView,
    SupplementalRequirementsLink,
)
from .store import MaterialFeedbackError, MaterialFeedbackStore


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class MaterialFeedbackService:
    def __init__(
        self,
        *,
        store: MaterialFeedbackStore,
        project_id: str,
        snapshot_provider=TimelineSnapshotService.snapshot_current,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
    ) -> None:
        self.store = store
        self.project_id = project_id
        self.snapshot_provider = snapshot_provider
        self.clock = clock
        self.id_factory = id_factory

    def _current_ref(self):
        return TimelineSnapshotReference.from_snapshot(self.snapshot_provider())

    def record(self, report: MaterialShortfallReport, *, expected_revision: int):
        if report.project_id != self.project_id:
            raise MaterialFeedbackError("Material shortfall crosses project")
        if report.snapshot_ref != self._current_ref():
            raise MaterialFeedbackError("Material shortfall snapshot is stale")
        current = self.store.load(project_id=self.project_id)
        known = [
            event.report
            for event in current.events
            if event.report is not None and event.report.report_id == report.report_id
        ]
        if known:
            if known == [report]:
                return current
            raise MaterialFeedbackError("Material shortfall ID was replayed with drift")
        with self.store.exclusive(
            project_id=self.project_id, expected_revision=expected_revision
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("feedback_event"),
                event_type="shortfall_recorded",
                report=report,
                recorded_at=self.clock(),
            )

    def link_requirements(
        self,
        report_id: str,
        proposal: MaterialRequirementsProposal,
        *,
        expected_revision: int,
    ):
        report = self._report(report_id)
        plan = proposal.plan
        if (
            plan.plan_kind != "supplemental_shortfall"
            or plan.shortfall_ref != report
            or proposal.review.snapshot_ref != report.snapshot_ref
        ):
            raise MaterialFeedbackError("Supplemental requirements binding drifted")
        link = SupplementalRequirementsLink(
            report_id=report.report_id,
            report_digest=report.report_digest,
            proposal_id=proposal.proposal_id,
            requirements_plan_id=plan.plan_id,
            requirements_plan_version=plan.plan_version,
            requirements_plan_digest=plan.digest(),
            requirements_review_id=proposal.review.review_id,
            requirements_review_digest=proposal.review.review_digest,
            requirement_item_ids=tuple(sorted(item.item_id for item in plan.items)),
            recorded_at=self.clock(),
        )
        current = self.store.load(project_id=self.project_id)
        known = [
            event.requirements_link
            for event in current.events
            if event.requirements_link is not None
            and event.requirements_link.report_id == report_id
        ]
        if known:
            comparable = known[0].model_copy(update={"recorded_at": link.recorded_at})
            if len(known) == 1 and comparable == link:
                return current
            raise MaterialFeedbackError("Requirements link was replayed with drift")
        with self.store.exclusive(
            project_id=self.project_id, expected_revision=expected_revision
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("feedback_event"),
                event_type="requirements_linked",
                requirements_link=link,
                recorded_at=self.clock(),
            )

    def link_production(
        self,
        report_id: str,
        *,
        requirements_confirmation_id: str,
        production_plan_id: str,
        production_plan_digest: str,
        production_confirmation_id: str,
        production_run_id: str,
        expected_revision: int,
    ):
        self._report(report_id)
        link = FeedbackProductionLink(
            report_id=report_id,
            requirements_confirmation_id=requirements_confirmation_id,
            production_plan_id=production_plan_id,
            production_plan_digest=production_plan_digest,
            production_confirmation_id=production_confirmation_id,
            production_run_id=production_run_id,
            recorded_at=self.clock(),
        )
        current = self.store.load(project_id=self.project_id)
        known = [
            event.production_link
            for event in current.events
            if event.production_link is not None
            and event.production_link.report_id == report_id
        ]
        if known:
            comparable = known[0].model_copy(update={"recorded_at": link.recorded_at})
            if len(known) == 1 and comparable == link:
                return current
            raise MaterialFeedbackError("Production link was replayed with drift")
        with self.store.exclusive(
            project_id=self.project_id, expected_revision=expected_revision
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("feedback_event"),
                event_type="production_linked",
                production_link=link,
                recorded_at=self.clock(),
            )

    def resolve(
        self,
        report_id: str,
        *,
        catalog: MaterialCatalogDocument,
        production_run_id: str,
        expected_revision: int,
    ):
        report = self._report(report_id)
        if catalog.project_id != self.project_id:
            raise MaterialFeedbackError("Material catalog crosses project")
        ledger = self.store.load(project_id=self.project_id)
        resolved = [
            event.resolution
            for event in ledger.events
            if event.resolution is not None
            and event.resolution.report_id == report_id
        ]
        if resolved:
            if (
                len(resolved) == 1
                and resolved[0].production_run_id == production_run_id
            ):
                return ledger
            raise MaterialFeedbackError("Feedback resolution was replayed with drift")
        requirements_links = [
            event.requirements_link
            for event in ledger.events
            if event.requirements_link is not None
            and event.requirements_link.report_id == report_id
        ]
        production_links = [
            event.production_link
            for event in ledger.events
            if event.production_link is not None
            and event.production_link.report_id == report_id
        ]
        if len(requirements_links) != 1 or len(production_links) != 1:
            raise MaterialFeedbackError("Feedback production chain is incomplete")
        requirements_link = requirements_links[0]
        production_link = production_links[0]
        if production_link.production_run_id != production_run_id:
            raise MaterialFeedbackError("Feedback production run binding drifted")
        entries = {
            item.requirement_item_id: item
            for item in catalog.entries
            if item.production_run_id == production_run_id
        }
        required = {item.requirement_item_id for item in report.items}
        if set(entries) != required:
            raise MaterialFeedbackError(
                "Accepted catalog material does not exactly resolve shortfall"
            )
        if any(
            item.requirements_plan_id
            != requirements_link.requirements_plan_id
            or item.production_plan_id != production_link.production_plan_id
            for item in entries.values()
        ):
            raise MaterialFeedbackError("Accepted material provenance drifted")
        mapping = {
            requirement_id: entries[requirement_id].material_id
            for requirement_id in sorted(entries)
        }
        values = {
            "resolution_id": self.id_factory("feedback_resolution"),
            "report_id": report_id,
            "production_run_id": production_run_id,
            "requirement_materials": mapping,
            "resolved_at": self.clock(),
        }
        shell = FeedbackResolution.model_construct(
            **values, schema_name="vistora.material-feedback.resolution",
            schema_version="1.0.0", resolution_digest="sha256:" + ("0" * 64)
        )
        resolution = FeedbackResolution(
            **values,
            resolution_digest=digest_json(
                shell.model_dump(mode="json", exclude={"resolution_digest"})
            ),
        )
        with self.store.exclusive(
            project_id=self.project_id, expected_revision=expected_revision
        ) as ledger:
            return self.store.append(
                ledger,
                event_id=self.id_factory("feedback_event"),
                event_type="resolved",
                resolution=resolution,
                recorded_at=self.clock(),
            )

    def _report(self, report_id: str):
        ledger = self.store.load(project_id=self.project_id)
        reports = [
            event.report for event in ledger.events
            if event.report is not None and event.report.report_id == report_id
        ]
        if len(reports) != 1:
            raise MaterialFeedbackError("Unknown material shortfall report")
        return reports[0]

    def latest_open_report(self):
        ledger = self.store.load(project_id=self.project_id)
        resolved = {
            event.resolution.report_id
            for event in ledger.events
            if event.resolution is not None
        }
        for event in reversed(ledger.events):
            if event.report is not None and event.report.report_id not in resolved:
                if event.report.snapshot_ref != self._current_ref():
                    return None
                return event.report
        return None

    def view(self):
        ledger = self.store.load(project_id=self.project_id)
        open_report = self.latest_open_report()
        latest_by_report: dict[str, str] = {}
        for event in ledger.events:
            payload = event.report or event.requirements_link or event.production_link or event.resolution
            assert payload is not None
            latest_by_report[payload.report_id] = event.event_type
        state = "empty"
        if open_report is not None:
            state = {
                "shortfall_recorded": "shortfall_open",
                "requirements_linked": "requirements_ready",
                "production_linked": "producing",
            }[latest_by_report[open_report.report_id]]
        elif any(event.resolution is not None for event in ledger.events):
            state = "resolved"
        history = tuple(
            {
                "report_id": report_id,
                "state": event_type,
            }
            for report_id, event_type in sorted(latest_by_report.items())
        )
        return MaterialFeedbackView(
            project_id=self.project_id,
            revision=ledger.revision,
            state=state,
            open_report=(
                {
                    "report_id": open_report.report_id,
                    "source_kind": open_report.source_kind,
                    "source_plan_id": open_report.source_plan_id,
                    "items": tuple(
                        {
                            "requirement_item_id": item.requirement_item_id,
                            "asset_type": item.asset_type,
                            "reason": item.reason,
                            "narrative_position": item.narrative_position,
                            "priority": item.priority,
                        }
                        for item in open_report.items
                    ),
                }
                if open_report is not None else None
            ),
            history=history,
        )
