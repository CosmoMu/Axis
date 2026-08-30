"""Deterministic AXIS renderer for one confidence-qualified structural path."""

from __future__ import annotations

from io import BytesIO
from typing import Any


class PredictionChartError(RuntimeError):
    """The structured path is missing or cannot be rendered."""


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_prediction_chart(payload: dict[str, Any]) -> bytes:
    """Render only the structured current → key point → target path; never future candles."""

    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise PredictionChartError("PIL_UNAVAILABLE") from exc
    scenario = payload.get("top_scenario")
    raw_points = payload.get("prediction_path")
    if (
        not isinstance(scenario, dict)
        or scenario.get("direction_clear") is not True
        or not isinstance(raw_points, list)
    ):
        raise PredictionChartError("PREDICTION_PATH_NOT_CONFIDENT")
    points = []
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        if not isinstance(price, (int, float)) or isinstance(price, bool) or float(price) <= 0:
            continue
        points.append(
            {
                "type": str(item.get("type") or "STRUCTURE").upper(),
                "price": float(price),
                "label": str(item.get("label") or "结构位置")[:40],
            }
        )
    if len(points) < 2:
        raise PredictionChartError("PREDICTION_PATH_INCOMPLETE")

    invalidation = scenario.get("invalidation")
    if not isinstance(invalidation, (int, float)) or isinstance(invalidation, bool):
        invalidation = None
    values = [item["price"] for item in points]
    if invalidation is not None and float(invalidation) > 0:
        values.append(float(invalidation))
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.18, max(values) * 0.015)
    floor, ceiling = floor - padding, ceiling + padding

    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#040807")
    draw = ImageDraw.Draw(image)
    white, muted, green, grid = "#F4F6F2", "#7D8984", "#48D597", "#14201C"
    left, right, top, bottom = 120, 1480, 190, 750
    for index in range(6):
        y_pos = top + (bottom - top) * index / 5
        draw.line((left, y_pos, right, y_pos), fill=grid, width=1)

    def y(price: float) -> float:
        return bottom - (price - floor) / (ceiling - floor) * (bottom - top)

    ticker = ", ".join(str(item) for item in payload.get("symbols", [])[:2]) or "AXIS"
    weight = float(scenario.get("model_weight_percent") or 0)
    draw.text((left, 58), f"{ticker} · AXIS ANALYSIS", font=_font(42, bold=True), fill=white)
    draw.text(
        (left, 120),
        f"PRIMARY STRUCTURAL PATH · {weight:.0f}% MODEL WEIGHT",
        font=_font(23, bold=True),
        fill=green,
    )
    step = (right - left) / max(len(points) - 1, 1)
    coordinates = [(left + index * step, y(item["price"])) for index, item in enumerate(points)]
    draw.line(coordinates, fill=green, width=7, joint="curve")
    for index, ((x_pos, y_pos), point) in enumerate(zip(coordinates, points, strict=True)):
        is_current = point["type"] == "CURRENT" or index == 0
        color = white if is_current else green
        radius = 11 if is_current else 9
        draw.ellipse(
            (x_pos - radius, y_pos - radius, x_pos + radius, y_pos + radius),
            fill=color,
        )
        anchor = "la" if index == 0 else "ma" if index < len(points) - 1 else "ra"
        label_x = x_pos + 16 if index == 0 else x_pos if index < len(points) - 1 else x_pos - 16
        draw.text(
            (label_x, y_pos - 66),
            point["label"].upper(),
            font=_font(18, bold=True),
            fill=muted,
            anchor=anchor,
        )
        draw.text(
            (label_x, y_pos - 37),
            f"${point['price']:,.2f}",
            font=_font(25, bold=True),
            fill=color,
            anchor=anchor,
        )
    if invalidation is not None and float(invalidation) > 0:
        invalidation_y = y(float(invalidation))
        draw.line((left, invalidation_y, right, invalidation_y), fill=muted, width=3)
        draw.text(
            (right, invalidation_y - 13),
            f"INVALIDATION  ${float(invalidation):,.2f}",
            font=_font(18, bold=True),
            fill=muted,
            anchor="rs",
        )
    draw.text(
        (left, 830),
        "STRUCTURAL PATH · NO FUTURE CANDLESTICKS · MODEL WEIGHT IS NOT PROBABILITY",
        font=_font(17, bold=True),
        fill=muted,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
