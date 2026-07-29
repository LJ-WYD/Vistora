"""Atomic append-only store for product-entry orchestration events."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from .models import (
    GENESIS_DIGEST,
    ProductEntryCommand,
    ProductEntryEvent,
    ProductEntryLedger,
    digest_json,
)


class ProductEntryStoreError(ValueError):
    pass


class ProductEntryIntegrityError(ProductEntryStoreError):
    pass


class ProductEntryConcurrencyError(ProductEntryStoreError):
    pass


class ProductEntryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path) -> ProductEntryStore:
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.product.json"))

    def load(
        self,
        *,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> ProductEntryLedger:
        if not self.path.exists():
            if session_id is None or project_id is None:
                raise ProductEntryStoreError("Product entry identity is unknown")
            return ProductEntryLedger.empty(
                session_id=session_id,
                project_id=project_id,
            )
        try:
            ledger = ProductEntryLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise ProductEntryIntegrityError(
                "Product entry ledger is corrupt or tampered"
            ) from exc
        if session_id is not None and ledger.session_id != session_id:
            raise ProductEntryIntegrityError("Product session ID is mismatched")
        if project_id is not None and ledger.project_id != project_id:
            raise ProductEntryIntegrityError("Product project ID is mismatched")
        return ledger

    @contextmanager
    def exclusive(
        self,
        *,
        session_id: str,
        project_id: str,
        expected_revision: int,
    ) -> Iterator[ProductEntryLedger]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise ProductEntryConcurrencyError(
                "Another product action is already running"
            ) from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(session_id=session_id, project_id=project_id)
            if ledger.revision != expected_revision:
                raise ProductEntryConcurrencyError(
                    "Product state changed; refresh before retrying"
                )
            yield ledger
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(
        self,
        ledger: ProductEntryLedger,
        command: ProductEntryCommand,
        *,
        event_id: str,
        status: str,
        target_id: str | None,
        result: dict,
        recorded_at,
    ) -> ProductEntryLedger:
        previous = (
            ledger.events[-1].event_digest if ledger.events else GENESIS_DIGEST
        )
        event = ProductEntryEvent.create(
            sequence=ledger.revision + 1,
            event_id=event_id,
            command=command,
            status=status,
            target_id=target_id,
            result=result,
            recorded_at=recorded_at,
            previous_event_digest=previous,
        )
        events = (*ledger.events, event)
        updated = ProductEntryLedger(
            session_id=ledger.session_id,
            project_id=ledger.project_id,
            revision=len(events),
            events=events,
            integrity_digest=digest_json(
                [candidate.event_digest for candidate in events]
            ),
        )
        self._atomic_save(updated)
        return updated

    def _atomic_save(self, ledger: ProductEntryLedger) -> None:
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
