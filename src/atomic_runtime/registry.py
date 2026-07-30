"""Deterministic immutable registry for production atomic skills."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from skills.base import BaseSkill

from .models import (
    AtomicRegistryReference,
    SkillDescriptor,
    digest_json,
)


class AtomicRegistryError(ValueError):
    """The registry composition or a descriptor is unsafe."""


class AtomicSkillRegistry(Mapping[str, BaseSkill]):
    """Immutable mapping plus exact descriptors and durable identity."""

    def __init__(
        self,
        *,
        registry_id: str,
        registry_revision: int,
        entries: Sequence[tuple[BaseSkill, SkillDescriptor, type[BaseModel]]],
    ) -> None:
        skills: dict[str, BaseSkill] = {}
        descriptors: dict[str, SkillDescriptor] = {}
        outputs: dict[str, type[BaseModel]] = {}
        for skill, descriptor, output_model in entries:
            if not isinstance(skill, BaseSkill):
                raise AtomicRegistryError(
                    "Every registered implementation must inherit BaseSkill"
                )
            if not isinstance(output_model, type) or not issubclass(
                output_model, BaseModel
            ):
                raise AtomicRegistryError(
                    f"{descriptor.name} has no valid result model"
                )
            name = descriptor.name
            if name in skills:
                raise AtomicRegistryError(
                    f"Duplicate atomic skill name/version: "
                    f"{name}@{descriptor.skill_version}"
                )
            if skill.name != name:
                raise AtomicRegistryError(
                    f"Atomic skill identity mismatch for {name!r}"
                )
            input_model = getattr(skill, "input_model", None)
            if not isinstance(input_model, type) or not issubclass(
                input_model, BaseModel
            ):
                raise AtomicRegistryError(
                    f"{name} has no valid Pydantic input model"
                )
            if descriptor.input_schema != input_model.model_json_schema():
                raise AtomicRegistryError(
                    f"Atomic skill input schema drifted for {name}"
                )
            if descriptor.output_schema != output_model.model_json_schema():
                raise AtomicRegistryError(
                    f"Atomic skill result schema drifted for {name}"
                )
            skills[name] = skill
            descriptors[name] = descriptor
            outputs[name] = output_model
        if not skills:
            raise AtomicRegistryError("Atomic registry cannot be empty")
        self._skills = MappingProxyType(dict(sorted(skills.items())))
        self._descriptors = MappingProxyType(
            dict(sorted(descriptors.items()))
        )
        self._outputs = MappingProxyType(dict(sorted(outputs.items())))
        descriptor_payload = [
            item.model_dump(mode="json")
            for item in self._descriptors.values()
        ]
        legacy_input_payload = [
            {
                "name": name,
                "parameters": skill.input_model.model_json_schema(),
            }
            for name, skill in self._skills.items()
        ]
        self._reference = AtomicRegistryReference(
            registry_id=registry_id,
            registry_revision=registry_revision,
            tool_names=tuple(self._skills),
            input_schema_digest=digest_json(legacy_input_payload),
            registry_digest=digest_json(descriptor_payload),
        )

    def __getitem__(self, name: str) -> BaseSkill:
        return self._skills[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._skills)

    def __len__(self) -> int:
        return len(self._skills)

    @property
    def reference(self) -> AtomicRegistryReference:
        return self._reference

    def descriptor(self, name: str) -> SkillDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as exc:
            raise AtomicRegistryError(f"Unknown atomic skill: {name}") from exc

    def output_model(self, name: str) -> type[BaseModel]:
        try:
            return self._outputs[name]
        except KeyError as exc:
            raise AtomicRegistryError(f"Unknown atomic skill: {name}") from exc

    def public_descriptors(self) -> tuple[SkillDescriptor, ...]:
        return tuple(self._descriptors.values())
