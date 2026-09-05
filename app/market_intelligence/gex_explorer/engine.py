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
    GexStrikeImportance,
    GexTrigger,
    GexZone,
    OptionSide,
)

AXIS_GEX_EXPLORER = "AXIS GEX Explorer"
CONTRACT_MULTIPLIER = 100
DEALER_SIGN_ASSUMPTION = (
    "估算假设：dealer 对 Call 为正 gamma、对 Put 为负 gamma；并非真实持仓观测。"
)
DEFAULT_REGIME_THRESHOLDS = (0.25, 0.08, -0.08, -0.25)


def classify_gamma_regime(
    ratio: float,
    thresholds: tuple[float, float, float, float] = DEFAULT_REGIME_THRESHOLDS,
) -> str:
    strong_positive, positive, negative, strong_negative = thresholds
    if ratio >= strong_positive:
        return "强正 Gamma"
    if ratio >= positive:
        return "正 Gamma"
    if ratio <= strong_negative:
        return "强负 Gamma"
    if ratio <= negative:
        return "负 Gamma"
    return "Gamma 平衡区"


def _zones(
    points: tuple[GexByStrike, ...],
    *,
    positive: bool,
    relative_threshold: float,
) -> tuple[GexZone, ...]:
    values = [
        (point.strike, point.net_gex if positive else abs(point.net_gex))
        for point in points
        if (point.net_gex > 0 if positive else point.net_gex < 0)
    ]
    if not values:
        return ()
    peak_value = max(value for _, value in values)
    selected = [
        (strike, value) for strike, value in values if value >= peak_value * relative_threshold
    ]
    all_strikes = sorted(point.strike for point in points)
    steps = [right - left for left, right in zip(all_strikes, all_strikes[1:], strict=False)]
    typical_step = sorted(steps)[len(steps) // 2] if steps else 1.0
    groups: list[list[tuple[float, float]]] = []
    for item in selected:
        if not groups or item[0] - groups[-1][-1][0] > typical_step * 1.6:
            groups.append([item])
        else:
            groups[-1].append(item)
    zones = []
    for group in groups:
        peak = max(group, key=lambda item: item[1])
        zones.append(
            GexZone(
                lower=group[0][0],
                upper=group[-1][0],
                peak=peak[0],
                exposure=sum(item[1] for item in group),
            )
        )
    return tuple(sorted(zones, key=lambda zone: zone.exposure, reverse=True)[:3])


def _trigger(
    *,
    spot: float,
    acceleration_zones: tuple[GexZone, ...],
    magnet: float | None,
    bullish: bool,
) -> GexTrigger:
    containing = next(
        (zone for zone in acceleration_zones if zone.lower <= spot <= zone.upper),
        None,
    )
    if containing is not None:
        level = containing.upper if bullish else containing.lower
        target_text = f"，关注{'上方' if bullish else '下方'}磁吸 {_fmt(magnet)}" if magnet else ""
        return GexTrigger(
            level,
            magnet,
            f"当前位于负 Net GEX 加速区 {containing.lower:g}–{containing.upper:g}{target_text}",
        )
    directional_zones = [
        zone for zone in acceleration_zones if (zone.lower > spot if bullish else zone.upper < spot)
    ]
    if directional_zones:
        zone = min(
            directional_zones,
            key=lambda item: abs((item.lower if bullish else item.upper) - spot),
        )
        level = zone.lower if bullish else zone.upper
        direction = "上方" if bullish else "下方"
        target_text = f"，后续关注{direction}磁吸 {_fmt(magnet)}" if magnet else ""
        return GexTrigger(
            level, magnet, f"进入{direction}负 Net GEX 加速区 {_fmt(level)}{target_text}"
        )
    if magnet is not None:
        direction = "上方" if bullish else "下方"
        return GexTrigger(magnet, None, f"暂无同向加速区；关注{direction}磁吸 {_fmt(magnet)}")
    return GexTrigger(None, None, "暂无明确向上结构" if bullish else "暂无明确向下结构")


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
    exposure_basis: str = "open_interest",
) -> tuple[tuple[GexByStrike, ...], int, int, str]:
    """Return signed dollar GEX per 1% move using OI or actual daily option volume."""

    if spot <= 0 or now_et.tzinfo is None:
        raise ValueError("spot must be positive and now_et timezone-aware")
    if exposure_basis not in {"open_interest", "volume"}:
        raise ValueError("exposure_basis must be open_interest or volume")
    calls: defaultdict[float, float] = defaultdict(float)
    puts: defaultdict[float, float] = defaultdict(float)
    included = skipped = vendor = calculated = 0
    for contract in contracts:
        weight = contract.open_interest if exposure_basis == "open_interest" else contract.volume
        if weight is None or weight <= 0:
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
        exposure = gamma * weight * CONTRACT_MULTIPLIER * spot**2 * 0.01
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
    oi_points: tuple[GexByStrike, ...] = (),
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
        oi_by_strike=oi_points,
    )


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 1.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))
    return max(1.0, ordered[index])


