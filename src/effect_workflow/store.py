"""Atomic hash-chained effect-plan store."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from director import digest_json
from .models import GENESIS_DIGEST, EffectPlanEvent, EffectPlanLedger


class EffectPlanError(ValueError):
    pass


class EffectPlanIntegrityError(EffectPlanError):
    pass


class EffectPlanConcurrencyError(EffectPlanError):
    pass


class EffectPlanStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path):
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.effect-plans.json"))

    def load(self, *, project_id=None):
        if not self.path.exists():
            if project_id is None:
                raise EffectPlanError("Effect project identity is unknown")
            return EffectPlanLedger.empty(project_id=project_id)
        try:
            ledger = EffectPlanLedger.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError) as exc:
            raise EffectPlanIntegrityError("Effect ledger is corrupt or tampered") from exc
        if project_id is not None and ledger.project_id != project_id:
            raise EffectPlanIntegrityError("Effect ledger project drifted")
        return ledger

    @contextmanager
    def exclusive(self, *, project_id: str, expected_revision: int):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise EffectPlanConcurrencyError("Another effect decision is in progress") from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(project_id=project_id)
            if ledger.revision != expected_revision:
                raise EffectPlanConcurrencyError("Effect history changed; refresh first")
            yield ledger
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(self, ledger, *, event_id, event_type, recorded_at, **payload):
        values = {
            "sequence": ledger.revision + 1,
            "event_id": event_id,
            "event_type": event_type,
            "plan": payload.get("plan"),
            "review": payload.get("review"),
            "confirmation": payload.get("confirmation"),
            "recorded_at": recorded_at,
            "previous_event_digest": ledger.events[-1].event_digest if ledger.events else GENESIS_DIGEST,
        }
        shell = EffectPlanEvent.model_construct(**values, event_digest=GENESIS_DIGEST)
        event = EffectPlanEvent(
            **values,
            event_digest=digest_json(shell.model_dump(mode="json", exclude={"event_digest"})),
        )
        events = (*ledger.events, event)
        updated = EffectPlanLedger(
            project_id=ledger.project_id,
            revision=len(events),
            events=events,
            integrity_digest=digest_json([item.event_digest for item in events]),
        )
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                output.write(updated.model_dump_json(indent=2))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return updated

