"""Safe deterministic FFmpeg visual filter construction."""

from __future__ import annotations

from core.timeline import ClipColorAdjustment, ClipConfig
from visual_automation.runtime import ffmpeg_property_expressions


def _number(value: float) -> str:
    return f"{value:.12g}"


def clip_visual_filter_chain(
    clip: ClipConfig,
    canvas_width: int,
    canvas_height: int,
    *,
    local_time_expression: str = "t",
) -> tuple[list[str], str]:
    """Return validated filters and an overlay expression without raw input."""

    transform = clip.transform
    color = clip.color
    animated = ffmpeg_property_expressions(
        clip, variable=local_time_expression
    )
    animated_geq = ffmpeg_property_expressions(
        clip, variable=local_time_expression.replace("t", "T")
    )

    def value(path: str, fallback: float) -> str:
        return animated.get(path, _number(fallback))

    chain: list[str] = []
    crop_paths = (
        "transform.crop_left",
        "transform.crop_right",
        "transform.crop_top",
        "transform.crop_bottom",
    )
    if any(path in animated for path in crop_paths) or any(
        item > 0
        for item in (
            transform.crop_left,
            transform.crop_right,
            transform.crop_top,
            transform.crop_bottom,
        )
    ):
        left = value("transform.crop_left", transform.crop_left)
        right = value("transform.crop_right", transform.crop_right)
        top = value("transform.crop_top", transform.crop_top)
        bottom = value("transform.crop_bottom", transform.crop_bottom)
        chain.append(
            "crop="
            f"w='max(2,iw*(1-({left})-({right})))':"
            f"h='max(2,ih*(1-({top})-({bottom})))':"
            f"x='iw*({left})':y='ih*({top})'"
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
    if (
        "transform.rotation_degrees" in animated
        or abs(transform.rotation_degrees) > 1e-9
    ):
        angle = value(
            "transform.rotation_degrees", transform.rotation_degrees
        )
        chain.append(
            f"rotate='({angle})*PI/180':ow=rotw(iw):oh=roth(ih):c=black@0"
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
    uniform = animated.get("transform.scale_uniform")
    scale_x = uniform or value("transform.scale_x", transform.scale_x)
    scale_y = uniform or value("transform.scale_y", transform.scale_y)
    if uniform is not None or any(
        path in animated
        for path in ("transform.scale_x", "transform.scale_y")
    ) or abs(transform.scale_x - 1) > 1e-9 or abs(transform.scale_y - 1) > 1e-9:
        chain.append(
            "scale="
            f"w='max(2,trunc(iw*({scale_x})/2)*2)':"
            f"h='max(2,trunc(ih*({scale_y})/2)*2)':eval=frame"
        )
    animated_color_fields = {
        path.split(".", 1)[1]
        for path in animated
        if path.startswith("color.")
    }
    static_color = color.model_copy(
        update={
            field: (1.0 if field == "gamma" else 0.0)
            for field in animated_color_fields
        }
    )
    chain.extend(color_filter_chain(static_color))
    dynamic_eq = any(
        f"color.{field}" in animated
        for field in ("exposure", "contrast", "saturation", "gamma")
    )
    if dynamic_eq:
        exposure = value("color.exposure", color.exposure)
        contrast = value("color.contrast", color.contrast)
        saturation = value("color.saturation", color.saturation)
        gamma = value("color.gamma", color.gamma)
        chain.append(
            "eq="
            f"brightness='({exposure})/4':contrast='1+({contrast})':"
            f"saturation='1+({saturation})':gamma='({gamma})':"
            "gamma_weight=1:eval=frame"
        )
    chain.append("format=rgba")
    dynamic_balance = any(
        path in animated
        for path in ("color.temperature", "color.tint")
    )
    dynamic_opacity = "transform.opacity" in animated
    if dynamic_balance or dynamic_opacity:
        temperature = animated_geq.get(
            "color.temperature", _number(color.temperature)
        )
        tint = animated_geq.get("color.tint", _number(color.tint))
        opacity = animated_geq.get(
            "transform.opacity", _number(transform.opacity)
        )
        chain.append(
            "geq="
            f"r='clip(r(X,Y)*(1+({temperature})*0.15),0,255)':"
            f"g='clip(g(X,Y)*(1+({tint})*0.15),0,255)':"
            f"b='clip(b(X,Y)*(1-({temperature})*0.15),0,255)':"
            f"a='clip(alpha(X,Y)*({opacity}),0,255)'"
        )
    elif transform.opacity < 1:
        chain.append(f"colorchannelmixer=aa={_number(transform.opacity)}")
    overlay = (
        f"x='({value('transform.position_x', transform.position_x)})*main_w-"
        f"{_number(transform.anchor_x)}*overlay_w':"
        f"y='({value('transform.position_y', transform.position_y)})*main_h-"
        f"{_number(transform.anchor_y)}*overlay_h':eval=frame"
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
