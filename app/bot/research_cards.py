"""Mobile-readable Discord cards for AXIS Multi-Agent Research."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import discord

from app.domain.enums import LlmWorkload
from app.market_intelligence.research_engine.models import (
    AgentOutput,
    ResearchComponent,
    ResearchRunResult,
)

ET = ZoneInfo("America/New_York")
GREEN = 0x86F7A8
RED = 0xD66A6A
YELLOW = 0xD8C477
GRAY = 0x747C76

STANCE_LABELS = {
    "STRONGLY BULLISH": "强烈看多",
    "BULLISH": "看多",
    "NEUTRAL_TO_BULLISH": "中性偏多",
    "NEUTRAL → BULLISH": "中性偏多",
    "NEUTRAL": "中性",
    "NEUTRAL_TO_BEARISH": "中性偏空",
    "NEUTRAL → BEARISH": "中性偏空",
    "BEARISH": "看空",
    "STRONGLY BEARISH": "强烈看空",
    "POSITIVE": "正面",
    "NEGATIVE": "负面",
    "LOW": "低",
    "MEDIUM": "中等",
    "HIGH": "高",
    "VERY HIGH": "很高",
    "STOCK": "股票",
    "ETF": "ETF",
    "INDEX": "指数",
    "FUND": "基金",
}
STATUS_LABELS = {
    "AVAILABLE": "可用",
    "NOT_APPLICABLE": "不适用",
    "UNAVAILABLE": "暂不可用",
    "COMPLETED": "已完成",
    "CURRENT": "实时",
    "RECENT": "近期",
    "LATEST_AVAILABLE": "最近可用",
    "STALE": "数据偏旧",
}
ERROR_LABELS = {
    "MASSIVE_RESEARCH_PROVIDER_FAILED": "市场数据服务暂时不可用",
    "MASSIVE_RATE_LIMITED": "市场数据请求频率受限",
    "MASSIVE_ENTITLEMENT_REQUIRED": "当前数据套餐未开通此项内容",
    "MOOMOO_SDK_UNAVAILABLE": "Moomoo 数据组件暂时不可用",
    "MOOMOO_RESEARCH_PERMISSION_MISSING": "Moomoo 当前权限不包含此项数据",
    "MOOMOO_RESEARCH_FUNDAMENTALS_FAILED": "Moomoo 基本面数据暂时不可用",
    "MOOMOO_RESEARCH_SNAPSHOT_FAILED": "Moomoo 行情快照暂时不可用",
    "MOOMOO_RESEARCH_NEWS_FAILED": "Moomoo 新闻数据暂时不可用",
    "MOOMOO_RESEARCH_CONSENSUS_FAILED": "Moomoo 分析师共识暂时不可用",
    "RESEARCH_TECHNICAL_FAILURE": "技术面数据获取失败",
    "RESEARCH_GEX_FAILURE": "期权结构数据获取失败",
    "RESEARCH_FUNDAMENTALS_FAILURE": "基本面数据获取失败",
    "RESEARCH_NEWS_FAILURE": "新闻数据获取失败",
    "RESEARCH_SENTIMENT_FAILURE": "市场情绪数据不足",
    "RESEARCH_MIN_COVERAGE_FAILURE": "可用研究分项未达到最低要求",
    "FUNDAMENTALS_NOT_APPLICABLE": "该类标的不适用公司基本面分析",
    "NEWS_EMPTY": "近期没有可用新闻",
    "SENTIMENT_UNAVAILABLE": "暂无足够情绪样本",
    "STALE_DATA": "数据已超过实时阈值",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _money(value: Any) -> str:
    return f"${float(value):,.2f}" if _is_number(value) else "—"


def _compact_number(value: Any) -> str:
    if not _is_number(value):
        return "—"
    number = float(value)
    absolute = abs(number)
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= divisor:
            return f"{number / divisor:,.2f}{suffix}"
    return f"{number:,.2f}"


def _levels(values: Any, *, limit: int = 4) -> str:
    if not isinstance(values, (list, tuple)):
        return "—"
    rendered = [_money(value) for value in values[:limit] if _is_number(value)]
    return " / ".join(rendered) or "—"


def _clip(value: Any, limit: int = 1024) -> str:
    text = str(value or "—").strip() or "—"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _bullets(values: Any, *, limit: int = 4) -> str:
    if not isinstance(values, (list, tuple)):
        return "—"
    rows = [_clip(value, 240) for value in values[:limit] if str(value).strip()]
    return _clip("\n".join(f"• {row}" for row in rows)) if rows else "—"


def _error_bullets(values: Any, *, limit: int = 4) -> str:
    if not isinstance(values, (list, tuple)):
        return "—"
    labels = [ERROR_LABELS.get(str(code), "相关数据暂时不可用") for code in values[:limit]]
    return _bullets(tuple(dict.fromkeys(labels)), limit=limit)


def _label(value: Any) -> str:
    text = str(value or "—")
    return STANCE_LABELS.get(text.upper(), STATUS_LABELS.get(text.upper(), text))


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(ET).strftime("%m/%d %H:%M ET")


def _warning_text(component: ResearchComponent) -> str:
    codes = list(component.warnings)
    if component.error_type and component.error_type not in codes:
        codes.insert(0, component.error_type)
    labels = [ERROR_LABELS.get(code, "相关数据暂时不可用") for code in codes]
    return _bullets(labels) if labels else "数据源暂时没有返回可用内容。"


def _component_embed(
    result: ResearchRunResult,
    component: ResearchComponent | None,
    *,
    title: str,
) -> discord.Embed:
    available = component is not None and component.available
    status = _label(component.status) if component is not None else "暂不可用"
    color = (
        GREEN
        if available
        else YELLOW
        if component and component.status == "NOT_APPLICABLE"
        else RED
    )
    embed = discord.Embed(
        title=f"AXIS 研究详情 · {title} · {result.view.ticker}",
        description=f"**数据状态：{status}**",
        color=color,
    )
    if component is not None:
        embed.set_footer(
            text=(
                f"数据源 {component.provider} · 更新 {_timestamp(component.source_timestamp)} · "
                f"新鲜度 {_label(component.freshness)} · 覆盖 {component.coverage * 100:.0f}%"
            )
        )
    else:
        embed.set_footer(text="仅供市场研究与教育，不构成投资建议")
    return embed


def _component_unavailable(embed: discord.Embed, component: ResearchComponent | None) -> bool:
    if component is not None and component.available:
        return False
    if component is not None and component.status == "NOT_APPLICABLE":
        embed.add_field(name="说明", value=_warning_text(component), inline=False)
    else:
        embed.add_field(
            name="暂未取得数据",
            value=_warning_text(component) if component is not None else "该研究分项没有返回结果。",
            inline=False,
        )
    return True


def build_research_embed(result: ResearchRunResult) -> discord.Embed:
    view = result.view
    if view.insufficient_data:
        embed = discord.Embed(
            title=f"AXIS 多智能体研究 · {view.ticker}",
            description="**数据覆盖不足，暂不生成研究倾向**",
            color=RED,
        )
        embed.add_field(
            name="数据覆盖",
            value=f"{sum(item.available for item in result.pack.components)} / 5 个分项可用",
            inline=True,
        )
        embed.add_field(name="原因", value=_error_bullets(view.warnings), inline=False)
        embed.set_footer(text="仅供市场研究与教育，不构成投资建议")
        return embed
    stance_color = (
        GREEN
        if "BULLISH" in str(view.research_stance)
        else RED
        if "BEARISH" in str(view.research_stance)
        else YELLOW
    )
    embed = discord.Embed(
        title=f"AXIS 多智能体研究 · {view.ticker}",
        description="**会员专属多智能体市场研究**",
        color=stance_color,
    )
    embed.add_field(name="研究倾向", value=_label(view.research_stance), inline=True)
    embed.add_field(name="研究置信度", value=f"{view.research_confidence}%", inline=True)
    embed.add_field(name="现价", value=_money(view.price), inline=True)
    embed.add_field(name="市场结构", value=_clip(view.market_structure, 600), inline=False)
    embed.add_field(name="期权结构 / GEX", value=_clip(view.gamma_context, 600), inline=False)
    embed.add_field(name="多方观点", value=_clip(view.bull_case, 500), inline=True)
    embed.add_field(name="空方观点", value=_clip(view.bear_case, 500), inline=True)
    embed.add_field(name="主要情景", value=_clip(view.primary_scenario, 500), inline=False)
    embed.add_field(
        name="关键价位",
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
    embed.add_field(name="主要风险", value=_clip(_bullets(view.risks), 700), inline=False)
    coverage = sum(item.available for item in result.pack.components)
    updated = view.generated_at.astimezone(ET).strftime("%m/%d %H:%M ET")
    embed.add_field(
        name="数据与运行",
        value=(
            f"可用分项 {coverage}/5 · 加权覆盖率 {view.coverage_score * 100:.0f}%\n"
            f"更新 {updated} · 缓存 {'已命中' if result.cache_hit else '未命中'}\n"
            f"耗时 {result.latency_ms} 毫秒 · 模型调用 {result.llm_calls} 次"
        ),
        inline=False,
    )
    if result.stock_chart_png is not None:
        embed.set_image(url=f"attachment://axis-research-{view.ticker.lower()}.png")
    embed.set_footer(text="点击下方按钮查看分项依据 · 仅供研究与教育，不构成投资建议")
    return embed


def progress_text(ticker: str, statuses: dict[str, str]) -> str:
    labels = (
        ("technical", "技术面"),
        ("gex", "期权结构"),
        ("fundamentals", "基本面"),
        ("news_macro", "新闻与宏观"),
        ("sentiment", "市场情绪"),
        ("bull_bear", "多空观点"),
        ("manager", "研究统筹"),
        ("risk", "风险评估"),
        ("synthesis", "综合结论"),
    )
    icons = {
        "PENDING": "…",
        "RUNNING": "◌",
        "DONE": "✓",
        "UNAVAILABLE": "—",
        "FAILED": "✕",
    }
    rows = [f"{label:<10} {icons.get(statuses.get(key, 'PENDING'), '…')}" for key, label in labels]
    return "AXIS 多智能体研究\n\n" + ticker + "\n\n```\n" + "\n".join(rows) + "\n```"


def _technical_embed(result: ResearchRunResult) -> discord.Embed:
    component = result.pack.component("technical")
    embed = _component_embed(result, component, title="技术面")
    if _component_unavailable(embed, component):
        return embed
    assert component is not None
    data = component.data
    score = data.get("bias_score")
    score_text = f" · {float(score):.1f}/100" if _is_number(score) else ""
    embed.add_field(
        name="市场概览",
        value=(
            f"现价 {_money(data.get('price'))}\n"
            f"结构 {_clip(data.get('market_structure'), 200)}\n"
            f"倾向 {_label(data.get('bias'))}{score_text}"
        ),
        inline=False,
    )
    embed.add_field(name="关键支撑", value=_levels(data.get("support_levels")), inline=True)
    embed.add_field(name="关键压力", value=_levels(data.get("resistance_levels")), inline=True)
    embed.add_field(
        name="成交密集区",
        value=(
            f"POC {_money(data.get('poc'))}\n"
            f"VAH {_money(data.get('vah'))}\n"
            f"VAL {_money(data.get('val'))}"
        ),
        inline=True,
    )
    indicators = data.get("indicator_summary")
    if isinstance(indicators, dict):
        rows = [
            f"{str(name).replace('_', ' ')}  {float(value):.1f}"
            for name, value in list(indicators.items())[:6]
            if _is_number(value)
        ]
        if rows:
            embed.add_field(name="技术指标", value="\n".join(rows), inline=False)
    embed.add_field(
        name="主要情景",
        value=(
            f"{_clip(data.get('top_scenario'), 300)}\n"
            f"情景权重 {_compact_number(data.get('scenario_weight'))}%"
        ),
        inline=False,
    )
    embed.add_field(
        name="触发与失效",
        value=(
            f"看多：{_clip(data.get('bullish_trigger'), 300)}\n"
            f"看空：{_clip(data.get('bearish_trigger'), 300)}\n"
            f"失效：{_money(data.get('invalidation'))}\n"
            f"目标：{_levels(data.get('targets'))}"
        ),
        inline=False,
    )
    if result.stock_chart_png is not None:
        embed.set_image(
            url=f"attachment://axis-research-technical-{result.view.ticker.lower()}.png"
        )
    return embed


def _gex_embed(result: ResearchRunResult) -> discord.Embed:
    component = result.pack.component("gex")
    embed = _component_embed(result, component, title="期权结构")
    if _component_unavailable(embed, component):
        return embed
    assert component is not None
    data = component.data
    embed.add_field(
        name="Gamma 概览",
        value=(
            f"现价 {_money(data.get('spot'))}\n"
            f"Gamma 环境 {_label(data.get('gamma_regime'))}\n"
            f"当前倾向 {_label(data.get('current_bias'))}\n"
            f"净 GEX {_compact_number(data.get('net_gex'))}"
        ),
        inline=False,
    )
    embed.add_field(
        name="核心节点",
        value=(
            f"Gamma 磁吸 {_money(data.get('gamma_magnet'))}\n"
            f"Gamma Flip {_money(data.get('gamma_flip'))}\n"
            f"Call Wall {_money(data.get('call_wall'))}\n"
            f"Put Wall {_money(data.get('put_wall'))}"
        ),
        inline=True,
    )
    embed.add_field(
        name="支撑与压力",
        value=(
            f"主要支撑 {_levels(data.get('major_support'))}\n"
            f"次要支撑 {_levels(data.get('minor_support'))}\n"
            f"主要压力 {_levels(data.get('major_resistance'))}\n"
            f"次要压力 {_levels(data.get('minor_resistance'))}"
        ),
        inline=True,
    )
    embed.add_field(
        name="结构触发",
        value=(
            f"向上 {_money(data.get('bullish_trigger'))}\n"
            f"向下 {_money(data.get('bearish_trigger'))}"
        ),
        inline=False,
    )
    if data.get("near_term_expiration"):
        embed.add_field(
            name="近期期限",
            value=(
                f"到期日 {data['near_term_expiration']}\n"
                f"净 GEX {_compact_number(data.get('near_term_net_gex'))}\n"
                f"环境 {_label(data.get('near_term_regime'))}"
            ),
            inline=False,
        )
    if result.gex_chart_png is not None:
        embed.set_image(url=f"attachment://axis-research-gex-{result.view.ticker.lower()}.png")
    return embed


def _metric_value(name: str, metric: Any) -> str:
    value = metric.get("value") if isinstance(metric, dict) else metric
    if not _is_number(value):
        return "—"
    if name == "revenue_growth":
        return f"{float(value) * 100:.1f}%"
    if name in {"eps", "price_to_earnings", "price_to_sales", "debt_to_equity"}:
        return f"{float(value):,.2f}"
    return _compact_number(value)


def _fundamentals_embed(result: ResearchRunResult) -> discord.Embed:
    component = result.pack.component("fundamentals")
    embed = _component_embed(result, component, title="基本面")
    if _component_unavailable(embed, component):
        return embed
    assert component is not None
    data = component.data
    company = data.get("company_name") or result.view.ticker
    embed.add_field(
        name="公司概览",
        value=f"{_clip(company, 300)}\n资产类型 {_label(data.get('asset_type'))}",
        inline=False,
    )
    metric_names = {
        "revenue": "营收",
        "revenue_growth": "营收增长",
        "gross_profit": "毛利润",
        "operating_income": "营业利润",
        "net_income": "净利润",
        "eps": "稀释每股收益",
        "price_to_earnings": "市盈率",
        "price_to_sales": "市销率",
        "debt_to_equity": "负债权益比",
        "free_cash_flow": "自由现金流",
        "cash_and_equivalents": "现金及等价物",
        "operating_cash_flow": "经营现金流",
        "total_assets": "总资产",
        "total_liabilities": "总负债",
    }
    metrics = data.get("metrics")
    rows = []
    if isinstance(metrics, dict):
        rows = [
            f"{metric_names.get(name, name.replace('_', ' '))}  {_metric_value(name, metric)}"
            for name, metric in metrics.items()
        ]
    embed.add_field(name="关键指标", value=_clip("\n".join(rows) if rows else "—"), inline=False)
    embed.add_field(
        name="研究解读",
        value=_clip(result.view.fundamental_context, 700),
        inline=False,
    )
    return embed


def _escape_markdown_link_title(value: Any) -> str:
    return str(value or "未命名新闻").replace("[", "［").replace("]", "］")


def _news_embed(result: ResearchRunResult) -> discord.Embed:
    component = result.pack.component("news_macro")
    embed = _component_embed(result, component, title="新闻动态")
    if _component_unavailable(embed, component):
        return embed
    assert component is not None
    embed.add_field(name="新闻综述", value=_clip(result.view.news_context, 700), inline=False)
    consensus = result.pack.component("sentiment")
    if consensus is not None and consensus.available:
        consensus_data = consensus.data
        embed.add_field(
            name="分析师共识",
            value=(
                f"评级 {_label(consensus_data.get('rating'))} · "
                f"样本 {int(consensus_data.get('sample_size') or 0)}\n"
                f"买入 {_compact_number(consensus_data.get('buy'))}% · "
                f"持有 {_compact_number(consensus_data.get('hold'))}% · "
                f"卖出 {_compact_number(consensus_data.get('sell'))}%\n"
                f"目标区间 {_money(consensus_data.get('target_low'))} / "
                f"{_money(consensus_data.get('target_average'))} / "
                f"{_money(consensus_data.get('target_high'))}"
            ),
            inline=False,
        )
    embed.add_field(
        name="观点解读", value=_clip(result.view.sentiment_context, 450), inline=False
    )
    items = component.data.get("items")
    if isinstance(items, list):
        for index, item in enumerate(items[:4], start=1):
            if not isinstance(item, dict):
                continue
            title = _escape_markdown_link_title(item.get("title"))
            url = str(item.get("article_url") or "")
            heading = f"[{title}]({url})" if url.startswith(("https://", "http://")) else title
            publisher = item.get("publisher") or "来源未标注"
            published = str(item.get("published_utc") or "")[:16].replace("T", " ")
            description = _clip(item.get("description"), 700)
            embed.add_field(
                name=f"新闻 {index}",
                value=_clip(f"{heading}\n{publisher} · {published}\n{description}", 800),
                inline=False,
            )
    return embed


def _agent(result: ResearchRunResult, workload: LlmWorkload) -> AgentOutput | None:
    return next(
        (item for item in result.agent_outputs if item.agent_type == workload.value),
        None,
    )


def _case_text(output: AgentOutput | None, fallback: str) -> str:
    if output is None or output.status != "COMPLETED":
        return _clip(fallback)
    data = output.structured_output
    parts = [_clip(data.get("thesis") or fallback, 450)]
    evidence = _bullets(data.get("supporting_evidence"), limit=3)
    if evidence != "—":
        parts.append(f"\n**主要依据**\n{evidence}")
    risks = _bullets(data.get("case_risks"), limit=2)
    if risks != "—":
        parts.append(f"\n**需要留意**\n{risks}")
    parts.append(f"\n信心等级：{_label(data.get('confidence_label'))}")
    return _clip("\n".join(parts))


def _bull_bear_embed(result: ResearchRunResult) -> discord.Embed:
    embed = discord.Embed(
        title=f"AXIS 研究详情 · 多空观点 · {result.view.ticker}",
        description=(
            f"**综合倾向：{_label(result.view.research_stance)} · "
            f"置信度 {result.view.research_confidence}%**"
        ),
        color=YELLOW,
    )
    embed.add_field(
        name="多方观点",
        value=_case_text(_agent(result, LlmWorkload.RESEARCH_BULL), result.view.bull_case),
        inline=False,
    )
    embed.add_field(
        name="空方观点",
        value=_case_text(_agent(result, LlmWorkload.RESEARCH_BEAR), result.view.bear_case),
        inline=False,
    )
    embed.add_field(name="主要情景", value=_clip(result.view.primary_scenario), inline=False)
    embed.add_field(name="备选情景", value=_clip(result.view.alternate_scenario), inline=False)
    embed.set_footer(text="多空观点基于同一冻结数据包 · 仅供研究与教育")
    return embed


def _risk_embed(result: ResearchRunResult) -> discord.Embed:
    embed = discord.Embed(
        title=f"AXIS 研究详情 · 风险评估 · {result.view.ticker}",
        description="**从积极、中性与保守三种风险视角交叉检查**",
        color=RED,
    )
    embed.add_field(name="综合主要风险", value=_bullets(result.view.risks, limit=6), inline=False)
    perspectives = (
        (LlmWorkload.RESEARCH_RISK_AGGRESSIVE, "积极视角"),
        (LlmWorkload.RESEARCH_RISK_NEUTRAL, "中性视角"),
        (LlmWorkload.RESEARCH_RISK_CONSERVATIVE, "保守视角"),
    )
    for workload, name in perspectives:
        output = _agent(result, workload)
        if output is None or output.status != "COMPLETED":
            value = "该视角暂未返回结果。"
        else:
            data = output.structured_output
            value = (
                f"风险等级：{_label(data.get('risk_level'))}\n"
                f"{_bullets(data.get('key_risks'), limit=3)}\n"
                f"**观点改变条件**\n{_bullets(data.get('what_would_change_view'), limit=2)}"
            )
        embed.add_field(name=name, value=_clip(value), inline=False)
    embed.add_field(name="备选情景", value=_clip(result.view.alternate_scenario), inline=False)
    embed.set_footer(text="风险评估不构成交易建议")
    return embed


def detail_embed(result: ResearchRunResult, section: str) -> discord.Embed:
    builders = {
        "technical": _technical_embed,
        "gex": _gex_embed,
        "fundamentals": _fundamentals_embed,
        "news": _news_embed,
        "bull_bear": _bull_bear_embed,
        "risk": _risk_embed,
    }
    builder = builders.get(section)
    if builder is None:
        return discord.Embed(
            title=f"AXIS 研究详情 · {result.view.ticker}",
            description="暂未找到该研究分项。",
            color=GRAY,
        )
    return builder(result)
