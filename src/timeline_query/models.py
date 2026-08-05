"""Immutable, JSON-serializable read models for timeline inspection."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


TIMELINE_SNAPSHOT_VERSION = "9.0.0"
SnapshotVersion = Literal["2.0.0", "3.0.0", "4.0.0", "5.0.0", "6.0.0", "7.0.0", "8.0.0", "9.0.0"]
SnapshotId = Annotated[
    str,
    Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class ReadModel(BaseModel):
    """Strict frozen base for detached read data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class MediaSourceReference(ReadModel):
    """Stable reference to a configured source without filesystem probing."""

    source_id: SnapshotId
    reference_type: Literal[
        "configured_path",
        "opaque_preview_reference",
    ] = "configured_path"
    value: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class EvidenceSummary(ReadModel):
    """Browser-safe source evidence referenced by confirmed intent."""

    evidence_id: SnapshotId
    material_id: SnapshotId
    locator_type: Literal["media_time_range", "whole_material"]
    start_seconds: FiniteFloat | None = Field(default=None, ge=0)
    end_seconds: FiniteFloat | None = Field(default=None, gt=0)
    analysis_fact_id: SnapshotId | None = None


class ClipProvenanceSummary(ReadModel):
    """Detached origin/change summary for one current or historical clip."""

    schema_name: Literal["vistora.clip-provenance-summary"] = (
        "vistora.clip-provenance-summary"
    )
    schema_version: SnapshotVersion = TIMELINE_SNAPSHOT_VERSION
    origin_kind: Literal[
        "director_plan",
        "user_manual",
        "legacy_unknown",
    ]
    latest_change_origin: Literal[
        "director_plan",
        "user_manual",
        "legacy_unknown",
    ]
    mapping_status: Literal[
        "current",
        "legacy_unknown",
        "stale",
        "orphaned",
        "deleted",
    ]
    trace_revision: int = Field(ge=1)
    plan_id: SnapshotId | None = None
    plan_version: int | None = Field(default=None, ge=1)
    plan_digest: Sha256Digest | None = None
    confirmation_id: SnapshotId | None = None
    execution_id: SnapshotId | None = None
    source_operation_id: SnapshotId | None = None
    step_id: SnapshotId | None = None
    request_id: SnapshotId | None = None
    result_id: SnapshotId | None = None
    execution_status: Literal["success", "error"] | None = None
    evidence: tuple[EvidenceSummary, ...] = ()


class ClipTraceQueryResult(ReadModel):
    """Revision-bound deterministic trace query result for one clip identity."""

    schema_name: Literal["vistora.clip-trace-query-result"] = (
        "vistora.clip-trace-query-result"
    )
    schema_version: SnapshotVersion = TIMELINE_SNAPSHOT_VERSION
    snapshot_id: SnapshotId
    project_id: SnapshotId
    revision: int = Field(ge=1)
    trace_revision: int = Field(ge=1)
    track_key: str = Field(min_length=1)
    clip_id: str = Field(min_length=1)
    present: bool
    provenance: ClipProvenanceSummary


class ClipTransformSnapshot(ReadModel):
    position_x: FiniteFloat = 0.5
    position_y: FiniteFloat = 0.5
    scale_x: FiniteFloat = 1
    scale_y: FiniteFloat = 1
    rotation_degrees: FiniteFloat = 0
    opacity: FiniteFloat = 1
    anchor_x: FiniteFloat = 0.5
    anchor_y: FiniteFloat = 0.5
    crop_left: FiniteFloat = 0
    crop_right: FiniteFloat = 0
    crop_top: FiniteFloat = 0
    crop_bottom: FiniteFloat = 0
    fit: Literal["contain", "fill", "stretch"] = "contain"
    flip_horizontal: bool = False
    flip_vertical: bool = False


class ClipColorSnapshot(ReadModel):
    exposure: FiniteFloat = 0
    contrast: FiniteFloat = 0
    saturation: FiniteFloat = 0
    temperature: FiniteFloat = 0
    tint: FiniteFloat = 0
    highlights: FiniteFloat = 0
    shadows: FiniteFloat = 0
    gamma: FiniteFloat = 1
    sharpen: FiniteFloat = 0
    blur: FiniteFloat = 0


