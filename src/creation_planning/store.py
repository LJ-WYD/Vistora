"""Atomic append-only store for material-production planning."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from director import digest_json

from .models import (
    GENESIS_DIGEST,
    CreationPlanningEvent,
    CreationPlanningLedger,
)


class CreationPlanningStoreError(ValueError):
    pass


class CreationPlanningIntegrityError(CreationPlanningStoreError):
    pass


class CreationPlanningConcurrencyError(CreationPlanningStoreError):
    pass


class CreationPlanningStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path):
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.creation-planning.json"))

    def load(self, *, session_id=None, project_id=None):
        if not self.path.exists():
            if session_id is None or project_id is None:
                raise CreationPlanningStoreError(
                    "Creation-planning ledger identity is unknown"
                )
            return CreationPlanningLedger.empty(
                session_id=session_id,
                project_id=project_id,
            )
        try:
            ledger = CreationPlanningLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise CreationPlanningIntegrityError(
                "Creation-planning ledger is corrupt or tampered"
            ) from exc
        if session_id is not None and ledger.session_id != session_id:
            raise CreationPlanningIntegrityError(
                "Creation-planning session is mismatched"
            )
        if project_id is not None and ledger.project_id != project_id:
            raise CreationPlanningIntegrityError(
                "Creation-planning project is mismatched"
            )
        return ledger

    @contextmanager
    def exclusive(
        self,
        *,
        session_id: str,
        project_id: str,
        expected_revision: int,
    ):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise CreationPlanningConcurrencyError(
                "Another creation-planning operation is in progress"
            ) from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(
                session_id=session_id,
                project_id=project_id,
            )
            if ledger.revision != expected_revision:
                raise CreationPlanningConcurrencyError(
                    "Creation plan changed; refresh first"
                )
            yield ledger
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(
        self,
        ledger,
        *,
        event_id,
        event_type,
        recorded_at,
        proposal=None,
        confirmation=None,
        withdrawn_proposal_id=None,
    ):
        values = {
            "schema_version": "1.0.0",
            "schema_name": "vistora.creation-planning.event",
            "sequence": ledger.revision + 1,
            "event_id": event_id,
            "event_type": event_type,
            "proposal": proposal,
            "confirmation": confirmation,
            "withdrawn_proposal_id": withdrawn_proposal_id,
            "recorded_at": recorded_at,
            "previous_event_digest": (
                ledger.events[-1].event_digest
                if ledger.events
                else GENESIS_DIGEST
            ),
        }
        shell = CreationPlanningEvent.model_construct(
            **values,
            event_digest=GENESIS_DIGEST,
        )
        event = CreationPlanningEvent(
            **values,
            event_digest=digest_json(
                shell.model_dump(mode="json", exclude={"event_digest"})
            ),
        )
        events = (*ledger.events, event)
        updated = CreationPlanningLedger(
            session_id=ledger.session_id,
            project_id=ledger.project_id,
            revision=len(events),
            events=events,
            integrity_digest=digest_json(
                [candidate.event_digest for candidate in events]
            ),
        )
        self._save(updated)
        return updated

    def _save(self, ledger):
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                output.write(ledger.model_dump_json(indent=2))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
