"""Small deterministic indicator library owned by AXIS Stock Analyst."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean


def ema_series(values: tuple[float, ...], period: int) -> tuple[float, ...]:
    if period <= 0 or len(values) < period:
        raise ValueError(f"need at least {period} values")
    seed = fmean(values[:period])
    multiplier = 2 / (period + 1)
    output = [seed]
    for value in values[period:]:
        output.append((value - output[-1]) * multiplier + output[-1])
    return tuple(output)


def rsi(values: tuple[float, ...], period: int = 14) -> float:
    if len(values) < period + 1:
        return 50.0
    changes = [right - left for left, right in zip(values, values[1:], strict=False)]
    recent = changes[-period:]
    gain = fmean(max(value, 0.0) for value in recent)
    loss = fmean(max(-value, 0.0) for value in recent)
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100 - 100 / (1 + gain / loss)


def macd_histogram(values: tuple[float, ...]) -> float:
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)
    if not fast or not slow:
        return 0.0
    aligned_fast = fast[-len(slow) :]
    macd = tuple(left - right for left, right in zip(aligned_fast, slow, strict=True))
    signal = ema_series(macd, 9)
    return macd[-1] - signal[-1] if signal else macd[-1]


def _ema_at_each_bar(values: tuple[float, ...], period: int) -> tuple[float, ...]:
    if not values:
        raise ValueError("EMA requires at least one value")
    multiplier = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(value * multiplier + output[-1] * (1 - multiplier))
    return tuple(output)


def macd_series(
    values: tuple[float, ...], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    if len(values) < slow + signal:
        raise ValueError(f"need at least {slow + signal} values for MACD")
    fast_line = _ema_at_each_bar(values, fast)
    slow_line = _ema_at_each_bar(values, slow)
    macd = tuple(left - right for left, right in zip(fast_line, slow_line, strict=True))
    signal_line = _ema_at_each_bar(macd, signal)
    histogram = tuple(value - average for value, average in zip(macd, signal_line, strict=True))
    return macd, signal_line, histogram


@dataclass(frozen=True, slots=True)
class PivotLevels:
    period: int
    support: float | None
    resistance: float | None
    previous_support: float | None
    previous_resistance: float | None


def confirmed_pivot_levels(bars: tuple[object, ...], period: int) -> PivotLevels:
    """Cosmos ZCZL pivot: usable only after ``period`` future bars confirm it."""
    if len(bars) < 2 * period + 1:
        return PivotLevels(period, None, None, None, None)
    supports: list[float] = []
    resistances: list[float] = []
    for index in range(period, len(bars) - period):
        window = bars[index - period : index + period + 1]
        if bars[index].low <= min(bar.low for bar in window):  # type: ignore[attr-defined]
            supports.append(float(bars[index].low))  # type: ignore[attr-defined]
        if bars[index].high >= max(bar.high for bar in window):  # type: ignore[attr-defined]
            resistances.append(float(bars[index].high))  # type: ignore[attr-defined]
    return PivotLevels(
        period,
        supports[-1] if supports else None,
        resistances[-1] if resistances else None,
        supports[-2] if len(supports) > 1 else None,
        resistances[-2] if len(resistances) > 1 else None,
    )


def average_true_range(
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    closes: tuple[float, ...],
    period: int = 14,
) -> float:
    if len(closes) < period + 1:
        return max(closes[-1] * 0.02, 0.01)
    ranges = []
    for index in range(1, len(closes)):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return fmean(ranges[-period:])


def period_return(values: tuple[float, ...], sessions: int) -> float | None:
    if len(values) < sessions + 1 or values[-sessions - 1] <= 0:
        return None
    return values[-1] / values[-sessions - 1] - 1


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
