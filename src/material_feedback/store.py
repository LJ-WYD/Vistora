"""Atomic append-only store for missing-material feedback."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from director import digest_json

from .models import GENESIS_DIGEST, MaterialFeedbackEvent, MaterialFeedbackLedger


class MaterialFeedbackError(ValueError):
    pass


class MaterialFeedbackIntegrityError(MaterialFeedbackError):
    pass


class MaterialFeedbackConcurrencyError(MaterialFeedbackError):
    pass


class MaterialFeedbackStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path):
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.material-feedback.json"))

    def load(self, *, project_id: str | None = None):
        if not self.path.exists():
            if project_id is None:
                raise MaterialFeedbackError("Material feedback project is unknown")
            return MaterialFeedbackLedger.empty(project_id=project_id)
        try:
            ledger = MaterialFeedbackLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise MaterialFeedbackIntegrityError(
                "Material feedback ledger is corrupt or tampered"
            ) from exc
        if project_id is not None and ledger.project_id != project_id:
            raise MaterialFeedbackIntegrityError("Material feedback project drifted")
        return ledger

    @contextmanager
    def exclusive(self, *, project_id: str, expected_revision: int):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise MaterialFeedbackConcurrencyError(
                "Another material feedback operation is in progress"
            ) from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(project_id=project_id)
            if ledger.revision != expected_revision:
                raise MaterialFeedbackConcurrencyError(
                    "Material feedback changed; refresh first"
                )
            yield ledger
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(self, ledger, *, event_id, event_type, recorded_at, **payload):
        values = {
            "sequence": ledger.revision + 1,
            "event_id": event_id,
            "event_type": event_type,
            "report": payload.get("report"),
            "requirements_link": payload.get("requirements_link"),
            "production_link": payload.get("production_link"),
            "resolution": payload.get("resolution"),
            "recorded_at": recorded_at,
            "previous_event_digest": (
                ledger.events[-1].event_digest if ledger.events else GENESIS_DIGEST
            ),
        }
        shell = MaterialFeedbackEvent.model_construct(
            **values, event_digest=GENESIS_DIGEST
        )
        event = MaterialFeedbackEvent(
            **values,
            event_digest=digest_json(
                shell.model_dump(mode="json", exclude={"event_digest"})
            ),
        )
        events = (*ledger.events, event)
        updated = MaterialFeedbackLedger(
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

