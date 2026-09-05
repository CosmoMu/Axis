"""Deterministic AXIS intraday chart and professional GEX ladder rendering."""

from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from app.market_intelligence.gex_explorer.models import (
    GexByStrike,
    GexIntradayBar,
    GexSnapshot,
)

ET = ZoneInfo("America/New_York")


class HeatmapPolicy(Protocol):
    heatmap_expiration_columns: int
    heatmap_strike_rows: int
    intraday_interval_minutes: int


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


def _compact(value: float | None) -> str:
    if value is None:
        return "—"
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{value / 1_000_000_000:+.1f}B"
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:+.1f}M"
    if magnitude >= 1_000:
        return f"{value / 1_000:+.0f}K"
    return f"{value:+.0f}"


def _price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _nearest_strike(strikes: tuple[float, ...], value: float | None) -> float | None:
    if value is None or not strikes:
        return None
    return min(strikes, key=lambda strike: abs(strike - value))


def _selected_strikes(snapshot: GexSnapshot, limit: int) -> tuple[float, ...]:
    """Return a continuous slice of real listed strikes centered around spot."""

    source = snapshot.listed_strikes or tuple(point.strike for point in snapshot.by_strike)
    strikes = tuple(sorted(set(source)))
    if len(strikes) <= limit:
        return tuple(reversed(strikes))
    nearest = min(range(len(strikes)), key=lambda index: abs(strikes[index] - snapshot.spot))
    half = limit // 2
    start = max(0, min(nearest - half, len(strikes) - limit))
    end = start + limit
    for wall in (snapshot.call_wall, snapshot.put_wall):
        if wall is None or wall not in strikes:
            continue
        wall_index = strikes.index(wall)
        if start - 4 <= wall_index < start:
            start, end = wall_index, wall_index + limit
        elif end <= wall_index < end + 4:
            end = wall_index + 1
            start = end - limit
    return tuple(reversed(strikes[start:end]))


def _same(left: float | None, right: float) -> bool:
    return left is not None and abs(left - right) < 1e-9


def _roles(snapshot: GexSnapshot, strike: float, spot_row: float | None) -> tuple[str, ...]:
    roles: list[str] = []
    if _same(snapshot.call_wall, strike):
        roles.append("CALL WALL")
    if _same(snapshot.put_wall, strike):
        roles.append("PUT WALL")
    if _same(snapshot.gamma_magnet, strike):
        roles.append("MAGNET")
    if _same(spot_row, strike):
        roles.append("SPOT")
    if strike in snapshot.major_resistance:
        roles.append("MAJOR RES")
    elif strike in snapshot.minor_resistance:
        roles.append("MINOR RES")
    if strike in snapshot.major_support:
        roles.append("MAJOR SUP")
    elif strike in snapshot.minor_support:
        roles.append("MINOR SUP")
    if strike in snapshot.gamma_nodes and not roles:
        roles.append("GAMMA NODE")
    flip_row = _nearest_strike(snapshot.listed_strikes, snapshot.zero_gamma)
    if _same(flip_row, strike) and "SPOT" not in roles:
        roles.append("FLIP ≈")
    if any(zone.lower <= strike <= zone.upper for zone in snapshot.negative_zones):
        roles.append("ACCEL")
    return tuple(roles[:2])


def _level_label(snapshot: GexSnapshot, level: float) -> tuple[str, str]:
    if level in snapshot.major_resistance:
        return "大压力", "#E6C84F"
    if level in snapshot.minor_resistance:
        return "小压力", "#E6C84F"
    if level in snapshot.major_support:
        return "大支撑", "#69D6C0"
    if level in snapshot.minor_support:
        return "小支撑", "#69D6C0"
    if _same(snapshot.gamma_magnet, level):
        return "Gamma Magnet", "#86F7A8"
    if _same(snapshot.zero_gamma, level):
        return "Gamma Flip", "#B991FF"
    return "GEX 结构", "#A9B5B0"


def _dashed_horizontal(
    draw,
    *,
    left: float,
    right: float,
    y: float,
    fill: str,
    width: int = 2,
    dash: int = 12,
    gap: int = 8,
) -> None:
    x = left
    while x < right:
        draw.line((x, y, min(x + dash, right), y), fill=fill, width=width)
        x += dash + gap


