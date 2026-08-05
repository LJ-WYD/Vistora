import os
from typing import Any, List, Dict, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip

TIMELINE_MODEL_VERSION = "2.0.0"


class FreezeFrameSettings(BaseModel):
    """One exact source frame held for a deterministic timeline duration."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.freeze-frame-settings"] = (
        "vistora.freeze-frame-settings"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_time_seconds: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, le=86400, allow_inf_nan=False)


class AudioEnvelopePoint(BaseModel):
    """One deterministic linear gain-envelope point in clip-local time."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.audio-envelope-point"] = (
        "vistora.audio-envelope-point"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    point_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    offset_seconds: float = Field(ge=0, allow_inf_nan=False)
    gain_db: float = Field(ge=-60, le=24, allow_inf_nan=False)


class AppliedLoudnessNormalization(BaseModel):
    """Exact read-only analysis evidence used for an explicit gain change."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.applied-loudness-normalization"] = (
        "vistora.applied-loudness-normalization"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    analysis_id: str = Field(min_length=3, max_length=160)
    analyzed_clip_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    integrated_lufs: float = Field(ge=-120, le=20, allow_inf_nan=False)
    true_peak_dbfs: float = Field(ge=-120, le=20, allow_inf_nan=False)
    target_lufs: float = Field(ge=-36, le=-5, allow_inf_nan=False)
    max_true_peak_dbfs: float = Field(ge=-9, le=0, allow_inf_nan=False)
    applied_gain_db: float = Field(ge=-60, le=24, allow_inf_nan=False)


class AppliedAudioDucking(BaseModel):
    """Auditable result of one explicitly confirmed structural ducking pass."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.applied-audio-ducking"] = (
        "vistora.applied-audio-ducking"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    ducking_id: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    key_track_ids: tuple[str, ...] = Field(min_length=1)
    key_timeline_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reduction_db: float = Field(ge=-36, le=-1, allow_inf_nan=False)
    attack_seconds: float = Field(gt=0, le=2, allow_inf_nan=False)
    release_seconds: float = Field(gt=0, le=5, allow_inf_nan=False)

    @model_validator(mode="after")
    def stable_keys(self) -> "AppliedAudioDucking":
        if self.key_track_ids != tuple(sorted(set(self.key_track_ids))):
            raise ValueError("Ducking key track IDs must be stable and unique")
        return self


class ClipAudioSettings(BaseModel):
    """Versioned non-destructive audio controls for one clip component."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.clip-audio-settings"] = (
        "vistora.clip-audio-settings"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    content_role: Literal[
        "unspecified",
        "dialogue",
        "voiceover",
        "background_music",
        "sound_effect",
        "ambience",
    ] = "unspecified"
    gain_db: float = Field(0, ge=-60, le=24, allow_inf_nan=False)
    muted: bool = False
    pan: float = Field(0, ge=-1, le=1, allow_inf_nan=False)
    fade_in_seconds: float = Field(0, ge=0, allow_inf_nan=False)
    fade_out_seconds: float = Field(0, ge=0, allow_inf_nan=False)
    envelope: tuple[AudioEnvelopePoint, ...] = ()
    normalization: AppliedLoudnessNormalization | None = None
    ducking: AppliedAudioDucking | None = None

    @model_validator(mode="after")
    def stable_envelope(self) -> "ClipAudioSettings":
        identities = [point.point_id for point in self.envelope]
        offsets = [point.offset_seconds for point in self.envelope]
        if len(identities) != len(set(identities)):
            raise ValueError("audio envelope point IDs must be unique")
        if len(offsets) != len(set(offsets)):
            raise ValueError("audio envelope offsets must be unique")
        if list(self.envelope) != sorted(
            self.envelope,
            key=lambda point: (point.offset_seconds, point.point_id),
        ):
            raise ValueError("audio envelope points must be deterministically sorted")
        return self


class TrackMixSettings(BaseModel):
    """Versioned deterministic mix controls applied to an audio source lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.track-mix-settings"] = (
        "vistora.track-mix-settings"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    gain_db: float = Field(0, ge=-60, le=24, allow_inf_nan=False)
    muted: bool = False
    pan: float = Field(0, ge=-1, le=1, allow_inf_nan=False)


class SubtitleStyle(BaseModel):
    """Safe, versioned subtitle styling with no file or filter injection."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.subtitle-style"] = "vistora.subtitle-style"
    schema_version: Literal["1.0.0"] = "1.0.0"
    font_family: Literal["sans", "serif", "monospace"] = "sans"
    fallback_families: tuple[Literal["sans", "serif", "monospace"], ...] = (
        "sans",
    )
    font_size: int = Field(42, ge=8, le=200)
    color: str = Field("#FFFFFFFF", pattern=r"^#[0-9A-Fa-f]{8}$")
    outline_color: str = Field("#000000FF", pattern=r"^#[0-9A-Fa-f]{8}$")
    background_color: str = Field("#00000000", pattern=r"^#[0-9A-Fa-f]{8}$")
    outline_width: float = Field(2, ge=0, le=12, allow_inf_nan=False)
    alignment: Literal["left", "center", "right"] = "center"
    position: Literal["top", "middle", "bottom"] = "bottom"
    safe_margin_x: float = Field(0.05, ge=0, le=0.25, allow_inf_nan=False)
    safe_margin_y: float = Field(0.08, ge=0, le=0.25, allow_inf_nan=False)
    bold: bool = False
    italic: bool = False

    @model_validator(mode="after")
    def stable_fallbacks(self) -> "SubtitleStyle":
        if not self.fallback_families:
            raise ValueError("Subtitle style requires a logical font fallback")
        if len(self.fallback_families) != len(set(self.fallback_families)):
            raise ValueError("Subtitle font fallbacks must be unique")
        return self


class SubtitleWord(BaseModel):
    """One exact, optional word-level timing item within a cue."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_name: Literal["vistora.subtitle-word"] = "vistora.subtitle-word"
    schema_version: Literal["1.0.0"] = "1.0.0"
    word_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=256)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def positive_range(self) -> "SubtitleWord":
        if self.end_seconds <= self.start_seconds + 1e-6:
            raise ValueError("Subtitle word must have positive duration")
        if "\x00" in self.text:
            raise ValueError("Subtitle word contains a null character")
        return self


