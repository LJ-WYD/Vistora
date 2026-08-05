"""Versioned O30 effect candidate, progress, cost, retry and cache records."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from director import digest_json
from effect_workflow import EffectArtifactCandidate, EffectExecutionRequest
from effect_workflow.models import Digest, EffectModel, GENESIS_DIGEST, StableId


class EffectJobCost(EffectModel):
    status: Literal["known", "unknown"] = "unknown"
    amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def truthful(self):
        if self.status == "known" and (self.amount is None or self.currency is None):
            raise ValueError("Known effect cost requires amount and currency")
        if self.status == "unknown" and (self.amount is not None or self.currency is not None):
            raise ValueError("Unknown effect cost cannot invent a value")
        return self


class EffectRedoScope(EffectModel):
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    object_id: StableId | None = None
    mask_id: StableId | None = None
    instruction: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def forward(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Effect redo scope must have positive duration")
        return self


class EffectAttemptRequest(EffectModel):
    schema_name: Literal["vistora.effect-attempt-request"] = (
        "vistora.effect-attempt-request"
    )
    attempt_id: StableId
    execution_request: EffectExecutionRequest
    task_id: StableId
    attempt_number: int = Field(ge=1, le=100)
    reason: Literal["initial", "retry", "partial_redo"]
    base_candidate_id: StableId | None = None
    redo_scope: EffectRedoScope | None = None
    idempotency_key: StableId
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def exact(self):
        if self.task_id not in self.execution_request.task_ids:
            raise ValueError("Effect attempt task is not in the exact execution request")
        if self.reason == "initial" and (
            self.attempt_number != 1 or self.base_candidate_id is not None or self.redo_scope is not None
        ):
            raise ValueError("Initial effect attempt has invalid retry state")
        if self.reason == "retry" and (
            self.attempt_number <= 1 or self.redo_scope is not None
        ):
            raise ValueError("Effect retry has invalid state")
        if self.reason == "partial_redo" and (
            self.attempt_number <= 1 or self.base_candidate_id is None or self.redo_scope is None
        ):
            raise ValueError("Partial redo requires a base candidate and bounded scope")
        return self

    def cache_key(self):
        return digest_json({
            "execution_request": self.execution_request.model_dump(mode="json"),
            "task_id": self.task_id,
            "redo_scope": self.redo_scope.model_dump(mode="json") if self.redo_scope else None,
        })


class EffectAttemptState(EffectModel):
    record_type: Literal["attempt"] = "attempt"
    attempt: EffectAttemptRequest
    status: Literal[
        "running", "succeeded", "failed", "cancelled", "recovery_required", "cached"
    ]
    progress: float = Field(ge=0, le=1, allow_inf_nan=False)
    stage: StableId
    cost: EffectJobCost = Field(default_factory=EffectJobCost)
    candidate_id: StableId | None = None
    error_code: StableId | None = None
    message: str = Field(min_length=1, max_length=500)
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def truthful(self):
        if self.status in {"succeeded", "cached"}:
            if self.candidate_id is None or self.progress != 1 or self.error_code is not None:
                raise ValueError("Successful effect attempt requires a candidate")
        elif self.candidate_id is not None:
            raise ValueError("Non-success effect attempt cannot claim a candidate")
        if self.status in {"failed", "recovery_required"} and self.error_code is None:
            raise ValueError("Failed effect attempt requires an error code")
        if self.status not in {"failed", "recovery_required"} and self.error_code is not None:
            raise ValueError("Non-failure effect attempt cannot carry an error")
        return self


class EffectCandidateRecord(EffectModel):
    record_type: Literal["candidate"] = "candidate"
    candidate_id: StableId
    task_id: StableId
    candidate_version: int = Field(ge=1)
    attempt_id: StableId
    artifact: EffectArtifactCandidate
    cache_key: Digest
    cost: EffectJobCost = Field(default_factory=EffectJobCost)
    review_status: Literal["pending", "accepted", "rejected", "superseded"] = "pending"
    created_at: AwareDatetime

    @model_validator(mode="after")
    def exact_artifact(self):
        if self.artifact.task_id != self.task_id:
            raise ValueError("Effect candidate artifact crosses task")
        return self


class EffectCandidateSelection(EffectModel):
    record_type: Literal["selection"] = "selection"
    selection_id: StableId
    task_id: StableId
    action: Literal["accept", "reject", "replace", "rollback"]
    candidate_id: StableId
    previous_candidate_id: StableId | None = None
    selected_candidate_id: StableId | None = None
    actor_id: StableId
    reason: str = Field(min_length=1, max_length=500)
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact(self):
        if self.action == "reject" and self.selected_candidate_id is not None:
            raise ValueError("Rejected candidate cannot become selected")
        if self.action in {"replace", "rollback"} and self.previous_candidate_id is None:
            raise ValueError("Replace/rollback requires previous selection")
        if self.action != "reject" and self.selected_candidate_id != self.candidate_id:
            raise ValueError("Selection action must select its candidate")
        return self


class EffectCacheRecord(EffectModel):
    record_type: Literal["cache"] = "cache"
    cache_id: StableId
    cache_key: Digest
    candidate_id: StableId
    task_id: StableId
    status: Literal["active", "invalidated"]
    reason: str = Field(min_length=1, max_length=300)
    recorded_at: AwareDatetime


EffectJobRecord = Annotated[
    EffectAttemptState | EffectCandidateRecord | EffectCandidateSelection | EffectCacheRecord,
    Field(discriminator="record_type"),
]


class EffectJobEvent(EffectModel):
    schema_name: Literal["vistora.effect-job-event"] = "vistora.effect-job-event"
    sequence: int = Field(ge=1)
    event_id: StableId
    record: EffectJobRecord
    previous_event_digest: Digest
    event_digest: Digest

    @model_validator(mode="after")
    def digest_is_exact(self):
        payload = self.model_dump(mode="json", exclude={"event_digest"})
        if self.event_digest != digest_json(payload):
            raise ValueError("Effect job event digest mismatched")
        return self


class EffectJobLedger(EffectModel):
    schema_name: Literal["vistora.effect-job-ledger"] = "vistora.effect-job-ledger"
    project_id: StableId
    revision: int = Field(ge=0)
    events: tuple[EffectJobEvent, ...] = ()
    integrity_digest: Digest

    @classmethod
    def empty(cls, project_id):
        return cls(project_id=project_id, revision=0, events=(), integrity_digest=digest_json([]))

    @model_validator(mode="after")
    def exact(self):
        if self.revision != len(self.events):
            raise ValueError("Effect job ledger revision mismatched")
        previous = GENESIS_DIGEST
        candidate_versions: dict[str, int] = {}
        candidate_ids: set[str] = set()
        candidate_tasks: dict[str, str] = {}
        attempt_keys: dict[str, str] = {}
        attempt_tasks: dict[str, str] = {}
        attempt_latest: dict[str, EffectAttemptState] = {}
        for sequence, event in enumerate(self.events, start=1):
            if event.sequence != sequence or event.previous_event_digest != previous:
                raise ValueError("Effect job ledger chain is broken")
            previous = event.event_digest
            record = event.record
            if isinstance(record, EffectAttemptState):
                known = attempt_keys.get(record.attempt.attempt_id)
                payload = digest_json(record.attempt.model_dump(mode="json"))
                if known is not None and known != payload:
                    raise ValueError("Effect attempt identity was replayed with drift")
                prior = attempt_latest.get(record.attempt.attempt_id)
                if prior is None and record.status not in {"running", "cached"}:
                    raise ValueError("Effect attempt starts in an illegal state")
                if prior is not None:
                    if prior.status != "running":
                        raise ValueError("Terminal effect attempt was appended again")
                    if record.progress < prior.progress:
                        raise ValueError("Effect attempt progress moved backward")
                attempt_keys[record.attempt.attempt_id] = payload
                attempt_tasks[record.attempt.attempt_id] = record.attempt.task_id
                attempt_latest[record.attempt.attempt_id] = record
            elif isinstance(record, EffectCandidateRecord):
                if record.candidate_id in candidate_ids:
                    raise ValueError("Effect candidate ID is duplicated")
                expected = candidate_versions.get(record.task_id, 0) + 1
                if record.candidate_version != expected:
                    raise ValueError("Effect candidate version is not contiguous")
                candidate_versions[record.task_id] = expected
                candidate_ids.add(record.candidate_id)
                candidate_tasks[record.candidate_id] = record.task_id
                if attempt_tasks.get(record.attempt_id) != record.task_id:
                    raise ValueError("Effect candidate crosses attempt or task")
            elif isinstance(record, EffectCandidateSelection):
                if record.candidate_id not in candidate_ids:
                    raise ValueError("Effect selection references an unknown candidate")
                if candidate_tasks[record.candidate_id] != record.task_id:
                    raise ValueError("Effect selection crosses task")
                if (
                    record.previous_candidate_id is not None
                    and candidate_tasks.get(record.previous_candidate_id) != record.task_id
                ):
                    raise ValueError("Effect prior selection crosses task")
            else:
                if record.candidate_id not in candidate_ids:
                    raise ValueError("Effect cache references an unknown candidate")
                if candidate_tasks[record.candidate_id] != record.task_id:
                    raise ValueError("Effect cache crosses task")
        if self.integrity_digest != digest_json([item.event_digest for item in self.events]):
            raise ValueError("Effect job ledger integrity digest mismatched")
        return self


class EffectJobView(EffectModel):
    schema_name: Literal["vistora.effect-job-view"] = "vistora.effect-job-view"
    project_id: StableId
    revision: int = Field(ge=0)
    state: Literal["empty", "running", "awaiting_review", "failed", "recovery_required", "selected"]
    attempts: tuple[dict[str, Any], ...] = ()
    candidates: tuple[dict[str, Any], ...] = ()
    selections: tuple[dict[str, Any], ...] = ()
    cache_entries: tuple[dict[str, Any], ...] = ()