def _percentile(values: list[float], fraction: float = 0.90) -> float:
    if not values:
        return 1.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return max(1.0, ordered[index])


def _heat_color(value: float | None, scale: float) -> tuple[int, int, int, int]:
    if value is None:
        return (13, 20, 18, 255)
    strength = min(1.0, math.log1p(abs(value)) / math.log1p(scale)) if value else 0.0
    if value > 0:
        return (12, int(47 + 104 * strength), int(51 + 80 * strength), 255)
    if value < 0:
        return (int(54 + 83 * strength), 24, int(62 + 94 * strength), 255)
    return (15, 24, 21, 255)


def _draw_summary_card(draw, box, title: str, primary: str, secondary: str, accent: str) -> None:
    draw.rounded_rectangle(box, radius=14, fill="#09110F", outline="#21302B", width=2)
    left, top, _, _ = box
    draw.text((left + 20, top + 15), title, fill="#87928D", font=_font(15, bold=True))
    draw.text((left + 20, top + 49), primary, fill=accent, font=_font(24, bold=True))
    draw.text((left + 20, top + 88), secondary, fill="#B3BCB8", font=_font(14, bold=True))


def _point_value(mapping: dict[float, GexByStrike], strike: float) -> float | None:
    point = mapping.get(strike)
    return point.net_gex if point is not None else None


