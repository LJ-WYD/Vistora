"""Safe deterministic FFmpeg visual filter construction."""

from __future__ import annotations

from core.timeline import ClipColorAdjustment, ClipConfig


def _number(value: float) -> str:
    return f"{value:.12g}"


def clip_visual_filter_chain(
    clip: ClipConfig,
    canvas_width: int,
    canvas_height: int,
) -> tuple[list[str], str]:
    """Return validated filters and an overlay expression without raw input."""

    transform = clip.transform
    color = clip.color
    chain: list[str] = []
    if any(
        value > 0
        for value in (
            transform.crop_left,
            transform.crop_right,
            transform.crop_top,
            transform.crop_bottom,
        )
    ):
        width = 1 - transform.crop_left - transform.crop_right
        height = 1 - transform.crop_top - transform.crop_bottom
        chain.append(
            "crop="
            f"iw*{_number(width)}:ih*{_number(height)}:"
            f"iw*{_number(transform.crop_left)}:"
            f"ih*{_number(transform.crop_top)}"
        )
    if transform.flip_horizontal:
        chain.append("hflip")
    if transform.flip_vertical:
        chain.append("vflip")
    if clip.rotate == 90:
        chain.append("transpose=1")
    elif clip.rotate == 180:
        chain.extend(("transpose=1", "transpose=1"))
    elif clip.rotate == 270:
        chain.append("transpose=2")
    if abs(transform.rotation_degrees) > 1e-9:
        angle = _number(transform.rotation_degrees)
        chain.append(
            f"rotate={angle}*PI/180:ow=rotw(iw):oh=roth(ih):c=black@0"
        )
    if transform.fit == "contain":
        chain.append(
            f"scale={canvas_width}:{canvas_height}:"
            "force_original_aspect_ratio=decrease"
        )
    elif transform.fit == "fill":
        chain.extend((
            f"scale={canvas_width}:{canvas_height}:"
            "force_original_aspect_ratio=increase",
            f"crop={canvas_width}:{canvas_height}:(iw-{canvas_width})/2:"
            f"(ih-{canvas_height})/2",
        ))
    else:
        chain.append(f"scale={canvas_width}:{canvas_height}")
    if abs(transform.scale_x - 1) > 1e-9 or abs(transform.scale_y - 1) > 1e-9:
        chain.append(
            "scale="
            f"'max(2,trunc(iw*{_number(transform.scale_x)}/2)*2)':"
            f"'max(2,trunc(ih*{_number(transform.scale_y)}/2)*2)'"
        )
    chain.extend(color_filter_chain(color))
    if transform.opacity < 1:
        chain.append(f"colorchannelmixer=aa={_number(transform.opacity)}")
    chain.append("format=rgba")
    overlay = (
        f"x={_number(transform.position_x)}*main_w-"
        f"{_number(transform.anchor_x)}*overlay_w:"
        f"y={_number(transform.position_y)}*main_h-"
        f"{_number(transform.anchor_y)}*overlay_h"
    )
    return chain, overlay


def color_filter_chain(color: ClipColorAdjustment) -> list[str]:
    """Deterministic bounded SDR filter order: tonal, balance, detail."""

    chain: list[str] = []
    if any(
        abs(value) > 1e-9
        for value in (
            color.exposure,
            color.contrast,
            color.saturation,
            color.gamma - 1,
        )
    ):
        chain.append(
            "eq="
            f"brightness={_number(color.exposure / 4)}:"
            f"contrast={_number(1 + color.contrast)}:"
            f"saturation={_number(1 + color.saturation)}:"
            f"gamma={_number(color.gamma)}:gamma_weight=1"
        )
    if any(
        abs(value) > 1e-9
        for value in (
            color.temperature,
            color.tint,
            color.highlights,
            color.shadows,
        )
    ):
        shadow = color.shadows * 0.15
        temperature = color.temperature * 0.15
        highlight = color.highlights * 0.15
        chain.append(
            "colorbalance="
            f"rs={_number(shadow + temperature)}:"
            f"gs={_number(shadow)}:bs={_number(shadow - temperature)}:"
            f"rm=0:gm={_number(color.tint * 0.15)}:bm=0:"
            f"rh={_number(highlight)}:gh={_number(highlight)}:"
            f"bh={_number(highlight)}:pl=1"
        )
    if color.sharpen > 0:
        chain.append(f"unsharp=5:5:{_number(color.sharpen)}:5:5:0")
    elif color.blur > 0:
        chain.append(f"gblur=sigma={_number(color.blur)}")
    return chain
