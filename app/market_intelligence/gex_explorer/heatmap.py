"""Deterministic Chinese intraday K-line and GEX heatmap rendering."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from app.market_intelligence.gex_explorer.models import GexIntradayBar, GexSnapshot

ET = ZoneInfo("America/New_York")


class HeatmapPolicy(Protocol):
    heatmap_expiration_columns: int
    heatmap_strike_rows: int


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    names = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
    )
    for name in names:
        if Path(name).is_file():
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _compact_zh(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 100_000_000:
        return f"{value / 100_000_000:+.1f}亿"
    if magnitude >= 10_000:
        return f"{value / 10_000:+.1f}万"
    return f"{value:+.0f}"


def _nearest_strike(strikes: tuple[float, ...], value: float | None) -> float | None:
    if value is None or not strikes:
        return None
    return min(strikes, key=lambda strike: abs(strike - value))


def _selected_strikes(snapshot: GexSnapshot, limit: int) -> tuple[float, ...]:
    strikes = tuple(point.strike for point in snapshot.by_strike)
    anchors = {
        value
        for value in (
            _nearest_strike(strikes, snapshot.spot),
            _nearest_strike(strikes, snapshot.zero_gamma),
            snapshot.call_wall,
            snapshot.put_wall,
        )
        if value is not None
    }
    for strike in sorted(strikes, key=lambda value: abs(value - snapshot.spot)):
        anchors.add(strike)
        if len(anchors) >= limit:
            break
    return tuple(sorted(anchors, reverse=True))


def _level_label(snapshot: GexSnapshot, level: float) -> tuple[str, str]:
    if snapshot.call_wall is not None and abs(level - snapshot.call_wall) < 1e-9:
        return "上方压力", "#D8B85B"
    if snapshot.put_wall is not None and abs(level - snapshot.put_wall) < 1e-9:
        return "下方支撑", "#77A997"
    return "Gamma 分界", "#9FA9A5"


def render_gex_heatmap(
    snapshot: GexSnapshot,
    intraday_bars: tuple[GexIntradayBar, ...],
    policy: HeatmapPolicy,
) -> bytes:
    """Render one desktop-first chart: real 1m candles, GEX levels/zones, and heatmap."""

    from PIL import Image, ImageDraw

    bars = tuple(sorted(intraday_bars, key=lambda item: item.timestamp_et))
    if not bars:
        raise ValueError("GEX intraday renderer requires real 1-minute bars")

    width, height = 1800, 1040
    image = Image.new("RGBA", (width, height), "#050807")
    draw = ImageDraw.Draw(image, "RGBA")
    white = "#F4F5F1"
    muted = "#87928D"
    secondary = "#B3BCB8"
    green = "#45D59A"
    red = "#D46B73"
    grid = "#17211E"
    panel = "#08100E"

    margin = 48
    left_panel_right = 1215
    right_panel_left = 1235
    panel_top = 138
    panel_bottom = 908
    plot_left = 76
    plot_right = 1182
    plot_top = 190
    plot_bottom = 848

    draw.text((margin, 34), f"AXIS GEX · {snapshot.ticker}", fill=white, font=_font(38, bold=True))
    draw.text(
        (margin, 87),
        "真实 1 分钟 K 线 · 支撑压力 · 波动加速区 · GEX 热力图",
        fill=secondary,
        font=_font(20, bold=True),
    )
    draw.text(
        (width - margin, 40),
        f"现价 ${snapshot.spot:,.2f}  ·  {snapshot.gamma_regime}",
        fill=green if snapshot.net_gex >= 0 else red,
        font=_font(25, bold=True),
        anchor="ra",
    )
    draw.text(
        (width - margin, 86),
        f"{snapshot.timestamp_et.astimezone(ET):%Y-%m-%d %H:%M} ET",
        fill=muted,
        font=_font(17, bold=True),
        anchor="ra",
    )

    draw.rounded_rectangle(
        (margin, panel_top, left_panel_right, panel_bottom),
        radius=18,
        fill=panel,
        outline="#21302B",
        width=2,
    )
    draw.rounded_rectangle(
        (right_panel_left, panel_top, width - margin, panel_bottom),
        radius=18,
        fill=panel,
        outline="#21302B",
        width=2,
    )
    draw.text((plot_left, 158), "1 分钟 K 线", fill=secondary, font=_font(17, bold=True))
    draw.text(
        (plot_right, 158),
        f"{bars[0].timestamp_et:%H:%M}–{bars[-1].timestamp_et:%H:%M} ET · {len(bars)} 根",
        fill=muted,
        font=_font(15, bold=True),
        anchor="ra",
    )

    candle_floor = min(item.low for item in bars)
    candle_ceiling = max(item.high for item in bars)
    candle_span = max(candle_ceiling - candle_floor, snapshot.spot * 0.002)
    # Keep nearby GEX structure visible without allowing remote chain-tail strikes to
    # flatten the intraday candles. Four percent includes the actionable walls in the
    # common case; more distant levels remain explicit in the heatmap markers/card.
    visible_distance = max(candle_span * 2.6, snapshot.spot * 0.04)
    structural_levels = tuple(
        value
        for value in (snapshot.call_wall, snapshot.put_wall, snapshot.zero_gamma)
        if value is not None and abs(value - snapshot.spot) <= visible_distance
    )
    zone_prices = tuple(
        value
        for zone in snapshot.negative_zones[:3]
        for value in (zone.lower, zone.upper)
        if abs(value - snapshot.spot) <= visible_distance
    )
    values = [candle_floor, candle_ceiling, snapshot.spot, *structural_levels, *zone_prices]
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.12, snapshot.spot * 0.0015)
    floor -= padding
    ceiling += padding

    def price_y(price: float) -> float:
        return plot_bottom - (price - floor) / (ceiling - floor) * (plot_bottom - plot_top)

    for index in range(7):
        y = plot_top + (plot_bottom - plot_top) * index / 6
        price = ceiling - (ceiling - floor) * index / 6
        draw.line((plot_left, y, plot_right, y), fill=grid, width=1)
        draw.text(
            (plot_right - 8, y + 5),
            f"{price:,.2f}",
            fill=muted,
            font=_font(13, bold=True),
            anchor="ra",
        )

    for zone in snapshot.negative_zones[:3]:
        if zone.upper < floor or zone.lower > ceiling:
            continue
        half_width = max((ceiling - floor) * 0.009, snapshot.spot * 0.0008)
        lower = max(zone.lower - half_width, floor)
        upper = min(zone.upper + half_width, ceiling)
        top_y, bottom_y = sorted((price_y(upper), price_y(lower)))
        draw.rectangle(
            (plot_left, top_y, plot_right, bottom_y),
            fill=(168, 61, 73, 34),
        )
        zone_label = (
            f"{zone.lower:g}"
            if abs(zone.lower - zone.upper) < 1e-9
            else f"{zone.lower:g}–{zone.upper:g}"
        )
        draw.text(
            (plot_left + 10, top_y + 7),
            f"波动加速区 {zone_label}",
            fill="#D98B91",
            font=_font(14, bold=True),
        )

    candle_step = (plot_right - plot_left) / len(bars)
    candle_width = max(2, int(candle_step * 0.62))
    for index, bar in enumerate(bars):
        x = plot_left + candle_step * (index + 0.5)
        color = green if bar.close >= bar.open else red
        draw.line((x, price_y(bar.high), x, price_y(bar.low)), fill=color, width=1)
        upper, lower = sorted((price_y(bar.open), price_y(bar.close)))
        lower = max(lower, upper + 2)
        draw.rectangle((x - candle_width / 2, upper, x + candle_width / 2, lower), fill=color)

    unique_levels: list[float] = []
    for value in structural_levels:
        if not any(abs(value - item) / value < 0.0005 for item in unique_levels):
            unique_levels.append(value)
    for level in unique_levels:
        label, color = _level_label(snapshot, level)
        y = price_y(level)
        draw.line((plot_left, y, plot_right, y), fill=color, width=2)
        text = f"{label}  {level:,.2f}"
        box_width = 178
        draw.rounded_rectangle(
            (plot_right - box_width, y - 16, plot_right - 6, y + 16),
            radius=7,
            fill="#0A1411",
            outline=color,
            width=1,
        )
        draw.text(
            (plot_right - 14, y),
            text,
            fill=color,
            font=_font(14, bold=True),
            anchor="rm",
        )

    spot_y = price_y(snapshot.spot)
    draw.line((plot_left, spot_y, plot_right, spot_y), fill=white, width=2)
    draw.rounded_rectangle(
        (plot_left + 8, spot_y - 17, plot_left + 159, spot_y + 17),
        radius=7,
        fill="#101A17",
        outline=white,
        width=1,
    )
    draw.text(
        (plot_left + 18, spot_y),
        f"现价 {snapshot.spot:,.2f}",
        fill=white,
        font=_font(14, bold=True),
        anchor="lm",
    )

    time_indexes = sorted({0, len(bars) // 3, len(bars) * 2 // 3, len(bars) - 1})
    for index in time_indexes:
        x = plot_left + candle_step * (index + 0.5)
        draw.text(
            (x, plot_bottom + 20),
            bars[index].timestamp_et.strftime("%H:%M"),
            fill=muted,
            font=_font(14, bold=True),
            anchor="ma",
        )

    heatmap_left = right_panel_left + 18
    heatmap_right = width - margin - 18
    draw.text(
        (heatmap_left, 158), "GEX 热力图", fill=secondary, font=_font(17, bold=True)
    )
    expirations = snapshot.expirations[: policy.heatmap_expiration_columns]
    strikes = _selected_strikes(snapshot, policy.heatmap_strike_rows)
    table_top = 220
    row_height = min(34, max(24, int((plot_bottom - table_top) / max(1, len(strikes)))))
    strike_width = 66
    total_width = 82
    cell_width = max(
        54,
        int((heatmap_right - heatmap_left - strike_width - total_width) / max(1, len(expirations))),
    )
    draw.text((heatmap_left, table_top - 31), "执行价", fill=muted, font=_font(13, bold=True))
    for index, expiration in enumerate(expirations):
        x = heatmap_left + strike_width + index * cell_width + cell_width / 2
        draw.text(
            (x, table_top - 31),
            expiration.expiration.strftime("%m/%d"),
            fill=muted,
            font=_font(12, bold=True),
            anchor="ma",
        )
    draw.text(
        (heatmap_right, table_top - 31),
        "合计",
        fill=muted,
        font=_font(13, bold=True),
        anchor="ra",
    )

    expiration_maps = [
        {point.strike: point for point in expiration.by_strike} for expiration in expirations
    ]
    aggregate_map = {point.strike: point for point in snapshot.by_strike}
    max_cell = max(
        (abs(point.net_gex) for expiration in expirations for point in expiration.by_strike),
        default=1.0,
    )
    spot_row = _nearest_strike(strikes, snapshot.spot)
    marker_map: dict[float, list[str]] = {}
    for strike, label in (
        (spot_row, "现"),
        (_nearest_strike(strikes, snapshot.zero_gamma), "零"),
        (snapshot.call_wall, "压"),
        (snapshot.put_wall, "撑"),
    ):
        if strike is not None and strike in strikes:
            marker_map.setdefault(strike, []).append(label)

    for row_index, strike in enumerate(strikes):
        y = table_top + row_index * row_height
        if strike in marker_map:
            draw.rounded_rectangle(
                (heatmap_left - 4, y, heatmap_right + 4, y + row_height - 2),
                radius=5,
                outline=green if "现" in marker_map[strike] else "#52635D",
                width=1,
            )
        draw.text(
            (heatmap_left, y + row_height / 2),
            f"{strike:g}",
            fill=white,
            font=_font(12, bold=True),
            anchor="lm",
        )
        markers = "".join(marker_map.get(strike, ()))
        if markers:
            draw.text(
                (heatmap_left + 40, y + row_height / 2),
                markers,
                fill=green,
                font=_font(11, bold=True),
                anchor="lm",
            )
        for column_index, expiration_map in enumerate(expiration_maps):
            point = expiration_map.get(strike)
            value = point.net_gex if point is not None else 0.0
            strength = min(1.0, abs(value) / max_cell)
            if value > 0:
                color = (20, int(66 + 112 * strength), int(54 + 70 * strength), 255)
            elif value < 0:
                color = (int(74 + 122 * strength), 35, int(49 + 26 * strength), 255)
            else:
                color = (20, 28, 25, 255)
            x = heatmap_left + strike_width + column_index * cell_width
            draw.rounded_rectangle(
                (x + 2, y + 2, x + cell_width - 2, y + row_height - 4),
                radius=4,
                fill=color,
            )
            draw.text(
                (x + cell_width / 2, y + row_height / 2 - 1),
                _compact_zh(value),
                fill=white,
                font=_font(10, bold=True),
                anchor="mm",
            )
        aggregate = aggregate_map.get(strike)
        total = aggregate.net_gex if aggregate is not None else 0.0
        draw.text(
            (heatmap_right, y + row_height / 2),
            _compact_zh(total),
            fill=green if total > 0 else red if total < 0 else muted,
            font=_font(11, bold=True),
            anchor="rm",
        )

    legend_y = 874
    draw.text(
        (heatmap_left, legend_y),
        "绿色：正 GEX   红色：负 GEX   现：现价   零：Gamma 分界   压：压力   撑：支撑",
        fill=muted,
        font=_font(11, bold=True),
    )
    draw.text(
        (margin, 952),
        "波动加速区来自负 GEX 集中带；支撑、压力与分界均由当前期权表面确定，不使用模型臆造。",
        fill=secondary,
        font=_font(16, bold=True),
    )
    draw.text(
        (width - margin, 992),
        "教育与市场结构研究用途，不构成投资建议",
        fill=muted,
        font=_font(15, bold=True),
        anchor="ra",
    )
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