def render_gex_heatmap(
    snapshot: GexSnapshot,
    intraday_bars: tuple[GexIntradayBar, ...],
    policy: HeatmapPolicy,
) -> bytes:
    """Render the Discord/mobile TOP → chart → strike-ladder hierarchy."""

    from PIL import Image, ImageDraw

    bars = tuple(sorted(intraday_bars, key=lambda item: item.timestamp_et))
    if not bars:
        raise ValueError("GEX intraday renderer requires real market bars")

    width, height = 1800, 1600
    image = Image.new("RGBA", (width, height), "#050807")
    draw = ImageDraw.Draw(image, "RGBA")
    white = "#F4F5F1"
    muted = "#87928D"
    secondary = "#B3BCB8"
    green = "#45D59A"
    red = "#D46B73"
    yellow = "#E6C84F"
    purple = "#B991FF"
    teal = "#69D6C0"
    grid = "#17211E"
    panel = "#08100E"
    margin = 48

    draw.text((margin, 31), f"AXIS GEX · {snapshot.ticker}", fill=white, font=_font(38, bold=True))
    draw.text(
        (margin, 83),
        "日内 Gamma 结构 · 非方向性交易信号",
        fill=secondary,
        font=_font(19, bold=True),
    )
    draw.text(
        (width - margin, 38),
        f"{snapshot.timestamp_et.astimezone(ET):%Y-%m-%d %H:%M} ET",
        fill=muted,
        font=_font(17, bold=True),
        anchor="ra",
    )

    card_top, card_bottom = 116, 248
    card_gap = 14
    card_width = (width - margin * 2 - card_gap * 3) / 4
    card_boxes = [
        (
            margin + index * (card_width + card_gap),
            card_top,
            margin + index * (card_width + card_gap) + card_width,
            card_bottom,
        )
        for index in range(4)
    ]
    regime_color = green if snapshot.net_gex > 0 else red if snapshot.net_gex < 0 else white
    _draw_summary_card(
        draw,
        card_boxes[0],
        "CURRENT · 现价",
        f"${snapshot.spot:,.2f}",
        f"最近 K 线 {bars[-1].timestamp_et:%H:%M} ET",
        white,
    )
    _draw_summary_card(
        draw,
        card_boxes[1],
        "REGIME · Gamma 状态",
        snapshot.gamma_regime,
        f"Net GEX {_compact(snapshot.net_gex)}",
        regime_color,
    )
    _draw_summary_card(
        draw,
        card_boxes[2],
        "MAJOR WALLS · 原始墙",
        f"CALL {_price(snapshot.call_wall)}  ·  PUT {_price(snapshot.put_wall)}",
        "Gross Wall 不自动等同压力 / 支撑",
        yellow,
    )
    nearest_res = min(
        (*snapshot.major_resistance, *snapshot.minor_resistance),
        default=None,
        key=lambda level: abs(level - snapshot.spot),
    )
    nearest_sup = min(
        (*snapshot.major_support, *snapshot.minor_support),
        default=None,
        key=lambda level: abs(level - snapshot.spot),
    )
    _draw_summary_card(
        draw,
        card_boxes[3],
        "NEAREST LEVELS · 最近结构",
        f"压 {_price(nearest_res)}  ·  撑 {_price(nearest_sup)}",
        f"Magnet {_price(snapshot.gamma_magnet)} · Flip {_price(snapshot.zero_gamma)}",
        teal,
    )

    chart_box = (margin, 276, width - margin, 946)
    draw.rounded_rectangle(chart_box, radius=18, fill=panel, outline="#21302B", width=2)
    draw.text(
        (72, 297),
        f"价格路径 · {policy.intraday_interval_minutes} 分钟",
        fill=white,
        font=_font(20, bold=True),
    )
    draw.text(
        (width - 72, 300),
        "粗虚线 = 主要 · 点线 = 次要 · 紫色 = 负 Gamma 加速",
        fill=muted,
        font=_font(14, bold=True),
        anchor="ra",
    )
    plot_left, plot_right, plot_top, plot_bottom = 76, width - 190, 350, 882
    candle_floor = min(bar.low for bar in bars)
    candle_ceiling = max(bar.high for bar in bars)
    candle_span = max(candle_ceiling - candle_floor, snapshot.spot * 0.002)
    actionable = (
        *snapshot.major_resistance,
        *snapshot.minor_resistance,
        *snapshot.major_support,
        *snapshot.minor_support,
        *((snapshot.gamma_magnet,) if snapshot.gamma_magnet is not None else ()),
        *((snapshot.zero_gamma,) if snapshot.zero_gamma is not None else ()),
    )
    visible_distance = max(candle_span * 2.0, snapshot.spot * 0.012)
    visible_levels = tuple(
        level for level in actionable if abs(level - snapshot.spot) <= visible_distance
    )
    visible_zone_prices = tuple(
        value
        for zone in snapshot.negative_zones[:3]
        for value in (zone.lower, zone.upper)
        if abs(value - snapshot.spot) <= visible_distance
    )
    values = [candle_floor, candle_ceiling, snapshot.spot, *visible_levels, *visible_zone_prices]
    floor, ceiling = min(values), max(values)
    padding = max((ceiling - floor) * 0.10, snapshot.spot * 0.0015)
    floor, ceiling = floor - padding, ceiling + padding

    def price_y(price: float) -> float:
        return plot_bottom - (price - floor) / max(ceiling - floor, 1e-9) * (plot_bottom - plot_top)

    for index in range(6):
        y = plot_top + (plot_bottom - plot_top) * index / 5
        price = ceiling - (ceiling - floor) * index / 5
        draw.line((plot_left, y, plot_right, y), fill=grid, width=1)
        draw.text((plot_right - 6, y + 4), f"{price:,.2f}", fill=muted, font=_font(12), anchor="ra")

    for zone in snapshot.negative_zones[:3]:
        if zone.upper < floor or zone.lower > ceiling:
            continue
        lower, upper = max(zone.lower, floor), min(zone.upper, ceiling)
        top_y, bottom_y = sorted((price_y(upper), price_y(lower)))
        if bottom_y - top_y < 10:
            top_y -= 6
            bottom_y += 6
        draw.rectangle((plot_left, top_y, plot_right, bottom_y), fill="#21142D")
        _dashed_horizontal(
            draw, left=plot_left, right=plot_right, y=top_y, fill=purple, dash=4, gap=6
        )
        _dashed_horizontal(
            draw, left=plot_left, right=plot_right, y=bottom_y, fill=purple, dash=4, gap=6
        )
        draw.text(
            (plot_left + 12, top_y + 7),
            f"加速区 {zone.lower:g}–{zone.upper:g}",
            fill="#D0B9FF",
            font=_font(13, bold=True),
        )

    candle_step = (plot_right - plot_left) / len(bars)
    candle_width = max(2, int(candle_step * 0.60))
    for index, bar in enumerate(bars):
        x = plot_left + candle_step * (index + 0.5)
        color = green if bar.close >= bar.open else red
        draw.line((x, price_y(bar.high), x, price_y(bar.low)), fill=color, width=1)
        top, bottom = sorted((price_y(bar.open), price_y(bar.close)))
        draw.rectangle(
            (x - candle_width / 2, top, x + candle_width / 2, max(bottom, top + 2)), fill=color
        )

    level_specs: list[tuple[float, str, str, bool, bool]] = []
    level_specs.extend(
        (level, "大压力", yellow, True, False) for level in snapshot.major_resistance
    )
    level_specs.extend(
        (level, "小压力", yellow, False, True) for level in snapshot.minor_resistance
    )
    level_specs.extend((level, "大支撑", teal, True, False) for level in snapshot.major_support)
    level_specs.extend((level, "小支撑", teal, False, True) for level in snapshot.minor_support)
    if snapshot.gamma_magnet is not None:
        level_specs.append((snapshot.gamma_magnet, "Magnet", green, False, False))
    if snapshot.zero_gamma is not None:
        level_specs.append((snapshot.zero_gamma, "Gamma Flip", purple, False, True))
    grouped_levels: dict[float, list[tuple[str, str, bool, bool]]] = {}
    for level, label, color, major, dotted in level_specs:
        grouped_levels.setdefault(level, []).append((label, color, major, dotted))
    for level, specifications in grouped_levels.items():
        if not floor <= level <= ceiling:
            continue
        major = any(item[2] for item in specifications)
        dotted = not major and any(item[3] for item in specifications)
        label = " · ".join(item[0] for item in specifications)
        color = next((item[1] for item in specifications if item[2]), specifications[0][1])
        y = price_y(level)
        _dashed_horizontal(
            draw,
            left=plot_left,
            right=plot_right,
            y=y,
            fill=color,
            width=3 if major else 2,
            dash=17 if major else 3 if dotted else 9,
            gap=9 if major else 6,
        )
        text = f"{label} {level:g}"
        draw.rounded_rectangle(
            (plot_right + 8, y - 15, width - 69, y + 15),
            radius=7,
            fill="#0A1411",
            outline=color,
            width=1,
        )
        draw.text((plot_right + 20, y), text, fill=color, font=_font(13, bold=True), anchor="lm")

    spot_y = price_y(snapshot.spot)
    draw.line((plot_left, spot_y, plot_right, spot_y), fill=white, width=2)
    draw.rounded_rectangle(
        (plot_right + 8, spot_y - 16, width - 69, spot_y + 16),
        radius=7,
        fill="#101A17",
        outline=white,
        width=1,
    )
    draw.text(
        (plot_right + 20, spot_y),
        f"现价 {snapshot.spot:,.2f}",
        fill=white,
        font=_font(13, bold=True),
        anchor="lm",
    )
    for index in sorted({0, len(bars) // 3, len(bars) * 2 // 3, len(bars) - 1}):
        x = plot_left + candle_step * (index + 0.5)
        draw.text(
            (x, plot_bottom + 18),
            bars[index].timestamp_et.strftime("%H:%M"),
            fill=muted,
            font=_font(13),
            anchor="ma",
        )

    ladder_box = (margin, 974, width - margin, 1516)
    draw.rounded_rectangle(ladder_box, radius=18, fill=panel, outline="#21302B", width=2)
    draw.text((72, 995), "Strike × Expiration GEX Ladder", fill=white, font=_font(20, bold=True))
    draw.text(
        (width - 72, 999),
        "绿色 = 正 Net GEX · 紫色 = 负 Net GEX · 0DTE 独立显示",
        fill=muted,
        font=_font(14, bold=True),
        anchor="ra",
    )
    expirations = snapshot.expirations[: policy.heatmap_expiration_columns]
    strikes = _selected_strikes(snapshot, min(policy.heatmap_strike_rows, 19))
    table_left, table_right, table_top, table_bottom = 70, width - 70, 1042, 1487
    strike_width, role_width, total_width = 106, 190, 128
    cell_width = (table_right - table_left - strike_width - role_width - total_width) / max(
        1, len(expirations)
    )
    header_height = 50
    row_height = (table_bottom - table_top - header_height) / max(1, len(strikes))
    draw.rectangle((table_left, table_top, table_right, table_top + header_height), fill="#0C1714")
    draw.text(
        (table_left + 10, table_top + 25),
        "STRIKE",
        fill=secondary,
        font=_font(14, bold=True),
        anchor="lm",
    )
    draw.text(
        (table_left + strike_width + 10, table_top + 25),
        "ROLE",
        fill=secondary,
        font=_font(14, bold=True),
        anchor="lm",
    )
    session_date = snapshot.timestamp_et.astimezone(ET).date()
    for index, expiration in enumerate(expirations):
        x = table_left + strike_width + role_width + index * cell_width
        is_zero = expiration.expiration == session_date
        if is_zero:
            draw.rectangle(
                (x, table_top, x + cell_width, table_top + header_height),
                fill="#362D0C",
            )
        dte = max(0, (expiration.expiration - session_date).days)
        label = "0DTE" if is_zero else f"{dte}D"
        draw.text(
            (x + cell_width / 2, table_top + 17),
            expiration.expiration.strftime("%m/%d"),
            fill=yellow if is_zero else white,
            font=_font(13, bold=True),
            anchor="mm",
        )
        draw.text(
            (x + cell_width / 2, table_top + 37),
            label,
            fill=yellow if is_zero else muted,
            font=_font(11, bold=True),
            anchor="mm",
        )
    total_x = table_right - total_width
    draw.text(
        (total_x + total_width / 2, table_top + 25),
        "TOTAL",
        fill=white,
        font=_font(14, bold=True),
        anchor="mm",
    )
    expiration_maps = [{point.strike: point for point in item.by_strike} for item in expirations]
    aggregate_map = {point.strike: point for point in snapshot.by_strike}
    values_for_scale = [
        abs(point.net_gex)
        for item in expirations
        for point in item.by_strike
        if point.strike in strikes
    ]
    values_for_scale.extend(
        abs(point.net_gex) for point in snapshot.by_strike if point.strike in strikes
    )
    scale = _percentile(values_for_scale)
    spot_row = _nearest_strike(strikes, snapshot.spot)
    for row_index, strike in enumerate(strikes):
        y = table_top + header_height + row_index * row_height
        is_spot = _same(spot_row, strike)
        if is_spot:
            draw.rectangle(
                (table_left, y, table_right, y + row_height),
                fill="#102527",
                outline="#AEEFFF",
                width=1,
            )
        elif row_index % 2:
            draw.rectangle((table_left, y, table_right, y + row_height), fill="#0A1210")
        draw.text(
            (table_left + 10, y + row_height / 2),
            f"{strike:g}",
            fill=white,
            font=_font(13, bold=True),
            anchor="lm",
        )
        roles = _roles(snapshot, strike, spot_row)
        role_color = (
            "#AEEFFF"
            if "SPOT" in roles
            else yellow
            if any("RES" in role or "CALL" in role for role in roles)
            else teal
            if any("SUP" in role or "PUT" in role for role in roles)
            else purple
            if any(role in {"ACCEL", "FLIP ≈"} for role in roles)
            else green
        )
        draw.text(
            (table_left + strike_width + 10, y + row_height / 2),
            " · ".join(roles) or "",
            fill=role_color,
            font=_font(10, bold=True),
            anchor="lm",
        )
        for column_index, mapping in enumerate(expiration_maps):
            value = _point_value(mapping, strike)
            x = table_left + strike_width + role_width + column_index * cell_width
            draw.rounded_rectangle(
                (x + 2, y + 2, x + cell_width - 2, y + row_height - 2),
                radius=3,
                fill=_heat_color(value, scale),
            )
            draw.text(
                (x + cell_width / 2, y + row_height / 2),
                _compact(value),
                fill=white if value is not None else muted,
                font=_font(10, bold=True),
                anchor="mm",
            )
        total_value = _point_value(aggregate_map, strike)
        draw.rounded_rectangle(
            (total_x + 2, y + 2, table_right - 2, y + row_height - 2),
            radius=3,
            fill=_heat_color(total_value, scale),
        )
        draw.text(
            (total_x + total_width / 2, y + row_height / 2),
            _compact(total_value),
            fill=white if total_value is not None else muted,
            font=_font(11, bold=True),
            anchor="mm",
        )

    draw.text(
        (margin, 1548),
        "Gamma 仅描述市场结构；不会据此输出 BUY CALL / BUY PUT / LONG / SHORT。缺失值显示为 —。",
        fill=secondary,
        font=_font(15, bold=True),
    )
    draw.text(
        (width - margin, 1548),
        "教育与市场结构研究用途，不构成投资建议",
        fill=muted,
        font=_font(14, bold=True),
        anchor="ra",
    )
    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
