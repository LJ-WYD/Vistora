"""Versioned AI packaging plan contracts and decision service."""

from .models import (
    EffectIntent,
    EffectMaskReference,
    EffectModelRequirement,
    EffectObjectTarget,
    EffectParameter,
    EffectPlanChange,
    EffectPlanConfirmation,
    EffectPlanEvent,
    EffectPlanLedger,
    EffectPlanReview,
    EffectPlanView,
    EffectProductionPlan,
    EffectPromptSpecification,
    EffectStyleReference,
    EffectTask,
    EffectTimeRange,
    EffectTrackingReference,
)
from .service import EffectPlanService
from .capabilities import (
    EFFECT_CAPABILITY_IDS,
    DeterministicEffectFixtureAdapter,
    EffectAdapterDescriptor,
    EffectAdapterRegistry,
    EffectAdapterRegistryReference,
    EffectAdapterRequest,
    EffectAdapterResult,
    EffectArtifactCandidate,
    EffectCapabilityDescriptor,
    ManualEffectImportAdapter,
    UnconfiguredEffectAdapter,
    build_effect_adapter_registry,
    effect_capability_descriptors,
)
from .execution import (
    EffectAcceptanceCheck,
    EffectCapabilityExecutionService,
    EffectExecutionBinding,
    EffectExecutionError,
    EffectExecutionReport,
    EffectExecutionRequest,
    EffectTaskExecutionReport,
    EffectTaskInput,
)
from .store import (
    EffectPlanConcurrencyError,
    EffectPlanError,
    EffectPlanIntegrityError,
    EffectPlanStore,
)

__all__ = [name for name in globals() if name.startswith("Effect")] + [
    "EFFECT_CAPABILITY_IDS",
    "DeterministicEffectFixtureAdapter",
    "ManualEffectImportAdapter",
    "UnconfiguredEffectAdapter",
    "build_effect_adapter_registry",
    "effect_capability_descriptors",
]