def _robust(value: float, scale: float) -> float:
    if value == 0:
        return 0.0
    return min(1.0, math.log1p(abs(value)) / math.log1p(max(1.0, scale)))


def _median_step(points: tuple[GexByStrike, ...]) -> float:
    steps = sorted(
        right.strike - left.strike
        for left, right in zip(points, points[1:], strict=False)
        if right.strike > left.strike
    )
    return steps[len(steps) // 2] if steps else 1.0


def _importance(
    points: tuple[GexByStrike, ...],
    oi_points: tuple[GexByStrike, ...],
    expirations: tuple[GexExpiration, ...],
    *,
    spot: float,
    now_et: datetime,
    score_weights: tuple[float, float, float, float, float, float],
    robust_percentile: float,
) -> tuple[GexStrikeImportance, ...]:
    """Score intraday relevance with robust cross-strike normalization."""

    point_map = {point.strike: point for point in points}
    oi_map = {point.strike: point for point in oi_points}
    session_date = now_et.astimezone(ZoneInfo("America/New_York")).date()
    zero_expiration = next(
        (item for item in expirations if item.expiration == session_date),
        None,
    )
    nearest_expiration = (
        expirations[1] if zero_expiration is not None and len(expirations) > 1 else expirations[0]
    )
    zero_map = (
        {point.strike: point for point in zero_expiration.by_strike}
        if zero_expiration is not None
        else {}
    )
    nearest_map = {point.strike: point for point in nearest_expiration.by_strike}
    aggregate_scale = _percentile([abs(point.net_gex) for point in points], robust_percentile)
    zero_scale = _percentile([abs(point.net_gex) for point in zero_map.values()], robust_percentile)
    nearest_scale = _percentile(
        [abs(point.net_gex) for point in nearest_map.values()], robust_percentile
    )
    volume_scale = _percentile(
        [abs(point.call_gex) + abs(point.put_gex) for point in points],
        robust_percentile,
    )
    oi_scale = _percentile(
        [abs(point.call_gex) + abs(point.put_gex) for point in oi_points],
        robust_percentile,
    )
    step = _median_step(points)
    zero_weight, nearest_weight, aggregate_weight, volume_weight, oi_weight, proximity_weight = (
        score_weights
    )
    scores: list[GexStrikeImportance] = []
    for index, point in enumerate(points):
        oi_point = oi_map.get(point.strike)
        proximity = max(0.0, 1 - abs(point.strike - spot) / max(step * 12, 1))
        score = round(
            100
            * (
                zero_weight
                * _robust(
                    zero_map[point.strike].net_gex if point.strike in zero_map else 0,
                    zero_scale,
                )
                + nearest_weight
                * _robust(
                    nearest_map[point.strike].net_gex if point.strike in nearest_map else 0,
                    nearest_scale,
                )
                + aggregate_weight * _robust(point.net_gex, aggregate_scale)
                + volume_weight * _robust(abs(point.call_gex) + abs(point.put_gex), volume_scale)
                + oi_weight
                * _robust(
                    abs(oi_point.call_gex) + abs(oi_point.put_gex) if oi_point is not None else 0,
                    oi_scale,
                )
                + proximity_weight * proximity
            )
        )
        neighbors = [
            candidate
            for candidate in (
                points[index - 1] if index > 0 else None,
                points[index + 1] if index + 1 < len(points) else None,
            )
            if candidate is not None
        ]
        baseline = (
            sum(abs(candidate.net_gex) for candidate in neighbors) / len(neighbors)
            if neighbors
            else 0
        )
        node_strength = abs(point_map[point.strike].net_gex) / baseline if baseline else 0.0
        scores.append(GexStrikeImportance(point.strike, score, node_strength))
    return tuple(scores)


def _classified_levels(
    points: tuple[GexByStrike, ...],
    importance: tuple[GexStrikeImportance, ...],
    *,
    spot: float,
    upper: bool,
    node_neighbor_ratio: float,
    major_minimum_score: int,
    minor_minimum_score: int,
    major_levels_per_side: int,
    minor_levels_per_side: int,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    score_map = {item.strike: item for item in importance}
    candidates = sorted(
        (
            point
            for point in points
            if (point.strike > spot if upper else point.strike < spot) and point.net_gex > 0
        ),
        key=lambda point: score_map[point.strike].score,
        reverse=True,
    )
    major = tuple(
        point.strike
        for point in candidates
        if score_map[point.strike].score >= major_minimum_score
        or score_map[point.strike].node_strength >= node_neighbor_ratio
    )[:major_levels_per_side]
    minor = tuple(
        point.strike
        for point in sorted(candidates, key=lambda point: abs(point.strike - spot))
        if point.strike not in major and score_map[point.strike].score >= minor_minimum_score
    )[:minor_levels_per_side]
    return major, minor


def build_gex_snapshot(
    ticker: str,
    spot: float,
    contracts: tuple[GexOptionContract, ...],
    now_et: datetime,
    *,
    risk_free_rate: float = 0.0425,
    dividend_yield: float = 0.012,
    regime_thresholds: tuple[float, float, float, float] = DEFAULT_REGIME_THRESHOLDS,
    zone_relative_threshold: float = 0.35,
    score_weights: tuple[float, float, float, float, float, float] = (
        0.35,
        0.20,
        0.15,
        0.10,
        0.10,
        0.10,
    ),
    robust_percentile: float = 0.90,
    node_neighbor_ratio: float = 1.80,
    node_minimum_score: int = 45,
    major_minimum_score: int = 68,
    minor_minimum_score: int = 42,
    magnet_minimum_score: int = 58,
    magnet_maximum_steps_from_spot: int = 8,
    major_levels_per_side: int = 2,
    minor_levels_per_side: int = 2,
    exposure_basis: str = "open_interest",
) -> GexSnapshot:
    if exposure_basis not in {"open_interest", "volume"}:
        raise ValueError("exposure_basis must be open_interest or volume")
    basis_label = "成交量 GEX" if exposure_basis == "volume" else "持仓量 GEX"
    grouped: defaultdict[object, list[GexOptionContract]] = defaultdict(list)
    for contract in contracts:
        grouped[contract.expiration].append(contract)
    expirations: list[GexExpiration] = []
    warnings = []
    methods = set()
    for expiration in sorted(grouped):
        points, included, _, method = calculate_gamma_exposure(
            tuple(grouped[expiration]),
            spot,
            now_et,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            exposure_basis=exposure_basis,
        )
        methods.add(method)
        if not included:
            weight_label = "成交量" if exposure_basis == "volume" else "OI"
            warnings.append(f"{expiration:%m/%d} 缺少可用 Gamma/{weight_label}")
            continue
        oi_expiration_points, _, _, _ = calculate_gamma_exposure(
            tuple(grouped[expiration]),
            spot,
            now_et,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            exposure_basis="open_interest",
        )
        expirations.append(_expiration(expiration, points, included, oi_expiration_points))
    if not expirations:
        raise ValueError("option chain did not contain usable Gamma and open interest")
    points, included, skipped, method = calculate_gamma_exposure(
        contracts,
        spot,
        now_et,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        exposure_basis=exposure_basis,
    )
    methods.add(method)
    oi_points, _, _, _ = calculate_gamma_exposure(
        contracts,
        spot,
        now_et,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        exposure_basis="open_interest",
    )
    net = sum(point.net_gex for point in points)
    total_abs = sum(abs(point.call_gex) + abs(point.put_gex) for point in points)
    ratio = net / total_abs if total_abs else 0.0
    regime = classify_gamma_regime(ratio, regime_thresholds)
    zero = _zero_gamma(points, spot)
    calls = [point for point in points if point.call_gex > 0]
    puts = [point for point in points if point.put_gex < 0]
    call_wall = max(calls, key=lambda item: item.call_gex).strike if calls else None
    put_wall = min(puts, key=lambda item: item.put_gex).strike if puts else None
    importance = _importance(
        points,
        oi_points,
        tuple(expirations),
        spot=spot,
        now_et=now_et,
        score_weights=score_weights,
        robust_percentile=robust_percentile,
    )
    major_resistance, minor_resistance = _classified_levels(
        points,
        importance,
        spot=spot,
        upper=True,
        node_neighbor_ratio=node_neighbor_ratio,
        major_minimum_score=major_minimum_score,
        minor_minimum_score=minor_minimum_score,
        major_levels_per_side=major_levels_per_side,
        minor_levels_per_side=minor_levels_per_side,
    )
    major_support, minor_support = _classified_levels(
        points,
        importance,
        spot=spot,
        upper=False,
        node_neighbor_ratio=node_neighbor_ratio,
        major_minimum_score=major_minimum_score,
        minor_minimum_score=minor_minimum_score,
        major_levels_per_side=major_levels_per_side,
        minor_levels_per_side=minor_levels_per_side,
    )
    score_map = {item.strike: item for item in importance}
    gamma_nodes = tuple(
        item.strike
        for item in sorted(
            importance,
            key=lambda item: (item.node_strength, item.score),
            reverse=True,
        )
        if item.node_strength >= node_neighbor_ratio and item.score >= node_minimum_score
    )[:5]
    step = _median_step(points)
    gamma_magnet = None
    if ratio >= regime_thresholds[1]:
        magnet_candidates = [
            point
            for point in points
            if point.net_gex > 0
            and score_map[point.strike].score >= magnet_minimum_score
            and abs(point.strike - spot) <= step * magnet_maximum_steps_from_spot
        ]
        if magnet_candidates:
            gamma_magnet = max(
                magnet_candidates,
                key=lambda point: (
                    score_map[point.strike].score - 2 * abs(point.strike - spot) / max(step, 1e-9),
                    score_map[point.strike].node_strength,
                ),
            ).strike
    positive_zones = _zones(
        points,
        positive=True,
        relative_threshold=zone_relative_threshold,
    )
    negative_zones = _zones(
        points,
        positive=False,
        relative_threshold=zone_relative_threshold,
    )
    bullish = _trigger(
        spot=spot,
        acceleration_zones=negative_zones,
        magnet=gamma_magnet if gamma_magnet is not None and gamma_magnet > spot else None,
        bullish=True,
    )
    bearish = _trigger(
        spot=spot,
        acceleration_zones=negative_zones,
        magnet=gamma_magnet if gamma_magnet is not None and gamma_magnet < spot else None,
        bullish=False,
    )
    bullish_trigger = bullish.level
    bearish_trigger = bearish.level
    location = 0 if zero is None else 1 if spot > zero else -1
    if location > 0 and ratio <= regime_thresholds[2]:
        bias = "偏多"
    elif location < 0 and ratio <= regime_thresholds[2]:
        bias = "偏空"
    elif ratio >= regime_thresholds[1]:
        bias = "中性"
    else:
        bias = "中性偏多" if location > 0 else "中性偏空"
    positive_gex = sum(point.net_gex for point in points if point.net_gex > 0)
    negative_gex = sum(point.net_gex for point in points if point.net_gex < 0)
    near_term = expirations[0]
    near_term_ratio = (
        near_term.net_gex / near_term.total_abs_gex if near_term.total_abs_gex else 0.0
    )
    analysis = (
        f"{basis_label} 当前处于{regime}；净 GEX 占总绝对 GEX 的 {ratio:+.1%}。",
        f"主要压力 {_fmt(major_resistance[0] if major_resistance else None)}；"
        f"主要支撑 {_fmt(major_support[0] if major_support else None)}；"
        f"Gamma Magnet {_fmt(gamma_magnet)}；Gamma Flip {_fmt(zero)}。",
        f"Gross Wall 仅作成交结构参考：Call {_fmt(call_wall)}；Put {_fmt(put_wall)}；"
        "支撑、压力、磁吸与加速区均由同一套实时分类产生，Gamma 不单独代表方向。",
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
        gamma_method=f"{basis_label} | {' | '.join(sorted(methods))}",
        included_contracts=included,
        skipped_contracts=skipped,
        data_warnings=tuple(warnings),
        dealer_sign_assumption=DEALER_SIGN_ASSUMPTION,
        exposure_basis=exposure_basis,
        gamma_magnet=gamma_magnet,
        major_resistance=tuple(sorted(major_resistance)),
        minor_resistance=tuple(sorted(minor_resistance)),
        major_support=tuple(sorted(major_support, reverse=True)),
        minor_support=tuple(sorted(minor_support, reverse=True)),
        gamma_nodes=gamma_nodes,
        importance_by_strike=importance,
        oi_by_strike=oi_points,
        listed_strikes=tuple(sorted({contract.strike for contract in contracts})),
        positive_gex=positive_gex,
        negative_gex=negative_gex,
        near_term_expiration=near_term.expiration,
        near_term_net_gex=near_term.net_gex,
        near_term_regime=classify_gamma_regime(near_term_ratio, regime_thresholds),
        positive_zones=positive_zones,
        negative_zones=negative_zones,
        bullish=bullish,
        bearish=bearish,
    )
