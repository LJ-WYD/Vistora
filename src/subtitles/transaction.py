"""Atomic project-state transaction for subtitle operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core import timeline_manager
from core.timeline import TimelineConfig
from timeline_edit import TimelineEditTransaction
from timeline_query import TimelineSnapshotService

from .engine import SubtitleEditEngine
from .models import SubtitleEditOutcome


class SubtitleEditTransaction:
    @classmethod
    def apply(
        cls,
        operation: Callable[[SubtitleEditEngine], tuple[TimelineConfig, SubtitleEditOutcome]],
    ) -> dict[str, Any]:
        prior = TimelineEditTransaction.current_bytes()
        current = timeline_manager.TimelineManager.get_current_timeline()
        before = TimelineSnapshotService.snapshot(current)
        try:
            updated, outcome = operation(SubtitleEditEngine(current))
            TimelineEditTransaction.replace_config(updated)
            after = TimelineSnapshotService.snapshot_current()
            return {
                **outcome.model_dump(
                    mode="json",
                    exclude={"schema_name", "schema_version"},
                ),
                "before_snapshot_id": before.snapshot_id,
                "after_snapshot_id": after.snapshot_id,
                "project_id": after.project_id,
                "revision": after.revision,
                "timeline_digest": after.timeline_digest,
            }
        except Exception:
            TimelineEditTransaction.restore_bytes(prior)
            raise
