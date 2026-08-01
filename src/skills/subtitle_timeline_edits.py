"""Registered atomic subtitle editing and sidecar tools."""

from __future__ import annotations

from typing import Any

from core import timeline_manager
from core.timeline import SubtitleTrackConfig
from subtitles import (
    SubtitleEditCueInput,
    SubtitleEditEngine,
    SubtitleEditOutcome,
    SubtitleEditTransaction,
    SubtitleExportInput,
    SubtitleImportInput,
    SubtitleManageTrackInput,
    export_sidecar,
    load_subtitles,
    parse_subtitles,
)

from .base import BaseSkill


class SubtitleManageTrackSkill(BaseSkill):
    name = "SubtitleManageTrackSkill"
    description = "Create, update, style, lock, or delete one exact first-class subtitle/text track."
    input_model = SubtitleManageTrackInput

    def run(self, params: SubtitleManageTrackInput) -> dict[str, Any]:
        return SubtitleEditTransaction.apply(lambda engine: engine.manage_track(params))


class SubtitleEditCueSkill(BaseSkill):
    name = "SubtitleEditCueSkill"
    description = (
        "Transactionally add/batch-add, update, split, merge, move, trim, ripple-shift, "
        "delete, or style exact subtitle cues on one unlocked track."
    )
    input_model = SubtitleEditCueInput

    def run(self, params: SubtitleEditCueInput) -> dict[str, Any]:
        return SubtitleEditTransaction.apply(lambda engine: engine.edit_cues(params))


class SubtitleImportSkill(BaseSkill):
    name = "SubtitleImportSkill"
    description = "Read UTF-8 SRT/WebVTT and transactionally import deterministic cues without changing the source file."
    input_model = SubtitleImportInput

    def run(self, params: SubtitleImportInput) -> dict[str, Any]:
        cues = (
            load_subtitles(params.input_path or "", params.format, language=params.language)
            if params.input_path is not None
            else parse_subtitles(params.content or "", params.format, language=params.language)
        )

        def apply(engine: SubtitleEditEngine):
            if params.create_track:
                engine.manage_track(SubtitleManageTrackInput(
                    action="create", track_id=params.track_id, kind="subtitle", language=params.language,
                ))
            key, track = engine._find_track(params.track_id)
            if params.replace_existing:
                engine._replace_track(key, track.model_copy(update={"cues": ()}))
            updated, outcome = engine.edit_cues(SubtitleEditCueInput(
                action="batch_add", track_id=params.track_id, cues=cues,
            ))
            return updated, outcome.model_copy(update={"operation": "import", "warnings": (f"Imported deterministic {params.format} subtitle data.",)})

        return SubtitleEditTransaction.apply(apply)


class SubtitleExportSidecarSkill(BaseSkill):
    name = "SubtitleExportSidecarSkill"
    description = "Atomically export enabled subtitle cues as deterministic UTF-8 SRT or WebVTT sidecar data."
    input_model = SubtitleExportInput

    def run(self, params: SubtitleExportInput) -> dict[str, Any]:
        timeline = timeline_manager.TimelineManager.get_current_timeline()
        return export_sidecar(timeline, params.output_path, params.format, params.track_ids)
