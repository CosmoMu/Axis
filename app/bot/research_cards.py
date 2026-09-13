"""Discord cards for AXIS Multi-Agent Research test mode."""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo

import discord

from app.domain.enums import LlmWorkload
from app.market_intelligence.research_engine.models import ResearchRunResult

ET = ZoneInfo("America/New_York")


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _levels(values: tuple[float, ...]) -> str:
    return " / ".join(_money(value) for value in values[:4]) or "—"


def _bullets(values: tuple[str, ...], *, limit: int = 4) -> str:
    return "\n".join(f"• {value}" for value in values[:limit]) or "—"


def build_research_embed(result: ResearchRunResult) -> discord.Embed:
    view = result.view
    if view.insufficient_data:
        embed = discord.Embed(
            title=f"AXIS MULTI-AGENT RESEARCH · TEST · {view.ticker}",
            description="**INSUFFICIENT DATA · 数据覆盖不足**",
            color=0xD66A6A,
        )
        embed.add_field(
            name="数据覆盖",
            value=f"{sum(item.available for item in result.pack.components)} / 5",
            inline=True,
        )
        embed.add_field(name="原因", value=_bullets(view.warnings), inline=False)
        embed.set_footer(text="仅供市场研究与教育，不构成投资建议")
        return embed
    stance_color = (
        0x86F7A8
        if "BULLISH" in str(view.research_stance)
        else 0xD66A6A
        if "BEARISH" in str(view.research_stance)
        else 0xD8C477
    )
    embed = discord.Embed(
        title=f"AXIS MULTI-AGENT RESEARCH · TEST · {view.ticker}",
        description="**仅限所有者 · 卡片测试频道 · 只读研究**",
        color=stance_color,
    )
    embed.add_field(name="研究倾向", value=view.research_stance or "NEUTRAL", inline=True)
    embed.add_field(name="确定性置信度", value=f"{view.research_confidence}%", inline=True)
    embed.add_field(name="现价", value=_money(view.price), inline=True)
    embed.add_field(name="市场结构", value=view.market_structure[:1024], inline=False)
    embed.add_field(name="Options / GEX", value=view.gamma_context[:1024], inline=False)
    embed.add_field(name="多方论点", value=view.bull_case[:1024], inline=True)
    embed.add_field(name="空方论点", value=view.bear_case[:1024], inline=True)
    embed.add_field(name="主要情景", value=view.primary_scenario[:1024], inline=False)
    embed.add_field(
        name="关键结构",
        value=(
            f"支撑 {_levels(view.key_support)}\n"
            f"压力 {_levels(view.key_resistance)}\n"
            f"向上触发 {_money(view.bullish_trigger)}\n"
            f"向下触发 {_money(view.bearish_trigger)}\n"
            f"失效 {_money(view.invalidation)}\n"
            f"目标 {_levels(view.targets)}"
        ),
        inline=False,
    )
    embed.add_field(name="主要风险", value=_bullets(view.risks), inline=False)
    coverage = sum(item.available for item in result.pack.components)
    updated = view.generated_at.astimezone(ET).strftime("%m/%d %H:%M ET")
    embed.add_field(
        name="数据与运行",
        value=(
            f"覆盖 {coverage}/5 · Coverage {view.coverage_score * 100:.0f}%\n"
            f"更新 {updated} · 缓存 {'命中' if result.cache_hit else '未命中'}\n"
            f"{result.latency_ms} ms · LLM {result.llm_calls} calls"
        ),
        inline=False,
    )
    if result.stock_chart_png is not None:
        embed.set_image(url=f"attachment://axis-research-{view.ticker.lower()}.png")
    embed.set_footer(text="模型辅助研究 · 仅供市场分析与教育，不构成投资建议")
    return embed


def progress_text(ticker: str, statuses: dict[str, str]) -> str:
    labels = (
        ("technical", "Technical"),
        ("gex", "GEX"),
        ("fundamentals", "Fundamentals"),
        ("news_macro", "News / Macro"),
        ("sentiment", "Sentiment"),
        ("bull_bear", "Bull / Bear"),
        ("manager", "Research Manager"),
        ("risk", "Risk Review"),
        ("synthesis", "Synthesis"),
    )
    icons = {
        "PENDING": "…",
        "RUNNING": "◌",
        "DONE": "✓",
        "UNAVAILABLE": "—",
        "FAILED": "✕",
    }
    rows = [f"{label:<18} {icons.get(statuses.get(key, 'PENDING'), '…')}" for key, label in labels]
    return "AXIS RESEARCH · TEST\n\n" + ticker + "\n\n```\n" + "\n".join(rows) + "\n```"


def detail_embed(result: ResearchRunResult, section: str) -> discord.Embed:
    component_names = {
        "technical": "technical",
        "gex": "gex",
        "fundamentals": "fundamentals",
        "news": "news_macro",
    }
    if section in component_names:
        component = result.pack.component(component_names[section])
        payload = component.to_dict() if component else {"status": "UNAVAILABLE"}
    elif section == "bull_bear":
        wanted = {LlmWorkload.RESEARCH_BULL.value, LlmWorkload.RESEARCH_BEAR.value}
        payload = {
            item.agent_type: item.structured_output
            for item in result.agent_outputs
            if item.agent_type in wanted
        }
    else:
        wanted = {
            LlmWorkload.RESEARCH_RISK_AGGRESSIVE.value,
            LlmWorkload.RESEARCH_RISK_NEUTRAL.value,
            LlmWorkload.RESEARCH_RISK_CONSERVATIVE.value,
        }
        payload = {
            item.agent_type: item.structured_output
            for item in result.agent_outputs
            if item.agent_type in wanted
        }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(text) > 3900:
        text = text[:3880] + "\n…"
    return discord.Embed(
        title=f"AXIS RESEARCH · {section.upper()} · {result.view.ticker}",
        description=f"```json\n{text}\n```",
        color=0x86F7A8,
    )
