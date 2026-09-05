"""AXIS-owned Stock Analyst orchestration and Analysis merge policy."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

from app.domain.analysis_voice import public_analysis_text
from app.market_intelligence.stock_analyst.chart import render_stock_analysis_chart
from app.market_intelligence.stock_analyst.engine import analyze_stock
from app.market_intelligence.stock_analyst.market_data import (
    MoomooDailyBarProvider,
    StockMarketDataError,
    StockMarketDataProvider,
)
from app.market_intelligence.stock_analyst.models import DailyBar, StockAnalysis

AXIS_STOCK_ANALYST = "AXIS Stock Analyst"


class AxisStockAnalystError(RuntimeError):
    """Secret-free failure from the AXIS-owned market intelligence engine."""


@dataclass(frozen=True, slots=True)
class AxisStockAnalystResult:
    context: dict[str, Any]
    chart_png: bytes | None
    analysis: StockAnalysis | None = None
    daily_bars: tuple[DailyBar, ...] = ()


class AxisStockAnalystService:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        provider: StockMarketDataProvider | None = None,
    ) -> None:
        self.provider = provider or MoomooDailyBarProvider(host, port)

    async def query(
        self,
        symbol: str,
        *,
        include_chart: bool = True,
        projection_points: tuple[dict[str, Any], ...] | None = None,
    ) -> AxisStockAnalystResult:
        try:
            bundle = await self.provider.fetch(symbol)
        except StockMarketDataError as exc:
            raise AxisStockAnalystError(exc.code) from exc
        try:
            analysis = await asyncio.to_thread(
                analyze_stock,
                bundle.ticker,
                bundle.bars,
                sector_etf=bundle.sector_etf,
                sector_bars=bundle.sector_bars,
                benchmark_bars=bundle.benchmark_bars,
                peer_bars=bundle.peer_bars,
                sector_candidate_bars=bundle.sector_candidate_bars,
            )
        except (TypeError, ValueError) as exc:
            raise AxisStockAnalystError("STOCK_ANALYST_CALCULATION_FAILURE") from exc
        try:
            chart = (
                await asyncio.to_thread(
                    render_stock_analysis_chart,
                    analysis,
                    bundle.bars,
                    projection_points=projection_points,
                )
                if include_chart
                else None
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise AxisStockAnalystError("STOCK_ANALYST_RENDER_FAILURE") from exc
        context = analysis.to_context()
        context.update(
            {
                "provider": bundle.provider,
                "market_timestamp": bundle.source_timestamp.isoformat(),
                "fetched_at": bundle.fetched_at.isoformat(),
                "market_status": bundle.market_status,
                "provider_unavailable_data": list(bundle.unavailable_data),
            }
        )
        context["daily_bars"] = [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in tuple(sorted(bundle.bars, key=lambda item: item.timestamp))[-82:]
        ]
        return AxisStockAnalystResult(context, chart, analysis, bundle.bars)


def input_projection_points(
    payload: dict[str, Any], *, allow_image: bool
) -> tuple[dict[str, Any], ...] | None:
    """Return ordered source-defined nodes; never invent a numeric input price."""

    projection = payload.get("source_projection")
    raw_points = projection.get("path_points") if isinstance(projection, dict) else None
    output: list[dict[str, Any]] = []
    if isinstance(raw_points, list):
        ordered = sorted(
            (item for item in raw_points if isinstance(item, dict)),
            key=lambda item: int(item.get("sequence") or 0),
        )
        for item in ordered[:12]:
            if item.get("source") == "IMAGE" and not allow_image:
                continue
            direction = item.get("direction")
            price = item.get("price")
            if direction not in {"START", "UP", "DOWN", "FLAT"}:
                continue
            if price is not None and (
                not isinstance(price, (int, float))
                or isinstance(price, bool)
                or not math.isfinite(float(price))
                or float(price) <= 0
            ):
                continue
            output.append(
                {
                    "direction": direction,
                    "price": float(price) if price is not None else None,
                    "label": str(item.get("label"))[:80] if item.get("label") else None,
                }
            )
    return tuple(output) or None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _unique_levels(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for item in values:
        key = (
            item.get("symbol"),
            item.get("role") or item.get("level_type"),
            item.get("price"),
            item.get("price_high"),
            item.get("description") or item.get("note"),
            item.get("source"),
        )
        if key not in seen:
            output.append(item)
            seen.add(key)
    return output


def _finite_price(value: Any) -> float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    ):
        return float(value)
    return None


def _source_label(source: Any) -> str:
    return "STOCK_ANALYST" if source == "STOCK_ANALYST" else "MENTOR_INPUT"


def _normalize_level(item: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    role = str(item.get("role") or item.get("level_type") or "WATCH").upper()
    if role not in {
        "SUPPORT",
        "RESISTANCE",
        "PIVOT",
        "WATCH",
        "BREAKOUT",
        "TARGET",
        "INVALIDATION",
        "KEY_ZONE",
        "OTHER",
    }:
        role = "OTHER"
    price = _finite_price(item.get("price"))
    price_high = _finite_price(item.get("price_high"))
    description = public_analysis_text(item.get("description") or item.get("note"))
    if price is None and price_high is None and not description:
        return None
    strength = item.get("strength")
    if not isinstance(strength, (int, float)) or isinstance(strength, bool):
        strength = None
    return {
        "symbol": item.get("symbol"),
        "role": role,
        "price": price,
        "price_high": price_high,
        "strength": round(float(strength), 2) if strength is not None else None,
        "description": description or None,
        "source": source,
    }


def _mentor_roles(levels: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("role") or item.get("level_type") or "").upper()
        for item in levels
        if item.get("source") == "MENTOR_INPUT"
    }


def _mentor_blocks_axis_role(mentor_roles: set[str], axis_role: str) -> bool:
    groups = {
        "SUPPORT": {"SUPPORT", "KEY_ZONE"},
        "RESISTANCE": {"RESISTANCE", "BREAKOUT"},
        "TARGET": {"TARGET"},
        "INVALIDATION": {"INVALIDATION"},
        "PIVOT": {"PIVOT", "WATCH"},
    }
    return bool(mentor_roles.intersection(groups.get(axis_role, {axis_role})))


def _level_conflicts(
    mentor_levels: list[dict[str, Any]], analyst_levels: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for role in ("SUPPORT", "RESISTANCE", "TARGET", "INVALIDATION"):
        mentor_prices = [item.get("price") for item in mentor_levels if item.get("role") == role]
        analyst_prices = [item.get("price") for item in analyst_levels if item.get("role") == role]
        mentor_prices = [value for value in mentor_prices if value is not None]
        analyst_prices = [value for value in analyst_prices if value is not None]
        if mentor_prices and analyst_prices and set(mentor_prices) != set(analyst_prices):
            conflicts.append(
                {
                    "field": role,
                    "mentor_values": mentor_prices,
                    "stock_analyst_values": analyst_prices,
                }
            )
    return conflicts


def _indicator_interpretation(name: str, value: float | str | None) -> str:
    upper = name.upper()
    if upper == "RSI14" and isinstance(value, (int, float)):
        return "动能偏强" if value >= 60 else "动能偏弱" if value <= 40 else "动能处于中性区域"
    if upper.startswith("MACD") and isinstance(value, (int, float)):
        return "动能保持正向" if value > 0 else "动能仍偏弱" if value < 0 else "动能接近平衡"
    if upper == "STRUCTURE" and isinstance(value, (int, float)):
        return "结构偏强" if value >= 60 else "结构偏弱" if value <= 40 else "结构保持平衡"
    if upper == "MONEY FLOW PROXY" and isinstance(value, (int, float)):
        if value >= 58:
            return "价格与成交量代理偏流入"
        return "价格与成交量代理偏流出" if value <= 42 else "价格与成交量代理中性"
    if upper == "SECTOR RS" and isinstance(value, (int, float)):
        if value >= 60:
            return "板块相对强度领先"
        return "板块相对强度偏弱" if value <= 40 else "板块相对强度中性"
    return "当前读数值得继续观察"


def _stock_indicators(context: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[tuple[str, Any]] = []
    scores = context.get("indicator_scores")
    if isinstance(scores, dict):
        for name in ("HLX", "ZCZL", "MACD", "MACD_ATR", "RSI14"):
            if name in scores:
                values.append(("MACD" if name == "MACD_ATR" else name, scores[name]))
    values.append(("Structure", context.get("trend_score")))
    flow = context.get("money_flow")
    if isinstance(flow, dict):
        values.append(("Money Flow Proxy", flow.get("score")))
    rotation = context.get("sector_rotation")
    if isinstance(rotation, dict):
        values.append(("Sector RS", rotation.get("strength_score")))
    output = []
    for name, value in values:
        if value is None:
            continue
        clean_value: float | str
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            clean_value = round(float(value), 2)
        else:
            clean_value = str(value)[:80]
        output.append(
            {
                "indicator_name": name,
                "value": clean_value,
                "interpretation": _indicator_interpretation(name, clean_value),
                "source": "STOCK_ANALYST",
            }
        )
    return output


def _stock_levels(context: dict[str, Any]) -> list[dict[str, Any]]:
    ticker = str(context.get("ticker") or "").upper() or None
    output: list[dict[str, Any]] = []
    for key, role in (("support_levels", "SUPPORT"), ("resistance_levels", "RESISTANCE")):
        rows = context.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows[:3]:
            if not isinstance(item, dict):
                continue
            level = _normalize_level(
                {
                    "symbol": ticker,
                    "role": role,
                    "price": item.get("price"),
                    "strength": (
                        float(item["strength"]) * 100
                        if isinstance(item.get("strength"), (int, float))
                        and float(item["strength"]) <= 1
                        else item.get("strength")
                    ),
                    "description": "主要结构支撑" if role == "SUPPORT" else "主要结构压力",
                },
                source="STOCK_ANALYST",
            )
            if level:
                output.append(level)
    scenarios = context.get("scenarios")
    if isinstance(scenarios, list):
        primary = max(
            (item for item in scenarios if isinstance(item, dict)),
            key=lambda item: float(item.get("model_weight_percent") or 0),
            default=None,
        )
        if primary:
            for target in list(primary.get("targets") or [])[:2]:
                level = _normalize_level(
                    {
                        "symbol": ticker,
                        "role": "TARGET",
                        "price": target,
                        "description": "模型主情景目标",
                    },
                    source="STOCK_ANALYST",
                )
                if level:
                    output.append(level)
            invalidation = _normalize_level(
                {
                    "symbol": ticker,
                    "role": "INVALIDATION",
                    "price": primary.get("invalidation"),
                    "description": "模型主情景失效位置",
                },
                source="STOCK_ANALYST",
            )
            if invalidation:
                output.append(invalidation)
    return output


def _normalize_scenarios(context: dict[str, Any]) -> list[dict[str, Any]]:
    raw = context.get("scenarios")
    if not isinstance(raw, list):
        return []
    output = []
    for position, item in enumerate(raw[:3]):
        if not isinstance(item, dict):
            continue
        weight = item.get("model_weight_percent")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        output.append(
            {
                "scenario_id": str(item.get("scenario_id") or f"SCENARIO_{position + 1}"),
                "label": public_analysis_text(item.get("label_zh")) or "结构路径",
                "model_weight_percent": round(float(weight), 2),
                "trigger": public_analysis_text(item.get("trigger_zh")) or None,
                "targets": [
                    price
                    for value in list(item.get("targets") or [])[:4]
                    if (price := _finite_price(value)) is not None
                ],
                "invalidation": _finite_price(item.get("invalidation")),
                "rationale": public_analysis_text(item.get("rationale_zh")) or None,
                "source": "STOCK_ANALYST",
            }
        )
    return sorted(output, key=lambda item: item["model_weight_percent"], reverse=True)


def _price_for_role(levels: list[dict[str, Any]], *roles: str) -> float | None:
    for role in roles:
        for item in levels:
            if item.get("role") == role and item.get("price") is not None:
                return float(item["price"])
    return None


def _prediction_path(
    payload: dict[str, Any],
    context: dict[str, Any],
    levels: list[dict[str, Any]],
    scenarios: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not scenarios:
        return None, []
    top = scenarios[0]
    second_weight = scenarios[1]["model_weight_percent"] if len(scenarios) > 1 else 0
    weight = float(top["model_weight_percent"])
    clear = weight >= 50 and weight - float(second_weight) >= 10
    top_public = {**top, "direction_clear": clear}
    if not clear:
        return top_public, []
    current = _finite_price(context.get("current_price"))
    if current is None:
        return {**top_public, "direction_clear": False}, []
    points: list[dict[str, Any]] = [
        {"type": "CURRENT", "price": current, "label": "当前", "sequence": 0}
    ]
    projection = payload.get("source_projection")
    raw_points = projection.get("path_points") if isinstance(projection, dict) else []
    if isinstance(raw_points, list):
        for item in sorted(
            (item for item in raw_points if isinstance(item, dict)),
            key=lambda item: int(item.get("sequence") or 0),
        ):
            price = _finite_price(item.get("price"))
            if price is None or abs(price - points[-1]["price"]) < 1e-9:
                continue
            label = public_analysis_text(item.get("label")) or "结构位置"
            upper_label = str(label).upper()
            point_type = (
                "TARGET"
                if "目标" in str(label) or "TARGET" in upper_label
                else "BREAKOUT"
                if "突破" in str(label) or "BREAKOUT" in upper_label
                else "STRUCTURE"
            )
            points.append(
                {"type": point_type, "price": price, "label": label, "sequence": len(points)}
            )
    if len(points) == 1:
        breakout = _price_for_role(levels, "BREAKOUT", "RESISTANCE", "PIVOT")
        target = _price_for_role(levels, "TARGET")
        if breakout is not None and abs(breakout - current) > 1e-9:
            points.append(
                {
                    "type": "BREAKOUT",
                    "price": breakout,
                    "label": "关键突破",
                    "sequence": len(points),
                }
            )
        if target is not None and all(abs(target - item["price"]) > 1e-9 for item in points):
            points.append(
                {"type": "TARGET", "price": target, "label": "目标", "sequence": len(points)}
            )
    if len(points) < 2:
        return {**top_public, "direction_clear": False}, []
    return top_public, points


def sanitize_input_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Mentor data without altering explicit prices or reversing the view."""

    sanitized = dict(payload)
    for key in ("title", "summary", "core_thesis", "invalidation"):
        sanitized[key] = public_analysis_text(payload.get(key))
    for key in (
        "why_now",
        "supporting_points",
        "catalysts",
        "risks",
        "market_conditions",
    ):
        sanitized[key] = [
            public_analysis_text(item) for item in payload.get(key, []) if isinstance(item, str)
        ]
    sanitized["engine_observations"] = []
    levels = []
    for item in payload.get("key_levels", []):
        if not isinstance(item, dict) or item.get("source") in {
            "STOCK_ANALYST",
            "AXIS_STOCK_ANALYST",
        }:
            continue
        level = _normalize_level(item, source="MENTOR_INPUT")
        if level:
            levels.append(level)
    sanitized["key_levels"] = _unique_levels(levels)
    indicators = []
    for item in payload.get("indicators", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("indicator_name") or item.get("name") or "").strip()
        interpretation = public_analysis_text(item.get("interpretation"))
        if name and (item.get("value") is not None or interpretation):
            indicators.append(
                {
                    "indicator_name": name[:80],
                    "value": item.get("value"),
                    "interpretation": interpretation or None,
                    "source": "MENTOR_INPUT",
                }
            )
    sanitized["indicators"] = indicators
    return sanitized


