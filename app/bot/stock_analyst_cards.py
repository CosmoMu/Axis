"""Mobile-readable Discord card for AXIS Stock Analyst Phase 1."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import discord

from app.services.stock_analyst import StockAnalystQueryResult

ET = ZoneInfo("America/New_York")


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _levels(values) -> str:
    return "\n".join(_money(float(value.price)) for value in values[:2]) or "—"


def _bias(score: float) -> str:
    if score >= 68:
        return "BULLISH"
    if score >= 55:
        return "NEUTRAL → BULLISH"
    if score <= 32:
        return "BEARISH"
    if score <= 45:
        return "NEUTRAL → BEARISH"
    return "NEUTRAL"


def _indicator_line(name: str, score: float) -> str:
    if name == "RSI14":
        meaning = "动能偏强" if score >= 60 else "动能偏弱" if score <= 40 else "动能中性"
        return f"RSI  {score:.1f} · {meaning}"
    meaning = "偏强" if score >= 60 else "偏弱" if score <= 40 else "中性"
    return f"{name}  {score:.1f} · {meaning}"


def build_stock_analyst_embed(result: StockAnalystQueryResult) -> discord.Embed:
    analysis = result.analysis
    color = (
        0x86F7A8
        if analysis.trend_score >= 55
        else 0xD66A6A
        if analysis.trend_score <= 45
        else 0xD8C477
    )
    embed = discord.Embed(
        title=f"AXIS STOCK ANALYST · TEST · {analysis.ticker}",
        description="**仅限所有者 · 卡片测试频道**",
        color=color,
    )
    embed.add_field(name="价格", value=_money(analysis.current_price), inline=True)
    embed.add_field(name="市场结构", value=analysis.trend_label, inline=True)
    embed.add_field(
        name="当前倾向",
        value=f"{_bias(analysis.trend_score)}\n{analysis.trend_score:.1f} / 100",
        inline=True,
    )
    embed.add_field(name="关键支撑", value=_levels(analysis.support_levels), inline=True)
    embed.add_field(name="关键压力", value=_levels(analysis.resistance_levels), inline=True)
    embed.add_field(
        name="POC / Value Area",
        value=(
            f"POC {_money(analysis.point_of_control)}\n"
            f"VAH {_money(analysis.value_area_high)}\n"
            f"VAL {_money(analysis.value_area_low)}"
        ),
        inline=True,
    )
    scores = dict(analysis.indicator_scores)
    important = [
        _indicator_line(name, float(scores[name]))
        for name in ("RSI14", "MACD", "HLX")
        if name in scores
    ]
    flow_label = {
        "ACCUMULATION": "偏流入",
        "DISTRIBUTION": "偏流出",
        "NEUTRAL": "中性",
    }.get(analysis.money_flow.label, analysis.money_flow.label)
    important.append(f"成交量压力代理  {analysis.money_flow.score:.1f} · {flow_label}")
    embed.add_field(name="动能", value="\n".join(important), inline=False)
    ordered = sorted(
        analysis.scenarios,
        key=lambda item: item.model_weight_percent,
        reverse=True,
    )
    primary = ordered[0]
    clear = primary.model_weight_percent >= 50 and (
        len(ordered) == 1 or primary.model_weight_percent - ordered[1].model_weight_percent >= 10
    )
    if clear:
        targets = " → ".join(_money(value) for value in primary.targets)
        embed.add_field(
            name="主要情景",
            value=(
                f"**{primary.label_zh}**\n{primary.trigger_zh}\n"
                f"目标 {targets}\n模型情景权重 {primary.model_weight_percent:.1f}%"
            ),
            inline=False,
        )
    else:
        support = analysis.support_levels[0].price if analysis.support_levels else None
        resistance = analysis.resistance_levels[0].price if analysis.resistance_levels else None
        embed.add_field(
            name="结构暂不明确",
            value=f"观察支撑 {_money(support)}\n观察压力 {_money(resistance)}",
            inline=False,
        )
    bullish = max(
        (item for item in analysis.scenarios if item.direction == "CALL"),
        key=lambda item: item.model_weight_percent,
    )
    bearish = max(
        (item for item in analysis.scenarios if item.direction == "PUT"),
        key=lambda item: item.model_weight_percent,
    )
    embed.add_field(name="看涨触发", value=bullish.trigger_zh, inline=True)
    embed.add_field(name="看跌触发", value=bearish.trigger_zh, inline=True)
    embed.add_field(
        name="主要情景失效",
        value=_money(primary.invalidation),
        inline=True,
    )
    states = []
    if result.stale:
        states.append("⚠️ STALE DATA · 数据已超过实时阈值")
    elif result.market_status != "open":
        states.append("市场已关闭 · 基于最近可用市场数据")
    if states:
        embed.add_field(name="数据状态", value="\n".join(states), inline=False)
    updated = result.source_timestamp.astimezone(ET).strftime("%m/%d %I:%M %p ET")
    embed.add_field(
        name="数据与版本",
        value=(
            f"更新 {updated}\n数据源 {result.provider.title()} · 日 K\n"
            f"缓存 {'命中' if result.cache_hit else '未命中'} · {result.latency_ms} 毫秒\n"
            f"策略 {result.strategy_version}"
        ),
        inline=False,
    )
    embed.set_image(url=f"attachment://axis-stock-{analysis.ticker.lower()}.png")
    embed.set_footer(text="模型市场分析 · 仅供研究与教育，不构成投资建议")
    return embed
