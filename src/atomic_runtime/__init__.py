"""Production atomic registry and execution gateway."""

from .gateway import AtomicExecutionGateway
from .models import (
    ATOMIC_REGISTRY_VERSION,
    AtomicExecutionContext,
    AtomicGatewayError,
    AtomicRegistryReference,
    SkillDescriptor,
)
from .registry import AtomicRegistryError, AtomicSkillRegistry


def build_production_registry() -> AtomicSkillRegistry:
    """Import the skill composition lazily to avoid workflow model cycles."""

    from .composition import build_production_registry as build

    return build()

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
