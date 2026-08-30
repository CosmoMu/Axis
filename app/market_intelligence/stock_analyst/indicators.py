"""Small deterministic indicator library owned by AXIS Stock Analyst."""

from __future__ import annotations

from statistics import fmean


def ema_series(values: tuple[float, ...], period: int) -> tuple[float, ...]:
    if period <= 0 or len(values) < period:
        return ()
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
