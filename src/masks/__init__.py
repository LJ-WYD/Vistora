"""Versioned mask/compositing contracts and deterministic render helpers."""

from .models import (
    CopyClipMasksInput,
    ReplaceClipMasksInput,
    SetClipCompositeInput,
    SetClipMaskInput,
)
from .runtime import mask_alpha_expression

__all__ = [
    "CopyClipMasksInput",
    "ReplaceClipMasksInput",
    "SetClipCompositeInput",
    "SetClipMaskInput",
    "mask_alpha_expression",
]
