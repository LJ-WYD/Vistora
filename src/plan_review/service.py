"""Safe freshness wrapper for local plan-review consumers."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from timeline_query import TimelineSnapshot, TimelineSnapshotReference

from .engine import PlanDiffEngine, PlanDiffValidationError
from .models import PlanDiffRequest, PlanReviewEnvelope


PlanReviewRequestProvider = Callable[[], PlanDiffRequest]


def load_plan_diff_request(path: str | Path) -> PlanDiffRequest:
    """Load one explicit fixture/reference request for the absent Director."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return PlanDiffRequest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise PlanDiffValidationError(
            f"Invalid plan-review request: {exc}"
        ) from exc


class PlanReviewService:
    """Return a browser-safe current/stale/invalid review envelope."""

    @staticmethod
    def review(
        request: PlanDiffRequest,
        snapshot: TimelineSnapshot,
        registry: Mapping[str, Any],
    ) -> PlanReviewEnvelope:
        current_ref = TimelineSnapshotReference.from_snapshot(snapshot)
        if request.snapshot_ref != current_ref:
            return PlanReviewEnvelope(
                review_state="stale",
                message=(
                    "The timeline snapshot identity, content, or revision "
                    "changed after this proposal was created. Regenerate the "
                    "plan review before confirmation."
                ),
            )
        try:
            diff = PlanDiffEngine.generate(request, snapshot, registry)
        except PlanDiffValidationError as exc:
            detail = str(exc)
            if "schema drifted" in detail:
                message = (
                    "Atomic registry or tool schema drifted; regenerate the "
                    "review."
                )
            elif "unregistered tool" in detail:
                message = (
                    "The proposal uses an unregistered atomic tool and cannot "
                    "be reviewed."
                )
            elif "invalid arguments" in detail:
                message = (
                    "A proposed step has invalid arguments and cannot be "
                    "reviewed."
                )
            else:
                message = (
                    "The proposal failed detached validation. Regenerate it "
                    "against the current snapshot and tool schemas."
                )
            return PlanReviewEnvelope(
                review_state="invalid",
                message=message,
            )
        return PlanReviewEnvelope(
            review_state="current",
            diff=diff,
            diff_digest=diff.digest(),
            message=(
                "This is a read-only preview. Confirmation and execution are "
                "not available in the plan-review boundary."
            ),
        )
