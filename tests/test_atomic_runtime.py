"""Focused production registry and gateway contract tests."""

from __future__ import annotations

import ast
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from atomic_runtime import (  # noqa: E402
    AtomicExecutionContext,
    AtomicExecutionGateway,
    AtomicRegistryError,
    AtomicSkillRegistry,
    SkillDescriptor,
    build_production_registry,
)
from atomic_runtime.models import digest_json  # noqa: E402
from contracts import (  # noqa: E402
    AtomicToolRequestEnvelope,
    PlanReference,
)
from plan_review import RegistrySchemaReference  # noqa: E402
from skills.base import BaseSkill  # noqa: E402


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: int


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str
    value: int


class EchoSkill(BaseSkill):
    name = "EchoSkill"
    description = "Echo one validated integer for an isolated runtime test."
    input_model = Input

    def __init__(self) -> None:
        self.calls = 0

    def run(self, params: Input) -> dict[str, Any]:
        self.calls += 1
        return {"status": "success", "value": params.value}


class ExplodingSkill(EchoSkill):
    name = "ExplodingSkill"
    description = "Raise a controlled failure for redaction tests."

    def run(self, params: Input) -> dict[str, Any]:
        self.calls += 1
        raise RuntimeError(
            r"decoder failed at C:\Users\private\secret.mov"
        )


class InvalidResultSkill(EchoSkill):
    name = "InvalidResultSkill"
    description = "Return a payload outside the registered result schema."

    def run(self, params: Input) -> dict[str, Any]:
        self.calls += 1
        return {"status": "success", "unexpected": params.value}


def _descriptor(
    skill: BaseSkill,
    *,
    side_effects: tuple[str, ...] = (),
    output_model: type[BaseModel] = Output,
) -> SkillDescriptor:
    input_schema = skill.input_model.model_json_schema()
    output_schema = output_model.model_json_schema()
    return SkillDescriptor(
        name=skill.name,
        skill_version="1.0.0",
        description=skill.description,
        input_schema_version="1.0.0",
        input_schema=input_schema,
        input_schema_digest=digest_json(input_schema),
        output_schema_version="1.0.0",
        output_schema=output_schema,
        output_schema_digest=digest_json(output_schema),
        side_effects=side_effects,
        mutation=bool(side_effects),
        transactionality=(
            "best_effort" if side_effects else "none"
        ),
        retry_safety="gateway_replay_only",
        preview_supported=True,
        rollback_support=(
            "checkpoint_restore" if "timeline" in side_effects else "none"
        ),
        required_capabilities=(),
    )


def _registry(
    skill: BaseSkill | None = None,
    *,
    revision: int = 1,
    side_effects: tuple[str, ...] = (),
) -> AtomicSkillRegistry:
    skill = skill or EchoSkill()
    return AtomicSkillRegistry(
        registry_id="registry_test_atomic",
        registry_revision=revision,
        entries=((skill, _descriptor(
            skill,
            side_effects=side_effects,
        ), Output),),
    )


