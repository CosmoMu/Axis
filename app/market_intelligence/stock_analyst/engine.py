"""Deterministic daily-stock method adapted into AXIS Stock Analyst.

The engine owns no Discord, database, or external-service behavior. Volume-at-price
and money-flow values are explicitly OHLCV proxies. Scenario weights are relative
model weights, never historical win rates or calibrated probabilities.
"""

from __future__ import annotations

from statistics import fmean

from app.market_intelligence.stock_analyst.indicators import (
    average_true_range,
    clamp,
    ema_series,
    macd_histogram,
    period_return,
    rsi,
)
from app.market_intelligence.stock_analyst.models import (
    DailyBar,
    MoneyFlowProxy,
    PriceLevel,
    StockAnalysis,
    StockScenario,
    VolumeProfileNode,
)

SECTOR_ETF_BY_TICKER = {
    "NVDA": "SMH",
    "AMD": "SMH",
    "AVGO": "SMH",
    "TSM": "SMH",
    "AAPL": "XLK",
    "ORCL": "XLK",
    "MSFT": "IGV",
    "PLTR": "IGV",
    "META": "XLC",
    "GOOGL": "XLC",
    "NFLX": "XLC",
    "AMZN": "XLY",
    "TSLA": "XLY",
    "JPM": "XLF",
    "BAC": "XLF",
    "COIN": "XLF",
    "XOM": "XLE",
    "CVX": "XLE",
    "LLY": "XLV",
    "UNH": "XLV",
    "CAT": "XLI",
    "GE": "XLI",
    "SPY": "SPY",
    "QQQ": "QQQ",
    "IWM": "IWM",
}


def infer_sector_etf(ticker: str) -> str:
    return SECTOR_ETF_BY_TICKER.get(ticker.upper(), "SPY")


def _volume_profile(bars: tuple[DailyBar, ...], bins: int = 24) -> tuple[VolumeProfileNode, ...]:
    selected = bars[-120:]
    floor = min(bar.low for bar in selected)
    ceiling = max(bar.high for bar in selected)
    step = max((ceiling - floor) / bins, ceiling * 0.0001)
    volumes = [0.0] * bins
    for bar in selected:
        typical = (bar.high + bar.low + bar.close) / 3
        index = min(bins - 1, max(0, int((typical - floor) / step)))
        volumes[index] += max(bar.volume, 0.0)
    total = sum(volumes) or 1.0
    ranks = {
        index: rank
        for rank, index in enumerate(
            sorted(range(bins), key=lambda item: volumes[item], reverse=True),
            start=1,
        )
    }
    return tuple(
        VolumeProfileNode(
            price_low=floor + index * step,
            price_high=floor + (index + 1) * step,
            midpoint=floor + (index + 0.5) * step,
            volume=volume,
            volume_share=volume / total,
            rank=ranks[index],
        )
        for index, volume in enumerate(volumes)
    )


def _value_area(nodes: tuple[VolumeProfileNode, ...]) -> tuple[float, float, float]:
    poc = max(nodes, key=lambda item: item.volume)
    selected = []
    running = 0.0
    for node in sorted(nodes, key=lambda item: item.volume, reverse=True):
        selected.append(node)
        running += node.volume_share
        if running >= 0.70:
            break
    return (
        poc.midpoint,
        min(item.price_low for item in selected),
        max(item.price_high for item in selected),
    )


def _pivot_candidates(bars: tuple[DailyBar, ...]) -> list[tuple[float, str, float]]:
    candidates: list[tuple[float, str, float]] = []
    recent = bars[-100:]
    for radius, strength in ((3, 0.65), (6, 0.80), (13, 1.0)):
        for index in range(radius, len(recent) - radius):
            window = recent[index - radius : index + radius + 1]
            bar = recent[index]
            if bar.low == min(item.low for item in window):
                candidates.append((bar.low, "SUPPORT", strength))
            if bar.high == max(item.high for item in window):
                candidates.append((bar.high, "RESISTANCE", strength))
    return candidates


