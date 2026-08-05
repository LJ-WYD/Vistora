"""Versioned contracts for Vistora's local production entry composition."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


PRODUCT_ENTRY_VERSION = "1.0.0"
ProductEntryVersion = Literal["1.0.0"]
StableId = Annotated[
    str,
    Field(min_length=3, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$"),
]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GENESIS_DIGEST = "sha256:" + ("0" * 64)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


class ProductEntryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_version: ProductEntryVersion = PRODUCT_ENTRY_VERSION


ProductAction = Literal[
    "director_turn",
    "persist_review",
    "confirm",
    "reject",
    "execute",
    "rollback_review",
    "rollback_confirm",
    "rollback_reject",
    "rollback_apply",
    "persist_material_review",
    "confirm_materials",
    "reject_materials",
    "withdraw_materials",
    "plan_material_production",
    "confirm_production_plan",
    "reject_production_plan",
    "withdraw_production_plan",
    "start_material_production",
    "poll_material_production",
    "cancel_material_job",
    "retry_material_job",
    "accept_material_artifact",
    "reject_material_artifact",
    "return_to_director",
]


class ProductEntryCommand(ProductEntryModel):
    schema_name: Literal["vistora.product-entry-command"] = (
        "vistora.product-entry-command"
    )
    request_id: StableId
    session_id: StableId
    project_id: StableId
    expected_revision: int = Field(ge=0)
    action: ProductAction
    actor_id: StableId
    user_message: str | None = Field(default=None, min_length=1, max_length=8000)
    target_id: StableId | None = None

    @model_validator(mode="after")
    def command_shape(self) -> ProductEntryCommand:
        if self.action == "director_turn":
            if self.user_message is None or self.target_id is not None:
                raise ValueError("Director turn requires only a user message")
        elif self.user_message is not None:
            raise ValueError("Only Director turns accept a user message")
        elif self.target_id is None:
            raise ValueError("Workflow actions require an exact target ID")
        return self

    def content_digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class ProductEntryEvent(ProductEntryModel):
    schema_name: Literal["vistora.product-entry-event"] = (
        "vistora.product-entry-event"
    )
    sequence: int = Field(ge=1)
    event_id: StableId
    request_id: StableId
    request_digest: Digest
    session_id: StableId
    project_id: StableId
    action: ProductAction
    status: StableId
    target_id: StableId | None = None
    result: dict[str, Any]
    recorded_at: AwareDatetime
    previous_event_digest: Digest
    event_digest: Digest

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        event_id: str,
        command: ProductEntryCommand,
        status: str,
        target_id: str | None,
        result: dict[str, Any],
        recorded_at: datetime,
        previous_event_digest: str,
    ) -> ProductEntryEvent:
        payload = {
            "schema_version": PRODUCT_ENTRY_VERSION,
            "schema_name": "vistora.product-entry-event",
            "sequence": sequence,
            "event_id": event_id,
            "request_id": command.request_id,
            "request_digest": command.content_digest(),
            "session_id": command.session_id,
            "project_id": command.project_id,
            "action": command.action,
            "status": status,
            "target_id": target_id,
            "result": result,
            "recorded_at": recorded_at,
            "previous_event_digest": previous_event_digest,
        }
        return cls(**payload, event_digest=digest_json(_jsonable(payload)))

    @model_validator(mode="after")
    def digest_matches(self) -> ProductEntryEvent:
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Product entry event digest is mismatched")
        return self


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            item.isoformat().replace("+00:00", "Z")
            if isinstance(item, datetime)
            else item
        )
        for key, item in value.items()
    }


class ProductEntryLedger(ProductEntryModel):
    schema_name: Literal["vistora.product-entry-ledger"] = (
        "vistora.product-entry-ledger"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[ProductEntryEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, *, session_id: str, project_id: str) -> ProductEntryLedger:
        return cls(
            session_id=session_id,
            project_id=project_id,
            revision=0,
            events=(),
            integrity_digest=digest_json([]),
        )

    @model_validator(mode="after")
    def ledger_is_exact(self) -> ProductEntryLedger:
        if self.revision != len(self.events):
            raise ValueError("Product entry revision must equal event count")
        previous = GENESIS_DIGEST
        request_ids: dict[str, str] = {}
        for sequence, event in enumerate(self.events, start=1):
            if event.sequence != sequence:
                raise ValueError("Product entry sequence must be contiguous")
            if event.session_id != self.session_id or event.project_id != self.project_id:
                raise ValueError("Product entry event crosses session/project")
            if event.previous_event_digest != previous:
                raise ValueError("Product entry digest chain is broken")
            known = request_ids.get(event.request_id)
            if known is not None and known != event.request_digest:
                raise ValueError("Product request ID was reused with new content")
            if known is not None:
                raise ValueError("Product request ID is duplicated in ledger")
            request_ids[event.request_id] = event.request_digest
            previous = event.event_digest
        if self.integrity_digest != digest_json(
            [event.event_digest for event in self.events]
        ):
            raise ValueError("Product entry integrity digest is mismatched")
        return self


class ProductEntryView(ProductEntryModel):
    schema_name: Literal["vistora.product-entry-view"] = (
        "vistora.product-entry-view"
    )
    session_id: StableId
    project_id: StableId
    revision: int = Field(ge=0)
    state: Literal[
        "dialogue",
        "needs_clarification",
        "needs_materials",
        "materials_incomplete",
        "proposal_ready",
        "material_requirements_ready",
        "material_reviewed",
        "materials_confirmed",
        "materials_rejected",
        "materials_withdrawn",
        "production_plan_ready",
        "production_plan_needs_input",
        "production_plan_unsupported",
        "production_plan_confirmed",
        "production_plan_rejected",
        "production_plan_withdrawn",
        "material_production_running",
        "material_awaiting_review",
        "material_production_succeeded",
        "material_production_partial",
        "material_production_failed",
        "material_production_recovery_required",
        "material_production_cancelled",
        "returned_to_director",
        "reviewed",
        "confirmed",
        "rejected",
        "executing",
        "succeeded",
        "failed",
        "partial",
        "recovery_required",
        "rollback_reviewed",
        "rollback_confirmed",
        "rollback_rejected",
        "rolled_back",
        "error",
    ]
    director: dict[str, Any]
    review: dict[str, Any] | None = None
    workflow: dict[str, Any]
    material_requirements: dict[str, Any] | None = None
    creation_planning: dict[str, Any] | None = None
    material_production: dict[str, Any] | None = None
    material_feedback: dict[str, Any] | None = None
    latest_result: dict[str, Any] | None = None
    allowed_actions: tuple[ProductAction, ...] = ()
    limitations: tuple[str, ...] = (
        "Online generation providers are not configured by default.",
        "Only validated and explicitly accepted artifacts enter the material catalog.",
        "A Director proposal is not user confirmation.",
        "Execution is delegated only to the constrained Editing Agent.",
        "The browser cannot call skills or mutate timeline/media directly.",
    )


class ProductEntryResponse(ProductEntryModel):
    schema_name: Literal["vistora.product-entry-response"] = (
        "vistora.product-entry-response"
    )
    request_id: StableId
    replayed: bool = False
    view: ProductEntryView
