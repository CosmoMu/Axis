"""Deterministic Cosmos Stock Analyst v0.1 strategy, ported into AXIS.

This module deliberately owns no network, Discord, database, LLM, or broker behavior.
The formulas match the recovered Cosmos implementation. OHLCV flow and volume-at-price
are proxies; scenario percentages are model weights, not calibrated probabilities.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from datetime import date

from app.market_intelligence.stock_analyst.indicators import (
    PivotLevels,
    confirmed_pivot_levels,
    ema_series,
    macd_series,
)
from app.market_intelligence.stock_analyst.models import (
    DailyBar,
    MoneyFlowProxy,
    PriceLevel,
    StockAnalysis,
    StockScenario,
    VolumeProfileNode,
)
from app.market_intelligence.stock_analyst.sector_rotation import analyze_sector_rotation

STRATEGY_VERSION = "COSMOS_STOCK_ANALYST_V0_1"
MINIMUM_ANALYSIS_SESSIONS = 100

SECTOR_ETF_BY_TICKER = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "IWM": "IWM",
    "SMH": "SMH",
    "NVDA": "SMH",
    "AMD": "SMH",
    "AVGO": "SMH",
    "TSM": "SMH",
    "MSFT": "IGV",
    "AAPL": "XLK",
    "ORCL": "XLK",
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
    "MSTR": "QQQ",
}
SECTOR_NAMES_ZH: Mapping[str, str] = {
    "SPY": "美股大盘",
    "QQQ": "纳斯达克成长",
    "IWM": "小盘股",
    "SMH": "半导体",
    "IGV": "软件",
    "XLK": "信息技术",
    "XLC": "通信服务",
    "XLY": "可选消费",
    "XLF": "金融",
    "XLE": "能源",
    "XLV": "医疗保健",
    "XLI": "工业",
    "XLP": "必选消费",
    "XLU": "公用事业",
    "XLB": "基础材料",
    "XLRE": "房地产",
}
SECTOR_COMPANY_CANDIDATES: Mapping[str, tuple[str, ...]] = {
    "SPY": ("MSFT", "NVDA", "AAPL", "AMZN", "META", "GOOGL", "AVGO", "JPM"),
    "QQQ": ("MSFT", "NVDA", "AAPL", "AMZN", "META", "GOOGL", "AVGO", "TSLA"),
    "IWM": (),
    "SMH": ("NVDA", "AMD", "AVGO", "TSM", "MU", "ASML", "AMAT", "LRCX", "QCOM"),
    "IGV": ("MSFT", "ORCL", "CRM", "NOW", "PLTR", "ADBE", "CRWD", "PANW"),
    "XLK": ("AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "AMD", "IBM"),
    "XLC": ("META", "GOOGL", "NFLX", "DIS", "TMUS", "T", "VZ", "WBD"),
    "XLY": ("AMZN", "TSLA", "HD", "MCD", "BKNG", "LOW", "SBUX", "NKE"),
    "XLF": ("JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "COIN"),
    "XLE": ("XOM", "CVX", "COP", "EOG", "SLB", "OXY"),
    "XLV": ("LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "AMGN", "ISRG"),
    "XLI": ("GE", "CAT", "RTX", "BA", "ETN", "UBER", "UNP", "HON"),
    "XLP": ("WMT", "COST", "PG", "KO", "PEP", "PM", "MO"),
    "XLU": ("NEE", "SO", "DUK", "CEG", "VST", "AEP"),
    "XLB": ("LIN", "SHW", "FCX", "NEM", "APD", "ECL", "CTVA", "DOW"),
    "XLRE": ("PLD", "AMT", "EQIX", "WELL", "SPG", "O", "PSA", "CCI"),
}


def infer_sector_etf(ticker: str) -> str:
    symbol = ticker.strip().upper()
    return SECTOR_ETF_BY_TICKER.get(symbol, symbol if symbol in SECTOR_NAMES_ZH else "SPY")


def sector_leader_candidates(sector_etf: str) -> tuple[str, ...]:
    return SECTOR_COMPANY_CANDIDATES.get(sector_etf.strip().upper(), ())


def _daily_bars(bars: tuple[DailyBar, ...], as_of: date | None) -> tuple[DailyBar, ...]:
    by_date: dict[date, DailyBar] = {}
    for bar in sorted(bars, key=lambda item: item.timestamp):
        session = bar.timestamp.date()
        if (as_of is None or session <= as_of) and min(bar.open, bar.high, bar.low, bar.close) > 0:
            by_date[session] = bar
    return tuple(by_date[session] for session in sorted(by_date))


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _period_return(bars: tuple[DailyBar, ...], sessions: int) -> float:
    if len(bars) < sessions + 1 or bars[-sessions - 1].close <= 0:
        raise ValueError(f"need {sessions + 1} bars")
    return bars[-1].close / bars[-sessions - 1].close - 1


def _atr(bars: tuple[DailyBar, ...], period: int = 14) -> float:
    ranges = [
        max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        for previous, current in zip(bars[-period - 1 : -1], bars[-period:], strict=True)
    ]
    return statistics.fmean(ranges)


def build_volume_profile_proxy(
    bars: tuple[DailyBar, ...], *, bins: int = 24, sessions: int = 80
) -> tuple[tuple[VolumeProfileNode, ...], float, float, float]:
    """Cosmos v0.1: distribute each daily bar's volume uniformly over its high/low bins."""
    if not 8 <= bins <= 100:
        raise ValueError("volume profile bins must be within 8..100")
    window = bars[-sessions:]
    if len(window) < 20:
        raise ValueError("volume profile requires at least 20 bars")
    low, high = min(bar.low for bar in window), max(bar.high for bar in window)
    if high <= low:
        raise ValueError("volume profile needs a positive price range")
    step = (high - low) / bins
    volumes = [0.0] * bins
    for bar in window:
        start = max(0, min(bins - 1, int((bar.low - low) / step)))
        end = max(0, min(bins - 1, int((bar.high - low) / step)))
        count = end - start + 1
        if count <= 0 or bar.volume <= 0:
            continue
        allocation = bar.volume / count
        for index in range(start, end + 1):
            volumes[index] += allocation
    total = sum(volumes)
    if total <= 0:
        raise ValueError("volume profile requires positive OHLCV volume")
    poc_index = max(range(bins), key=volumes.__getitem__)
    left = right = poc_index
    cumulative = volumes[poc_index]
    while cumulative / total < 0.70 and (left > 0 or right < bins - 1):
        left_volume = volumes[left - 1] if left > 0 else -1.0
        right_volume = volumes[right + 1] if right < bins - 1 else -1.0
        if right_volume > left_volume:
            right += 1
            cumulative += volumes[right]
        else:
            left -= 1
            cumulative += volumes[left]
    ranks = {
        index: rank
        for rank, index in enumerate(sorted(range(bins), key=volumes.__getitem__, reverse=True), 1)
    }
    nodes = tuple(
        VolumeProfileNode(
            round(low + index * step, 6),
            round(low + (index + 1) * step, 6),
            round(low + (index + 0.5) * step, 6),
            round(volumes[index], 4),
            round(volumes[index] / total, 6),
            ranks[index],
        )
        for index in range(bins)
    )
    return (
        nodes,
        round(low + (poc_index + 0.5) * step, 6),
        round(low + left * step, 6),
        round(low + (right + 1) * step, 6),
    )


