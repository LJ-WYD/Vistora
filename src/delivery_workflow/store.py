"""Atomic project-scoped O32 delivery plan and manifest store."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

from director import digest_json
from .models import DeliveryLedger


class DeliveryStoreError(ValueError): pass
class DeliveryIntegrityError(DeliveryStoreError): pass
class DeliveryConcurrencyError(DeliveryStoreError): pass


class DeliveryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @classmethod
    def for_project_file(cls, project_file):
        path = Path(project_file)
        return cls(path.with_name(path.stem + ".deliveries.json"))

    def load(self, *, project_id=None):
        if not self.path.exists():
            if project_id is None: raise DeliveryStoreError("Delivery project identity is unknown")
            return DeliveryLedger.empty(project_id)
        try:
            ledger = DeliveryLedger.model_validate_json(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DeliveryIntegrityError("Delivery ledger is corrupt or tampered") from exc
        if project_id is not None and ledger.project_id != project_id:
            raise DeliveryIntegrityError("Delivery ledger crosses project")
        return ledger

    @contextmanager
    def exclusive(self, *, project_id, expected_revision):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try: lock = self.lock_path.open("x", encoding="utf-8")
        except FileExistsError as exc: raise DeliveryConcurrencyError("Another delivery action is running") from exc
        try:
            with lock:
                lock.write(f"pid={os.getpid()}\ntoken={uuid.uuid4().hex}\n"); lock.flush(); os.fsync(lock.fileno())
            ledger = self.load(project_id=project_id)
            if ledger.revision != expected_revision: raise DeliveryConcurrencyError("Delivery history changed; refresh first")
            yield ledger
        finally: self.lock_path.unlink(missing_ok=True)

    def _write(self, ledger):
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as output:
                output.write(ledger.model_dump_json(indent=2)); output.write("\n"); output.flush(); os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally: temporary.unlink(missing_ok=True)
        return ledger

    def append_plan(self, plan, *, expected_revision):
        with self.exclusive(project_id=plan.project.project_id, expected_revision=expected_revision) as ledger:
            if any(item.delivery_plan_id == plan.delivery_plan_id for item in ledger.plans): raise DeliveryStoreError("Delivery plan ID is duplicated")
            plans = (*ledger.plans, plan)
            payload = {"plans": [item.plan_digest for item in plans], "manifests": [item.manifest_digest for item in ledger.manifests]}
            return self._write(DeliveryLedger(project_id=ledger.project_id, revision=ledger.revision + 1, plans=plans, manifests=ledger.manifests, integrity_digest=digest_json(payload)))

    def append_manifest(self, manifest, *, expected_revision):
        with self.exclusive(project_id=manifest.project.project_id, expected_revision=expected_revision) as ledger:
            if any(item.manifest_id == manifest.manifest_id for item in ledger.manifests): raise DeliveryStoreError("Delivery manifest ID is duplicated")
            manifests = (*ledger.manifests, manifest)
            payload = {"plans": [item.plan_digest for item in ledger.plans], "manifests": [item.manifest_digest for item in manifests]}
            return self._write(DeliveryLedger(project_id=ledger.project_id, revision=ledger.revision + 1, plans=ledger.plans, manifests=manifests, integrity_digest=digest_json(payload)))
