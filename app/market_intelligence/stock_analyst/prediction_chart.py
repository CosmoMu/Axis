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
        if price is None:
            continue
        role = str(item.get("role") or item.get("level_type") or "WATCH").upper()
        candidates.append(
            {
                "price": price,
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
                {"price": invalidation, "role": "INVALIDATION", "label": "", "rank": 0}
            )
    for point in points[1:]:
        if point["price"] is None:
            continue
        role = "TARGET" if point["type"] == "TARGET" else "BREAKOUT"
        candidates.append(
            {
                "price": point["price"],
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


def render_prediction_chart(
    payload: dict[str, Any],
    daily_bars: Iterable[DailyBar | dict[str, Any]] | None = None,
) -> bytes:
    """Render real daily candles plus one deterministic structural forecast path.

    Historical candles always come from provider OHLC. The forecast area contains a line only;
    it never fabricates future candles.
    """

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

    values = [*lows, *highs]
    values.extend(item["plot_price"] for item in points)
    values.extend(item["price"] for item in levels)
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.075, bars[-1].close * 0.006)
    floor, ceiling = floor - padding, ceiling + padding
    if ceiling <= floor:
        raise PredictionChartError("DAILY_K_RANGE_INVALID")

    width, height = 1600, 900
    image = Image.new("RGB", (width, height), "#040807")
    draw = ImageDraw.Draw(image)
    white, muted, secondary, green = "#F4F6F2", "#7D8984", "#A2AEA9", "#48D597"
    red, grid, panel = "#C86A72", "#15201C", "#07100D"
    left, history_right, forecast_left, right = 92, 1120, 1155, 1490
    top, bottom = 168, 758

    draw.rounded_rectangle((58, 138, 1534, 797), radius=18, fill=panel, outline="#1B2B25", width=2)
    draw.rectangle((forecast_left, top, right, bottom), fill="#091511")
    for index in range(6):
        y_pos = top + (bottom - top) * index / 5
        draw.line((left, y_pos, right, y_pos), fill=grid, width=1)
        price = ceiling - (ceiling - floor) * index / 5
        draw.text(
            (right - 6, y_pos + 7),
            f"{price:,.2f}",
            font=_font(15, bold=True),
            fill=muted,
            anchor="ra",
        )

    def y(price: float) -> float:
        return bottom - (price - floor) / (ceiling - floor) * (bottom - top)

    ticker = ", ".join(str(item) for item in payload.get("symbols", [])[:2]) or "AXIS"
    market_as_of = str(payload.get("market_as_of") or bars[-1].timestamp.date().isoformat())[:10]
    draw.text((74, 43), f"{ticker} · 日 K 结构预测", font=_font(38, bold=True), fill=white)
    draw.text(
        (74, 98),
        f"1D · 截至 {market_as_of} · 历史蜡烛为真实行情",
        font=_font(20, bold=True),
        fill=secondary,
    )
    draw.text(
        (1515, 55),
        "AXIS ANALYSIS",
        font=_font(22, bold=True),
        fill=green,
        anchor="ra",
    )
    draw.text((left, 151), "历史日 K", font=_font(16, bold=True), fill=muted, anchor="ls")
    draw.text(
        (forecast_left + 14, 151),
        "预测走势",
        font=_font(16, bold=True),
        fill=green,
        anchor="ls",
    )

    candle_step = (history_right - left) / len(bars)
    candle_width = max(5, int(candle_step * 0.58))
    for index, bar in enumerate(bars):
        x_pos = left + candle_step * (index + 0.5)
        color = green if bar.close >= bar.open else red
        draw.line((x_pos, y(bar.high), x_pos, y(bar.low)), fill=color, width=2)
        upper, lower = sorted((y(bar.open), y(bar.close)))
        lower = max(lower, upper + 2)
        draw.rectangle(
            (x_pos - candle_width / 2, upper, x_pos + candle_width / 2, lower),
            fill=color,
        )

    closes = [item.close for item in bars]
    ema20 = _ema(closes, 20)
    ema_points = [
        (left + candle_step * (index + 0.5), y(value))
        for index, value in enumerate(ema20)
        if value is not None
    ]
    if len(ema_points) > 1:
        draw.line(ema_points, fill="#D8C67E", width=2, joint="curve")
        draw.text(
            (history_right - 8, top + 17),
            "EMA20",
            font=_font(13, bold=True),
            fill="#D8C67E",
            anchor="ra",
        )

    role_names = {
        "INVALIDATION": "失效",
        "SUPPORT": "支撑",
        "KEY_ZONE": "关键区",
        "PIVOT": "枢轴",
        "BREAKOUT": "突破",
        "RESISTANCE": "压力",
        "TARGET": "目标",
        "WATCH": "关注",
    }
    role_colors = {
        "INVALIDATION": "#A8656C",
        "SUPPORT": "#6F8D84",
        "KEY_ZONE": "#7F948C",
        "PIVOT": "#8A948F",
        "BREAKOUT": "#7CAF99",
        "RESISTANCE": "#A99A73",
        "TARGET": "#48D597",
        "WATCH": "#7D8984",
    }
    label_positions: list[float] = []
    for level in sorted(levels, key=lambda item: item["price"], reverse=True):
        actual_y = y(level["price"])
        color = role_colors.get(level["role"], muted)
        draw.line((left, actual_y, right, actual_y), fill=color, width=2)
        label_y = actual_y
        while any(abs(label_y - occupied) < 27 for occupied in label_positions):
            label_y += 28
        label_y = min(max(label_y, top + 14), bottom - 14)
        label_positions.append(label_y)
        if abs(label_y - actual_y) > 2:
            draw.line((right - 182, actual_y, right - 145, label_y), fill=color, width=1)
        role = role_names.get(level["role"], "关键位")
        label = f"{role}  {level['price']:,.2f}"
        draw.rounded_rectangle(
            (right - 142, label_y - 14, right - 7, label_y + 14),
            radius=7,
            fill="#0B1713",
            outline=color,
            width=1,
        )
        draw.text((right - 14, label_y), label, font=_font(14, bold=True), fill=color, anchor="rm")

    draw.line(
        (forecast_left - 18, top, forecast_left - 18, bottom),
        fill="#365047",
        width=2,
    )
    forecast_width = right - forecast_left - 160
    path_coordinates = [
        (
            forecast_left + index * forecast_width / max(len(points) - 1, 1),
            y(item["plot_price"]),
        )
        for index, item in enumerate(points)
    ]
    draw.line(path_coordinates, fill=green, width=6, joint="curve")
    for index, ((x_pos, y_pos), point) in enumerate(zip(path_coordinates, points, strict=True)):
        is_current = index == 0 or point["type"] == "CURRENT"
        color = white if is_current else green
        radius = 8 if is_current else 7
        draw.ellipse((x_pos - radius, y_pos - radius, x_pos + radius, y_pos + radius), fill=color)
        if index == 0:
            continue
        price_text = f"{point['price']:,.2f}" if point["price"] is not None else "方向"
        label_y = y_pos - 31 if index % 2 else y_pos + 30
        draw.text(
            (x_pos, label_y),
            f"{point['label']} · {price_text}",
            font=_font(14, bold=True),
            fill=white,
            anchor="mb" if index % 2 else "mt",
        )

    last_candle_y = y(bars[-1].close)
    draw.line(
        (history_right - 15, last_candle_y, forecast_left, path_coordinates[0][1]),
        fill=white,
        width=2,
    )
    draw.text(
        (forecast_left + 4, path_coordinates[0][1] - 16),
        f"当前 {bars[-1].close:,.2f}",
        font=_font(14, bold=True),
        fill=white,
        anchor="ls",
    )

    date_indexes = sorted({0, len(bars) // 3, len(bars) * 2 // 3, len(bars) - 1})
    for index in date_indexes:
        x_pos = left + candle_step * (index + 0.5)
        draw.text(
            (x_pos, bottom + 19),
            bars[index].timestamp.strftime("%m/%d"),
            font=_font(14, bold=True),
            fill=muted,
            anchor="ma",
        )

    basis = "输入点位重绘" if source_derived else "融合结构路径"
    draw.text(
        (74, 840),
        f"{basis} · 关键点位为水平线 · 右侧仅为预测路径，不代表未来真实 K 线",
        font=_font(17, bold=True),
        fill=secondary,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
