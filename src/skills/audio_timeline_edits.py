"""Atomic local audio edits and read-only loudness evidence acquisition."""

from __future__ import annotations

from typing import Any

from audio_analysis import (
    LoudnessAnalysisRequest,
    LoudnessAnalysisService,
    clip_audio_state_digest,
    source_sha256,
)
from core import timeline_manager
from timeline_edit import (
    SetClipAudioPropertiesInput,
    SetTrackMixPropertiesInput,
    SetVolumeEnvelopeInput,
    TimelineEditEngine,
    TimelineEditTransaction,
)

from .base import BaseSkill


class AudioAnalyzeLoudnessSkill(BaseSkill):
    name = "AudioAnalyzeLoudnessSkill"
    description = (
        "Read and cache deterministic EBU-style integrated loudness and true "
        "peak evidence for one exact clip; this skill never mutates project state."
    )
    input_model = LoudnessAnalysisRequest

    def __init__(self, service: LoudnessAnalysisService | None = None) -> None:
        self.service = service or LoudnessAnalysisService()

    def run(self, params: LoudnessAnalysisRequest) -> dict[str, Any]:
        timeline = timeline_manager.TimelineManager.get_current_timeline()
        return self.service.analyze(timeline, params).model_dump(mode="json")


class AudioSetClipPropertiesSkill(BaseSkill):
    name = "AudioSetClipPropertiesSkill"
    description = (
        "Set bounded clip-local gain, mute, pan, fades, or audio-track playback "
        "rate. Applying loudness gain requires exact prior analysis evidence."
    )
    input_model = SetClipAudioPropertiesInput

    def run(self, params: SetClipAudioPropertiesInput) -> dict[str, Any]:
        current = timeline_manager.TimelineManager.get_current_timeline()
        _, track, clip = TimelineEditEngine(current).clip_state(
            params.track_reference, params.clip_id
        )
        evidence = params.normalization_evidence
        if evidence is not None:
            if params.gain_db is None or abs(
                params.gain_db - evidence.applied_gain_db
            ) > 1e-9:
                raise ValueError(
                    "Explicit loudness application must use the evidenced gain"
                )
            if evidence.analyzed_clip_digest != clip_audio_state_digest(
                track.id, clip
            ):
                raise ValueError("Loudness evidence is stale for this clip")
            if evidence.source_sha256 != source_sha256(clip.source):
                raise ValueError("Loudness evidence source has changed")
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_clip_audio(
                params.track_reference,
                params.clip_id,
                gain_db=params.gain_db,
                muted=params.muted,
                pan=params.pan,
                fade_in_seconds=params.fade_in_seconds,
                fade_out_seconds=params.fade_out_seconds,
                playback_rate=params.playback_rate,
                normalization=evidence,
            )
        )


class AudioSetTrackMixSkill(BaseSkill):
    name = "AudioSetTrackMixSkill"
    description = (
        "Set bounded gain, mute, or pan on one exact unlocked audio track."
    )
    input_model = SetTrackMixPropertiesInput

    def run(self, params: SetTrackMixPropertiesInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_track_mix(
                params.track_id,
                gain_db=params.gain_db,
                muted=params.muted,
                pan=params.pan,
            )
        )


class AudioSetVolumeEnvelopeSkill(BaseSkill):
    name = "AudioSetVolumeEnvelopeSkill"
    description = (
        "Upsert, delete, or clear stable linear clip gain-envelope points."
    )
    input_model = SetVolumeEnvelopeInput

    def run(self, params: SetVolumeEnvelopeInput) -> dict[str, Any]:
        return TimelineEditTransaction.apply(
            lambda engine: engine.set_volume_envelope(
                params.track_reference,
                params.clip_id,
                action=params.action,
                point_id=params.point_id,
                offset_seconds=params.offset_seconds,
                gain_db=params.gain_db,
            )
        )
