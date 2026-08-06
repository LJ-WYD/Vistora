"""Atomic append-only persistence and concurrency guards for workflow records."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from .models import (
    GENESIS_DIGEST,
    WorkflowLedger,
    WorkflowLedgerEntry,
    WorkflowRecord,
    digest_json,
)


class WorkflowStoreError(ValueError):
    pass


class WorkflowIntegrityError(WorkflowStoreError):
    pass


class WorkflowConcurrencyError(WorkflowStoreError):
    pass


class WorkflowLedgerSession:
    def __init__(
        self,
        store: WorkflowStore,
        ledger: WorkflowLedger,
    ) -> None:
        self._store = store
        self.ledger = ledger

    def append(
        self,
        record: WorkflowRecord,
        *,
        entry_id: str,
        recorded_at: datetime,
    ) -> WorkflowLedger:
        previous = (
            self.ledger.entries[-1].entry_digest
            if self.ledger.entries
            else GENESIS_DIGEST
        )
        entry = WorkflowLedgerEntry.create(
            sequence=self.ledger.revision + 1,
            entry_id=entry_id,
            previous_entry_digest=previous,
            record=record,
            recorded_at=recorded_at,
        )
        entries = (*self.ledger.entries, entry)
        updated = WorkflowLedger(
            project_id=self.ledger.project_id,
            revision=len(entries),
            migration_source=self.ledger.migration_source,
            entries=entries,
            integrity_digest=digest_json(
                [item.entry_digest for item in entries]
            ),
        )
        self._store._atomic_save(updated)
        self.ledger = updated
        return updated


class WorkflowStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(
        cls,
        project_file: str | Path,
    ) -> WorkflowStore:
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.workflow.json"))

    def load(self, project_id: str | None = None) -> WorkflowLedger:
        if not self.path.exists():
            if project_id is None:
                raise WorkflowStoreError(
                    "Workflow ledger does not exist and project ID is unknown"
                )
            return WorkflowLedger.empty(project_id)
        try:
            ledger = WorkflowLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise WorkflowIntegrityError(
                "Workflow ledger is corrupt or failed integrity validation"
            ) from exc
        if project_id is not None and ledger.project_id != project_id:
            raise WorkflowIntegrityError(
                "Workflow ledger project identity is mismatched"
            )
        return ledger

    @staticmethod
    def _process_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            # ``os.kill(pid, 0)`` is not a reliable liveness probe for a
            # Python process launched with CREATE_NO_WINDOW/DETACHED_PROCESS:
            # Windows can report EINVAL for the current, healthy process and
            # make a live workflow lock look stale.  Query a process handle
            # instead, which is also how the packaged desktop app runs work.
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information,
                False,
                pid,
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            # Access denied means the process exists but is protected from
            # this caller; it must never be treated as a dead lock owner.
            return ctypes.get_last_error() == 5
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _clear_dead_owner_lock(self) -> bool:
        """Remove only a well-formed lock whose recorded process is gone."""

        try:
            lines = self.lock_path.read_text(encoding="utf-8").splitlines()
            values = dict(line.split("=", 1) for line in lines)
            pid = int(values["pid"])
            token = values["token"]
        except (OSError, ValueError, KeyError):
            return False
        if not token or self._process_is_alive(pid):
            return False
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return True

    @contextmanager
    def exclusive(
        self,
        *,
        project_id: str,
        expected_revision: int | None = None,
    ) -> Iterator[WorkflowLedgerSession]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open(
                "x",
                encoding="utf-8",
                newline="\n",
            )
        except FileExistsError:
            if not self._clear_dead_owner_lock():
                raise WorkflowConcurrencyError(
                    "Another workflow operation holds the project lock"
                )
            try:
                lock = self.lock_path.open(
                    "x",
                    encoding="utf-8",
                    newline="\n",
                )
            except FileExistsError as exc:
                raise WorkflowConcurrencyError(
                    "Another workflow operation acquired the project lock"
                ) from exc
        try:
            with lock:
                lock.write(
                    f"pid={os.getpid()}\n"
                    f"token={uuid.uuid4().hex}\n"
                )
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(project_id)
            if (
                expected_revision is not None
                and ledger.revision != expected_revision
            ):
                raise WorkflowConcurrencyError(
                    "Workflow ledger revision changed concurrently"
                )
            yield WorkflowLedgerSession(self, ledger)
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(
        self,
        record: WorkflowRecord,
        *,
        entry_id: str,
        recorded_at: datetime,
        expected_revision: int | None = None,
    ) -> WorkflowLedger:
        with self.exclusive(
            project_id=record.project_id,
            expected_revision=expected_revision,
        ) as session:
            return session.append(
                record,
                entry_id=entry_id,
                recorded_at=recorded_at,
            )

    def _atomic_save(self, ledger: WorkflowLedger) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / (
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open(
                "x",
                encoding="utf-8",
                newline="\n",
            ) as output:
                output.write(ledger.model_dump_json(indent=2))
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
