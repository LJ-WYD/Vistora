"""Atomic hash-chained material-requirements ledger store."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from director import digest_json

from .models import (
    GENESIS_DIGEST,
    MaterialRequirementsEvent,
    MaterialRequirementsLedger,
)


class MaterialRequirementsStoreError(ValueError):
    pass


class MaterialRequirementsIntegrityError(MaterialRequirementsStoreError):
    pass


class MaterialRequirementsConcurrencyError(MaterialRequirementsStoreError):
    pass


class MaterialRequirementsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path):
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.materials.json"))

    def load(self, *, session_id=None, project_id=None):
        if not self.path.exists():
            if session_id is None or project_id is None:
                raise MaterialRequirementsStoreError(
                    "Material ledger identity is unknown"
                )
            return MaterialRequirementsLedger.empty(
                session_id=session_id,
                project_id=project_id,
            )
        try:
            ledger = MaterialRequirementsLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise MaterialRequirementsIntegrityError(
                "Material ledger is corrupt or tampered"
            ) from exc
        if session_id is not None and ledger.session_id != session_id:
            raise MaterialRequirementsIntegrityError(
                "Material ledger session is mismatched"
            )
        if project_id is not None and ledger.project_id != project_id:
            raise MaterialRequirementsIntegrityError(
                "Material ledger project is mismatched"
            )
        return ledger

    @contextmanager
    def exclusive(
        self,
        *,
        session_id: str,
        project_id: str,
        expected_revision: int,
    ) -> Iterator[MaterialRequirementsLedger]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise MaterialRequirementsConcurrencyError(
                "Another material decision is in progress"
            ) from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(session_id=session_id, project_id=project_id)
            if ledger.revision != expected_revision:
                raise MaterialRequirementsConcurrencyError(
                    "Material requirements changed; refresh first"
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
            "schema_name": "vistora.material-requirements-event",
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
        shell = MaterialRequirementsEvent.model_construct(
            **values,
            event_digest="sha256:" + ("0" * 64),
        )
        event = MaterialRequirementsEvent(
            **values,
            event_digest=digest_json(
                shell.model_dump(mode="json", exclude={"event_digest"})
            ),
        )
        events = (*ledger.events, event)
        updated = MaterialRequirementsLedger(
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

