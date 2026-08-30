"""Pure Gamma-exposure calculations and interpretation for AXIS GEX Explorer."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.market_intelligence.gex_explorer.models import (
    GexByStrike,
    GexExpiration,
    GexOptionContract,
    GexSnapshot,
    OptionSide,
)

AXIS_GEX_EXPLORER = "AXIS GEX Explorer"
CONTRACT_MULTIPLIER = 100
DEALER_SIGN_ASSUMPTION = (
    "估算假设：dealer 对 Call 为正 gamma、对 Put 为负 gamma；并非真实持仓观测。"
)


def black_scholes_gamma(
    spot: float,
    strike: float,
    volatility: float,
    time_years: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float | None:
    if (
        spot <= 0
        or strike <= 0
        or volatility <= 0
        or time_years <= 0
        or not math.isfinite(volatility)
    ):
        return None
    root_time = math.sqrt(time_years)
    denominator = spot * volatility * root_time
    if denominator <= 0:
        return None
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * time_years
    ) / (volatility * root_time)
    density = math.exp(-(d1**2) / 2) / math.sqrt(2 * math.pi)
    return math.exp(-dividend_yield * time_years) * density / denominator


def _time_years(contract: GexOptionContract, now_et: datetime) -> float:
    timezone = ZoneInfo("America/New_York")
    expiry_at = datetime.combine(contract.expiration, time(16, 0), tzinfo=timezone)
    seconds = max((expiry_at - now_et.astimezone(timezone)).total_seconds(), 60.0)
    return seconds / (365 * 24 * 60 * 60)


def _zero_gamma(points: tuple[GexByStrike, ...], spot: float) -> float | None:
    if not points:
        return None
    cumulative = []
    running = 0.0
    for point in points:
        running += point.net_gex
        cumulative.append((point.strike, running))
    crossings = []
    for (left_strike, left_value), (right_strike, right_value) in zip(
        cumulative, cumulative[1:], strict=False
    ):
        if left_value == 0:
            crossings.append(left_strike)
        elif left_value * right_value < 0:
            fraction = abs(left_value) / (abs(left_value) + abs(right_value))
            crossings.append(left_strike + (right_strike - left_strike) * fraction)
    if crossings:
        return min(crossings, key=lambda value: abs(value - spot))
    return min(cumulative, key=lambda item: abs(item[1]))[0]


def calculate_gamma_exposure(
    contracts: tuple[GexOptionContract, ...],
    spot: float,
    now_et: datetime,
    *,
    risk_free_rate: float = 0.0425,
    dividend_yield: float = 0.012,
) -> tuple[tuple[GexByStrike, ...], int, int, str]:
    """Return signed dollar GEX per 1% move; missing Gamma/OI is never imputed."""

    if spot <= 0 or now_et.tzinfo is None:
        raise ValueError("spot must be positive and now_et timezone-aware")
    calls: defaultdict[float, float] = defaultdict(float)
    puts: defaultdict[float, float] = defaultdict(float)
    included = skipped = vendor = calculated = 0
    for contract in contracts:
        if contract.open_interest is None or contract.open_interest <= 0:
            skipped += 1
            continue
        gamma = contract.gamma
        if gamma is not None and gamma > 0:
            vendor += 1
        elif contract.implied_volatility is not None:
            gamma = black_scholes_gamma(
                spot,
                contract.strike,
                contract.implied_volatility,
                _time_years(contract, now_et),
                risk_free_rate,
                dividend_yield,
            )
            if gamma is not None:
                calculated += 1
        if gamma is None or gamma <= 0:
            skipped += 1
            continue
        exposure = gamma * contract.open_interest * CONTRACT_MULTIPLIER * spot**2 * 0.01
        if contract.side is OptionSide.CALL:
            calls[contract.strike] += exposure
        else:
            puts[contract.strike] -= exposure
        included += 1
    points = tuple(
        GexByStrike(
            strike=strike,
            call_gex=calls[strike],
            put_gex=puts[strike],
            net_gex=calls[strike] + puts[strike],
        )
        for strike in sorted(set(calls) | set(puts))
    )
    method = (
        "vendor gamma"
        if vendor and not calculated
        else "Black-Scholes gamma from vendor IV"
        if calculated and not vendor
        else "vendor gamma + Black-Scholes IV fallback"
        if included
        else "unavailable"
    )
    return points, included, skipped, method


def _expiration(
    expiration: object,
    points: tuple[GexByStrike, ...],
    included: int,
) -> GexExpiration:
    calls = [point for point in points if point.call_gex > 0]
    puts = [point for point in points if point.put_gex < 0]
    return GexExpiration(
        expiration=expiration,  # type: ignore[arg-type]
        net_gex=sum(point.net_gex for point in points),
        total_abs_gex=sum(abs(point.call_gex) + abs(point.put_gex) for point in points),
        call_wall=max(calls, key=lambda item: item.call_gex).strike if calls else None,
        put_wall=min(puts, key=lambda item: item.put_gex).strike if puts else None,
        included_contracts=included,
        by_strike=points,
    )


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def build_gex_snapshot(
    ticker: str,
    spot: float,
    contracts: tuple[GexOptionContract, ...],
    now_et: datetime,
    *,
    risk_free_rate: float = 0.0425,
    dividend_yield: float = 0.012,
) -> GexSnapshot:
    grouped: defaultdict[object, list[GexOptionContract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.expiration].append(contract)
    expirations = []
    warnings = []
    methods = set()
    for expiration in sorted(grouped):
        points, included, _, method = calculate_gamma_exposure(
            tuple(grouped[expiration]),
            spot,
            now_et,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
        )
        methods.add(method)
        if not included:
            warnings.append(f"{expiration:%m/%d} 缺少可用 Gamma/OI")
            continue
        expirations.append(_expiration(expiration, points, included))
    if not expirations:
        raise ValueError("option chain did not contain usable Gamma and open interest")
    points, included, skipped, method = calculate_gamma_exposure(
        contracts,
        spot,
        now_et,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    methods.add(method)
    net = sum(point.net_gex for point in points)
    total_abs = sum(abs(point.call_gex) + abs(point.put_gex) for point in points)
    ratio = net / total_abs if total_abs else 0.0
    regime = (
        "正 Gamma 稳定区"
        if ratio >= 0.08
        else "负 Gamma 加速区"
        if ratio <= -0.08
        else "Gamma 平衡区"
    )
    zero = _zero_gamma(points, spot)
    calls = [point for point in points if point.call_gex > 0]
    puts = [point for point in points if point.put_gex < 0]
    call_wall = max(calls, key=lambda item: item.call_gex).strike if calls else None
    put_wall = min(puts, key=lambda item: item.put_gex).strike if puts else None
    above = [point.strike for point in points if point.strike > spot and point.net_gex > 0]
    below = [point.strike for point in points if point.strike < spot and point.net_gex < 0]
    bullish_trigger = (
        call_wall if call_wall is not None and call_wall > spot else min(above, default=None)
    )
    bearish_trigger = (
        put_wall if put_wall is not None and put_wall < spot else max(below, default=None)
    )
    location = 0 if zero is None else 1 if spot > zero else -1
    if location > 0 and ratio < -0.08:
        bias = "偏多且具备波动扩张条件"
    elif location < 0 and ratio < -0.08:
        bias = "偏空且下行波动可能被放大"
    elif ratio >= 0.08:
        bias = "正 Gamma 主导，更接近震荡吸附"
    else:
        bias = "中性，等待关键 Gamma 位置给出方向"
    analysis = (
        f"当前处于{regime}；净 GEX 占总绝对 GEX 的 {ratio:+.1%}。",
        f"Zero Gamma {_fmt(zero)}；Call Wall {_fmt(call_wall)}；Put Wall {_fmt(put_wall)}。",
        f"当前观察为“{bias}”。向上关注 {_fmt(bullish_trigger)}，向下关注 {_fmt(bearish_trigger)}。",
    )
    return GexSnapshot(
        ticker=ticker.upper(),
        timestamp_et=now_et,
        spot=spot,
        expirations=tuple(expirations),
        by_strike=points,
        net_gex=net,
        total_abs_gex=total_abs,
        normalized_net_gex=ratio,
        zero_gamma=zero,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_regime=regime,
        current_bias=bias,
        bullish_trigger=bullish_trigger,
        bearish_trigger=bearish_trigger,
        analysis_zh=analysis,
        gamma_method=" | ".join(sorted(methods)),
        included_contracts=included,
        skipped_contracts=skipped,
        data_warnings=tuple(warnings),
        dealer_sign_assumption=DEALER_SIGN_ASSUMPTION,
    )
