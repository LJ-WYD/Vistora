"""Production atomic registry and execution gateway."""

from collections.abc import Callable
from typing import Any

from .gateway import AtomicExecutionGateway
from .models import (
    ATOMIC_REGISTRY_VERSION,
    AtomicExecutionContext,
    AtomicGatewayError,
    AtomicRegistryReference,
    SkillDescriptor,
)
from .registry import AtomicRegistryError, AtomicSkillRegistry


def build_production_registry(
    *,
    timeline_id_factory: Callable[[str], str] | None = None,
    subtitle_alignment_service: Any | None = None,
    subtitle_sync_qc_service: Any | None = None,
) -> AtomicSkillRegistry:
    """Import the skill composition lazily to avoid workflow model cycles."""

    from .composition import build_production_registry as build

    return build(
        timeline_id_factory=timeline_id_factory,
        subtitle_alignment_service=subtitle_alignment_service,
        subtitle_sync_qc_service=subtitle_sync_qc_service,
    )

__all__ = [
    "ATOMIC_REGISTRY_VERSION",
    "AtomicExecutionContext",
    "AtomicExecutionGateway",
    "AtomicGatewayError",
    "AtomicRegistryError",
    "AtomicRegistryReference",
    "AtomicSkillRegistry",
    "SkillDescriptor",
    "build_production_registry",
]
