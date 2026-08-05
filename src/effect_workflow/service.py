"""Read-only review and explicit decision boundary for effect plans."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from director import digest_json
from timeline_query import TimelineSnapshotReference, TimelineSnapshotService

from .models import (
    EffectPlanChange,
    EffectPlanConfirmation,
    EffectPlanReview,
    EffectPlanView,
    EffectProductionPlan,
)
from .store import EffectPlanError, EffectPlanStore


def _now():
    return datetime.now(timezone.utc)


def _identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


class EffectPlanService:
    def __init__(
        self,
        *,
        store: EffectPlanStore,
        project_id: str,
        snapshot_provider=TimelineSnapshotService.snapshot_current,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[str], str] = _identifier,
    ):
        self.store = store
        self.project_id = project_id
        self.snapshot_provider = snapshot_provider
        self.clock = clock
        self.id_factory = id_factory

    def _current(self):
        return TimelineSnapshotReference.from_snapshot(self.snapshot_provider())

    @staticmethod
    def _validate_targets(plan, snapshot):
        tracks = {
            track.track_id: track
            for track in getattr(snapshot, "tracks", ())
        }
        if not tracks:
            raise EffectPlanError("Effect review requires detached timeline tracks")
        evidence = {
            item.evidence_id: item for item in plan.intent.source_evidence
        }
        for task in plan.tasks:
            track = tracks.get(task.track_id)
            if track is None:
                raise EffectPlanError("Effect task references an unknown track")
            clips = {clip.clip_id: clip for clip in track.clips}
            clip = clips.get(task.clip_id)
            if clip is None:
                raise EffectPlanError("Effect task references an unknown clip")
            if (
                task.timeline_range.start_seconds < clip.timeline_start_seconds
                or task.timeline_range.end_seconds > clip.timeline_end_seconds
            ):
                raise EffectPlanError("Effect task range exceeds its clip")
            used = [
                evidence[item]
                for item in task.object_target.source_evidence_ids
            ]
            if any(item.material_id != clip.source.source_id for item in used):
                raise EffectPlanError("Effect object evidence crosses clip source")
            if task.mask_ref is not None:
                if task.mask_ref.clip_id != task.clip_id:
                    raise EffectPlanError("Effect mask crosses clip identity")
                masks = {
                    mask.mask_id: mask
                    for mask in getattr(clip, "masks", ())
                }
                mask = masks.get(task.mask_ref.mask_id)
                if mask is None or task.mask_ref.mask_digest != digest_json(
                    mask.model_dump(mode="json")
                ):
                    raise EffectPlanError("Effect mask reference is missing or stale")

    def review(self, plan: EffectProductionPlan, *, expected_revision: int):
        snapshot = self.snapshot_provider()
        current_ref = TimelineSnapshotReference.from_snapshot(snapshot)
        if plan.snapshot_ref != current_ref or plan.snapshot_ref.project_id != self.project_id:
            raise EffectPlanError("Effect plan snapshot is stale or cross-project")
        self._validate_targets(plan, snapshot)
        ledger = self.store.load(project_id=self.project_id)
        previous = [
            event.plan for event in ledger.events
            if event.plan is not None and event.plan.effect_plan_id == plan.effect_plan_id
        ]
        if previous and (
            plan.plan_version != previous[-1].plan_version + 1
            or plan.intent.director_plan_ref.plan_id
            != previous[-1].intent.director_plan_ref.plan_id
        ):
            raise EffectPlanError("Effect plan version or Director binding drifted")
        if not previous and plan.plan_version != 1:
            raise EffectPlanError("First effect plan version must be one")
        before = {task.task_id: task for task in previous[-1].tasks} if previous else {}
        after = {task.task_id: task for task in plan.tasks}
        changes = []
        for task_id in sorted(before.keys() | after.keys()):
            old, new = before.get(task_id), after.get(task_id)
            if old is None:
                kind, summary = "added", f"Add effect task {new.capability_id}."
            elif new is None:
                kind, summary = "removed", f"Remove effect task {old.capability_id}."
            elif old == new:
                continue
            else:
                kind, summary = "changed", f"Revise effect task {new.capability_id}."
            changes.append(EffectPlanChange(
                change_id=self.id_factory("effect_change"),
                change_type=kind,
                task_id=task_id,
                before_digest=digest_json(old.model_dump(mode="json")) if old else None,
                after_digest=digest_json(new.model_dump(mode="json")) if new else None,
                summary=summary,
            ))
        if not changes:
            raise EffectPlanError("Effect plan revision contains no changes")
        values = {
            "review_id": self.id_factory("effect_review"),
            "effect_plan_id": plan.effect_plan_id,
            "plan_version": plan.plan_version,
            "plan_digest": plan.digest(),
            "snapshot_ref": plan.snapshot_ref,
            "changes": tuple(changes),
            "warnings": (
                "No production effect provider is configured in O27.",
            ),
            "created_at": self.clock(),
        }
        shell = EffectPlanReview.model_construct(
            **values,
            schema_name="vistora.effect-plan-review",
            schema_version="1.0.0",
            review_digest="sha256:" + ("0" * 64),
        )
        review = EffectPlanReview(
            **values,
            review_digest=digest_json(shell.model_dump(mode="json", exclude={"review_digest"})),
        )
        with self.store.exclusive(project_id=self.project_id, expected_revision=expected_revision) as current:
            return review, self.store.append(
                current,
                event_id=self.id_factory("effect_event"),
                event_type="reviewed",
                plan=plan,
                review=review,
                recorded_at=self.clock(),
            )

    def decide(self, review_id: str, *, decision: str, confirmed_by: str, expected_revision: int):
        if decision not in {"confirmed", "rejected"}:
            raise EffectPlanError("Invalid effect-plan decision")
        with self.store.exclusive(project_id=self.project_id, expected_revision=expected_revision) as ledger:
            matches = [
                (event.plan, event.review) for event in ledger.events
                if event.review is not None and event.review.review_id == review_id
            ]
            if len(matches) != 1:
                raise EffectPlanError("Unknown effect-plan review")
            plan, review = matches[0]
            assert plan is not None and review is not None
            if plan.snapshot_ref != self._current():
                raise EffectPlanError("Effect-plan review is stale")
            confirmation = EffectPlanConfirmation(
                confirmation_id=self.id_factory("effect_confirmation"),
                effect_plan_id=plan.effect_plan_id,
                plan_version=plan.plan_version,
                plan_digest=plan.digest(),
                review_id=review.review_id,
                review_digest=review.review_digest,
                snapshot_ref=plan.snapshot_ref,
                decision=decision,
                confirmed_by=confirmed_by,
                recorded_at=self.clock(),
            )
            updated = self.store.append(
                ledger,
                event_id=self.id_factory("effect_event"),
                event_type=decision,
                confirmation=confirmation,
                recorded_at=self.clock(),
            )
        return confirmation, updated

    def confirmed(self, confirmation_id: str):
        ledger = self.store.load(project_id=self.project_id)
        matches = [
            event.confirmation for event in ledger.events
            if event.confirmation is not None
            and event.confirmation.confirmation_id == confirmation_id
        ]
        if len(matches) != 1 or matches[0].decision != "confirmed":
            raise EffectPlanError("Exact confirmed effect plan is unavailable")
        confirmation = matches[0]
        plans = [
            event.plan for event in ledger.events
            if event.plan is not None and event.review.review_id == confirmation.review_id
        ]
        if len(plans) != 1 or plans[0].snapshot_ref != self._current():
            raise EffectPlanError("Confirmed effect plan is stale or unavailable")
        return plans[0], confirmation

    def view(self):
        ledger = self.store.load(project_id=self.project_id)
        plans = tuple({
            "effect_plan_id": event.plan.effect_plan_id,
            "plan_version": event.plan.plan_version,
            "plan_digest": event.plan.digest(),
            "review_id": event.review.review_id,
            "task_count": len(event.plan.tasks),
            "tasks": tuple({
                "task_id": task.task_id,
                "capability_id": task.capability_id,
                "shot_id": task.shot_id,
                "clip_id": task.clip_id,
                "start_seconds": task.timeline_range.start_seconds,
                "end_seconds": task.timeline_range.end_seconds,
                "output_role": task.output_role,
            } for task in event.plan.tasks),
        } for event in ledger.events if event.plan is not None)
        decisions = tuple({
            "confirmation_id": event.confirmation.confirmation_id,
            "review_id": event.confirmation.review_id,
            "decision": event.confirmation.decision,
        } for event in ledger.events if event.confirmation is not None)
        state = "empty"
        if ledger.events:
            state = {
                "reviewed": "reviewable",
                "confirmed": "confirmed",
                "rejected": "rejected",
            }[ledger.events[-1].event_type]
        return EffectPlanView(
            project_id=self.project_id,
            revision=ledger.revision,
            state=state,
            plans=plans,
            decisions=decisions,
        )
