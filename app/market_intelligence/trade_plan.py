"""Deterministic SWING / LEAPS entry-plan enrichment and rendering."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from decimal import Decimal
from io import BytesIO
from typing import Protocol

from app.domain.public_cards import PublicTradeCard
from app.market_intelligence.stock_analyst.engine import analyze_stock
from app.market_intelligence.stock_analyst.indicators import ema_series
from app.market_intelligence.stock_analyst.market_data import StockMarketDataError
from app.market_intelligence.stock_analyst.models import DailyBar, StockAnalysis, StockMarketBundle


class TradePlanMarketData(Protocol):
    async def fetch(self, ticker: str) -> StockMarketBundle: ...


@dataclass(frozen=True, slots=True)
class TradePlanArtifact:
    card: PublicTradeCard
    chart_png: bytes | None
    provenance: dict[str, str]


class SwingLeapsTradePlanService:
    """Fill only absent Mentor plan points, then render one stable real-data chart."""

    def __init__(self, provider: TradePlanMarketData | None) -> None:
        self.provider = provider

    async def prepare(self, card: PublicTradeCard) -> TradePlanArtifact:
        mentor_provenance = _mentor_provenance(card)
        if (
            self.provider is None
            or card.category not in {"SWING", "LEAPS"}
            or card.action != "ENTRY"
            or not card.ticker
        ):
            return TradePlanArtifact(card, None, mentor_provenance)
        try:
            bundle = await self.provider.fetch(card.ticker)
            analysis = await asyncio.to_thread(
                analyze_stock,
                bundle.ticker,
                bundle.bars,
                sector_etf=bundle.sector_etf,
                sector_bars=bundle.sector_bars,
                benchmark_bars=bundle.benchmark_bars,
            )
            enriched, provenance = resolve_entry_plan(card, analysis, bundle.bars)
            chart = await asyncio.to_thread(
                render_swing_leaps_entry_chart,
                enriched,
                bundle.bars,
            )
            return TradePlanArtifact(enriched, chart, provenance)
        except (StockMarketDataError, ValueError, OSError, RuntimeError):
            return TradePlanArtifact(card, None, mentor_provenance)


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))


def _money(value: float | Decimal) -> str:
    return "$" + f"{float(value):,.2f}"


def _mentor_provenance(card: PublicTradeCard) -> dict[str, str]:
    fields = {
        "current_stock": card.current_stock,
        "starter": card.starter,
        "add_zone_low": card.add_zone_low,
        "add_zone_high": card.add_zone_high,
        "stock_sl": card.stock_sl,
        "stock_pt1": card.stock_pt1,
        "stock_pt2": card.stock_pt2,
        "stock_pt3": card.stock_pt3,
        "fib_0618": card.fib_0618,
    }
    return {name: "MENTOR_INPUT" for name, value in fields.items() if value is not None}


def _directional_targets(
    card: PublicTradeCard,
    analysis: StockAnalysis,
    current: float,
) -> list[float]:
    raw = [target for scenario in analysis.scenarios for target in scenario.targets]
    raw.extend(level.price for level in analysis.resistance_levels)
    raw.extend(level.price for level in analysis.support_levels)
    existing = {
        float(value)
        for value in (card.stock_pt1, card.stock_pt2, card.stock_pt3)
        if value is not None
    }
    if card.option_side == "PUT":
        return sorted(
            {round(value, 4) for value in raw if value < current and value not in existing},
            reverse=True,
        )
    return sorted({round(value, 4) for value in raw if value > current and value not in existing})


def _axis_add_zone(
    card: PublicTradeCard,
    analysis: StockAnalysis,
    current: float,
) -> tuple[Decimal | None, Decimal | None, dict[str, str]]:
    low, high = card.add_zone_low, card.add_zone_high
    provenance: dict[str, str] = {}
    if card.option_side == "PUT":
        candidates = sorted(
            {level.price for level in analysis.resistance_levels if level.price > current}
        )
    else:
        candidates = sorted(
            {level.price for level in analysis.support_levels if level.price < current},
            reverse=True,
        )
    if low is None and high is None and len(candidates) >= 2:
        low, high = sorted((_decimal(candidates[0]), _decimal(candidates[1])))
        provenance = {
            "add_zone_low": "STOCK_ANALYST",
            "add_zone_high": "STOCK_ANALYST",
        }
    elif low is None and high is not None:
        match = next((value for value in candidates if value < float(high)), None)
        if match is not None:
            low = _decimal(match)
            provenance["add_zone_low"] = "STOCK_ANALYST"
    elif high is None and low is not None:
        match = next((value for value in candidates if value > float(low)), None)
        if match is not None:
            high = _decimal(match)
            provenance["add_zone_high"] = "STOCK_ANALYST"
    return low, high, provenance


def compute_fib_0618(
    bars: tuple[DailyBar, ...],
    *,
    option_side: str | None,
) -> Decimal | None:
    """Use a visible 60-session swing only when its range is materially non-flat."""

    window = tuple(sorted(bars, key=lambda item: item.timestamp))[-60:]
    if len(window) < 20:
        return None
    swing_high = max(window, key=lambda item: item.high)
    swing_low = min(window, key=lambda item: item.low)
    price_range = swing_high.high - swing_low.low
    if (
        swing_high.timestamp.date() == swing_low.timestamp.date()
        or price_range / max(window[-1].close, 0.01) < 0.02
    ):
        return None
    value = (
        swing_low.low + price_range * 0.618
        if option_side == "PUT"
        else swing_high.high - price_range * 0.618
    )
    return _decimal(value)


def resolve_entry_plan(
    card: PublicTradeCard,
    analysis: StockAnalysis,
    bars: tuple[DailyBar, ...],
) -> tuple[PublicTradeCard, dict[str, str]]:
    """Apply Mentor-first / AXIS-fill-missing without changing explicit values."""

    provenance = _mentor_provenance(card)
    current = card.current_stock
    if current is None:
        current = _decimal(analysis.current_price)
        provenance["current_stock"] = "STOCK_ANALYST"
    starter = card.starter
    if starter is None:
        starter = current
        provenance["starter"] = "STOCK_ANALYST"

    targets: list[Decimal | None] = [card.stock_pt1, card.stock_pt2, card.stock_pt3]
    candidates = _directional_targets(card, analysis, float(current))
    for index, value in enumerate(targets):
        if value is None and candidates:
            targets[index] = _decimal(candidates.pop(0))
            provenance[f"stock_pt{index + 1}"] = "STOCK_ANALYST"

    add_low, add_high, add_provenance = _axis_add_zone(card, analysis, float(current))
    provenance.update(add_provenance)

    stock_sl = card.stock_sl
    if stock_sl is None:
        primary = max(
            analysis.scenarios,
            key=lambda scenario: scenario.model_weight_percent,
            default=None,
        )
        if primary is not None and primary.invalidation is not None:
            invalidation = primary.invalidation
            valid = (
                invalidation > float(current)
                if card.option_side == "PUT"
                else invalidation < float(current)
            )
            if valid:
                stock_sl = _decimal(invalidation)
                provenance["stock_sl"] = "STOCK_ANALYST"

    fib = card.fib_0618
    if fib is None:
        fib = compute_fib_0618(bars, option_side=card.option_side)
        if fib is not None:
            provenance["fib_0618"] = "STOCK_ANALYST"

    return (
        replace(
            card,
            current_stock=current,
            starter=starter,
            add_zone_low=add_low,
            add_zone_high=add_high,
            stock_sl=stock_sl,
            stock_pt1=targets[0],
            stock_pt2=targets[1],
            stock_pt3=targets[2],
            fib_0618=fib,
        ),
        provenance,
    )


def visible_entry_plan_labels(card: PublicTradeCard) -> tuple[str, ...]:
    labels: list[str] = []
    if card.current_stock is not None:
        labels.append("CURRENT")
    if card.starter is not None:
        labels.append("STARTER")
    if card.add_zone_low is not None and card.add_zone_high is not None:
        labels.append("ADD ZONE")
    if card.stock_sl is not None:
        labels.append("SL")
    for label, value in (
        ("PT1", card.stock_pt1),
        ("PT2", card.stock_pt2),
        ("PT3", card.stock_pt3),
    ):
        if value is not None:
            labels.append(label)
    if card.fib_0618 is not None:
        labels.append("0.618")
    return tuple(labels)


def _font(size: int, *, bold: bool = False):
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


def render_swing_leaps_entry_chart(
    card: PublicTradeCard,
    bars: tuple[DailyBar, ...],
) -> bytes:
    """Render real candles plus the resolved plan; never create fake market data."""

    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("PIL_UNAVAILABLE") from exc
    history = tuple(sorted(bars, key=lambda item: item.timestamp))[-64:]
    if len(history) < 20 or card.current_stock is None:
        raise ValueError("TRADE_PLAN_HISTORY_INSUFFICIENT")

    width, height = 1800, 1050
    image = Image.new("RGB", (width, height), "#050807")
    draw = ImageDraw.Draw(image, "RGBA")
    white, muted, grid = "#F4F6F2", "#7D8984", "#14201C"
    up, down = "#46D69A", "#E15B64"
    blue, orange, red, green, fib_color = (
        "#4EA1FF",
        "#F0A34A",
        "#E15B64",
        "#54D99A",
        "#85918C",
    )
    left, history_right, projection_left, path_right, right = 70, 1160, 1200, 1480, 1660
    top, bottom = 165, 910
    values = [bar.low for bar in history] + [bar.high for bar in history]
    for value in (
        card.current_stock,
        card.starter,
        card.add_zone_low,
        card.add_zone_high,
        card.stock_sl,
        card.stock_pt1,
        card.stock_pt2,
        card.stock_pt3,
        card.fib_0618,
    ):
        if value is not None:
            values.append(float(value))
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.09, float(card.current_stock) * 0.01)
    floor, ceiling = floor - padding, ceiling + padding

    def y(price: float) -> float:
        return bottom - (price - floor) / (ceiling - floor) * (bottom - top)

    category = "SWING" if card.category == "SWING" else "LEAPS"
    side = "C" if card.option_side == "CALL" else "P"
    expiry = card.expiry.strftime("%m/%d/%Y") if card.expiry else "—"
    draw.text(
        (left, 42),
        f"{card.ticker or '—'} · {expiry} · {card.strike or '—'}{side}",
        font=_font(40, bold=True),
        fill=white,
    )
    draw.text(
        (left, 100),
        f"{category} · STARTER ENTRY · AXIS TRADE PLAN",
        font=_font(23, bold=True),
        fill=green,
    )
    for index in range(7):
        price = floor + (ceiling - floor) * index / 6
        y_pos = y(price)
        draw.line((left, y_pos, right, y_pos), fill=grid, width=1)
        draw.text(
            (right + 18, y_pos),
            _money(price),
            font=_font(15, bold=True),
            fill=muted,
            anchor="lm",
        )

    step = (history_right - left) / len(history)
    candle_width = max(4, int(step * 0.55))
    for index, bar in enumerate(history):
        x_pos = left + step * (index + 0.5)
        color = up if bar.close >= bar.open else down
        draw.line((x_pos, y(bar.high), x_pos, y(bar.low)), fill=color, width=2)
        upper, lower = sorted((y(bar.open), y(bar.close)))
        lower = max(lower, upper + 2)
        draw.rectangle(
            (x_pos - candle_width / 2, upper, x_pos + candle_width / 2, lower),
            fill=color,
        )
    ema20 = ema_series(tuple(bar.close for bar in history), 20)
    ema_points = [
        (left + step * (index + 19.5), y(value)) for index, value in enumerate(ema20)
    ]
    if len(ema_points) >= 2:
        draw.line(ema_points, fill="#8CA3A0", width=2, joint="curve")

    if card.add_zone_low is not None and card.add_zone_high is not None:
        zone_top = y(float(max(card.add_zone_low, card.add_zone_high)))
        zone_bottom = y(float(min(card.add_zone_low, card.add_zone_high)))
        draw.rectangle(
            (left, zone_top, right, zone_bottom),
            fill=(240, 163, 74, 42),
            outline=orange,
            width=2,
        )
        draw.text(
            (right - 8, zone_top + 8),
            f"ADD ZONE  {_money(card.add_zone_low)} – {_money(card.add_zone_high)}",
            font=_font(16, bold=True),
            fill=orange,
            anchor="ra",
        )

    def horizontal(
        value: Decimal | None,
        label: str,
        color: str,
        width_px: int = 3,
        label_x: int | None = None,
    ) -> None:
        if value is None:
            return
        y_pos = y(float(value))
        draw.line((left, y_pos, right, y_pos), fill=color, width=width_px)
        draw.text(
            (label_x or right - 8, y_pos - 8),
            f"{label}  {_money(value)}",
            font=_font(16, bold=True),
            fill=color,
            anchor="rs",
        )

    horizontal(card.starter, "STARTER", blue, 4)
    horizontal(card.stock_sl, "SL", red, 4)
    horizontal(card.stock_pt1, "PT1", green)
    horizontal(card.stock_pt2, "PT2", green)
    horizontal(card.stock_pt3, "PT3", green)
    if card.fib_0618 is not None:
        fib_y = y(float(card.fib_0618))
        cursor = left
        while cursor < right:
            draw.line((cursor, fib_y, min(cursor + 14, right), fib_y), fill=fib_color, width=2)
            cursor += 28
        draw.text(
            (history_right - 8, fib_y - 7),
            f"0.618  {_money(card.fib_0618)}",
            font=_font(15, bold=True),
            fill=fib_color,
            anchor="rs",
        )
    horizontal(card.current_stock, "CURRENT", white, 2, history_right - 8)

    path_values: list[tuple[str, Decimal]] = [("CURRENT", card.current_stock)]
    if card.starter is not None:
        path_values.append(("STARTER", card.starter))
    if card.add_zone_low is not None and card.add_zone_high is not None:
        path_values.append(("ADD", (card.add_zone_low + card.add_zone_high) / 2))
    path_values.extend(
        (label, value)
        for label, value in (
            ("PT1", card.stock_pt1),
            ("PT2", card.stock_pt2),
            ("PT3", card.stock_pt3),
        )
        if value is not None
    )
    if len(path_values) >= 2:
        path_points = [
            (
                projection_left
                + index * (path_right - projection_left) / max(len(path_values) - 1, 1),
                y(float(value)),
            )
            for index, (_, value) in enumerate(path_values)
        ]
        draw.line(path_points, fill=white, width=5, joint="curve")
        for (x_pos, y_pos), (label, _) in zip(path_points, path_values, strict=True):
            node_color = green if label.startswith("PT") else white
            draw.ellipse((x_pos - 7, y_pos - 7, x_pos + 7, y_pos + 7), fill=node_color)
    draw.text(
        (left, 985),
        "REAL DAILY CANDLES · MENTOR LEVELS FIRST · AXIS FILLS MISSING LEVELS ONLY",
        font=_font(16, bold=True),
        fill=muted,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