class VisualKeyframeSnapshot(ReadModel):
    schema_name: Literal["vistora.visual-keyframe-snapshot"] = (
        "vistora.visual-keyframe-snapshot"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    keyframe_id: SnapshotId
    offset_seconds: FiniteFloat = Field(ge=0)
    value: FiniteFloat
    interpolation: Literal[
        "hold", "linear", "ease_in", "ease_out", "ease_in_out"
    ]


class VisualAutomationSnapshot(ReadModel):
    schema_name: Literal["vistora.visual-automation-snapshot"] = (
        "vistora.visual-automation-snapshot"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    automation_id: SnapshotId
    clip_id: SnapshotId
    property_path: str = Field(min_length=3, max_length=80)
    enabled: bool
    keyframes: tuple[VisualKeyframeSnapshot, ...]
    automation_digest: Sha256Digest


class MaskPointSnapshot(ReadModel):
    point_id: SnapshotId
    x: FiniteFloat
    y: FiniteFloat


class MaskAutomationSnapshot(ReadModel):
    automation_id: SnapshotId
    mask_id: SnapshotId
    property_path: Literal[
        "position_x", "position_y", "scale_x", "scale_y",
        "rotation_degrees", "opacity", "feather",
    ]
    enabled: bool
    keyframes: tuple[VisualKeyframeSnapshot, ...]


class ClipMaskSnapshot(ReadModel):
    schema_name: Literal["vistora.clip-mask-snapshot"] = "vistora.clip-mask-snapshot"
    schema_version: Literal["1.0.0"] = "1.0.0"
    mask_id: SnapshotId
    kind: Literal["rectangle", "ellipse", "polygon"]
    operation: Literal["add", "subtract", "intersect"]
    enabled: bool
    invert: bool
    opacity: FiniteFloat
    feather: FiniteFloat
    expand: FiniteFloat
    position_x: FiniteFloat
    position_y: FiniteFloat
    scale_x: FiniteFloat
    scale_y: FiniteFloat
    rotation_degrees: FiniteFloat
    width: FiniteFloat | None = None
    height: FiniteFloat | None = None
    points: tuple[MaskPointSnapshot, ...] = ()
    automations: tuple[MaskAutomationSnapshot, ...] = ()


class ClipCompositeSnapshot(ReadModel):
    blend_mode: Literal["normal", "multiply", "screen"] = "normal"


class ClipSnapshot(ReadModel):
    """Detached view of one clip and its declared timing."""

    clip_id: str = Field(min_length=1)
    visual_kind: Literal["video", "image", "sticker"] = "video"
    order_index: int = Field(ge=0)
    source: MediaSourceReference
    trim_in_seconds: FiniteFloat
    trim_out_seconds: FiniteFloat
    declared_source_duration_seconds: FiniteFloat = Field(ge=0)
    speed_factor: FiniteFloat = Field(gt=0)
    timeline_start_seconds: FiniteFloat
    timeline_end_seconds: FiniteFloat
    effective_duration_seconds: FiniteFloat = Field(ge=0)
    volume: FiniteFloat | None
    keep_audio: bool
    reverse: bool
    freeze_frame_source_time_seconds: FiniteFloat | None = None
    freeze_frame_duration_seconds: FiniteFloat | None = None
    rotate_degrees: int
    link_group_id: SnapshotId | None = None
    audio_gain_db: FiniteFloat = 0
    audio_muted: bool = False
    audio_pan: FiniteFloat = 0
    audio_fade_in_seconds: FiniteFloat = 0
    audio_fade_out_seconds: FiniteFloat = 0
    audio_envelope: tuple[tuple[str, FiniteFloat, FiniteFloat], ...] = ()
    loudness_analysis_id: SnapshotId | None = None
    transform: ClipTransformSnapshot
    color: ClipColorSnapshot
    visual_automations: tuple[VisualAutomationSnapshot, ...] = ()
    masks: tuple[ClipMaskSnapshot, ...] = ()
    composite: ClipCompositeSnapshot = Field(default_factory=ClipCompositeSnapshot)
    mask_digest: Sha256Digest
    automation_digest: Sha256Digest
    visual_digest: Sha256Digest
    provenance: ClipProvenanceSummary | None = None


class TrackSnapshot(ReadModel):
    """Detached view of a configured track."""

    track_key: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    kind: Literal["video", "audio"]
    role: str = Field(min_length=1)
    order_index: int = Field(ge=0)
    enabled: bool
    muted: bool
    locked: bool
    mix_gain_db: FiniteFloat = 0
    mix_muted: bool = False
    mix_pan: FiniteFloat = 0
    clips: tuple[ClipSnapshot, ...] = ()
    clip_count: int = Field(ge=0)
    duration_seconds: FiniteFloat = Field(ge=0)


class SubtitleStyleSnapshot(ReadModel):
    schema_name: Literal["vistora.subtitle-style-snapshot"] = (
        "vistora.subtitle-style-snapshot"
    )
    font_family: Literal["sans", "serif", "monospace"]
    fallback_families: tuple[Literal["sans", "serif", "monospace"], ...]
    font_size: int = Field(ge=8, le=200)
    color: str
    outline_color: str
    background_color: str
    outline_width: FiniteFloat
    alignment: Literal["left", "center", "right"]
    position: Literal["top", "middle", "bottom"]
    safe_margin_x: FiniteFloat
    safe_margin_y: FiniteFloat
    bold: bool
    italic: bool


class SubtitleWordSnapshot(ReadModel):
    schema_name: Literal["vistora.subtitle-word-snapshot"] = (
        "vistora.subtitle-word-snapshot"
    )
    word_id: SnapshotId
    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat = Field(gt=0)
    text: str = Field(min_length=1)
    confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)


class SubtitleCueSnapshot(ReadModel):
    schema_name: Literal["vistora.subtitle-cue-snapshot"] = (
        "vistora.subtitle-cue-snapshot"
    )
    cue_id: SnapshotId
    cue_kind: Literal["subtitle", "title"] = "subtitle"
    order_index: int = Field(ge=0)
    start_seconds: FiniteFloat = Field(ge=0)
    end_seconds: FiniteFloat = Field(gt=0)
    duration_seconds: FiniteFloat = Field(gt=0)
    text: str = Field(min_length=1)
    language: str = Field(min_length=2)
    speaker: str | None = None
    enabled: bool
    settings: tuple[str, ...] = ()
    style: SubtitleStyleSnapshot | None = None
    words: tuple[SubtitleWordSnapshot, ...] = ()
    word_count: int = Field(default=0, ge=0)


class SubtitleTrackSnapshot(ReadModel):
    schema_name: Literal["vistora.subtitle-track-snapshot"] = (
        "vistora.subtitle-track-snapshot"
    )
    track_key: str = Field(min_length=1)
    track_id: SnapshotId
    kind: Literal["subtitle", "text"]
    role: str = Field(min_length=1)
    language: str = Field(min_length=2)
    order_index: int = Field(ge=0)
    enabled: bool
    locked: bool
    allow_overlaps: bool
    style: SubtitleStyleSnapshot
    cues: tuple[SubtitleCueSnapshot, ...] = ()
    cue_count: int = Field(ge=0)
    duration_seconds: FiniteFloat = Field(ge=0)


class TransitionSnapshot(ReadModel):
    """Detached browser-safe state for one exact timeline transition."""

    schema_name: Literal["vistora.transition-snapshot"] = (
        "vistora.transition-snapshot"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    transition_id: SnapshotId
    track_id: SnapshotId
    from_clip_id: SnapshotId
    to_clip_id: SnapshotId
    media_type: Literal["video", "audio"]
    kind: Literal[
        "cut",
        "cross_dissolve",
        "fade_color",
        "wipe",
        "slide",
        "audio_equal_power",
        "audio_linear",
        "audio_fade_out_in",
    ]
    duration_seconds: FiniteFloat = Field(ge=0, le=10)
    alignment: Literal["centered", "start_at_cut", "end_at_cut"]
    direction: Literal["left", "right", "up", "down"] | None = None
    color: Literal["#000000", "#FFFFFF"] | None = None
    enabled: bool
    audio_policy: Literal[
        "none", "linked_audio", "explicit_audio_transition"
    ]
    paired_transition_id: SnapshotId | None = None


class TimelineSnapshotReference(ReadModel):
    """Optimistic read guard for a specific project revision."""

    project_id: SnapshotId
    revision: int = Field(ge=1)
    snapshot_id: SnapshotId | None = None
    timeline_digest: Sha256Digest | None = None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: TimelineSnapshot,
    ) -> TimelineSnapshotReference:
        return cls(
            project_id=snapshot.project_id,
            revision=snapshot.revision,
            snapshot_id=snapshot.snapshot_id,
            timeline_digest=snapshot.timeline_digest,
        )


class TimelineSnapshot(ReadModel):
    """Versioned, deterministic, read-only project/timeline snapshot."""

    schema_name: Literal["vistora.timeline-snapshot"] = (
        "vistora.timeline-snapshot"
    )
    schema_version: SnapshotVersion = TIMELINE_SNAPSHOT_VERSION
    snapshot_id: SnapshotId
    project_id: SnapshotId
    revision: int = Field(ge=1)
    source_schema_name: Literal["vistora.timeline-project"] = (
        "vistora.timeline-project"
    )
    source_schema_version: Literal["1.0.0"] = "1.0.0"
    migration_source: Literal["native", "legacy.timeline.v0"]
    timeline_digest: Sha256Digest
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    tracks: tuple[TrackSnapshot, ...] = ()
    subtitle_tracks: tuple[SubtitleTrackSnapshot, ...] = ()
    transitions: tuple[TransitionSnapshot, ...] = ()
    track_count: int = Field(ge=0)
    subtitle_track_count: int = Field(ge=0)
    subtitle_cue_count: int = Field(ge=0)
    transition_count: int = Field(ge=0)
    clip_count: int = Field(ge=0)
    video_clip_count: int = Field(ge=0)
    audio_clip_count: int = Field(ge=0)
    duration_seconds: FiniteFloat = Field(ge=0)
    empty: bool
    orphaned_provenance: tuple[ClipTraceQueryResult, ...] = ()
