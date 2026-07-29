"""Atomic hash-chained production ledger and material catalog stores."""

from __future__ import annotations

import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from director import digest_json

from .models import (
    GENESIS_DIGEST,
    MaterialCatalogDocument,
    MaterialCatalogEntry,
    MaterialProductionEvent,
    MaterialProductionLedger,
)


class MaterialProductionStoreError(ValueError):
    pass


class MaterialProductionIntegrityError(MaterialProductionStoreError):
    pass


class MaterialProductionConcurrencyError(MaterialProductionStoreError):
    pass


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            output.write(value.model_dump_json(indent=2))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class MaterialProductionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path):
        path = Path(project_file)
        return cls(path.with_name(f"{path.stem}.production.json"))

    def load(self, *, project_id=None):
        if not self.path.exists():
            if project_id is None:
                raise MaterialProductionStoreError(
                    "Material-production project is unknown"
                )
            return MaterialProductionLedger.empty(project_id=project_id)
        try:
            ledger = MaterialProductionLedger.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise MaterialProductionIntegrityError(
                "Material-production ledger is corrupt or tampered"
            ) from exc
        if project_id is not None and ledger.project_id != project_id:
            raise MaterialProductionIntegrityError(
                "Material-production project is mismatched"
            )
        return ledger

    @contextmanager
    def exclusive(self, *, project_id: str, expected_revision: int):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise MaterialProductionConcurrencyError(
                "Another material-production operation is in progress"
            ) from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            ledger = self.load(project_id=project_id)
            if ledger.revision != expected_revision:
                raise MaterialProductionConcurrencyError(
                    "Material-production history changed; refresh first"
                )
            yield ledger
        finally:
            self.lock_path.unlink(missing_ok=True)

    def append(self, ledger, *, event_id, record):
        values = {
            "sequence": ledger.revision + 1,
            "event_id": event_id,
            "record": record,
            "previous_event_digest": (
                ledger.events[-1].event_digest
                if ledger.events
                else GENESIS_DIGEST
            ),
        }
        shell = MaterialProductionEvent.model_construct(
            schema_name="vistora.material-production.event",
            schema_version="1.0.0",
            event_digest=GENESIS_DIGEST,
            **values,
        )
        event = MaterialProductionEvent(
            **values,
            event_digest=digest_json(
                shell.model_dump(mode="json", exclude={"event_digest"})
            ),
        )
        events = (*ledger.events, event)
        updated = MaterialProductionLedger(
            project_id=ledger.project_id,
            revision=len(events),
            events=events,
            integrity_digest=digest_json(
                [candidate.event_digest for candidate in events]
            ),
        )
        _atomic_json(self.path, updated)
        return updated


class MaterialCatalogStore:
    def __init__(
        self,
        path: str | Path,
        *,
        media_root: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        self.media_root = (
            Path(media_root)
            if media_root is not None
            else self.path.with_name("materials")
        )
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    @classmethod
    def for_project_file(cls, project_file: str | Path):
        path = Path(project_file)
        return cls(
            path.with_name(f"{path.stem}.material-catalog.json"),
            media_root=path.parent / "materials",
        )

    def load(self, *, project_id=None):
        if not self.path.exists():
            if project_id is None:
                raise MaterialProductionStoreError(
                    "Material catalog project is unknown"
                )
            return MaterialCatalogDocument.empty(project_id=project_id)
        try:
            catalog = MaterialCatalogDocument.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise MaterialProductionIntegrityError(
                "Material catalog is corrupt or tampered"
            ) from exc
        if project_id is not None and catalog.project_id != project_id:
            raise MaterialProductionIntegrityError(
                "Material catalog project is mismatched"
            )
        return catalog

    def register(
        self,
        catalog: MaterialCatalogDocument,
        *,
        entry: MaterialCatalogEntry,
        staged_path: Path,
    ) -> MaterialCatalogDocument:
        try:
            lock = self.lock_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError as exc:
            raise MaterialProductionConcurrencyError(
                "Another material-catalog operation is in progress"
            ) from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n")
                lock.flush()
                os.fsync(lock.fileno())
            current = self.load(project_id=catalog.project_id)
            if current != catalog:
                raise MaterialProductionConcurrencyError(
                    "Material catalog changed; refresh before registering"
                )
            if any(
                existing.artifact_sha256 == entry.artifact_sha256
                for existing in catalog.entries
            ):
                raise MaterialProductionStoreError(
                    "Artifact hash is already registered"
                )
            if any(
                existing.material_id == entry.material_id
                for existing in catalog.entries
            ):
                raise MaterialProductionStoreError(
                    "Material ID is already registered"
                )
            target = (
                self.media_root / entry.managed_relative_path
            ).resolve()
            root = self.media_root.resolve()
            if root not in target.parents:
                raise MaterialProductionStoreError(
                    "Catalog target escapes managed media root"
                )
            if target.exists():
                raise MaterialProductionIntegrityError(
                    "Managed catalog target already exists without a record"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f".{target.name}.{uuid.uuid4().hex}.tmp"
            )
            try:
                shutil.copyfile(staged_path, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            entries = (*catalog.entries, entry)
            updated = MaterialCatalogDocument(
                project_id=catalog.project_id,
                revision=len(entries),
                entries=entries,
                integrity_digest=digest_json(
                    [
                        candidate.model_dump(mode="json")
                        for candidate in entries
                    ]
                ),
            )
            try:
                _atomic_json(self.path, updated)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return updated
        finally:
            self.lock_path.unlink(missing_ok=True)

    def resolve_uri(self, uri: str) -> Path | None:
        if not uri.startswith("material://"):
            return None
        if not self.path.exists():
            return None
        material_id = uri.removeprefix("material://")
        catalog = self.load()
        matches = [
            entry for entry in catalog.entries
            if entry.material_id == material_id
        ]
        if len(matches) != 1:
            return None
        target = (self.media_root / matches[0].managed_relative_path).resolve()
        root = self.media_root.resolve()
        if root not in target.parents or not target.is_file():
            return None
        return target
