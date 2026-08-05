"""Provider-neutral execution capabilities for reviewed AI packaging tasks.

The production composition intentionally contains only unavailable placeholders.
Deterministic and manual-import adapters are explicit test/local integration
boundaries and never imply that an online provider is configured.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import Field, model_validator

from director import digest_json

from .models import Digest, EffectModel, EffectTask, StableId


EFFECT_CAPABILITY_IDS = (
    "ai_music",
    "ai_sound_effect",
    "ai_voice",
    "background_replacement",
    "frame_interpolation",
    "generative_b_roll",
    "generative_transition",
    "localized_inpainting",
    "object_removal",
    "stylization",
)

EffectCapabilityId = Literal[
    "ai_music",
    "ai_sound_effect",
    "ai_voice",
    "background_replacement",
    "frame_interpolation",
    "generative_b_roll",
    "generative_transition",
    "localized_inpainting",
    "object_removal",
    "stylization",
]


class EffectCapabilityDescriptor(EffectModel):
    schema_name: Literal["vistora.effect-capability"] = "vistora.effect-capability"
    capability_id: EffectCapabilityId
    title: str = Field(min_length=1, max_length=120)
    modality: Literal["video", "image", "audio", "multimodal"]
    accepted_output_roles: tuple[
        Literal["video_clip", "transparent_layer", "effect_layer"], ...
    ] = Field(min_length=1)
    required_task_fields: tuple[StableId, ...] = Field(min_length=1)
    acceptance_dimensions: tuple[StableId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_sets(self):
        for value, label in (
            (self.accepted_output_roles, "output roles"),
            (self.required_task_fields, "required fields"),
            (self.acceptance_dimensions, "acceptance dimensions"),
        ):
            if value != tuple(sorted(set(value))):
                raise ValueError(f"Effect capability {label} must be unique and ordered")
        return self


class EffectAdapterDescriptor(EffectModel):
    schema_name: Literal["vistora.effect-adapter"] = "vistora.effect-adapter"
    adapter_id: StableId
    adapter_version: str = Field(min_length=1, max_length=40)
    capability_ids: tuple[EffectCapabilityId, ...] = Field(min_length=1)
    execution_kind: Literal[
        "external_provider",
        "manual_import",
        "local_deterministic_test",
    ]
    configured: bool
    max_concurrency: int = Field(ge=1, le=64)
    input_schema_digest: Digest
    result_schema_digest: Digest
    limitation: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def truthful(self):
        if self.capability_ids != tuple(sorted(set(self.capability_ids))):
            raise ValueError("Effect adapter capabilities must be unique and ordered")
        if self.configured == (self.limitation is not None):
            raise ValueError("Configured state and limitation disagree")
        return self


class EffectAdapterRegistryReference(EffectModel):
    schema_name: Literal["vistora.effect-adapter-registry"] = (
        "vistora.effect-adapter-registry"
    )
    registry_id: StableId
    registry_revision: int = Field(ge=1)
    capabilities: tuple[EffectCapabilityDescriptor, ...]
    adapters: tuple[EffectAdapterDescriptor, ...]
    registry_digest: Digest

    @classmethod
    def create(cls, *, registry_id, registry_revision, capabilities, adapters):
        capabilities = tuple(sorted(capabilities, key=lambda item: item.capability_id))
        adapters = tuple(sorted(adapters, key=lambda item: item.adapter_id))
        payload = {
            "capabilities": [item.model_dump(mode="json") for item in capabilities],
            "adapters": [item.model_dump(mode="json") for item in adapters],
        }
        return cls(
            registry_id=registry_id,
            registry_revision=registry_revision,
            capabilities=capabilities,
            adapters=adapters,
            registry_digest=digest_json(payload),
        )

    @model_validator(mode="after")
    def exact(self):
        capability_ids = [item.capability_id for item in self.capabilities]
        adapter_ids = [item.adapter_id for item in self.adapters]
        if capability_ids != sorted(set(capability_ids)):
            raise ValueError("Effect capability registry is ambiguous")
        if tuple(capability_ids) != EFFECT_CAPABILITY_IDS:
            raise ValueError("Effect capability registry is incomplete")
        if adapter_ids != sorted(set(adapter_ids)):
            raise ValueError("Effect adapter registry is ambiguous")
        known = set(capability_ids)
        if any(not set(item.capability_ids).issubset(known) for item in self.adapters):
            raise ValueError("Effect adapter exposes an unknown capability")
        payload = {
            "capabilities": [item.model_dump(mode="json") for item in self.capabilities],
            "adapters": [item.model_dump(mode="json") for item in self.adapters],
        }
        if self.registry_digest != digest_json(payload):
            raise ValueError("Effect adapter registry digest mismatched")
        return self


class EffectAdapterRequest(EffectModel):
    schema_name: Literal["vistora.effect-adapter-request"] = (
        "vistora.effect-adapter-request"
    )
    job_id: StableId
    execution_request_id: StableId
    project_id: StableId
    confirmation_id: StableId
    task: EffectTask
    idempotency_key: StableId
    input_token: StableId | None = None


class EffectArtifactCandidate(EffectModel):
    schema_name: Literal["vistora.effect-artifact-candidate"] = (
        "vistora.effect-artifact-candidate"
    )
    artifact_id: StableId
    job_id: StableId
    task_id: StableId
    capability_id: EffectCapabilityId
    output_role: Literal["video_clip", "transparent_layer", "effect_layer"]
    staging_relative_path: str = Field(min_length=1, max_length=300)
    content_digest: Digest
    media_kind: Literal["video", "image", "audio", "fixture_manifest"]

    @model_validator(mode="after")
    def safe_relative_path(self):
        value = self.staging_relative_path.replace("\\", "/")
        if (
            value.startswith("/")
            or ":/" in value
            or value == ".."
            or value.startswith("../")
            or "/../" in value
        ):
            raise ValueError("Effect artifact path escapes staging")
        return self


class EffectAdapterResult(EffectModel):
    schema_name: Literal["vistora.effect-adapter-result"] = (
        "vistora.effect-adapter-result"
    )
    job_id: StableId
    adapter_id: StableId
    capability_id: EffectCapabilityId
    status: Literal["succeeded", "failed", "not_configured", "needs_manual_input"]
    artifact: EffectArtifactCandidate | None = None
    error_code: StableId | None = None
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def truthful(self):
        if self.status == "succeeded":
            if self.artifact is None or self.error_code is not None:
                raise ValueError("Successful effect result needs exactly one artifact")
        elif self.artifact is not None or self.error_code is None:
            raise ValueError("Unsuccessful effect result needs a typed error")
        if self.artifact is not None and (
            self.artifact.job_id != self.job_id
            or self.artifact.capability_id != self.capability_id
        ):
            raise ValueError("Effect result artifact linkage drifted")
        return self


class EffectProductionAdapter(Protocol):
    def descriptor(self) -> EffectAdapterDescriptor: ...
    def submit(self, request: EffectAdapterRequest, *, staging_root: Path) -> EffectAdapterResult: ...


def _schema_digest(model):
    return digest_json(model.model_json_schema())


_CAPABILITY_FACTS = {
    "background_replacement": ("Background replacement", "video", ("effect_layer", "transparent_layer", "video_clip"), ("mask_ref", "object_target", "prompt", "timeline_range"), ("edge_quality", "temporal_consistency")),
    "object_removal": ("Object removal", "video", ("effect_layer", "video_clip"), ("mask_ref", "object_target", "prompt", "timeline_range"), ("fill_consistency", "temporal_consistency")),
    "localized_inpainting": ("Localized inpainting", "multimodal", ("effect_layer", "transparent_layer", "video_clip"), ("mask_ref", "object_target", "prompt", "timeline_range"), ("boundary_quality", "prompt_alignment")),
    "stylization": ("Stylization", "multimodal", ("effect_layer", "transparent_layer", "video_clip"), ("prompt", "style_references", "timeline_range"), ("content_preservation", "style_alignment")),
    "frame_interpolation": ("Frame interpolation", "video", ("video_clip",), ("parameters", "timeline_range"), ("motion_continuity", "timing_accuracy")),
    "generative_transition": ("Generative transition", "video", ("effect_layer", "video_clip"), ("prompt", "timeline_range"), ("boundary_match", "temporal_continuity")),
    "generative_b_roll": ("Generative B-roll", "video", ("video_clip",), ("prompt", "style_references", "timeline_range"), ("prompt_alignment", "technical_compliance")),
    "ai_voice": ("AI voice", "audio", ("effect_layer",), ("parameters", "prompt", "timeline_range"), ("pronunciation", "timing_accuracy")),
    "ai_music": ("AI music", "audio", ("effect_layer",), ("parameters", "prompt", "timeline_range"), ("duration_accuracy", "style_alignment")),
    "ai_sound_effect": ("AI sound effect", "audio", ("effect_layer",), ("prompt", "timeline_range"), ("duration_accuracy", "prompt_alignment")),
}


def effect_capability_descriptors():
    return tuple(
        EffectCapabilityDescriptor(
            capability_id=capability_id,
            title=values[0],
            modality=values[1],
            accepted_output_roles=tuple(sorted(values[2])),
            required_task_fields=tuple(sorted(values[3])),
            acceptance_dimensions=tuple(sorted(values[4])),
        )
        for capability_id, values in sorted(_CAPABILITY_FACTS.items())
    )


class EffectAdapterRegistry:
    def __init__(self, adapters: tuple[EffectProductionAdapter, ...], *, revision=1):
        descriptors = [adapter.descriptor() for adapter in adapters]
        if len({item.adapter_id for item in descriptors}) != len(descriptors):
            raise ValueError("Effect adapter ID is duplicated")
        self._adapters = {item.adapter_id: adapter for item, adapter in zip(descriptors, adapters)}
        self.revision = revision

    def reference(self):
        return EffectAdapterRegistryReference.create(
            registry_id="vistora_effect_capabilities",
            registry_revision=self.revision,
            capabilities=effect_capability_descriptors(),
            adapters=tuple(adapter.descriptor() for adapter in self._adapters.values()),
        )

    def select(self, capability_id):
        matches = [
            adapter for adapter in self._adapters.values()
            if adapter.descriptor().configured
            and capability_id in adapter.descriptor().capability_ids
        ]
        return sorted(matches, key=lambda item: item.descriptor().adapter_id)[0] if matches else None

    def public_view(self):
        reference = self.reference()
        return {
            "schema_name": "vistora.effect-capability-view",
            "schema_version": "1.0.0",
            "registry_revision": reference.registry_revision,
            "registry_digest": reference.registry_digest,
            "capabilities": tuple(
                {
                    "capability_id": capability.capability_id,
                    "title": capability.title,
                    "configured": any(
                        adapter.configured and capability.capability_id in adapter.capability_ids
                        for adapter in reference.adapters
                    ),
                    "status": "available" if any(
                        adapter.configured and capability.capability_id in adapter.capability_ids
                        for adapter in reference.adapters
                    ) else "not_configured",
                    "limitation": next((
                        adapter.limitation for adapter in reference.adapters
                        if capability.capability_id in adapter.capability_ids and adapter.limitation
                    ), "No provider or manual-import adapter is configured."),
                }
                for capability in reference.capabilities
            ),
            "message": "AI packaging providers are not configured by default.",
        }


class UnconfiguredEffectAdapter:
    def __init__(self, capability_id: EffectCapabilityId):
        if capability_id not in EFFECT_CAPABILITY_IDS:
            raise ValueError("Unknown effect capability")
        self.capability_id = capability_id

    def descriptor(self):
        return EffectAdapterDescriptor(
            adapter_id=f"unconfigured_{self.capability_id}",
            adapter_version="1.0.0",
            capability_ids=(self.capability_id,),
            execution_kind="external_provider",
            configured=False,
            max_concurrency=1,
            input_schema_digest=_schema_digest(EffectAdapterRequest),
            result_schema_digest=_schema_digest(EffectAdapterResult),
            limitation=f"No {self.capability_id.replace('_', '-')} provider is configured.",
        )

    def submit(self, request, *, staging_root):
        return EffectAdapterResult(
            job_id=request.job_id,
            adapter_id=self.descriptor().adapter_id,
            capability_id=self.capability_id,
            status="not_configured",
            error_code="effect_provider_not_configured",
            message=self.descriptor().limitation,
        )


class DeterministicEffectFixtureAdapter:
    """Explicit test-only adapter which emits a non-media fixture manifest."""

    def descriptor(self):
        return EffectAdapterDescriptor(
            adapter_id="deterministic_effect_fixture",
            adapter_version="1.0.0",
            capability_ids=EFFECT_CAPABILITY_IDS,
            execution_kind="local_deterministic_test",
            configured=True,
            max_concurrency=1,
            input_schema_digest=_schema_digest(EffectAdapterRequest),
            result_schema_digest=_schema_digest(EffectAdapterResult),
        )

    def submit(self, request, *, staging_root):
        payload = {
            "schema_name": "vistora.effect-fixture-artifact",
            "schema_version": "1.0.0",
            "capability_id": request.task.capability_id,
            "task_id": request.task.task_id,
            "task_digest": digest_json(request.task.model_dump(mode="json")),
            "output_role": request.task.output_role,
        }
        data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        relative = f"fixtures/{request.task.task_id}-{digest[7:19]}.json"
        destination = staging_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return EffectAdapterResult(
            job_id=request.job_id,
            adapter_id=self.descriptor().adapter_id,
            capability_id=request.task.capability_id,
            status="succeeded",
            artifact=EffectArtifactCandidate(
                artifact_id=f"effect_artifact_{digest[7:31]}",
                job_id=request.job_id,
                task_id=request.task.task_id,
                capability_id=request.task.capability_id,
                output_role=request.task.output_role,
                staging_relative_path=relative,
                content_digest=digest,
                media_kind="fixture_manifest",
            ),
            message="Deterministic test fixture created; no online provider was called.",
        )


class ManualEffectImportAdapter:
    """Copies an explicitly token-resolved local artifact into isolated staging."""

    def __init__(self, resolver: Callable[[str], Path | None]):
        self.resolver = resolver

    def descriptor(self):
        return EffectAdapterDescriptor(
            adapter_id="manual_effect_import",
            adapter_version="1.0.0",
            capability_ids=EFFECT_CAPABILITY_IDS,
            execution_kind="manual_import",
            configured=True,
            max_concurrency=1,
            input_schema_digest=_schema_digest(EffectAdapterRequest),
            result_schema_digest=_schema_digest(EffectAdapterResult),
        )

    def submit(self, request, *, staging_root):
        if request.input_token is None:
            return EffectAdapterResult(
                job_id=request.job_id,
                adapter_id=self.descriptor().adapter_id,
                capability_id=request.task.capability_id,
                status="needs_manual_input",
                error_code="effect_manual_input_required",
                message="A server-side opaque import token is required.",
            )
        source = self.resolver(request.input_token)
        if source is None or not source.is_file():
            return EffectAdapterResult(
                job_id=request.job_id,
                adapter_id=self.descriptor().adapter_id,
                capability_id=request.task.capability_id,
                status="failed",
                error_code="effect_manual_input_unavailable",
                message="The approved manual import is unavailable.",
            )
        data_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        relative = f"manual/{request.task.task_id}-{data_digest[:12]}{source.suffix.lower()}"
        destination = staging_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        media_kind = "audio" if source.suffix.lower() in {".wav", ".mp3", ".m4a"} else "image" if source.suffix.lower() in {".png", ".jpg", ".jpeg"} else "video"
        return EffectAdapterResult(
            job_id=request.job_id,
            adapter_id=self.descriptor().adapter_id,
            capability_id=request.task.capability_id,
            status="succeeded",
            artifact=EffectArtifactCandidate(
                artifact_id=f"effect_artifact_{data_digest[:24]}",
                job_id=request.job_id,
                task_id=request.task.task_id,
                capability_id=request.task.capability_id,
                output_role=request.task.output_role,
                staging_relative_path=relative,
                content_digest=f"sha256:{data_digest}",
                media_kind=media_kind,
            ),
            message="Manual artifact copied into isolated effect staging.",
        )


def build_effect_adapter_registry(*, revision=1):
    """Production composition root: all online effect providers are unavailable."""

    return EffectAdapterRegistry(
        tuple(UnconfiguredEffectAdapter(item) for item in EFFECT_CAPABILITY_IDS),
        revision=revision,
    )
