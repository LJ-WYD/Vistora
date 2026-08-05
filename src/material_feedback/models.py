"""Versioned contracts for the missing-material feedback loop."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from director import MaterialShortfallReport, digest_json


VERSION = "1.0.0"
Version = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GENESIS_DIGEST = "sha256:" + ("0" * 64)


class FeedbackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: Version = VERSION


class SupplementalRequirementsLink(FeedbackModel):
    schema_name: Literal["vistora.material-feedback.requirements-link"] = (
        "vistora.material-feedback.requirements-link"
    )
    report_id: StableId
    report_digest: Digest
    proposal_id: StableId
    requirements_plan_id: StableId
    requirements_plan_version: int = Field(ge=1)
    requirements_plan_digest: Digest
    requirements_review_id: StableId
    requirements_review_digest: Digest
    requirement_item_ids: tuple[StableId, ...] = Field(min_length=1)
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def items_are_stable(self):
        if self.requirement_item_ids != tuple(sorted(set(self.requirement_item_ids))):
            raise ValueError("Requirement item IDs must be unique and ordered")
        return self


class FeedbackProductionLink(FeedbackModel):
    schema_name: Literal["vistora.material-feedback.production-link"] = (
        "vistora.material-feedback.production-link"
    )
    report_id: StableId
    requirements_confirmation_id: StableId
    production_plan_id: StableId
    production_plan_digest: Digest
    production_confirmation_id: StableId
    production_run_id: StableId
    recorded_at: AwareDatetime


class FeedbackResolution(FeedbackModel):
    schema_name: Literal["vistora.material-feedback.resolution"] = (
        "vistora.material-feedback.resolution"
    )
    resolution_id: StableId
    report_id: StableId
    production_run_id: StableId
    requirement_materials: dict[StableId, StableId]
    resolved_at: AwareDatetime
    resolution_digest: Digest

    @model_validator(mode="after")
    def resolution_is_exact(self):
        if not self.requirement_materials:
            raise ValueError("Feedback resolution requires accepted materials")
        if list(self.requirement_materials) != sorted(self.requirement_materials):
            raise ValueError("Resolution requirements must be ordered")
        if len(set(self.requirement_materials.values())) != len(
            self.requirement_materials
        ):
            raise ValueError("One accepted material cannot satisfy two requirements")
        payload = self.model_dump(mode="json", exclude={"resolution_digest"})
        if self.resolution_digest != digest_json(payload):
            raise ValueError("Feedback resolution digest mismatched")
        return self


class MaterialFeedbackEvent(FeedbackModel):
    schema_name: Literal["vistora.material-feedback.event"] = (
        "vistora.material-feedback.event"
    )
    sequence: int = Field(ge=1)
    event_id: StableId
    event_type: Literal[
        "shortfall_recorded",
        "requirements_linked",
        "production_linked",
        "resolved",
    ]
    report: MaterialShortfallReport | None = None
    requirements_link: SupplementalRequirementsLink | None = None
    production_link: FeedbackProductionLink | None = None
    resolution: FeedbackResolution | None = None
    recorded_at: AwareDatetime
    previous_event_digest: Digest
    event_digest: Digest

    @model_validator(mode="after")
    def event_shape_and_digest(self):
        values = {
            "shortfall_recorded": self.report,
            "requirements_linked": self.requirements_link,
            "production_linked": self.production_link,
            "resolved": self.resolution,
        }
        if values[self.event_type] is None or sum(
            value is not None for value in values.values()
        ) != 1:
            raise ValueError("Material feedback event payload is invalid")
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Material feedback event digest mismatched")
        return self


class MaterialFeedbackLedger(FeedbackModel):
    schema_name: Literal["vistora.material-feedback.ledger"] = (
        "vistora.material-feedback.ledger"
    )
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[MaterialFeedbackEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, *, project_id: str):
        return cls(
            project_id=project_id,
            revision=0,
            events=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def ledger_is_exact(self):
        if self.revision != len(self.events):
            raise ValueError("Feedback revision must equal event count")
        previous = GENESIS_DIGEST
        reports: dict[str, MaterialShortfallReport] = {}
        requirements: set[str] = set()
        productions: set[str] = set()
        resolutions: set[str] = set()
        for sequence, event in enumerate(self.events, start=1):
            if event.sequence != sequence or event.previous_event_digest != previous:
                raise ValueError("Feedback event chain is broken")
            previous = event.event_digest
            if event.report is not None:
                report = event.report
                if report.project_id != self.project_id or report.report_id in reports:
                    raise ValueError("Feedback report is duplicate or cross-project")
                reports[report.report_id] = report
            elif event.requirements_link is not None:
                link = event.requirements_link
                report = reports.get(link.report_id)
                if report is None or report.report_digest != link.report_digest:
                    raise ValueError("Requirements link has no exact shortfall")
                if link.report_id in requirements or link.report_id in resolutions:
                    raise ValueError("Requirements link is duplicate or resolved")
                expected = tuple(sorted(item.requirement_item_id for item in report.items))
                if link.requirement_item_ids != expected:
                    raise ValueError("Requirements link does not cover shortfall")
                requirements.add(link.report_id)
            elif event.production_link is not None:
                link = event.production_link
                if link.report_id not in requirements or link.report_id in productions:
                    raise ValueError("Production link is out of order or duplicate")
                productions.add(link.report_id)
            else:
                resolution = event.resolution
                assert resolution is not None
                if (
                    resolution.report_id not in productions
                    or resolution.report_id in resolutions
                ):
                    raise ValueError("Feedback resolution is out of order or duplicate")
                expected = {
                    item.requirement_item_id
                    for item in reports[resolution.report_id].items
                }
                if set(resolution.requirement_materials) != expected:
                    raise ValueError("Feedback resolution is incomplete")
                resolutions.add(resolution.report_id)
        if self.integrity_digest != digest_json(
            [event.event_digest for event in self.events]
        ):
            raise ValueError("Feedback ledger integrity digest mismatched")
        return self


class MaterialFeedbackView(FeedbackModel):
    schema_name: Literal["vistora.material-feedback.view"] = (
        "vistora.material-feedback.view"
    )
    project_id: StableId
    revision: int = Field(ge=0)
    state: Literal["empty", "shortfall_open", "requirements_ready", "producing", "resolved"]
    open_report: dict[str, Any] | None = None
    history: tuple[dict[str, Any], ...] = ()