def analyze_money_flow_proxy(bars: tuple[DailyBar, ...], sessions: int = 20) -> MoneyFlowProxy:
    window = bars[-sessions:]
    if len(window) < sessions:
        raise ValueError(f"money-flow proxy requires {sessions} bars")
    total_volume = sum(max(bar.volume, 0.0) for bar in window)
    if total_volume <= 0:
        return MoneyFlowProxy(
            50.0, "NEUTRAL", 0.0, 0.0, 0.0, 0.5, "成交量不可用；资金流向保持中性，未使用伪造数据。"
        )
    locations: list[float] = []
    signed_volume = obv_change = 0.0
    for index, bar in enumerate(window):
        location = (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else 0.5
        locations.append(location)
        signed_volume += (location * 2 - 1) * max(bar.volume, 0.0)
        if index > 0:
            if bar.close > window[index - 1].close:
                obv_change += max(bar.volume, 0.0)
            elif bar.close < window[index - 1].close:
                obv_change -= max(bar.volume, 0.0)
    signed_ratio, obv_slope = signed_volume / total_volume, obv_change / total_volume
    location = statistics.fmean(locations)
    score = _clamp(50 + signed_ratio * 28 + obv_slope * 15 + (location - 0.5) * 28)
    label = "ACCUMULATION" if score >= 60 else "DISTRIBUTION" if score <= 40 else "NEUTRAL"
    return MoneyFlowProxy(
        round(score, 1),
        label,
        round(signed_ratio, 4),
        round(signed_ratio, 4),
        round(obv_slope, 4),
        round(location, 4),
        "OHLCV 资金流代理：按 K 线收盘位置分配成交量，并结合 OBV 方向；"
        "不代表逐笔主动买卖、暗池净流入或真实机构持仓。",
    )


def _hlx_score(
    price: float,
    up1: tuple[float, ...],
    low1: tuple[float, ...],
    up2: tuple[float, ...],
    low2: tuple[float, ...],
) -> float:
    score = 50.0
    score += 20 if up1[-1] > up2[-1] and low1[-1] > low2[-1] else -20
    score += 20 if price > up1[-1] else 8 if price >= low1[-1] else -20 if price < low2[-1] else 0
    score += 10 if up1[-1] > up1[-2] and low1[-1] > low1[-2] else -10
    return _clamp(score)


def _zczl_score(price: float, levels: tuple[PivotLevels, ...]) -> float:
    score = 50.0
    for level in levels:
        weight = {3: 7.0, 6: 10.0, 13: 14.0}[level.period]
        if level.support is not None:
            score += weight if price >= level.support else -weight
            if level.previous_support is not None:
                score += weight / 3 if level.support >= level.previous_support else -weight / 3
        if level.resistance is not None and price >= level.resistance:
            score += weight / 2
    return _clamp(score)


def _macd_score(closes: tuple[float, ...]) -> float:
    macd, signal, histogram = macd_series(closes)
    score = 50.0
    score += 20 if macd[-1] >= signal[-1] else -20
    score += 15 if histogram[-1] >= 0 else -15
    score += 15 if histogram[-1] >= histogram[-2] else -15
    return _clamp(score)


def _rsi14(closes: tuple[float, ...]) -> float:
    differences = [closes[index] - closes[index - 1] for index in range(-14, 0)]
    gain = statistics.fmean(max(value, 0.0) for value in differences)
    loss = statistics.fmean(max(-value, 0.0) for value in differences)
    if loss <= 0:
        return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def _structure_score(bars: tuple[DailyBar, ...]) -> float:
    closes = [bar.close for bar in bars]
    average_20, average_50 = statistics.fmean(closes[-20:]), statistics.fmean(closes[-50:])
    score = 50.0
    score += 15 if closes[-1] >= average_20 else -15
    score += 15 if average_20 >= average_50 else -15
    score += 10 if _period_return(bars, 20) >= 0 else -10
    score += 10 if _period_return(bars, 60) >= 0 else -10
    return _clamp(score)


def _cluster_levels(
    current: float, atr: float, candidates: list[tuple[float, float, str]]
) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
    tolerance = max(atr * 0.35, current * 0.0025, 0.01)
    clusters: list[list[tuple[float, float, str]]] = []
    for candidate in sorted(candidates):
        if (
            clusters
            and abs(candidate[0] - statistics.fmean(item[0] for item in clusters[-1])) <= tolerance
        ):
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])
    supports: list[PriceLevel] = []
    resistances: list[PriceLevel] = []
    for cluster in clusters:
        total = sum(item[1] for item in cluster)
        price = sum(item[0] * item[1] for item in cluster) / total
        sources = tuple(dict.fromkeys(item[2] for item in cluster))
        strength = _clamp(max(item[1] for item in cluster) + 8 * (len(sources) - 1))
        kind = "SUPPORT" if price <= current else "RESISTANCE"
        (supports if kind == "SUPPORT" else resistances).append(
            PriceLevel(round(price, 6), kind, round(strength, 1), sources)
        )
    supports.sort(key=lambda item: item.price, reverse=True)
    resistances.sort(key=lambda item: item.price)
    return tuple(supports[:5]), tuple(resistances[:5])