def _levels(
    bars: tuple[DailyBar, ...],
    nodes: tuple[VolumeProfileNode, ...],
    current: float,
) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
    candidates = _pivot_candidates(bars)
    candidates.extend(
        (node.midpoint, "SUPPORT" if node.midpoint <= current else "RESISTANCE", 0.55)
        for node in nodes
        if node.rank <= 5
    )
    clustered: list[dict[str, object]] = []
    tolerance = max(current * 0.006, 0.01)
    for price, kind, strength in sorted(candidates):
        match = next(
            (
                item
                for item in clustered
                if item["kind"] == kind and abs(float(item["price"]) - price) <= tolerance
            ),
            None,
        )
        if match is None:
            clustered.append(
                {"price": price, "kind": kind, "strength": strength, "sources": {"PIVOT/VAP"}}
            )
        else:
            match["price"] = (float(match["price"]) + price) / 2
            match["strength"] = min(1.0, float(match["strength"]) + strength * 0.25)
    supports = sorted(
        (
            PriceLevel(
                round(float(item["price"]), 4),
                "SUPPORT",
                round(float(item["strength"]), 3),
                tuple(sorted(item["sources"])),
            )
            for item in clustered
            if item["kind"] == "SUPPORT" and float(item["price"]) < current
        ),
        key=lambda item: item.price,
        reverse=True,
    )[:4]
    resistance = sorted(
        (
            PriceLevel(
                round(float(item["price"]), 4),
                "RESISTANCE",
                round(float(item["strength"]), 3),
                tuple(sorted(item["sources"])),
            )
            for item in clustered
            if item["kind"] == "RESISTANCE" and float(item["price"]) > current
        ),
        key=lambda item: item.price,
    )[:4]
    return tuple(supports), tuple(resistance)


