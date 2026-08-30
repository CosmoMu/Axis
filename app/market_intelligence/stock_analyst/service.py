"""AXIS-owned Stock Analyst orchestration and Analysis merge policy."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

from app.domain.analysis_voice import first_person_text
from app.market_intelligence.stock_analyst.chart import render_stock_analysis_chart
from app.market_intelligence.stock_analyst.engine import analyze_stock
from app.market_intelligence.stock_analyst.market_data import (
    MoomooDailyBarProvider,
    StockMarketDataError,
)

AXIS_STOCK_ANALYST = "AXIS Stock Analyst"


class AxisStockAnalystError(RuntimeError):
    """Secret-free failure from the AXIS-owned market intelligence engine."""


@dataclass(frozen=True, slots=True)
class AxisStockAnalystResult:
    context: dict[str, Any]
    chart_png: bytes | None


class AxisStockAnalystService:
    def __init__(
        self, *, host: str, port: int, provider: MoomooDailyBarProvider | None = None
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
            analysis = await asyncio.to_thread(
                analyze_stock,
                bundle.ticker,
                bundle.bars,
                sector_etf=bundle.sector_etf,
                sector_bars=bundle.sector_bars,
                benchmark_bars=bundle.benchmark_bars,
            )
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
            return AxisStockAnalystResult(analysis.to_context(), chart)
        except (StockMarketDataError, ValueError, OSError, RuntimeError) as exc:
            code = exc.code if isinstance(exc, StockMarketDataError) else type(exc).__name__
            raise AxisStockAnalystError(code) from exc


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
            item.get("level_type"),
            item.get("price"),
            item.get("note"),
            item.get("source"),
        )
        if key not in seen:
            output.append(item)
            seen.add(key)
    return output


def sanitize_input_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Prevent the LLM from claiming observations that only the AXIS engine can create."""

    sanitized = dict(payload)
    for key in ("title", "summary", "core_thesis", "invalidation"):
        sanitized[key] = first_person_text(payload.get(key))
    for key in (
        "why_now",
        "supporting_points",
        "catalysts",
        "risks",
        "market_conditions",
    ):
        sanitized[key] = [
            first_person_text(item) for item in payload.get(key, []) if isinstance(item, str)
        ]
    sanitized["engine_observations"] = []
    sanitized["key_levels"] = [
        {**item, "note": first_person_text(item.get("note")), "source": "INPUT"}
        for item in payload.get("key_levels", [])
        if isinstance(item, dict) and item.get("source") != "AXIS_STOCK_ANALYST"
    ]
    return sanitized


def merge_stock_analysis(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Merge current AXIS engine evidence without replacing the manager thesis."""

    merged = dict(payload)
    ticker = str(context.get("ticker") or "").upper()
    observations = list(merged.get("engine_observations", []))
    trend_score = context.get("trend_score")
    if isinstance(trend_score, (int, float)):
        observations.append(
            f"AXIS Stock Analyst：{context.get('trend_label') or '方向未定'} "
            f"{float(trend_score):.0f}/100。"
        )
    flow = context.get("money_flow")
    if isinstance(flow, dict) and isinstance(flow.get("score"), (int, float)):
        observations.append(
            f"AXIS OHLCV 资金流代理：{flow.get('label') or '中性'} {float(flow['score']):.0f}/100。"
        )
    rotation = context.get("sector_rotation")
    if isinstance(rotation, dict) and rotation.get("rotation_phase"):
        observations.append(
            f"AXIS 板块相对强度：{context.get('sector_etf') or 'SPY'} · "
            f"{rotation['rotation_phase']}。"
        )
    scenarios = context.get("scenarios")
    if isinstance(scenarios, list):
        primary = max(
            (item for item in scenarios if isinstance(item, dict)),
            key=lambda item: float(item.get("model_weight_percent") or 0),
            default=None,
        )
        if primary:
            targets = (
                primary.get("targets") if isinstance(primary.get("targets"), (list, tuple)) else []
            )
            target_text = " / ".join(
                f"${float(value):,.2f}" for value in targets if isinstance(value, (int, float))
            )
            observations.append(
                f"AXIS 当前主情景：{primary.get('label_zh') or primary.get('scenario_id')} · "
                f"模型权重 {float(primary.get('model_weight_percent') or 0):.0f}%"
                + (f" · 路径参考 {target_text}" if target_text else "")
                + "（权重不是胜率）。"
            )
    merged["engine_observations"] = _unique(observations)
    levels = list(merged.get("key_levels", []))
    for source_name, level_type in (
        ("support_levels", "SUPPORT"),
        ("resistance_levels", "RESISTANCE"),
    ):
        raw_levels = context.get(source_name)
        if not isinstance(raw_levels, list):
            continue
        for item in raw_levels[:3]:
            if not isinstance(item, dict) or not isinstance(item.get("price"), (int, float)):
                continue
            levels.append(
                {
                    "symbol": ticker or None,
                    "level_type": level_type,
                    "price": float(item["price"]),
                    "note": "AXIS Stock Analyst 日 K 结构聚类",
                    "source": "AXIS_STOCK_ANALYST",
                }
            )
    merged["key_levels"] = _unique_levels(levels)
    conditions = list(merged.get("market_conditions", []))
    if ticker and context.get("as_of"):
        conditions.append(f"AXIS 行情数据截至 {context['as_of']} · {ticker} 日 K。")
    if context.get("history_mode") == "LIMITED":
        conditions.append(
            f"AXIS 新股有限历史模式：仅有 {int(context.get('history_sessions') or 0)} 个交易日，"
            "趋势分数已向中性收缩。"
        )
    merged["market_conditions"] = _unique(conditions)
    risks = list(merged.get("risks", []))
    risks.append("AXIS 预测线是未校准的模型情景路径，不是胜率、承诺或交易指令。")
    risks.append("筹码峰与资金流为 OHLCV 代理，不代表逐笔主动买卖或暗池数据。")
    merged["risks"] = _unique(risks)
    warnings = list(merged.get("warnings", []))
    warnings.extend(["AXIS_SCENARIO_WEIGHT_NOT_PROBABILITY", "AXIS_OHLCV_PROXY"])
    if context.get("history_mode") == "LIMITED":
        warnings.append("AXIS_LIMITED_HISTORY")
    merged["warnings"] = _unique(warnings)
    return merged