def _price_levels(
    bars: tuple[DailyBar, ...],
    pivots: tuple[PivotLevels, ...],
    channels: tuple[tuple[float, ...], ...],
    poc: float,
    val: float,
    vah: float,
    atr: float,
) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
    candidates: list[tuple[float, float, str]] = []
    for pivot in pivots:
        strength = {3: 58.0, 6: 66.0, 13: 78.0}[pivot.period]
        if pivot.support is not None:
            candidates.append((pivot.support, strength, f"ZCZL {pivot.period} 支撑"))
        if pivot.resistance is not None:
            candidates.append((pivot.resistance, strength, f"ZCZL {pivot.period} 阻力"))
    candidates.extend(
        (
            (channels[0][-1], 68.0, "HLX25 上轨"),
            (channels[1][-1], 68.0, "HLX25 下轨"),
            (channels[2][-1], 82.0, "HLX90 上轨"),
            (channels[3][-1], 82.0, "HLX90 下轨"),
            (min(bar.low for bar in bars[-20:]), 64.0, "20D 低点"),
            (max(bar.high for bar in bars[-20:]), 64.0, "20D 高点"),
            (min(bar.low for bar in bars[-60:]), 74.0, "60D 低点"),
            (max(bar.high for bar in bars[-60:]), 74.0, "60D 高点"),
            (poc, 80.0, "筹码峰 POC 代理"),
            (val, 66.0, "70% Value Area 下沿"),
            (vah, 66.0, "70% Value Area 上沿"),
        )
    )
    return _cluster_levels(bars[-1].close, atr, candidates)


