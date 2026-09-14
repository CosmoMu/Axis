"""AXIS-native SPY adaptation of the committed Cosmos 5-minute GEX algorithm."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean, median, pstdev

from app.market_intelligence.gex_explorer.models import GexByStrike, GexIntradayBar


class SpyDataQuality(StrEnum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class SpyScenario:
    name: str
    weight: int
    condition: str
    targets: tuple[float, float]


@dataclass(frozen=True, slots=True)
class SpySnapshotChange:
    label: str
    previous: str
    current: str
    arrow: str


def bias_label(score: int) -> str:
    if score <= -72:
        return "强烈偏空"
    if score <= -50:
        return "偏空"
    if score <= -22:
        return "轻度偏空"
    if score <= 21:
        return "中性"
    if score <= 49:
        return "轻度偏多"
    if score <= 71:
        return "偏多"
    return "强烈偏多"


def _bucket(bars: tuple[GexIntradayBar, ...], minutes: int) -> tuple[GexIntradayBar, ...]:
    groups: defaultdict[object, list[GexIntradayBar]] = defaultdict(list)
    for bar in bars:
        local = bar.timestamp_et
        session_minutes = (local.hour * 60 + local.minute) - (9 * 60 + 30)
        if session_minutes < 0:
            continue
        bucket_start = session_minutes - session_minutes % minutes
        bucket_time = local.replace(
            hour=9 + (30 + bucket_start) // 60,
            minute=(30 + bucket_start) % 60,
            second=0,
            microsecond=0,
        )
        groups[bucket_time].append(bar)
    output = []
    for bucket_time in sorted(groups):
        group = sorted(groups[bucket_time], key=lambda item: item.timestamp_et)
        output.append(
            GexIntradayBar(
                timestamp_et=bucket_time,  # type: ignore[arg-type]
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(item.volume for item in group),
            )
        )
    return tuple(output)


def five_minute_bars(bars: tuple[GexIntradayBar, ...]) -> tuple[GexIntradayBar, ...]:
    return _bucket(bars, 5)


def _direction_score(bars: tuple[GexIntradayBar, ...], lookback: int) -> int:
    if len(bars) < 3:
        return 0
    sample = bars[-min(lookback, len(bars)) :]
    closes = [bar.close for bar in sample]
    returns = [
        right / left - 1 for left, right in zip(closes, closes[1:], strict=False) if left > 0
    ]
    if not returns:
        return 0
    cumulative = closes[-1] / closes[0] - 1 if closes[0] else 0
    volatility = max(pstdev(returns), 0.00005)
    momentum = math.tanh(cumulative / (volatility * math.sqrt(len(returns)))) * 70
    mean_close = fmean(closes)
    mean_range = max(fmean(bar.high - bar.low for bar in sample), closes[-1] * 0.0001)
    trend = math.tanh((closes[-1] - mean_close) / (mean_range * 2)) * 30
    return int(round(max(-100, min(100, momentum + trend))))


def calculate_timeframe_scores(bars: tuple[GexIntradayBar, ...]) -> dict[str, int]:
    return {
        "1m": _direction_score(_bucket(bars, 1), 15),
        "5m": _direction_score(_bucket(bars, 5), 12),
        "15m": _direction_score(_bucket(bars, 15), 8),
        "1h": _direction_score(_bucket(bars, 60), 6),
    }


def calculate_bias(
    scores: dict[str, int],
    spot: float,
    zero_gamma: float | None,
    call_wall: float | None,
    put_wall: float | None,
    quality: SpyDataQuality,
    *,
    timeframe_weights: dict[str, float],
    momentum_weight: float,
    location_weight: float,
) -> tuple[int, str]:
    momentum = sum(scores.get(name, 0) * weight for name, weight in timeframe_weights.items())
    location = 0.0
    if zero_gamma is not None:
        span = max(abs((call_wall or spot * 1.02) - (put_wall or spot * 0.98)), spot * 0.005)
        location = math.tanh((spot - zero_gamma) / (span / 3)) * 100
    score = int(round(momentum * momentum_weight + location * location_weight))
    cap = {
        SpyDataQuality.GOOD: 100,
        SpyDataQuality.PARTIAL: 71,
        SpyDataQuality.STALE: 49,
        SpyDataQuality.DEGRADED: 21,
    }[quality]
    score = max(-cap, min(cap, score))
    return score, bias_label(score)


def gamma_regime(
    net_gex: float,
    total_abs_gex: float,
    spot: float,
    zero_gamma: float | None,
    *,
    near_flip_ratio: float = 0.0065,
) -> tuple[str, str]:
    if zero_gamma is not None and abs(spot - zero_gamma) <= spot * near_flip_ratio:
        return "Zero Gamma 决胜区", "方向容易快速切换，先等价格离开中轴再跟随"
    ratio = net_gex / total_abs_gex if total_abs_gex else 0
    if ratio >= 0.12:
        return "正 Gamma 控场", "更容易来回震荡与均值回归，不追瞬间突破"
    if ratio <= -0.12:
        return "负 Gamma 加速区", "突破后更容易放大波动，只跟随 5 分钟收盘确认"
    return "Gamma 拉锯区", "正负力量接近平衡，先看 Call Wall 或 Put Wall 谁先失守"


def _strike_step(points: tuple[GexByStrike, ...]) -> float:
    values = sorted({point.strike for point in points})
    steps = [right - left for left, right in zip(values, values[1:], strict=False) if right > left]
    return median(steps) if steps else 1.0


def _nearest_grid(value: float, step: float) -> float:
    return round(value / step) * step


def _resolve_levels(
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
    points: tuple[GexByStrike, ...],
) -> tuple[float, float, tuple[float, float], tuple[float, float]]:
    step = max(_strike_step(points), 0.5)
    upper = (
        call_wall
        if call_wall is not None and call_wall > spot
        else _nearest_grid(spot + step, step)
    )
    lower = (
        put_wall if put_wall is not None and put_wall < spot else _nearest_grid(spot - step, step)
    )
    strikes = sorted(point.strike for point in points)
    higher = [strike for strike in strikes if strike > upper]
    lower_strikes = [strike for strike in reversed(strikes) if strike < lower]

    def distinct(values: list[float], anchor: float, direction: float) -> tuple[float, float]:
        selected: list[float] = []
        for value in values:
            if not selected or abs(value - selected[-1]) >= step:
                selected.append(value)
            if len(selected) == 2:
                break
        while len(selected) < 2:
            selected.append(anchor + direction * step * (len(selected) + 1))
        return selected[0], selected[1]

    return upper, lower, distinct(higher, upper, 1), distinct(lower_strikes, lower, -1)


def _integer_weights(values: tuple[float, float, float]) -> tuple[int, int, int]:
    total = sum(max(value, 1) for value in values)
    raw = [max(value, 1) / total * 100 for value in values]
    base = [math.floor(value) for value in raw]
    remainder = 100 - sum(base)
    order = sorted(range(3), key=lambda index: raw[index] - base[index], reverse=True)
    for index in order[:remainder]:
        base[index] += 1
    return base[0], base[1], base[2]


def build_scenarios(
    bias_score: int,
    regime: str,
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
    points: tuple[GexByStrike, ...],
) -> tuple[SpyScenario, SpyScenario, SpyScenario]:
    upper, lower, up_targets, down_targets = _resolve_levels(spot, call_wall, put_wall, points)
    up = 33 + max(bias_score, 0) * 0.32 - max(-bias_score, 0) * 0.12
    down = 29 + max(-bias_score, 0) * 0.32 - max(bias_score, 0) * 0.12
    rejection = 38 - abs(bias_score) * 0.12 + (10 if regime.startswith("正 Gamma") else -5)
    up_weight, reject_weight, down_weight = _integer_weights((up, rejection, down))
    precision = 2 if _strike_step(points) < 1 else 0
    fmt = f",.{precision}f"
    return (
        SpyScenario(
            "上破延伸",
            up_weight,
            f"5分钟收盘站稳 {format(upper, fmt)}",
            up_targets,
        ),
        SpyScenario(
            "上沿拒绝",
            reject_weight,
            f"{format(upper, fmt)} 受阻后回落",
            (_nearest_grid(spot, _strike_step(points)), lower),
        ),
        SpyScenario(
            "下破加速",
            down_weight,
            f"5分钟收盘跌破 {format(lower, fmt)}",
            down_targets,
        ),
    )


def arrow(previous: float, current: float, tolerance: float = 0.01) -> str:
    if current > previous + tolerance:
        return "↑"
    if current < previous - tolerance:
        return "↓"
    return "—"