class SubtitleCue(BaseModel):
    """One immutable, precisely timed subtitle cue."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_name: Literal["vistora.subtitle-cue"] = "vistora.subtitle-cue"
    schema_version: Literal["1.0.0"] = "1.0.0"
    cue_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    cue_kind: Literal["subtitle", "title"] = "subtitle"
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=4096)
    language: str = Field("und", pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    speaker: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool = True
    settings: tuple[str, ...] = ()
    style: SubtitleStyle | None = None
    words: tuple[SubtitleWord, ...] = ()

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("Subtitle cue text cannot be empty")
        if "\x00" in normalized:
            raise ValueError("Subtitle cue text contains a null character")
        return normalized

    @model_validator(mode="after")
    def valid_range_and_settings(self) -> "SubtitleCue":
        if self.end_seconds <= self.start_seconds + 1e-6:
            raise ValueError("Subtitle cue must have positive duration")
        allowed = {"align", "line", "position", "size", "vertical"}
        keys: list[str] = []
        for setting in self.settings:
            if not setting or any(char in setting for char in "\r\n<>{}\\"):
                raise ValueError("Subtitle cue setting contains unsafe characters")
            key, separator, value = setting.partition(":")
            if not separator or key not in allowed or not value or len(setting) > 80:
                raise ValueError("Subtitle cue setting is unsupported")
            keys.append(key)
        if len(keys) != len(set(keys)):
            raise ValueError("Subtitle cue settings must use unique keys")
        if self.settings != tuple(sorted(self.settings)):
            raise ValueError("Subtitle cue settings must use stable ordering")
        word_ids = tuple(word.word_id for word in self.words)
        if len(word_ids) != len(set(word_ids)):
            raise ValueError("Subtitle word IDs must be unique within a cue")
        expected_words = tuple(
            sorted(
                self.words,
                key=lambda word: (word.start_seconds, word.end_seconds, word.word_id),
            )
        )
        if self.words != expected_words:
            raise ValueError("Subtitle words must use deterministic time ordering")
        for previous, current in zip(self.words, self.words[1:]):
            if current.start_seconds < previous.end_seconds - 1e-6:
                raise ValueError("Subtitle word timings cannot overlap")
        if any(
            word.start_seconds < self.start_seconds - 1e-6
            or word.end_seconds > self.end_seconds + 1e-6
            for word in self.words
        ):
            raise ValueError("Subtitle word timing must stay inside its cue")
        return self


class SubtitleTrackConfig(BaseModel):
    """Immutable first-class subtitle/text lane, separate from media clips."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_name: Literal["vistora.subtitle-track"] = "vistora.subtitle-track"
    schema_version: Literal["1.0.0"] = "1.0.0"
    track_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    kind: Literal["subtitle", "text"] = "subtitle"
    role: str = Field("captions", min_length=1, max_length=80)
    language: str = Field("und", pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    order: int = Field(0, ge=0)
    enabled: bool = True
    locked: bool = False
    allow_overlaps: bool = False
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    cues: tuple[SubtitleCue, ...] = ()

    @model_validator(mode="after")
    def stable_cues(self) -> "SubtitleTrackConfig":
        ids = [cue.cue_id for cue in self.cues]
        if len(ids) != len(set(ids)):
            raise ValueError("Subtitle cue IDs must be unique within a track")
        word_ids = [word.word_id for cue in self.cues for word in cue.words]
        if len(word_ids) != len(set(word_ids)):
            raise ValueError("Subtitle word IDs must be unique within a track")
        expected_kind = "title" if self.kind == "text" else "subtitle"
        if any(cue.cue_kind != expected_kind for cue in self.cues):
            raise ValueError(
                f"{self.kind} tracks require {expected_kind} cue semantics"
            )
        expected = tuple(
            sorted(self.cues, key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id))
        )
        if self.cues != expected:
            raise ValueError("Subtitle cues must use deterministic time ordering")
        if not self.allow_overlaps:
            for previous, current in zip(self.cues, self.cues[1:]):
                if current.start_seconds < previous.end_seconds - 1e-6:
                    raise ValueError("Subtitle cues overlap on a non-overlap track")
        return self


class ClipTransform(BaseModel):
    """Frozen canvas-relative visual transform for one video/image clip.

    Position and anchor are normalized to the output canvas and transformed
    clip respectively. Crop values are normalized fractions of source edges.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.clip-transform"] = "vistora.clip-transform"
    schema_version: Literal["1.0.0"] = "1.0.0"
    position_x: float = Field(0.5, ge=-2, le=3, allow_inf_nan=False)
    position_y: float = Field(0.5, ge=-2, le=3, allow_inf_nan=False)
    scale_x: float = Field(1, ge=0.05, le=8, allow_inf_nan=False)
    scale_y: float = Field(1, ge=0.05, le=8, allow_inf_nan=False)
    rotation_degrees: float = Field(0, ge=-360, le=360, allow_inf_nan=False)
    opacity: float = Field(1, ge=0, le=1, allow_inf_nan=False)
    anchor_x: float = Field(0.5, ge=0, le=1, allow_inf_nan=False)
    anchor_y: float = Field(0.5, ge=0, le=1, allow_inf_nan=False)
    crop_left: float = Field(0, ge=0, le=0.95, allow_inf_nan=False)
    crop_right: float = Field(0, ge=0, le=0.95, allow_inf_nan=False)
    crop_top: float = Field(0, ge=0, le=0.95, allow_inf_nan=False)
    crop_bottom: float = Field(0, ge=0, le=0.95, allow_inf_nan=False)
    fit: Literal["contain", "fill", "stretch"] = "contain"
    flip_horizontal: bool = False
    flip_vertical: bool = False

    @model_validator(mode="after")
    def crop_keeps_pixels(self) -> "ClipTransform":
        if self.crop_left + self.crop_right >= 0.99:
            raise ValueError("Horizontal crop must retain at least 1%")
        if self.crop_top + self.crop_bottom >= 0.99:
            raise ValueError("Vertical crop must retain at least 1%")
        return self


class ClipColorAdjustment(BaseModel):
    """Bounded deterministic SDR color adjustment in documented order."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.clip-color-adjustment"] = (
        "vistora.clip-color-adjustment"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    exposure: float = Field(0, ge=-2, le=2, allow_inf_nan=False)
    contrast: float = Field(0, ge=-0.75, le=1, allow_inf_nan=False)
    saturation: float = Field(0, ge=-1, le=2, allow_inf_nan=False)
    temperature: float = Field(0, ge=-1, le=1, allow_inf_nan=False)
    tint: float = Field(0, ge=-1, le=1, allow_inf_nan=False)
    highlights: float = Field(0, ge=-1, le=1, allow_inf_nan=False)
    shadows: float = Field(0, ge=-1, le=1, allow_inf_nan=False)
    gamma: float = Field(1, ge=0.5, le=2, allow_inf_nan=False)
    sharpen: float = Field(0, ge=0, le=1, allow_inf_nan=False)
    blur: float = Field(0, ge=0, le=8, allow_inf_nan=False)

    @model_validator(mode="after")
    def one_detail_filter(self) -> "ClipColorAdjustment":
        if self.sharpen > 0 and self.blur > 0:
            raise ValueError("Sharpen and blur cannot be active together")
        return self


VisualPropertyPath = Literal[
    "transform.position_x",
    "transform.position_y",
    "transform.scale_x",
    "transform.scale_y",
    "transform.scale_uniform",
    "transform.rotation_degrees",
    "transform.opacity",
    "transform.crop_left",
    "transform.crop_right",
    "transform.crop_top",
    "transform.crop_bottom",
    "color.exposure",
    "color.contrast",
    "color.saturation",
    "color.temperature",
    "color.tint",
    "color.gamma",
]


VISUAL_PROPERTY_RANGES: dict[str, tuple[float, float]] = {
    "transform.position_x": (-2.0, 3.0),
    "transform.position_y": (-2.0, 3.0),
    "transform.scale_x": (0.05, 8.0),
    "transform.scale_y": (0.05, 8.0),
    "transform.scale_uniform": (0.05, 8.0),
    "transform.rotation_degrees": (-360.0, 360.0),
    "transform.opacity": (0.0, 1.0),
    "transform.crop_left": (0.0, 0.95),
    "transform.crop_right": (0.0, 0.95),
    "transform.crop_top": (0.0, 0.95),
    "transform.crop_bottom": (0.0, 0.95),
    "color.exposure": (-2.0, 2.0),
    "color.contrast": (-0.75, 1.0),
    "color.saturation": (-1.0, 2.0),
    "color.temperature": (-1.0, 1.0),
    "color.tint": (-1.0, 1.0),
    "color.gamma": (0.5, 2.0),
}


class VisualKeyframe(BaseModel):
    """One frozen seek-safe value at clip-local output time."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.visual-keyframe"] = "vistora.visual-keyframe"
    schema_version: Literal["1.0.0"] = "1.0.0"
    keyframe_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    offset_seconds: float = Field(ge=0, allow_inf_nan=False)
    value: float = Field(allow_inf_nan=False)
    interpolation: Literal[
        "hold", "linear", "ease_in", "ease_out", "ease_in_out"
    ] = "linear"


class VisualAutomation(BaseModel):
    """Versioned animation curve for one whitelisted clip property."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.visual-automation"] = (
        "vistora.visual-automation"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    automation_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    clip_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    property_path: VisualPropertyPath
    keyframes: tuple[VisualKeyframe, ...] = Field(min_length=1, max_length=128)
    enabled: bool = True

    @model_validator(mode="after")
    def stable_bounded_curve(self) -> "VisualAutomation":
        identities = [item.keyframe_id for item in self.keyframes]
        offsets = [item.offset_seconds for item in self.keyframes]
        if len(identities) != len(set(identities)):
            raise ValueError("Visual keyframe IDs must be unique within a curve")
        if len(offsets) != len(set(offsets)):
            raise ValueError("Visual keyframe times must be unique within a curve")
        expected = tuple(
            sorted(self.keyframes, key=lambda item: (item.offset_seconds, item.keyframe_id))
        )
        if self.keyframes != expected:
            raise ValueError("Visual keyframes must use deterministic time ordering")
        lower, upper = VISUAL_PROPERTY_RANGES[self.property_path]
        if any(item.value < lower or item.value > upper for item in self.keyframes):
            raise ValueError(
                f"Visual keyframe value is outside {self.property_path} range"
            )
        return self


MaskPropertyPath = Literal[
    "position_x",
    "position_y",
    "scale_x",
    "scale_y",
    "rotation_degrees",
    "opacity",
    "feather",
]


MASK_PROPERTY_RANGES: dict[str, tuple[float, float]] = {
    "position_x": (-2.0, 3.0),
    "position_y": (-2.0, 3.0),
    "scale_x": (0.05, 8.0),
    "scale_y": (0.05, 8.0),
    "rotation_degrees": (-360.0, 360.0),
    "opacity": (0.0, 1.0),
    "feather": (0.0, 0.25),
}


class MaskPoint(BaseModel):
    """One stable normalized point in a controlled convex polygon mask."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.mask-point"] = "vistora.mask-point"
    schema_version: Literal["1.0.0"] = "1.0.0"
    point_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    x: float = Field(ge=-2, le=3, allow_inf_nan=False)
    y: float = Field(ge=-2, le=3, allow_inf_nan=False)


class MaskAutomation(BaseModel):
    """STEP 23-compatible fixed-interpolation curve for one mask property."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.mask-automation"] = "vistora.mask-automation"
    schema_version: Literal["1.0.0"] = "1.0.0"
    automation_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    mask_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    property_path: MaskPropertyPath
    keyframes: tuple[VisualKeyframe, ...] = Field(min_length=1, max_length=128)
    enabled: bool = True

    @model_validator(mode="after")
    def stable_curve(self) -> "MaskAutomation":
        ids = tuple(point.keyframe_id for point in self.keyframes)
        offsets = tuple(point.offset_seconds for point in self.keyframes)
        if len(ids) != len(set(ids)) or len(offsets) != len(set(offsets)):
            raise ValueError("Mask keyframe IDs and times must be unique")
        if self.keyframes != tuple(
            sorted(self.keyframes, key=lambda point: (point.offset_seconds, point.keyframe_id))
        ):
            raise ValueError("Mask keyframes must use deterministic time ordering")
        lower, upper = MASK_PROPERTY_RANGES[self.property_path]
        if any(point.value < lower or point.value > upper for point in self.keyframes):
            raise ValueError("Mask keyframe value is outside the property range")
        return self