def _money_flow(bars: tuple[DailyBar, ...]) -> MoneyFlowProxy:
    recent = bars[-20:]
    total_volume = sum(max(bar.volume, 0.0) for bar in recent) or 1.0
    signed = sum(
        max(bar.volume, 0.0) * (1 if bar.close > bar.open else -1 if bar.close < bar.open else 0)
        for bar in recent
    )
    signed_ratio = signed / total_volume
    location = fmean(
        (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else 0.5
        for bar in recent
    )
    score = round(clamp(50 + signed_ratio * 35 + (location - 0.5) * 40, 0, 100), 1)
    label = "偏流入" if score >= 58 else "偏流出" if score <= 42 else "中性"
    return MoneyFlowProxy(
        score=score,
        label=label,
        signed_volume_ratio=round(signed_ratio, 5),
        close_location_20=round(location, 5),
        note="OHLCV 方向成交量与收盘位置代理；不是逐笔主动买卖、暗池或真实资金账户数据。",
    )


def _sector_strength(
    sector_bars: tuple[DailyBar, ...] | None,
    benchmark_bars: tuple[DailyBar, ...] | None,
) -> tuple[float | None, str | None]:
    if not sector_bars or not benchmark_bars:
        return None, None
    sector = tuple(bar.close for bar in sector_bars)
    benchmark = tuple(bar.close for bar in benchmark_bars)
    relative_5 = (period_return(sector, 5) or 0) - (period_return(benchmark, 5) or 0)
    relative_20 = (period_return(sector, 20) or 0) - (period_return(benchmark, 20) or 0)
    absolute_5 = period_return(sector, 5) or 0
    score = round(clamp(50 + relative_5 * 350 + relative_20 * 180 + absolute_5 * 120, 0, 100), 1)
    phase = (
        "LEADING"
        if score >= 65
        else "IMPROVING"
        if score >= 55
        else "NEUTRAL"
        if score > 45
        else "LAGGING"
    )
    return score, phase


def _scenario_levels(
    current: float,
    atr: float,
    supports: tuple[PriceLevel, ...],
    resistance: tuple[PriceLevel, ...],
    trend_score: float,
) -> tuple[StockScenario, ...]:
    support = supports[0].price if supports else current - atr * 1.5
    lower_support = supports[1].price if len(supports) > 1 else support - atr * 1.5
    first_resistance = resistance[0].price if resistance else current + atr * 1.5
    second_resistance = resistance[1].price if len(resistance) > 1 else first_resistance + atr * 1.5
    bullish = clamp(25 + (trend_score - 50) * 0.8, 15, 55)
    bearish = clamp(25 + (50 - trend_score) * 0.8, 15, 55)
    balanced = 100 - bullish - bearish
    raw = [bullish, balanced, bearish]
    total = sum(raw)
    weights = [round(value / total * 100, 1) for value in raw]
    weights[1] = round(100 - weights[0] - weights[2], 1)
    return (
        StockScenario(
            "TREND_CONTINUATION",
            "趋势延续",
            weights[0],
            f"站稳 ${first_resistance:,.2f}",
            (round(first_resistance, 4), round(second_resistance, 4)),
            round(support, 4),
            "趋势与结构位保持一致时，向上测试压力层。",
        ),
        StockScenario(
            "STRUCTURAL_PULLBACK",
            "结构回踩",
            weights[1],
            f"回踩 ${support:,.2f} 附近观察承接",
            (round(support, 4), round(first_resistance, 4)),
            round(lower_support, 4),
            "价格先向支撑/成交密集区均值回归，再决定方向。",
        ),
        StockScenario(
            "SUPPORT_BREAKDOWN",
            "支撑失守",
            weights[2],
            f"有效跌破 ${support:,.2f}",
            (round(lower_support, 4),),
            round(first_resistance, 4),
            "支撑失守时，负向波动可能向下一结构层扩张。",
        ),
    )


def analyze_stock(
    ticker: str,
    bars: tuple[DailyBar, ...],
    *,
    sector_etf: str,
    sector_bars: tuple[DailyBar, ...] | None = None,
    benchmark_bars: tuple[DailyBar, ...] | None = None,
) -> StockAnalysis:
    if len(bars) < 50:
        raise ValueError("AXIS Stock Analyst requires at least 50 daily bars")
    ordered = tuple(sorted(bars, key=lambda item: item.timestamp))
    closes = tuple(bar.close for bar in ordered)
    highs = tuple(bar.high for bar in ordered)
    lows = tuple(bar.low for bar in ordered)
    current = closes[-1]
    ema20 = ema_series(closes, 20)[-1]
    ema50 = ema_series(closes, 50)[-1]
    ema200 = ema_series(closes, 200)[-1] if len(closes) >= 200 else ema50
    rsi14 = rsi(closes)
    macd = macd_histogram(closes)
    atr14 = average_true_range(highs, lows, closes)
    score = 50.0
    score += 10 if current >= ema20 else -10
    score += 9 if ema20 >= ema50 else -9
    score += 8 if ema50 >= ema200 else -8
    score += clamp((rsi14 - 50) * 0.35, -10, 10)
    score += clamp(macd / max(atr14, 0.01) * 18, -8, 8)
    history_mode = "STANDARD" if len(ordered) >= 120 else "LIMITED"
    if history_mode == "LIMITED":
        # New listings have enough data for EMA50/RSI/MACD and structural pivots,
        # but not enough history to justify the same conviction as established names.
        score = 50 + (score - 50) * 0.65
    trend_score = round(clamp(score, 0, 100), 1)
    trend_label = (
        "趋势偏多" if trend_score >= 60 else "趋势偏空" if trend_score <= 40 else "震荡平衡"
    )
    nodes = _volume_profile(ordered)
    poc, value_low, value_high = _value_area(nodes)
    supports, resistance = _levels(ordered, nodes, current)
    flow = _money_flow(ordered)
    sector_score, sector_phase = _sector_strength(sector_bars, benchmark_bars)
    unavailable = []
    if sector_score is None:
        unavailable.append("sector_relative_strength")
    if history_mode == "LIMITED":
        unavailable.append("limited_history_under_120_sessions")
    scenarios = _scenario_levels(current, atr14, supports, resistance, trend_score)
    return StockAnalysis(
        ticker=ticker.upper(),
        as_of=ordered[-1].timestamp.date(),
        data_timestamp=ordered[-1].timestamp,
        history_sessions=len(ordered),
        history_mode=history_mode,
        current_price=round(current, 4),
        trend_score=trend_score,
        trend_label=trend_label,
        indicator_scores=(
            ("RSI14", round(rsi14, 2)),
            ("MACD_ATR", round(macd / max(atr14, 0.01), 4)),
            ("EMA20_DISTANCE_PCT", round((current / ema20 - 1) * 100, 3)),
            ("EMA50_DISTANCE_PCT", round((current / ema50 - 1) * 100, 3)),
        ),
        support_levels=supports,
        resistance_levels=resistance,
        volume_profile_nodes=nodes,
        point_of_control=round(poc, 4),
        value_area_low=round(value_low, 4),
        value_area_high=round(value_high, 4),
        money_flow=flow,
        sector_etf=sector_etf,
        sector_strength_score=sector_score,
        sector_rotation_phase=sector_phase,
        scenarios=scenarios,
        unavailable_data=tuple(unavailable),
        methodology_note=(
            "AXIS Stock Analyst：日 K 趋势、EMA/RSI/MACD、确认拐点、OHLCV 成交量分布与"
            "板块相对强度。资金流与筹码峰为 OHLCV 代理；情景百分比为相对模型权重，"
            "不是历史胜率或承诺。"
            + (
                f" 当前仅有 {len(ordered)} 个交易日，属于新股有限历史模式，趋势分数已向中性收缩。"
                if history_mode == "LIMITED"
                else ""
            )
        ),
    )