def _rank(values: list[float]) -> list[float]:
    if len(values) <= 1:
        return [0.5] * len(values)
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    for rank, index in enumerate(ordered):
        ranks[index] = rank / (len(values) - 1)
    return ranks


def _sector_leader(
    sector: str, candidates: Mapping[str, tuple[DailyBar, ...]] | None, as_of: date
) -> tuple[str | None, str, bool]:
    available: list[tuple[str, tuple[DailyBar, ...], float, float, float]] = []
    for ticker in sector_leader_candidates(sector):
        bars = _daily_bars((candidates or {}).get(ticker, ()), as_of)
        if len(bars) < 61:
            continue
        available.append(
            (
                ticker,
                bars,
                _period_return(bars, 20),
                _period_return(bars, 60),
                statistics.fmean(bar.close * bar.volume for bar in bars[-20:]),
            )
        )
    if len(available) < 2:
        return sector, "公司候选池行情不足；仅回退显示板块 ETF，不代表个股龙头。", False
    r20, r60 = _rank([item[2] for item in available]), _rank([item[3] for item in available])
    liquidity = _rank([math.log10(max(item[4], 1.0)) for item in available])
    scores = [a * 0.45 + b * 0.40 + c * 0.15 for a, b, c in zip(r20, r60, liquidity, strict=True)]
    winner = max(range(len(available)), key=scores.__getitem__)
    return (
        available[winner][0],
        f"固定候选池相对强度领先（{len(available)}只；"
        "20D 45% + 60D 40% + 20D流动性15%），非全市场排名。",
        True,
    )