class ClipMask(BaseModel):
    """Frozen normalized mask applied after clip visual processing."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.clip-mask"] = "vistora.clip-mask"
    schema_version: Literal["1.0.0"] = "1.0.0"
    mask_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    kind: Literal["rectangle", "ellipse", "polygon"]
    operation: Literal["add", "subtract", "intersect"] = "add"
    enabled: bool = True
    invert: bool = False
    opacity: float = Field(1, ge=0, le=1, allow_inf_nan=False)
    feather: float = Field(0, ge=0, le=0.25, allow_inf_nan=False)
    expand: float = Field(0, ge=-0.25, le=0.25, allow_inf_nan=False)
    position_x: float = Field(0.5, ge=-2, le=3, allow_inf_nan=False)
    position_y: float = Field(0.5, ge=-2, le=3, allow_inf_nan=False)
    scale_x: float = Field(1, ge=0.05, le=8, allow_inf_nan=False)
    scale_y: float = Field(1, ge=0.05, le=8, allow_inf_nan=False)
    rotation_degrees: float = Field(0, ge=-360, le=360, allow_inf_nan=False)
    width: float | None = Field(default=None, gt=0, le=4, allow_inf_nan=False)
    height: float | None = Field(default=None, gt=0, le=4, allow_inf_nan=False)
    points: tuple[MaskPoint, ...] = Field(default=(), max_length=12)
    automations: tuple[MaskAutomation, ...] = ()

    @model_validator(mode="after")
    def exact_shape(self) -> "ClipMask":
        if self.kind in {"rectangle", "ellipse"}:
            if self.width is None or self.height is None or self.points:
                raise ValueError("Rectangle/ellipse masks require width and height only")
        else:
            if self.width is not None or self.height is not None or len(self.points) < 3:
                raise ValueError("Polygon masks require three to twelve points only")
            point_ids = tuple(point.point_id for point in self.points)
            if len(point_ids) != len(set(point_ids)):
                raise ValueError("Mask point IDs must be unique")
            signs: list[float] = []
            for index, point in enumerate(self.points):
                nxt = self.points[(index + 1) % len(self.points)]
                after = self.points[(index + 2) % len(self.points)]
                cross = (nxt.x - point.x) * (after.y - nxt.y) - (nxt.y - point.y) * (after.x - nxt.x)
                if abs(cross) > 1e-9:
                    signs.append(cross)
            if not signs or any(value * signs[0] < 0 for value in signs[1:]):
                raise ValueError("Polygon masks must be non-degenerate and convex")
        automation_ids = tuple(item.automation_id for item in self.automations)
        properties = tuple(item.property_path for item in self.automations)
        if len(automation_ids) != len(set(automation_ids)) or len(properties) != len(set(properties)):
            raise ValueError("Mask automation IDs and properties must be unique")
        if self.automations != tuple(sorted(self.automations, key=lambda item: (item.property_path, item.automation_id))):
            raise ValueError("Mask automations must use stable property ordering")
        if any(item.mask_id != self.mask_id for item in self.automations):
            raise ValueError("Mask automation must target its containing mask")
        return self


class ClipCompositeSettings(BaseModel):
    """Bounded clip compositing declaration; no raw backend expressions."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.clip-composite-settings"] = "vistora.clip-composite-settings"
    schema_version: Literal["1.0.0"] = "1.0.0"
    blend_mode: Literal["normal", "multiply", "screen"] = "normal"


TransitionKind = Literal[
    "cut",
    "cross_dissolve",
    "fade_color",
    "wipe",
    "slide",
    "audio_equal_power",
    "audio_linear",
    "audio_fade_out_in",
]


class TransitionParameters(BaseModel):
    """Whitelisted parameters for deterministic built-in transitions."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.transition-parameters"] = (
        "vistora.transition-parameters"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    direction: Literal["left", "right", "up", "down"] | None = None
    color: Literal["#000000", "#FFFFFF"] | None = None


class TimelineTransition(BaseModel):
    """Frozen first-class transition bound to one exact adjacent cut."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_name: Literal["vistora.timeline-transition"] = (
        "vistora.timeline-transition"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    transition_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    track_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    from_clip_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    to_clip_id: str = Field(
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    kind: TransitionKind
    duration_seconds: float = Field(0, ge=0, le=10, allow_inf_nan=False)
    alignment: Literal["centered", "start_at_cut", "end_at_cut"] = (
        "centered"
    )
    parameters: TransitionParameters = Field(
        default_factory=TransitionParameters
    )
    enabled: bool = True
    audio_policy: Literal[
        "none", "linked_audio", "explicit_audio_transition"
    ] = "none"
    paired_transition_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )

    @property
    def media_type(self) -> Literal["video", "audio"]:
        return "audio" if self.kind.startswith("audio_") else "video"

    @model_validator(mode="after")
    def kind_parameters_are_exact(self) -> "TimelineTransition":
        direction = self.parameters.direction
        color = self.parameters.color
        if self.kind == "cut":
            if self.duration_seconds != 0:
                raise ValueError("Cut transitions must have zero duration")
            if direction is not None or color is not None:
                raise ValueError("Cut transitions accept no parameters")
            if self.audio_policy != "none" or self.paired_transition_id:
                raise ValueError("Cut transitions cannot create audio pairing")
        else:
            if self.duration_seconds < 0.04:
                raise ValueError(
                    "Non-cut transitions require at least 0.04 seconds"
                )
        if self.kind in {"wipe", "slide"}:
            if direction is None or color is not None:
                raise ValueError(
                    "Wipe/slide requires one direction and no color"
                )
        elif self.kind == "fade_color":
            if color is None or direction is not None:
                raise ValueError(
                    "Fade-through-color requires controlled black/white color"
                )
        elif direction is not None or color is not None:
            raise ValueError("This transition kind accepts no parameters")
        if self.media_type == "audio":
            if self.audio_policy != "none":
                raise ValueError("Audio transitions cannot carry audio policy")
        elif self.kind != "cut":
            if self.audio_policy == "none" and self.paired_transition_id:
                raise ValueError("Unpaired video transitions accept no pair ID")
            if self.audio_policy != "none" and not self.paired_transition_id:
                raise ValueError("Audio-linked video transition requires pair ID")
        return self


