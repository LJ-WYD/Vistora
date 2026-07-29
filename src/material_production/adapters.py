"""Provider-neutral material-production adapter registry and local adapters."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from director import digest_json

from .models import (
    AdapterCapability,
    AdapterJobUpdate,
    AdapterRegistryReference,
    ArtifactCandidate,
    ProductionJobRequest,
)


def _now():
    return datetime.now(timezone.utc)


def _schema_digest(value) -> str:
    return digest_json(value.model_json_schema())


class MaterialProductionAdapter(Protocol):
    def capability(self) -> AdapterCapability:
        ...

    def submit(
        self,
        request: ProductionJobRequest,
        *,
        staging_root: Path,
    ) -> AdapterJobUpdate:
        ...

    def poll(
        self,
        request: ProductionJobRequest,
        *,
        provider_opaque_ref: str,
        staging_root: Path,
    ) -> AdapterJobUpdate:
        ...

    def cancel(
        self,
        request: ProductionJobRequest,
        *,
        provider_opaque_ref: str,
    ) -> AdapterJobUpdate:
        ...


class AdapterRegistry:
    def __init__(
        self,
        adapters: tuple[MaterialProductionAdapter, ...],
        *,
        registry_id: str = "material_production_adapters",
        registry_revision: int = 1,
    ) -> None:
        self.adapters = {
            adapter.capability().adapter_id: adapter
            for adapter in adapters
        }
        if len(self.adapters) != len(adapters):
            raise ValueError("Material-production adapter ID is duplicated")
        self.registry_id = registry_id
        self.registry_revision = registry_revision

    def reference(self) -> AdapterRegistryReference:
        return AdapterRegistryReference.create(
            registry_id=self.registry_id,
            registry_revision=self.registry_revision,
            adapters=tuple(
                adapter.capability()
                for adapter in self.adapters.values()
            ),
        )

    def select(self, capability_id: str):
        candidates = [
            adapter
            for adapter in self.adapters.values()
            if (
                capability_id
                in adapter.capability().capability_ids
                and adapter.capability().configured
            )
        ]
        return sorted(
            candidates,
            key=lambda item: item.capability().adapter_id,
        )[0] if candidates else None


class ManualImportAdapter:
    """Truthful local import adapter backed by server-side opaque tokens."""

    def __init__(
        self,
        resolver: Callable[[str], Path | None],
        *,
        clock: Callable[[], datetime] = _now,
        configured: bool = True,
    ) -> None:
        self.resolver = resolver
        self.clock = clock
        self.configured = configured

    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            adapter_id="manual_import_local",
            adapter_version="1.0.0",
            capability_ids=("manual_import",),
            configured=self.configured,
            execution_kind="manual_import",
            max_concurrency=4,
            limitation=(
                None
                if self.configured
                else "No secure local import-token resolver is configured."
            ),
            input_schema_digest=_schema_digest(ProductionJobRequest),
            result_schema_digest=_schema_digest(AdapterJobUpdate),
        )

    def submit(self, request, *, staging_root):
        if not self.configured:
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id="manual_import_local",
                provider_opaque_ref=f"unconfigured_{request.job_id}",
                status="failed",
                progress=0,
                error_code="manual_import_unconfigured",
                message="The local import adapter is not configured.",
                updated_at=self.clock(),
            )
        opaque = f"manual_{request.job_id}"
        if request.input_token is None:
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id="manual_import_local",
                provider_opaque_ref=opaque,
                status="needs_input",
                progress=0,
                message="A validated local import token is required.",
                updated_at=self.clock(),
            )
        source = self.resolver(request.input_token)
        if source is None or not source.is_file():
            return AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id="manual_import_local",
                provider_opaque_ref=opaque,
                status="failed",
                progress=0,
                error_code="manual_import_unavailable",
                message="The opaque import token is unavailable.",
                updated_at=self.clock(),
            )
        relative = Path(request.run_id) / request.job_id / source.name
        target = (staging_root / relative).resolve()
        staging = staging_root.resolve()
        if staging not in target.parents:
            raise ValueError("Manual import target escapes staging")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id="manual_import_local",
            provider_opaque_ref=opaque,
            status="succeeded",
            progress=1,
            artifacts=(
                ArtifactCandidate(
                    artifact_id=f"artifact_{request.job_id}",
                    job_id=request.job_id,
                    task_id=request.task_id,
                    requirement_item_id=request.requirement_item_id,
                    staging_relative_path=relative.as_posix(),
                    claimed_mime_type=(
                        "video/mp4"
                        if source.suffix.lower() == ".mp4"
                        else "application/octet-stream"
                    ),
                ),
            ),
            message="The local import was copied into isolated staging.",
            updated_at=self.clock(),
        )

    def poll(self, request, *, provider_opaque_ref, staging_root):
        return self.submit(request, staging_root=staging_root)

    def cancel(self, request, *, provider_opaque_ref):
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id="manual_import_local",
            provider_opaque_ref=provider_opaque_ref,
            status="cancelled",
            progress=0,
            message="The pending local import was cancelled.",
            updated_at=self.clock(),
        )


class DeterministicLocalVideoAdapter:
    """Explicit test-only fake provider; never registered by production factory."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _now,
        fail_task_ids: tuple[str, ...] = (),
        corrupt_task_ids: tuple[str, ...] = (),
        capability_ids: tuple[str, ...] = ("video_generation",),
        width: int = 320,
        height: int = 180,
        fps: int = 24,
        duration_seconds: float = 2,
    ) -> None:
        if (
            not capability_ids
            or tuple(sorted(set(capability_ids))) != capability_ids
            or width <= 0
            or height <= 0
            or fps <= 0
            or duration_seconds <= 0
        ):
            raise ValueError("Deterministic adapter settings are invalid")
        self.clock = clock
        self.fail_task_ids = set(fail_task_ids)
        self.corrupt_task_ids = set(corrupt_task_ids)
        self.capability_ids = capability_ids
        self.width = width
        self.height = height
        self.fps = fps
        self.duration_seconds = duration_seconds
        self.submissions: dict[str, AdapterJobUpdate] = {}

    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            adapter_id="deterministic_local_video_test",
            adapter_version="1.0.0",
            capability_ids=self.capability_ids,
            configured=True,
            execution_kind="local_deterministic_test",
            max_concurrency=8,
            input_schema_digest=_schema_digest(ProductionJobRequest),
            result_schema_digest=_schema_digest(AdapterJobUpdate),
        )

    def submit(self, request, *, staging_root):
        if request.idempotency_key in self.submissions:
            return self.submissions[request.idempotency_key]
        opaque = "fake_" + hashlib.sha256(
            request.idempotency_key.encode()
        ).hexdigest()[:20]
        if request.task_id in self.fail_task_ids:
            update = AdapterJobUpdate(
                job_id=request.job_id,
                adapter_id=self.capability().adapter_id,
                provider_opaque_ref=opaque,
                status="failed",
                progress=0,
                error_code="synthetic_provider_failure",
                message="The deterministic fake provider failed as requested.",
                updated_at=self.clock(),
            )
            self.submissions[request.idempotency_key] = update
            return update
        relative = Path(request.run_id) / request.job_id / "artifact.mp4"
        target = (staging_root / relative).resolve()
        if staging_root.resolve() not in target.parents:
            raise ValueError("Deterministic adapter target escapes staging")
        target.parent.mkdir(parents=True, exist_ok=True)
        if request.task_id in self.corrupt_task_ids:
            target.write_bytes(b"not-media")
        else:
            seed = int(
                hashlib.sha256(request.task_id.encode()).hexdigest()[:2],
                16,
            )
            color = f"0x{seed:02x}{(seed + 31) % 256:02x}{(seed + 67) % 256:02x}"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        f"color=c={color}:s={self.width}x{self.height}:"
                        f"r={self.fps}:d={self.duration_seconds}"
                    ),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(target),
                ],
                check=True,
                capture_output=True,
            )
        update = AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=opaque,
            status="succeeded",
            progress=1,
            artifacts=(
                ArtifactCandidate(
                    artifact_id=f"artifact_{request.job_id}",
                    job_id=request.job_id,
                    task_id=request.task_id,
                    requirement_item_id=request.requirement_item_id,
                    staging_relative_path=relative.as_posix(),
                    claimed_mime_type="video/mp4",
                ),
            ),
            message="The deterministic fake provider created a local fixture.",
            updated_at=self.clock(),
        )
        self.submissions[request.idempotency_key] = update
        return update

    def poll(self, request, *, provider_opaque_ref, staging_root):
        return self.submissions.get(
            request.idempotency_key,
            self.submit(request, staging_root=staging_root),
        )

    def cancel(self, request, *, provider_opaque_ref):
        return AdapterJobUpdate(
            job_id=request.job_id,
            adapter_id=self.capability().adapter_id,
            provider_opaque_ref=provider_opaque_ref,
            status="cancelled",
            progress=0,
            message="The deterministic fake job was cancelled.",
            updated_at=self.clock(),
        )
