"""Pure seek-safe evaluation and safe FFmpeg expressions."""

from __future__ import annotations

from core.timeline import ClipConfig, VisualAutomation


def _ease(kind: str, ratio: float) -> float:
    ratio = max(0.0, min(1.0, ratio))
    if kind == "hold":
        return 0.0
    if kind == "ease_in":
        return ratio * ratio
    if kind == "ease_out":
        return 1.0 - (1.0 - ratio) * (1.0 - ratio)
    if kind == "ease_in_out":
        return ratio * ratio * (3.0 - 2.0 * ratio)
    return ratio


def evaluate_curve(
    automation: VisualAutomation,
    offset_seconds: float,
    baseline: float,
) -> float:
    """Evaluate solely from clip-local time; call order never affects output."""

    if not automation.enabled:
        return baseline
    points = automation.keyframes
    if offset_seconds < points[0].offset_seconds or offset_seconds > points[-1].offset_seconds:
        return baseline
    if len(points) == 1:
        return points[0].value if abs(offset_seconds - points[0].offset_seconds) <= 1e-6 else baseline
    for left, right in zip(points, points[1:]):
        if offset_seconds <= right.offset_seconds + 1e-12:
            span = right.offset_seconds - left.offset_seconds
            ratio = (offset_seconds - left.offset_seconds) / span
            eased = _ease(left.interpolation, ratio)
            return left.value + eased * (right.value - left.value)
    return baseline


def static_visual_value(clip: ClipConfig, property_path: str) -> float:
    group, field = property_path.split(".", 1)
    if property_path == "transform.scale_uniform":
        return (clip.transform.scale_x + clip.transform.scale_y) / 2.0
    return float(getattr(getattr(clip, group), field))


def evaluated_visual_values(clip: ClipConfig, offset_seconds: float) -> dict[str, float]:
    return {
        item.property_path: evaluate_curve(
            item,
            offset_seconds,
            static_visual_value(clip, item.property_path),
        )
        for item in clip.visual_automations
        if item.enabled
    }


def _number(value: float) -> str:
    return f"{value:.12g}"


def _curve_expression(
    automation: VisualAutomation,
    baseline: float,
    variable: str,
) -> str:
    points = automation.keyframes
    baseline_s = _number(baseline)
    if len(points) == 1:
        point = points[0]
        return (
            f"if(lte(abs({variable}-{_number(point.offset_seconds)}),0.000001),"
            f"{_number(point.value)},{baseline_s})"
        )
    expression = baseline_s
    for left, right in reversed(tuple(zip(points, points[1:]))):
        start = _number(left.offset_seconds)
        end = _number(right.offset_seconds)
        ratio = f"(({variable}-{start})/({end}-{start}))"
        if left.interpolation == "hold":
            eased = "0"
        elif left.interpolation == "ease_in":
            eased = f"({ratio})*({ratio})"
        elif left.interpolation == "ease_out":
            eased = f"1-(1-({ratio}))*(1-({ratio}))"
        elif left.interpolation == "ease_in_out":
            eased = f"({ratio})*({ratio})*(3-2*({ratio}))"
        else:
            eased = ratio
        value = (
            f"{_number(left.value)}+({eased})*"
            f"({_number(right.value)}-{_number(left.value)})"
        )
        expression = (
            f"if(between({variable},{start},{end}),({value}),({expression}))"
        )
    return expression


def ffmpeg_property_expressions(
    clip: ClipConfig,
    *,
    variable: str = "t",
) -> dict[str, str]:
    return {
        item.property_path: _curve_expression(
            item,
            static_visual_value(clip, item.property_path),
            variable,
        )
        for item in clip.visual_automations
        if item.enabled
    }