class ClipConfig(BaseModel):
    """Declarative clip state shared by legacy and v2 timelines."""

    id: str = Field(..., description="Stable clip ID.")
    source: str = Field(..., description="Configured source.")
    visual_kind: Literal["video", "image", "sticker"] = "video"
    trim_in: float = 0.0
    trim_out: float
    timeline_start: float = 0.0
    volume: Optional[float] = 1.0
    keep_audio: bool = True
    speed_factor: float = 1.0
    reverse: bool = False
    freeze_frame: FreezeFrameSettings | None = None
    rotate: int = 0
    link_group_id: Optional[str] = Field(
        None,
        min_length=3,
        max_length=160,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
        description="Explicit linked-clip group; never inferred.",
    )
    audio: ClipAudioSettings = Field(default_factory=ClipAudioSettings)
    transform: ClipTransform = Field(default_factory=ClipTransform)
    color: ClipColorAdjustment = Field(default_factory=ClipColorAdjustment)
    visual_automations: tuple[VisualAutomation, ...] = ()
    masks: tuple[ClipMask, ...] = ()
    composite: ClipCompositeSettings = Field(default_factory=ClipCompositeSettings)

    @model_validator(mode="after")
    def audio_timing_is_bounded(self) -> "ClipConfig":
        if self.speed_factor <= 0:
            return self
        duration = (
            self.freeze_frame.duration_seconds
            if self.freeze_frame is not None
            else (self.trim_out - self.trim_in) / self.speed_factor
        )
        if duration <= 0:
            return self
        if self.visual_kind in {"image", "sticker"}:
            if self.keep_audio or self.reverse or self.freeze_frame is not None:
                raise ValueError(
                    "Static image/sticker clips are silent and cannot reverse or freeze"
                )
            if abs(self.speed_factor - 1.0) > 1e-9:
                raise ValueError("Static image/sticker clips require playback speed 1")
        if self.freeze_frame is not None:
            if not (
                self.trim_in <= self.freeze_frame.source_time_seconds
                < self.trim_out
            ):
                raise ValueError(
                    "freeze-frame source time must be inside the clip source range"
                )
            if self.reverse:
                raise ValueError("a frozen frame cannot also be reversed")
            if self.keep_audio:
                raise ValueError("a frozen frame cannot retain embedded audio")
        if self.audio.fade_in_seconds > duration + 1e-6:
            raise ValueError("audio fade-in exceeds effective clip duration")
        if self.audio.fade_out_seconds > duration + 1e-6:
            raise ValueError("audio fade-out exceeds effective clip duration")
        if self.audio.fade_in_seconds + self.audio.fade_out_seconds > duration + 1e-6:
            raise ValueError("combined audio fades exceed effective clip duration")
        if any(
            point.offset_seconds > duration + 1e-6
            for point in self.audio.envelope
        ):
            raise ValueError("audio envelope point exceeds effective clip duration")
        automation_ids = [item.automation_id for item in self.visual_automations]
        properties = [item.property_path for item in self.visual_automations]
        if len(automation_ids) != len(set(automation_ids)):
            raise ValueError("Visual automation IDs must be unique per clip")
        if len(properties) != len(set(properties)):
            raise ValueError("A clip may have only one curve per visual property")
        if "transform.scale_uniform" in properties and any(
            item in properties
            for item in ("transform.scale_x", "transform.scale_y")
        ):
            raise ValueError(
                "Uniform scale automation cannot coexist with axis scale curves"
            )
        if tuple(self.visual_automations) != tuple(
            sorted(
                self.visual_automations,
                key=lambda item: (item.property_path, item.automation_id),
            )
        ):
            raise ValueError("Visual automations must use stable property ordering")
        for automation in self.visual_automations:
            if automation.clip_id != self.id:
                raise ValueError("Visual automation must target its containing clip")
            if any(
                item.offset_seconds > duration + 1e-6
                for item in automation.keyframes
            ):
                raise ValueError("Visual keyframe exceeds effective clip duration")
        mask_ids = tuple(mask.mask_id for mask in self.masks)
        if len(mask_ids) != len(set(mask_ids)):
            raise ValueError("Mask IDs must be unique per clip")
        if self.masks != tuple(sorted(self.masks, key=lambda mask: mask.mask_id)):
            raise ValueError("Masks must use deterministic mask-ID ordering")
        for mask in self.masks:
            if any(
                point.offset_seconds > duration + 1e-6
                for curve in mask.automations
                for point in curve.keyframes
            ):
                raise ValueError("Mask keyframe exceeds effective clip duration")
        return self


def effective_clip_duration(clip: ClipConfig) -> float:
    """Return exact declared timeline duration for normal or frozen playback."""

    if clip.freeze_frame is not None:
        return clip.freeze_frame.duration_seconds
    return (clip.trim_out - clip.trim_in) / clip.speed_factor


class TrackConfig(BaseModel):
    """Stable, ordered multi-track declaration."""

    id: str = Field(min_length=1)
    kind: Literal["video", "audio"] | None = None
    role: str = Field("primary", min_length=1, max_length=80)
    order: int = Field(0, ge=0)
    enabled: bool = True
    muted: bool = False
    locked: bool = False
    mix: TrackMixSettings = Field(default_factory=TrackMixSettings)
    clips: List[ClipConfig] = Field(default_factory=list)


