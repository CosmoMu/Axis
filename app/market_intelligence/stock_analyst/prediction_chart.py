"""Deterministic AXIS daily-candle and structural-path renderer."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from io import BytesIO
from typing import Any

from app.market_intelligence.stock_analyst.models import DailyBar


class PredictionChartError(RuntimeError):
    """The real daily history or structured path is missing and cannot be rendered."""


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


def _finite_price(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    ):
        return float(value)
    return None


def _coerce_daily_bars(raw_bars: Iterable[DailyBar | dict[str, Any]] | None) -> list[DailyBar]:
    bars: list[DailyBar] = []
    for item in raw_bars or ():
        if isinstance(item, DailyBar):
            bars.append(item)
            continue
        if not isinstance(item, dict):
            continue
        raw_timestamp = item.get("timestamp")
        try:
            timestamp = (
                raw_timestamp
                if isinstance(raw_timestamp, datetime)
                else datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
            )
            bars.append(
                DailyBar(
                    timestamp=timestamp,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume") or 0),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    ordered = sorted(bars, key=lambda item: item.timestamp)
    deduplicated = {item.timestamp: item for item in ordered}
    selected = list(deduplicated.values())[-72:]
    if len(selected) < 30:
        raise PredictionChartError("DAILY_K_BARS_REQUIRED")
    return selected


def _ema(values: list[float], period: int) -> list[float | None]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    current = values[0]
    output: list[float | None] = []
    for index, value in enumerate(values):
        current = value if index == 0 else alpha * value + (1 - alpha) * current
        output.append(current if index >= period - 1 else None)
    return output


def _path_points(
    payload: dict[str, Any],
    *,
    last_close: float,
    recent_span: float,
) -> tuple[list[dict[str, Any]], bool]:
    scenario = payload.get("top_scenario")
    raw_points = payload.get("prediction_path")
    if (
        not isinstance(scenario, dict)
        or scenario.get("direction_clear") is not True
        or not isinstance(raw_points, list)
    ):
        raise PredictionChartError("PREDICTION_PATH_NOT_CONFIDENT")

    source_derived = payload.get("chart_path_basis") == "SOURCE_PROJECTION"
    points: list[dict[str, Any]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        price = _finite_price(item.get("price"))
        direction = str(item.get("direction") or "").upper()
        if price is None and (not source_derived or direction not in {"UP", "DOWN", "FLAT"}):
            continue
        points.append(
            {
                "type": str(item.get("type") or "STRUCTURE").upper(),
                "price": price,
                "direction": direction,
                "label": str(item.get("label") or "结构位置")[:36],
            }
        )

    if not points:
        raise PredictionChartError("PREDICTION_PATH_INCOMPLETE")
    first_price = points[0]["price"]
    if points[0]["type"] != "CURRENT" and (
        first_price is None or abs(first_price - last_close) / last_close > 0.002
    ):
        points.insert(
            0,
            {
                "type": "CURRENT",
                "price": last_close,
                "direction": "START",
                "label": "当前",
            },
        )
    elif points[0]["type"] == "CURRENT":
        points[0]["price"] = last_close

    direction_step = max(recent_span * 0.22, last_close * 0.015)
    resolved: list[dict[str, Any]] = []
    for item in points:
        plot_price = item["price"]
        if plot_price is None:
            previous = resolved[-1]["plot_price"] if resolved else last_close
            plot_price = (
                previous + direction_step
                if item["direction"] == "UP"
                else max(previous - direction_step, 0.01)
                if item["direction"] == "DOWN"
                else previous
            )
        resolved.append({**item, "plot_price": plot_price})
    if len(resolved) < 2:
        raise PredictionChartError("PREDICTION_PATH_INCOMPLETE")
    return resolved[:8], source_derived


def _key_levels(payload: dict[str, Any], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    role_rank = {
        "INVALIDATION": 0,
        "SUPPORT": 1,
        "KEY_ZONE": 2,
        "PIVOT": 3,
        "BREAKOUT": 4,
        "RESISTANCE": 5,
        "TARGET": 6,
        "WATCH": 7,
    }
    candidates: list[dict[str, Any]] = []
    for item in payload.get("key_levels", []):
        if not isinstance(item, dict):
            continue
        price = _finite_price(item.get("price"))
        price_high = _finite_price(item.get("price_high"))
        if price is None and price_high is None:
            continue
        role = str(item.get("role") or item.get("level_type") or "WATCH").upper()
        candidates.append(
            {
                "price": price or price_high,
                "price_high": price_high,
                "role": role,
                "label": str(item.get("description") or "")[:28],
                "rank": role_rank.get(role, 8),
            }
        )
    scenario = payload.get("top_scenario")
    if isinstance(scenario, dict):
        invalidation = _finite_price(scenario.get("invalidation"))
        if invalidation is not None:
            candidates.append(
                {
                    "price": invalidation,
                    "price_high": None,
                    "role": "INVALIDATION",
                    "label": "",
                    "rank": 0,
                }
            )
    for point in points[1:]:
        if point["price"] is None:
            continue
        if point["type"] not in {"TARGET", "BREAKOUT"}:
            continue
        role = point["type"]
        candidates.append(
            {
                "price": point["price"],
                "price_high": None,
                "role": role,
                "label": point["label"],
                "rank": role_rank[role],
            }
        )

    unique: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda value: (value["rank"], value["price"])):
        existing = next(
            (
                value
                for value in unique
                if abs(value["price"] - item["price"]) / item["price"] < 0.001
            ),
            None,
        )
        if existing is None:
            unique.append(item)
        elif item["rank"] < existing["rank"]:
            existing.update(item)
    return unique[:8]


def _ema_channel(values: list[float], period: int) -> list[float]:
    """Cosmos Pilot HLX-compatible full EMA channel, copied into AXIS ownership."""

    if not values:
        return []
    alpha = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(value * alpha + output[-1] * (1 - alpha))
    return output


def _hlx_ladder_channels(bars: list[DailyBar]) -> tuple[list[float], ...]:
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    return (
        _ema_channel(highs, 25),
        _ema_channel(lows, 25),
        _ema_channel(highs, 90),
        _ema_channel(lows, 90),
    )


def _pilot_route(
    points: list[dict[str, Any]],
    levels: list[dict[str, Any]],
    *,
    stance: str,
    source_derived: bool,
) -> list[tuple[float, str | None]]:
    """Build the Pilot-style pullback/confirm/target shape without inventing key levels."""

    current = float(points[0]["plot_price"])
    if source_derived:
        return [
            (float(item["plot_price"]), str(item.get("label") or "") or None)
            for item in points
        ]

    bullish = stance != "BEARISH"
    candidates: list[tuple[float, str | None]] = [(current, "当前")]
    zones = [item for item in levels if item["role"] in {"KEY_ZONE", "SUPPORT", "RESISTANCE"}]
    directional_zones = [
        item
        for item in zones
        if (bullish and float(item["price"]) <= current)
        or (not bullish and float(item["price"]) >= current)
    ]
    if directional_zones:
        zone = min(directional_zones, key=lambda item: abs(float(item["price"]) - current))
        high = float(zone.get("price_high") or zone["price"])
        candidates.append(((float(zone["price"]) + high) / 2, "关注区"))

    for item in points[1:]:
        price = float(item["plot_price"])
        if all(abs(price - existing[0]) / price >= 0.0005 for existing in candidates):
            candidates.append((price, str(item.get("label") or "结构位置")))

    if len(candidates) >= 4:
        # The Pilot entry chart uses one restrained retracement after the first
        # objective. It is a route shape between Mentor levels, not a new level.
        first_objective = 2 if len(directional_zones) else 1
        if first_objective + 1 < len(candidates):
            before = candidates[first_objective - 1][0]
            peak = candidates[first_objective][0]
            retrace = before + (peak - before) * 0.55
            candidates.insert(first_objective + 1, (retrace, None))
    return candidates[:7]


def render_prediction_chart(
    payload: dict[str, Any],
    daily_bars: Iterable[DailyBar | dict[str, Any]] | None = None,
) -> bytes:
    """Render real daily candles with Mentor-first levels and one Pilot-style route."""

    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise PredictionChartError("PIL_UNAVAILABLE") from exc

    bars = _coerce_daily_bars(daily_bars)
    lows = [item.low for item in bars]
    highs = [item.high for item in bars]
    recent_span = max(highs[-20:]) - min(lows[-20:])
    points, source_derived = _path_points(
        payload,
        last_close=bars[-1].close,
        recent_span=recent_span,
    )
    levels = _key_levels(payload, points)
    history_floor, history_ceiling = min(lows), max(highs)
    history_span = history_ceiling - history_floor
    relevant_floor = max(0.01, history_floor - history_span * 0.5)
    relevant_ceiling = history_ceiling + history_span * 0.75
    levels = [
        item for item in levels if relevant_floor <= item["price"] <= relevant_ceiling
    ]

    route = _pilot_route(
        points,
        levels,
        stance=str(payload.get("stance") or "WATCH").upper(),
        source_derived=source_derived,
    )
    values = [*lows, *highs]
    values.extend(price for price, _ in route)
    values.extend(item["price"] for item in levels)
    values.extend(item["price_high"] for item in levels if item.get("price_high") is not None)
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.075, bars[-1].close * 0.006)
    floor, ceiling = floor - padding, ceiling + padding
    if ceiling <= floor:
        raise PredictionChartError("DAILY_K_RANGE_INVALID")

    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#05070A")
    draw = ImageDraw.Draw(image)
    white, muted, green = "#F3F4F2", "#68716E", "#42CB8A"
    red, grid, cyan, gold, blue = "#E64A68", "#17201E", "#00AEEB", "#E3BE4D", "#3F73E6"
    left, history_right, forecast_left, right = 58, 1080, 1110, 1518
    top, bottom = 48, 824

    for index in range(6):
        y_pos = top + (bottom - top) * index / 5
        draw.line((left, y_pos, right, y_pos), fill=grid, width=1)
        price = ceiling - (ceiling - floor) * index / 5
        draw.text(
            (right + 8, y_pos),
            f"{price:,.2f}",
            font=_font(13, bold=True),
            fill=muted,
            anchor="lm",
        )

    def y(price: float) -> float:
        return bottom - (price - floor) / (ceiling - floor) * (bottom - top)

    candle_step = (history_right - left) / len(bars)
    candle_width = max(5, int(candle_step * 0.58))
    for index, bar in enumerate(bars):
        x_pos = left + candle_step * (index + 0.5)
        color = white if bar.close >= bar.open else red
        draw.line((x_pos, y(bar.high), x_pos, y(bar.low)), fill=color, width=2)
        upper, lower = sorted((y(bar.open), y(bar.close)))
        lower = max(lower, upper + 2)
        draw.rectangle(
            (x_pos - candle_width / 2, upper, x_pos + candle_width / 2, lower),
            fill=color,
        )

    for channel, color in zip(_hlx_ladder_channels(bars), (cyan, cyan, gold, gold), strict=True):
        channel_points = [
            (left + candle_step * (index + 0.5), y(value))
            for index, value in enumerate(channel)
        ]
        draw.line(channel_points, fill=color, width=3, joint="curve")

    current_y = y(bars[-1].close)
    draw.line((left, current_y, right, current_y), fill=blue, width=2)
    draw.text(
        (right - 8, current_y - 9),
        f"起点  {bars[-1].close:,.2f}",
        font=_font(14, bold=True),
        fill="#6F9CF4",
        anchor="rb",
    )

    zones = [
        item
        for item in levels
        if item["role"] == "KEY_ZONE"
        or (
            item.get("price_high") is not None
            and item["role"] in {"SUPPORT", "RESISTANCE"}
        )
    ]
    for zone in zones[:1]:
        low, high = sorted((float(zone["price"]), float(zone.get("price_high") or zone["price"])))
        zone_top, zone_bottom = sorted((y(high), y(low)))
        if zone_bottom - zone_top < 8:
            zone_top -= 4
            zone_bottom += 4
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(
            (left, zone_top, right, zone_bottom),
            fill=(139, 104, 21, 55),
            outline=(139, 104, 21, 220),
        )
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(image)
        draw.text(
            (right - 8, (zone_top + zone_bottom) / 2),
            f"关注区  {low:,.2f}–{high:,.2f}" if high != low else f"关注区  {low:,.2f}",
            font=_font(13, bold=True),
            fill=gold,
            anchor="rm",
        )

    target_candidates = [
        item for item in levels if item["role"] in {"BREAKOUT", "RESISTANCE", "TARGET"}
    ]
    bullish = str(payload.get("stance") or "WATCH").upper() != "BEARISH"
    target_candidates.sort(key=lambda item: float(item["price"]), reverse=not bullish)
    target_index = 0
    for level in target_candidates[:4]:
        level_y = y(float(level["price"]))
        color = "#236B49" if level["role"] != "TARGET" else "#238A54"
        if level["role"] == "BREAKOUT":
            label = "突破"
        else:
            target_index += 1
            label = f"目标{target_index}"
        draw.line((left, level_y, right, level_y), fill=color, width=2)
        high = float(level.get("price_high") or level["price"])
        price_label = (
            f"{float(level['price']):,.2f}–{high:,.2f}"
            if abs(high - float(level["price"])) > 1e-9
            else f"{float(level['price']):,.2f}"
        )
        draw.text(
            (right - 8, level_y - 8),
            f"{label}  {price_label}",
            font=_font(13, bold=True),
            fill=green,
            anchor="rb",
        )

    invalidation = next((item for item in levels if item["role"] == "INVALIDATION"), None)
    if invalidation is not None:
        invalidation_y = y(float(invalidation["price"]))
        draw.line((left, invalidation_y, right, invalidation_y), fill="#A93244", width=2)
        draw.text(
            (right - 8, invalidation_y - 8),
            f"失效  {float(invalidation['price']):,.2f}",
            font=_font(13, bold=True),
            fill="#D46A78",
            anchor="rb",
        )

    for level in (
        item
        for item in levels
        if item["role"] in {"SUPPORT", "PIVOT", "WATCH"}
        and item.get("price_high") is None
    ):
        level_y = y(float(level["price"]))
        draw.line((left, level_y, right, level_y), fill="#315149", width=1)
        draw.text(
            (right - 8, level_y + 8),
            f"支撑  {float(level['price']):,.2f}",
            font=_font(12, bold=True),
            fill="#6E9C8D",
            anchor="rt",
        )

    path_coordinates = [
        (
            forecast_left + index * (right - forecast_left) / max(len(route) - 1, 1),
            y(price),
        )
        for index, (price, _) in enumerate(route)
    ]
    draw.line(path_coordinates, fill=white, width=4, joint="curve")
    for x_pos, y_pos in path_coordinates:
        draw.ellipse((x_pos - 5, y_pos - 5, x_pos + 5, y_pos + 5), fill=white)
    draw.line(
        (history_right, current_y, forecast_left, path_coordinates[0][1]),
        fill=white,
        width=2,
    )
    draw.text(
        (forecast_left, top + 10),
        "预测路径",
        font=_font(14, bold=True),
        fill=muted,
    )

    date_indexes = sorted({0, len(bars) // 3, len(bars) * 2 // 3, len(bars) - 1})
    for index in date_indexes:
        x_pos = left + candle_step * (index + 0.5)
        draw.text(
            (x_pos, bottom + 17),
            bars[index].timestamp.strftime("%m/%d"),
            font=_font(14, bold=True),
            fill=muted,
            anchor="ma",
        )

    market_as_of = str(payload.get("market_as_of") or bars[-1].timestamp.date().isoformat())[:10]
    basis = "导师路径重绘" if source_derived else "导师点位 · AXIS 路径"
    draw.text(
        (left, 872),
        f"{basis} · 真实日 K 截至 {market_as_of} · 右侧为结构路径，不是未来 K 线",
        font=_font(14, bold=True),
        fill=muted,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
