"""AXIS rendering of the Cosmos-style five-minute SPY 0DTE terminal card."""

from __future__ import annotations

import math
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING

from app.market_intelligence.gex_explorer.models import GexByStrike
from app.services.spy_0dte_algorithm import SpyDataQuality

if TYPE_CHECKING:
    from app.services.spy_0dte_desk import Spy0dtePolicy, Spy0dteSnapshot


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = (
        "/System/Library/Fonts/STHeiti Medium.ttc"
        if bold
        else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _panel(draw, box: tuple[int, int, int, int], outline: str = "#233244") -> None:
    draw.rounded_rectangle(box, radius=18, fill="#0D151B", outline=outline, width=2)


def _level(value: float | None, decimals: int = 0) -> str:
    return "—" if value is None else f"{value:,.{decimals}f}"


def _score_color(value: int) -> str:
    if value >= 22:
        return "#27E39A"
    if value <= -22:
        return "#FF5E73"
    return "#F2C94C"


def _quality_label(quality: SpyDataQuality) -> str:
    return {
        SpyDataQuality.GOOD: "良好",
        SpyDataQuality.PARTIAL: "部分可用",
        SpyDataQuality.STALE: "历史快照",
        SpyDataQuality.DEGRADED: "不足",
    }[quality]


def _aggregate_chart_points(
    points: tuple[GexByStrike, ...],
    spot: float,
    strike_range: float,
    required_levels: tuple[float | None, ...],
) -> tuple[tuple[GexByStrike, ...], float]:
    available = [level for level in required_levels if level is not None]
    lower = min([spot - strike_range, *available])
    upper = max([spot + strike_range, *available])
    listed = sorted({point.strike for point in points})
    steps = [right - left for left, right in zip(listed, listed[1:], strict=False) if right > left]
    base_step = median(steps) if steps else 1.0
    visible_count = max(1, int((upper - lower) / base_step))
    bucket_size = base_step * max(1, math.ceil(visible_count / 31))
    buckets: defaultdict[float, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for point in points:
        if not lower <= point.strike <= upper:
            continue
        strike = round(point.strike / bucket_size) * bucket_size
        buckets[strike][0] += point.call_gex
        buckets[strike][1] += point.put_gex
        buckets[strike][2] += point.net_gex
    return (
        tuple(
            GexByStrike(strike, values[0], values[1], values[2])
            for strike, values in sorted(buckets.items(), reverse=True)
        ),
        bucket_size,
    )


def _nice_limit_m(value_m: float, padding_ratio: float) -> float:
    padded = max(value_m * max(padding_ratio, 1.0), 1.0)
    magnitude = 10 ** math.floor(math.log10(padded))
    normalized = padded / magnitude
    factor = 1 if normalized <= 1 else 2 if normalized <= 2 else 2.5 if normalized <= 2.5 else 5
    if normalized > 5:
        factor = 10
    return factor * magnitude


def _gex_m_label(value_m: float) -> str:
    decimals = 1 if abs(value_m) < 100 else 0
    return f"{value_m:+,.{decimals}f}M"


def _price_text(value: float) -> str:
    return f"{value:,.2f}" if not value.is_integer() else f"{value:,.0f}"


def render_spy_0dte_card(snapshot: Spy0dteSnapshot, policy: Spy0dtePolicy) -> bytes:
    """Render the formal 1400×1500 AXIS member card from one frozen snapshot."""

    from PIL import Image, ImageDraw

    width, height = 1400, 1500
    image = Image.new("RGB", (width, height), "#05090D")
    draw = ImageDraw.Draw(image)
    emerald = "#27E39A"
    red = "#FF5E73"
    yellow = "#F2C94C"
    white = "#F4F8F7"
    muted = "#90A4AE"
    cyan = "#64D8FF"

    for x in range(0, width, 70):
        draw.line((x, 0, x, height), fill="#081117", width=1)
    for y in range(0, height, 70):
        draw.line((0, y, width, y), fill="#081117", width=1)
    draw.ellipse((31, 30, 66, 65), outline=emerald, width=4)
    draw.ellipse((42, 41, 55, 54), fill=emerald)
    draw.text((82, 27), "AXIS | SPY GEX 5分钟监控", font=_font(28, True), fill=white)
    draw.text((82, 67), "0DTE · OI 加权 · 每 5 分钟", font=_font(17), fill=muted)
    draw.text(
        (1160, 29), snapshot.spot_timestamp.strftime("%H:%M ET"), font=_font(25, True), fill=white
    )
    draw.text((1186, 66), "5MIN UPDATE", font=_font(15, True), fill=emerald)
    if snapshot.stale:
        draw.rounded_rectangle((960, 27, 1135, 75), radius=14, fill="#493B08", outline=yellow)
        draw.text((985, 39), "历史快照", font=_font(18, True), fill=yellow)

    for box in (
        (50, 112, 365, 324),
        (385, 112, 700, 324),
        (720, 112, 1035, 324),
        (1055, 112, 1350, 324),
    ):
        _panel(draw, box)

    change_color = emerald if snapshot.day_change >= 0 else red
    draw.text((78, 136), "SPY 当前价格", font=_font(18, True), fill=muted)
    draw.text((78, 181), f"{snapshot.spot:,.2f}", font=_font(43, True), fill=white)
    draw.text(
        (78, 247),
        f"{snapshot.day_change:+.2f} ({snapshot.day_change_pct:+.2f}%)",
        font=_font(21, True),
        fill=change_color,
    )
    draw.text((78, 286), "涨跌比例：Moomoo SPY", font=_font(13), fill=muted)

    bias_color = _score_color(snapshot.display_score)
    draw.text((413, 136), "盘面方向（综合）", font=_font(18, True), fill=muted)
    draw.text((413, 179), f"{snapshot.display_score:+d}", font=_font(52, True), fill=bias_color)
    draw.text((550, 192), snapshot.structure_label, font=_font(23, True), fill=bias_color)
    delta = "首条更新" if snapshot.bias_delta is None else f"较上次 {snapshot.bias_delta:+d}"
    draw.text((413, 264), delta, font=_font(17), fill=muted)

    gamma_color = (
        red
        if "负" in snapshot.gamma_regime
        else emerald
        if "正" in snapshot.gamma_regime
        else yellow
    )
    draw.text((748, 136), "波动环境", font=_font(18, True), fill=muted)
    draw.text((748, 183), snapshot.gamma_regime, font=_font(27, True), fill=gamma_color)
    note_parts = snapshot.gamma_note.split("，", 1)
    draw.text((748, 240), note_parts[0], font=_font(16), fill=white)
    if len(note_parts) > 1:
        draw.text((748, 270), note_parts[1], font=_font(16), fill=muted)

    draw.text((1083, 136), "关键价位", font=_font(18, True), fill=muted)
    levels = (
        ("Call Wall", snapshot.call_wall, emerald),
        ("Zero Gamma", snapshot.gamma_flip, yellow),
        ("Put Wall", snapshot.put_wall, red),
        ("当前价格", snapshot.spot, white),
    )
    for index, (label, value, color) in enumerate(levels):
        y = 178 + index * 32
        draw.text((1083, y), label, font=_font(15), fill=muted)
        draw.text(
            (1260, y - 2),
            _level(value, 2 if label == "当前价格" else 0),
            font=_font(17, True),
            fill=color,
            anchor="ra",
        )

    draw.text((50, 348), "盘中剧本 · 相对优先级（不是胜率）", font=_font(21, True), fill=white)
    scenario_boxes = ((50, 384, 470, 604), (490, 384, 910, 604), (930, 384, 1350, 604))
    for index, (scenario, box, color) in enumerate(
        zip(snapshot.scenarios, scenario_boxes, (emerald, yellow, red), strict=True), start=1
    ):
        _panel(draw, box, color)
        draw.text(
            (box[0] + 24, box[1] + 22),
            f"情景 {index} · {scenario.name}",
            font=_font(21, True),
            fill=white,
        )
        draw.text(
            (box[2] - 25, box[1] + 20),
            f"{scenario.weight}%",
            font=_font(29, True),
            fill=color,
            anchor="ra",
        )
        draw.text((box[0] + 24, box[1] + 83), scenario.condition, font=_font(18), fill=white)
        draw.text((box[0] + 24, box[1] + 140), "目标", font=_font(16, True), fill=muted)
        draw.text(
            (box[0] + 88, box[1] + 135),
            f"{_price_text(scenario.targets[0])}  →  {_price_text(scenario.targets[1])}",
            font=_font(24, True),
            fill=color,
        )

    lower_boxes = ((50, 632, 425, 876), (445, 632, 875, 876), (895, 632, 1350, 876))
    for box in lower_boxes:
        _panel(draw, box)
    draw.text((76, 655), "价格动量（多周期）", font=_font(20, True), fill=white)
    for index, (label, value) in enumerate(
        (
            ("1分钟", snapshot.score_1m),
            ("5分钟", snapshot.score_5m),
            ("15分钟", snapshot.score_15m),
            ("1小时", snapshot.score_1h),
        )
    ):
        y = 707 + index * 38
        draw.text((76, y), label, font=_font(17), fill=muted)
        draw.text((255, y - 2), f"{value:+d}", font=_font(20, True), fill=_score_color(value))
        draw.rectangle((306, y + 4, 392, y + 14), fill="#17232A")
        center = 349
        extent = int(43 * abs(value) / 100)
        x0, x1 = (center, center + extent) if value >= 0 else (center - extent, center)
        draw.rectangle((x0, y + 4, x1, y + 14), fill=_score_color(value))

    upper = snapshot.scenarios[0].condition.replace("5分钟收盘", "")
    lower = snapshot.scenarios[2].condition.replace("5分钟收盘", "")
    draw.text((471, 655), "执行确认", font=_font(20, True), fill=white)
    draw.text((471, 713), "向上触发", font=_font(16, True), fill=emerald)
    draw.text((583, 709), upper, font=_font(20, True), fill=white)
    draw.text((471, 766), "向下触发", font=_font(16, True), fill=red)
    draw.text((583, 762), lower, font=_font(20, True), fill=white)
    draw.text((471, 824), "只认 5 分钟收盘；盘中刺穿不算突破", font=_font(15), fill=muted)

    draw.text((921, 655), "5 分钟前 → 现在", font=_font(20, True), fill=white)
    for index, change in enumerate(snapshot.changes[:6]):
        y = 700 + index * 27
        draw.text((921, y), change.label, font=_font(14), fill=muted)
        draw.text(
            (1074, y), f"{change.previous} → {change.current}", font=_font(14, True), fill=white
        )
        arrow_score = 1 if change.arrow == "↑" else -1 if change.arrow == "↓" else 0
        draw.text(
            (1312, y),
            change.arrow,
            font=_font(16, True),
            fill=_score_color(arrow_score),
            anchor="ra",
        )

    _panel(draw, (50, 904, 1350, 1438))
    chart_points, strike_bucket = _aggregate_chart_points(
        snapshot.gex.by_strike,
        snapshot.spot,
        policy.chart_strike_range_points,
        (snapshot.call_wall, snapshot.put_wall, snapshot.gamma_flip, snapshot.spot),
    )
    ordered_points = tuple(reversed(chart_points))
    peak = max((abs(point.net_gex) / 1e6 for point in ordered_points), default=0.0)
    axis_limit_m = _nice_limit_m(peak, policy.chart_axis_padding_ratio)
    positive_peak = max(
        (point for point in ordered_points if point.net_gex > 0),
        key=lambda point: point.net_gex,
        default=None,
    )
    negative_peak = min(
        (point for point in ordered_points if point.net_gex < 0),
        key=lambda point: point.net_gex,
        default=None,
    )
    chart_green, chart_red = "#58E62E", "#F04444"

    draw.text((76, 925), "0DTE GEX · SPY", font=_font(28, True), fill=white)
    draw.text(
        (76, 967),
        f"峰值 +GEX  {_price_text(positive_peak.strike)} · "
        f"{_gex_m_label(positive_peak.net_gex / 1e6)}"
        if positive_peak
        else "峰值 +GEX  —",
        font=_font(17, True),
        fill=chart_green,
    )
    draw.text(
        (455, 967),
        f"峰值 -GEX  {_price_text(negative_peak.strike)} · "
        f"{_gex_m_label(negative_peak.net_gex / 1e6)}"
        if negative_peak
        else "峰值 -GEX  —",
        font=_font(17, True),
        fill=chart_red,
    )
    draw.text((950, 967), "Strike 横轴 · 正向上 / 负向下", font=_font(14, True), fill=muted)
    draw.text(
        (1318, 968),
        f"{snapshot.spot_timestamp:%H:%M ET} · {_quality_label(snapshot.data_quality)}",
        font=_font(15, True),
        fill=yellow if snapshot.data_quality is not SpyDataQuality.GOOD else emerald,
        anchor="ra",
    )

    chart_left, chart_right = 155, 1318
    chart_top, chart_bottom = 1025, 1325
    zero_y = (chart_top + chart_bottom) / 2
    half_height = (chart_bottom - chart_top) / 2
    for value_m in (axis_limit_m, axis_limit_m / 2, 0.0, -axis_limit_m / 2, -axis_limit_m):
        y = zero_y - value_m / axis_limit_m * half_height
        draw.line(
            (chart_left, y, chart_right, y),
            fill="#A7ADB3" if value_m == 0 else "#172229",
            width=3 if value_m == 0 else 1,
        )
        draw.text(
            (chart_left - 14, y),
            "0" if value_m == 0 else f"{value_m:+,.0f}",
            font=_font(13, True),
            fill=white if value_m == 0 else muted,
            anchor="rm",
        )

    if ordered_points:
        step = (chart_right - chart_left) / len(ordered_points)
        bar_width = max(9.0, min(36.0, step * 0.62))
        named_labels: defaultdict[float, list[tuple[str, str]]] = defaultdict(list)
        for label, value, color in (
            ("CW", snapshot.call_wall, emerald),
            ("ZG", snapshot.gamma_flip, yellow),
            ("PW", snapshot.put_wall, red),
            ("SPOT", snapshot.spot, cyan),
        ):
            if value is not None:
                named_labels[round(value / strike_bucket) * strike_bucket].append((label, color))
        for index, point in enumerate(ordered_points):
            x = chart_left + step * (index + 0.5)
            value_m = point.net_gex / 1e6
            end_y = zero_y - value_m / axis_limit_m * half_height
            bar = (x - bar_width / 2, min(zero_y, end_y), x + bar_width / 2, max(zero_y, end_y))
            color = chart_green if value_m >= 0 else chart_red
            if abs(end_y - zero_y) >= 1:
                draw.rounded_rectangle(bar, radius=3, fill=color)
            if point is positive_peak or point is negative_peak:
                draw.rounded_rectangle(bar, radius=3, outline=white, width=2)
                draw.text(
                    (x, end_y - 7 if value_m > 0 else end_y + 7),
                    _gex_m_label(value_m),
                    font=_font(12, True),
                    fill=color,
                    anchor="mb" if value_m > 0 else "ma",
                )
            markers = named_labels.get(point.strike, [])
            strike_color = markers[0][1] if markers else muted
            draw.text(
                (x, 1339),
                _price_text(point.strike),
                font=_font(12, bool(markers)),
                fill=strike_color,
                anchor="ma",
            )
            if markers:
                draw.text(
                    (x, 1361),
                    "/".join(label for label, _ in markers),
                    font=_font(10, True),
                    fill=strike_color,
                    anchor="ma",
                )

    draw.text(
        ((chart_left + chart_right) / 2, 1404),
        "STRIKE · 纵轴为 Net 0DTE GEX (M)，红绿共用同一比例",
        font=_font(18, True),
        fill=muted,
        anchor="ma",
    )
    if snapshot.data_quality is not SpyDataQuality.GOOD and snapshot.warnings:
        draw.rounded_rectangle((50, 1450, 790, 1488), radius=12, fill="#3A2608")
        warning = snapshot.warnings[0][:45] + ("…" if len(snapshot.warnings[0]) > 45 else "")
        draw.text(
            (68, 1459),
            f"数据提醒：{_quality_label(snapshot.data_quality)} · {warning}",
            font=_font(14, True),
            fill=yellow,
        )
    draw.text((1040, 1458), "AXIS | Signals without the noise.", font=_font(15, True), fill=emerald)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
