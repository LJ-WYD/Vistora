"""Build deterministic FFmpeg alpha expressions from validated masks."""

from __future__ import annotations

import math

from core.timeline import ClipMask, MaskAutomation


def _number(value: float) -> str:
    return f"{value:.12g}"


def _curve_expression(curve: MaskAutomation, fallback: float, variable: str) -> str:
    points = curve.keyframes
    expression = _number(points[-1].value)
    for index in range(len(points) - 2, -1, -1):
        left, right = points[index], points[index + 1]
        span = right.offset_seconds - left.offset_seconds
        normalized = f"clip(({variable}-{_number(left.offset_seconds)})/{_number(span)},0,1)"
        if left.interpolation == "hold":
            progress = "0"
        elif left.interpolation == "linear":
            progress = normalized
        elif left.interpolation == "ease_in":
            progress = f"pow({normalized},2)"
        elif left.interpolation == "ease_out":
            progress = f"(1-pow(1-({normalized}),2))"
        else:
            progress = f"(({normalized})*({normalized})*(3-2*({normalized})))"
        segment = f"({_number(left.value)}+({_number(right.value-left.value)})*({progress}))"
        expression = f"if(lt({variable},{_number(right.offset_seconds)}),{segment},{expression})"
    return f"if(lt({variable},{_number(points[0].offset_seconds)}),{_number(fallback)},{expression})"


def _value(mask: ClipMask, name: str, fallback: float, variable: str) -> str:
    curve = next((item for item in mask.automations if item.enabled and item.property_path == name), None)
    return _curve_expression(curve, fallback, variable) if curve else _number(fallback)


def _shape_expression(mask: ClipMask, variable: str) -> str:
    cx = _value(mask, "position_x", mask.position_x, variable)
    cy = _value(mask, "position_y", mask.position_y, variable)
    sx = _value(mask, "scale_x", mask.scale_x, variable)
    sy = _value(mask, "scale_y", mask.scale_y, variable)
    rotation = _value(mask, "rotation_degrees", mask.rotation_degrees, variable)
    feather = _value(mask, "feather", mask.feather, variable)
    cos_value = f"cos(({rotation})*PI/180)"
    sin_value = f"sin(({rotation})*PI/180)"
    dx = f"(X/W-({cx}))"
    dy = f"(Y/H-({cy}))"
    u = f"(({dx})*({cos_value})+({dy})*({sin_value}))/({sx})"
    v = f"(-({dx})*({sin_value})+({dy})*({cos_value}))/({sy})"
    expand = _number(mask.expand)
    if mask.kind in {"rectangle", "ellipse"}:
        half_w = f"({_number((mask.width or 0)/2)}+({expand}))"
        half_h = f"({_number((mask.height or 0)/2)}+({expand}))"
        if mask.kind == "rectangle":
            distance = f"min(({half_w})-abs({u}),({half_h})-abs({v}))"
        else:
            distance = (
                f"(1-sqrt(pow(({u})/({half_w}),2)+"
                f"pow(({v})/({half_h}),2)))*min(({half_w}),({half_h}))"
            )
    else:
        points = mask.points
        orientation = sum(
            points[index].x * points[(index + 1) % len(points)].y
            - points[(index + 1) % len(points)].x * points[index].y
            for index in range(len(points))
        )
        distances: list[str] = []
        for index, point in enumerate(points):
            nxt = points[(index + 1) % len(points)]
            ex, ey = nxt.x - point.x, nxt.y - point.y
            length = max(math.hypot(ex, ey), 1e-9)
            cross = f"(({_number(ex)})*(({v})-{_number(point.y)})-({_number(ey)})*(({u})-{_number(point.x)}))/{_number(length)}"
            distances.append(cross if orientation > 0 else f"-({cross})")
        distance = distances[0]
        for item in distances[1:]:
            distance = f"min({distance},{item})"
        distance = f"({distance})+({expand})"
    hard = f"gte(({distance}),0)"
    soft = f"clip((({distance})+({feather}))/max(0.000001,2*({feather})),0,1)"
    shape = f"if(lte(({feather}),0.000001),{hard},{soft})"
    if mask.invert:
        shape = f"(1-({shape}))"
    opacity = _value(mask, "opacity", mask.opacity, variable)
    return f"clip(({shape})*({opacity}),0,1)"


def mask_alpha_expression(masks: tuple[ClipMask, ...], *, variable: str = "T") -> str | None:
    """Return one stable normalized alpha expression for enabled masks."""

    enabled = tuple(mask for mask in masks if mask.enabled)
    if not enabled:
        return None
    result: str | None = None
    for mask in enabled:
        shape = _shape_expression(mask, variable)
        if result is None:
            result = shape if mask.operation != "subtract" else f"(1-({shape}))"
        elif mask.operation == "add":
            result = f"max(({result}),({shape}))"
        elif mask.operation == "subtract":
            result = f"({result})*(1-({shape}))"
        else:
            result = f"min(({result}),({shape}))"
    return f"clip(({result}),0,1)" if result is not None else None
