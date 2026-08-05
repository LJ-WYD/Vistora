"""Confirmed, transactional static image/sticker insertion skill."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image

from core import timeline_manager
from core.timeline import ClipConfig
from graphics import InsertGraphicInput
from material_production import MaterialCatalogStore
from timeline_edit import TimelineEditEngine, TimelineEditTransaction

from .base import BaseSkill


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _resolve_graphic(source_path: str) -> str:
    if source_path.startswith("material://"):
        resolved = MaterialCatalogStore.for_project_file(
            timeline_manager.PROJECT_FILE
        ).resolve_uri(source_path)
        if resolved is None:
            raise FileNotFoundError(
                "Catalog graphic is missing, unaccepted, or tampered"
            )
        return str(resolved)
    if not os.path.isfile(source_path):
        raise FileNotFoundError("The configured graphic source is unavailable")
    return source_path


def _validate_graphic(path: str, kind: str) -> tuple[int, int]:
    source = Path(path)
    if source.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise ValueError("Graphics must be PNG, JPEG, or WebP images")
    try:
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            width, height = image.size
            bands = image.getbands()
    except Exception as exc:
        raise ValueError("Graphic media could not be decoded safely") from exc
    if width <= 0 or height <= 0 or width > 16384 or height > 16384:
        raise ValueError("Graphic dimensions are outside the supported range")
    if width * height > 67_108_864:
        raise ValueError("Graphic pixel count exceeds the supported limit")
    if kind == "sticker" and "A" not in bands:
        raise ValueError("Sticker graphics require a decoded alpha channel")
    return width, height


class VideoInsertGraphicSkill(BaseSkill):
    name = "VideoInsertGraphicSkill"
    description = (
        "Insert or overwrite one validated static image/sticker on an exact "
        "unlocked video track for a bounded duration. The source is read-only."
    )
    input_model = InsertGraphicInput

    def run(self, params: InsertGraphicInput) -> dict[str, Any]:
        resolved = _resolve_graphic(params.source_path)
        _validate_graphic(resolved, params.graphic_kind)
        current = timeline_manager.TimelineManager.get_current_timeline()
        if TimelineEditEngine(current).track_kind(params.track_reference) != "video":
            raise ValueError("Graphics require an exact video track")
        clip = ClipConfig(
            id=params.clip_id,
            source=resolved,
            visual_kind=params.graphic_kind,
            trim_in=0,
            trim_out=params.duration_seconds,
            timeline_start=params.timeline_start,
            keep_audio=False,
            speed_factor=1,
            reverse=False,
            transform=params.transform,
        )
        return TimelineEditTransaction.apply(
            lambda engine: engine.insert_overwrite(
                params.track_reference,
                clip,
                mode=params.mode,
                edit_scope="current_clip",
            ),
        )
