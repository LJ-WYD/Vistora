"""Deterministic read queries over a completed plan diff."""

from __future__ import annotations

from collections import Counter

from contracts import PlanReference
from timeline_query import TimelineSnapshotReference

from .models import PlanChange, PlanDiffDocument


class PlanDiffQueryError(ValueError):
    """A query does not match the immutable diff identity."""


class PlanDiffQuery:
    def __init__(
        self,
        diff: PlanDiffDocument,
        *,
        current_snapshot_ref: TimelineSnapshotReference | None = None,
    ) -> None:
        if (
            current_snapshot_ref is not None
            and current_snapshot_ref != diff.snapshot_ref
        ):
            raise PlanDiffQueryError(
                "Plan diff is stale for the requested project revision"
            )
        self._diff = diff

    def for_plan(
        self,
        plan_ref: PlanReference,
    ) -> tuple[PlanChange, ...]:
        if plan_ref != self._diff.plan_ref:
            raise PlanDiffQueryError("Plan reference does not match the diff")
        return self._diff.changes

    def for_clip(
        self,
        *,
        track_key: str,
        clip_id: str,
    ) -> tuple[PlanChange, ...]:
        return tuple(
            change
            for change in self._diff.changes
            if change.entity.entity_kind == "clip"
            and change.entity.track_key == track_key
            and change.entity.entity_id == clip_id
        )

    def for_evidence(self, evidence_id: str) -> tuple[PlanChange, ...]:
        return tuple(
            change
            for change in self._diff.changes
            if any(
                evidence.evidence_id == evidence_id
                for evidence in change.evidence
            )
        )

    def warning_summary(self) -> dict[str, object]:
        warning_changes = tuple(
            change
            for change in self._diff.changes
            if change.severity in {"warning", "blocker"}
        )
        return {
            "review_status": self._diff.review_status,
            "warning_count": sum(
                change.severity == "warning"
                for change in warning_changes
            ),
            "blocker_count": sum(
                change.severity == "blocker"
                for change in warning_changes
            ),
            "by_tool": dict(
                sorted(
                    Counter(
                        change.tool_name for change in warning_changes
                    ).items()
                )
            ),
            "change_ids": tuple(
                change.change_id for change in warning_changes
            ),
        }
