"""The only production dispatcher for registered atomic skill execution."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from contracts import (
    AtomicToolRequestEnvelope,
    AtomicToolResultEnvelope,
    ToolError,
)

from .models import AtomicExecutionContext, digest_json
from .registry import AtomicSkillRegistry


_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:\b[A-Z]:[\\/]|\\\\)[^\s,;]+"
    r"|(?<![\w:])/(?:[^/\s]+/)+[^/\s,;]+"
)


def _redact_text(value: str) -> str:
    return _ABSOLUTE_PATH.sub("[redacted-path]", value)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith("material://"):
            return value
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class AtomicExecutionGateway:
    """Validate exact bindings and normalize every skill result."""

    def __init__(
        self,
        registry: AtomicSkillRegistry,
        *,
        clock: Callable[[], datetime] = (
            lambda: datetime.now(timezone.utc)
        ),
        result_id_factory: Callable[[str], str] = (
            lambda request_id: (
                f"result_{digest_json(request_id)[7:31]}"
            )
        ),
    ) -> None:
        self.registry = registry
        self._clock = clock
        self._result_id_factory = result_id_factory
        self._lock = threading.RLock()
        self._replays: dict[
            str, tuple[str, AtomicToolResultEnvelope]
        ] = {}

    def execute(
        self,
        request: AtomicToolRequestEnvelope,
        context: AtomicExecutionContext,
    ) -> AtomicToolResultEnvelope:
        started = self._clock()
        request_digest = digest_json(request.model_dump(mode="json"))
        with self._lock:
            replay = self._replays.get(context.idempotency_key)
            if replay is not None:
                previous_digest, previous = replay
                if previous_digest != request_digest:
                    return self._error(
                        request,
                        started,
                        "idempotency_conflict",
                        "The idempotency key was already used for a "
                        "different atomic request.",
                    )
                return previous.model_copy(update={"replayed": True})

            preflight = self._preflight(request, context, started)
            if preflight is not None:
                self._replays[context.idempotency_key] = (
                    request_digest,
                    preflight,
                )
                return preflight
            descriptor = self.registry.descriptor(request.tool_name)
            try:
                validated = request.validate_against_registry(self.registry)
                raw = self.registry[request.tool_name].execute(
                    validated.model_dump(mode="python")
                )
                normalized = _redact(raw)
                output = self.registry.output_model(
                    request.tool_name
                ).model_validate(normalized)
                result = AtomicToolResultEnvelope(
                    result_id=self._result_id_factory(request.request_id),
                    request_id=request.request_id,
                    execution_id=request.execution_id,
                    step_id=request.step_id,
                    tool_name=request.tool_name,
                    status="success",
                    payload=output.model_dump(mode="json"),
                    started_at=started,
                    finished_at=self._clock(),
                    registry_digest=(
                        self.registry.reference.registry_digest
                    ),
                )
            except ValidationError:
                result = self._error(
                    request,
                    started,
                    "atomic_result_invalid",
                    "The atomic tool returned a result that did not match "
                    "its registered result schema.",
                    recovery_required=(
                        descriptor.mutation
                        and descriptor.transactionality
                        not in {"atomic_project_state", "atomic_file"}
                    ),
                )
            except Exception:
                result = self._error(
                    request,
                    started,
                    "atomic_dispatch_failed",
                    "The registered atomic tool failed during execution.",
                    retryable=(
                        descriptor.retry_safety
                        != "unsafe"
                    ),
                    recovery_required=(
                        descriptor.mutation
                        and descriptor.transactionality
                        not in {"atomic_project_state", "atomic_file"}
                    ),
                )
            self._replays[context.idempotency_key] = (
                request_digest,
                result,
            )
            return result

    def _preflight(
        self,
        request: AtomicToolRequestEnvelope,
        context: AtomicExecutionContext,
        started: datetime,
    ) -> AtomicToolResultEnvelope | None:
        if context.registry_ref != self.registry.reference:
            return self._error(
                request,
                started,
                "registry_reference_stale",
                "The atomic registry reference drifted before dispatch.",
            )
        if (
            request.project_id != context.project_id
            or request.confirmation_id != context.confirmation_id
        ):
            return self._error(
                request,
                started,
                "confirmation_binding_mismatch",
                "Atomic execution does not match the confirmed project gate.",
            )
        try:
            descriptor = self.registry.descriptor(request.tool_name)
        except ValueError:
            return self._error(
                request,
                started,
                "atomic_tool_unknown",
                "The requested atomic tool is not registered.",
            )
        if not set(descriptor.side_effects).issubset(
            context.allowed_side_effects
        ):
            return self._error(
                request,
                started,
                "side_effect_policy_rejected",
                "The caller is not authorized for this tool's declared "
                "side effects.",
            )
        try:
            request.validate_against_registry(self.registry)
        except (TypeError, ValueError, ValidationError):
            return self._error(
                request,
                started,
                "atomic_arguments_invalid",
                "Atomic tool arguments do not match the registered schema.",
            )
        return None

    def _error(
        self,
        request: AtomicToolRequestEnvelope,
        started: datetime,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        recovery_required: bool = False,
    ) -> AtomicToolResultEnvelope:
        return AtomicToolResultEnvelope(
            result_id=self._result_id_factory(request.request_id),
            request_id=request.request_id,
            execution_id=request.execution_id,
            step_id=request.step_id,
            tool_name=request.tool_name,
            status=("recovery_required" if recovery_required else "error"),
            error=ToolError(
                code=code,
                message=_redact_text(message),
                retryable=retryable,
                details={"recovery_required": recovery_required},
            ),
            started_at=started,
            finished_at=self._clock(),
            registry_digest=self.registry.reference.registry_digest,
        )
