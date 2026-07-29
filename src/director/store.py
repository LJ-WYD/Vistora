"""Atomic append-only persistence for Director conversation/audit records."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from .models import (
    GENESIS_DIGEST,
    DirectorLedgerEntry,
    DirectorSessionLedger,
    DirectorSessionRecord,
    digest_json,
)


class DirectorStoreError(ValueError):
    pass


class DirectorIntegrityError(DirectorStoreError):
    pass


class DirectorConcurrencyError(DirectorStoreError):
    pass


class DirectorLedgerSession:
    def __init__(
        self,
        store: DirectorStore,
        ledger: DirectorSessionLedger,
    ) -> None:
        self._store = store
        self.ledger = ledger

    def append(
        self,
        record: DirectorSessionRecord,
        *,
        entry_id: str,
    ) -> DirectorSessionLedger:
        previous = (
            self.ledger.entries[-1].entry_digest
            if self.ledger.entries
            else GENESIS_DIGEST
        )
        entry = DirectorLedgerEntry.create(
            sequence=self.ledger.revision + 1,
            entry_id=entry_id,
            previous_entry_digest=previous,
            record=record,
        )
        entries = (*self.ledger.entries, entry)
        updated = DirectorSessionLedger(
            session_id=self.ledger.session_id,
            project_id=self.ledger.project_id,
            revision=len(entries),
            entries=entries,
            integrity_digest=digest_json(
                [item.entry_digest for item in entries]
            ),
        )
        self._store._atomic_save(updated)
        self.ledger = updated
        return updated


class DirectorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(
        cls,
        project_file: str | Path,
        *,
        session_id: str,
    ) -> DirectorStore:
        path = Path(project_file)
        return cls(
            path.with_name(f"{path.stem}.{session_id}.director.json")
        )

    def load(
        self,
        *,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> DirectorSessionLedger:
        if not self.path.exists():
            if session_id is None or project_id is None:
                raise DirectorStoreError(
                    "Director ledger does not exist and identity is unknown"
                )
            return DirectorSessionLedger.empty(
                session_id=session_id,
                project_id=project_id,
            )
        try:
            ledger = DirectorSessionLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise DirectorIntegrityError(
                "Director ledger is corrupt or failed integrity validation"
            ) from exc
        if session_id is not None and ledger.session_id != session_id:
            raise DirectorIntegrityError(
                "Director ledger session identity is mismatched"
            )
        if project_id is not None and ledger.project_id != project_id:
            raise DirectorIntegrityError(
                "Director ledger project identity is mismatched"
            )
        return ledger

    @staticmethod
    def _process_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
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
        try:
            values = dict(
                line.split("=", 1)
                for line in self.lock_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            )
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
        session_id: str,
        project_id: str,
        expected_revision: int | None = None,
    ) -> Iterator[DirectorLedgerSession]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open(
                "x",
                encoding="utf-8",
                newline="\n",
            )
        except FileExistsError:
            if not self._clear_dead_owner_lock():
                raise DirectorConcurrencyError(
                    "Another Director turn holds the session lock"
                )
            try:
                lock = self.lock_path.open(
                    "x",
                    encoding="utf-8",
                    newline="\n",
                )
            except FileExistsError as exc:
                raise DirectorConcurrencyError(
                    "Another Director turn acquired the session lock"
                ) from exc
        try:
            with lock:
                lock.write(
                    f"pid={os.getpid()}\n"
                    f"token={uuid.uuid4().hex}\n"
                )
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(
                session_id=session_id,
                project_id=project_id,
            )
            if (
                expected_revision is not None
                and ledger.revision != expected_revision
            ):
                raise DirectorConcurrencyError(
                    "Director ledger revision changed concurrently"
                )
            yield DirectorLedgerSession(self, ledger)
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(
        self,
        record: DirectorSessionRecord,
        *,
        entry_id: str,
        expected_revision: int,
    ) -> DirectorSessionLedger:
        with self.exclusive(
            session_id=record.session_id,
            project_id=record.project_id,
            expected_revision=expected_revision,
        ) as session:
            return session.append(record, entry_id=entry_id)

    def _atomic_save(self, ledger: DirectorSessionLedger) -> None:
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
