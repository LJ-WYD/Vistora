"""Atomic narration alignment, aligned subtitle construction, and sync QC."""

from __future__ import annotations

from typing import Any

from core import timeline_manager
from subtitles import SubtitleEditCueInput, SubtitleEditEngine, SubtitleEditTransaction, SubtitleManageTrackInput
from subtitle_alignment import (
    AudioAlignTranscriptInput, SubtitleAlignmentBuildResult,
    SubtitleAlignmentService, SubtitleBuildFromAlignmentInput,
    SubtitleSyncQCInput, SubtitleSyncQCService, build_aligned_cues,
    validate_report_source,
)

from .base import BaseSkill


class AudioAlignTranscriptSkill(BaseSkill):
    name = "AudioAlignTranscriptSkill"
    description = (
        "Read one exact final narration clip and produce immutable word-level "
        "alignment evidence; project and media state remain unchanged."
    )
    input_model = AudioAlignTranscriptInput

    def __init__(self, service: SubtitleAlignmentService | None = None):
        self.service = service or SubtitleAlignmentService()

    def run(self, params: AudioAlignTranscriptInput) -> dict[str, Any]:
        timeline = timeline_manager.TimelineManager.get_current_timeline()
        return self.service.analyze(timeline, params).model_dump(mode="json")


class SubtitleBuildFromAlignmentSkill(BaseSkill):
    name = "SubtitleBuildFromAlignmentSkill"
    description = (
        "Transactionally replace one exact unlocked caption track with cues and "
        "word timings derived from immutable narration alignment evidence."
    )
    input_model = SubtitleBuildFromAlignmentInput

    def run(self, params: SubtitleBuildFromAlignmentInput) -> dict[str, Any]:
        current = timeline_manager.TimelineManager.get_current_timeline()
        validate_report_source(current, params.report)
        cues = build_aligned_cues(params.report, params.cue_id_prefix)
        prior_ids: tuple[str, ...] = ()

        def apply(engine: SubtitleEditEngine):
            nonlocal prior_ids
            if params.create_track:
                engine.manage_track(SubtitleManageTrackInput(
                    action="create", track_id=params.track_id, kind="subtitle",
                    role="captions", language=params.language,
                ))
            key, track = engine._find_track(params.track_id)
            prior_ids = tuple(cue.cue_id for cue in track.cues)
            engine._replace_track(key, track.model_copy(update={"cues": ()}))
            updated, outcome = engine.edit_cues(SubtitleEditCueInput(
                action="batch_add", track_id=params.track_id, cues=cues,
            ))
            return updated, outcome.model_copy(update={
                "operation": "build_from_alignment",
                "deleted_cue_ids": prior_ids,
                "warnings": ("Subtitle timing is bound to immutable narration alignment evidence.",),
            })

        raw = SubtitleEditTransaction.apply(apply)
        return SubtitleAlignmentBuildResult(
            track_id=params.track_id, report_id=params.report.report_id,
            report_digest=params.report.report_digest,
            source_sha256=params.report.source_sha256,
            analyzed_clip_digest=params.report.analyzed_clip_digest,
            created_cue_ids=tuple(raw["created_cue_ids"]),
            deleted_cue_ids=prior_ids,
            before_snapshot_id=raw["before_snapshot_id"],
            after_snapshot_id=raw["after_snapshot_id"],
            project_id=raw["project_id"], revision=raw["revision"],
            timeline_digest=raw["timeline_digest"],
        ).model_dump(mode="json")


class SubtitleSyncQCSkill(BaseSkill):
    name = "SubtitleSyncQCSkill"
    description = (
        "Read exact narration, aligned captions, and optionally the rendered "
        "asset; fail when timeline timing or final audio mux drift exceeds policy."
    )
    input_model = SubtitleSyncQCInput

    def __init__(self, service: SubtitleSyncQCService | None = None):
        self.service = service or SubtitleSyncQCService()

    def run(self, params: SubtitleSyncQCInput) -> dict[str, Any]:
        timeline = timeline_manager.TimelineManager.get_current_timeline()
        return self.service.analyze(timeline, params).model_dump(mode="json")
