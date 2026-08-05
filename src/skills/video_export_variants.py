"""Deterministic, bounded multi-specification media export skill."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.timeline import TimelineRenderer
from core.timeline_manager import TimelineManager
from subtitles import analyze_subtitle_layout, burn_subtitles

from .base import BaseSkill


class VideoExportVariant(BaseModel):
    """One exact output canvas in a deterministic export set."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_name: Literal["vistora.video-export-variant"] = (
        "vistora.video-export-variant"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    variant_id: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    output_path: str = Field(min_length=1, max_length=4096)
    width: int = Field(ge=16, le=8192, multiple_of=2)
    height: int = Field(ge=16, le=8192, multiple_of=2)
    fps: float = Field(ge=1, le=120, allow_inf_nan=False)

    @field_validator("output_path")
    @classmethod
    def output_is_absolute_mp4(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("Export output paths must be absolute")
        if path.suffix.lower() != ".mp4":
            raise ValueError("Multi-spec export currently supports .mp4 outputs only")
        return str(path)


class VideoExportVariantsInput(BaseModel):
    """Frozen input contract for two to eight explicit output variants."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    schema_name: Literal["vistora.video-export-variants-input"] = (
        "vistora.video-export-variants-input"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    export_set_id: str = Field(
        min_length=3,
        max_length=96,
        pattern=r"^[A-Za-z][A-Za-z0-9._:-]*$",
    )
    variants: tuple[VideoExportVariant, ...] = Field(min_length=2, max_length=8)
    subtitle_mode: Literal["none", "burn"] = "none"
    subtitle_track_ids: tuple[str, ...] = ()
    output_policy: Literal["create_new"] = "create_new"

    @model_validator(mode="after")
    def variants_are_unique_and_stable(self) -> "VideoExportVariantsInput":
        variant_ids = tuple(item.variant_id for item in self.variants)
        if variant_ids != tuple(sorted(set(variant_ids))):
            raise ValueError("Variant IDs must be unique and stably sorted")
        normalized_paths = tuple(
            os.path.normcase(os.path.abspath(item.output_path))
            for item in self.variants
        )
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("Variant output paths must be unique")
        if self.subtitle_mode == "none" and self.subtitle_track_ids:
            raise ValueError("Subtitle track IDs require subtitle_mode=burn")
        if self.subtitle_track_ids != tuple(sorted(set(self.subtitle_track_ids))):
            raise ValueError("Subtitle track IDs must be unique and stably sorted")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _fsync_file(path: Path) -> None:
    # Windows rejects fsync on some read-only CRT descriptors; append mode does
    # not change existing bytes and yields a writable descriptor that can flush.
    with path.open("ab") as stream:
        stream.flush()
        os.fsync(stream.fileno())


class VideoExportVariantsSkill(BaseSkill):
    """Render an exact timeline revision to multiple explicit canvases."""

    name = "VideoExportVariantsSkill"
    description = (
        "Export the confirmed timeline to two to eight explicit MP4 canvas/frame-rate "
        "variants. Outputs are staged in their destination directories and published "
        "only after every render succeeds; existing files are never overwritten."
    )
    input_model = VideoExportVariantsInput

    def run(self, params: VideoExportVariantsInput) -> dict[str, Any]:
        timeline = TimelineManager.get_current_timeline()
        if not any(
            track.enabled and track.kind == "video" and track.clips
            for track in timeline.tracks.values()
        ):
            raise ValueError("Multi-spec export requires an enabled video clip")

        selected_subtitle_ids = set(params.subtitle_track_ids)
        known_subtitle_ids = set(timeline.subtitle_tracks)
        if selected_subtitle_ids - known_subtitle_ids:
            raise ValueError("Subtitle burn references an unknown track")

        staged: list[
            tuple[VideoExportVariant, Path, tuple[str, ...], tuple[dict[str, Any], ...]]
        ] = []
        committed: list[Path] = []
        temporary_paths: set[Path] = set()
        try:
            for variant in params.variants:
                target = Path(variant.output_path)
                if not target.parent.is_dir():
                    raise ValueError("Every export destination directory must exist")
                if target.exists():
                    raise FileExistsError("Multi-spec export never overwrites existing files")

            for variant in params.variants:
                target = Path(variant.output_path)
                token = uuid.uuid4().hex
                staged_output = target.parent / (
                    f".vistora-export-{params.export_set_id}-{variant.variant_id}-{token}.mp4"
                )
                temporary_paths.add(staged_output)
                variant_timeline = timeline.model_copy(
                    update={
                        "width": variant.width,
                        "height": variant.height,
                        "fps": variant.fps,
                    }
                )
                renderer = TimelineRenderer(variant_timeline)
                font_warnings: tuple[str, ...] = ()
                subtitle_layout: tuple[dict[str, Any], ...] = ()
                if params.subtitle_mode == "burn":
                    subtitle_layout = analyze_subtitle_layout(
                        variant_timeline,
                        params.subtitle_track_ids,
                    )
                    base_output = target.parent / (
                        f".vistora-export-base-{params.export_set_id}-"
                        f"{variant.variant_id}-{token}.mp4"
                    )
                    temporary_paths.add(base_output)
                    renderer.render(str(base_output), enforce_canvas=True)
                    _, font_warnings = burn_subtitles(
                        str(base_output),
                        str(staged_output),
                        variant_timeline,
                        params.subtitle_track_ids,
                    )
                    base_output.unlink(missing_ok=True)
                    temporary_paths.discard(base_output)
                else:
                    renderer.render(str(staged_output), enforce_canvas=True)
                if not staged_output.is_file() or staged_output.stat().st_size <= 0:
                    raise RuntimeError("A staged export did not produce a valid file")
                _fsync_file(staged_output)
                staged.append(
                    (
                        variant,
                        staged_output,
                        tuple(font_warnings),
                        subtitle_layout,
                    )
                )

            # Hard-link publication is an atomic create-new operation and fails if a
            # concurrent writer created the destination after preflight.
            for variant, staged_output, _, _ in staged:
                target = Path(variant.output_path)
                os.link(staged_output, target)
                committed.append(target)

            outputs: list[dict[str, Any]] = []
            for variant, staged_output, font_warnings, subtitle_layout in staged:
                target = Path(variant.output_path)
                outputs.append(
                    {
                        "variant_id": variant.variant_id,
                        "output_path": str(target),
                        "width": variant.width,
                        "height": variant.height,
                        "fps": variant.fps,
                        "size_bytes": target.stat().st_size,
                        "sha256": _sha256(target),
                        "font_warnings": list(font_warnings),
                        "subtitle_layout": list(subtitle_layout),
                    }
                )
            return {
                "status": "success",
                "export_set_id": params.export_set_id,
                "output_policy": params.output_policy,
                "subtitle_mode": params.subtitle_mode,
                "outputs": outputs,
            }
        except Exception:
            for target in reversed(committed):
                target.unlink(missing_ok=True)
            raise
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)