def _scenarios(
    direction: str,
    current: float,
    atr: float,
    supports: tuple[PriceLevel, ...],
    resistances: tuple[PriceLevel, ...],
    score: float,
) -> tuple[StockScenario, ...]:
    support = supports[0].price if supports else current - atr
    next_support = supports[1].price if len(supports) > 1 else support - atr
    resistance = resistances[0].price if resistances else current + atr
    next_resistance = resistances[1].price if len(resistances) > 1 else resistance + atr
    conviction = abs(score - 50) * 2
    raw = [35 + conviction * 0.45, 40 - conviction * 0.15, max(5.0, 25 - conviction * 0.30)]
    total = sum(raw)
    weights = [round(value / total * 100, 1) for value in raw]
    weights[-1] = round(100 - weights[0] - weights[1], 1)
    if direction == "CALL":
        return (
            StockScenario(
                "TREND_CONTINUATION",
                "多头延续",
                "CALL",
                weights[0],
                f"日线收盘站稳 ${resistance:.2f}，HLX25 上轨继续抬升。",
                (resistance, next_resistance),
                support,
                "HLX/ZCZL、MACD、结构与 OHLCV 资金流代理的方向性综合。",
            ),
            StockScenario(
                "PULLBACK_HOLD",
                "回踩支撑后再走强",
                "CALL",
                weights[1],
                f"回踩 ${support:.2f} 附近但日线未有效跌破，并重新收复。",
                (current, resistance),
                next_support,
                "筹码峰、HLX 与确认后的 ZCZL 聚类只用于定位，不预言盘中最低点。",
            ),
            StockScenario(
                "THESIS_BREAK",
                "支撑失守转弱",
                "PUT",
                weights[2],
                f"日线有效跌破 ${support:.2f} 且反抽无法收复。",
                (support, next_support),
                resistance,
                "这是原多头结构的失效路径，不是对下跌概率的历史校准。",
            ),
        )
    return (
        StockScenario(
            "TREND_CONTINUATION",
            "空头延续",
            "PUT",
            weights[0],
            f"日线有效跌破 ${support:.2f}，HLX25 通道继续下压。",
            (support, next_support),
            resistance,
            "HLX/ZCZL、MACD、结构与 OHLCV 资金流代理的方向性综合。",
        ),
        StockScenario(
            "RECLAIM_REJECTION",
            "反抽压力后再转弱",
            "PUT",
            weights[1],
            f"反抽 ${resistance:.2f} 附近未能日线站稳，并再次转弱。",
            (current, support),
            next_resistance,
            "筹码峰、HLX 与确认后的 ZCZL 聚类只用于定位，不预言盘中最高点。",
        ),
        StockScenario(
            "THESIS_BREAK",
            "压力突破转强",
            "CALL",
            weights[2],
            f"日线收盘站稳 ${resistance:.2f} 且回踩确认。",
            (resistance, next_resistance),
            support,
            "这是原空头结构的失效路径，不是对上涨概率的历史校准。",
        ),
    )


