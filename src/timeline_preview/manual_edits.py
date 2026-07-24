"""Confirmed manual-edit application service for the local preview."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from contracts import (
    ManualClipRemove,
    ManualClipUpdate,
    ManualEditChange,
    ManualEditConfirmationRecord,
    ManualEditProposal,
    ManualEditProposalReference,
    ManualEditReview,
)
from timeline_query import TimelineSnapshot


MANUAL_EDIT_TOOL_NAME = "VideoApplyManualEditsSkill"


class ManualEditValidationError(ValueError):
    """A user-authored proposal cannot be reviewed or applied safely."""


def _clip_state(clip: Any, order_index: int) -> dict[str, Any]:
    return {
        "order_index": order_index,
        "trim_in_seconds": clip.trim_in_seconds,
        "trim_out_seconds": clip.trim_out_seconds,
        "timeline_start_seconds": clip.timeline_start_seconds,
        "timeline_end_seconds": clip.timeline_end_seconds,
        "effective_duration_seconds": clip.effective_duration_seconds,
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
        if state["clip"].clip_id == clip_id
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
        {"clip": clip}
        for clip in video_tracks[0].clips
    ]
    changes: list[ManualEditChange] = []

    for edit in proposal.edits:
        index = _find_unique_state_index(states, edit.clip_id)
        clip = states[index]["clip"]
        before = _clip_state(clip, index)
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
            continue

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
        result = skill.execute(
            {
                "proposal": proposal.model_dump(mode="json"),
                "confirmation": confirmation.model_dump(mode="json"),
            }
        )
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