def _request(
    tool_name: str,
    *,
    request_id: str = "request_atomic_test",
    confirmation_id: str = "confirmation_atomic_test",
    arguments: dict[str, Any] | None = None,
) -> AtomicToolRequestEnvelope:
    return AtomicToolRequestEnvelope(
        request_id=request_id,
        execution_id="execution_atomic_test",
        project_id="project_atomic_test",
        confirmation_id=confirmation_id,
        plan_ref=PlanReference(
            plan_id="plan_atomic_test",
            plan_version=1,
            plan_digest="sha256:" + ("1" * 64),
        ),
        step_id="step_atomic_test",
        tool_name=tool_name,
        arguments=arguments or {"value": 7},
        requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _context(
    registry: AtomicSkillRegistry,
    *,
    confirmation_id: str = "confirmation_atomic_test",
    allowed: tuple[str, ...] = (),
    key: str = "idempotency_atomic_test",
) -> AtomicExecutionContext:
    return AtomicExecutionContext(
        caller="workflow",
        registry_ref=registry.reference,
        project_id="project_atomic_test",
        confirmation_id=confirmation_id,
        allowed_side_effects=allowed,
        idempotency_key=key,
    )


def test_production_registry_is_deterministic_frozen_and_complete() -> None:
    first = build_production_registry()
    second = build_production_registry()
    assert first.reference == second.reference
    assert first.reference.registry_digest.startswith("sha256:")
    assert "Legacy index-addressed" in first.descriptor(
        "VideoModifyClipSkill"
    ).description
    assert tuple(first) == tuple(sorted(first))
    assert tuple(first) == (
        "VideoAddClipSkill",
        "VideoApplyManualEditsSkill",
        "VideoClearTimelineSkill",
        "VideoExportSkill",
        "VideoInsertOverwriteClipSkill",
        "VideoModifyClipSkill",
        "VideoMoveClipSkill",
        "VideoRemoveClipSkill",
        "VideoRestoreTimelineCheckpointSkill",
        "VideoSetClipPropertiesSkill",
        "VideoSplitClipSkill",
        "VideoTimelapseSkill",
        "VideoTrimClipSkill",
    )
    roundtrip = type(first.reference).model_validate_json(
        first.reference.model_dump_json()
    )
    assert roundtrip == first.reference
    with pytest.raises(TypeError):
        first["VideoClearTimelineSkill"] = object()  # type: ignore[index]


def test_legacy_schema_only_reference_loads_but_cannot_confirm_current() -> None:
    registry = build_production_registry()
    durable = RegistrySchemaReference.from_registry(registry)
    legacy = RegistrySchemaReference.from_registry(dict(registry))
    assert legacy.registry_digest is None
    assert durable.registry_digest == registry.reference.registry_digest
    assert legacy.schema_digest == durable.schema_digest
    assert legacy != durable


def test_registry_rejects_duplicate_non_skill_and_schema_drift() -> None:
    skill = EchoSkill()
    descriptor = _descriptor(skill)
    with pytest.raises(AtomicRegistryError, match="Duplicate"):
        AtomicSkillRegistry(
            registry_id="registry_test_atomic",
            registry_revision=1,
            entries=(
                (skill, descriptor, Output),
                (EchoSkill(), descriptor, Output),
            ),
        )
    with pytest.raises(AtomicRegistryError, match="inherit"):
        AtomicSkillRegistry(
            registry_id="registry_test_atomic",
            registry_revision=1,
            entries=((object(), descriptor, Output),),  # type: ignore[arg-type]
        )
    drifted = descriptor.model_copy(
        update={"input_schema": {"type": "object"}}
    )
    with pytest.raises(ValueError, match="digest"):
        SkillDescriptor.model_validate(drifted.model_dump(mode="json"))
    with pytest.raises(ValueError, match="Extra inputs"):
        SkillDescriptor.model_validate({
            **descriptor.model_dump(mode="json"),
            "unknown": True,
        })


def test_gateway_validates_policy_result_and_replay() -> None:
    skill = EchoSkill()
    registry = _registry(skill, side_effects=("timeline",))
    gateway = AtomicExecutionGateway(registry)
    request = _request(skill.name)

    rejected = gateway.execute(
        request,
        _context(registry, allowed=()),
    )
    assert rejected.status == "error"
    assert rejected.error.code == "side_effect_policy_rejected"
    assert skill.calls == 0

    result = gateway.execute(
        request.model_copy(update={"request_id": "request_allowed"}),
        _context(
            registry,
            allowed=("timeline",),
            key="idempotency_allowed",
        ),
    )
    assert result.status == "success"
    assert result.payload == {"status": "success", "value": 7}
    assert result.registry_digest == registry.reference.registry_digest
    replay = gateway.execute(
        request.model_copy(update={"request_id": "request_allowed"}),
        _context(
            registry,
            allowed=("timeline",),
            key="idempotency_allowed",
        ),
    )
    assert replay.replayed is True
    assert skill.calls == 1


def test_gateway_rejects_unconfirmed_drift_and_invalid_arguments() -> None:
    registry = _registry(side_effects=("timeline",))
    gateway = AtomicExecutionGateway(registry)
    request = _request("EchoSkill")
    mismatch = gateway.execute(
        request,
        _context(
            registry,
            confirmation_id="confirmation_other",
            allowed=("timeline",),
        ),
    )
    assert mismatch.error.code == "confirmation_binding_mismatch"

    drifted_context = _context(
        registry,
        allowed=("timeline",),
        key="idempotency_drift",
    ).model_copy(
        update={"registry_ref": _registry(revision=2).reference}
    )
    drifted = gateway.execute(request, drifted_context)
    assert drifted.error.code == "registry_reference_stale"

    invalid = gateway.execute(
        _request(
            "EchoSkill",
            request_id="request_invalid",
            arguments={"value": "not-an-int"},
        ),
        _context(
            registry,
            allowed=("timeline",),
            key="idempotency_invalid",
        ),
    )
    assert invalid.error.code == "atomic_arguments_invalid"


def test_gateway_redacts_exceptions_and_serializes_concurrent_replay() -> None:
    exploding = ExplodingSkill()
    registry = _registry(exploding, side_effects=("files",))
    failure = AtomicExecutionGateway(registry).execute(
        _request(exploding.name),
        _context(registry, allowed=("files",)),
    )
    assert failure.status == "recovery_required"
    assert failure.error.message == (
        "The registered atomic tool failed during execution."
    )
    assert "C:\\Users" not in failure.model_dump_json()

    echo = EchoSkill()
    registry = _registry(echo)
    gateway = AtomicExecutionGateway(registry)
    request = _request(echo.name)
    results = []

    def dispatch() -> None:
        results.append(gateway.execute(request, _context(registry)))

    threads = [threading.Thread(target=dispatch) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert echo.calls == 1
    assert len(results) == 4
    assert sum(result.replayed for result in results) == 3


def test_gateway_rejects_result_schema_drift() -> None:
    skill = InvalidResultSkill()
    registry = _registry(skill)
    result = AtomicExecutionGateway(registry).execute(
        _request(skill.name),
        _context(registry),
    )
    assert result.status == "error"
    assert result.error.code == "atomic_result_invalid"
    assert result.payload == {}


def test_cli_registry_output_is_versioned_and_descriptor_complete(
    capsys,
) -> None:
    import main

    main.list_skills()
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_name"] == "vistora.atomic-skill-registry"
    assert payload["registry"]["registry_digest"]
    assert len(payload["skills"]) == 13
    assert all(item["output_schema_digest"] for item in payload["skills"])


def test_cli_unknown_tool_returns_structured_gateway_envelope(capsys) -> None:
    import main

    with pytest.raises(SystemExit) as caught:
        main.run_skill("UnknownAtomicSkill", "{}")
    assert caught.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_name"] == "vistora.atomic-tool-result"
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "atomic_tool_unknown"


def test_skill_implementations_are_imported_only_by_composition_root() -> None:
    violations: dict[str, list[str]] = {}
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        if relative.startswith("skills/") or relative == (
            "atomic_runtime/composition.py"
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        direct = sorted(
            name for name in imports
            if name.startswith("skills.video_")
        )
        if direct:
            violations[relative] = direct
    assert not violations