class TimelineConfig(BaseModel):
    """V2 multi-track timeline with deterministic legacy migration."""

    schema_version: Literal["2.0.0"] = TIMELINE_MODEL_VERSION
    width: int = Field(1920, gt=0)
    height: int = Field(1080, gt=0)
    fps: int = Field(30, gt=0)
    tracks: Dict[str, TrackConfig] = Field(default_factory=dict)
    subtitle_tracks: Dict[str, SubtitleTrackConfig] = Field(default_factory=dict)
    transitions: Dict[str, TimelineTransition] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_tracks(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        native_v2 = migrated.get("schema_version") == TIMELINE_MODEL_VERSION
        migrated["schema_version"] = TIMELINE_MODEL_VERSION
        raw_tracks = migrated.get("tracks")
        if not isinstance(raw_tracks, dict):
            return migrated
        normalized: dict[str, Any] = {}
        used_orders: set[int] = set()
        for fallback_order, (track_key, raw_track) in enumerate(
            raw_tracks.items()
        ):
            if isinstance(raw_track, BaseModel):
                explicit_order = "order" in raw_track.model_fields_set
                track_data = raw_track.model_dump(mode="python")
            elif isinstance(raw_track, dict):
                explicit_order = "order" in raw_track
                track_data = dict(raw_track)
            else:
                normalized[track_key] = raw_track
                continue
            inferred_kind = (
                "audio"
                if track_key == "audio"
                or str(track_data.get("id", "")).startswith("audio")
                else "video"
            )
            if not track_data.get("kind"):
                track_data["kind"] = inferred_kind
            track_data.setdefault(
                "role",
                "primary" if track_key in {"video", "audio"} else "auxiliary",
            )
            legacy_priority = {"video": 0, "audio": 1}.get(
                track_key,
                fallback_order + 2,
            )
            proposed_order = (
                track_data.get("order")
                if explicit_order
                else legacy_priority
            )
            if not isinstance(proposed_order, int) or proposed_order < 0:
                proposed_order = fallback_order
            if not native_v2:
                while proposed_order in used_orders:
                    proposed_order += 1
            used_orders.add(proposed_order)
            track_data["order"] = proposed_order
            track_data.setdefault("enabled", True)
            track_data.setdefault("muted", False)
            track_data.setdefault("locked", False)
            normalized[track_key] = track_data
        migrated["tracks"] = normalized
        migrated.setdefault("transitions", {})
        return migrated

    @model_validator(mode="after")
    def stable_id_invariants(self) -> "TimelineConfig":
        track_ids = [track.id for track in self.tracks.values()]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("track IDs must be unique")
        orders = [track.order for track in self.tracks.values()]
        if len(orders) != len(set(orders)):
            raise ValueError("track order values must be unique")
        clip_ids = [
            clip.id for track in self.tracks.values() for clip in track.clips
        ]
        if len(clip_ids) != len(set(clip_ids)):
            raise ValueError("clip IDs must be unique across all tracks")
        if any(
            clip.visual_kind != "video"
            for track in self.tracks.values()
            if track.kind != "video"
            for clip in track.clips
        ):
            raise ValueError("Image and sticker clips require a video track")
        subtitle_ids = [track.track_id for track in self.subtitle_tracks.values()]
        if len(subtitle_ids) != len(set(subtitle_ids)):
            raise ValueError("subtitle track IDs must be unique")
        subtitle_orders = [track.order for track in self.subtitle_tracks.values()]
        if len(subtitle_orders) != len(set(subtitle_orders)):
            raise ValueError("subtitle track order values must be unique")
        cue_ids = [
            cue.cue_id
            for track in self.subtitle_tracks.values()
            for cue in track.cues
        ]
        if len(cue_ids) != len(set(cue_ids)):
            raise ValueError("subtitle cue IDs must be unique across all tracks")
        if any(
            key != transition.transition_id
            for key, transition in self.transitions.items()
        ):
            raise ValueError("transition mapping keys must equal transition IDs")
        transition_ids = [
            transition.transition_id for transition in self.transitions.values()
        ]
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("transition IDs must be unique")
        track_by_id = {track.id: track for track in self.tracks.values()}
        occupied_cuts: set[tuple[str, str, str, str]] = set()
        for transition in self.transitions.values():
            track = track_by_id.get(transition.track_id)
            if track is None:
                raise ValueError("transition references an unknown track")
            clips = sorted(
                track.clips,
                key=lambda item: (item.timeline_start, item.id),
            )
            from_indices = [
                index for index, clip in enumerate(clips)
                if clip.id == transition.from_clip_id
            ]
            to_indices = [
                index for index, clip in enumerate(clips)
                if clip.id == transition.to_clip_id
            ]
            if len(from_indices) != 1 or len(to_indices) != 1:
                raise ValueError("transition clip references must be exact")
            if to_indices[0] != from_indices[0] + 1:
                raise ValueError("transition clips must be same-track adjacent")
            outgoing = clips[from_indices[0]]
            incoming = clips[to_indices[0]]
            outgoing_end = outgoing.timeline_start + effective_clip_duration(outgoing)
            if abs(outgoing_end - incoming.timeline_start) > 1e-6:
                raise ValueError(
                    "transition clips must meet at one exact cut without gap/overlap"
                )
            if transition.media_type == "video" and track.kind != "video":
                raise ValueError("video transition requires a video track")
            if transition.kind != "cut" and any(
                clip.visual_kind != "video"
                for clip in (clips[from_indices[0]], clips[to_indices[0]])
            ):
                raise ValueError(
                    "Non-cut transitions involving static graphics are unsupported"
                )
            if transition.kind != "cut" and (
                outgoing.freeze_frame is not None
                or incoming.freeze_frame is not None
            ):
                raise ValueError(
                    "non-cut transitions over frozen frames are unsupported"
                )
            if transition.media_type == "audio":
                if track.kind == "video" and not (
                    outgoing.keep_audio and incoming.keep_audio
                ):
                    raise ValueError(
                        "embedded-audio transition requires active clip audio"
                    )
                if track.kind not in {"video", "audio"}:
                    raise ValueError("audio transition requires media clips")
            cut_key = (
                transition.track_id,
                transition.from_clip_id,
                transition.to_clip_id,
                transition.media_type,
            )
            if cut_key in occupied_cuts:
                raise ValueError("one media transition may bind each exact cut")
            occupied_cuts.add(cut_key)
        for transition in self.transitions.values():
            pair_id = transition.paired_transition_id
            if pair_id is None:
                continue
            pair = self.transitions.get(pair_id)
            if pair is None or pair.paired_transition_id != transition.transition_id:
                raise ValueError("paired transition linkage must be reciprocal")
            if pair.media_type == transition.media_type:
                raise ValueError("transition pair must contain video and audio")
        return self


class TimelineRenderer:
    """
    时间线渲染器，基于 MoviePy 将声明式时间线渲染输出为视频文件
    """
    def __init__(self, config: TimelineConfig):
        self.config = config
        self._opened_clips = []  # 记录所有打开的 MoviePy Clip 实例，便于渲染结束后统一关闭释放资源

    def render(self, output_path: str, *, enforce_canvas: bool = False) -> str:
        """
        开始渲染时间线，并输出到指定路径
        """
        # --- Fast-Path 极速渲染通道判断 ---
        if any(
            transition.enabled and transition.kind != "cut"
            for transition in self.config.transitions.values()
        ):
            from transitions import render_transition_timeline

            return render_transition_timeline(self.config, output_path)

        ordered_tracks = sorted(
            self.config.tracks.values(),
            key=lambda track: (track.order, track.id),
        )
        video_tracks = [
            track
            for track in ordered_tracks
            if track.enabled and track.kind == "video"
        ]
        audio_tracks = [
            track
            for track in ordered_tracks
            if (
                track.enabled
                and not track.muted
                and not track.mix.muted
                and track.kind == "audio"
            )
        ]
        video_track = TrackConfig(
            id="render_video",
            kind="video",
            clips=[
                clip.model_copy(update={"keep_audio": False})
                if track.muted
                else clip
                for track in video_tracks
                for clip in sorted(
                    track.clips,
                    key=lambda item: (item.timeline_start, item.id),
                )
            ],
        )
        audio_track = TrackConfig(
            id="render_audio",
            kind="audio",
            clips=[
                clip
                for track in audio_tracks
                for clip in sorted(
                    track.clips,
                    key=lambda item: (item.timeline_start, item.id),
                )
            ],
        )
        
        is_fast_path = False
        is_multi_fast_path = False
        
        canonical_video = self.config.tracks.get("video")
        if (
            len(video_tracks) == 1
            and canonical_video is video_tracks[0]
            and video_track.clips
            and all(
                clip.transform == ClipTransform()
                and clip.color == ClipColorAdjustment()
                and not clip.visual_automations
                and not clip.masks
                and clip.composite == ClipCompositeSettings()
                and clip.freeze_frame is None
                and clip.visual_kind == "video"
                for clip in video_track.clips
            )
        ):
            if not audio_track or len(audio_track.clips) == 0:
                if len(video_track.clips) == 1:
                    is_fast_path = True
                else:
                    is_multi_fast_path = True
                
        if is_fast_path and not enforce_canvas:
            try:
                return self._render_fast_path(output_path)
            except Exception as e:
                print(f"[Fast-Path] 极速渲染失败，降级到标准 MoviePy 渲染通道: {e}")
                
        if is_multi_fast_path and not enforce_canvas:
            try:
                return self._render_multi_fast_path(output_path)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[Multi-Fast-Path] 多片段极速并发拼接失败，降级到标准 MoviePy 渲染通道: {e}")

        requires_multitrack = (
            enforce_canvas
            or len(video_tracks) > 1
            or len(audio_tracks) > 1
            or any(
                track.mix != TrackMixSettings()
                or any(clip.audio != ClipAudioSettings() for clip in track.clips)
                for track in ordered_tracks
            )
            or any(
                key not in {"video", "audio"}
                and track.enabled
                and track.clips
                for key, track in self.config.tracks.items()
            )
            or any(
                clip.transform != ClipTransform()
                or clip.color != ClipColorAdjustment()
                or bool(clip.visual_automations)
                or bool(clip.masks)
                or clip.composite != ClipCompositeSettings()
                or clip.freeze_frame is not None
                or clip.visual_kind != "video"
                for track in video_tracks
                for clip in track.clips
            )
        )
        if requires_multitrack:
            return self._render_multitrack_ffmpeg(output_path)

        video_clips = []
        audio_clips = []

        # 1. 解析视频轨
        if video_track.clips:
            for clip_cfg in video_track.clips:
                if not os.path.exists(clip_cfg.source):
                    raise FileNotFoundError(f"视频素材文件不存在: {clip_cfg.source}")
                
                # 加载视频剪辑
                clip = VideoFileClip(clip_cfg.source)
                self._opened_clips.append(clip)

                # 如果不保留音频，清除音轨
                if not clip_cfg.keep_audio:
                    clip = clip.without_audio()

                # 限制裁剪范围
                duration = clip.duration
                trim_out = min(clip_cfg.trim_out, duration)
                trim_in = max(0.0, clip_cfg.trim_in)
                if trim_in >= trim_out:
                    raise ValueError(f"视频片段 {clip_cfg.id} 的 trim_in ({trim_in}) 必须小于 trim_out ({trim_out})")

                # 进行裁剪
                trimmed = clip.subclipped(trim_in, trim_out)
                
                # 应用视频特效链（变速、倒放、旋转）
                effects = []
                if clip_cfg.speed_factor != 1.0:
                    from moviepy.video.fx import MultiplySpeed
                    effects.append(MultiplySpeed(clip_cfg.speed_factor))
                
                if clip_cfg.reverse:
                    if trimmed.fps is None:
                        trimmed = trimmed.with_fps(clip.fps or 30)
                    orig_duration = trimmed.duration
                    if orig_duration is not None:
                        # 显式保留时长参数，防止 time_transform 将 duration 丢失为 None
                        trimmed = trimmed.time_transform(
                            lambda t: max(0.0, min(orig_duration - 0.0001, orig_duration - t)),
                            keep_duration=True
                        )
                        trimmed.duration = orig_duration
                    else:
                        from moviepy.video.fx import TimeMirror
                        effects.append(TimeMirror())
                
                if clip_cfg.rotate in (90, 180, 270):
                    from moviepy.video.fx import Rotate
                    effects.append(Rotate(clip_cfg.rotate))
                
                if effects:
                    trimmed = trimmed.with_effects(effects)
                
                # 设置在时间线上的起始播放时间
                positioned = trimmed.with_start(clip_cfg.timeline_start)
                video_clips.append(positioned)

        # 2. 解析音频轨（如背景音乐等）
        if audio_track.clips:
            for clip_cfg in audio_track.clips:
                if not os.path.exists(clip_cfg.source):
                    raise FileNotFoundError(f"音频素材文件不存在: {clip_cfg.source}")
                
                # 加载音频剪辑
                clip = AudioFileClip(clip_cfg.source)
                self._opened_clips.append(clip)

                # 限制裁剪范围
                duration = clip.duration
                trim_out = min(clip_cfg.trim_out, duration)
                trim_in = max(0.0, clip_cfg.trim_in)
                if trim_in >= trim_out:
                    raise ValueError(f"音频片段 {clip_cfg.id} 的 trim_in ({trim_in}) 必须小于 trim_out ({trim_out})")

                # 进行裁剪
                trimmed = clip.subclipped(trim_in, trim_out)
                
                # 设置音量和起始时间
                positioned = trimmed.with_start(clip_cfg.timeline_start)
                if clip_cfg.volume is not None:
                    positioned = positioned.with_volume_scaled(clip_cfg.volume)
                
                audio_clips.append(positioned)

        if not video_clips:
            raise ValueError("时间线中未包含任何有效的视频轨道，无法进行渲染。")

        # 3. 合成视频
        # 使用 CompositeVideoClip 将所有视频片段层叠/顺序播放
        final_video = CompositeVideoClip(video_clips, size=(self.config.width, self.config.height))

        # 4. 合成音频并混音
        if audio_clips:
            # 如果视频本身有音轨，需要进行混音
            # MoviePy 中 CompositeVideoClip 默认会把子 clip 的声音也带上。
            # 我们将音频轨的 clip 与 final_video 自带的音轨混音
            extra_audio = CompositeAudioClip(audio_clips)
            if final_video.audio is not None:
                mixed_audio = CompositeAudioClip([final_video.audio, extra_audio])
                final_video = final_video.with_audio(mixed_audio)
            else:
                final_video = final_video.with_audio(extra_audio)

        # 5. 导出视频文件
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        try:
            # 导出视频文件（动态识别 GPU 加速或软编）
            from utils.hardware import get_optimal_export_kwargs
            kwargs = get_optimal_export_kwargs(keep_audio=True, fps=self.config.fps)
            kwargs["temp_audiofile"] = "temp-audio.m4a"
            kwargs["remove_temp"] = True
            
            final_video.write_videofile(output_path, **kwargs)
        finally:
            # 6. 关闭所有打开的文件句柄，释放内存和文件锁
            final_video.close()
            for c in self._opened_clips:
                try:
                    c.close()
                except Exception:
                    pass
            self._opened_clips.clear()

        return output_path

    def _render_multitrack_ffmpeg(self, output_path: str) -> str:
        """Deterministic multi-layer video composition and audio mixing."""

        import json
        import subprocess

        tracks = sorted(
            (
                track
                for track in self.config.tracks.values()
                if track.enabled
            ),
            key=lambda track: (track.order, track.id),
        )
        video_items = [
            (track, clip)
            for track in tracks
            if track.kind == "video"
            for clip in sorted(
                track.clips,
                key=lambda item: (item.timeline_start, item.id),
            )
        ]
        if not video_items:
            raise ValueError(
                "A multi-track export requires an enabled video clip"
            )
        unsupported_blend = next(
            (
                clip.composite.blend_mode
                for _, clip in video_items
                if clip.composite.blend_mode != "normal"
            ),
            None,
        )
        if unsupported_blend is not None:
            raise RuntimeError(
                "The deterministic renderer currently supports only normal "
                f"clip compositing; {unsupported_blend!r} must be re-reviewed"
            )
        audio_items = [
            (track, clip)
            for track in tracks
            if track.kind == "audio" and not track.muted and not track.mix.muted
            for clip in sorted(
                track.clips,
                key=lambda item: (item.timeline_start, item.id),
            )
        ]
        all_items = [
            ("video", track, clip) for track, clip in video_items
        ] + [
            ("audio", track, clip) for track, clip in audio_items
        ]
        command = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error"]
        for kind, _, clip in all_items:
            if not os.path.isfile(clip.source):
                raise FileNotFoundError(
                    f"Configured media is unavailable: {clip.source}"
                )
            if kind == "video" and clip.visual_kind in {"image", "sticker"}:
                command.extend([
                    "-loop", "1",
                    "-framerate", str(self.config.fps),
                    "-t", f"{effective_clip_duration(clip):.12g}",
                    "-i", clip.source,
                ])
            else:
                command.extend(["-i", clip.source])

        def has_audio(path: str) -> bool:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "json",
                    path,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(json.loads(probe.stdout).get("streams"))

        def atempo(speed: float) -> list[str]:
            filters: list[str] = []
            remaining = speed
            while remaining > 2.0:
                filters.append("atempo=2.0")
                remaining /= 2.0
            while remaining < 0.5:
                filters.append("atempo=0.5")
                remaining /= 0.5
            if abs(remaining - 1.0) > 1e-9:
                filters.append(f"atempo={remaining:.12g}")
            return filters

        def pan_filter(value: float) -> str | None:
            if abs(value) <= 1e-9:
                return None
            import math

            left = math.sqrt((1.0 - value) / 2.0) * 1.41421356237
            right = math.sqrt((1.0 + value) / 2.0) * 1.41421356237
            return (
                "pan=stereo|"
                f"c0={left:.12g}*c0|c1={right:.12g}*c1"
            )

        def envelope_filter(clip: ClipConfig) -> str | None:
            points = clip.audio.envelope
            if not points:
                return None
            import math

            amplitudes = [10 ** (point.gain_db / 20.0) for point in points]
            expression = f"{amplitudes[-1]:.12g}"
            for index in range(len(points) - 2, -1, -1):
                left_point = points[index]
                right_point = points[index + 1]
                left = amplitudes[index]
                right = amplitudes[index + 1]
                span = right_point.offset_seconds - left_point.offset_seconds
                interpolated = (
                    f"{left:.12g}+(t-{left_point.offset_seconds:.12g})*"
                    f"{(right-left):.12g}/{span:.12g}"
                )
                expression = (
                    f"if(lt(t,{right_point.offset_seconds:.12g}),"
                    f"{interpolated},{expression})"
                )
            expression = (
                f"if(lt(t,{points[0].offset_seconds:.12g}),"
                f"{amplitudes[0]:.12g},{expression})"
            )
            return f"volume='{expression}':eval=frame"

        def audio_filters(
            track: TrackConfig,
            clip: ClipConfig,
            clip_duration_seconds: float,
        ) -> list[str]:
            chain = ["aformat=channel_layouts=stereo"]
            legacy_volume = 1.0 if clip.volume is None else clip.volume
            track_gain = track.mix.gain_db if track.kind == "audio" else 0.0
            gain = legacy_volume * 10 ** (
                (clip.audio.gain_db + track_gain) / 20.0
            )
            if clip.audio.muted:
                gain = 0.0
            chain.append(f"volume={gain:.12g}")
            pan = clip.audio.pan + (
                track.mix.pan if track.kind == "audio" else 0.0
            )
            pan_stage = pan_filter(max(-1.0, min(1.0, pan)))
            if pan_stage:
                chain.append(pan_stage)
            envelope_stage = envelope_filter(clip)
            if envelope_stage:
                chain.append(envelope_stage)
            if clip.audio.fade_in_seconds > 0:
                chain.append(
                    "afade=t=in:st=0:"
                    f"d={clip.audio.fade_in_seconds:.12g}"
                )
            if clip.audio.fade_out_seconds > 0:
                start = max(
                    0.0,
                    clip_duration_seconds - clip.audio.fade_out_seconds,
                )
                chain.append(
                    f"afade=t=out:st={start:.12g}:"
                    f"d={clip.audio.fade_out_seconds:.12g}"
                )
            return chain

        duration = max(
            (
                clip.timeline_start + effective_clip_duration(clip)
                for _, _, clip in all_items
            ),
            default=0.0,
        )
        filters = [
            f"color=c=black:s={self.config.width}x{self.config.height}:"
            f"r={self.config.fps}:d={duration:.12g}[base]"
        ]
        audio_labels: list[str] = []
        video_labels: list[tuple[str, str]] = []
        for index, (kind, track, clip) in enumerate(all_items):
            delay_ms = max(0, round(clip.timeline_start * 1000))
            if kind == "video":
                from visuals.render import clip_visual_filter_chain

                if clip.visual_kind in {"image", "sticker"}:
                    chain = [
                        f"[{index}:v]trim=duration={effective_clip_duration(clip):.12g}",
                        "setpts=PTS-STARTPTS",
                    ]
                elif clip.freeze_frame is not None:
                    frame_window = max(1.0 / self.config.fps, 0.001)
                    chain = [
                        f"[{index}:v]trim=start={clip.freeze_frame.source_time_seconds:.12g}:"
                        f"end={clip.freeze_frame.source_time_seconds + frame_window:.12g}",
                        "setpts=PTS-STARTPTS",
                        "tpad=stop_mode=clone:"
                        f"stop_duration={clip.freeze_frame.duration_seconds:.12g}",
                        f"trim=duration={clip.freeze_frame.duration_seconds:.12g}",
                    ]
                else:
                    chain = [
                        f"[{index}:v]trim=start={clip.trim_in:.12g}:"
                        f"end={clip.trim_out:.12g}",
                        f"setpts=(PTS-STARTPTS)/{clip.speed_factor:.12g}",
                    ]
                    if clip.reverse:
                        chain.append("reverse")
                visual_chain, overlay_expression = clip_visual_filter_chain(
                    clip,
                    self.config.width,
                    self.config.height,
                )
                chain.extend((
                    *visual_chain,
                    f"fps={self.config.fps}",
                    f"setpts=PTS+{clip.timeline_start:.12g}/TB"
                    f"[video_{index}]",
                ))
                filters.append(",".join(chain))
                video_labels.append((f"[video_{index}]", overlay_expression))
                if (
                    clip.keep_audio
                    and clip.visual_kind == "video"
                    and clip.freeze_frame is None
                    and not track.muted
                    and not clip.audio.muted
                    and has_audio(clip.source)
                ):
                    effective_duration = effective_clip_duration(clip)
                    audio_chain = [
                        f"[{index}:a]atrim=start={clip.trim_in:.12g}:"
                        f"end={clip.trim_out:.12g}",
                        "asetpts=PTS-STARTPTS",
                        *atempo(clip.speed_factor),
                        *audio_filters(track, clip, effective_duration),
                    ]
                    if clip.reverse:
                        audio_chain.append("areverse")
                    audio_chain.extend((
                        f"adelay={delay_ms}|{delay_ms}",
                        f"atrim=end={duration:.12g}[audio_{index}]",
                    ))
                    filters.append(",".join(audio_chain))
                    audio_labels.append(f"[audio_{index}]")
            elif not clip.audio.muted and has_audio(clip.source):
                effective_duration = effective_clip_duration(clip)
                audio_chain = [
                    f"[{index}:a]atrim=start={clip.trim_in:.12g}:"
                    f"end={clip.trim_out:.12g}",
                    "asetpts=PTS-STARTPTS",
                    *atempo(clip.speed_factor),
                    *audio_filters(track, clip, effective_duration),
                ]
                if clip.reverse:
                    audio_chain.append("areverse")
                audio_chain.extend((
                    f"adelay={delay_ms}|{delay_ms}",
                    f"atrim=end={duration:.12g}[audio_{index}]",
                ))
                filters.append(",".join(audio_chain))
                audio_labels.append(f"[audio_{index}]")

        current = "[base]"
        for layer_index, (label, overlay_expression) in enumerate(video_labels):
            output = f"[layer_{layer_index}]"
            filters.append(
                f"{current}{label}overlay={overlay_expression}:"
                "eof_action=pass:shortest=0"
                f"{output}"
            )
            current = output
        filters.append(f"{current}format=yuv420p[video_out]")
        if audio_labels:
            filters.append(
                "".join(audio_labels)
                + f"amix=inputs={len(audio_labels)}:"
                "duration=longest:normalize=0,"
                "alimiter=limit=0.95:level=false,"
                "aresample=48000,aformat=channel_layouts=stereo[audio_out]"
            )
        command.extend([
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[video_out]",
        ])
        if audio_labels:
            command.extend([
                "-map", "[audio_out]", "-c:a", "aac", "-ar", "48000", "-ac", "2"
            ])
        command.extend([
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.config.fps),
            "-t",
            f"{duration:.12g}",
            output_path,
        ])
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Deterministic multi-track FFmpeg export timed out"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "Deterministic multi-track FFmpeg export failed: "
                + " ".join((exc.stderr or "").strip().splitlines()[-2:])
            ) from exc
        return output_path

    def _render_fast_path(self, output_path: str) -> str:
        """
        极速直通渲染引擎：
        当时间轴非常纯净（只有一个主视频，无叠加图层或混音）时，
        绕过 MoviePy 内存交换流，直接将操作转化为纯 FFmpeg 底层滤镜进行原生渲染，性能提升最高可达上百倍！
        """
        import subprocess
        from moviepy import VideoFileClip
        from utils.hardware import _detect_hardware_encoder
        
        clip_cfg = self.config.tracks["video"].clips[0]
        
        # 探测是否有音频轨
        has_audio = False
        try:
            probe = VideoFileClip(clip_cfg.source)
            has_audio = probe.audio is not None
            probe.close()
        except:
            pass

        v_filters = []
        a_filters = []
        input_args = []
        
        # 截取 (前置截取效率最高)
        if clip_cfg.trim_in > 0:
            input_args.extend(["-ss", str(clip_cfg.trim_in)])
            
        if clip_cfg.trim_out < 999999.0:
            duration_to_cut = clip_cfg.trim_out - clip_cfg.trim_in
            input_args.extend(["-t", str(duration_to_cut)])

        # 变速
        if clip_cfg.speed_factor != 1.0:
            pts_factor = 1.0 / clip_cfg.speed_factor
            v_filters.append(f"setpts={pts_factor}*PTS")
            
            # FFmpeg atempo 限制 0.5 到 2.0，超过则需要级联
            temp_speed = clip_cfg.speed_factor
            while temp_speed > 2.0:
                a_filters.append("atempo=2.0")
                temp_speed /= 2.0
            while temp_speed < 0.5:
                a_filters.append("atempo=0.5")
                temp_speed /= 0.5
            if temp_speed != 1.0:
                a_filters.append(f"atempo={temp_speed}")
            
        # 旋转
        if clip_cfg.rotate == 90:
            v_filters.append("transpose=1")
        elif clip_cfg.rotate == 180:
            v_filters.append("transpose=2,transpose=2")
        elif clip_cfg.rotate == 270:
            v_filters.append("transpose=2")
            
        # 倒放
        if clip_cfg.reverse:
            v_filters.append("reverse")
            a_filters.append("areverse")
            
        cmd = ["ffmpeg", "-y"]
        cmd.extend(input_args)
        cmd.extend(["-i", clip_cfg.source])
        
        use_audio = clip_cfg.keep_audio and has_audio
        
        if v_filters or a_filters:
            filter_complex = ""
            if v_filters:
                filter_complex += f"[0:v]{','.join(v_filters)}[v];"
            if use_audio and a_filters:
                filter_complex += f"[0:a]{','.join(a_filters)}[a];"
            
            if filter_complex:
                filter_complex = filter_complex.rstrip(";")
                cmd.extend(["-filter_complex", filter_complex])
                
                if v_filters:
                    cmd.extend(["-map", "[v]"])
                else:
                    cmd.extend(["-map", "0:v"])
                    
                if use_audio:
                    if a_filters:
                        cmd.extend(["-map", "[a]"])
                    else:
                        cmd.extend(["-map", "0:a"])
        else:
            if not use_audio:
                cmd.append("-an")
        
        # 编码参数
        gpu_encoder = _detect_hardware_encoder()
        if gpu_encoder:
            cmd.extend(["-c:v", gpu_encoder, "-cq", "18", "-pix_fmt", "yuv420p"])
        else:
            cmd.extend(["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"])
            
        if use_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            
        cmd.append(output_path)
        
        print(f"[Fast-Path] 探测到单轴纯净场景，已启用 FFmpeg 底层极速直通渲染通道！")
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path

    def _render_multi_fast_path(self, output_path: str) -> str:
        """
        多片段极速并发拼接引擎 (Multi-Fast-Path):
        将时间线上多个含有各自属性（裁切/倍速/旋转/倒放）的视频，并发执行“标准化转码”，
        并强制填充黑边对齐工程分辨率。最后使用 concat demuxer 进行无损缝合，全过程抛弃 MoviePy。
        """
        import uuid
        import subprocess
        from concurrent.futures import ThreadPoolExecutor
        from moviepy import VideoFileClip
        from utils.hardware import _detect_hardware_encoder
        
        WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".workspace"))
        CACHE_DIR = os.path.join(WORKSPACE_DIR, "fast_concat_cache")
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        clips = self.config.tracks["video"].clips
        target_w = self.config.width
        target_h = self.config.height
        target_fps = self.config.fps
        
        temp_files = []
        futures = []
        
        gpu_encoder = _detect_hardware_encoder()
        
        def _normalize_clip(clip_cfg, out_path, idx):
            # 探测是否有音频轨
            has_audio = False
            try:
                probe = VideoFileClip(clip_cfg.source)
                has_audio = probe.audio is not None
                probe.close()
            except:
                pass

            v_filters = []
            a_filters = []
            input_args = []
            
            # 截取
            if clip_cfg.trim_in > 0:
                input_args.extend(["-ss", str(clip_cfg.trim_in)])
            if clip_cfg.trim_out < 999999.0:
                duration_to_cut = clip_cfg.trim_out - clip_cfg.trim_in
                input_args.extend(["-t", str(duration_to_cut)])

            # 变速
            if clip_cfg.speed_factor != 1.0:
                pts_factor = 1.0 / clip_cfg.speed_factor
                v_filters.append(f"setpts={pts_factor}*PTS")
                
                temp_speed = clip_cfg.speed_factor
                while temp_speed > 2.0:
                    a_filters.append("atempo=2.0")
                    temp_speed /= 2.0
                while temp_speed < 0.5:
                    a_filters.append("atempo=0.5")
                    temp_speed /= 0.5
                if temp_speed != 1.0:
                    a_filters.append(f"atempo={temp_speed}")
                
            # 旋转
            if clip_cfg.rotate == 90:
                v_filters.append("transpose=1")
            elif clip_cfg.rotate == 180:
                v_filters.append("transpose=2,transpose=2")
            elif clip_cfg.rotate == 270:
                v_filters.append("transpose=2")
                
            # 倒放
            if clip_cfg.reverse:
                v_filters.append("reverse")
                a_filters.append("areverse")
                
            # --- 核心：画面与音频归一化滤镜 ---
            norm_v = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,fps={target_fps},format=yuv420p"
            v_filters.append(norm_v)
            a_filters.append("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo")
            
            cmd = ["ffmpeg", "-y"]
            cmd.extend(input_args)
            cmd.extend(["-i", clip_cfg.source])
            
            use_audio = clip_cfg.keep_audio and has_audio
            
            filter_complex = ""
            if not use_audio:
                # 为了 concat 不出错，为无声视频自动补齐静音轨
                filter_complex += f"anullsrc=r=48000:cl=stereo[null_a];"
                
            if v_filters:
                filter_complex += f"[0:v]{','.join(v_filters)}[v];"
            else:
                filter_complex += f"[0:v]{norm_v}[v];"
                
            if use_audio:
                if a_filters:
                    filter_complex += f"[0:a]{','.join(a_filters)}[a];"
                else:
                    filter_complex += f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a];"
            
            if filter_complex:
                filter_complex = filter_complex.rstrip(";")
                cmd.extend(["-filter_complex", filter_complex])
                cmd.extend(["-map", "[v]"])
                if use_audio:
                    cmd.extend(["-map", "[a]"])
                else:
                    cmd.extend(["-map", "[null_a]"])
            
            # 编码参数
            if gpu_encoder:
                cmd.extend(["-c:v", gpu_encoder, "-cq", "18", "-pix_fmt", "yuv420p"])
            else:
                cmd.extend(["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"])
                
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            
            if not use_audio:
                cmd.extend(["-shortest"])

            cmd.append(out_path)
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, check=True)
            return out_path
        
        session_id = uuid.uuid4().hex[:8]
        print(f"\n[Multi-Fast-Path] 侦测到多片段串接场景！启动并发归一化流水线 (片段数: {len(clips)})...")
        
        max_workers = min(len(clips), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx, clip_cfg in enumerate(clips):
                out_p = os.path.join(CACHE_DIR, f"norm_{session_id}_{idx}.mp4")
                temp_files.append(out_p)
                futures.append(executor.submit(_normalize_clip, clip_cfg, out_p, idx))
                
            for f in futures:
                f.result() 
                
        print("[Multi-Fast-Path] 标准化分片出线，启动毫秒级物理缝合...")
        
        concat_txt_path = os.path.join(CACHE_DIR, f"concat_list_{session_id}.txt")
        with open(concat_txt_path, "w", encoding="utf-8") as f:
            for tf in temp_files:
                f.write(f"file '{tf.replace(chr(92), '/')}'\n")
                
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt_path,
            "-c", "copy",
            output_path
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, check=True)
        
        print(f"[Multi-Fast-Path] 多片段极速缝合完毕！")
        
        for tf in temp_files:
            try:
                os.remove(tf)
            except:
                pass
        try:
            os.remove(concat_txt_path)
        except:
            pass
            
        return output_path
