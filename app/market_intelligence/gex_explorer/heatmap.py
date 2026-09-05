"""Deterministic mobile-first GEX heatmap rendering."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Protocol

from app.market_intelligence.gex_explorer.models import GexSnapshot


class HeatmapPolicy(Protocol):
    heatmap_expiration_columns: int
    heatmap_strike_rows: int


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    names = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for name in names:
        if name and Path(name).is_file():
            try:
                return ImageFont.truetype(name, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _compact(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{value / 1_000_000_000:+.1f}B"
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:+.1f}M"
    if magnitude >= 1_000:
        return f"{value / 1_000:+.1f}K"
    return f"{value:+.0f}"


def _regime_label(regime: str) -> str:
    return {
        "强正 Gamma": "STRONG POSITIVE GAMMA",
        "正 Gamma": "POSITIVE GAMMA",
        "Gamma 平衡区": "BALANCED GAMMA",
        "负 Gamma": "NEGATIVE GAMMA",
        "强负 Gamma": "STRONG NEGATIVE GAMMA",
    }.get(regime, regime.upper())


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


def render_gex_heatmap(snapshot: GexSnapshot, policy: HeatmapPolicy) -> bytes:
    from PIL import Image, ImageDraw

    width = 1080
    margin = 64
    header_height = 300
    footer_height = 120
    row_height = 54
    strikes = _selected_strikes(snapshot, policy.heatmap_strike_rows)
    expirations = snapshot.expirations[: policy.heatmap_expiration_columns]
    height = header_height + 120 + row_height * len(strikes) + footer_height
    image = Image.new("RGB", (width, height), "#090B0B")
    draw = ImageDraw.Draw(image)
    white = "#F3F1EA"
    muted = "#9AA5A0"
    green = "#86F7A8"
    red = "#D66A6A"
    panel = "#111615"
    grid = "#27302D"

    title_font = _font(50, bold=True)
    metric_font = _font(28, bold=True)
    body_font = _font(25)
    small_font = _font(21)
    draw.text((margin, 48), f"AXIS GEX · {snapshot.ticker}", fill=white, font=title_font)
    draw.text(
        (margin, 112),
        f"Spot ${snapshot.spot:,.2f}   ·   {_regime_label(snapshot.gamma_regime)}",
        fill=green if snapshot.net_gex >= 0 else red,
        font=metric_font,
    )
    draw.rounded_rectangle((margin, 168, width - margin, 276), radius=18, fill=panel)
    metrics = (
        ("ZERO", snapshot.zero_gamma),
        ("CALL WALL", snapshot.call_wall),
        ("PUT WALL", snapshot.put_wall),
    )
    column_width = (width - margin * 2) // 3
    for index, (label, value) in enumerate(metrics):
        x = margin + index * column_width + 22
        draw.text((x, 186), label, fill=muted, font=small_font)
        rendered = "—" if value is None else f"${value:,.2f}"
        draw.text((x, 220), rendered, fill=white, font=metric_font)

    table_top = header_height
    strike_width = 130
    total_width = 220
    heatmap_left = margin + strike_width
    heatmap_right = width - margin - total_width
    cell_width = max(70, (heatmap_right - heatmap_left) // max(1, len(expirations)))
    draw.text((margin, table_top + 16), "STRIKE", fill=muted, font=small_font)
    for index, expiry in enumerate(expirations):
        label = expiry.expiration.strftime("%m/%d")
        draw.text(
            (heatmap_left + index * cell_width + 10, table_top + 16),
            label,
            fill=muted,
            font=small_font,
        )
    draw.text((heatmap_right + 20, table_top + 16), "+GEX       -GEX", fill=muted, font=small_font)
    draw.line((margin, table_top + 58, width - margin, table_top + 58), fill=grid, width=2)

    expiration_maps = [
        {point.strike: point for point in expiration.by_strike} for expiration in expirations
    ]
    max_cell = max(
        (
            abs(point.net_gex)
            for expiration in expirations
            for point in expiration.by_strike
        ),
        default=1.0,
    )
    aggregate_map = {point.strike: point for point in snapshot.by_strike}
    spot_row = _nearest_strike(strikes, snapshot.spot)
    zero_row = _nearest_strike(strikes, snapshot.zero_gamma)
    marker_map: dict[float, list[str]] = {}
    for strike, label in (
        (spot_row, "S"),
        (zero_row, "ZG"),
        (snapshot.call_wall, "CW"),
        (snapshot.put_wall, "PW"),
    ):
        if strike is not None:
            marker_map.setdefault(strike, []).append(label)

    for row_index, strike in enumerate(strikes):
        y = table_top + 70 + row_index * row_height
        if strike in marker_map:
            draw.rounded_rectangle(
                (margin - 8, y - 4, width - margin + 8, y + row_height - 5),
                radius=10,
                outline=green if "S" in marker_map[strike] else "#6C7A75",
                width=2,
            )
        draw.text((margin, y + 8), f"{strike:g}", fill=white, font=body_font)
        markers = "/".join(marker_map.get(strike, ()))
        if markers:
            draw.text((margin + 76, y + 11), markers, fill=green, font=small_font)
        for column_index, expiration_map in enumerate(expiration_maps):
            point = expiration_map.get(strike)
            value = point.net_gex if point is not None else 0.0
            strength = min(1.0, abs(value) / max_cell)
            if value > 0:
                color = (18, int(65 + 115 * strength), int(46 + 62 * strength))
            elif value < 0:
                color = (int(70 + 120 * strength), 35, 45)
            else:
                color = (22, 29, 27)
            x = heatmap_left + column_index * cell_width
            draw.rounded_rectangle(
                (x + 3, y + 3, x + cell_width - 5, y + row_height - 8),
                radius=7,
                fill=color,
            )
        aggregate = aggregate_map.get(strike)
        positive = aggregate.call_gex if aggregate is not None else 0.0
        negative = aggregate.put_gex if aggregate is not None else 0.0
        draw.text(
            (heatmap_right + 18, y + 8),
            f"{_compact(positive):>7}  {_compact(negative):>7}",
            fill=white,
            font=small_font,
        )

    footer_y = height - footer_height + 18
    draw.line((margin, footer_y - 14, width - margin, footer_y - 14), fill=grid, width=2)
    draw.text(
        (margin, footer_y),
        "Green = positive GEX   ·   Red = negative GEX   ·   S / ZG / CW / PW markers",
        fill=muted,
        font=small_font,
    )
    draw.text(
        (margin, footer_y + 40),
        "Structure estimate only · not investment advice",
        fill="#78827E",
        font=small_font,
    )
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