def merge_stock_analysis(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Fuse one final Analysis with strict Mentor-first, AXIS-fill-missing policy."""

    merged = dict(payload)
    mentor_levels = [dict(item) for item in merged.get("key_levels", []) if isinstance(item, dict)]
    analyst_levels = _stock_levels(context)
    roles = _mentor_roles(mentor_levels)
    final_levels = list(mentor_levels)
    for level in analyst_levels:
        role = str(level.get("role"))
        if not _mentor_blocks_axis_role(roles, role):
            final_levels.append(level)
    merged["key_levels"] = _unique_levels(final_levels)
    conflicts = _level_conflicts(mentor_levels, analyst_levels)
    merged["conflict_detected"] = bool(conflicts)
    merged["conflicts"] = conflicts

    mentor_indicators = [
        dict(item) for item in merged.get("indicators", []) if isinstance(item, dict)
    ]
    mentor_names = {
        str(item.get("indicator_name") or "").strip().upper() for item in mentor_indicators
    }
    analyst_indicators = [
        item
        for item in _stock_indicators(context)
        if str(item["indicator_name"]).upper() not in mentor_names
    ]
    merged["indicators"] = (mentor_indicators + analyst_indicators)[:7]

    scenarios = _normalize_scenarios(context)
    merged["scenarios"] = scenarios
    top_scenario, prediction_path = _prediction_path(merged, context, final_levels, scenarios)
    merged["top_scenario"] = top_scenario
    merged["prediction_path"] = prediction_path
    if top_scenario and top_scenario.get("direction_clear"):
        invalidation_level = _price_for_role(final_levels, "INVALIDATION")
        if invalidation_level is not None:
            top_scenario["invalidation"] = invalidation_level

    flow = context.get("money_flow") if isinstance(context.get("money_flow"), dict) else {}
    merged["market_profile"] = {
        "point_of_control": _finite_price(context.get("point_of_control")),
        "value_area_low": _finite_price(context.get("value_area_low")),
        "value_area_high": _finite_price(context.get("value_area_high")),
        "money_flow_label": flow.get("label"),
        "money_flow_score": flow.get("score"),
        "signed_volume_ratio": flow.get("signed_volume_ratio"),
    }
    merged["current_price"] = _finite_price(context.get("current_price"))
    merged["market_as_of"] = context.get("data_timestamp") or context.get("as_of")
    merged["engine_observations"] = []
    conditions = list(merged.get("market_conditions", []))
    if context.get("history_mode") == "LIMITED":
        conditions.append(
            f"当前仅有 {int(context.get('history_sessions') or 0)} 个交易日，"
            "结构置信度已向中性收缩。"
        )
    merged["market_conditions"] = _unique(conditions)
    risks = list(merged.get("risks", []))
    risks.append("模型情景权重用于表达当前结构下的相对路径，并非历史校准后的真实概率。")
    merged["risks"] = _unique(risks)
    merged["methodology_notice"] = (
        "OHLCV 资金流为价格与成交量代理，不代表逐笔主动买卖或真实机构持仓。"
    )
    warnings = list(merged.get("warnings", []))
    warnings.extend(["AXIS_SCENARIO_WEIGHT_NOT_PROBABILITY", "AXIS_OHLCV_PROXY"])
    if conflicts:
        warnings.append("AXIS_DATA_CONFLICT_REVIEW_REQUIRED")
    if context.get("history_mode") == "LIMITED":
        warnings.append("AXIS_LIMITED_HISTORY")
    merged["warnings"] = _unique(warnings)
    return merged
