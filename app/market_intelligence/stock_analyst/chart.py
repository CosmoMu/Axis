"""Unified black/green visual renderer for AXIS Stock Analyst."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from app.market_intelligence.stock_analyst.indicators import ema_series
from app.market_intelligence.stock_analyst.models import DailyBar, StockAnalysis


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def resolve_projection_path(
    analysis: StockAnalysis,
    projection_points: tuple[dict[str, Any], ...] | None,
) -> tuple[list[float], list[str | None], str] | None:
    if not projection_points:
        primary = max(
            analysis.scenarios,
            key=lambda item: item.model_weight_percent,
            default=None,
        )
        if primary is None or not primary.targets:
            return None
        destination = primary.targets[0]
        pullback = analysis.current_price + (destination - analysis.current_price) * -0.18
        return (
            [analysis.current_price, pullback, *primary.targets],
            [None] * (len(primary.targets) + 2),
            f"AXIS MODEL PATH · {primary.model_weight_percent:.0f}% WEIGHT",
        )
    current = analysis.current_price
    levels = sorted(
        set(
            [level.price for level in analysis.support_levels]
            + [level.price for level in analysis.resistance_levels]
            + [value for scenario in analysis.scenarios for value in scenario.targets]
        )
    )
    prices = [current]
    labels: list[str | None] = [None]
    exact = mapped = False
    for item in projection_points[:12]:
        direction = str(item.get("direction") or "FLAT").upper()
        raw_price = item.get("price")
        label = str(item.get("label"))[:40] if item.get("label") else None
        if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool):
            price = float(raw_price)
            exact = True
        elif direction == "UP":
            price = next((value for value in levels if value > prices[-1]), prices[-1] * 1.04)
            mapped = True
        elif direction == "DOWN":
            price = next(
                (value for value in reversed(levels) if value < prices[-1]),
                prices[-1] * 0.96,
            )
            mapped = True
        elif direction in {"START", "FLAT"}:
            price = current if direction == "START" else prices[-1]
            mapped = True
        else:
            continue
        if direction == "START" and abs(price - prices[-1]) < 1e-9 and not label:
            continue
        prices.append(price)
        labels.append(label)
    if len(prices) < 2:
        return None
    title = (
        "INPUT PATH · SOURCE + AXIS LEVELS"
        if exact and mapped
        else "INPUT PATH · EXPLICIT LEVELS"
        if exact
        else "INPUT PATH · AXIS-MAPPED LEVELS"
    )
    return prices, labels, title


def render_stock_analysis_chart(
    analysis: StockAnalysis,
    daily_bars: tuple[DailyBar, ...],
    *,
    projection_points: tuple[dict[str, Any], ...] | None = None,
) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required for AXIS Stock Analyst rendering") from exc
    bars = tuple(sorted(daily_bars, key=lambda item: item.timestamp))[-82:]
    if len(bars) < 50:
        raise ValueError("AXIS Stock Analyst chart requires at least 50 daily bars")
    width, height = 1900, 1160
    image = Image.new("RGB", (width, height), "#05090D")
    draw = ImageDraw.Draw(image)
    white, muted, panel = "#F4F8F7", "#81918C", "#091117"
    green, red, cyan, gold = "#25DFA0", "#F14251", "#55D8FF", "#F4C95D"
    for x_pos in range(0, width, 100):
        draw.line((x_pos, 0, x_pos, height), fill="#081117", width=1)
    for y_pos in range(0, height, 100):
        draw.line((0, y_pos, width, y_pos), fill="#081117", width=1)
    draw.text((50, 32), f"{analysis.ticker} · AXIS STOCK ANALYST", font=_font(42, True), fill=white)
    trend = (
        "BULLISH"
        if analysis.trend_score >= 60
        else "BEARISH"
        if analysis.trend_score <= 40
        else "BALANCED"
    )
    price_header = f"${analysis.current_price:,.2f} · {trend} {analysis.trend_score:.0f}/100"
    draw.text(
        (50, 89),
        price_header,
        font=_font(25, True),
        fill=green if analysis.trend_score >= 55 else red if analysis.trend_score <= 45 else gold,
    )
    draw.text(
        (1845, 43),
        f"AS OF {analysis.as_of.isoformat()}",
        font=_font(22, True),
        fill=muted,
        anchor="ra",
    )
    draw.text(
        (1845, 84),
        (
            f"LIMITED HISTORY · {analysis.history_sessions} SESSIONS"
            if analysis.history_mode == "LIMITED"
            else "VOLUME PROFILE / FLOW = OHLCV PROXY"
        ),
        font=_font(18, True),
        fill=gold,
        anchor="ra",
    )
    chart_left, history_right = 75, 1090
    projection_left, chart_right = 1120, 1370
    profile_left, profile_right = 1435, 1835
    chart_top, chart_bottom = 175, 1060
    draw.rounded_rectangle((35, 145, 1865, 1100), radius=18, fill=panel, outline="#20332E", width=2)
    projection = resolve_projection_path(analysis, projection_points)
    values = [bar.low for bar in bars] + [bar.high for bar in bars]
    values.extend(level.price for level in analysis.support_levels)
    values.extend(level.price for level in analysis.resistance_levels)
    if projection is not None:
        values.extend(projection[0])
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.06, analysis.current_price * 0.005)
    floor -= padding
    ceiling += padding

    def y(price: float) -> float:
        return chart_bottom - (price - floor) / (ceiling - floor) * (chart_bottom - chart_top)

    for index in range(7):
        level = floor + (ceiling - floor) * index / 6
        y_pos = y(level)
        draw.line((chart_left, y_pos, profile_right, y_pos), fill="#16221E", width=1)
        draw.text(
            (profile_right + 8, y_pos),
            f"{level:,.2f}",
            font=_font(16, True),
            fill=muted,
            anchor="lm",
        )
    step = (history_right - chart_left) / len(bars)
    candle_width = max(4, int(step * 0.58))
    for index, bar in enumerate(bars):
        x_pos = chart_left + step * (index + 0.5)
        color = green if bar.close >= bar.open else red
        draw.line((x_pos, y(bar.high), x_pos, y(bar.low)), fill=color, width=2)
        upper, lower = sorted((y(bar.open), y(bar.close)))
        lower = max(lower, upper + 2)
        draw.rectangle(
            (x_pos - candle_width / 2, upper, x_pos + candle_width / 2, lower), fill=color
        )
    closes = tuple(bar.close for bar in bars)
    for period, color in ((20, cyan), (50, gold)):
        series = ema_series(closes, period)
        points = [
            (chart_left + step * (index + period - 0.5), y(value))
            for index, value in enumerate(series)
        ]
        if len(points) >= 2:
            draw.line(points, fill=color, width=3, joint="curve")
    for level, label, color in (
        *((item.price, "SUPPORT", green) for item in analysis.support_levels[:3]),
        *((item.price, "RESISTANCE", red) for item in analysis.resistance_levels[:3]),
    ):
        y_pos = y(level)
        draw.line((chart_left, y_pos, chart_right, y_pos), fill=color, width=2)
        draw.text(
            (chart_right - 4, y_pos - 13),
            f"{label} {level:,.2f}",
            font=_font(12, True),
            fill=color,
            anchor="ra",
        )
    draw.line(
        (chart_left, y(analysis.current_price), profile_right, y(analysis.current_price)),
        fill=white,
        width=2,
    )
    draw.text(
        (profile_right - 4, y(analysis.current_price) - 18),
        f"SPOT {analysis.current_price:,.2f}",
        font=_font(16, True),
        fill=white,
        anchor="ra",
    )
    if projection is not None:
        path_prices, labels, title = projection
        points = [
            (
                projection_left + index * (chart_right - projection_left) / (len(path_prices) - 1),
                y(price),
            )
            for index, price in enumerate(path_prices)
        ]
        draw.line(points, fill=white, width=4, joint="curve")
        for index, ((x_pos, y_pos), price, label) in enumerate(
            zip(points, path_prices, labels, strict=True)
        ):
            draw.ellipse((x_pos - 5, y_pos - 5, x_pos + 5, y_pos + 5), fill=white)
            if index:
                text = f"{label + ' · ' if label else f'P{index} · '}${price:,.2f}"
                draw.text(
                    (x_pos, y_pos - 17 if index % 2 else y_pos + 17),
                    text,
                    font=_font(12, True),
                    fill=white,
                    anchor="mb" if index % 2 else "mt",
                )
        draw.text((projection_left, chart_top + 14), title, font=_font(15, True), fill=white)
        draw.text(
            (projection_left, chart_top + 39),
            "INPUT ROUTE" if projection_points else "AXIS DAILY STRUCTURE",
            font=_font(13, True),
            fill=muted,
        )
    draw.line(
        (profile_left - 28, chart_top, profile_left - 28, chart_bottom), fill="#31423C", width=2
    )
    draw.text((profile_left, 164), "OHLCV CHIP PEAKS", font=_font(21, True), fill=white)
    max_volume = max((node.volume for node in analysis.volume_profile_nodes), default=1.0)
    for node in analysis.volume_profile_nodes:
        if node.price_high < floor or node.price_low > ceiling:
            continue
        y0, y1 = sorted((y(node.price_high), y(node.price_low)))
        bar_width = (profile_right - profile_left) * node.volume / max_volume
        color = (
            gold if node.rank == 1 else green if node.midpoint <= analysis.current_price else cyan
        )
        draw.rectangle((profile_left, y0 + 1, profile_left + bar_width, y1 - 1), fill=color)
        if node.rank <= 5:
            draw.text(
                (profile_left + bar_width + 5, (y0 + y1) / 2),
                f"{node.volume_share:.1%}",
                font=_font(14, True),
                fill=white,
                anchor="lm",
            )
    draw.text(
        (50, 1114),
        (
            "EMA20 · EMA50 · LIMITED HISTORY · LOWER CONVICTION · WEIGHT IS NOT PROBABILITY"
            if analysis.history_mode == "LIMITED"
            else "EMA20 · EMA50 · CONFIRMED PIVOTS · AXIS SCENARIO WEIGHT IS NOT PROBABILITY"
        ),
        font=_font(15, True),
        fill=muted,
        anchor="lm",
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
