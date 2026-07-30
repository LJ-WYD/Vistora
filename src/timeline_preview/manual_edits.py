"""Confirmed manual-edit application service for the local preview."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from atomic_runtime import (
    AtomicExecutionContext,
    AtomicExecutionGateway,
    AtomicSkillRegistry,
)
from contracts import (
    AtomicToolRequestEnvelope,
    ManualClipRemove,
    ManualClipSplit,
    ManualClipUpdate,
    ManualEditChange,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualEditProposalReference,
    ManualEditReview,
    PlanReference,
)
from timeline_query import TimelineSnapshot


MANUAL_EDIT_TOOL_NAME = "VideoApplyManualEditsSkill"


class ManualEditValidationError(ValueError):
    """A user-authored proposal cannot be reviewed or applied safely."""


def _clip_state(clip: Any, order_index: int) -> dict[str, Any]:
    return {
        "clip_id": clip.clip_id,
        "order_index": order_index,
        "trim_in_seconds": clip.trim_in_seconds,
        "trim_out_seconds": clip.trim_out_seconds,
        "timeline_start_seconds": clip.timeline_start_seconds,
        "timeline_end_seconds": clip.timeline_end_seconds,
        "effective_duration_seconds": clip.effective_duration_seconds,
        "speed_factor": clip.speed_factor,
        "volume": clip.volume,
        "keep_audio": clip.keep_audio,
        "reverse": clip.reverse,
        "rotate_degrees": clip.rotate_degrees,
        "source_id": clip.source.source_id,
        "source_name": clip.source.display_name,
    }


def _find_unique_state_index(
    states: list[dict[str, Any]],
    clip_id: str,
) -> int:
    matches = [
        index
        for index, state in enumerate(states)
        if state["clip_id"] == clip_id
    ]
    if len(matches) != 1:
        raise ManualEditValidationError(
            f"Clip {clip_id!r} must identify exactly one current video clip"
        )
    return matches[0]


def review_manual_edit_proposal(
    snapshot: TimelineSnapshot,
    proposal: ManualEditProposal,
) -> ManualEditReview:
    """Validate and diff a proposal without mutating source or persistence."""

    if snapshot.project_id != proposal.base_project_id:
        raise ManualEditValidationError(
            "Proposal project does not match the current snapshot"
        )
    if snapshot.revision != proposal.base_revision:
        raise ManualEditValidationError(
            "Proposal revision does not match the current snapshot"
        )
    if snapshot.timeline_digest != proposal.base_timeline_digest:
        raise ManualEditValidationError(
            "Proposal timeline digest does not match the current snapshot"
        )

    video_tracks = [
        track for track in snapshot.tracks if track.track_key == "video"
    ]
    if len(video_tracks) != 1:
        raise ManualEditValidationError(
            "Manual editing requires exactly one current video track"
        )
    states = [
        _clip_state(clip, index)
        for index, clip in enumerate(video_tracks[0].clips)
    ]
    changes: list[ManualEditChange] = []

    for edit in proposal.edits:
        index = _find_unique_state_index(states, edit.clip_id)
        before = {**states[index], "order_index": index}
        if isinstance(edit, ManualClipRemove):
            states.pop(index)
            changes.append(
                ManualEditChange(
                    operation_id=edit.operation_id,
                    track_key=edit.track_key,
                    clip_id=edit.clip_id,
                    action="remove",
                    before=before,
                    after=None,
                )
            )
            if edit.mode == "ripple":
                duration = before["effective_duration_seconds"]
                old_end = before["timeline_end_seconds"]
                for state in states:
                    if state["timeline_start_seconds"] >= old_end - 1e-6:
                        previous = dict(state)
                        state["timeline_start_seconds"] -= duration
                        state["timeline_end_seconds"] -= duration
                        changes.append(
                            ManualEditChange(
                                operation_id=edit.operation_id,
                                track_key=edit.track_key,
                                clip_id=state["clip_id"],
                                action="update",
                                effect_kind="consequential",
                                before=previous,
                                after=dict(state),
                            )
                        )
            continue

        if isinstance(edit, ManualClipSplit):
            if any(
                state["clip_id"] == edit.right_clip_id
                for state in states
            ):
                raise ManualEditValidationError(
                    "Split output clip ID already exists"
                )
            if (
                edit.split_at_seconds
                <= before["timeline_start_seconds"] + 1e-6
                or edit.split_at_seconds
                >= before["timeline_end_seconds"] - 1e-6
            ):
                raise ManualEditValidationError(
                    "Split point must be inside the selected clip"
                )
            source_split = before["trim_in_seconds"] + (
                edit.split_at_seconds
                - before["timeline_start_seconds"]
            ) * before["speed_factor"]
            left = {
                **before,
                "trim_out_seconds": source_split,
                "timeline_end_seconds": edit.split_at_seconds,
                "effective_duration_seconds": (
                    edit.split_at_seconds
                    - before["timeline_start_seconds"]
                ),
            }
            right = {
                **before,
                "clip_id": edit.right_clip_id,
                "order_index": index + 1,
                "trim_in_seconds": source_split,
                "timeline_start_seconds": edit.split_at_seconds,
                "effective_duration_seconds": (
                    before["timeline_end_seconds"] - edit.split_at_seconds
                ),
            }
            states[index] = left
            states.insert(index + 1, right)
            changes.extend(
                (
                    ManualEditChange(
                        operation_id=edit.operation_id,
                        track_key=edit.track_key,
                        clip_id=edit.clip_id,
                        action="update",
                        before=before,
                        after=left,
                    ),
                    ManualEditChange(
                        operation_id=edit.operation_id,
                        track_key=edit.track_key,
                        clip_id=edit.right_clip_id,
                        action="create",
                        before=None,
                        after=right,
                    ),
                )
            )
            continue

        clip = video_tracks[0].clips[
            next(
                clip_index
                for clip_index, candidate in enumerate(video_tracks[0].clips)
                if candidate.clip_id == edit.clip_id
            )
        ]
        if edit.order_index >= len(states):
            raise ManualEditValidationError(
                f"Clip order {edit.order_index} is outside the current "
                f"video track range 0..{len(states) - 1}"
            )
        duration = (
            edit.trim_out_seconds - edit.trim_in_seconds
        ) / clip.speed_factor
        after = {
            **before,
            "order_index": edit.order_index,
            "trim_in_seconds": edit.trim_in_seconds,
            "trim_out_seconds": edit.trim_out_seconds,
            "timeline_start_seconds": edit.timeline_start_seconds,
            "timeline_end_seconds": (
                edit.timeline_start_seconds + duration
            ),
            "effective_duration_seconds": duration,
        }
        if after == before:
            raise ManualEditValidationError(
                f"Update for clip {edit.clip_id!r} does not change any field"
            )
        ripple_changes: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if edit.ripple:
            old_end = before["timeline_end_seconds"]
            delta = duration - before["effective_duration_seconds"]
            for state in states:
                if (
                    state["clip_id"] != edit.clip_id
                    and state["timeline_start_seconds"] >= old_end - 1e-6
                ):
                    previous = dict(state)
                    state["timeline_start_seconds"] += delta
                    state["timeline_end_seconds"] += delta
                    ripple_changes.append((previous, dict(state)))
        states[index] = after
        if edit.order_index != index:
            moved = states.pop(index)
            states.insert(edit.order_index, moved)
        changes.append(
            ManualEditChange(
                operation_id=edit.operation_id,
                track_key=edit.track_key,
                clip_id=edit.clip_id,
                action="update",
                before=before,
                after=after,
            )
        )
        changes.extend(
            ManualEditChange(
                operation_id=edit.operation_id,
                track_key=edit.track_key,
                clip_id=current["clip_id"],
                action="update",
                effect_kind="consequential",
                before=previous,
                after=current,
            )
            for previous, current in ripple_changes
        )

    return ManualEditReview(
        proposal_ref=ManualEditProposalReference.from_proposal(proposal),
        snapshot_id=snapshot.snapshot_id,
        changes=tuple(changes),
    )


class ManualEditApplicationService:
    """Review then registry-dispatch exact confirmed user-authored proposals."""

    def __init__(
        self,
        snapshot_provider: Callable[[], TimelineSnapshot],
        registry: Mapping[str, Any],
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._registry = registry
        self._gateway = (
            AtomicExecutionGateway(registry)
            if isinstance(registry, AtomicSkillRegistry)
            else None
        )

    def review(self, proposal_value: Any) -> tuple[
        ManualEditProposal,
        ManualEditReview,
    ]:
        try:
            proposal = ManualEditProposal.model_validate(proposal_value)
        except ValidationError as exc:
            raise ManualEditValidationError(str(exc)) from exc
        review = review_manual_edit_proposal(
            self._snapshot_provider(),
            proposal,
        )
        return proposal, review

    def apply(
        self,
        proposal_value: Any,
        confirmation_value: Any,
    ) -> dict[str, Any]:
        proposal, review = self.review(proposal_value)
        try:
            confirmation = ManualEditConfirmationRecord.model_validate(
                confirmation_value
            )
        except ValidationError as exc:
            raise ManualEditValidationError(str(exc)) from exc
        if not confirmation.confirms(proposal):
            raise ManualEditValidationError(
                "Apply requires confirmation of this exact manual proposal"
            )

        skill = self._registry.get(MANUAL_EDIT_TOOL_NAME)
        if skill is None:
            raise ManualEditValidationError(
                "The manual edit atomic tool is not registered"
            )
        if getattr(skill, "name", None) != MANUAL_EDIT_TOOL_NAME:
            raise ManualEditValidationError(
                "The registered manual edit tool identity is invalid"
            )
        arguments = {
            "proposal": proposal.model_dump(mode="json"),
            "confirmation": confirmation.model_dump(mode="json"),
        }
        if self._gateway is not None:
            token = uuid.uuid4().hex
            request = AtomicToolRequestEnvelope(
                request_id=f"request_manual_{token}",
                execution_id=f"execution_manual_{token}",
                project_id=proposal.base_project_id,
                confirmation_id=confirmation.confirmation_id,
                plan_ref=PlanReference(
                    plan_id=proposal.proposal_id,
                    plan_version=1,
                    plan_digest=proposal.digest(),
                ),
                step_id=f"step_manual_{token}",
                tool_name=MANUAL_EDIT_TOOL_NAME,
                arguments=arguments,
                requested_at=datetime.now(timezone.utc),
            )
            gateway_result = self._gateway.execute(
                request,
                AtomicExecutionContext(
                    caller="manual_edit",
                    registry_ref=self._registry.reference,
                    project_id=proposal.base_project_id,
                    confirmation_id=confirmation.confirmation_id,
                    allowed_side_effects=("files", "timeline"),
                    idempotency_key=request.request_id,
                ),
            )
            if gateway_result.status != "success":
                raise ManualEditValidationError(
                    gateway_result.error.message
                    if gateway_result.error is not None
                    else "Manual edit atomic dispatch failed"
                )
            result = gateway_result.payload
        else:
            result = skill.execute(arguments)
        applied_snapshot = self._snapshot_provider()
        return {
            "schema_name": "vistora.manual-edit-application",
            "schema_version": "1.0.0",
            "application_id": f"application_{uuid.uuid4().hex}",
            "proposal_ref": review.proposal_ref.model_dump(mode="json"),
            "confirmation_id": confirmation.confirmation_id,
            "tool_name": MANUAL_EDIT_TOOL_NAME,
            "tool_result": result,
            "snapshot": applied_snapshot.model_dump(mode="json"),
        }
