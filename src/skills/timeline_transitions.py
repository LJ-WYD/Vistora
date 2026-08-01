"""First-class deterministic transition edits through the shared transaction."""

from __future__ import annotations

from typing import Any

from transitions.media import probe_source_duration, probe_source_has_audio
from timeline_edit import (
    AddTransitionInput,
    CopyTransitionInput,
    RemoveTransitionInput,
    TimelineEditError,
    TimelineEditTransaction,
    UpdateTransitionInput,
)

from .base import BaseSkill


class TimelineAddTransitionSkill(BaseSkill):
    name = "TimelineAddTransitionSkill"
    description = (
        "Add one exact first-class video/audio transition at a validated "
        "same-track adjacent cut, with optional explicit audio pairing."
    )
    input_model = AddTransitionInput

    def run(self, params: AddTransitionInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.add_transition(
                params.transition,
                paired_transition=params.paired_transition,
            ),
            source_duration_resolver=probe_source_duration,
            source_audio_resolver=probe_source_has_audio,
        )


class TimelineUpdateTransitionSkill(BaseSkill):
    name = "TimelineUpdateTransitionSkill"
    description = (
        "Replace one exact transition definition atomically while preserving "
        "its stable identity and exact cut binding."
    )
    input_model = UpdateTransitionInput

    def run(self, params: UpdateTransitionInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.update_transition(
                params.transition,
                paired_transition=params.paired_transition,
            ),
            source_duration_resolver=probe_source_duration,
            source_audio_resolver=probe_source_has_audio,
        )


class TimelineRemoveTransitionSkill(BaseSkill):
    name = "TimelineRemoveTransitionSkill"
    description = (
        "Remove one exact transition and its reciprocal audio/video pair "
        "atomically when present."
    )
    input_model = RemoveTransitionInput

    def run(self, params: RemoveTransitionInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.remove_transition(
                params.transition_id,
                include_paired=params.include_paired,
            )
        )


class TimelineCopyTransitionSkill(BaseSkill):
    name = "TimelineCopyTransitionSkill"
    description = (
        "Copy one whitelisted transition to an explicit stable ordered set "
        "of adjacent cuts without index or time approximation."
    )
    input_model = CopyTransitionInput

    def run(self, params: CopyTransitionInput) -> dict[str, Any]:
        def operation(engine: Any):
            source = engine.timeline.transitions.get(
                params.source_transition_id
            )
            if source is None:
                raise TimelineEditError("Source transition ID is unknown")
            source_pair = (
                engine.timeline.transitions.get(source.paired_transition_id)
                if source.paired_transition_id is not None
                else None
            )
            pairs = []
            for target in params.targets:
                if source_pair is None and target.paired_transition_id:
                    raise TimelineEditError(
                        "Unpaired source cannot create an implicit audio pair"
                    )
                if source_pair is not None and not target.paired_transition_id:
                    raise TimelineEditError(
                        "Paired source requires an explicit copied audio cut"
                    )
                copied_pair = None
                copied = source.model_copy(
                    update={
                        "transition_id": target.transition_id,
                        "track_id": target.track_id,
                        "from_clip_id": target.from_clip_id,
                        "to_clip_id": target.to_clip_id,
                        "paired_transition_id": target.paired_transition_id,
                    }
                )
                if source_pair is not None:
                    copied_pair = source_pair.model_copy(
                        update={
                            "transition_id": target.paired_transition_id,
                            "track_id": target.paired_track_id,
                            "from_clip_id": target.paired_from_clip_id,
                            "to_clip_id": target.paired_to_clip_id,
                            "paired_transition_id": target.transition_id,
                        }
                    )
                pairs.append((copied, copied_pair))
            return engine.copy_transition(
                params.source_transition_id, tuple(pairs)
            )

        return TimelineEditTransaction.apply(
            operation,
            source_duration_resolver=probe_source_duration,
            source_audio_resolver=probe_source_has_audio,
        )
