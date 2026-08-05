"""Shared atomic timeline persistence used by every new edit skill."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core import timeline_manager
from core.timeline import TimelineConfig
from timeline_query import TimelineSnapshotService

from .engine import TimelineEditEngine
from .engine import SourceAudioResolver, SourceDurationResolver
from .models import TimelineEditOutcome


class TimelineEditTransaction:
    @staticmethod
    def current_bytes() -> bytes | None:
        path = Path(timeline_manager.PROJECT_FILE)
        return path.read_bytes() if path.exists() else None

    @staticmethod
    def restore_bytes(content: bytes | None) -> None:
        path = Path(timeline_manager.PROJECT_FILE)
        if content is None:
            path.unlink(missing_ok=True)
            return
        TimelineEditTransaction._replace(path, content)

    @staticmethod
    def _replace(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def replace_config(cls, timeline: TimelineConfig) -> None:
        """Durably replace the project file through the shared transaction."""

        cls._replace(
            Path(timeline_manager.PROJECT_FILE),
            timeline.model_dump_json(indent=2).encode("utf-8"),
        )

    @classmethod
    def apply(
        cls,
        operation: Callable[
            [TimelineEditEngine],
            tuple[TimelineConfig, TimelineEditOutcome],
        ],
        *,
        id_factory: Callable[[str], str] | None = None,
        source_duration_resolver: SourceDurationResolver | None = None,
        source_audio_resolver: SourceAudioResolver | None = None,
    ) -> dict[str, Any]:
        prior = cls.current_bytes()
        current = timeline_manager.TimelineManager.get_current_timeline()
        before = TimelineSnapshotService.snapshot(current)
        engine = (
            TimelineEditEngine(
                current,
                id_factory=id_factory,
                source_duration_resolver=source_duration_resolver,
                source_audio_resolver=source_audio_resolver,
            )
            if id_factory is not None
            else TimelineEditEngine(
                current,
                source_duration_resolver=source_duration_resolver,
                source_audio_resolver=source_audio_resolver,
            )
        )
        try:
            updated, outcome = operation(engine)
            TimelineEditEngine.validate(updated)
            cls.replace_config(updated)
            after = TimelineSnapshotService.snapshot_current()
            return {
                "status": "success",
                "operation": outcome.operation,
                "track_id": outcome.track_id,
                "track_key": outcome.track_key,
                "direct_clip_ids": list(outcome.direct_clip_ids),
                "consequential_clip_ids": list(
                    outcome.consequential_clip_ids
                ),
                "created_clip_ids": list(outcome.created_clip_ids),
                "modified_clip_ids": list(outcome.modified_clip_ids),
                "deleted_clip_ids": list(outcome.deleted_clip_ids),
                "consequential_subtitle_cue_ids": list(
                    outcome.consequential_subtitle_cue_ids
                ),
                "created_transition_ids": list(
                    outcome.created_transition_ids
                ),
                "modified_transition_ids": list(
                    outcome.modified_transition_ids
                ),
                "deleted_transition_ids": list(
                    outcome.deleted_transition_ids
                ),
                "created_automation_ids": list(
                    outcome.created_automation_ids
                ),
                "modified_automation_ids": list(
                    outcome.modified_automation_ids
                ),
                "deleted_automation_ids": list(
                    outcome.deleted_automation_ids
                ),
                "warnings": list(outcome.warnings),
                "before_snapshot_id": before.snapshot_id,
                "after_snapshot_id": after.snapshot_id,
                "project_id": after.project_id,
                "revision": after.revision,
                "timeline_digest": after.timeline_digest,
            }
        except Exception:
            cls.restore_bytes(prior)
            raise
