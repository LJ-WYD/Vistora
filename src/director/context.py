"""Read-only context construction for Director Agent reasoning."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plan_review import RegistrySchemaReference
from timeline_query import TimelineSnapshot, TimelineSnapshotReference

from .models import (
    DirectorMaterialFact,
    DirectorReadContext,
    DirectorToolSchema,
    digest_json,
)


class DirectorContextService:
    """Build path-free context only from detached read models and schemas."""

    @staticmethod
    def build(
        snapshot: TimelineSnapshot,
        registry: Mapping[str, Any],
        *,
        materials: tuple[DirectorMaterialFact, ...] = (),
    ) -> DirectorReadContext:
        registry_ref = RegistrySchemaReference.from_registry(registry)
        tool_schemas = []
        for name, skill in sorted(registry.items()):
            descriptor_reader = getattr(registry, "descriptor", None)
            if descriptor_reader is not None:
                descriptor = descriptor_reader(name)
                input_schema = descriptor.input_schema
            else:
                input_model = getattr(skill, "input_model", None)
                if input_model is None:
                    raise ValueError(
                        f"Registered tool {name!r} has no input schema"
                    )
                input_schema = input_model.model_json_schema()
            tool_schemas.append(
                DirectorToolSchema(
                    tool_name=name,
                    input_schema=input_schema,
                    schema_digest=digest_json(input_schema),
                )
            )
        return DirectorReadContext(
            snapshot_ref=TimelineSnapshotReference.from_snapshot(snapshot),
            registry_ref=registry_ref,
            project_summary={
                "project_id": snapshot.project_id,
                "revision": snapshot.revision,
                "snapshot_id": snapshot.snapshot_id,
                "timeline_digest": snapshot.timeline_digest,
                "width": snapshot.width,
                "height": snapshot.height,
                "fps": snapshot.fps,
                "duration_seconds": snapshot.duration_seconds,
                "track_count": snapshot.track_count,
                "clip_count": snapshot.clip_count,
                "video_clip_count": snapshot.video_clip_count,
                "audio_clip_count": snapshot.audio_clip_count,
                "empty": snapshot.empty,
            },
            materials=tuple(sorted(materials, key=lambda item: item.material_id)),
            tool_schemas=tuple(tool_schemas),
        )
