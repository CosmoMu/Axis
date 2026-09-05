"""Exact explainable sector-rotation overlay ported from Cosmos Stock Analyst v0.1."""

from __future__ import annotations

from dataclasses import dataclass

from app.market_intelligence.stock_analyst.models import DailyBar

ROTATION_GROUPS = {
    "broad": ("QQQ", "IWM", "SPY"),
    "growth": ("SMH", "IGV", "XLK", "XLC", "XLY"),
    "cyclical": ("XLI", "XLF", "XLE"),
    "defensive": ("XLV", "XLP", "XLU"),
}


def rotation_peers(sector_etf: str) -> tuple[str, ...]:
    return next(
        (members for members in ROTATION_GROUPS.values() if sector_etf in members), (sector_etf,)
    )


@dataclass(frozen=True, slots=True)
class SectorRotationResult:
    sector_etf: str
    benchmark: str
    strength_score: float
    alignment_score: float
    label: str
    relative_return_5d: float
    relative_return_20d: float
    rotation_phase: str
    rotation_rank: int
    rotation_group_size: int
    leader_etf: str
    leadership_spread_5d: float
    reason: str


def _return(bars: tuple[DailyBar, ...], sessions: int) -> float:
    if len(bars) < sessions + 1 or bars[-sessions - 1].close <= 0:
        raise ValueError("sector rotation history insufficient")
    return bars[-1].close / bars[-sessions - 1].close - 1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def analyze_sector_rotation(
    sector_etf: str,
    sector_bars: tuple[DailyBar, ...],
    benchmark: str,
    benchmark_bars: tuple[DailyBar, ...],
    direction: str,
    peer_bars: dict[str, tuple[DailyBar, ...]] | None = None,
) -> SectorRotationResult:
    sector_5d, sector_20d = _return(sector_bars, 5), _return(sector_bars, 20)
    benchmark_5d, benchmark_20d = _return(benchmark_bars, 5), _return(benchmark_bars, 20)
    relative_5d, relative_20d = sector_5d - benchmark_5d, sector_20d - benchmark_20d
    average_20d = sum(bar.close for bar in sector_bars[-20:]) / 20
    available = dict(peer_bars or {})
    available[sector_etf] = sector_bars
    momentum: dict[str, float] = {}
    peer_5d: dict[str, float] = {}
    peer_1d: dict[str, float] = {}
    for ticker, bars in available.items():
        try:
            one, five, twenty = _return(bars, 1), _return(bars, 5), _return(bars, 20)
        except ValueError:
            continue
        peer_1d[ticker], peer_5d[ticker] = one, five
        momentum[ticker] = one * 0.20 + five * 0.50 + twenty * 0.30
    ordered = sorted(momentum, key=momentum.get, reverse=True)  # type: ignore[arg-type]
    rank = ordered.index(sector_etf) + 1 if sector_etf in ordered else 1
    size = max(1, len(ordered))
    leader = ordered[0] if ordered else sector_etf
    spread = sector_5d - peer_5d.get(leader, sector_5d)
    acceleration = peer_1d.get(sector_etf, 0.0) - sector_5d / 5
    phase = (
        "LEADING"
        if rank == 1 and sector_5d > 0
        else "ROTATING IN"
        if rank <= max(2, size // 2) and acceleration > 0.002
        else "FOLLOW-THROUGH"
        if sector_5d > 0 and acceleration >= -0.002
        else "ROTATING OUT"
        if sector_5d > 0
        else "LAGGING"
    )
    strength = 50.0
    strength += _clamp(relative_5d * 300, -15, 15)
    strength += _clamp(relative_20d * 150, -15, 15)
    strength += _clamp(sector_5d * 150, -10, 10)
    strength += 10 if sector_bars[-1].close >= average_20d else -10
    if size > 1:
        strength += _clamp(((size + 1) / 2 - rank) * 4, -8, 8)
    strength = round(_clamp(strength, 0, 100), 1)
    alignment = round(strength if direction == "CALL" else 100 - strength, 1)
    label = (
        "LEADING"
        if strength >= 65
        else "IMPROVING"
        if strength >= 55
        else "NEUTRAL"
        if strength > 45
        else "WEAKENING"
        if strength > 35
        else "LAGGING"
    )
    relation = "支持" if alignment >= 55 else "暂不支持"
    direction_word = "看涨" if direction == "CALL" else "看跌"
    return SectorRotationResult(
        sector_etf,
        benchmark,
        strength,
        alignment,
        label,
        relative_5d,
        relative_20d,
        phase,
        rank,
        size,
        leader,
        spread,
        f"{sector_etf} 在轮动组中排名 {rank}/{size}，当前领先者为 {leader}；"
        f"相对 {benchmark} 的 5 日/20 日强弱为 "
        f"{relative_5d:+.1%}/{relative_20d:+.1%}，因此{relation}{direction_word}判断。",
    )
