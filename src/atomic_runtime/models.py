"""Frozen contracts for the production atomic-skill runtime boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ATOMIC_REGISTRY_VERSION = "1.0.0"
StableId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class AtomicRuntimeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
    schema_version: Literal["1.0.0"] = ATOMIC_REGISTRY_VERSION


SideEffect = Literal["timeline", "media", "files", "external"]
Transactionality = Literal[
    "none",
    "best_effort",
    "atomic_project_state",
    "atomic_file",
]
RetrySafety = Literal[
    "unsafe",
    "gateway_replay_only",
    "intrinsically_idempotent",
]
RollbackSupport = Literal[
    "none",
    "checkpoint_restore",
    "self_compensating",
]


class SkillDescriptor(AtomicRuntimeModel):
    """Public, durable metadata for one exact registered skill version."""

    schema_name: Literal["vistora.atomic-skill-descriptor"] = (
        "vistora.atomic-skill-descriptor"
    )
    name: StableId
    skill_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    description: str = Field(min_length=1)
    input_schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    input_schema: dict[str, Any]
    input_schema_digest: Sha256Digest
    output_schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    output_schema: dict[str, Any]
    output_schema_digest: Sha256Digest
    side_effects: tuple[SideEffect, ...] = ()
    mutation: bool
    transactionality: Transactionality
    retry_safety: RetrySafety
    preview_supported: bool
    rollback_support: RollbackSupport
    compensation_tool: StableId | None = None
    required_capabilities: tuple[StableId, ...] = ()

    @model_validator(mode="after")
    def metadata_is_exact(self) -> SkillDescriptor:
        if self.input_schema_digest != digest_json(self.input_schema):
            raise ValueError("Input schema digest does not match its schema")
        if self.output_schema_digest != digest_json(self.output_schema):
            raise ValueError("Output schema digest does not match its schema")
        if self.side_effects != tuple(sorted(set(self.side_effects))):
            raise ValueError("Side effects must be unique and stably sorted")
        if self.required_capabilities != tuple(
            sorted(set(self.required_capabilities))
        ):
            raise ValueError(
                "Required capabilities must be unique and stably sorted"
            )
        if self.mutation != bool(self.side_effects):
            raise ValueError(
                "Mutation must truthfully match declared side effects"
            )
        if (
            self.rollback_support == "self_compensating"
        ) != (self.compensation_tool is not None):
            raise ValueError(
                "A compensation tool is valid only for self compensation"
            )
        return self


class AtomicRegistryReference(AtomicRuntimeModel):
    """Exact durable identity for a composed registry."""

    schema_name: Literal["vistora.atomic-registry-reference"] = (
        "vistora.atomic-registry-reference"
    )
    registry_id: StableId
    registry_version: Literal["1.0.0"] = ATOMIC_REGISTRY_VERSION
    registry_revision: int = Field(ge=1)
    tool_names: tuple[StableId, ...]
    input_schema_digest: Sha256Digest
    registry_digest: Sha256Digest

    @model_validator(mode="after")
    def names_are_stable(self) -> AtomicRegistryReference:
        if not self.tool_names:
            raise ValueError("Atomic registry cannot be empty")
        if self.tool_names != tuple(sorted(set(self.tool_names))):
            raise ValueError("Registry tool names must be unique and sorted")
        return self


class AtomicExecutionContext(AtomicRuntimeModel):
    """Fail-closed caller policy supplied independently from tool arguments."""

    schema_name: Literal["vistora.atomic-execution-context"] = (
        "vistora.atomic-execution-context"
    )
    caller: Literal["workflow", "manual_edit", "rollback", "cli_compatibility"]
    registry_ref: AtomicRegistryReference
    project_id: StableId
    confirmation_id: StableId
    allowed_side_effects: tuple[SideEffect, ...]
    idempotency_key: StableId
    low_level_manual_acknowledged: bool = False

    @model_validator(mode="after")
    def policy_is_explicit(self) -> AtomicExecutionContext:
        if self.allowed_side_effects != tuple(
            sorted(set(self.allowed_side_effects))
        ):
            raise ValueError(
                "Allowed side effects must be unique and stably sorted"
            )
        if (
            self.caller == "cli_compatibility"
        ) != self.low_level_manual_acknowledged:
            raise ValueError(
                "Only the explicit compatibility CLI may acknowledge "
                "low-level manual execution"
            )
        return self


class AtomicGatewayError(AtomicRuntimeModel):
    schema_name: Literal["vistora.atomic-gateway-error"] = (
        "vistora.atomic-gateway-error"
    )
    code: StableId
    message: str = Field(min_length=1)
    retryable: bool = False
    recovery_required: bool = False