def analyze_stock(
    ticker: str,
    bars: tuple[DailyBar, ...],
    *,
    sector_etf: str | None = None,
    sector_bars: tuple[DailyBar, ...] | None = None,
    benchmark_ticker: str = "SPY",
    benchmark_bars: tuple[DailyBar, ...] | None = None,
    peer_bars: Mapping[str, tuple[DailyBar, ...]] | None = None,
    sector_candidate_bars: Mapping[str, tuple[DailyBar, ...]] | None = None,
    as_of: date | None = None,
) -> StockAnalysis:
    ordered = _daily_bars(bars, as_of)
    if len(ordered) < MINIMUM_ANALYSIS_SESSIONS:
        raise ValueError(f"stock analysis requires at least {MINIMUM_ANALYSIS_SESSIONS} daily bars")
    symbol = ticker.strip().upper()
    effective_as_of = ordered[-1].timestamp.date()
    sector = (sector_etf or infer_sector_etf(symbol)).strip().upper()
    closes, highs, lows = (
        tuple(bar.close for bar in ordered),
        tuple(bar.high for bar in ordered),
        tuple(bar.low for bar in ordered),
    )
    channels = (
        ema_series(highs, 25),
        ema_series(lows, 25),
        ema_series(highs, 90),
        ema_series(lows, 90),
    )
    pivots = tuple(confirmed_pivot_levels(ordered, period) for period in (3, 6, 13))
    flow = analyze_money_flow_proxy(ordered)
    nodes, poc, val, vah = build_volume_profile_proxy(ordered)
    hlx, zczl, macd, rsi14, structure = (
        _hlx_score(ordered[-1].close, *channels),
        _zczl_score(ordered[-1].close, pivots),
        _macd_score(closes),
        _rsi14(closes),
        _structure_score(ordered),
    )
    technical = (
        hlx * 0.30 + zczl * 0.25 + macd * 0.14 + structure * 0.14 + rsi14 * 0.07 + flow.score * 0.10
    )
    preliminary = "CALL" if technical >= 50 else "PUT"
    normalized_sector = _daily_bars(sector_bars or (), effective_as_of)
    normalized_benchmark = _daily_bars(benchmark_bars or (), effective_as_of)
    normalized_peers = {
        key.strip().upper(): _daily_bars(value, effective_as_of)
        for key, value in (peer_bars or {}).items()
    }
    rotation = None
    if len(normalized_sector) >= 21 and len(normalized_benchmark) >= 21:
        rotation = analyze_sector_rotation(
            sector,
            normalized_sector,
            benchmark_ticker.strip().upper(),
            normalized_benchmark,
            preliminary,
            dict(normalized_peers),
        )
        bullish_score = technical * 0.90 + rotation.strength_score * 0.10
    else:
        bullish_score = technical
    direction = "CALL" if bullish_score >= 50 else "PUT"
    if rotation is not None and direction != preliminary:
        rotation = analyze_sector_rotation(
            sector,
            normalized_sector,
            benchmark_ticker.strip().upper(),
            normalized_benchmark,
            direction,
            dict(normalized_peers),
        )
    trend_score = round(_clamp(bullish_score), 1)
    trend_label = (
        "多头趋势"
        if trend_score >= 68
        else "震荡偏多"
        if trend_score >= 55
        else "空头趋势"
        if trend_score <= 32
        else "震荡偏空"
        if trend_score <= 45
        else "方向均衡"
    )
    atr = _atr(ordered)
    supports, resistances = _price_levels(ordered, pivots, channels, poc, val, vah, atr)
    leader, leader_basis, leader_available = _sector_leader(
        sector, sector_candidate_bars, effective_as_of
    )
    unavailable = []
    if rotation is None:
        unavailable.append("sector_rotation")
    if not leader_available:
        unavailable.append("sector_company_leader_comparison")
    return StockAnalysis(
        ticker=symbol,
        as_of=effective_as_of,
        data_timestamp=ordered[-1].timestamp,
        history_sessions=len(ordered),
        history_mode="STANDARD",
        current_price=ordered[-1].close,
        direction=direction,
        trend_score=trend_score,
        trend_label=trend_label,
        indicator_scores=(
            ("HLX", round(hlx, 1)),
            ("ZCZL", round(zczl, 1)),
            ("MACD", round(macd, 1)),
            ("RSI14", round(rsi14, 1)),
            ("Structure", round(structure, 1)),
            ("Money Flow Proxy", flow.score),
            ("Sector RS", rotation.strength_score if rotation else 50.0),
        ),
        support_levels=supports,
        resistance_levels=resistances,
        volume_profile_nodes=nodes,
        point_of_control=poc,
        value_area_low=val,
        value_area_high=vah,
        money_flow=flow,
        sector_etf=sector,
        sector_name_zh=SECTOR_NAMES_ZH.get(sector, "美股大盘"),
        sector_strength_score=rotation.strength_score if rotation else None,
        sector_rotation_phase=rotation.rotation_phase if rotation else None,
        sector_leader_ticker=leader,
        sector_leader_basis_zh=leader_basis,
        scenarios=_scenarios(direction, ordered[-1].close, atr, supports, resistances, trend_score),
        unavailable_data=tuple(dict.fromkeys(unavailable)),
        methodology_note=(
            "CosmosMarket Stock Analyst v0.1：调整日 K、HLX 25/90、已确认且不回填的 "
            "ZCZL 3/6/13、MACD 12/26/9、RSI14、20/50/60 日结构、80 日 OHLCV "
            "区间成交量分布与 20 日资金流代理。情景百分比为规则模型权重，"
            "未经历史校准。"
        ),
    )
